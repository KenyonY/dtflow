"""
二进制工具自动下载和管理

- rg: pip install ripgrep (从 PyPI)
- fd: 从 GitHub 下载静态二进制 (PyPI 上没有)
"""

import platform
import shutil
import subprocess
import tarfile
from pathlib import Path
from urllib.request import urlretrieve

# 版本配置
FD_VERSION = "10.2.0"

# fd 下载地址 (PyPI 上没有，只能从 GitHub 下载)
FD_URLS = {
    ("Linux", "x86_64"): f"https://github.com/sharkdp/fd/releases/download/v{FD_VERSION}/fd-v{FD_VERSION}-x86_64-unknown-linux-musl.tar.gz",
    ("Darwin", "x86_64"): f"https://github.com/sharkdp/fd/releases/download/v{FD_VERSION}/fd-v{FD_VERSION}-x86_64-apple-darwin.tar.gz",
    ("Darwin", "arm64"): f"https://github.com/sharkdp/fd/releases/download/v{FD_VERSION}/fd-v{FD_VERSION}-aarch64-apple-darwin.tar.gz",
}

# 二进制存放目录
BIN_DIR = Path(__file__).parent / "bin"


def get_platform_key() -> tuple:
    """获取当前平台的 key"""
    system = platform.system()
    machine = platform.machine()
    if machine in ("aarch64", "arm64"):
        machine = "arm64"
    return (system, machine)


def get_rg_path() -> Path | None:
    """获取 rg 路径 (系统安装或 pip 安装)"""
    rg_path = shutil.which("rg")
    return Path(rg_path) if rg_path else None


def get_fd_path() -> Path | None:
    """获取 fd 路径"""
    # 系统安装的
    system_fd = shutil.which("fd")
    if system_fd:
        return Path(system_fd)
    # 本地下载的
    local_fd = BIN_DIR / "fd"
    if local_fd.exists():
        return local_fd
    return None


def install_rg() -> Path:
    """通过 pip 安装 ripgrep"""
    print("Installing ripgrep via pip...")
    result = subprocess.run(
        ["pip", "install", "ripgrep"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pip install ripgrep failed: {result.stderr}")

    rg_path = get_rg_path()
    if rg_path is None:
        raise RuntimeError("ripgrep installed but rg not found in PATH")

    print(f"✓ rg installed via pip: {rg_path}")
    return rg_path


def install_fd() -> Path:
    """从 GitHub 下载 fd"""
    key = get_platform_key()
    if key not in FD_URLS:
        raise RuntimeError(f"Unsupported platform: {key}")

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    binary_path = BIN_DIR / "fd"

    url = FD_URLS[key]
    print(f"Downloading fd from GitHub...")

    # 下载
    tar_path = BIN_DIR / "fd.tar.gz"
    urlretrieve(url, tar_path)

    # 解压
    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name.endswith("/fd") or member.name == "fd":
                member.name = "fd"
                tar.extract(member, BIN_DIR)
                break

    # 设置可执行权限
    binary_path.chmod(0o755)
    tar_path.unlink()

    print(f"✓ fd installed to {binary_path}")
    return binary_path


def ensure_binaries(tools: list[str] | None = None) -> dict[str, Path]:
    """确保指定工具已安装"""
    if tools is None:
        tools = ["rg", "fd"]

    paths = {}
    for tool in tools:
        if tool == "rg":
            path = get_rg_path()
            if path is None:
                path = install_rg()
        elif tool == "fd":
            path = get_fd_path()
            if path is None:
                path = install_fd()
        else:
            raise ValueError(f"Unknown tool: {tool}")
        paths[tool] = path

    return paths


def run_binary(tool: str, args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """运行二进制工具"""
    paths = ensure_binaries([tool])
    return subprocess.run([str(paths[tool])] + args, **kwargs)
