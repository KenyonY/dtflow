"""
数据原语 (库层): filter / select / map / explode / sort / shuffle / group / join。

每个函数把一步操作挂到 StreamingTransformer 上 (能惰性的都惰性), CLI (cli/ops.py) 与
pipeline 共用同一份实现。表达式一律是 Python (见 dtflow.expr), 当前行为 x。
只抛 ValueError / ExprSyntaxError, 不 import 任何 CLI 层的东西。
"""

from __future__ import annotations

import itertools
import random as _random
import statistics
from collections import Counter, OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .core import DictWrapper, ListWrapper, unwrap
from .expr import compile_in, compile_map, compile_value, compile_where
from .i18n import t
from .streaming import StreamingTransformer
from .utils.field_path import get_field_with_spec

Row = Dict[str, Any]


def _on_error(strict: bool) -> str:
    return "raise" if strict else "skip"


# --------------------------------------------------------------------------- #
# SPEC 解析: "id,text,n=len(x.messages),src=x.meta.source"
# --------------------------------------------------------------------------- #
def parse_spec(spec: str) -> List[Tuple[str, Optional[str]]]:
    """按深度 0 的逗号切分 (括号/引号内的逗号不算), 每项 → (name, expr 或 None)。

    ``a`` → ("a", None): 字面顶层字段名, 不解析 (含 - 或空格的键也能选);
    ``n=len(x.m)`` → ("n", "len(x.m)")。
    """
    items: List[str] = []
    depth = 0
    quote: Optional[str] = None
    buf: List[str] = []
    for ch in spec:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    items.append("".join(buf))

    out: List[Tuple[str, Optional[str]]] = []
    for raw in items:
        item = raw.strip()
        if not item:
            continue
        name, eq, expr = item.partition("=")
        # 只有 "name=expr" 形态的 = 算赋值; "a==b" 这种会被上面切成 name="a", expr="=b" → 拒绝
        if eq and (not expr or expr.startswith("=")):
            raise ValueError(
                t(
                    f"Cannot parse: {item!r} (expected name=expr or a field name)",
                    f"无法解析: {item!r} (形如 name=表达式 或 字段名)",
                )
            )
        name = name.strip()
        if not name.isidentifier() and eq:
            raise ValueError(
                t(
                    f"Derived field name must be a valid identifier: {name!r}",
                    f"派生字段名必须是合法标识符: {name!r}",
                )
            )
        out.append((name, expr.strip() if eq else None))
    if not out:
        raise ValueError(t("SPEC is empty", "SPEC 为空"))
    return out


# --------------------------------------------------------------------------- #
# 逐行原语
# --------------------------------------------------------------------------- #
def filter_rows(st: StreamingTransformer, expr: str, strict: bool = False) -> StreamingTransformer:
    """保留 expr 为真的行。求值失败的行: 默认跳过并计数, strict 则抛出。"""
    return st.filter(compile_where(expr), raw=True, on_error=_on_error(strict))


def map_rows(st: StreamingTransformer, code: str, strict: bool = False) -> StreamingTransformer:
    """对每行执行语句 (原地改 x), 如 ``x.text = x.text.strip(); del x.debug``。

    map 是一进一出: 语句失败的行**原样透传**并计数 (不像 filter 那样丢行), strict 则抛出。
    """
    fn = compile_map(code)
    new = st.transform(lambda r: r, raw=True, on_error="raise")
    err = new._err  # 闭包只捕获计数对象, 不捕获 new (避免引用环)

    def apply(row: Row) -> Row:
        try:
            return fn(row)
        except Exception as e:
            if strict:
                raise
            err.count += 1
            if err.first is None:
                err.first = t(
                    f"{type(e).__name__}: {e} (row kept as is)",
                    f"{type(e).__name__}: {e} (该行原样保留)",
                )
            return row

    new._iterator = map(apply, st)
    return new


