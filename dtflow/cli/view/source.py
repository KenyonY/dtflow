"""
dt view 的行数据源: 稳定快照、快速尾窗与 JSONL 增量追尾。

JSONL 的两种打开方式:
- 普通浏览在打开时建索引，之后所有读取都限定在该快照高水位。
- 尾窗 / follow 先反向读取最后 N 行，历史导航或全量操作时再按需建索引。

follow 只提交以换行结束的完整记录；正在写的尾行保持 pending，不会被
误报成坏 JSON。偏移用 uint64 数组，避免每行一个 Python int 的额外内存。
"""

from __future__ import annotations

import json
import os
import threading
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple

import orjson

PARSE_ERROR_FIELD = "_parse_error"
RAW_LINE_FIELD = "_raw_line"
_RAW_KEEP = 500
_TAIL_BLOCK = 256 * 1024


class SourceChangedError(OSError):
    """快照所属的文件代次已经变化。"""


@dataclass(frozen=True)
class SourceUpdate:
    """follow 轮询结果。row_numbers 与 rows 一一对齐。"""

    kind: str
    rows: List[Dict]
    row_numbers: List[int]
    added: int = 0
    pending: bool = False
    generation: int = 0


def _bad_row(line: bytes, err: Exception) -> Dict:
    """坏行 → 占位行, 而不是抛出。"""
    return {
        PARSE_ERROR_FIELD: f"{type(err).__name__}: {err}",
        RAW_LINE_FIELD: line.decode("utf-8", errors="replace")[:_RAW_KEEP],
    }


def _loads(line: bytes) -> Dict:
    """orjson 优先, 失败回退标准 json；两者失败时返回可见占位行。"""
    try:
        return orjson.loads(line)
    except orjson.JSONDecodeError:
        try:
            return json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            return _bad_row(line, e)


def _identity(stat_result: os.stat_result) -> Tuple[int, int]:
    return stat_result.st_dev, stat_result.st_ino


def _complete_end(path: Path, size: int) -> int:
    """返回最后一个换行之后的字节位置；没有完整行时为 0。"""
    if size <= 0:
        return 0
    with open(path, "rb") as f:
        pos = size
        while pos > 0:
            start = max(0, pos - _TAIL_BLOCK)
            f.seek(start)
            block = f.read(pos - start)
            at = block.rfind(b"\n")
            if at >= 0:
                return start + at + 1
            pos = start
    return 0


def _tail_offsets(path: Path, end: int, count: int) -> array:
    """反向读取 [0, end) 中最后 count 个非空行的起始偏移。"""
    if count <= 0 or end <= 0:
        return array("Q")

    chunks: List[bytes] = []
    start = end
    entries: List[int] = []
    while start > 0:
        new_start = max(0, start - _TAIL_BLOCK)
        with open(path, "rb") as f:
            f.seek(new_start)
            chunks.append(f.read(start - new_start))
        start = new_start
        data = b"".join(reversed(chunks))
        base = start
        if base > 0:
            cut = data.find(b"\n")
            if cut < 0:
                continue
            base += cut + 1
            data = data[cut + 1 :]

        entries = []
        cursor = base
        pieces = data.split(b"\n")
        for i, piece in enumerate(pieces):
            line_start = cursor
            cursor += len(piece) + (1 if i < len(pieces) - 1 else 0)
            if piece.strip():
                entries.append(line_start)
        if len(entries) >= count or start == 0:
            break

    return array("Q", entries[-count:])


def _scan_offsets(
    path: Path,
    start: int,
    end: int,
    expected_identity: Tuple[int, int],
    progress_cb: Optional[Callable[[int], None]] = None,
    cancel=None,
) -> Optional[array]:
    """建立 [start, end) 非空行偏移。返回 None 表示取消。"""
    offsets = array("Q")
    with open(path, "rb") as f:
        if _identity(os.fstat(f.fileno())) != expected_identity:
            raise SourceChangedError("文件已被替换")
        f.seek(start)
        pos = start
        while pos < end:
            if cancel is not None and cancel.is_set():
                return None
            line_start = pos
            line = f.readline(end - pos)
            if not line:
                break
            pos += len(line)
            if line.strip():
                offsets.append(line_start)
                if progress_cb is not None and len(offsets) % 5000 == 0:
                    progress_cb(len(offsets))
        if pos < end:
            raise SourceChangedError("文件在扫描期间被截断")
    if progress_cb is not None:
        progress_cb(len(offsets))
    return offsets


class RowSource:
    """行数据源基类。"""

    total: int = 0
    fully_indexed: bool = True
    follow: bool = False

    @property
    def has_unindexed_history(self) -> bool:
        return False

    def window(self, offset: int, size: int) -> List[Dict]:
        raise NotImplementedError

    def row_numbers(self, offset: int, size: int) -> List[int]:
        return list(range(offset, min(offset + size, self.total)))

    def iter_all(self, progress_cb: Optional[Callable[[int], None]] = None) -> Iterator[Dict]:
        raise NotImplementedError

    def rows_at(self, indices: Sequence[int]) -> List[Dict]:
        raise NotImplementedError

    def ensure_index(self, progress_cb=None, cancel=None) -> bool:
        return True

    def poll(self) -> SourceUpdate:
        return SourceUpdate("unchanged", [], [])

    def snapshot_info(self) -> Dict:
        return {"rows": self.total}


