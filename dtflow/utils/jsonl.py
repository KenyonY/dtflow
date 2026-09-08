"""JSONL 非空记录计数，不解析 JSON，也不建立逐行偏移。"""

from __future__ import annotations

import os
import threading
from pathlib import Path

_CHECK_BLOCK = 8 * 1024 * 1024
# Polars 1.36 的自动解压签名。这里统计的是原始 JSONL 字节，不能解压后再计数。
_COMPRESSION_PREFIXES = (b"\x1f\x8b", b"x\x01", b"x^", b"x\x9c", b"x\xda", b"\x28\xb5\x2f\xfd")


def count_jsonl_rows(path: Path, *, end=None, expected_identity=None, cancel=None):
    """统计固定字节快照中的非空行；取消返回 None。

    Polars 的空 schema COUNT(*) 路径只计数，不对坏 JSON 做类型推断。
    已追加的文件、Polars 不支持的输入以及特殊空白字符走精确的有界计数，
    保持与 bytes.strip() 一致，并包含未以换行结束的最后一行。
    """
    import polars as pl

    cancel = cancel if cancel is not None else threading.Event()
    with open(path, "rb") as f:
        before = os.fstat(f.fileno())
        if expected_identity is not None:
            if (before.st_dev, before.st_ino) != expected_identity:
                raise OSError("文件已被替换")
        end = before.st_size if end is None else end
        if before.st_size < end:
            raise OSError("文件已被截断")
        if cancel.is_set():
            return None
        if not end:
            return 0

        total = None
        prefix = f.read(min(4, end))
        f.seek(0)
        if before.st_size == end and not prefix.startswith(_COMPRESSION_PREFIXES):
            try:
                query = pl.scan_ndjson(f, schema={}).select(pl.len()).collect(background=True)
                try:
                    while not cancel.is_set():
                        result = query.fetch()
                        if result is not None:
                            total = result.item()
                            break
                        cancel.wait(0.01)
                finally:
                    if cancel.is_set():
                        query.cancel()
            except (pl.exceptions.PolarsError, OSError):
                # 例如以压缩格式 magic bytes 开头的坏行，Polars 会尝试解压。
                # 浏览器仍必须把它作为一行保留，不能计数失败或静默丢弃。
                total = None

        if cancel.is_set():
            return None
        after = os.fstat(f.fileno())
        if after.st_size < end:
            raise OSError("文件在计数期间被截断")
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            total = None

        if total is not None:
            # Polars 的空行规则不含 VT/FF；只需快速检测这两个罕见字节，
            # 常见 JSONL 不做 Python 逐行循环。读取始终限制在快照末尾。
            f.seek(0)
            remaining = end
            while remaining:
                if cancel.is_set():
                    return None
                block = f.read(min(_CHECK_BLOCK, remaining))
                if not block:
                    raise OSError("文件在计数期间被截断")
                remaining -= len(block)
                if b"\v" in block or b"\f" in block:
                    total = None
                    break

        if total is None:
            f.seek(0)
            pos = total = 0
            while pos < end:
                if cancel.is_set():
                    return None
                line = f.readline(end - pos)
                if not line:
                    raise OSError("文件在计数期间被截断")
                pos += len(line)
                total += bool(line.strip())
        if os.fstat(f.fileno()).st_size < end:
            raise OSError("文件在计数期间被截断")
        return None if cancel.is_set() else total
