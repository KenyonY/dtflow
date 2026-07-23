"""
Datatron CLI (dt) — Agent 友好的数据转换工具

基本用法:
    dt <command> [options]
    dt --install-completion            # 安装 shell 自动补全

Agent 探索入口:
    dt --help                          # 查看所有命令
    dt schema                          # 机器可读的命令树 (JSON)
    dt schema <command>                # 单个命令的参数定义
    dt <command> --help                # 某命令的详细参数和示例

输出契约:
    stdout  只承载数据（JSON / NDJSON / CSV / Table）
    stderr  承载进度、警告、错误等消息
    退出码  0=成功, 1=一般错误, 2=参数错误, 3=资源不存在,
            4=权限拒绝, 5=冲突, 10=dry-run 预演成功

全局选项:
    --format json|ndjson|csv|table     指定输出格式
        预览类命令 (head/sample/tail/slice): 非 TTY 默认 ndjson;
        TTY 默认逐条 pretty JSON, 加 --pretty 或 --format=table 走格式感知渲染
        (对话气泡/dpo对比/alpaca分段/通用表格)
    --no-color                          禁用彩色（同样响应 NO_COLOR 环境变量）
    --yes                               跳过所有确认
    --verbose / --quiet                 日志等级

副作用命令（clean / transform / concat / dedupe / split / export / run / eval）
都支持 --dry-run，可先预演再执行实际写入。

Commands:
    sample        从数据文件中采样
    head          显示文件的前 N 条数据
    tail          显示文件的后 N 条数据
    slice         按行号范围查看数据
    view          交互式浏览数据（表格+详情 TUI）
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
    schema        输出命令树 / 参数定义 (JSON)
    logs          日志查看工具使用说明
    install-skill 安装 dtflow skill 到 Claude Code
"""

import os
import sys
from enum import Enum
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
from .cli.output import CLIState, set_state
from .cli.view import _DEFAULT_CAP as _VIEW_CAP
from .cli.view import view as _view

# ============ 受约束参数枚举 ============
# 这些枚举让 click 在解析层就拒绝非法值，并把 choices 暴露给 `dt schema`。


class SampleType(str, Enum):
    """sample 命令的 --type 取值。"""

    random = "random"
    head = "head"
    tail = "tail"


class TransformPreset(str, Enum):
    """transform 命令的 --preset 取值。"""

    openai_chat = "openai_chat"
    alpaca = "alpaca"
    sharegpt = "sharegpt"
    dpo_pair = "dpo_pair"
    simple_qa = "simple_qa"


class ValidatePreset(str, Enum):
    """validate 命令的 --preset 取值。"""

    openai_chat = "openai_chat"
    alpaca = "alpaca"
    dpo = "dpo"
    sharegpt = "sharegpt"


class Framework(str, Enum):
    """export 命令的 --framework 取值。"""

    llama_factory = "llama-factory"
    swift = "swift"
    axolotl = "axolotl"


# 创建主应用
try:  # 与 dt schema 的 version 字段同源, 三处 (--help / --version / schema) 不漂移
    from . import __version__ as _VERSION
except Exception:  # noqa: BLE001  源码树以外的异常安装方式
    _VERSION = "unknown"


