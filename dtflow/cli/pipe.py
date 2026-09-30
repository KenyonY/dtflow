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

from ..i18n import t
from ..streaming import StreamingTransformer, open_stream
from .common import _check_file_format, _require_file_exists
from .output import (
    die_io_error,
    emit_action,
    emit_data,
    emit_ndjson,
    get_state,
    is_stderr_tty,
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
        die_io_error(e, operation=t("Read", "读取"), path=input_label(filename))


def load_rows(filename: str) -> List[Dict]:
    """需要全量内存的命令 (stats/validate/split/…) 用: 支持 ``-``, 读错即结构化退出。"""
    st = open_input(filename)
    try:
        return st.collect()
    except Exception as e:
        die_io_error(e, operation=t("Read", "读取"), path=input_label(filename))


def emit_rows(st: StreamingTransformer, *, fmt: Optional[str] = None, action: str = "") -> int:
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
            t(
                f"[yellow]… Terminal preview shows only the first {limit} rows (input not fully "
                f"consumed, total unknown); for everything use -o FILE, pipe with |, "
                f"or --format=ndjson[/yellow]",
                f"[yellow]… 终端预览只显示前 {limit} 条 (未消费完, 总数未知); 取全量请 -o FILE 落盘、"
                f"| 接下游, 或 --format=ndjson[/yellow]",
            )
        )
    elif action:
        log(
            t(f"[dim]{action}: {count} rows written[/dim]", f"[dim]{action}: 输出 {count} 条[/dim]")
        )
    return count


def check_output_path(output: str) -> None:
    """落盘前把格式问题挡在读数据之前: 不支持压缩的格式带 .gz 后缀 → 用法错误。"""
    from ..storage.io import _detect_format, is_gz
    from .output import die_usage

    p = Path(output)
    if is_gz(p) and _detect_format(p) not in ("jsonl", "json"):
        die_usage(
            t(
                f"{p.name}: only .jsonl.gz / .json.gz support compressed output",
                f"{p.name}: 只有 .jsonl.gz / .json.gz 支持压缩写出",
            ),
            suggestion=t("Use .jsonl.gz instead", "改用 .jsonl.gz"),
        )


def save_rows(st: StreamingTransformer, output: str) -> int:
    """落盘: 一律先写同目录临时文件, 成功后原子替换 —— 中途失败不留半截文件,
    输出与输入同一文件时也因此可以流式读写。只有 OSError 才是 io_error, 其它异常原样抛给调用方定性。"""
    from ..storage.io import _detect_format

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if _detect_format(out) == "flaxkv":
        # flaxkv 是目录型 DB, 没法用临时文件替换; 临时 stem 会留下一个打开的 DB 把锁占住
        try:
            return st.save(output, show_progress=is_stderr_tty())
        except OSError as e:
            die_io_error(e, operation=t("Save", "保存"), path=output)
    fd, tmp = tempfile.mkstemp(suffix="".join(out.suffixes), prefix=".tmp_", dir=out.parent)
    os.close(fd)
    try:
        # 进度条只在 stderr 是终端时画: 重定向到文件时那行 "⠋ 处理中" 会混进结构化错误前面
        n = st.save(tmp, show_progress=is_stderr_tty())
        shutil.move(tmp, output)
        return n
    except OSError as e:
        die_io_error(e, operation=t("Save", "保存"), path=output)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_output(
    st: StreamingTransformer,
    output: Optional[str],
    *,
    action: str,
    inputs: Iterable[str],
    stats: Optional[Dict] = None,
    extra: Optional[Dict] = None,
) -> int:
    """无 ``-o`` (或 ``-o -``) → stdout 数据流 (摘要只走 stderr, 绝不污染 stdout);
    有 ``-o`` → 落盘并按 emit_action 约定输出动作摘要。
    读写过程中的非 IO 异常 (如 --strict 下的求值失败) 统一定性为 ``<action>_failed``, 退出码 1。"""
    import typer

    from .output import die

    if output == STDIN:
        output = None
    try:
        if output is None:
            return emit_rows(st, action=action)
        check_output_path(output)
        n = save_rows(st, output)
    except typer.Exit:
        raise
    except Exception as e:
        die(f"{action}_failed", f"{type(e).__name__}: {e}", exit_code=1)
    log(t(f"💾 Saved: {output}", f"💾 保存结果: {output}"))
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
            die_usage(
                t(
                    "-i/--in-place and -o/--output are mutually exclusive",
                    "-i/--in-place 与 -o/--output 只能二选一",
                )
            )
        if is_stdin(filename):
            die_usage(
                t("Cannot write stdin input in place", "stdin 输入无法原地写回"),
                suggestion=t("Use -o FILE or pipe the output", "用 -o FILE 或直接接管道"),
            )
        return filename
    return None if output == STDIN else output
