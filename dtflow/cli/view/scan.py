"""dt view 的全量扫描层: 约束 spec 化 + 多进程分片扫描。

谓词是闭包, 跨不了进程; 而"搜索词 / where 表达式 / 列值集 / 排序列"本来就都是可序列化的。
于是把这些定为唯一真相 (ScanSpec), 主进程与子进程各自由它编译出同一个谓词 ——
并行与串行两条路径因此不会各写一套判定逻辑而悄悄跑偏。

三条路径, 按"能少扫就少扫"排序:
- refine_rows: 新约束是旧约束的收紧 (只加条件/只缩值集) → 只扫当前子集, 不碰文件。
- scan_rows:   必须全量时, 按字节区间分片交给进程池 (线程池无用: orjson 解析不放 GIL)。
- scan_values: 列值勾选面板的候选值, 顺带记下每个值的行号 → 勾完即可直接拼子集, 免二次扫描。

本模块刻意不 import textual: fork 出来的子进程只跑纯函数。
"""

from __future__ import annotations

import atexit
import multiprocessing
import os
import re
from array import array
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Dict, Iterator, List, Optional, Pattern, Sequence, Tuple

from . import render
from .source import _loads

# 行数低于此值时进程池的启动与调度开销盖过收益 (串行约 6μs/行), 直接串行
PARALLEL_MIN_ROWS = 50_000
# 每个 worker 切多块: 兼顾负载均衡与取消响应 (取消只需等当前块跑完)
CHUNKS_PER_WORKER = 4
# 子集占全量的比例超过它就别"收紧"了, 老老实实重扫: 逐行回读要按行 seek, 实测约
# 8.9μs/行, 而并行顺序全扫只要 0.72μs/行 —— 子集大过约 1/12 时, 少读的那点行数
# 抵不过随机读与失去并行的代价 (冷缓存下顺序读更占优, 故取整到 1/10)
REFINE_MAX_RATIO = 0.1


# --------------------------------------------------------------------------- #
# 表达式编译 (主进程校验用户输入、子进程重建谓词, 同一套代码)
# --------------------------------------------------------------------------- #
def _compile_atom(expr: str, fmt: str):
    """编译单个条件 ``字段 运算符 值`` → predicate(row)->bool。

    字段直接用表格里看到的列名 (turns/roles/chars/source 等):
    - 若是**派生列** (计算列, 无字段路径, 如 chars/turns/first_user) → 按该列的值比较;
      ``~=`` (包含) 匹配未截断的完整文本, 不是表格里那 80 字的预览。
    - 否则当**真实字段路径**交给 _parse_where (标量列名 source, 或深层 messages.#>=2)。
    """
    import operator

    from ..sample import _parse_where

    ops = [
        (">=", operator.ge),
        ("<=", operator.le),
        ("!=", operator.ne),
        # 包含; 必须排在 "=" 之前。不区分大小写, 与 _parse_where、/ 搜索、值面板搜索框一致
        ("~=", lambda cell, v: v.lower() in cell.lower()),
        ("==", operator.eq),
        (">", operator.gt),
        ("<", operator.lt),
        ("=", operator.eq),
    ]
    field_name = op = value = None
    token = ""
    for token, _op in ops:
        if token in expr:
            field_name, _, value = expr.partition(token)
            op = _op
            break
    field_s = (field_name or "").strip()
    if field_s not in render.derived_columns(fmt):
        return _parse_where(expr)  # 标量列名 / 深层字段路径, 走原生解析

    col = field_s
    value = (value or "").strip()
    if token == "~=":  # 包含永远是字符串语义, 不能把 "2000" 当数字比
        numeric, cmp_value = False, value
    else:
        try:
            cmp_value = float(value)
            numeric = True
        except ValueError:
            cmp_value = value
            numeric = False
    # 包含筛选要看全文 (预览只有 80 字, 截断会静默漏掉靠后的关键词)
    preview = token != "~="

    def predicate(row) -> bool:
        if not isinstance(row, dict):
            return False
        cell = render.row_cells(0, row, fmt, [col], preview=preview)[0]
        if cell == "":
            return False
        if numeric:
            try:
                return op(float(cell), cmp_value)
            except (ValueError, TypeError):
                return False
        return op(str(cell), str(cmp_value))

    return predicate