def select_rows(st: StreamingTransformer, spec: str, strict: bool = False) -> StreamingTransformer:
    """投影 + 重命名 + 派生: ``id,text,n=len(x.messages),src=x.meta.source``。

    字面字段缺失时省略该键 (不报错, 异构数据是常态); 派生表达式失败按 strict 处理。
    输出键序 = SPEC 序。
    """
    plan = [(name, compile_value(expr) if expr else None) for name, expr in parse_spec(spec)]
    new = st.transform(lambda r: r, raw=True, on_error="raise")
    err = new._err

    def project(row: Row) -> Row:
        # 一进一出: 派生项求值失败置 None 并计数, 不丢整行; strict 则抛出
        out: Row = OrderedDict()
        for name, fn in plan:
            if fn is None:
                if name in row:
                    out[name] = row[name]
                continue
            try:
                out[name] = fn(row)
            except Exception as e:
                if strict:
                    raise
                err.count += 1
                if err.first is None:
                    err.first = t(
                        f"{name}: {type(e).__name__}: {e} (set to null)",
                        f"{name}: {type(e).__name__}: {e} (该项置 null)",
                    )
                out[name] = None
        return dict(out)

    new._iterator = map(project, st)
    return new


def explode_rows(
    st: StreamingTransformer,
    field: str,
    as_name: Optional[str] = None,
    index_as: Optional[str] = None,
) -> StreamingTransformer:
    """list 字段展开为多行, 其余字段复制。非 list / 缺失的行原样透传。"""
    target = as_name or field

    def blow(row: Row) -> Iterable[Row]:
        values = row.get(field)
        if not isinstance(values, list):
            return (row,)
        out = []
        for i, v in enumerate(values):
            new = dict(row)
            if target != field:
                del new[field]
            new[target] = v
            if index_as:
                new[index_as] = i
            out.append(new)
        return out

    return st.flat_map(blow, raw=True)


# --------------------------------------------------------------------------- #
# 需要全量的原语
# --------------------------------------------------------------------------- #
def _materialize(st: StreamingTransformer, rows: List[Row]) -> StreamingTransformer:
    new = StreamingTransformer(iter(rows), st._source_path, total=len(rows))
    new._error_count, new._first_error = st._error_count, st._first_error
    return new


def sort_rows(
    st: StreamingTransformer, by: str, desc: bool = False, strict: bool = False
) -> StreamingTransformer:
    """按表达式排序 (稳定)。键求值失败的行排最后; 键类型混杂无法比较时抛 ValueError。"""
    keyfn = compile_value(by)
    rows = st.collect()
    keyed: List[Tuple[int, Any, Row]] = []
    failed = 0
    for row in rows:
        try:
            keyed.append((0, keyfn(row), row))
        except Exception:
            if strict:
                raise  # 运行时数据错误原样抛出 (退出码 1), ValueError 留给用法错误
            failed += 1
            keyed.append((1, None, row))
    ok = [k for k in keyed if k[0] == 0]
    bad = [k for k in keyed if k[0] == 1]
    try:
        ok.sort(key=lambda k: k[1], reverse=desc)
    except TypeError as e:
        raise ValueError(
            t(
                f"Sort keys have mixed types and cannot be compared ({e}); "
                f"normalize with str(...) or float(...)",
                f"排序键类型不一致, 无法比较 ({e}); 用 str(...) 或 float(...) 统一",
            )
        ) from e
    new = _materialize(st, [k[2] for k in ok] + [k[2] for k in bad])
    if failed:
        new._error_count += failed
        new._first_error = new._first_error or t(
            "Sort key evaluation failed (placed last)", "排序键求值失败 (已排在末尾)"
        )
    return new


def shuffle_rows(st: StreamingTransformer, seed: Optional[int] = None) -> StreamingTransformer:
    """全量打乱。流式做不到: 均匀随机排列必须先知道全集。"""
    rows = st.collect()
    _random.Random(seed).shuffle(rows)
    return _materialize(st, rows)


def _hashable(v: Any) -> Any:
    if isinstance(v, list):
        return tuple(_hashable(x) for x in v)
    if isinstance(v, dict):
        return tuple((k, _hashable(x)) for k, x in v.items())
    return v


