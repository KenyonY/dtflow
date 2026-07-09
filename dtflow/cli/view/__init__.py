"""
dt view: 交互式表格 + 详情浏览器 (Textual TUI)。

用于高效查看训练数据: 表格扫视 + 详情按格式渲染 (对话气泡/dpo对比/alpaca分段)。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

# 大文件默认只加载前 N 行 (窗口), 避免 OOM; 状态栏会提示已截断。
_DEFAULT_CAP = 20000


def _load_rows(filepath: Path, cap: int) -> tuple[List[dict], bool]:
    """加载数据行, 超过 cap 则截断。返回 (rows, truncated)。"""
    ext = filepath.suffix.lower()
    if ext in (".jsonl", ".ndjson"):
        from ...streaming import load_stream

        rows: List[dict] = []
        for i, row in enumerate(load_stream(str(filepath))):
            if i >= cap:
                return rows, True
            rows.append(row)
        return rows, False

    from ...storage.io import load_data

    data = load_data(str(filepath))
    if len(data) > cap:
        return data[:cap], True
    return data, False


def view(
    filename: str,
    cap: int = _DEFAULT_CAP,
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

    rows, truncated = _load_rows(filepath, cap)
    if not rows:
        print("文件为空。", file=sys.stderr)
        raise SystemExit(1)

    from .render import detect_format

    fmt = format_hint or detect_format(rows)

    from .app import ViewApp

    ViewApp(rows, fmt, filepath.name, truncated).run()
