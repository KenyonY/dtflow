"""
数据原语 (库层): filter / select / map / explode / sort / shuffle / group / join。

每个函数把一步操作挂到 StreamingTransformer 上 (能惰性的都惰性), CLI (cli/ops.py) 与
pipeline 共用同一份实现。表达式一律是 Python (见 dtflow.expr), 当前行为 x。
只抛 ValueError / ExprSyntaxError, 不 import 任何 CLI 层的东西。
"""

from __future__ import annotations

import random as _random
import statistics
from collections import Counter, OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .core import ListWrapper, unwrap
from .expr import compile_in, compile_map, compile_value, compile_where
from .streaming import StreamingTransformer

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
            raise ValueError(f"无法解析: {item!r} (形如 name=表达式 或 字段名)")
        name = name.strip()
        if not name.isidentifier() and eq:
            raise ValueError(f"派生字段名必须是合法标识符: {name!r}")
        out.append((name, expr.strip() if eq else None))
    if not out:
        raise ValueError("SPEC 为空")
    return out


# --------------------------------------------------------------------------- #
# 逐行原语
# --------------------------------------------------------------------------- #
def filter_rows(st: StreamingTransformer, expr: str, strict: bool = False) -> StreamingTransformer:
    """保留 expr 为真的行。求值失败的行: 默认跳过并计数, strict 则抛出。"""
    return st.filter(compile_where(expr), raw=True, on_error=_on_error(strict))


def map_rows(st: StreamingTransformer, code: str, strict: bool = False) -> StreamingTransformer:
    """对每行执行语句 (原地改 x), 如 ``x.text = x.text.strip(); del x.debug``。"""
    return st.transform(compile_map(code), raw=True, on_error=_on_error(strict))


def select_rows(st: StreamingTransformer, spec: str, strict: bool = False) -> StreamingTransformer:
    """投影 + 重命名 + 派生: ``id,text,n=len(x.messages),src=x.meta.source``。

    字面字段缺失时省略该键 (不报错, 异构数据是常态); 派生表达式失败按 strict 处理。
    输出键序 = SPEC 序。
    """
    plan = [(name, compile_value(expr) if expr else None) for name, expr in parse_spec(spec)]

    def project(row: Row) -> Row:
        out: Row = OrderedDict()
        for name, fn in plan:
            if fn is None:
                if name in row:
                    out[name] = row[name]
            else:
                out[name] = fn(row)
        return dict(out)

    return st.transform(project, raw=True, on_error=_on_error(strict))


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
        except Exception as e:
            if strict:
                raise ValueError(f"排序键求值失败: {type(e).__name__}: {e}") from e
            failed += 1
            keyed.append((1, None, row))
    ok = [k for k in keyed if k[0] == 0]
    bad = [k for k in keyed if k[0] == 1]
    try:
        ok.sort(key=lambda k: k[1], reverse=desc)
    except TypeError as e:
        raise ValueError(f"排序键类型不一致, 无法比较 ({e}); 用 str(...) 或 float(...) 统一") from e
    new = _materialize(st, [k[2] for k in ok] + [k[2] for k in bad])
    if failed:
        new._error_count += failed
        new._first_error = new._first_error or "排序键求值失败 (已排在末尾)"
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


def group_rows(
    st: StreamingTransformer, by: str, agg: Optional[str] = None, strict: bool = False
) -> StreamingTransformer:
    """按表达式分组。

    无 agg: 流式计数, 输出 {"key", "count"} 按 count 降序。
    有 agg (``n=len(g),avg=mean(len(r.text) for r in g)``): 按组收集行, 每个表达式可用
    ``g`` (该组行列表)、``key``、``n``、``mean``/``median``。
    """
    keyfn = compile_value(by)
    if agg is None:
        counter: Counter = Counter()
        keys: Dict[Any, Any] = {}
        failed = 0
        first_err = None
        for row in st:
            try:
                k = keyfn(row)
            except Exception as e:
                if strict:
                    raise ValueError(f"分组键求值失败: {type(e).__name__}: {e}") from e
                failed += 1
                first_err = first_err or f"{type(e).__name__}: {e}"
                continue
            hk = _hashable(k)
            keys.setdefault(hk, k)
            counter[hk] += 1
        rows = [{"key": keys[hk], "count": n} for hk, n in counter.most_common()]
        new = _materialize(st, rows)
        new._error_count += failed
        new._first_error = new._first_error or first_err
        return new

    plan = [(name, compile_in(expr)) for name, expr in parse_spec(agg)]
    for name, expr in parse_spec(agg):
        if expr is None:
            raise ValueError(f"--agg 每项都要是 name=表达式, 得到 {name!r}")
    groups: Dict[Any, List[Row]] = OrderedDict()
    keys = {}
    failed = 0
    first_err = None
    for row in st:
        try:
            k = keyfn(row)
        except Exception as e:
            if strict:
                raise ValueError(f"分组键求值失败: {type(e).__name__}: {e}") from e
            failed += 1
            first_err = first_err or f"{type(e).__name__}: {e}"
            continue
        hk = _hashable(k)
        keys.setdefault(hk, k)
        groups.setdefault(hk, []).append(row)
    out: List[Row] = []
    for hk, members in groups.items():
        ns = {**_AGG_NS, "g": ListWrapper(members), "key": keys[hk], "n": len(members)}
        rec: Row = {"key": keys[hk], "n": len(members)}
        for name, fn in plan:
            rec[name] = unwrap(fn(ns))
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
) -> Tuple[StreamingTransformer, int]:
    """左表流式、右表入内存的键连接。返回 (结果流, 右表重复键数)。

    默认左连接 (未命中的左行原样透传), inner 则丢弃。合并时左表字段优先;
    给 prefix 则右表全部字段加前缀 (可预期, 不做"只对冲突字段加前缀"这种看数据才知道的规则)。
    右表同键多行只取首条 (一对多留待后续)。
    """
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

    def merge(row: Row) -> Iterable[Row]:
        try:
            hk = _hashable(lkey(row))
        except Exception:
            hk = None
        match = index.get(hk) if hk is not None else None
        if match is None:
            return () if inner else (row,)
        out = dict(row)
        for k, v in match.items():
            if prefix:
                out[prefix + k] = v
            else:
                out.setdefault(k, v)
        return (out,)

    return st.flat_map(merge, raw=True), dup


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
        t = _type_name(value)
        node["types"][t] += 1
        if t == "str" and node["values"] is not None:
            node["values"].add(value)
            if len(node["values"]) > _LOW_CARDINALITY:
                node["values"] = None
        elif t == "dict" and depth < max_depth:
            if node["fields"] is None:
                node["fields"] = {}
            for k, v in value.items():
                visit(node["fields"].setdefault(k, new_node()), v, depth + 1)
        elif t == "list" and depth < max_depth:
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
        types = [t for t, _ in node["types"].most_common() if t != "null"]
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
    "infer_schema",
]
