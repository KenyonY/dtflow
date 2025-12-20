"""
搜索工具的 Python 封装

提供 rg, fd 的简单 Python API
"""

import subprocess
from pathlib import Path
from typing import Iterator

from .binaries import ensure_binaries


def rg(
    pattern: str,
    path: str = ".",
    *,
    ext: str | None = None,
    ignore_case: bool = False,
    word: bool = False,
    files_only: bool = False,
    context: int = 0,
    max_count: int | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    """
    使用 ripgrep 搜索文件内容

    Args:
        pattern: 搜索模式 (正则表达式)
        path: 搜索路径
        ext: 文件扩展名过滤，如 "py", "js"
        ignore_case: 忽略大小写
        word: 全词匹配
        files_only: 只返回文件名
        context: 显示匹配行前后的行数
        max_count: 每个文件最多匹配数
        extra_args: 额外的 rg 参数

    Returns:
        匹配结果列表
    """
    paths = ensure_binaries(["rg"])
    args = [str(paths["rg"])]

    if ignore_case:
        args.append("-i")
    if word:
        args.append("-w")
    if files_only:
        args.append("-l")
    if context > 0:
        args.extend(["-C", str(context)])
    if max_count:
        args.extend(["-m", str(max_count)])
    if ext:
        args.extend(["-t", ext])
    if extra_args:
        args.extend(extra_args)

    args.extend([pattern, path])

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode not in (0, 1):  # 1 = no matches
        raise RuntimeError(f"rg failed: {result.stderr}")

    return result.stdout.strip().split("\n") if result.stdout.strip() else []


def fd(
    pattern: str = "",
    path: str = ".",
    *,
    ext: str | None = None,
    file_type: str | None = None,
    hidden: bool = False,
    max_depth: int | None = None,
    exclude: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> list[Path]:
    """
    使用 fd 查找文件

    Args:
        pattern: 文件名模式 (正则表达式)
        path: 搜索路径
        ext: 文件扩展名，如 "py", "json"
        file_type: 类型过滤 - "f"(文件), "d"(目录), "l"(链接)
        hidden: 包含隐藏文件
        max_depth: 最大搜索深度
        exclude: 排除的模式列表
        extra_args: 额外的 fd 参数

    Returns:
        匹配的文件路径列表
    """
    paths = ensure_binaries(["fd"])
    args = [str(paths["fd"])]

    if ext:
        args.extend(["-e", ext])
    if file_type:
        args.extend(["-t", file_type])
    if hidden:
        args.append("-H")
    if max_depth:
        args.extend(["-d", str(max_depth)])
    if exclude:
        for exc in exclude:
            args.extend(["-E", exc])
    if extra_args:
        args.extend(extra_args)

    if pattern:
        args.append(pattern)
    args.append(path)

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"fd failed: {result.stderr}")

    lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    return [Path(line) for line in lines]


def fzf_select(
    items: list[str],
    *,
    multi: bool = False,
    preview: str | None = None,
    prompt: str = "> ",
) -> list[str]:
    """
    使用 fzf 进行交互式选择 (需要系统安装 fzf)

    Args:
        items: 待选择的项目列表
        multi: 是否允许多选
        preview: 预览命令，如 "cat {}"
        prompt: 提示符

    Returns:
        选中的项目列表
    """
    import shutil

    fzf_path = shutil.which("fzf")
    if not fzf_path:
        raise RuntimeError("fzf not found. Please install fzf first.")

    args = [fzf_path, "--prompt", prompt]
    if multi:
        args.append("-m")
    if preview:
        args.extend(["--preview", preview])

    result = subprocess.run(
        args,
        input="\n".join(items),
        capture_output=True,
        text=True,
    )

    if result.returncode == 130:  # User cancelled
        return []

    return result.stdout.strip().split("\n") if result.stdout.strip() else []


# 便捷函数
def grep_files(pattern: str, path: str = ".", ext: str | None = None) -> list[str]:
    """搜索内容，只返回匹配的文件名"""
    return rg(pattern, path, ext=ext, files_only=True)


def find_files(ext: str, path: str = ".") -> list[Path]:
    """按扩展名查找文件"""
    return fd("", path, ext=ext, file_type="f")
