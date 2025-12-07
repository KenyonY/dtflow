"""Datatron MCP CLI 命令

提供 MCP 服务的安装和管理命令。
"""

import json
import os
import platform
from pathlib import Path
from typing import Literal

try:
    from rich import print
    from rich.console import Console
    console = Console()
except ImportError:
    console = None
    def print(*args, **kwargs):
        import builtins
        builtins.print(*args, **kwargs)

# 支持的目标类型
TargetType = Literal["desktop", "code", "all"]


def get_claude_desktop_config_path() -> Path:
    """获取 Claude Desktop 配置文件路径"""
    system = platform.system()

    if system == "Darwin":  # macOS
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    elif system == "Linux":
        return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
    else:
        raise RuntimeError(f"不支持的操作系统: {system}")


def get_claude_code_config_path() -> Path:
    """获取 Claude Code 配置文件路径"""
    return Path.home() / ".claude.json"


def get_dt_mcp_command() -> list[str]:
    """获取 dt-mcp 命令路径

    使用 python -m 形式，更通用
    """
    return ["python", "-m", "dtflow.mcp"]


def _install_to_config(config_path: Path, name: str, target_name: str) -> bool:
    """安装 MCP 服务到指定配置文件

    Returns:
        True 成功，False 失败
    """
    # 确保配置目录存在
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # 读取现有配置
    config = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except json.JSONDecodeError:
            if console:
                console.print(f"[yellow]警告:[/yellow] {target_name} 配置文件格式错误，将创建新配置")
            else:
                print(f"警告: {target_name} 配置文件格式错误，将创建新配置")

    # 确保 mcpServers 字段存在
    if "mcpServers" not in config:
        config["mcpServers"] = {}

    # 获取命令
    command = get_dt_mcp_command()

    # 添加 datatron MCP 服务配置
    config["mcpServers"][name] = {
        "type": "stdio",
        "command": command[0],
        "args": command[1:] if len(command) > 1 else [],
    }

    # 写入配置
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        if console:
            console.print(f"[bold red]错误:[/bold red] 无法写入 {target_name} 配置文件: {e}")
        else:
            print(f"错误: 无法写入 {target_name} 配置文件: {e}")
        return False


def _uninstall_from_config(config_path: Path, name: str, target_name: str) -> bool:
    """从指定配置文件移除 MCP 服务

    Returns:
        True 成功移除，False 未找到或失败
    """
    if not config_path.exists():
        return False

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError:
        return False

    if "mcpServers" not in config or name not in config["mcpServers"]:
        return False

    del config["mcpServers"][name]

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def _show_config_status(config_path: Path, target_name: str):
    """显示单个配置文件的状态"""
    if console:
        console.print(f"\n[bold]{target_name} 配置:[/bold]")
        console.print(f"  路径: [bold blue]{config_path}[/bold blue]")
        console.print(f"  存在: {'[green]是[/green]' if config_path.exists() else '[yellow]否[/yellow]'}")
    else:
        print(f"\n{target_name} 配置:")
        print(f"  路径: {config_path}")
        print(f"  存在: {'是' if config_path.exists() else '否'}")

    if not config_path.exists():
        return

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError:
        if console:
            console.print("  [red]配置文件格式错误[/red]")
        else:
            print("  配置文件格式错误")
        return

    mcp_servers = config.get("mcpServers", {})
    if mcp_servers:
        if console:
            console.print("  已安装的 MCP 服务:")
        else:
            print("  已安装的 MCP 服务:")
        for name, server_config in mcp_servers.items():
            command = server_config.get("command", "N/A")
            is_dt = "data" in name.lower() or "dt" in name.lower() or "transformer" in str(command)
            if console:
                marker = "[green]*[/green]" if is_dt else " "
                console.print(f"    {marker} [cyan]{name}[/cyan]")
            else:
                marker = "*" if is_dt else " "
                print(f"    {marker} {name}")