def compile_where(expr: str, fmt: str):
    """把筛选表达式编译成 predicate(row)->bool, 支持 ``and``/``or`` 多条件组合。

    用带空格的 `` and `` / `` or `` 分隔 (避免误伤值内子串如 source==android);
    ``and`` 优先级高于 ``or`` (标准语义, 不支持括号)。每个子条件形如 ``列名 运算符 值``,
    列名取表头所见 —— 这样 ``turns>=6 and chars<2000`` 这类多列筛选直接可写。

    不支持括号是刻意的: 需要 ``(a or b) and (c or d)`` 时改用多条 where
    (TUI 内连按两次 f, 命令行传两个 --where), 多条之间是 AND。
    """
    or_groups = []
    for or_part in re.split(r"\s+or\s+", expr, flags=re.IGNORECASE):
        ands = [
            _compile_atom(a.strip(), fmt)
            for a in re.split(r"\s+and\s+", or_part, flags=re.IGNORECASE)
        ]
        or_groups.append(ands)

    def predicate(row) -> bool:
        return any(all(p(row) for p in ands) for ands in or_groups)

    return predicate


def compile_search(text: str) -> Pattern:
    """搜索词 → 正则。默认按字面子串 (转义), ``re:`` 前缀走正则; 一律不分大小写。

    编译出的 pattern 同时用于两处, 必须同源: 筛选出命中子集, 以及给命中处画黄底。
    非法正则原样抛 re.error, 由调用方提示用户。
    """
    if text.startswith("re:"):
        return re.compile(text[3:], re.IGNORECASE)
    return re.compile(re.escape(text), re.IGNORECASE)


# --------------------------------------------------------------------------- #
# 约束模型
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ScanSpec:
    """一次扫描的全部约束。必须保持可 pickle (子进程靠它重建谓词)。"""

    fmt: str
    search: Optional[str] = None
    wheres: Tuple[str, ...] = ()
    # 列值勾选: ((列名, (保留值…)), …); 用 tuple 而非 dict/set 以保证可哈希可比较
    value_filters: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    sort_col: Optional[str] = None
    sort_desc: bool = False

    @property
    def has_filters(self) -> bool:
        return bool(self.search or self.wheres or self.value_filters)

    def without_column(self, col: str) -> "ScanSpec":
        """去掉某列自己的值约束 —— 算该列候选值时要看"除本列外"的其他约束。"""
        return ScanSpec(
            fmt=self.fmt,
            search=self.search,
            wheres=self.wheres,
            value_filters=tuple((c, v) for c, v in self.value_filters if c != col),
            sort_col=self.sort_col,
            sort_desc=self.sort_desc,
        )


def make_spec(
    fmt: str,
    search: Optional[str],
    wheres: Sequence[str],
    value_filters: Dict[str, set],
    sort: Optional[Tuple[str, bool]],
) -> ScanSpec:
    """从 TUI 的可变状态铸一个不可变 spec (列/值都排序, 使相等比较稳定)。"""
    return ScanSpec(
        fmt=fmt,
        search=search,
        wheres=tuple(wheres),
        value_filters=tuple((c, tuple(sorted(value_filters[c]))) for c in sorted(value_filters)),
        sort_col=sort[0] if sort else None,
        sort_desc=bool(sort and sort[1]),
    )


