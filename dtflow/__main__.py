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
    split         分割数据集
    export        导出到训练框架
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
from .cli.commands import eval as _eval
from .cli.commands import export as _export
from .cli.commands import head as _head
from .cli.commands import history as _history
from .cli.commands import install_skill as _install_skill
from .cli.commands import run as _run
from .cli.commands import sample as _sample
from .cli.commands import skill_status as _skill_status
from .cli.commands import slice_data as _slice_data
from .cli.commands import split as _split
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
    pretty: bool = typer.Option(False, "--pretty", "-R", help="使用表格预览（默认原始 JSON）"),
    where: Optional[List[str]] = typer.Option(None, "--where", "-w", help="筛选条件 (可多次使用)"),
):
    """从数据文件中采样指定数量的数据"""
    actual_num = num_arg if num_arg is not None else num
    _sample(filename, actual_num, type, output, seed, by, uniform, fields, not pretty, where)


@app.command()
def head(
    filename: str = typer.Argument(..., help="输入文件路径"),
    num_arg: Optional[int] = typer.Argument(None, help="显示数量", metavar="NUM"),
    num: int = typer.Option(10, "--num", "-n", help="显示数量", show_default=True),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
    fields: Optional[str] = typer.Option(None, "--fields", "-f", help="只显示指定字段"),
    pretty: bool = typer.Option(False, "--pretty", "-R", help="使用表格预览（默认原始 JSON）"),
):
    """显示文件的前 N 条数据"""
    # 位置参数优先于选项参数
    actual_num = num_arg if num_arg is not None else num
    _head(filename, actual_num, output, fields, not pretty)


@app.command()
def tail(
    filename: str = typer.Argument(..., help="输入文件路径"),
    num_arg: Optional[int] = typer.Argument(None, help="显示数量", metavar="NUM"),
    num: int = typer.Option(10, "--num", "-n", help="显示数量", show_default=True),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
    fields: Optional[str] = typer.Option(None, "--fields", "-f", help="只显示指定字段"),
    pretty: bool = typer.Option(False, "--pretty", "-R", help="使用表格预览（默认原始 JSON）"),
):
    """显示文件的后 N 条数据"""
    # 位置参数优先于选项参数
    actual_num = num_arg if num_arg is not None else num
    _tail(filename, actual_num, output, fields, not pretty)


