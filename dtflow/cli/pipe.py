"""
CLI 管道层: 所有数据命令共用的输入/输出约定。

    FILE 为 ``-`` → 从 stdin 读 NDJSON;  无 ``-o`` → 数据写 stdout (NDJSON)

于是 ``dt filter a.jsonl "..." | dt select - "..." | dt head -`` 能串起来。
stdout 只放数据, 进度/摘要/警告一律 stderr (见 output.py 的总约定)。
"""

from __future__ import annotations

import itertools
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ..i18n import t
from ..streaming import StreamingTransformer, expand_inputs, open_stream
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
)

STDIN = "-"
# stdout 是终端且没说要什么格式时, 只展示前这么多行: 大文件全量刷屏对谁都没用,
# 重定向/管道即非 TTY, 不受影响
TTY_PREVIEW_LIMIT = 50


def is_stdin(filename: str) -> bool:
    return filename == STDIN


def input_label(filename: str) -> str:
    return "<stdin>" if is_stdin(filename) else filename


def input_files(filename: str) -> List[str]:
    """FILE 参数实际展开成的文件列表 (目录 / glob), 供校验与 action 摘要用; stdin → ["<stdin>"]。"""
    if is_stdin(filename):
        return [input_label(filename)]
    try:
        return expand_inputs(filename)
    except FileNotFoundError as e:
        die_io_error(e, operation=t("Read", "读取"), path=filename)


def open_input(filename: str) -> StreamingTransformer:
    """``-`` → stdin NDJSON 流; 文件 → 存在/格式校验后, 流式格式 load_stream, 其余全量包成流;
    目录 / 引号 glob → 逐个校验后首尾相接 (见 streaming.expand_inputs)。"""
    if not is_stdin(filename):
        for f in input_files(filename):
            path = Path(f)
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
    explicit = bool(fmt or get_state().fmt)
    # 本模块的 is_stdout_tty 是可替换的 (测试模拟终端), 不经 resolve_format 里那份
    fmt = fmt or get_state().fmt or ("table" if is_stdout_tty() else "ndjson")
    if fmt in ("json", "csv"):
        rows = st.collect()
        emit_data(rows, format=fmt)
        st.report_errors()
        return len(rows)

    limit = None if (explicit or not is_stdout_tty()) else TTY_PREVIEW_LIMIT
    if fmt == "table":
        # 表格是"看"的形态: 终端里默认给它, 且只看前 limit 行; 显式 --format=table 则全量
        rows = list(itertools.islice(st, limit + 1 if limit is not None else None))
        truncated = limit is not None and len(rows) > limit
        rows = rows[:limit] if truncated else rows
        emit_table(rows)
        st.report_errors()
        _report_count(len(rows), truncated, limit, action)
        return len(rows)

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
    _report_count(count, truncated, limit, action)
    return count


def _report_count(count: int, truncated: bool, limit: Optional[int], action: str) -> None:
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


def emit_table(rows: List[Dict], *, start_no: int = 0) -> None:
    """把若干行画成 rich 表格写到 stdout —— 列目录与单元格和 dt view 同源 (render.build_columns /
    row_cells): 对话数据出 turns/roles/first_user/chars/calls 派生列, 其余数据出全部顶层字段。

    这是 view 的表格下放到非交互场景: dt filter … 在终端里直接看见和 view 一样的表。
    列宽自己算 (rich 的自动压缩会把窄列挤没): 数值列取自然宽, 文本列封顶后按比例压缩,
    还装不下就从右侧藏列并在 stderr 说明 —— 静态输出没有横向滚动, 藏比挤成一个字符诚实。
    """
    import sys

    from rich import box
    from rich.cells import cell_len
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    from .output import use_color
    from .view.render import (
        NUMERIC_DERIVED,
        build_columns,
        default_visible_columns,
        detect_format,
        row_cells,
    )

    if not rows:
        log(t("[dim](no rows)[/dim]", "[dim](无数据)[/dim]"))
        return
    fmt = detect_format(rows)
    cols = default_visible_columns(build_columns(rows, fmt), fmt)
    cells = [row_cells(i, row, fmt, cols, row_no=start_no + i) for i, row in enumerate(rows)]
    tty = is_stdout_tty()
    styled = tty and use_color()
    console = Console(
        file=sys.stdout,
        force_terminal=styled,
        no_color=not styled,
        width=shutil.get_terminal_size((120, 24)).columns
        if tty
        else int(os.environ.get("COLUMNS", "120")),
        highlight=False,
    )

    # 列宽: 数值/行号列按内容; 文本列封顶 (长文本 60, 其余 40) 再按比例压到能放下
    fixed = {"#", *NUMERIC_DERIVED}
    long_text = {"first_user", "prompt", "instruction"}
    widths = {}
    for j, c in enumerate(cols):
        natural = max(cell_len(c), *(cell_len(r[j]) for r in cells))
        cap = None if c in fixed else (60 if c in long_text else 40)
        widths[c] = natural if cap is None else min(natural, cap)
    pad = 2  # 每列左右各 1 格 padding

    def total(names):
        return sum(widths[c] + pad for c in names)

    shown = list(cols)
    avail = console.width
    if total(shown) > avail:
        flex = [c for c in shown if c not in fixed]
        need = total(shown) - avail
        room = sum(widths[c] - 6 for c in flex)  # 文本列最窄压到 6
        if flex and room > 0:
            ratio = min(1.0, need / room)
            for c in flex:
                widths[c] -= int((widths[c] - 6) * ratio)
        while len(shown) > 1 and total(shown) > avail:
            shown.pop()
    hidden = len(cols) - len(shown)

    table = Table(
        box=box.SIMPLE_HEAD, header_style="bold cyan", pad_edge=False, show_edge=False, expand=False
    )
    for c in shown:
        table.add_column(
            c,
            width=widths[c],
            justify="right" if c in fixed else "left",
            no_wrap=True,
            overflow="ellipsis",
        )
    for r in cells:
        table.add_row(*(Text(r[j]) for j in range(len(shown))))
    try:
        console.print(table)
    except BrokenPipeError:
        return
    if hidden:
        log(
            t(
                f"[dim]… {hidden} more column(s) hidden (narrow terminal): {', '.join(cols[len(shown) :])};"
                f" widen the terminal, or use dt view / --format=ndjson[/dim]",
                f"[dim]… 终端太窄, 隐藏了 {hidden} 列: {', '.join(cols[len(shown) :])};"
                f" 拉宽终端, 或用 dt view / --format=ndjson[/dim]",
            )
        )


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
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        die_io_error(e, operation=t("Save", "保存"), path=output)
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
        input_files=[lbl for f in inputs for lbl in input_files(f)],
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
        if len(input_files(filename)) > 1:
            die_usage(
                t(
                    "A directory / glob input cannot be written in place",
                    "目录/glob 输入无法原地写回",
                ),
                suggestion=t("Use -o FILE to write one file", "用 -o FILE 落到一个文件"),
            )
        return filename
    return None if output == STDIN else output