_AGG_NS = {"mean": statistics.mean, "median": statistics.median}
_AGG_ALLOWED = frozenset({"g", "key", "n", "mean", "median"})


def group_rows(
    st: StreamingTransformer,
    by: str,
    agg: Optional[str] = None,
    strict: bool = False,
    top: Optional[int] = None,
) -> StreamingTransformer:
    """按表达式分组。

    无 agg: 流式计数, 输出 {"key", "count", "pct"} 按 count 降序 (pct 以全部输入行为分母,
    键求值失败的行也在分母里, 所以各组 pct 之和可能不到 1, 差额即 stderr 汇总的失败数)。
    有 agg (``n=len(g),avg=mean(len(r.text) for r in g)``): 按组收集行, 每个表达式可用
    ``g`` (该组行列表)、``key``、``n``、``mean``/``median``。
    top: 只保留前 N 组 (计数模式按 count, agg 模式按 n)。
    """
    keyfn = compile_value(by)
    if agg is None:
        counter: Counter = Counter()
        keys: Dict[Any, Any] = {}
        failed = 0
        seen = 0
        first_err = None
        for row in st:
            seen += 1
            try:
                k = keyfn(row)
            except Exception as e:
                if strict:
                    raise
                failed += 1
                first_err = first_err or f"{type(e).__name__}: {e}"
                continue
            hk = _hashable(k)
            keys.setdefault(hk, k)
            counter[hk] += 1
        rows = [
            {"key": keys[hk], "count": n, "pct": round(n / seen, 4)}
            for hk, n in counter.most_common(top)
        ]
        new = _materialize(st, rows)
        new._error_count += failed
        new._first_error = new._first_error or first_err
        return new

    for name, expr in parse_spec(agg):
        if expr is None:
            raise ValueError(
                t(
                    f"Each --agg item must be name=expr, got {name!r}",
                    f"--agg 每项都要是 name=表达式, 得到 {name!r}",
                )
            )
    plan = [(name, compile_in(expr, _AGG_ALLOWED)) for name, expr in parse_spec(agg)]
    groups: Dict[Any, List[Row]] = OrderedDict()
    keys = {}
    failed = 0
    first_err = None
    for row in st:
        try:
            k = keyfn(row)
        except Exception as e:
            if strict:
                raise
            failed += 1
            first_err = first_err or f"{type(e).__name__}: {e}"
            continue
        hk = _hashable(k)
        keys.setdefault(hk, k)
        groups.setdefault(hk, []).append(row)
    out: List[Row] = []
    if top is not None:
        groups = OrderedDict(sorted(groups.items(), key=lambda kv: -len(kv[1]))[:top])
    for hk, members in groups.items():
        ns = {**_AGG_NS, "g": ListWrapper(members), "key": keys[hk], "n": len(members)}
        rec: Row = {"key": keys[hk], "n": len(members)}
        for name, fn in plan:
            try:
                rec[name] = unwrap(fn(ns))
            except Exception as e:
                if strict:
                    raise
                failed += 1
                first_err = first_err or t(
                    f"aggregate {name}: {type(e).__name__}: {e} (set to null)",
                    f"聚合 {name}: {type(e).__name__}: {e} (该项置 null)",
                )
                rec[name] = None
        out.append(rec)
    new = _materialize(st, out)
    new._error_count += failed
    new._first_error = new._first_error or first_err
    return new