app = typer.Typer(
    name="dt",
    help=(
        f"Datatron CLI v{_VERSION} - 数据转换工具 (Agent 友好)\n\n"
        "stdout=数据, stderr=消息, 退出码见 --help.\n"
        "Agent 建议先运行: dt schema | dt --help | dt <cmd> --help"
    ),
    add_completion=True,
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    """--version: 只打裸版本号到 stdout。

    与 dt schema 的 version 字段一致, 不加 "dt " 前缀 —— stdout 是数据, 版本号本身
    就是这条命令的数据, 裸值最好解析 (dt --version 直接可比对)。
    """
    if value:
        typer.echo(_VERSION)
        raise typer.Exit()


# ============ 全局选项 (注入 CLIState) ============


@app.callback()
def _global_options(
    ctx: typer.Context,
    fmt: Optional[str] = typer.Option(
        None,
        "--format",
        help="输出格式: json|ndjson|csv|table (非 TTY 默认 ndjson; 预览命令 TTY 默认逐条 JSON, table=格式渲染)",
    ),
    no_color: bool = typer.Option(
        False, "--no-color", help="禁用彩色输出 (同样响应 NO_COLOR / TERM=dumb)"
    ),
    yes: bool = typer.Option(False, "--yes", help="跳过所有交互确认"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="显示更详细的日志"),
    quiet: bool = typer.Option(False, "--quiet", "-Q", help="抑制所有 stderr 消息"),
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,  # 先于其他选项处理: dt --version 不该被别的参数校验挡住
        help="显示版本号并退出",
    ),
):
    """全局运行状态注入；各命令通过 dtflow.cli.output.get_state() 读取。"""
    if fmt is not None and fmt not in {"json", "ndjson", "csv", "table"}:
        from .cli.output import die_usage

        die_usage(
            f"不支持的 --format 值: {fmt}",
            suggestion="可选值: json | ndjson | csv | table",
        )
    set_state(
        CLIState(
            fmt=fmt,
            no_color=no_color,
            yes=yes,
            verbose=verbose,
            quiet=quiet,
        )
    )


# ============ 数据预览命令 ============


@app.command()
def sample(
    filename: str = typer.Argument(..., help="输入文件路径"),
    num_arg: Optional[int] = typer.Argument(None, help="采样数量", metavar="NUM"),
    num: int = typer.Option(10, "--num", "-n", help="采样数量", show_default=True),
    type: Optional[SampleType] = typer.Option(
        None,
        "--type",
        "-t",
        help="采样方式: random|head|tail（默认 random，n=0 时默认 head）",
        case_sensitive=False,
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
    seed: Optional[int] = typer.Option(None, "--seed", help="随机种子"),
    by: Optional[str] = typer.Option(None, "--by", help="分层采样字段"),
    uniform: bool = typer.Option(False, "--uniform", help="均匀采样模式"),
    dist: Optional[str] = typer.Option(
        None, "--dist", help='自定义分布 (JSON), 如 \'{"A":0.5,"B":0.3,"C":0.2}\''
    ),
    fields: Optional[str] = typer.Option(None, "--fields", "-f", help="只显示指定字段（逗号分隔）"),
    pretty: bool = typer.Option(
        False,
        "--pretty",
        "-R",
        help="格式感知渲染: 对话气泡/dpo对比/alpaca分段/通用表格 (默认逐条 JSON)",
    ),
    where: Optional[List[str]] = typer.Option(
        None,
        "--where",
        "-w",
        help="筛选条件 字段 运算符 值, 可多次使用 (与关系); 运算符 = != > >= < <= ~=(包含,不分大小写)",
    ),
):
    """从数据文件中采样指定数量的数据

    示例:
        dt sample data.jsonl --num=10                     # 随机 10 条
        dt sample data.jsonl 100 --by=category            # 按字段分层 100 条
        dt sample data.jsonl --where="messages.#>=2"      # 筛选后采样
        dt sample data.jsonl -w "meta.source~=alpaca"     # 包含子串 (不分大小写)
        dt sample data.jsonl --dist='{"A":0.5,"B":0.5}' --by=label
        dt --format=json sample data.jsonl                # stdout 输出 JSON

    退出码: 0 成功, 1 筛选后无数据, 2 参数错误, 3 文件不存在
    """
    actual_num = num_arg if num_arg is not None else num
    type_value = type.value if isinstance(type, SampleType) else type
    _sample(
        filename,
        actual_num,
        type_value,
        output,
        seed,
        by,
        uniform,
        fields,
        not pretty,
        where,
        dist,
    )


@app.command()
def head(
    filename: str = typer.Argument(..., help="输入文件路径"),
    num_arg: Optional[int] = typer.Argument(None, help="显示数量", metavar="NUM"),
    num: int = typer.Option(10, "--num", "-n", help="显示数量", show_default=True),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
    fields: Optional[str] = typer.Option(None, "--fields", "-f", help="只显示指定字段"),
    pretty: bool = typer.Option(
        False,
        "--pretty",
        "-R",
        help="格式感知渲染: 对话气泡/dpo对比/alpaca分段/通用表格 (默认逐条 JSON)",
    ),
):
    """显示文件的前 N 条数据

    示例:
        dt head data.jsonl 5                     # 前 5 条
        dt head data.jsonl --fields=id,text      # 只显示部分字段
        dt --format=json head data.jsonl | jq .  # 机器可读输出
    """
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
    pretty: bool = typer.Option(
        False,
        "--pretty",
        "-R",
        help="格式感知渲染: 对话气泡/dpo对比/alpaca分段/通用表格 (默认逐条 JSON)",
    ),
):
    """显示文件的后 N 条数据

    示例:
        dt tail data.jsonl 5                     # 后 5 条
        dt tail data.jsonl --fields=id,label
    """
    # 位置参数优先于选项参数
    actual_num = num_arg if num_arg is not None else num
    _tail(filename, actual_num, output, fields, not pretty)