def build_row_ok(spec: ScanSpec) -> Optional[Callable]:
    """spec → predicate(row)->bool; 无任何筛选返回 None (全通过)。

    多列值约束合并成一次 row_cells 调用: 它每次都会把所有派生列算一遍, 逐列问
    等于把整行重算 N 遍。
    """
    if not spec.has_filters:
        return None
    pat = compile_search(spec.search) if spec.search else None
    wheres = [compile_where(e, spec.fmt) for e in spec.wheres]
    cols = [c for c, _ in spec.value_filters]
    kept = [set(v) for _, v in spec.value_filters]
    fmt = spec.fmt

    def row_ok(row) -> bool:
        if not isinstance(row, dict):
            return False
        if pat is not None and not pat.search(render.row_text(row)):
            return False
        for w in wheres:
            if not w(row):
                return False
        if cols:
            cells = render.row_cells(0, row, fmt, cols)
            for cell, keep in zip(cells, kept, strict=False):
                if cell not in keep:
                    return False
        return True

    return row_ok


def build_keyfn(spec: ScanSpec) -> Optional[Callable]:
    """按排序列取键 ``keyfn(全局行号, 行)``: 数值优先 (0, float), 非数值退化为 (1, str)。

    分层元组保证数值行整体排在字符串行之前, 不会 float 与 str 相比报错。
    ``#`` 列必须用传进来的全局行号: 它是"第几行"这一事实, 不在行数据里
    (row_cells 拿到的 # 恒为占位值), 按它排会全部同键 → 扫了一遍却纹丝不动。
    """
    if spec.sort_col is None:
        return None
    col, fmt = spec.sort_col, spec.fmt

    def keyfn(idx: int, row):
        if col == "#":
            return (0, float(idx), "")
        v = render.row_cells(0, row, fmt, [col])[0] if isinstance(row, dict) else ""
        try:
            return (0, float(v), "")
        except (ValueError, TypeError):
            return (1, 0.0, str(v))

    return keyfn


def is_refinement(old: Optional[ScanSpec], new: ScanSpec) -> bool:
    """new 的命中集是否必然是 old 的子集 —— 是则可以只扫旧子集, 不必重读文件。

    收紧的三种形态: 新加一条 where (只许追加, 改写旧条件不算)、从无到有加搜索词、
    某列值集收窄。排序键一变就不算: 子集虽仍是子集, 但已排好的顺序作不得数。
    """
    if old is None or old.fmt != new.fmt:
        return False
    if (old.sort_col, old.sort_desc) != (new.sort_col, new.sort_desc):
        return False
    if old.search is not None and new.search != old.search:
        return False
    if new.wheres[: len(old.wheres)] != old.wheres:
        return False
    new_values = dict(new.value_filters)
    for col, vals in old.value_filters:
        if col not in new_values or not set(new_values[col]) <= set(vals):
            return False
    return True


# --------------------------------------------------------------------------- #
# 进程池 (fork: 子进程直接继承已 import 的模块, 无需重新导入)
# --------------------------------------------------------------------------- #
_pool: Optional[ProcessPoolExecutor] = None
_pool_size = 0
_atexit_done = False


def worker_count() -> int:
    """并行度。DTFLOW_VIEW_WORKERS=1 (或 0) 可强制退回串行, 便于排障。"""
    env = os.environ.get("DTFLOW_VIEW_WORKERS")
    if env:
        try:
            return max(0, int(env))
        except ValueError:
            pass
    return min(os.cpu_count() or 1, 16)


def parallel_available() -> bool:
    return worker_count() > 1 and "fork" in multiprocessing.get_all_start_methods()


def shutdown_pool() -> None:
    global _pool, _pool_size
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool, _pool_size = None, 0


def _get_pool(n: int) -> ProcessPoolExecutor:
    """复用同一个池: 池只在第一次扫描时启动, 之后每次扫描省掉 fork 开销。"""
    global _pool, _pool_size, _atexit_done
    if _pool is not None and _pool_size == n:
        return _pool
    shutdown_pool()
    _pool = ProcessPoolExecutor(n, mp_context=multiprocessing.get_context("fork"))
    _pool_size = n
    if not _atexit_done:
        atexit.register(shutdown_pool)
        _atexit_done = True
    return _pool


