"""
dt view 的行数据源: 随机窗口访问, 内存 O(窗口), 与文件大小解耦。

核心洞察: 贵的是 JSON 解析, 便宜的是定位。
- JSONL: 首次扫一遍只记录每行字节偏移 (不 parse), 之后只 parse 当前窗口, seek 任意位置瞬时。
- 其他格式 (JSON/CSV/Parquet/Arrow): 无逐行随机访问, 沿用 load_data 全量入内存, 窗口即切片。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence

import orjson

# 坏行占位行的字段名。带前缀且足够具体, 避免与真实数据撞名。
PARSE_ERROR_FIELD = "_parse_error"
RAW_LINE_FIELD = "_raw_line"
_RAW_KEEP = 500  # 原始行留多少字符 (够看出坏在哪, 又不至于把表格撑爆)


def _bad_row(line: bytes, err: Exception) -> Dict:
    """坏行 → 占位行, 而不是抛出。

    dt view 的职责就是"看数据", 而语法坏掉的行恰恰是人打开它要找的东西: 崩掉最差,
    悄悄跳过次之 (行号会与文件错位, 而且你根本不知道漏了什么), 显示出来才对。

    偏移索引按"非空行"计数, 坏行本就占一个行号 —— 返回占位行, ``#`` 列与文件行号
    继续对齐, total 也不用改, 索引语义一点不动。
    """
    return {
        PARSE_ERROR_FIELD: f"{type(err).__name__}: {err}",
        RAW_LINE_FIELD: line.decode("utf-8", errors="replace")[:_RAW_KEEP],
    }


def _loads(line: bytes) -> Dict:
    """orjson 优先, 失败回退标准 json (与 streaming._stream_jsonl 一致)。

    两者都解不动时返回占位行 —— 浏览器不该被一行坏数据挡在门外。
    """
    try:
        return orjson.loads(line)
    except orjson.JSONDecodeError:
        try:
            return json.loads(line)  # 标准 json 更宽松 (NaN/Infinity)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            return _bad_row(line, e)


class RowSource:
    """行数据源基类。total = 总行数; window(offset, size) 返回 [offset, offset+size) 的行。"""

    total: int = 0

    def window(self, offset: int, size: int) -> List[Dict]:
        raise NotImplementedError

    def iter_all(self, progress_cb: Optional[Callable[[int], None]] = None) -> Iterator[Dict]:
        """流式产出全部行 (供全量统计/筛选)。O(1) 内存, 不物化整表。

        progress_cb(已产出行数): 每 N 行回调一次, 供 TUI 刷新扫描进度。
        """
        raise NotImplementedError

    def rows_at(self, indices: Sequence[int]) -> List[Dict]:
        """按全局行号 (0-based) 取任意若干行, 顺序与 indices 一致。供筛选子集分页。"""
        raise NotImplementedError


class _JsonlSource(RowSource):
    """JSONL: 建立行字节偏移索引 (跳过空行, 与 _stream_jsonl 一致), 只 parse 当前窗口。"""

    def __init__(self, path: Path):
        self._path = path
        # 每个非空行的字节偏移; 100 万行 ≈ 8MB, 只数换行不 parse, 一趟扫描很快。
        offsets: List[int] = []
        with open(path, "rb") as f:
            pos = 0
            for line in f:
                if line.strip():
                    offsets.append(pos)
                pos += len(line)
        self._offsets = offsets
        self.total = len(offsets)

    def window(self, offset: int, size: int) -> List[Dict]:
        offset = max(0, offset)
        end = min(offset + size, self.total)
        if offset >= end:
            return []
        rows: List[Dict] = []
        need = end - offset
        with open(self._path, "rb") as f:
            f.seek(self._offsets[offset])
            # 顺序读并跳过夹杂的空行 (索引只记非空行, 读到空行不计数)
            while len(rows) < need:
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                rows.append(_loads(line))
        return rows

    def iter_all(self, progress_cb: Optional[Callable[[int], None]] = None) -> Iterator[Dict]:
        # 顺序读整个文件 (比逐 offset seek 快), 跳过空行; 每 5000 行回调一次进度。
        n = 0
        with open(self._path, "rb") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield _loads(line)
                n += 1
                if progress_cb is not None and n % 5000 == 0:
                    progress_cb(n)
        if progress_cb is not None:
            progress_cb(n)

    def rows_at(self, indices: Sequence[int]) -> List[Dict]:
        rows: List[Dict] = []
        with open(self._path, "rb") as f:
            for i in indices:
                if not (0 <= i < self.total):
                    continue
                f.seek(self._offsets[i])
                line = f.readline().strip()
                if line:
                    rows.append(_loads(line))
        return rows


class _MemorySource(RowSource):
    """全量载入内存, 窗口即切片。用于非 JSONL 文件 (无逐行随机访问) 与 stdin (流不可 seek)。"""

    def __init__(self, rows: List[Dict]):
        self._data = rows
        self.total = len(rows)

    def window(self, offset: int, size: int) -> List[Dict]:
        return self._data[max(0, offset) : offset + size]

    def iter_all(self, progress_cb: Optional[Callable[[int], None]] = None) -> Iterator[Dict]:
        yield from self._data
        if progress_cb is not None:
            progress_cb(self.total)

    def rows_at(self, indices: Sequence[int]) -> List[Dict]:
        return [self._data[i] for i in indices if 0 <= i < self.total]


def read_stdin_source() -> RowSource:
    """从 stdin 逐行读 NDJSON (dt 管道默认格式, 跳过空行) → 全量内存源。

    管道是流, 无法 seek, 必须全量入内存; 适合看处理结果的一小撮
    (如 dt sample ... | dt view -)。
    """
    import sys

    rows: List[Dict] = []
    for line in sys.stdin:
        line = line.strip()
        if line:
            rows.append(_loads(line.encode()))
    return _MemorySource(rows)


def open_source(filepath: Path) -> RowSource:
    """按扩展名选择数据源实现。"""
    if filepath.suffix.lower() in (".jsonl", ".ndjson"):
        return _JsonlSource(filepath)
    from ...storage.io import load_data

    return _MemorySource(load_data(str(filepath)))