@app.command()
def view(
    filename: str = typer.Argument(..., help="输入文件路径；- 表示从 stdin 读（管道模式）"),
    num_arg: Optional[int] = typer.Argument(
        None, metavar="NUM", help="窗口大小简写（等价 --cap，首屏 N 行，仍可 ]/[ 翻页）"
    ),
    cap: int = typer.Option(
        _VIEW_CAP, "--cap", help="单窗口加载行数（只 parse 这么多，其余按需翻页）"
    ),
    offset: int = typer.Option(
        0, "--offset", help="起始行号（0-based），从文件中间打开（stdin 模式无效）"
    ),
    format: Optional[str] = typer.Option(
        None, "--format", help="强制格式: openai_chat|sharegpt|dpo|alpaca|generic"
    ),
    where: Optional[List[str]] = typer.Option(
        None,
        "--where",
        help="启动即筛选，列名取表头所见，可多次使用（与关系）；单条内可用 and/or",
    ),
    search: Optional[str] = typer.Option(
        None, "--search", help="启动即全字段搜索（不分大小写；re: 前缀走正则），命中处高亮"
    ),
    sort: Optional[str] = typer.Option(
        None, "--sort", help="启动即全量排序，列名前加 - 为降序（如 -chars）"
    ),
):
    """交互式浏览数据（表格 + 详情联动，Textual TUI）

    表格扫视 + 详情按格式渲染（对话气泡/dpo对比/alpaca分段），无需逐层展开。
    大文件靠偏移索引窗口化浏览：只 parse 当前窗口，TUI 内按 ] / [ 翻窗口、: 跳行。
    筛选/搜索/排序都是全量的（扫整个文件），可叠加；TUI 内按 w 把结果导出成文件，
    按 C 复制"复现当前视图"的命令。管道模式 dt view - 从 stdin 读 NDJSON 全量入内存。
    需要交互式终端（TTY）。按 ? 查看快捷键。

    示例:
        dt view data.jsonl                       # 打开浏览器（顺序从第 1 行）
        dt view data.jsonl 100                   # 首屏 100 行（NUM = --cap 简写）
        dt view data.jsonl --format=dpo          # 强制按 dpo 渲染
        dt view big.jsonl --offset=20000         # 从第 2 万行开始（默认每窗口 1 万行）
        dt view big.jsonl --cap=50000            # 每窗口加载 5 万行
        dt view data.jsonl --sort=-chars         # 最长的样本排在最前（全量排序）
        dt view data.jsonl --where="turns>=6" --where="source==alpaca"   # 多条为与关系
        dt view data.jsonl --search=报错          # 命中子集 + 详情里黄底高亮
        dt sample data.jsonl 500 | dt view -     # 管道: 看采样/筛选等处理后结果
    """
    # 位置参数 NUM 优先于 --cap（与 sample/head 的 num_arg 惯例一致）
    _view(
        filename,
        cap=num_arg if num_arg is not None else cap,
        offset=offset,
        format_hint=format,
        where=where,
        search=search,
        sort=sort,
    )