# --------------------------------------------------------------------------- #
# 分片任务 (子进程执行; 必须是模块级函数才能 pickle)
# --------------------------------------------------------------------------- #
def _iter_chunk(path: str, start: int, end: int, first_row: int) -> Iterator[Tuple[int, dict]]:
    """读 [start, end) 字节区间的行; 产出 (全局行号, 行)。区间边界即行边界。"""
    i = first_row
    with open(path, "rb") as f:
        f.seek(start)
        pos = start
        while pos < end:
            line = f.readline(end - pos)
            if not line:
                break
            pos += len(line)
            line = line.strip()
            if not line:
                continue
            yield i, _loads(line)
            i += 1


def chunk_filter(task):
    """一个分片的筛选结果: (命中行号, 排序键, 扫过的行数)。"""
    path, start, end, first_row, spec = task
    row_ok = build_row_ok(spec)
    keyfn = build_keyfn(spec)
    matches: List[int] = []
    keys: List = []
    n = 0
    for i, row in _iter_chunk(path, start, end, first_row):
        n += 1
        try:
            if row_ok is None or row_ok(row):
                matches.append(i)
                if keyfn is not None:
                    keys.append(keyfn(i, row))
        except Exception:  # noqa: BLE001  单行畸形不该中断整轮扫描
            pass
    return matches, keys, n


def chunk_values(task):
    """一个分片里某列的 值 → 行号表 (行号升序); 扫过的行数一并带回。"""
    path, start, end, first_row, spec, col = task
    row_ok = build_row_ok(spec)
    fmt = spec.fmt
    buckets: Dict[str, array] = {}
    n = 0
    for i, row in _iter_chunk(path, start, end, first_row):
        n += 1
        if not isinstance(row, dict):
            continue
        try:
            if row_ok is not None and not row_ok(row):
                continue
            cell = render.row_cells(0, row, fmt, [col])[0]
        except Exception:  # noqa: BLE001
            continue
        bucket = buckets.get(cell)
        if bucket is None:
            bucket = buckets[cell] = array("q")
        bucket.append(i)
    return buckets, n


# --------------------------------------------------------------------------- #
# 驱动: 并行优先, 不可用/出错则串行; 取消一律返回 None
# --------------------------------------------------------------------------- #
def _run_chunks(fn, tasks, total: int, progress, cancel):
    """把分片交给进程池, 按分片序号归位结果。取消返回 None; 池不可用抛异常由调用方兜。"""
    pool = _get_pool(worker_count())
    futures = {pool.submit(fn, t): k for k, t in enumerate(tasks)}
    results: List = [None] * len(tasks)
    pending = set(futures)
    done_rows = 0
    while pending:
        if cancel is not None and cancel.is_set():
            for f in pending:
                f.cancel()
            return None
        done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
        for f in done:
            result = f.result()
            results[futures[f]] = result
            done_rows += result[-1]
            if progress is not None:
                progress(done_rows, total)
    return results


def _sorted_matches(matches: List[int], keys: List, spec: ScanSpec) -> List[int]:
    if spec.sort_col is None:
        return matches
    # sort 是稳定的 → 键相同的行保持原文件顺序, 结果可复现
    order = sorted(range(len(matches)), key=lambda j: keys[j], reverse=spec.sort_desc)
    return [matches[j] for j in order]


def scan_rows(source, spec: ScanSpec, *, progress=None, cancel=None) -> Optional[List[int]]:
    """全量扫描 → 命中的全局行号 (已按 spec 排序)。取消返回 None。"""
    ranges = source.parallel_ranges(worker_count() * CHUNKS_PER_WORKER)
    if ranges is not None and parallel_available() and source.total >= PARALLEL_MIN_ROWS:
        try:
            tasks = [(str(source.path), a, b, first, spec) for a, b, first in ranges]
            results = _run_chunks(chunk_filter, tasks, source.total, progress, cancel)
            if results is None:
                return None
            matches: List[int] = []
            keys: List = []
            for m, k, _ in results:
                matches.extend(m)
                keys.extend(k)
            return _sorted_matches(matches, keys, spec)
        except Exception:  # noqa: BLE001  进程池不可用 (容器限制/内存/被杀) → 串行兜底
            shutdown_pool()

    row_ok = build_row_ok(spec)
    keyfn = build_keyfn(spec)
    matches = []
    keys = []
    total = source.total
    for i, row in enumerate(source.iter_all()):
        if cancel is not None and cancel.is_set():
            return None
        try:
            if row_ok is None or row_ok(row):
                matches.append(i)
                if keyfn is not None:
                    keys.append(keyfn(i, row))
        except Exception:  # noqa: BLE001
            pass
        if progress is not None and i % 5000 == 0:
            progress(i + 1, total)
    return _sorted_matches(matches, keys, spec)


