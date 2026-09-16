"""
dt view 的行数据源: 稳定快照、快速尾窗与 JSONL 增量追尾。

JSONL 的两种打开方式:
- 普通浏览先索引首窗口，翻页继续向后扫描；读取限定在打开时的快照高水位。
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


def _tail_offsets(path: Path, end: int, count: int, *, expected_identity=None, cancel=None):
    """反向读取 [0, end) 中最后 count 个非空行的起始偏移。"""
    if count <= 0 or end <= 0:
        return array("Q")

    # 每个块只扫描一次。跨块的行只需记住是否含非空白字节，
    # 无需反复拼接、重新扫描整个已读尾部（大窗口时会变成平方开销）。
    entries: List[int] = []
    nonempty = False
    pos = end
    with open(path, "rb") as f:
        if expected_identity is not None:
            if _identity(os.fstat(f.fileno())) != expected_identity:
                raise SourceChangedError("文件已被替换")
        while pos > 0 and len(entries) < count:
            if cancel is not None and cancel.is_set():
                return None
            start = max(0, pos - _TAIL_BLOCK)
            f.seek(start)
            block = f.read(pos - start)
            if len(block) != pos - start:
                raise SourceChangedError("文件在读取尾部期间被截断")
            cursor = len(block)
            while cursor > 0 and len(entries) < count:
                newline = block.rfind(b"\n", 0, cursor)
                nonempty = nonempty or bool(block[newline + 1 : cursor].strip())
                if newline < 0:
                    break
                if nonempty:
                    entries.append(start + newline + 1)
                nonempty = False
                cursor = newline
            pos = start
        if pos == 0 and nonempty and len(entries) < count:
            entries.append(0)
    return array("Q", reversed(entries))


def _scan_offsets(
    path: Path,
    start: int,
    end: int,
    expected_identity: Tuple[int, int],
    progress_cb: Optional[Callable[[int], None]] = None,
    cancel=None,
    max_rows: Optional[int] = None,
) -> Optional[Tuple[array, int]]:
    """建立 [start, end) 非空行偏移，返回偏移和续扫位置；None 表示取消。"""
    offsets = array("Q")
    with open(path, "rb") as f:
        if _identity(os.fstat(f.fileno())) != expected_identity:
            raise SourceChangedError("文件已被替换")
        f.seek(start)
        pos = start
        while pos < end and (max_rows is None or len(offsets) < max_rows):
            if cancel is not None and cancel.is_set():
                return None
            line_start = pos
            line = f.readline(end - pos)
            if not line:
                raise SourceChangedError("文件在扫描期间被截断")
            pos += len(line)
            if line.strip():
                offsets.append(line_start)
                if progress_cb is not None and len(offsets) % 5000 == 0:
                    progress_cb(len(offsets))
        if os.fstat(f.fileno()).st_size < end:
            raise SourceChangedError("文件在扫描期间被截断")
    if progress_cb is not None:
        progress_cb(len(offsets))
    return offsets, pos


class RowSource:
    """行数据源基类。"""

    total: int = 0
    fully_indexed: bool = True
    follow: bool = False
    path: Optional[Path] = None

    def parallel_ranges(self, chunks: int):
        """可并行扫描的字节分片 [(起始字节, 结束字节, 首行全局行号)]; 不支持返回 None。"""
        return None

    @property
    def total_known(self) -> bool:
        return self.fully_indexed

    @property
    def has_unindexed_history(self) -> bool:
        return False

    @property
    def has_unindexed_tail(self) -> bool:
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

    def ensure_rows(self, count: int, progress_cb=None, cancel=None) -> bool:
        return True

    def window_is_indexed(self, offset: int, size: int) -> bool:
        return True

    def ensure_window(self, offset: int, size: int, progress_cb=None, cancel=None) -> bool:
        return self.ensure_rows(offset + size, progress_cb=progress_cb, cancel=cancel)

    def ensure_tail(self, size: int, cancel=None) -> bool:
        return self.ensure_index(cancel=cancel)

    def poll(self) -> SourceUpdate:
        return SourceUpdate("unchanged", [], [])

    def snapshot_info(self) -> Dict:
        return {"rows": self.total}


class _JsonlSource(RowSource):
    """JSONL 字节偏移数据源，支持稳定快照和 follow。"""

    def __init__(
        self,
        path: Path,
        tail_size: Optional[int] = None,
        follow: bool = False,
        initial_size: Optional[int] = None,
    ):
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
        self._indexed_end = 0
        self._known_total: Optional[int] = None
        self._suffix_offsets = array("Q")

        if tail_size is None:
            self._read_end = st.st_size
            scanned = _scan_offsets(path, 0, self._read_end, self._identity, max_rows=initial_size)
            assert scanned is not None
            self._offsets, self._indexed_end = scanned
            self.fully_indexed = self._indexed_end == self._read_end
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
    def path(self) -> Path:
        return self._path

    def parallel_ranges(self, chunks: int):
        """按行号等分成 chunks 段, 换算成字节区间 —— 每段都从完整行首开始。

        只在全量索引就绪后可用: 分片起点取自偏移表, 行号由此天然对齐, 子进程各扫各的
        区间即可给出全局行号, 不必回传行内容。
        """
        with self._lock:
            if not self.fully_indexed or self.total <= 0 or chunks < 1:
                return None
            n = min(chunks, self.total)
            step = -(-self.total // n)  # 向上取整, 保证段数不超过 n
            bounds = list(range(0, self.total, step)) + [self.total]
            return [
                (
                    self._offsets[a],
                    self._offsets[b] if b < self.total else self._read_end,
                    a,
                )
                for a, b in zip(bounds[:-1], bounds[1:], strict=False)
            ]

    @property
    def has_unindexed_history(self) -> bool:
        return not self.fully_indexed and self._tail_size is not None

    @property
    def has_unindexed_tail(self) -> bool:
        return not self.fully_indexed and self._tail_size is None

    @property
    def total_known(self) -> bool:
        return self.fully_indexed or self._known_total is not None

    def window_is_indexed(self, offset: int, size: int) -> bool:
        with self._lock:
            if not self.has_unindexed_tail:
                return True
            end = offset + size
            if self.total_known:
                end = min(end, self.total)
            return end <= len(self._offsets) or (
                self._known_total is not None
                and bool(self._suffix_offsets)
                and offset >= self.total - len(self._suffix_offsets)
            )

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
            if not self.window_is_indexed(offset, size):
                raise RuntimeError("窗口偏移尚未建立")
            if self._known_total is not None and offset >= self.total - len(self._suffix_offsets):
                start = offset - (self.total - len(self._suffix_offsets))
                picked = self._suffix_offsets[start : start + max(0, end - offset)]
            else:
                picked = self._offsets[offset:end]
        return self._rows_for_offsets(picked)

    def row_numbers(self, offset: int, size: int) -> List[int]:
        with self._lock:
            end = min(offset + size, self.total)
            if not self.has_unindexed_history:
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
            picked = []
            suffix_start = self.total - len(self._suffix_offsets)
            for i in indices:
                if not 0 <= i < self.total:
                    continue
                if i < len(self._offsets):
                    picked.append(self._offsets[i])
                elif i >= suffix_start:
                    picked.append(self._suffix_offsets[i - suffix_start])
                else:
                    raise RuntimeError("行偏移尚未建立")
        return self._rows_for_offsets(picked)

    def ensure_index(self, progress_cb=None, cancel=None) -> bool:
        """在当前完整行高水位建立全量索引。"""
        with self._operation_lock:
            return self._ensure_index(progress_cb=progress_cb, cancel=cancel)

    def ensure_rows(self, count: int, progress_cb=None, cancel=None) -> bool:
        """只把正向索引延伸到所需窗口，不读取后面的文件。"""
        with self._operation_lock:
            if not self.has_unindexed_tail or count <= len(self._offsets):
                return True
            return self._ensure_index(
                progress_cb=progress_cb, cancel=cancel, max_rows=count - len(self._offsets)
            )

    def ensure_window(self, offset: int, size: int, progress_cb=None, cancel=None) -> bool:
        if self.window_is_indexed(offset, size):
            return True
        with self._lock:
            suffix_start = self.total - len(self._suffix_offsets)
            from_tail = (
                self._known_total is not None
                and bool(self._suffix_offsets)
                and suffix_start - offset < offset + size - len(self._offsets)
            )
        if from_tail:
            return self.ensure_tail(self.total - offset, cancel=cancel)
        return self.ensure_rows(offset + size, progress_cb=progress_cb, cancel=cancel)

    def ensure_tail(self, size: int, cancel=None) -> bool:
        """精确计数后只建立所需尾窗偏移，保留已读的前缀索引。"""
        from ...utils.jsonl import count_jsonl_rows

        if self._tail_size is not None:
            return self.ensure_index(cancel=cancel)
        with self._operation_lock:
            if self.fully_indexed:
                return True
            with self._lock:
                total = self._known_total
                end = self._read_end
                expected = self._identity
            if total is None:
                total = count_jsonl_rows(
                    self._path, end=end, expected_identity=expected, cancel=cancel
                )
                if total is None:
                    return False
            size = min(size, total)
            needed = max(0, size - len(self._suffix_offsets))
            if needed:
                end = self._suffix_offsets[0] if self._suffix_offsets else end
                offsets = _tail_offsets(
                    self._path, end, needed, expected_identity=expected, cancel=cancel
                )
                if offsets is None:
                    return False
                if len(offsets) != needed:
                    raise SourceChangedError("文件在读取尾窗期间发生变化")
            else:
                offsets = array("Q")
            with self._open_checked():
                pass
            if cancel is not None and cancel.is_set():
                return False
            with self._lock:
                offsets.extend(self._suffix_offsets)
                self._suffix_offsets = offsets
                self._known_total = self.total = total
                self._join_index_ends()
            return True

    def _join_index_ends(self) -> None:
        """前后索引相接时合并；重叠行只保留一次。调用方持有 _lock。"""
        if self._known_total is None or not self._suffix_offsets:
            return
        start = self.total - len(self._suffix_offsets)
        if len(self._offsets) >= start:
            self._offsets.extend(self._suffix_offsets[len(self._offsets) - start :])
            self._suffix_offsets = array("Q")
            self._indexed_end = self._read_end
            self.fully_indexed = True

    def _ensure_index(self, progress_cb=None, cancel=None, max_rows=None) -> bool:
        with self._lock:
            if self.fully_indexed:
                return True
            end = self._read_end
            expected = self._identity
            start = self._indexed_end if self._tail_size is None else 0
            if self._suffix_offsets:
                end = self._suffix_offsets[0]

        scanned = _scan_offsets(
            self._path,
            start,
            end,
            expected,
            progress_cb=progress_cb,
            cancel=cancel,
            max_rows=max_rows,
        )
        if scanned is None:
            return False
        offsets, indexed_end = scanned

        with self._lock:
            if self._identity != expected:
                raise SourceChangedError("建索引期间发生了日志轮转")
            if self._tail_size is None:
                self._offsets.extend(offsets)
            else:
                self._offsets = offsets
            self._indexed_end = indexed_end
            self._labels = array("q")
            self.fully_indexed = indexed_end == self._read_end
            self.total = self._known_total if self._known_total is not None else len(self._offsets)
            self._join_index_ends()
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

        scanned = _scan_offsets(self._path, start, complete_end, expected)
        assert scanned is not None
        new_offsets, _ = scanned
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


def open_source(
    filepath: Path,
    tail_size: Optional[int] = None,
    follow: bool = False,
    initial_size: Optional[int] = None,
) -> RowSource:
    """按扩展名选择数据源实现。"""
    if filepath.suffix.lower() in (".jsonl", ".ndjson"):
        return _JsonlSource(filepath, tail_size=tail_size, follow=follow, initial_size=initial_size)
    from ...storage.io import load_data

    return _MemorySource(load_data(str(filepath)))