@app.command("slice")
def slice_cmd(
    filename: str = typer.Argument(..., help="输入文件路径"),
    range_str: str = typer.Argument(..., help="行号范围 (start:end)，如 10:20、:100、100:、-10:"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
    fields: Optional[str] = typer.Option(None, "--fields", "-f", help="只显示指定字段"),
    pretty: bool = typer.Option(False, "--pretty", "-R", help="使用表格预览（默认原始 JSON）"),
):
    """按行号范围查看数据（Python 切片语法）

    示例:
        dt slice data.jsonl 10:20     第 10-19 行
        dt slice data.jsonl :100      前 100 行
        dt slice data.jsonl 100:      第 100 行到末尾
        dt slice data.jsonl -10:      最后 10 行
    """
    _slice_data(filename, range_str, output, fields, not pretty)


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
    rename: Optional[str] = typer.Option(None, "--rename", help="重命名字段 (old:new,old2:new2)"),
    promote: Optional[str] = typer.Option(
        None, "--promote", help="提升嵌套字段到顶层 (meta.label 或 meta.label:tag)"
    ),
    add_field: Optional[str] = typer.Option(None, "--add-field", help="添加常量字段 (key:value)"),
    fill: Optional[str] = typer.Option(None, "--fill", help="填充空值 (field:default_value)"),
    reorder: Optional[str] = typer.Option(
        None, "--reorder", help="控制字段顺序 (field1,field2,...)"
    ),
    strip: bool = typer.Option(False, "--strip", help="去除字符串首尾空白"),
    min_tokens: Optional[str] = typer.Option(
        None, "--min-tokens", help="最小 token 数过滤 (字段:数量)"
    ),
    max_tokens: Optional[str] = typer.Option(
        None, "--max-tokens", help="最大 token 数过滤 (字段:数量)"
    ),
    model: str = typer.Option("cl100k_base", "--model", "-m", help="分词器模型 (默认 cl100k_base)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
):
    """数据清洗"""
    _clean(
        filename,
        drop_empty,
        min_len,
        max_len,
        keep,
        drop,
        rename,
        promote,
        add_field,
        fill,
        reorder,
        strip,
        min_tokens,
        max_tokens,
        model,
        output,
    )


# ============ 数据统计命令 ============


@app.command()
def stats(
    filename: str = typer.Argument(..., help="输入文件路径"),
    top: int = typer.Option(10, "--top", "-n", help="显示 Top N 值"),
    full: bool = typer.Option(False, "--full", "-f", help="完整模式：统计值分布、唯一值等详细信息"),
    field: Optional[List[str]] = typer.Option(
        None, "--field", help="指定统计字段（可多次使用），支持嵌套路径"
    ),
    expand: Optional[List[str]] = typer.Option(
        None, "--expand", help="展开 list 字段统计（可多次使用）"
    ),
):
    """显示数据文件的统计信息"""
    _stats(filename, top, full, field, expand)


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


# ============ 切分与导出命令 ============


@app.command()
def split(
    filename: str = typer.Argument(..., help="输入文件路径"),
    ratio: str = typer.Option("0.8", "--ratio", "-r", help="分割比例，如 0.8 或 0.7,0.15,0.15"),
    seed: Optional[int] = typer.Option(None, "--seed", help="随机种子"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出目录（默认同目录）"),
):
    """分割数据集为 train/test (或 train/val/test)"""
    _split(filename, ratio, seed, output)


@app.command()
def export(
    filename: str = typer.Argument(..., help="输入文件路径"),
    framework: str = typer.Option(
        ..., "--framework", "-f", help="目标框架: llama-factory, swift, axolotl"
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出目录"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="数据集名称"),
    check: bool = typer.Option(False, "--check", help="仅检查兼容性，不导出"),
):
    """导出数据到训练框架 (LLaMA-Factory, ms-swift, Axolotl)"""
    _export(filename, framework, output, name, check)


# ============ 评估命令 ============


@app.command()
def eval(
    result_file: str = typer.Argument(..., help="模型输出的 .jsonl 文件路径"),
    source: Optional[str] = typer.Option(
        None, "--source", "-s", help="原始输入文件，按行号对齐合并"
    ),
    response_col: str = typer.Option("content", "--response-col", "-r", help="模型响应字段名"),
    label_col: Optional[str] = typer.Option(
        None, "--label-col", "-l", help="标签字段名（不指定时自动检测）"
    ),
    extract: str = typer.Option(
        "direct",
        "--extract",
        "-e",
        help="管道式提取规则，算子: direct/tag:X/json_key:X/index:N/line:N/lines/regex:X",
    ),
    sep: Optional[str] = typer.Option(None, "--sep", help="配合 index 算子使用的分隔符"),
    mapping: Optional[str] = typer.Option(None, "--mapping", "-m", help="值映射 (k1:v1,k2:v2)"),
    output_dir: str = typer.Option("record", "--output-dir", "-o", help="指标报告输出目录"),
):
    """对模型输出进行解析和指标评估

    两阶段解析：自动清洗（去 think 标签、提取代码块）+ 管道式提取。

    示例:
        dt eval result.jsonl --label-col=label
        dt eval result.jsonl --extract="tag:标签" --mapping="是:1,否:0"
        dt eval result.jsonl --source=input.jsonl --response-col=api_output.content
        dt eval result.jsonl --extract="json_key:result | index:0" --sep=","
        dt eval result.jsonl --extract="lines | index:1" --sep="|"
    """
    _eval(result_file, source, response_col, label_col, extract, sep, mapping, output_dir)


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
