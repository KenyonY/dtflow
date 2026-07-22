"""
dt view: 交互式表格 + 详情浏览器 (Textual TUI)。

用于高效查看训练数据: 表格扫视 + 详情按格式渲染 (对话气泡/dpo对比/alpaca分段)。
大文件通过"偏移索引 + 窗口翻页"浏览: 只 parse 当前窗口 (--cap 行), TUI 内 ] / [ 翻窗口、: 跳行。
管道 (dt view -): 从 stdin 读 NDJSON 全量入内存, 适合看处理结果的一小撮。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

# 单个窗口默认加载行数; 只 parse 这么多行, 其余靠偏移索引按需翻页。
# 首屏/翻页耗时随行数线性 (add_row 成本), 主瓶颈的逐格 measure 已由 FastDataTable
# 消除; 1 万行是流畅度与窗口内搜索/排序覆盖面的平衡点, 可用 --cap 调整。
_DEFAULT_CAP = 10000


def _run_tui(
    source,
    cap: int,
    offset: int,
    format_hint: Optional[str],
    title: str,
    where: Optional[List[str]] = None,
    search: Optional[str] = None,
    sort: Optional[str] = None,
    filepath: Optional[str] = None,
) -> None:
    """公共 TUI 启动: 取首窗口 → 检测格式 → 起 ViewApp。"""
    if source.total == 0:
        print("无数据。", file=sys.stderr)
        raise SystemExit(1)

    offset = min(max(0, offset), source.total - 1)
    window = source.window(offset, cap)

    from .render import detect_format

    fmt = format_hint or detect_format(window)

    from .app import ViewApp

    ViewApp(
        source,
        window,
        offset,
        cap,
        fmt,
        title,
        where=where,
        search=search,
        sort=sort,
        filepath=filepath,
    ).run()


def _view_stdin(
    cap: int,
    format_hint: Optional[str],
    where: Optional[List[str]] = None,
    search: Optional[str] = None,
    sort: Optional[str] = None,
) -> None:
    """dt view -: 先读完 stdin 数据, 再把 fd 0 重定向到 /dev/tty 供 TUI 读键盘。

    管道占用了 stdin 作数据流, 而 Textual 硬编码从 fd 0 读键盘 → 二者冲突;
    读完数据后 dup2 /dev/tty 到 fd 0 化解 (Textual 输出本就走 stderr, stdout 不受影响)。
    """
    import os

    from .source import read_stdin_source

    source = read_stdin_source()  # 此刻 fd 0 仍是管道
    if source.total == 0:
        print("stdin 无数据。", file=sys.stderr)
        raise SystemExit(1)

    try:
        tty = open("/dev/tty")  # noqa: SIM115  (需长期持有到 TUI 退出)
    except OSError:
        print("dt view - 需要交互式终端, 但无法打开 /dev/tty。", file=sys.stderr)
        raise SystemExit(2) from None
    os.dup2(tty.fileno(), 0)  # fd 0 → tty, Textual 从此读真实键盘

    # 管道数据已全在内存, offset 无意义 (从头开始; 可在 TUI 内 : 跳行)
    # filepath 留空: 管道输入没有可复现的源文件, C 复制命令会据此提示改用导出
    _run_tui(source, cap, 0, format_hint, "<stdin>", where=where, search=search, sort=sort)


def view(
    filename: str,
    cap: int = _DEFAULT_CAP,
    offset: int = 0,
    format_hint: Optional[str] = None,
    where: Optional[List[str]] = None,
    search: Optional[str] = None,
    sort: Optional[str] = None,
) -> None:
    """启动 dt view TUI。filename 为 - 时从 stdin 读 (管道模式)。

    where/search/sort: 启动即带上的约束, 与 TUI 内按 f / / / s 完全同义 (同一条扫描管线),
    于是 C 复制出来的命令粘回终端能还原当时的视图。
    """
    if filename == "-":
        _view_stdin(cap, format_hint, where=where, search=search, sort=sort)
        return

    filepath = Path(filename)
    if not filepath.exists():
        print(f"文件不存在: {filename}", file=sys.stderr)
        raise SystemExit(3)

    if not sys.stdout.isatty():
        print("dt view 需要交互式终端 (TTY)。管道/重定向请用 dt head/sample。", file=sys.stderr)
        raise SystemExit(2)

    from .source import open_source

    _run_tui(
        open_source(filepath),
        cap,
        offset,
        format_hint,
        filepath.name,
        where=where,
        search=search,
        sort=sort,
        filepath=filename,
    )
