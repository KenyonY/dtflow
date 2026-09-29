"""
CLI 管道层: 所有数据命令共用的输入/输出约定。

    FILE 为 ``-`` → 从 stdin 读 NDJSON;  无 ``-o`` → 数据写 stdout (NDJSON)

于是 ``dt filter a.jsonl "..." | dt select - "..." | dt head -`` 能串起来。
stdout 只放数据, 进度/摘要/警告一律 stderr (见 output.py 的总约定)。
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ..streaming import StreamingTransformer, open_stream
from .common import _check_file_format, _require_file_exists
from .output import (
    die_io_error,
    emit_action,
    emit_data,
    emit_ndjson,
    get_state,
    is_stdout_tty,
    log,
    resolve_format,
)

STDIN = "-"
# stdout 是终端且没说要什么格式时, 只展示前这么多行: 大文件全量刷屏对谁都没用,
# 重定向/管道即非 TTY, 不受影响
TTY_PREVIEW_LIMIT = 50


def is_stdin(filename: str) -> bool:
    return filename == STDIN


def input_label(filename: str) -> str:
    return "<stdin>" if is_stdin(filename) else filename


def open_input(filename: str) -> StreamingTransformer:
    """``-`` → stdin NDJSON 流; 文件 → 存在/格式校验后, 流式格式 load_stream, 其余全量包成流。"""
    if not is_stdin(filename):
        path = Path(filename)
        _require_file_exists(path)
        _check_file_format(path)
    try:
        return open_stream(filename)
    except Exception as e:
        die_io_error(e, operation="读取", path=input_label(filename))


def load_rows(filename: str) -> List[Dict]:
    """需要全量内存的命令 (stats/validate/split/…) 用: 支持 ``-``, 读错即结构化退出。"""
    st = open_input(filename)
    try:
        return st.collect()
    except Exception as e:
        die_io_error(e, operation="读取", path=input_label(filename))


def emit_rows(st: StreamingTransformer, *, fmt: Optional[str] = None) -> int:
    """把数据流写到 stdout, 返回行数。

    默认 NDJSON 逐行流式; 显式 --format=json/csv 需要整体, 先 collect。
    stdout 是 TTY 且未显式指定格式时只出前 TTY_PREVIEW_LIMIT 行并提示。
    """
    fmt = resolve_format(fmt, default_for_tty="table")
    if fmt in ("json", "csv"):
        rows = st.collect()
        emit_data(rows, format=fmt)
        st.report_errors()
        return len(rows)

    explicit = bool(get_state().fmt)
    limit = None if (explicit or not is_stdout_tty()) else TTY_PREVIEW_LIMIT
    count = 0
    truncated = False

    def counted():
        nonlocal count, truncated
        for item in st:
            if limit is not None and count >= limit:
                truncated = True
                return
            count += 1
            yield item

    emit_ndjson(counted())
    st.report_errors()
    if truncated:
        log(
            f"[yellow]… 已显示前 {limit} 条 (终端预览); 取全量请 -o FILE 落盘、"
            f"| 接下游, 或 --format=ndjson[/yellow]"
        )
    return count


def save_rows(st: StreamingTransformer, output: str) -> int:
    """落盘; 输出与输入同一文件时先写同目录临时文件再原子替换 (流式读写不能同时开一个文件)。"""
    out = Path(output)
    src = st._source_path
    same = src is not None and Path(src).resolve() == out.resolve()
    if not same:
        try:
            return st.save(output)
        except Exception as e:
            die_io_error(e, operation="保存", path=output)
    fd, tmp = tempfile.mkstemp(suffix="".join(out.suffixes), prefix=".tmp_", dir=out.parent)
    os.close(fd)
    try:
        n = st.save(tmp)
        shutil.move(tmp, output)
        return n
    except Exception as e:
        if os.path.exists(tmp):
            os.unlink(tmp)
        die_io_error(e, operation="保存", path=output)


def write_output(
    st: StreamingTransformer,
    output: Optional[str],
    *,
    action: str,
    inputs: Iterable[str],
    stats: Optional[Dict] = None,
    extra: Optional[Dict] = None,
) -> int:
    """无 ``-o`` → stdout 数据流 (摘要只走 stderr, 绝不污染 stdout);
    有 ``-o`` → 落盘并按 emit_action 约定输出动作摘要。"""
    if output is None:
        n = emit_rows(st)
        log(f"[dim]{action}: 输出 {n} 条[/dim]")
        return n
    n = save_rows(st, output)
    log(f"💾 保存结果: {output}")
    emit_action(
        action,
        input_files=[input_label(f) for f in inputs],
        output=output,
        stats={**(stats or {}), "output_rows": n},
        extra=extra,
    )
    return n


def resolve_output(filename: str, output: Optional[str], in_place: bool) -> Optional[str]:
    """clean/dedupe 的三态输出: -i 原地 / -o 文件 / 都没有 → stdout (None)。"""
    from .output import die_usage

    if in_place:
        if output:
            die_usage("-i/--in-place 与 -o/--output 只能二选一")
        if is_stdin(filename):
            die_usage("stdin 输入无法原地写回", suggestion="用 -o FILE 或直接接管道")
        return filename
    return output
