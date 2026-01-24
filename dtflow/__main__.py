"""
Datatron CLI entry point.

Usage:
    dt <command> [options]
    dt --install-completion  # 安装 shell 自动补全

Commands:
    sample        从数据文件中采样
    head          显示文件的前 N 条数据
    tail          显示文件的后 N 条数据
    transform     转换数据格式（核心命令）
    stats         显示数据文件的统计信息
    token-stats   Token 统计
    diff          数据集对比
    dedupe        数据去重
    concat        拼接多个数据文件
    clean         数据清洗
    run           执行 Pipeline 配置文件
    history       显示数据血缘历史
    validate      使用 Schema 验证数据格式
    logs          日志查看工具使用说明
    install-skill 安装 dtflow skill 到 Claude Code
"""

import os
import sys
from typing import List, Optional

import typer

from .cli.commands import clean as _clean
from .cli.commands import concat as _concat
from .cli.commands import dedupe as _dedupe
from .cli.commands import diff as _diff
from .cli.commands import head as _head
from .cli.commands import history as _history
from .cli.commands import install_skill as _install_skill
from .cli.commands import run as _run
from .cli.commands import sample as _sample
from .cli.commands import skill_status as _skill_status
from .cli.commands import stats as _stats
from .cli.commands import tail as _tail
from .cli.commands import token_stats as _token_stats
from .cli.commands import transform as _transform
from .cli.commands import uninstall_skill as _uninstall_skill
from .cli.commands import validate as _validate

# 创建主应用
app = typer.Typer(
    name="dt",
    help="Datatron CLI - 数据转换工具",
    add_completion=True,
    no_args_is_help=True,
)


# ============ 数据预览命令 ============


