"""
dt view 的行数据源: 随机窗口访问, 内存 O(窗口), 与文件大小解耦。

核心洞察: 贵的是 JSON 解析, 便宜的是定位。
- JSONL: 首次扫一遍只记录每行字节偏移 (不 parse), 之后只 parse 当前窗口, seek 任意位置瞬时。
- 其他格式 (JSON/CSV/Parquet/Arrow): 无逐行随机访问, 沿用 load_data 全量入内存, 窗口即切片。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import orjson


def _loads(line: bytes) -> Dict:
    """orjson 优先, 失败回退标准 json (与 streaming._stream_jsonl 一致)。"""
    try:
        return orjson.loads(line)
    except orjson.JSONDecodeError:
        return json.loads(line)


class RowSource:
    """行数据源基类。total = 总行数; window(offset, size) 返回 [offset, offset+size) 的行。"""

    total: int = 0

    def window(self, offset: int, size: int) -> List[Dict]:
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


class _MemorySource(RowSource):
    """全量载入内存, 窗口即切片。用于非 JSONL 文件 (无逐行随机访问) 与 stdin (流不可 seek)。"""

    def __init__(self, rows: List[Dict]):
        self._data = rows
        self.total = len(rows)

    def window(self, offset: int, size: int) -> List[Dict]:
        return self._data[max(0, offset) : offset + size]


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
