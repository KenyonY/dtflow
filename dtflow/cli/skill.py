"""Agent Skill 安装命令。"""

import shutil
from pathlib import Path

from rich.console import Console

console = Console()

SKILL_TARGETS = {
    "claude": (".claude", "Claude Code"),
    "codex": (".agents", "Codex"),
}


def get_skill_source_path() -> Path:
    """获取 SKILL.md 源文件路径"""
    return Path(__file__).parent.parent / "SKILL.md"


def get_skill_target_dir(target: str = "claude") -> Path:
    """获取指定 agent 的用户级 skill 安装目录。"""
    try:
        config_dir, _ = SKILL_TARGETS[target]
    except KeyError as exc:
        choices = ", ".join(SKILL_TARGETS)
        raise ValueError(f"未知 skill 安装目标: {target}（可选: {choices}）") from exc
    return Path.home() / config_dir / "skills" / "dtflow"


def install_skill(target: str = "claude") -> None:
    """安装 dtflow skill 到指定 agent。"""
    source = get_skill_source_path()
    target_dir = get_skill_target_dir(target)
    target_file = target_dir / "SKILL.md"
    _, agent_name = SKILL_TARGETS[target]

    if not source.exists():
        console.print("[red]错误: SKILL.md 源文件不存在[/red]")
        raise SystemExit(1)

    # 创建目标目录
    target_dir.mkdir(parents=True, exist_ok=True)

    # 复制文件
    shutil.copy2(source, target_file)

    console.print(f"[green]✓[/green] 已安装 dtflow skill 到 {agent_name}")
    console.print(f"  [dim]{target_file}[/dim]")
    console.print()
    invocation = "/dtflow" if target == "claude" else "$dtflow"
    console.print(f"[dim]在 {agent_name} 中使用 {invocation} 调用此 skill[/dim]")


def uninstall_skill(target: str = "claude") -> None:
    """从指定 agent 卸载 dtflow skill。"""
    target_dir = get_skill_target_dir(target)
    target = target_dir / "SKILL.md"

    if not target.exists():
        console.print("[yellow]dtflow skill 未安装[/yellow]")
        return

    target.unlink()

    # 如果目录为空，也删除目录
    if target_dir.exists() and not any(target_dir.iterdir()):
        target_dir.rmdir()

    console.print("[green]✓[/green] 已卸载 dtflow skill")


def skill_status(target: str = "claude") -> None:
    """显示指定 agent 的 skill 安装状态。"""
    target_file = get_skill_target_dir(target) / "SKILL.md"
    _, agent_name = SKILL_TARGETS[target]

    if target_file.exists():
        console.print(f"[green]✓[/green] {agent_name} skill 已安装")
        console.print(f"  [dim]{target_file}[/dim]")
    else:
        console.print(f"[yellow]✗[/yellow] {agent_name} skill 未安装")
        console.print(f"  [dim]运行 dt install-skill --target {target} 安装[/dim]")