class _JsonlSource(RowSource):
    """JSONL 字节偏移数据源，支持稳定快照和 follow。"""

    def __init__(self, path: Path, tail_size: Optional[int] = None, follow: bool = False):
        self._path = path
        self.follow = follow
        self._tail_size = tail_size
        self._lock = threading.RLock()
        self._operation_lock = threading.Lock()
        st = path.stat()
        self._identity = _identity(st)
        self._observed_size = st.st_size
        self._generation = 0
        self._missing = False
        self._labels = array("q")
        self._next_relative = 0

        if tail_size is None:
            self._read_end = st.st_size
            scanned = _scan_offsets(path, 0, self._read_end, self._identity)
            assert scanned is not None
            self._offsets = scanned
            self.fully_indexed = True
        else:
            # follow 不把正在写的未换行尾巴当成记录；静态 -N 则保留
            # 无末尾换行的合法 JSONL，与原有静态语义一致。
            self._read_end = _complete_end(path, st.st_size) if follow else st.st_size
            self._offsets = _tail_offsets(path, self._read_end, tail_size)
            self.fully_indexed = bool(not self._offsets or self._offsets[0] == 0)
            if not self.fully_indexed:
                self._labels = array("q", range(-len(self._offsets), 0))
        self.total = len(self._offsets)

    @property
    def has_unindexed_history(self) -> bool:
        return not self.fully_indexed

    @property
    def generation(self) -> int:
        return self._generation

    def _open_checked(self):
        f = open(self._path, "rb")
        st = os.fstat(f.fileno())
        if _identity(st) != self._identity:
            f.close()
            raise SourceChangedError("文件已被替换")
        if st.st_size < self._read_end:
            f.close()
            raise SourceChangedError("文件已被截断")
        return f

    def _rows_for_offsets(self, offsets: Sequence[int]) -> List[Dict]:
        rows: List[Dict] = []
        if not offsets:
            return rows
        with self._open_checked() as f:
            for offset in offsets:
                if offset >= self._read_end:
                    continue
                f.seek(offset)
                line = f.readline(self._read_end - offset).strip()
                if line:
                    rows.append(_loads(line))
        return rows

    def window(self, offset: int, size: int) -> List[Dict]:
        with self._lock:
            offset = max(0, offset)
            end = min(offset + size, self.total)
            picked = self._offsets[offset:end]
        return self._rows_for_offsets(picked)

    def row_numbers(self, offset: int, size: int) -> List[int]:
        with self._lock:
            end = min(offset + size, self.total)
            if self.fully_indexed:
                return list(range(offset, end))
            return list(self._labels[offset:end])

    def iter_all(self, progress_cb: Optional[Callable[[int], None]] = None) -> Iterator[Dict]:
        if not self.fully_indexed:
            raise RuntimeError("历史偏移索引尚未建立")
        with self._lock:
            limit = self.total
            end = self._read_end
            expected = self._identity
        n = 0
        with open(self._path, "rb") as f:
            if _identity(os.fstat(f.fileno())) != expected:
                raise SourceChangedError("文件已被替换")
            pos = 0
            while pos < end and n < limit:
                line = f.readline(end - pos)
                if not line:
                    break
                pos += len(line)
                line = line.strip()
                if not line:
                    continue
                yield _loads(line)
                n += 1
                if progress_cb is not None and n % 5000 == 0:
                    progress_cb(n)
        if n < limit:
            raise SourceChangedError("文件在扫描期间被截断")
        if progress_cb is not None:
            progress_cb(n)

    def rows_at(self, indices: Sequence[int]) -> List[Dict]:
        with self._lock:
            picked = [self._offsets[i] for i in indices if 0 <= i < self.total]
        return self._rows_for_offsets(picked)

    def ensure_index(self, progress_cb=None, cancel=None) -> bool:
        """在当前完整行高水位建立全量索引。"""
        with self._operation_lock:
            return self._ensure_index(progress_cb=progress_cb, cancel=cancel)

    def _ensure_index(self, progress_cb=None, cancel=None) -> bool:
        with self._lock:
            if self.fully_indexed:
                return True
            end = self._read_end
            expected = self._identity

        scanned = _scan_offsets(
            self._path,
            0,
            end,
            expected,
            progress_cb=progress_cb,
            cancel=cancel,
        )
        if scanned is None:
            return False

        with self._lock:
            if self._identity != expected:
                raise SourceChangedError("建索引期间发生了日志轮转")
            newer = [offset for offset in self._offsets if offset >= end]
            scanned.extend(newer)
            self._offsets = scanned
            self._labels = array("q")
            self.fully_indexed = True
            self.total = len(scanned)
        return True

    def poll(self) -> SourceUpdate:
        with self._operation_lock:
            return self._poll()

    def _poll(self) -> SourceUpdate:
        if not self.follow:
            return SourceUpdate("unchanged", [], [], generation=self._generation)

        try:
            st = self._path.stat()
        except FileNotFoundError:
            self._missing = True
            return SourceUpdate("missing", [], [], generation=self._generation)

        current_identity = _identity(st)
        with self._lock:
            rotated = current_identity != self._identity or st.st_size < self._read_end
        if rotated:
            return self._reset_generation(st)

        with self._lock:
            if st.st_size == self._observed_size:
                kind = "restored" if self._missing else "unchanged"
                self._missing = False
                return SourceUpdate(
                    kind,
                    [],
                    [],
                    pending=st.st_size > self._read_end,
                    generation=self._generation,
                )

        complete_end = _complete_end(self._path, st.st_size)
        with self._lock:
            start = self._read_end
            if complete_end <= start:
                kind = "restored" if self._missing else "unchanged"
                self._missing = False
                self._observed_size = st.st_size
                return SourceUpdate(
                    kind,
                    [],
                    [],
                    pending=st.st_size > start,
                    generation=self._generation,
                )
            expected = self._identity
            was_indexed = self.fully_indexed
            old_total = self.total

        new_offsets = _scan_offsets(self._path, start, complete_end, expected)
        assert new_offsets is not None
        rows = self._rows_for_new_offsets(new_offsets, complete_end, expected)

        with self._lock:
            self._read_end = complete_end
            self._observed_size = st.st_size
            self._missing = False
            self._offsets.extend(new_offsets)
            if was_indexed:
                numbers = list(range(old_total, old_total + len(new_offsets)))
            else:
                numbers = list(range(self._next_relative, self._next_relative + len(new_offsets)))
                self._next_relative += len(new_offsets)
                self._labels.extend(numbers)
                overflow = max(0, len(self._offsets) - int(self._tail_size or 0))
                if overflow:
                    del self._offsets[:overflow]
                    del self._labels[:overflow]
            self.total = len(self._offsets)
        return SourceUpdate(
            "append",
            rows,
            numbers,
            added=len(rows),
            pending=st.st_size > complete_end,
            generation=self._generation,
        )

    def _rows_for_new_offsets(
        self, offsets: Sequence[int], end: int, expected: Tuple[int, int]
    ) -> List[Dict]:
        rows: List[Dict] = []
        with open(self._path, "rb") as f:
            if _identity(os.fstat(f.fileno())) != expected:
                raise SourceChangedError("文件已被替换")
            for offset in offsets:
                f.seek(offset)
                line = f.readline(end - offset).strip()
                if line:
                    rows.append(_loads(line))
        return rows

    def _reset_generation(self, st: os.stat_result) -> SourceUpdate:
        expected = _identity(st)
        end = _complete_end(self._path, st.st_size)
        count = int(self._tail_size or 1)
        offsets = _tail_offsets(self._path, end, count)
        with self._lock:
            self._identity = expected
            self._generation += 1
            self._read_end = end
            self._observed_size = st.st_size
            self._offsets = offsets
            self.fully_indexed = bool(not offsets or offsets[0] == 0)
            if self.fully_indexed:
                self._labels = array("q")
                numbers = list(range(len(offsets)))
            else:
                numbers = list(range(self._next_relative, self._next_relative + len(offsets)))
                self._next_relative += len(offsets)
                self._labels = array("q", numbers)
            self.total = len(offsets)
            self._missing = False
        rows = self._rows_for_offsets(offsets)
        return SourceUpdate(
            "rotation",
            rows,
            numbers,
            added=len(rows),
            pending=st.st_size > end,
            generation=self._generation,
        )

    def snapshot_info(self) -> Dict:
        with self._lock:
            return {
                "rows": self.total,
                "byte_end": self._read_end,
                "device": self._identity[0],
                "inode": self._identity[1],
                "generation": self._generation,
                "fully_indexed": self.fully_indexed,
                "follow": self.follow,
            }


class _MemorySource(RowSource):
    """全量载入内存，窗口即切片。"""

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
    """从 stdin 逐行读 NDJSON（流不可 seek，因此全量入内存）。"""
    import sys

    rows: List[Dict] = []
    for line in sys.stdin:
        line = line.strip()
        if line:
            rows.append(_loads(line.encode()))
    return _MemorySource(rows)


def open_source(filepath: Path, tail_size: Optional[int] = None, follow: bool = False) -> RowSource:
    """按扩展名选择数据源实现。"""
    if filepath.suffix.lower() in (".jsonl", ".ndjson"):
        return _JsonlSource(filepath, tail_size=tail_size, follow=follow)
    from ...storage.io import load_data

    return _MemorySource(load_data(str(filepath)))