class MCPCommands:
    """MCP 服务管理命令"""

    def install(self, name: str = "datatron", target: str = "code"):
        """
        安装 Datatron MCP 服务

        Args:
            name: MCP 服务名称（默认: datatron）
            target: 安装目标 - 'desktop'(Claude Desktop), 'code'(Claude Code), 'all'(两者)

        示例:
            # 安装到 Claude Code（推荐）
            dt mcp install

            # 安装到所有目标
            dt mcp install --target all

            # 仅安装到 Claude Desktop
            dt mcp install --target desktop

            # 自定义服务名称
            dt mcp install --name my-dt
        """
        command = get_dt_mcp_command()
        installed_targets = []

        # Claude Desktop
        if target in ("desktop", "all"):
            try:
                desktop_path = get_claude_desktop_config_path()
                if _install_to_config(desktop_path, name, "Claude Desktop"):
                    installed_targets.append(("Claude Desktop", desktop_path))
            except RuntimeError:
                if target == "desktop":
                    if console:
                        console.print("[bold red]错误:[/bold red] 不支持的操作系统")
                    else:
                        print("错误: 不支持的操作系统")
                    return

        # Claude Code
        if target in ("code", "all"):
            code_path = get_claude_code_config_path()
            if _install_to_config(code_path, name, "Claude Code"):
                installed_targets.append(("Claude Code", code_path))

        if not installed_targets:
            if console:
                console.print("[bold red]错误:[/bold red] 安装失败")
            else:
                print("错误: 安装失败")
            return

        if console:
            console.print(f"\n[bold green]Datatron MCP 服务安装成功[/bold green]\n")
            console.print(f"服务名称: [bold blue]{name}[/bold blue]")
            console.print(f"命令: [bold blue]{' '.join(command)}[/bold blue]")
            console.print(f"\n已安装到:")
            for target_name, config_path in installed_targets:
                console.print(f"  - {target_name}: [dim]{config_path}[/dim]")
            console.print(f"\n[dim]请重启 Claude Desktop/Code 以使配置生效[/dim]")
        else:
            print(f"\nDatatron MCP 服务安装成功\n")
            print(f"服务名称: {name}")
            print(f"命令: {' '.join(command)}")
            print(f"\n已安装到:")
            for target_name, config_path in installed_targets:
                print(f"  - {target_name}: {config_path}")
            print(f"\n请重启 Claude Desktop/Code 以使配置生效")

    def uninstall(self, name: str = "datatron", target: str = "all"):
        """
        移除 Datatron MCP 服务

        Args:
            name: MCP 服务名称（默认: datatron）
            target: 移除目标 - 'desktop', 'code', 'all'

        示例:
            dt mcp uninstall
            dt mcp uninstall --target code
        """
        removed_targets = []

        # Claude Desktop
        if target in ("desktop", "all"):
            try:
                desktop_path = get_claude_desktop_config_path()
                if _uninstall_from_config(desktop_path, name, "Claude Desktop"):
                    removed_targets.append("Claude Desktop")
            except RuntimeError:
                pass

        # Claude Code
        if target in ("code", "all"):
            code_path = get_claude_code_config_path()
            if _uninstall_from_config(code_path, name, "Claude Code"):
                removed_targets.append("Claude Code")

        if removed_targets:
            if console:
                console.print(f"\n[bold green]Datatron MCP 服务已移除[/bold green]")
                console.print(f"从以下位置移除: {', '.join(removed_targets)}")
                console.print(f"\n[dim]请重启 Claude Desktop/Code 以使配置生效[/dim]")
            else:
                print(f"\nDatatron MCP 服务已移除")
                print(f"从以下位置移除: {', '.join(removed_targets)}")
                print(f"\n请重启 Claude Desktop/Code 以使配置生效")
        else:
            if console:
                console.print(f"[yellow]未找到名为 '{name}' 的 MCP 服务[/yellow]")
            else:
                print(f"未找到名为 '{name}' 的 MCP 服务")

    def status(self):
        """
        查看 Datatron MCP 服务安装状态

        示例:
            dt mcp status
        """
        # Claude Desktop
        try:
            desktop_path = get_claude_desktop_config_path()
            _show_config_status(desktop_path, "Claude Desktop")
        except RuntimeError:
            pass

        # Claude Code
        code_path = get_claude_code_config_path()
        _show_config_status(code_path, "Claude Code")

        # 检查 mcp 依赖是否安装
        if console:
            console.print(f"\n[bold]依赖状态:[/bold]")
        else:
            print(f"\n依赖状态:")

        try:
            import mcp
            if console:
                console.print(f"  mcp: [green]已安装[/green]")
            else:
                print(f"  mcp: 已安装")
        except ImportError:
            if console:
                console.print(f"  mcp: [red]未安装[/red] (运行 'pip install dtflow[mcp]')")
            else:
                print(f"  mcp: 未安装 (运行 'pip install dtflow[mcp]')")

    def test(self):
        """
        测试 Datatron MCP 服务是否正常工作

        示例:
            dt mcp test
        """
        if console:
            console.print("\n[bold]测试 Datatron MCP 服务...[/bold]\n")
        else:
            print("\n测试 Datatron MCP 服务...\n")

        # 检查依赖
        try:
            from dtflow.mcp import mcp
            if console:
                console.print("[green]OK[/green] MCP 模块导入成功")
            else:
                print("OK MCP 模块导入成功")
        except ImportError as e:
            if console:
                console.print(f"[red]FAIL[/red] MCP 模块导入失败: {e}")
                console.print("\n请安装 mcp 依赖: pip install datatron[mcp]")
            else:
                print(f"FAIL MCP 模块导入失败: {e}")
                print("\n请安装 mcp 依赖: pip install datatron[mcp]")
            return

        # 检查文档
        try:
            from dtflow.mcp.docs import DOCS, TOPICS
            if console:
                console.print(f"[green]OK[/green] 文档加载成功 ({len(TOPICS)} 个主题)")
            else:
                print(f"OK 文档加载成功 ({len(TOPICS)} 个主题)")
        except ImportError as e:
            if console:
                console.print(f"[red]FAIL[/red] 文档加载失败: {e}")
            else:
                print(f"FAIL 文档加载失败: {e}")
            return

        # 检查命令
        command = get_dt_mcp_command()
        if console:
            console.print(f"[green]OK[/green] MCP 命令: {' '.join(command)}")
            console.print("\n[bold green]所有测试通过[/bold green]")
        else:
            print(f"OK MCP 命令: {' '.join(command)}")
            print("\n所有测试通过")