@app.command("slice")
def slice_cmd(
    filename: str = typer.Argument(..., help="输入文件路径"),
    range_str: str = typer.Argument(..., help="行号范围 (start:end)，如 10:20、:100、100:、-10:"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
    fields: Optional[str] = typer.Option(None, "--fields", "-f", help="只显示指定字段"),
    pretty: bool = typer.Option(
        False,
        "--pretty",
        "-R",
        help="格式感知渲染: 对话气泡/dpo对比/alpaca分段/通用表格 (默认逐条 JSON)",
    ),
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
    preset: Optional[TransformPreset] = typer.Option(
        None,
        "--preset",
        "-p",
        help="使用预设模板: openai_chat|alpaca|sharegpt|dpo_pair|simple_qa",
        case_sensitive=False,
    ),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="配置文件路径"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预演: 计算结果但不写出 (退出码 10)"),
):
    """转换数据格式

    示例:
        dt transform data.jsonl --preset=openai_chat
        dt transform data.jsonl --config=./config.yaml -o out.jsonl
        dt transform data.jsonl --preset=alpaca --dry-run
    """
    preset_value = preset.value if isinstance(preset, TransformPreset) else preset
    _transform(filename, num, preset_value, config, output, dry_run=dry_run)


@app.command()
def run(
    config: str = typer.Argument(..., help="Pipeline YAML 配置文件"),
    input: Optional[str] = typer.Option(None, "--input", "-i", help="输入文件路径"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预演: 验证配置并打印步骤链 (退出码 10)"),
):
    """执行 Pipeline 配置文件

    示例:
        dt run pipeline.yaml
        dt run pipeline.yaml --input=data.jsonl --output=result.jsonl
        dt run pipeline.yaml --dry-run
    """
    _run(config, input, output, dry_run=dry_run)


# ============ 数据处理命令 ============


@app.command()
def dedupe(
    filename: str = typer.Argument(..., help="输入文件路径"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="去重依据字段"),
    similar: Optional[float] = typer.Option(None, "--similar", "-s", help="相似度阈值 (0-1)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预演: 计算结果但不写出 (退出码 10)"),
):
    """数据去重

    示例:
        dt dedupe data.jsonl --key=text                  # 精确去重
        dt dedupe data.jsonl --key=messages[0].content   # 按嵌套字段去重
        dt dedupe data.jsonl --key=text --similar=0.9    # 模糊去重（相似度 >= 0.9）
        dt dedupe data.jsonl --key=text --dry-run        # 预演
    """
    _dedupe(filename, key, similar, output, dry_run=dry_run)


@app.command()
def concat(
    files: List[str] = typer.Argument(..., help="输入文件列表 (至少两个)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径（必须）"),
    strict: bool = typer.Option(False, "--strict", help="严格模式，字段必须一致"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="预演: 分析字段/行数但不写出 (退出码 10)"
    ),
):
    """拼接多个数据文件

    示例:
        dt concat a.jsonl b.jsonl -o merged.jsonl
        dt concat data1.csv data2.csv data3.csv -o all.jsonl
        dt concat a.jsonl b.jsonl --strict -o merged.jsonl
        dt concat a.jsonl b.jsonl --dry-run -o merged.jsonl
    """
    _concat(*files, output=output, strict=strict, dry_run=dry_run)


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
    dry_run: bool = typer.Option(False, "--dry-run", help="预演: 计算结果但不写出 (退出码 10)"),
):
    """数据清洗

    示例:
        dt clean data.jsonl --drop-empty=text -o out.jsonl
        dt clean data.jsonl --min-len=messages.#:2       # 至少 2 条消息
        dt clean data.jsonl --rename=old:new --drop=debug
        dt clean data.jsonl --promote=meta.label --strip  # 提升嵌套字段 + 去空白
        dt clean data.jsonl --drop-empty=text --dry-run  # 预演, 退出码 10
    """
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
        dry_run=dry_run,
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
    """显示数据文件的统计信息

    示例:
        dt stats data.jsonl                       # 快速模式: 字段结构
        dt stats data.jsonl --full                # 完整模式: 值分布/唯一值
        dt stats data.jsonl --full --field=label  # 仅统计 label 字段
        dt stats data.jsonl --full --expand=tags  # 展开 list 字段
        dt --format=json stats data.jsonl         # 机器可读报告
    """
    _stats(filename, top, full, field, expand)


@app.command("token-stats")
def token_stats(
    filename: str = typer.Argument(..., help="输入文件路径"),
    field: str = typer.Option("messages", "--field", "-f", help="统计字段"),
    model: str = typer.Option(
        "cl100k_base", "--model", "-m", help="分词器: cl100k_base (默认), qwen2.5, llama3, gpt-4 等"
    ),
    detailed: bool = typer.Option(False, "--detailed", "-d", help="显示详细统计"),
    workers: Optional[int] = typer.Option(
        None, "--workers", "-w", help="并行进程数 (默认自动, 1 禁用并行)"
    ),
):
    """统计数据集的 Token 信息

    示例:
        dt token-stats data.jsonl --field=messages          # 默认 cl100k_base
        dt token-stats data.jsonl --field=text --model=qwen2.5
        dt token-stats data.jsonl --detailed
        dt --format=json token-stats data.jsonl             # JSON 报告
    """
    _token_stats(filename, field, model, detailed, workers)


@app.command()
def diff(
    file1: str = typer.Argument(..., help="第一个文件"),
    file2: str = typer.Argument(..., help="第二个文件"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="匹配键字段"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="报告输出路径"),
):
    """对比两个数据集的差异

    示例:
        dt diff v1.jsonl v2.jsonl                    # 无 key, 按行号对比
        dt diff v1.jsonl v2.jsonl --key=id           # 按 id 字段对齐
        dt diff v1.jsonl v2.jsonl --key=meta.uuid    # 按嵌套字段
        dt --format=json diff a.jsonl b.jsonl --key=id | jq .
    """
    _diff(file1, file2, key, output)


@app.command()
def history(
    filename: str = typer.Argument(..., help="数据文件路径"),
    json: bool = typer.Option(
        False, "--json", "-j", help="JSON 格式输出 (已废弃, 建议用 --format=json)"
    ),
):
    """显示数据文件的血缘历史

    示例:
        dt history processed.jsonl                   # TTY: 表格, 非 TTY: JSON
        dt --format=json history processed.jsonl     # 强制 JSON
    """
    _history(filename, json)


# ============ 切分与导出命令 ============


@app.command()
def split(
    filename: str = typer.Argument(..., help="输入文件路径"),
    ratio: str = typer.Option("0.8", "--ratio", "-r", help="分割比例，如 0.8 或 0.7,0.15,0.15"),
    seed: Optional[int] = typer.Option(None, "--seed", help="随机种子"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出目录（默认同目录）"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="预演: 计算各切分行数但不写出 (退出码 10)"
    ),
):
    """分割数据集为 train/test (或 train/val/test)

    示例:
        dt split data.jsonl --ratio=0.8
        dt split data.jsonl --ratio=0.7,0.15,0.15 --seed=42
        dt split data.jsonl --ratio=0.8 --dry-run
    """
    _split(filename, ratio, seed, output, dry_run=dry_run)


@app.command()
def export(
    filename: str = typer.Argument(..., help="输入文件路径"),
    framework: Framework = typer.Option(
        ...,
        "--framework",
        "-f",
        help="目标框架: llama-factory|swift|axolotl",
        case_sensitive=False,
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出目录"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="数据集名称"),
    check: bool = typer.Option(False, "--check", help="仅检查兼容性，不导出 (等价 --dry-run)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预演: 同 --check (退出码 10)"),
):
    """导出数据到训练框架 (LLaMA-Factory, ms-swift, Axolotl)

    示例:
        dt export data.jsonl --framework=llama-factory
        dt export data.jsonl --framework=swift -o dataset/
        dt export data.jsonl --framework=axolotl --dry-run
    """
    framework_value = framework.value if isinstance(framework, Framework) else framework
    _export(filename, framework_value, output, name, check, dry_run=dry_run)


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
    dry_run: bool = typer.Option(
        False, "--dry-run", help="预演: 解析预览但不生成 metrics 报告 (退出码 10)"
    ),
):
    """对模型输出进行解析和指标评估

    两阶段解析：自动清洗（去 think 标签、提取代码块）+ 管道式提取。

    示例:
        dt eval result.jsonl --label-col=label
        dt eval result.jsonl --extract="tag:标签" --mapping="是:1,否:0"
        dt eval result.jsonl --source=input.jsonl --response-col=api_output.content
        dt eval result.jsonl --extract="json_key:result | index:0" --sep=","
        dt eval result.jsonl --extract="lines | index:1" --sep="|"
        dt eval result.jsonl --label-col=label --dry-run
    """
    _eval(
        result_file,
        source,
        response_col,
        label_col,
        extract,
        sep,
        mapping,
        output_dir,
        dry_run=dry_run,
    )


# ============ 验证命令 ============


@app.command()
def validate(
    filename: str = typer.Argument(..., help="输入文件路径"),
    preset: Optional[ValidatePreset] = typer.Option(
        None,
        "--preset",
        "-p",
        help="预设 Schema: openai_chat|alpaca|dpo|sharegpt",
        case_sensitive=False,
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出有效数据的文件路径"),
    filter: bool = typer.Option(False, "--filter", "-f", help="过滤无效数据并保存"),
    max_errors: int = typer.Option(20, "--max-errors", help="最多显示的错误数量"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示详细信息"),
    workers: Optional[int] = typer.Option(
        None, "--workers", "-w", help="并行进程数 (默认自动, 1 禁用并行)"
    ),
):
    """使用预设 Schema 验证数据格式

    可用预设: openai_chat, alpaca, dpo, sharegpt

    示例:
        dt validate data.jsonl --preset=openai_chat
        dt validate data.jsonl --preset=alpaca -o valid.jsonl
        dt validate data.jsonl --preset=openai_chat --filter   # 过滤无效
        dt --format=json validate data.jsonl --preset=openai_chat  # JSON 报告

    退出码: 0 全部有效或命令成功, 2 参数错误 (未知预设), 3 文件不存在
    """
    preset_value = preset.value if isinstance(preset, ValidatePreset) else preset
    _validate(filename, preset_value, output, filter, max_errors, verbose, workers)


# ============ 工具命令 ============


@app.command()
def logs():
    """日志查看工具使用说明"""
    from .cli.output import log

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
    log(help_text)


# ============ Skill 命令 ============


@app.command("schema")
def schema_cmd(
    command: Optional[str] = typer.Argument(
        None,
        help="若指定则只输出该命令的 schema；否则输出所有命令的完整 schema",
    ),
):
    """输出命令树与参数定义 (JSON), 供 agent 内省使用.

    示例:
        dt schema                    # 输出完整命令树
        dt schema clean              # 输出 clean 命令的参数定义
        dt schema | jq '.commands[].name'
    """
    from .cli.schema import schema as _schema

    _schema(command, app=app)


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