def join_rows(
    st: StreamingTransformer,
    right: Iterable[Row],
    on: Optional[str] = None,
    left_on: Optional[str] = None,
    right_on: Optional[str] = None,
    inner: bool = False,
    prefix: Optional[str] = None,
    *,
    anti: bool = False,
    strict: bool = False,
) -> Tuple[StreamingTransformer, int]:
    """左表流式、右表入内存的键连接。返回 (结果流, 右表重复键数)。

    默认左连接 (未命中的左行原样透传), inner 则丢弃, anti 则**只留未命中的左行**
    (去测试集污染 / 找还没处理的样本就是它)。合并时左表字段优先; 给 prefix 则右表全部字段
    加前缀 (可预期, 不做"只对冲突字段加前缀"这种看数据才知道的规则)。
    右表同键多行只取首条 (一对多留待后续)。
    左表键求值失败的行按"未命中"处理并计数 (stderr 汇总, 与 filter 一致), strict 则抛出。
    """
    if inner and anti:
        raise ValueError(
            t("--inner and --anti are mutually exclusive", "--inner 与 --anti 只能二选一")
        )
    lkey = compile_value(left_on or on or "")
    rkey = compile_value(right_on or on or "")
    index: Dict[Any, Row] = {}
    dup = 0
    for row in right:
        hk = _hashable(rkey(row))
        if hk in index:
            dup += 1
            continue
        index[hk] = row

    new = st.transform(lambda r: r, raw=True, on_error="raise")
    err = new._err  # 闭包只捕获计数对象 (见 map_rows)

    def merge(row: Row) -> Iterable[Row]:
        try:
            match = index.get(_hashable(lkey(row)))
        except Exception as e:
            if strict:
                raise
            err.count += 1
            if err.first is None:
                err.first = t(
                    f"left key {type(e).__name__}: {e} (row treated as unmatched)",
                    f"左表键 {type(e).__name__}: {e} (该行按未命中处理)",
                )
            match = None
        if match is None:
            return () if inner else (row,)
        if anti:
            return ()
        out = dict(row)
        for k, v in match.items():
            if prefix:
                out[prefix + k] = v
            else:
                out.setdefault(k, v)
        return (out,)

    new._iterator = itertools.chain.from_iterable(map(merge, st))
    return new, dup


# --------------------------------------------------------------------------- #
# clean: 声明式的批量卫生 (CLI dt clean 与 pipeline clean 步骤共用)
# --------------------------------------------------------------------------- #
def _is_empty_value(v: Any) -> bool:
    """None / 空白字符串 / 空 list / 空 dict 视为空"""
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    if isinstance(v, (list, dict)) and len(v) == 0:
        return True
    return False


def _get_value_len(value: Any) -> int:
    """str/list/dict 取 len; 数值直接当长度 (messages.# 这类); None 为 0"""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, (str, list, dict)):
        return len(value)
    return len(str(value))


def parse_pairs(spec: str, option: str, need_value: bool = False) -> Dict[str, str]:
    """``"a:b,c:d"`` → ``{"a": "b", "c": "d"}``。CLI 的 --rename/--add-field/--fill 与 pipeline
    的同名参数共用这一个解析, 行为不会漂移。同一个 key 出现两次报错 (否则静默取后者);
    need_value: 冒号后不能为空 (rename 的新名)。option 原样出现在报错里 (CLI 传 ``--rename``,
    pipeline 传 YAML 键名 ``fill``), 用户一眼知道是哪一项。"""
    out: Dict[str, str] = {}
    for pair in str(spec).split(","):
        pair = pair.strip()
        key, sep, value = pair.partition(":")
        key, value = key.strip(), value.strip()
        if not sep:
            raise ValueError(
                t(
                    f"Invalid {option} spec: {pair!r}, expected 'key:value'",
                    f"{option} 参数格式错误: {pair!r}，应为 'key:value'",
                )
            )
        if not key or (need_value and not value):
            raise ValueError(
                t(
                    f"Invalid {option} spec: {pair!r}, names must not be empty",
                    f"{option} 参数格式错误: {pair!r}，名字不能为空",
                )
            )
        if key in out:
            raise ValueError(
                t(
                    f"Invalid {option} spec: {key!r} appears twice",
                    f"{option} 参数格式错误: {key!r} 出现了两次",
                )
            )
        out[key] = value
    return out


