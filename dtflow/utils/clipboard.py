"""系统剪贴板写入。

两条通道都发, 覆盖面互补:
- OSC52 转义序列: 本机和 SSH 都能用, 但要终端支持 (tmux/screen 需 passthrough 包装)
- 本地命令行工具: wl-copy / xclip / xsel, 覆盖吞掉 OSC52 的终端; tmux 内额外写 paste buffer

两条都失败也不报错 —— 复制不是关键路径, 调用方拿返回值说清楚"到底进没进剪贴板"即可。
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
from typing import List, Optional

_TIMEOUT = 0.5


def osc52(text: str) -> str:
    """OSC52 序列; 在 tmux/screen 内包 DCS passthrough 直穿到外层终端。

    Textual 只发裸 OSC52, 会被 tmux 拦截; 这里检测复用环境做穿透包装
    (需 tmux ``set -g allow-passthrough on``), 让 Ghostty 等支持 OSC52 的终端收到。
    """
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    seq = f"\x1b]52;c;{b64}\a"
    if os.environ.get("TMUX"):  # tmux: \ePtmux;<每个 ESC 翻倍的原序列>\e\\
        return "\x1bPtmux;" + seq.replace("\x1b", "\x1b\x1b") + "\x1b\\"
    if os.environ.get("STY"):  # GNU screen: \eP<原序列>\e\\
        return "\x1bP" + seq + "\x1b\\"
    return seq


def _pipe(cmd: List[str], text: str) -> bool:
    if not shutil.which(cmd[0]):
        return False
    try:
        subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            timeout=_TIMEOUT,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def copy_external(text: str) -> Optional[str]:
    """尽力用本地工具写系统剪贴板, 返回成功的工具名 (都没有则 None)。

    SSH 会话里 DISPLAY/WAYLAND_DISPLAY 通常是空的, 这里自然什么都不做, 由 OSC52 兜。
    """
    candidates: List[List[str]] = []
    if os.environ.get("WAYLAND_DISPLAY"):
        candidates.append(["wl-copy"])
    if os.environ.get("DISPLAY"):
        candidates.append(["xclip", "-selection", "clipboard"])
        candidates.append(["xsel", "-ib"])

    used = None
    for cmd in candidates:
        if _pipe(cmd, text):
            used = cmd[0]
            break
    if os.environ.get("TMUX") and _pipe(["tmux", "load-buffer", "-w", "-"], text):
        used = used or "tmux"
    return used
