"""
dt view: 交互式表格 + 详情浏览器 (Textual TUI)。

用于高效查看训练数据: 表格扫视 + 详情按格式渲染 (对话气泡/dpo对比/alpaca分段)。
大文件通过"偏移索引 + 窗口翻页"浏览: 只 parse 当前窗口 (--cap 行), TUI 内 ] / [ 翻窗口、: 跳行。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# 单个窗口默认加载行数; 只 parse 这么多行, 其余靠偏移索引按需翻页。
_DEFAULT_CAP = 20000


def view(
    filename: str,
    cap: int = _DEFAULT_CAP,
    offset: int = 0,
    format_hint: Optional[str] = None,
) -> None:
    """启动 dt view TUI。"""
    filepath = Path(filename)
    if not filepath.exists():
        print(f"文件不存在: {filename}", file=sys.stderr)
        raise SystemExit(3)

    if not sys.stdout.isatty():
        print("dt view 需要交互式终端 (TTY)。管道/重定向请用 dt head/sample。", file=sys.stderr)
        raise SystemExit(2)

    from .source import open_source

    source = open_source(filepath)
    if source.total == 0:
        print("文件为空。", file=sys.stderr)
        raise SystemExit(1)

    offset = min(max(0, offset), source.total - 1)
    window = source.window(offset, cap)

    from .render import detect_format

    fmt = format_hint or detect_format(window)

    from .app import ViewApp

    ViewApp(source, window, offset, cap, fmt, filepath.name).run()