def _rename_item(item: Row, rename_map: Dict[str, str]) -> Row:
    """重命名字段, 保持字段顺序。

    改完键数变少即两个字段落到同一名字 (目标名已是该行未被改走的字段, 或多对一), 报错而不是
    静默覆盖丢数据; 交换 (a:b,b:a) 与链式 (b:c,a:b) 键数不变, 照常。
    """
    out = {rename_map.get(k, k): v for k, v in item.items()}
    if len(out) != len(item):
        clash = sorted(k for k in out if sum(1 for j in item if rename_map.get(j, j) == k) > 1)
        raise ValueError(
            t(
                f"rename would merge several fields into {clash} and lose data",
                f"重命名会把多个字段并成 {clash}, 丢数据",
            )
        )
    return out


def _promote_fields(item: Row, promote_list: List[tuple]) -> Row:
    """提升嵌套字段到顶层（始终添加字段，即使值为 None）"""
    item = dict(item)
    for src_path, dst_name in promote_list:
        item[dst_name] = get_field_with_spec(item, src_path)
    return item


def _add_fields(item: Row, add_field_map: Dict[str, str]) -> Row:
    item = dict(item)
    item.update(add_field_map)
    return item


def _fill_empty(item: Row, fill_map: Dict[str, str]) -> Row:
    """填充空值（字段不存在时也会添加）"""
    item = dict(item)
    for field, default in fill_map.items():
        if field not in item or _is_empty_value(item[field]):
            item[field] = default
    return item


def _reorder_item(item: Row, reorder_fields: List[str]) -> Row:
    """按指定顺序重排字段，未列出的字段追加在后面"""
    ordered = {}
    for f in reorder_fields:
        if f in item:
            ordered[f] = item[f]
    for k, v in item.items():
        if k not in ordered:
            ordered[k] = v
    return ordered


def clean_rows(
    st: StreamingTransformer,
    strip: bool = False,
    empty_fields: Optional[List[str]] = None,
    min_len_field: Optional[str] = None,
    min_len_value: Optional[int] = None,
    max_len_field: Optional[str] = None,
    max_len_value: Optional[int] = None,
    keep_set: Optional[set] = None,
    drop_fields_set: Optional[set] = None,
    rename_map: Optional[Dict[str, str]] = None,
    promote_list: Optional[List[tuple]] = None,
    add_field_map: Optional[Dict[str, str]] = None,
    fill_map: Optional[Dict[str, str]] = None,
    reorder_fields: Optional[List[str]] = None,
    min_tokens_field: Optional[str] = None,
    min_tokens_value: Optional[int] = None,
    max_tokens_field: Optional[str] = None,
    max_tokens_value: Optional[int] = None,
    token_model: str = "cl100k_base",
) -> StreamingTransformer:
    """把清洗步骤按固定顺序挂到数据流上 (惰性):
    strip → 过滤 (空值/长度/token) → promote → keep/drop → rename → add → fill → reorder。
    """
    _count_tokens = None
    if min_tokens_field is not None or max_tokens_field is not None:
        from .tokenizers import count_tokens as _count_tokens

    def clean_filter(item: Row) -> bool:
        if empty_fields is not None:
            if len(empty_fields) == 0:
                if any(_is_empty_value(v) for v in item.values()):
                    return False
            elif any(_is_empty_value(get_field_with_spec(item, f)) for f in empty_fields):
                return False
        if min_len_field is not None:
            if _get_value_len(get_field_with_spec(item, min_len_field, default="")) < min_len_value:
                return False
        if max_len_field is not None:
            if _get_value_len(get_field_with_spec(item, max_len_field, default="")) > max_len_value:
                return False
        if min_tokens_field is not None:
            value = get_field_with_spec(item, min_tokens_field, default="")
            if _count_tokens(str(value), model=token_model) < min_tokens_value:
                return False
        if max_tokens_field is not None:
            value = get_field_with_spec(item, max_tokens_field, default="")
            if _count_tokens(str(value), model=token_model) > max_tokens_value:
                return False
        return True

    # strip 先做, 空值检测才准
    if strip:
        st = st.transform(
            lambda x: {k: v.strip() if isinstance(v, str) else v for k, v in x.items()}, raw=True
        )
    if (
        empty_fields is not None
        or min_len_field is not None
        or max_len_field is not None
        or min_tokens_field is not None
        or max_tokens_field is not None
    ):
        st = st.filter(clean_filter, raw=True)
    # promote 在 drop 之前, 否则父字段被删后无法提取
    if promote_list is not None:
        st = st.transform(lambda item: _promote_fields(item, promote_list), raw=True)
    if keep_set is not None:
        st = st.transform(lambda item: {k: v for k, v in item.items() if k in keep_set}, raw=True)
    elif drop_fields_set is not None:
        st = st.transform(
            lambda item: {k: v for k, v in item.items() if k not in drop_fields_set}, raw=True
        )
    if rename_map is not None:
        st = st.transform(lambda item: _rename_item(item, rename_map), raw=True, on_error="raise")
    if add_field_map is not None:
        st = st.transform(lambda item: _add_fields(item, add_field_map), raw=True)
    if fill_map is not None:
        st = st.transform(lambda item: _fill_empty(item, fill_map), raw=True)
    if reorder_fields is not None:
        st = st.transform(lambda item: _reorder_item(item, reorder_fields), raw=True)
    return st