def refine_base(old: Optional[ScanSpec], new: ScanSpec, subset, total: int):
    """可以只扫旧子集时返回该子集, 否则 None (交给全量扫描)。

    两个条件缺一不可: 约束确实是收紧 (命中集必然是子集), 且子集小到逐行回读划算。
    """
    if subset is None or not is_refinement(old, new):
        return None
    if total > 0 and len(subset) > total * REFINE_MAX_RATIO:
        return None
    return subset


def refine_rows(
    source, subset: Sequence[int], spec: ScanSpec, *, progress=None, cancel=None
) -> Optional[List[int]]:
    """在已有子集上收紧约束: 只读这些行, 顺序原样保留 (含已排好的排序序)。"""
    row_ok = build_row_ok(spec)
    if row_ok is None:
        return list(subset)
    total = len(subset)
    matches: List[int] = []
    for start in range(0, total, 1000):
        if cancel is not None and cancel.is_set():
            return None
        chunk = list(subset[start : start + 1000])
        for gidx, row in zip(chunk, source.rows_at(chunk), strict=False):
            try:
                if row_ok(row):
                    matches.append(gidx)
            except Exception:  # noqa: BLE001
                pass
        if progress is not None:
            progress(min(start + 1000, total), total)
    return matches


def scan_values(
    source, col: str, spec: ScanSpec, *, progress=None, cancel=None
) -> Optional[Dict[str, array]]:
    """某列的 值 → 行号表 (行号升序), 施加 spec 里的其他约束。取消返回 None。

    带上行号而不只是频次: 勾选确定后子集 = 选中各值行号表的归并, 无需再扫一遍文件。
    """
    ranges = source.parallel_ranges(worker_count() * CHUNKS_PER_WORKER)
    if ranges is not None and parallel_available() and source.total >= PARALLEL_MIN_ROWS:
        try:
            tasks = [(str(source.path), a, b, first, spec, col) for a, b, first in ranges]
            results = _run_chunks(chunk_values, tasks, source.total, progress, cancel)
            if results is None:
                return None
            merged: Dict[str, array] = {}
            for buckets, _ in results:  # 分片按序归位 → 拼出来天然行号升序
                for value, rows in buckets.items():
                    if value in merged:
                        merged[value].extend(rows)
                    else:
                        merged[value] = rows
            return merged
        except Exception:  # noqa: BLE001
            shutdown_pool()

    row_ok = build_row_ok(spec)
    fmt = spec.fmt
    merged = {}
    total = source.total
    for i, row in enumerate(source.iter_all()):
        if cancel is not None and cancel.is_set():
            return None
        if progress is not None and i % 5000 == 0:
            progress(i + 1, total)
        if not isinstance(row, dict):
            continue
        try:
            if row_ok is not None and not row_ok(row):
                continue
            cell = render.row_cells(0, row, fmt, [col])[0]
        except Exception:  # noqa: BLE001
            continue
        bucket = merged.get(cell)
        if bucket is None:
            bucket = merged[cell] = array("q")
        bucket.append(i)
    return merged


def merge_value_rows(value_rows: Dict[str, array], selected) -> List[int]:
    """选中值的行号表归并成升序子集 (各表本身有序, 直接合并再排)。"""
    out: List[int] = []
    for value in selected:
        rows = value_rows.get(value)
        if rows:
            out.extend(rows)
    out.sort()
    return out
