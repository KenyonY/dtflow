"""
Claude Code Skill 安装命令
"""

import shutil
from pathlib import Path

from rich.console import Console

console = Console()


def get_skill_source_path() -> Path:
    """获取 SKILL.md 源文件路径"""
    return Path(__file__).parent.parent / "SKILL.md"


def get_skill_target_dir() -> Path:
    """获取 skill 安装目标目录"""
    return Path.home() / ".claude" / "skills" / "dtflow"


def install_skill() -> None:
    """安装 dtflow skill 到 Claude Code"""
    source = get_skill_source_path()
    target_dir = get_skill_target_dir()
    target = target_dir / "SKILL.md"

    if not source.exists():
        console.print("[red]错误: SKILL.md 源文件不存在[/red]")
        raise SystemExit(1)

    # 创建目标目录
    target_dir.mkdir(parents=True, exist_ok=True)

    # 复制文件
    shutil.copy2(source, target)

    console.print("[green]✓[/green] 已安装 dtflow skill 到 Claude Code")
    console.print(f"  [dim]{target}[/dim]")
    console.print()
    console.print("[dim]在 Claude Code 中使用 /dtflow 调用此 skill[/dim]")


def uninstall_skill() -> None:
    """卸载 dtflow skill"""
    target_dir = get_skill_target_dir()
    target = target_dir / "SKILL.md"

    if not target.exists():
        console.print("[yellow]dtflow skill 未安装[/yellow]")
        return

    target.unlink()

    # 如果目录为空，也删除目录
    if target_dir.exists() and not any(target_dir.iterdir()):
        target_dir.rmdir()

    console.print("[green]✓[/green] 已卸载 dtflow skill")


def skill_status() -> None:
    """显示 skill 安装状态"""
    target = get_skill_target_dir() / "SKILL.md"

    if target.exists():
        console.print("[green]✓[/green] dtflow skill 已安装")
        console.print(f"  [dim]{target}[/dim]")
    else:
        console.print("[yellow]✗[/yellow] dtflow skill 未安装")
        console.print("  [dim]运行 dt install-skill 安装[/dim]")
