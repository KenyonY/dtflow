"""
命令行工具封装 - 自动下载 rg/fd 二进制

独立脚本，不依赖 dtflow 包。

用法:
    # 安装二进制
    python -m scripts.tools install

    # 作为模块使用
    from scripts.tools import rg, fd
    rg("pattern", path="src/")
    fd("*.py", path=".")
"""

from .binaries import ensure_binaries, get_fd_path, get_rg_path
from .search import fd, fzf_select, rg

__all__ = ["rg", "fd", "fzf_select", "ensure_binaries", "get_rg_path", "get_fd_path"]


def main():
    """CLI 入口"""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "install":
        print("Installing rg and fd...")
        paths = ensure_binaries(["rg", "fd"])
        print(f"rg: {paths['rg']}")
        print(f"fd: {paths['fd']}")
    else:
        print("Usage: python -m scripts.tools install")


if __name__ == "__main__":
    main()