@app.command()
def sample(
    filename: str = typer.Argument(..., help="输入文件路径"),
    num_arg: Optional[int] = typer.Argument(None, help="采样数量", metavar="NUM"),
    num: int = typer.Option(10, "--num", "-n", help="采样数量", show_default=True),
    type: str = typer.Option("random", "--type", "-t", help="采样方式: random/head/tail"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
    seed: Optional[int] = typer.Option(None, "--seed", help="随机种子"),
    by: Optional[str] = typer.Option(None, "--by", help="分层采样字段"),
    uniform: bool = typer.Option(False, "--uniform", help="均匀采样模式"),
    fields: Optional[str] = typer.Option(None, "--fields", "-f", help="只显示指定字段（逗号分隔）"),
    raw: bool = typer.Option(False, "--raw", "-r", help="输出原始 JSON（不截断）"),
    where: Optional[List[str]] = typer.Option(None, "--where", "-w", help="筛选条件 (可多次使用)"),
):
    """从数据文件中采样指定数量的数据"""
    actual_num = num_arg if num_arg is not None else num
    _sample(filename, actual_num, type, output, seed, by, uniform, fields, raw, where)


@app.command()
def head(
    filename: str = typer.Argument(..., help="输入文件路径"),
    num_arg: Optional[int] = typer.Argument(None, help="显示数量", metavar="NUM"),
    num: int = typer.Option(10, "--num", "-n", help="显示数量", show_default=True),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
    fields: Optional[str] = typer.Option(None, "--fields", "-f", help="只显示指定字段"),
    raw: bool = typer.Option(False, "--raw", "-r", help="输出原始 JSON（不截断）"),
):
    """显示文件的前 N 条数据"""
    # 位置参数优先于选项参数
    actual_num = num_arg if num_arg is not None else num
    _head(filename, actual_num, output, fields, raw)


@app.command()
def tail(
    filename: str = typer.Argument(..., help="输入文件路径"),
    num_arg: Optional[int] = typer.Argument(None, help="显示数量", metavar="NUM"),
    num: int = typer.Option(10, "--num", "-n", help="显示数量", show_default=True),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
    fields: Optional[str] = typer.Option(None, "--fields", "-f", help="只显示指定字段"),
    raw: bool = typer.Option(False, "--raw", "-r", help="输出原始 JSON（不截断）"),
):
    """显示文件的后 N 条数据"""
    # 位置参数优先于选项参数
    actual_num = num_arg if num_arg is not None else num
    _tail(filename, actual_num, output, fields, raw)


# ============ 数据转换命令 ============


@app.command()
def transform(
    filename: str = typer.Argument(..., help="输入文件路径"),
    num: Optional[int] = typer.Argument(None, help="只转换前 N 条数据"),
    preset: Optional[str] = typer.Option(None, "--preset", "-p", help="使用预设模板"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="配置文件路径"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
):
    """转换数据格式"""
    _transform(filename, num, preset, config, output)


@app.command()
def run(
    config: str = typer.Argument(..., help="Pipeline YAML 配置文件"),
    input: Optional[str] = typer.Option(None, "--input", "-i", help="输入文件路径"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
):
    """执行 Pipeline 配置文件"""
    _run(config, input, output)


# ============ 数据处理命令 ============


@app.command()
def dedupe(
    filename: str = typer.Argument(..., help="输入文件路径"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="去重依据字段"),
    similar: Optional[float] = typer.Option(None, "--similar", "-s", help="相似度阈值 (0-1)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
):
    """数据去重"""
    _dedupe(filename, key, similar, output)


@app.command()
def concat(
    files: List[str] = typer.Argument(..., help="输入文件列表"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径（必须）"),
    strict: bool = typer.Option(False, "--strict", help="严格模式，字段必须一致"),
):
    """拼接多个数据文件"""
    _concat(*files, output=output, strict=strict)


@app.command()
def clean(
    filename: str = typer.Argument(..., help="输入文件路径"),
    drop_empty: Optional[str] = typer.Option(None, "--drop-empty", help="删除空值记录"),
    min_len: Optional[str] = typer.Option(None, "--min-len", help="最小长度过滤 (字段:长度)"),
    max_len: Optional[str] = typer.Option(None, "--max-len", help="最大长度过滤 (字段:长度)"),
    keep: Optional[str] = typer.Option(None, "--keep", help="只保留指定字段"),
    drop: Optional[str] = typer.Option(None, "--drop", help="删除指定字段"),
    strip: bool = typer.Option(False, "--strip", help="去除字符串首尾空白"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
):
    """数据清洗"""
    _clean(filename, drop_empty, min_len, max_len, keep, drop, strip, output)


# ============ 数据统计命令 ============


@app.command()
def stats(
    filename: str = typer.Argument(..., help="输入文件路径"),
    top: int = typer.Option(10, "--top", "-n", help="显示 Top N 值"),
    full: bool = typer.Option(False, "--full", "-f", help="完整模式：统计值分布、唯一值等详细信息"),
):
    """显示数据文件的统计信息"""
    _stats(filename, top, full)


@app.command("token-stats")
def token_stats(
    filename: str = typer.Argument(..., help="输入文件路径"),
    field: str = typer.Option("messages", "--field", "-f", help="统计字段"),
    model: str = typer.Option(
        "cl100k_base", "--model", "-m", help="分词器: cl100k_base (默认), qwen2.5, llama3, gpt-4 等"
    ),
    detailed: bool = typer.Option(False, "--detailed", "-d", help="显示详细统计"),
):
    """统计数据集的 Token 信息"""
    _token_stats(filename, field, model, detailed)


@app.command()
def diff(
    file1: str = typer.Argument(..., help="第一个文件"),
    file2: str = typer.Argument(..., help="第二个文件"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="匹配键字段"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="报告输出路径"),
):
    """对比两个数据集的差异"""
    _diff(file1, file2, key, output)


@app.command()
def history(
    filename: str = typer.Argument(..., help="数据文件路径"),
    json: bool = typer.Option(False, "--json", "-j", help="JSON 格式输出"),
):
    """显示数据文件的血缘历史"""
    _history(filename, json)


# ============ 验证命令 ============


@app.command()
def validate(
    filename: str = typer.Argument(..., help="输入文件路径"),
    preset: Optional[str] = typer.Option(
        None, "--preset", "-p", help="预设 Schema: openai_chat, alpaca, dpo, sharegpt"
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出有效数据的文件路径"),
    filter: bool = typer.Option(False, "--filter", "-f", help="过滤无效数据并保存"),
    max_errors: int = typer.Option(20, "--max-errors", help="最多显示的错误数量"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示详细信息"),
):
    """使用预设 Schema 验证数据格式"""
    _validate(filename, preset, output, filter, max_errors, verbose)


# ============ 工具命令 ============


@app.command()
def logs():
    """日志查看工具使用说明"""
    help_text = """
日志查看工具 (tl)

dtflow 内置了 toolong 日志查看器，安装后可直接使用 tl 命令：

基本用法:
    tl app.log              查看日志文件（交互式 TUI）
    tl app.log error.log    同时查看多个日志
    tl --tail app.log       实时跟踪模式（类似 tail -f）
    tl *.log                通配符匹配多个文件

快捷键:
    /     搜索
    n/N   下一个/上一个匹配
    g/G   跳到开头/结尾
    f     过滤显示
    q     退出

安装:
    pip install dtflow[logs]   # 仅安装日志工具
    pip install dtflow[full]   # 安装全部可选依赖
"""
    print(help_text)


# ============ Skill 命令 ============


@app.command("install-skill")
def install_skill():
    """安装 dtflow skill 到 Claude Code"""
    _install_skill()


@app.command("uninstall-skill")
def uninstall_skill():
    """卸载 dtflow skill"""
    _uninstall_skill()


@app.command("skill-status")
def skill_status():
    """查看 skill 安装状态"""
    _skill_status()


def _show_completion_hint():
    """首次运行时提示用户可以安装补全"""
    from pathlib import Path

    # 标记文件
    marker = Path.home() / ".config" / "dtflow" / ".completion_hinted"

    # 已提示过则跳过
    if marker.exists():
        return

    # 检测是否在交互式终端中（检查 stderr，因为 stdout 可能被管道）
    if not (sys.stderr.isatty() or sys.stdout.isatty()):
        return

    # 显示提示（使用 stderr 避免干扰管道输出）
    from rich.console import Console

    console = Console(stderr=True)
    console.print("[dim]💡 提示: 运行 [green]dt --install-completion[/green] 启用命令补全[/dim]")

    # 记录已提示
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except Exception:
        pass


def main():
    # less 分页器配置（仅 Unix-like 系统）
    if sys.platform != "win32":
        os.environ["PAGER"] = "less -RXF"

    # _show_completion_hint()
    app()


if __name__ == "__main__":
    main()