# --------------------------------------------------------------------------- #
# transform / dedupe / split 核心 (CLI 与 pipeline 共用)
# --------------------------------------------------------------------------- #
def load_transform_config(config_path: str) -> Dict[str, Any]:
    """动态加载 .dt/*.py 配置, 返回模块的公开名字 (含 transform 函数与 output)。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("dt_config", config_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {name: getattr(module, name) for name in dir(module) if not name.startswith("_")}


def transform_rows(
    st: StreamingTransformer,
    preset: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    config: Optional[str] = None,
    strict: bool = False,
) -> StreamingTransformer:
    """按预设 (preset + params) 或配置文件 (config 的 transform 函数) 逐行转换。"""
    if preset:
        from .presets import get_preset

        func = get_preset(preset, **(params or {}))
    elif config:
        ns = load_transform_config(config)
        if "transform" not in ns:
            raise ValueError(
                t(
                    f"Config file defines no transform function: {config}",
                    f"配置文件未定义 transform 函数: {config}",
                )
            )
        func = ns["transform"]
    else:
        raise ValueError(
            t("transform requires a preset or config", "transform 需要指定 preset 或 config")
        )
    return st.transform(
        lambda item: unwrap(func(DictWrapper(item))), raw=True, on_error=_on_error(strict)
    )


def dedupe_key(key: Optional[str]) -> Any:
    """--key 'a,b' → ['a', 'b']; 单个 → 'a'; 空 → None (全量)"""
    if not key:
        return None
    keys = [k.strip() for k in key.split(",")]
    return keys[0] if len(keys) == 1 else keys


def dedupe_rows(
    st: StreamingTransformer, key: Optional[str] = None, similar: Optional[float] = None
) -> StreamingTransformer:
    """精确去重流式 (O(唯一键)); 相似度去重 (MinHash) 需全量。"""
    if similar is None:
        return st.dedupe(dedupe_key(key), raw=True)
    if not key:
        raise ValueError(t("Similarity dedupe requires a key", "相似度去重需要指定 key"))
    from .core import DataTransformer

    rows = DataTransformer(st.collect()).dedupe_similar(key, threshold=similar).data
    return _materialize(st, rows)


def parse_ratio(ratio: Any) -> List[float]:
    """ "0.8" → [0.8, 0.2]; "0.7,0.15,0.15" → 三段; 也接受数字 0.8 或 list。"""
    if isinstance(ratio, (int, float)):
        parts = [float(ratio)]
    elif isinstance(ratio, (list, tuple)):
        parts = [float(x) for x in ratio]
    else:
        parts = [float(x.strip()) for x in str(ratio).split(",")]
    if len(parts) == 1:
        if not (0 < parts[0] < 1):
            raise ValueError(
                t(f"Ratio must be between 0 and 1: {parts[0]}", f"比例必须在 0-1 之间: {parts[0]}")
            )
        parts.append(round(1 - parts[0], 10))
    if abs(sum(parts) - 1.0) > 1e-6:
        raise ValueError(
            t(
                f"Ratios must sum to 1.0, got {sum(parts)}",
                f"比例之和必须为 1.0，当前为 {sum(parts)}",
            )
        )
    if any(p <= 0 for p in parts):
        raise ValueError(t("Every ratio must be greater than 0", "每个比例都必须大于 0"))
    return parts


def split_names(count: int) -> List[str]:
    """二分 train/test; 三分 train/val/test; 更多追加 part4..."""
    if count == 2:
        return ["train", "test"]
    names = ["train", "val", "test"]
    for i in range(3, count):
        names.append(f"part{i + 1}")
    return names


def split_rows(rows: List[Row], ratios: List[float], seed: Optional[int] = None) -> List[List[Row]]:
    """打乱后按比例切成 len(ratios) 段 (最后一段吃掉取整余数)。"""
    data = list(rows)
    _random.Random(seed).shuffle(data)
    total = len(data)
    parts: List[List[Row]] = []
    prev = 0
    for r in ratios[:-1]:
        cut = prev + int(total * r)
        parts.append(data[prev:cut])
        prev = cut
    parts.append(data[prev:])
    return parts


# --------------------------------------------------------------------------- #
# schema 推断: 给 agent "先了解全貌" 用
# --------------------------------------------------------------------------- #
_LOW_CARDINALITY = 10


def infer_schema(rows: Iterable[Row], max_depth: int = 5) -> Dict[str, Any]:
    """单遍推断嵌套结构: 每个路径的类型集合、非空率、list 元素类型、低基数字符串的取值。"""

    def new_node() -> Dict[str, Any]:
        return {
            "types": Counter(),
            "seen": 0,
            "nonnull": 0,
            "values": set(),
            "fields": None,
            "items": None,
        }

    def visit(node: Dict[str, Any], value: Any, depth: int) -> None:
        node["seen"] += 1
        if value is None:
            node["types"]["null"] += 1
            return
        node["nonnull"] += 1
        tn = _type_name(value)
        node["types"][tn] += 1
        if tn == "str" and node["values"] is not None:
            node["values"].add(value)
            if len(node["values"]) > _LOW_CARDINALITY:
                node["values"] = None
        elif tn == "dict" and depth < max_depth:
            if node["fields"] is None:
                node["fields"] = {}
            for k, v in value.items():
                visit(node["fields"].setdefault(k, new_node()), v, depth + 1)
        elif tn == "list" and depth < max_depth:
            if node["items"] is None:
                node["items"] = new_node()
            for v in value:
                visit(node["items"], v, depth + 1)

    root = new_node()
    n = 0
    for row in rows:
        n += 1
        visit(root, row, 0)

    def render(node: Dict[str, Any], denom: int) -> Dict[str, Any]:
        # denom = 父级出现次数: 键缺失也算"空", 否则缺字段的行会把非空率虚报成 100%
        types = [tn for tn, _ in node["types"].most_common() if tn != "null"]
        out: Dict[str, Any] = {"type": types[0] if len(types) == 1 else (types or ["null"])}
        out["non_null"] = round(node["nonnull"] / denom, 4) if denom else 0.0
        if node["values"]:
            out["values"] = sorted(node["values"])
        if node["fields"] is not None:
            n_dict = node["types"]["dict"]
            out["fields"] = {k: render(v, n_dict) for k, v in node["fields"].items()}
        if node["items"] is not None:
            out["items"] = render(node["items"], node["items"]["seen"])
        return out

    result = render(root, n)
    return {"rows_scanned": n, "fields": result.get("fields", {})}


def _type_name(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, dict):
        return "dict"
    if isinstance(v, list):
        return "list"
    return type(v).__name__


__all__ = [
    "parse_spec",
    "filter_rows",
    "map_rows",
    "select_rows",
    "explode_rows",
    "sort_rows",
    "shuffle_rows",
    "group_rows",
    "join_rows",
    "clean_rows",
    "transform_rows",
    "load_transform_config",
    "dedupe_rows",
    "dedupe_key",
    "parse_ratio",
    "split_names",
    "split_rows",
    "infer_schema",
]
