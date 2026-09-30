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
    管道    FILE 写 - 表示从 stdin 读 NDJSON; 数据命令不加 -o 时数据写 stdout,
            于是 dt sample a.jsonl -w "x.ok" | dt clean - --strip | dt head - 可串联
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
    filter/select/map/explode/sort/shuffle/group/join   数据原语 (可管道拼接)
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
    install-skill 安装 dtflow skill 到 Claude Code 或 Codex
"""

import os
import sys
from enum import Enum
from typing import List, Optional

import typer
import typer.rich_utils as _rich_utils

from .cli.commands import clean as _clean
from .cli.commands import concat as _concat
from .cli.commands import dedupe as _dedupe
from .cli.commands import describe as _describe
from .cli.commands import diff as _diff
from .cli.commands import eval as _eval
from .cli.commands import explode_cmd as _explode
from .cli.commands import export as _export
from .cli.commands import filter_cmd as _filter
from .cli.commands import group_cmd as _group
from .cli.commands import head as _head
from .cli.commands import history as _history
from .cli.commands import install_skill as _install_skill
from .cli.commands import join_cmd as _join
from .cli.commands import map_cmd as _map
from .cli.commands import run as _run
from .cli.commands import sample as _sample
from .cli.commands import select_cmd as _select
from .cli.commands import shuffle_cmd as _shuffle
from .cli.commands import skill_status as _skill_status
from .cli.commands import slice_data as _slice_data
from .cli.commands import sort_cmd as _sort
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
from .i18n import LANG, LANGS, t

# ============ 受约束参数枚举 ============
# 这些枚举让 click 在解析层就拒绝非法值，并把 choices 暴露给 `dt schema`。


class SampleType(str, Enum):
    """sample 命令的 --type 取值。"""

    random = "random"
    head = "head"
    tail = "tail"


class SkillTarget(str, Enum):
    """install-skill / uninstall-skill / skill-status 的目标 agent。"""

    claude = "claude"
    codex = "codex"


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
    help=t(
        f"Datatron CLI v{_VERSION} - data transformation toolkit (agent friendly)\n\n"
        "stdout=data, stderr=messages, exit codes in --help.\n"
        "Agents should start with: dt schema | dt --help | dt <cmd> --help\n\n"
        "Language: English. Switch to Chinese: dt lang zh (one-off: DT_LANG=zh dt ...)",
        f"Datatron CLI v{_VERSION} - 数据转换工具 (Agent 友好)\n\n"
        "stdout=数据, stderr=消息, 退出码见 --help.\n"
        "Agent 建议先运行: dt schema | dt --help | dt <cmd> --help\n\n"
        "界面语言: 中文。切换英文: dt lang en (临时: DT_LANG=en dt ...)",
    ),
    add_completion=True,
    no_args_is_help=True,
)

# typer 自带的帮助面板标题不走 t(), 在此覆盖
_rich_utils.ARGUMENTS_PANEL_TITLE = t("Arguments", "参数")
_rich_utils.OPTIONS_PANEL_TITLE = t("Options", "选项")
_rich_utils.COMMANDS_PANEL_TITLE = t("Commands", "命令")
_rich_utils.ERRORS_PANEL_TITLE = t("Error", "错误")


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
        help=t(
            "Output format: json|ndjson|csv|table (non-TTY default: ndjson; on a TTY data commands default to a table of the first 50 rows, --format=table renders everything; preview commands default to one JSON per record, table = format-aware rendering)",
            "输出格式: json|ndjson|csv|table (非 TTY 默认 ndjson; TTY 下数据命令默认表格且只看前 50 行, --format=table 全量; 预览命令默认逐条 JSON, table=格式渲染)",
        ),
    ),
    no_color: bool = typer.Option(
        False,
        "--no-color",
        help=t(
            "Disable colored output (also honors NO_COLOR / TERM=dumb)",
            "禁用彩色输出 (同样响应 NO_COLOR / TERM=dumb)",
        ),
    ),
    yes: bool = typer.Option(
        False, "--yes", help=t("Skip all interactive confirmations", "跳过所有交互确认")
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-V", help=t("Show more detailed logs", "显示更详细的日志")
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-Q", help=t("Suppress all stderr messages", "抑制所有 stderr 消息")
    ),
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,  # 先于其他选项处理: dt --version 不该被别的参数校验挡住
        help=t("Show the version and exit", "显示版本号并退出"),
    ),
):
    """全局运行状态注入；各命令通过 dtflow.cli.output.get_state() 读取。"""
    if fmt is not None and fmt not in {"json", "ndjson", "csv", "table"}:
        from .cli.output import die_usage

        die_usage(
            t(f"Unsupported --format value: {fmt}", f"不支持的 --format 值: {fmt}"),
            suggestion=t(
                "Choices: json | ndjson | csv | table", "可选值: json | ndjson | csv | table"
            ),
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


@app.command(
    help=t(
        "Sample records from a data file\n\n"
        "Examples:\n"
        "    dt sample data.jsonl --num=10                     # 10 random rows\n"
        "    dt sample data.jsonl 100 --by=category            # 100 rows stratified by field\n"
        '    dt sample data.jsonl --where="len(x.messages)>=2"      # filter, then sample\n'
        "    dt sample data.jsonl -w \"'alpaca' in x.meta.source\"   # substring match\n"
        '    dt sample data.jsonl --dist=\'{"A":0.5,"B":0.5}\' --by=label\n'
        "    dt --format=json sample data.jsonl                # JSON to stdout\n\n"
        "Exit codes: 0 success, 1 no rows left after filtering, 2 bad arguments, 3 file not found",
        "从数据文件中采样指定数量的数据\n\n"
        "示例:\n"
        "    dt sample data.jsonl --num=10                     # 随机 10 条\n"
        "    dt sample data.jsonl 100 --by=category            # 按字段分层 100 条\n"
        '    dt sample data.jsonl --where="len(x.messages)>=2"      # 筛选后采样\n'
        "    dt sample data.jsonl -w \"'alpaca' in x.meta.source\"   # 包含子串\n"
        '    dt sample data.jsonl --dist=\'{"A":0.5,"B":0.5}\' --by=label\n'
        "    dt --format=json sample data.jsonl                # stdout 输出 JSON\n\n"
        "退出码: 0 成功, 1 筛选后无数据, 2 参数错误, 3 文件不存在",
    )
)
def sample(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    num_arg: Optional[int] = typer.Argument(
        None, help=t("Number of records to sample", "采样数量"), metavar="NUM"
    ),
    num: int = typer.Option(
        10, "--num", "-n", help=t("Number of records to sample", "采样数量"), show_default=True
    ),
    type: Optional[SampleType] = typer.Option(
        None,
        "--type",
        "-t",
        help=t(
            "Sampling mode: random|head|tail (default random; head when n=0)",
            "采样方式: random|head|tail（默认 random，n=0 时默认 head）",
        ),
        case_sensitive=False,
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help=t("Output file path", "输出文件路径")
    ),
    seed: Optional[int] = typer.Option(None, "--seed", help=t("Random seed", "随机种子")),
    by: Optional[str] = typer.Option(
        None,
        "--by",
        help=t(
            "Field to stratify by (field path, e.g. meta.source; not an expression)",
            "分层采样字段 (字段路径, 如 meta.source; 不是表达式)",
        ),
    ),
    uniform: bool = typer.Option(
        False, "--uniform", help=t("Uniform sampling across strata", "均匀采样模式")
    ),
    dist: Optional[str] = typer.Option(
        None,
        "--dist",
        help=t(
            'Custom distribution (JSON), e.g. \'{"A":0.5,"B":0.3,"C":0.2}\'',
            '自定义分布 (JSON), 如 \'{"A":0.5,"B":0.3,"C":0.2}\'',
        ),
    ),
    fields: Optional[str] = typer.Option(
        None,
        "--fields",
        "-f",
        help=t("Show only these fields (comma-separated)", "只显示指定字段（逗号分隔）"),
    ),
    pretty: bool = typer.Option(
        False,
        "--pretty",
        "-R",
        help=t(
            "Format-aware rendering: chat bubbles / DPO comparison / alpaca sections / generic table (default: one JSON per record)",
            "格式感知渲染: 对话气泡/dpo对比/alpaca分段/通用表格 (默认逐条 JSON)",
        ),
    ),
    where: Optional[List[str]] = typer.Option(
        None,
        "--where",
        "-w",
        help=t(
            "Filter expression (Python, current row is x, e.g. \"x.score>0.5 and 'a' in x.text\"); repeatable (ANDed)",
            "筛选表达式 (Python, 当前行为 x, 如 \"x.score>0.5 and 'a' in x.text\"), 可多次 (与关系)",
        ),
    ),
):
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


@app.command(
    help=t(
        "Show the first N records\n\n"
        "Examples:\n"
        "    dt head data.jsonl 5                     # first 5\n"
        "    dt head data.jsonl --fields=id,text      # show only some fields\n"
        "    dt --format=json head data.jsonl | jq .  # machine-readable output",
        "显示文件的前 N 条数据\n\n"
        "示例:\n"
        "    dt head data.jsonl 5                     # 前 5 条\n"
        "    dt head data.jsonl --fields=id,text      # 只显示部分字段\n"
        "    dt --format=json head data.jsonl | jq .  # 机器可读输出",
    )
)
def head(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    num_arg: Optional[int] = typer.Argument(
        None, help=t("Number of records to show", "显示数量"), metavar="NUM"
    ),
    num: int = typer.Option(
        10, "--num", "-n", help=t("Number of records to show", "显示数量"), show_default=True
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help=t("Output file path", "输出文件路径")
    ),
    fields: Optional[str] = typer.Option(
        None, "--fields", "-f", help=t("Show only these fields", "只显示指定字段")
    ),
    pretty: bool = typer.Option(
        False,
        "--pretty",
        "-R",
        help=t(
            "Format-aware rendering: chat bubbles / DPO comparison / alpaca sections / generic table (default: one JSON per record)",
            "格式感知渲染: 对话气泡/dpo对比/alpaca分段/通用表格 (默认逐条 JSON)",
        ),
    ),
):
    # 位置参数优先于选项参数
    actual_num = num_arg if num_arg is not None else num
    _head(filename, actual_num, output, fields, not pretty)


@app.command(
    help=t(
        "Show the last N records\n\n"
        "Examples:\n"
        "    dt tail data.jsonl 5                     # last 5\n"
        "    dt tail data.jsonl --fields=id,label",
        "显示文件的后 N 条数据\n\n"
        "示例:\n"
        "    dt tail data.jsonl 5                     # 后 5 条\n"
        "    dt tail data.jsonl --fields=id,label",
    )
)
def tail(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    num_arg: Optional[int] = typer.Argument(
        None, help=t("Number of records to show", "显示数量"), metavar="NUM"
    ),
    num: int = typer.Option(
        10, "--num", "-n", help=t("Number of records to show", "显示数量"), show_default=True
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help=t("Output file path", "输出文件路径")
    ),
    fields: Optional[str] = typer.Option(
        None, "--fields", "-f", help=t("Show only these fields", "只显示指定字段")
    ),
    pretty: bool = typer.Option(
        False,
        "--pretty",
        "-R",
        help=t(
            "Format-aware rendering: chat bubbles / DPO comparison / alpaca sections / generic table (default: one JSON per record)",
            "格式感知渲染: 对话气泡/dpo对比/alpaca分段/通用表格 (默认逐条 JSON)",
        ),
    ),
):
    # 位置参数优先于选项参数
    actual_num = num_arg if num_arg is not None else num
    _tail(filename, actual_num, output, fields, not pretty)


@app.command(
    context_settings={"ignore_unknown_options": True},
    help=t(
        "Browse data interactively (linked table + detail, Textual TUI)\n\n"
        "Scan the table; details render per format (chat bubbles / DPO comparison / alpaca sections), no drilling down.\n"
        "Large files are browsed in windows via an offset index: only the current window is parsed; ] / [ page windows, : jumps to a row.\n"
        "A negative NUM opens at the end of the file; --follow keeps tailing as JSONL/NDJSON is appended or rotated.\n"
        "Filter / search / sort all scan the whole file and can be combined; press r to clear them and browse everything again;\n"
        "press w to export the results to a file, C to copy a command that reproduces the current view,\n"
        "P to copy the same conditions as a processing chain (dt filter FILE '…' | dt sort - --by '…').\n"
        "Full scans of JSONL run in parallel over byte ranges (tune with env var DTFLOW_VIEW_WORKERS,\n"
        "1 forces serial). Pipe mode dt view - reads NDJSON from stdin fully into memory.\n"
        "Double-click a column header to rename it: the view updates at once, and q asks whether to\n"
        "write the new names back to the file (streamed rewrite, lineage recorded) or discard them.\n"
        "Requires an interactive terminal (TTY). Press ? for key bindings.\n\n"
        "Examples:\n"
        "    dt view data.jsonl                       # open the browser (from row 1)\n"
        "    dt view data.jsonl 100                   # browse from the start, 100-row window\n"
        "    dt view data.jsonl -100                  # start at the last 100 rows\n"
        "    dt view app.jsonl -100 -f                # follow the latest 100 rows (-f=--follow)\n"
        "    dt view data.jsonl --format=dpo          # force dpo rendering\n"
        "    dt view big.jsonl --offset=20000         # start at row 20,000 (default window: 10,000 rows)\n"
        "    dt view big.jsonl --cap=50000            # load 50,000 rows per window\n"
        "    dt view data.jsonl -S -chars             # sort by length, descending (-S=--sort)\n"
        '    dt view data.jsonl -w "turns(x)>=6" -w "x.source==\'alpaca\'"   # multiple filters are ANDed\n'
        "    dt view data.jsonl -s error              # search everything, highlight hits (-s=--search)\n"
        "    dt sample data.jsonl 500 | dt view -     # pipe: inspect sampled/filtered results\n"
        "    dt view data.jsonl --pipe 'dt filter - \"turns(x)>=6\" | dt head - 200'   # run a pipe first (| inside the TUI)",
        "交互式浏览数据（表格 + 详情联动，Textual TUI）\n\n"
        "表格扫视 + 详情按格式渲染（对话气泡/dpo对比/alpaca分段），无需逐层展开。\n"
        "大文件靠偏移索引窗口化浏览：只 parse 当前窗口，TUI 内按 ] / [ 翻窗口、: 跳行。\n"
        "NUM 为负数时快速从文件尾部打开；--follow 在 JSONL/NDJSON 追加或轮转时持续追尾。\n"
        "筛选/搜索/排序都是全量的（扫整个文件），可叠加，按 r 一键清空回到全量浏览；\n"
        'TUI 内按 w 把结果导出成文件，按 C 复制"复现当前视图"的命令，\n'
        "按 P 把同一套条件复制成处理链 (dt filter FILE '…' | dt sort - --by '…')。\n"
        "JSONL 的全量扫描按字节区间分片并行（环境变量 DTFLOW_VIEW_WORKERS 可调并行度，\n"
        "设为 1 强制串行）。管道模式 dt view - 从 stdin 读 NDJSON 全量入内存。\n"
        "双击列头可重命名：界面即时生效，按 q 退出时询问是否把新列名写回文件（流式重写并记血缘）或丢弃。\n"
        "需要交互式终端（TTY）。按 ? 查看快捷键。\n\n"
        "示例:\n"
        "    dt view data.jsonl                       # 打开浏览器（顺序从第 1 行）\n"
        "    dt view data.jsonl 100                   # 从开头浏览，窗口 100 行\n"
        "    dt view data.jsonl -100                  # 快速从倒数 100 行开始\n"
        "    dt view app.jsonl -100 -f                # 追踪最新 100 行 (-f=--follow)\n"
        "    dt view data.jsonl --format=dpo          # 强制按 dpo 渲染\n"
        "    dt view big.jsonl --offset=20000         # 从第 2 万行开始（默认每窗口 1 万行）\n"
        "    dt view big.jsonl --cap=50000            # 每窗口加载 5 万行\n"
        "    dt view data.jsonl -S -chars             # 按长度降序 (-S=--sort)\n"
        '    dt view data.jsonl -w "turns(x)>=6" -w "x.source==\'alpaca\'"   # 多条为与关系\n'
        "    dt view data.jsonl -s 报错               # 全量搜索并高亮 (-s=--search)\n"
        "    dt sample data.jsonl 500 | dt view -     # 管道: 看采样/筛选等处理后结果\n"
        "    dt view data.jsonl --pipe 'dt filter - \"turns(x)>=6\" | dt head - 200'   # 先跑一段管道 (TUI 内按 | 同义)",
    ),
)
def view(
    filename: str = typer.Argument(
        ...,
        help=t(
            "Input file path; - reads from stdin (pipe mode)",
            "输入文件路径；- 表示从 stdin 读（管道模式）",
        ),
    ),
    num_arg: Optional[int] = typer.Argument(
        None,
        metavar="NUM",
        help=t(
            "Rows per window; positive opens at the start, negative at the end; ]/[ still page windows",
            "窗口行数；正数从开头、负数从末尾打开，仍可 ]/[ 翻窗口",
        ),
    ),
    cap: int = typer.Option(
        _VIEW_CAP,
        "--cap",
        help=t(
            "Rows loaded per window (only this many are parsed; the rest are paged on demand)",
            "单窗口加载行数（只 parse 这么多，其余按需翻页）",
        ),
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        help=t(
            "Starting row (0-based) to open mid-file (ignored for stdin)",
            "起始行号（0-based），从文件中间打开（stdin 模式无效）",
        ),
    ),
    format: Optional[str] = typer.Option(
        None,
        "--format",
        help=t(
            "Force format: openai_chat|sharegpt|dpo|alpaca|generic",
            "强制格式: openai_chat|sharegpt|dpo|alpaca|generic",
        ),
    ),
    where: Optional[List[str]] = typer.Option(
        None,
        "--where",
        "-w",
        help=t(
            "Filter on startup (Python expression, current row is x, same as dt filter: turns(x)>=6); repeatable (ANDed)",
            "启动即筛选 (Python 表达式, 当前行为 x, 与 dt filter 同一套: turns(x)>=6), 可多次 (与关系)",
        ),
    ),
    search: Optional[str] = typer.Option(
        None,
        "--search",
        "-s",
        help=t(
            "Search all fields on startup (case-insensitive; re: prefix for regex), highlighting matches",
            "启动即全字段搜索（不分大小写；re: 前缀走正则），命中处高亮",
        ),
    ),
    sort: Optional[str] = typer.Option(
        None,
        "--sort",
        "-S",
        help=t(
            "Sort all rows on startup; prefix a column with - for descending (e.g. -chars)",
            "启动即全量排序，列名前加 - 为降序（如 -chars）",
        ),
    ),
    follow: bool = typer.Option(
        False,
        "--follow",
        "-f",
        help=t(
            "Follow JSONL/NDJSON appends and log rotation live, starting from the latest window",
            "实时追踪 JSONL/NDJSON 追加与日志轮转，从最新尾窗开始",
        ),
    ),
    pipe: Optional[str] = typer.Option(
        None,
        "--pipe",
        help=t(
            "Run this shell pipe over the whole file first (NDJSON in/out) and browse its output; same as pressing | inside",
            "先对全文件跑这段 shell 管道 (进出 NDJSON), 浏览它的输出; 等同于在 TUI 内按 |",
        ),
    ),
):
    from pathlib import Path

    from .cli.output import die_usage

    if follow and pipe:
        die_usage(
            t("--follow cannot be used with --pipe", "--follow 不能与 --pipe 同时使用"),
            suggestion=t(
                "Run the pipe in the shell and follow its output file",
                "在 shell 里跑管道, 再 follow 它的输出文件",
            ),
        )

    actual_cap = abs(num_arg) if num_arg is not None else cap
    tail = bool(num_arg is not None and num_arg < 0)
    if actual_cap <= 0:
        die_usage(
            t("dt view window size must be greater than 0", "dt view 的窗口大小必须大于 0"),
            suggestion=t("e.g. dt view data.jsonl 100", "例如: dt view data.jsonl 100"),
        )
    if tail and offset:
        die_usage(
            t("-NUM cannot be used with --offset", "-NUM 不能与 --offset 同时使用"),
            suggestion=t("Remove --offset", "删除 --offset"),
        )
    if follow and offset:
        die_usage(
            t("--follow cannot be used with --offset", "--follow 不能与 --offset 同时使用"),
            suggestion=t(
                "Follow mode always starts from the latest rows", "追尾模式固定从最新处开始"
            ),
        )
    if follow and sort:
        die_usage(
            t(
                "--follow cannot be used with startup sorting (--sort)",
                "--follow 不能与启动排序 --sort 同时使用",
            ),
            suggestion=t(
                "Start follow first, then press s to sort up to the current high-water mark when needed",
                "先进入 follow，需要时再按 s 对固定高水位排序",
            ),
        )
    if follow and filename == "-":
        die_usage(
            t("--follow does not support stdin", "--follow 不支持 stdin"),
            suggestion=t(
                "Pass a JSONL/NDJSON file path directly", "请直接传入 JSONL/NDJSON 文件路径"
            ),
        )
    if follow and Path(filename).suffix.lower() not in (".jsonl", ".ndjson"):
        die_usage(
            t("--follow only supports JSONL/NDJSON files", "--follow 仅支持 JSONL/NDJSON 文件"),
            suggestion=t(
                "For plain-text logs, use tl --tail FILE", "纯文本日志可使用 tl --tail FILE"
            ),
        )

    _view(
        filename,
        cap=actual_cap,
        offset=offset,
        format_hint=format,
        where=where,
        search=search,
        sort=sort,
        tail=tail,
        follow=follow,
        pipe=pipe,
    )


@app.command(
    "slice",
    help=t(
        "View rows by line range (Python slice syntax)\n\n"
        "Examples:\n"
        "    dt slice data.jsonl 10:20     rows 10-19\n"
        "    dt slice data.jsonl :100      first 100 rows\n"
        "    dt slice data.jsonl 100:      row 100 to the end\n"
        "    dt slice data.jsonl -10:      last 10 rows",
        "按行号范围查看数据（Python 切片语法）\n\n"
        "示例:\n"
        "    dt slice data.jsonl 10:20     第 10-19 行\n"
        "    dt slice data.jsonl :100      前 100 行\n"
        "    dt slice data.jsonl 100:      第 100 行到末尾\n"
        "    dt slice data.jsonl -10:      最后 10 行",
    ),
)
def slice_cmd(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    range_str: str = typer.Argument(
        ...,
        help=t(
            "Row range (start:end), e.g. 10:20, :100, 100:, -10:",
            "行号范围 (start:end)，如 10:20、:100、100:、-10:",
        ),
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help=t("Output file path", "输出文件路径")
    ),
    fields: Optional[str] = typer.Option(
        None, "--fields", "-f", help=t("Show only these fields", "只显示指定字段")
    ),
    pretty: bool = typer.Option(
        False,
        "--pretty",
        "-R",
        help=t(
            "Format-aware rendering: chat bubbles / DPO comparison / alpaca sections / generic table (default: one JSON per record)",
            "格式感知渲染: 对话气泡/dpo对比/alpaca分段/通用表格 (默认逐条 JSON)",
        ),
    ),
):
    _slice_data(filename, range_str, output, fields, not pretty)


# ============ 数据转换命令 ============


@app.command(
    help=t(
        "Convert data format\n\n"
        "Examples:\n"
        "    dt transform data.jsonl --preset=openai_chat -o out.jsonl\n"
        "    dt transform data.jsonl --config=./config.py -o out.jsonl\n"
        "    dt transform data.jsonl --preset=alpaca --dry-run\n"
        '    dt sample data.jsonl -w "x.ok" | dt transform - --preset=openai_chat | dt head -',
        "转换数据格式\n\n"
        "示例:\n"
        "    dt transform data.jsonl --preset=openai_chat -o out.jsonl\n"
        "    dt transform data.jsonl --config=./config.py -o out.jsonl\n"
        "    dt transform data.jsonl --preset=alpaca --dry-run\n"
        '    dt sample data.jsonl -w "x.ok" | dt transform - --preset=openai_chat | dt head -',
    )
)
def transform(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    num: Optional[int] = typer.Argument(
        None, help=t("Convert only the first N records", "只转换前 N 条数据")
    ),
    preset: Optional[TransformPreset] = typer.Option(
        None,
        "--preset",
        "-p",
        help=t(
            "Target format: openai_chat|alpaca|sharegpt|dpo_pair|simple_qa; input is auto-detected (messages/sharegpt/alpaca/dpo/q-a, except for dpo_pair), tool calls are converted, unrecognized rows are skipped and summarized",
            "目标格式: openai_chat|alpaca|sharegpt|dpo_pair|simple_qa; 自动识别输入 (messages/sharegpt/alpaca/dpo/q-a, dpo_pair 除外), 工具调用互转, 认不出的行跳过并汇总",
        ),
        case_sensitive=False,
    ),
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help=t("Config file path", "配置文件路径")
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help=t(
            "Output file path (default: stdout; in config mode, the config's output)",
            "输出文件路径 (不指定则写 stdout; 配置模式取配置里的 output)",
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=t(
            "Dry run: compute results without writing (exit code 10)",
            "预演: 计算结果但不写出 (退出码 10)",
        ),
    ),
):
    preset_value = preset.value if isinstance(preset, TransformPreset) else preset
    _transform(filename, num, preset_value, config, output, dry_run=dry_run)


@app.command(
    help=t(
        "Run a pipeline config file (a step's type is a CLI command name, its params are option names)\n\n"
        "Examples:\n"
        "    dt run pipeline.yaml\n"
        "    dt run pipeline.yaml --input=data.jsonl --output=result.jsonl\n"
        "    cat data.jsonl | dt run pipeline.yaml -i - | dt head -\n"
        "    dt run pipeline.yaml --dry-run",
        "执行 Pipeline 配置文件 (step 的 type 即 CLI 命令名, 参数即选项名)\n\n"
        "示例:\n"
        "    dt run pipeline.yaml\n"
        "    dt run pipeline.yaml --input=data.jsonl --output=result.jsonl\n"
        "    cat data.jsonl | dt run pipeline.yaml -i - | dt head -\n"
        "    dt run pipeline.yaml --dry-run",
    )
)
def run(
    config: str = typer.Argument(
        ..., help=t("Pipeline YAML config file", "Pipeline YAML 配置文件")
    ),
    input: Optional[str] = typer.Option(
        None,
        "--input",
        "-i",
        help=t(
            "Input file path (overrides config; - for stdin)", "输入文件路径 (覆盖配置; - 为 stdin)"
        ),
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help=t(
            "Output file path (overrides config; stdout if neither is set; a trailing split derives _train/_test from it)",
            "输出文件路径 (覆盖配置; 都没有则写 stdout; split 结尾按它派生 _train/_test)",
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=t(
            "Dry run: validate the config and print the step chain (exit code 10)",
            "预演: 验证配置并打印步骤链 (退出码 10)",
        ),
    ),
):
    _run(config, input, output, dry_run=dry_run)


# ============ 数据处理命令 ============


@app.command(
    help=t(
        "Deduplicate data (exact dedupe streams, O(unique keys) memory)\n\n"
        "Examples:\n"
        "    dt dedupe data.jsonl --key=text -i               # exact dedupe, write back in place\n"
        "    dt dedupe data.jsonl --key=messages[0].content -o out.jsonl   # dedupe by nested field\n"
        "    dt dedupe data.jsonl --key=text --similar=0.9    # fuzzy dedupe (similarity >= 0.9) → stdout\n"
        "    dt dedupe data.jsonl --key=text --dry-run        # dry run",
        "数据去重 (精确去重流式, O(唯一键) 内存)\n\n"
        "示例:\n"
        "    dt dedupe data.jsonl --key=text -i               # 精确去重, 原地写回\n"
        "    dt dedupe data.jsonl --key=messages[0].content -o out.jsonl   # 按嵌套字段去重\n"
        "    dt dedupe data.jsonl --key=text --similar=0.9    # 模糊去重（相似度 >= 0.9）→ stdout\n"
        "    dt dedupe data.jsonl --key=text --dry-run        # 预演",
    )
)
def dedupe(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    key: Optional[str] = typer.Option(
        None, "--key", "-k", help=t("Field to deduplicate by", "去重依据字段")
    ),
    similar: Optional[float] = typer.Option(
        None, "--similar", "-s", help=t("Similarity threshold (0-1)", "相似度阈值 (0-1)")
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help=t("Output file path (default: stdout)", "输出文件路径 (不指定则写 stdout)"),
    ),
    in_place: bool = typer.Option(
        False,
        "--in-place",
        "-i",
        help=t("Write back to the input file in place", "原地写回输入文件"),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=t(
            "Dry run: compute results without writing (exit code 10)",
            "预演: 计算结果但不写出 (退出码 10)",
        ),
    ),
):
    _dedupe(filename, key, similar, output, in_place=in_place, dry_run=dry_run)


@app.command(
    help=t(
        "Concatenate multiple data files\n\n"
        "Examples:\n"
        "    dt concat a.jsonl b.jsonl -o merged.jsonl\n"
        "    dt concat data1.csv data2.csv data3.csv -o all.jsonl\n"
        "    dt concat a.jsonl b.jsonl --strict -o merged.jsonl\n"
        "    dt concat a.jsonl b.jsonl --dry-run -o merged.jsonl",
        "拼接多个数据文件\n\n"
        "示例:\n"
        "    dt concat a.jsonl b.jsonl -o merged.jsonl\n"
        "    dt concat data1.csv data2.csv data3.csv -o all.jsonl\n"
        "    dt concat a.jsonl b.jsonl --strict -o merged.jsonl\n"
        "    dt concat a.jsonl b.jsonl --dry-run -o merged.jsonl",
    )
)
def concat(
    files: List[str] = typer.Argument(
        ...,
        help=t(
            "Input files (at least two; at most one - for stdin)",
            "输入文件列表 (至少两个; 至多一个 - 表示 stdin)",
        ),
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help=t("Output file path (default: stdout)", "输出文件路径 (不指定则写 stdout)"),
    ),
    strict: bool = typer.Option(
        False, "--strict", help=t("Strict mode: fields must match", "严格模式，字段必须一致")
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=t(
            "Dry run: analyze fields/row counts without writing (exit code 10)",
            "预演: 分析字段/行数但不写出 (退出码 10)",
        ),
    ),
):
    _concat(*files, output=output, strict=strict, dry_run=dry_run)


@app.command(
    help=t(
        "Clean data (streaming; stdout without -o, -i writes back in place)\n\n"
        "Examples:\n"
        "    dt clean data.jsonl --drop-empty=text -o out.jsonl\n"
        "    dt clean data.jsonl --min-len=messages.#:2 -i    # at least 2 messages, in place\n"
        "    dt clean data.jsonl --rename=old:new --drop=debug | dt head -\n"
        "    dt clean data.jsonl --promote=meta.label --strip -i  # promote nested field + strip whitespace\n"
        "    dt clean data.jsonl --drop-empty=text --dry-run  # dry run, exit code 10",
        "数据清洗 (流式; 无 -o 写 stdout, -i 原地写回)\n\n"
        "示例:\n"
        "    dt clean data.jsonl --drop-empty=text -o out.jsonl\n"
        "    dt clean data.jsonl --min-len=messages.#:2 -i    # 至少 2 条消息, 原地写回\n"
        "    dt clean data.jsonl --rename=old:new --drop=debug | dt head -\n"
        "    dt clean data.jsonl --promote=meta.label --strip -i  # 提升嵌套字段 + 去空白\n"
        "    dt clean data.jsonl --drop-empty=text --dry-run  # 预演, 退出码 10",
    )
)
def clean(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    drop_empty: Optional[str] = typer.Option(
        None, "--drop-empty", help=t("Drop records with empty values", "删除空值记录")
    ),
    min_len: Optional[str] = typer.Option(
        None,
        "--min-len",
        help=t("Minimum length filter (field:length)", "最小长度过滤 (字段:长度)"),
    ),
    max_len: Optional[str] = typer.Option(
        None,
        "--max-len",
        help=t("Maximum length filter (field:length)", "最大长度过滤 (字段:长度)"),
    ),
    keep: Optional[str] = typer.Option(
        None, "--keep", help=t("Keep only these fields", "只保留指定字段")
    ),
    drop: Optional[str] = typer.Option(None, "--drop", help=t("Drop these fields", "删除指定字段")),
    rename: Optional[str] = typer.Option(
        None,
        "--rename",
        help=t("Rename fields (old:new,old2:new2)", "重命名字段 (old:new,old2:new2)"),
    ),
    promote: Optional[str] = typer.Option(
        None,
        "--promote",
        help=t(
            "Promote nested fields to top level (meta.label or meta.label:tag)",
            "提升嵌套字段到顶层 (meta.label 或 meta.label:tag)",
        ),
    ),
    add_field: Optional[str] = typer.Option(
        None, "--add-field", help=t("Add a constant field (key:value)", "添加常量字段 (key:value)")
    ),
    fill: Optional[str] = typer.Option(
        None,
        "--fill",
        help=t("Fill empty values (field:default_value)", "填充空值 (field:default_value)"),
    ),
    reorder: Optional[str] = typer.Option(
        None,
        "--reorder",
        help=t("Set field order (field1,field2,...)", "控制字段顺序 (field1,field2,...)"),
    ),
    strip: bool = typer.Option(
        False,
        "--strip",
        help=t("Strip leading/trailing whitespace from strings", "去除字符串首尾空白"),
    ),
    min_tokens: Optional[str] = typer.Option(
        None,
        "--min-tokens",
        help=t("Minimum token count filter (field:count)", "最小 token 数过滤 (字段:数量)"),
    ),
    max_tokens: Optional[str] = typer.Option(
        None,
        "--max-tokens",
        help=t("Maximum token count filter (field:count)", "最大 token 数过滤 (字段:数量)"),
    ),
    model: str = typer.Option(
        "cl100k_base",
        "--model",
        "-m",
        help=t("Tokenizer model (default cl100k_base)", "分词器模型 (默认 cl100k_base)"),
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help=t("Output file path (default: stdout)", "输出文件路径 (不指定则写 stdout)"),
    ),
    in_place: bool = typer.Option(
        False,
        "--in-place",
        "-i",
        help=t("Write back to the input file in place", "原地写回输入文件"),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=t(
            "Dry run: compute results without writing (exit code 10)",
            "预演: 计算结果但不写出 (退出码 10)",
        ),
    ),
):
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
        in_place=in_place,
        dry_run=dry_run,
    )


# ============ 数据原语命令 (可管道拼接; 表达式即 Python, 当前行为 x) ============

_OUT_HELP = t("Output file path (default: stdout)", "输出文件路径 (不指定则写 stdout)")
_STRICT_HELP = t(
    "Exit with an error when an expression fails (default: filter skips the row / select sets the item to null / map keeps the row unchanged / sort puts it last, with a summary at the end)",
    "表达式求值失败即报错退出 (默认: filter 跳过该行 / select 该项置 null / map 该行原样保留 / sort 排末尾, 结束时汇总)",
)


@app.command(
    "filter",
    help=t(
        "Keep rows where the expression is true\n\n"
        "Examples:\n"
        "    dt filter data.jsonl \"x.score > 0.5 and 'wiki' in x.meta.source\"\n"
        "    dt filter data.jsonl \"len(x.messages) >= 2 and x.messages[-1].role == 'assistant'\"\n"
        "    dt filter data.jsonl \"any('refund' in m.content for m in x.messages)\" -o hit.jsonl\n"
        "    dt filter data.jsonl \"re.search(r'\\d{4}', x.text)\" | dt head -",
        "保留表达式为真的行\n\n"
        "示例:\n"
        "    dt filter data.jsonl \"x.score > 0.5 and 'wiki' in x.meta.source\"\n"
        "    dt filter data.jsonl \"len(x.messages) >= 2 and x.messages[-1].role == 'assistant'\"\n"
        "    dt filter data.jsonl \"any('退款' in m.content for m in x.messages)\" -o hit.jsonl\n"
        "    dt filter data.jsonl \"re.search(r'\\d{4}', x.text)\" | dt head -",
    ),
)
def filter_cmd(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    expr: str = typer.Argument(
        ..., help=t("Python expression; current row is x", "Python 表达式, 当前行为 x")
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    strict: bool = typer.Option(False, "--strict", help=_STRICT_HELP),
):
    _filter(filename, expr, output, strict)


@app.command(
    "select",
    help=t(
        "Project / rename / derive fields (output key order = SPEC order)\n\n"
        "Examples:\n"
        '    dt select data.jsonl "id,text"                              # keep two columns\n'
        '    dt select data.jsonl "id,n=len(x.messages),last=x.messages[-1].content"\n'
        '    dt select data.jsonl "prompt=x.instruction,answer=x.output" # rename',
        "投影 / 重命名 / 派生字段 (输出键序 = SPEC 序)\n\n"
        "示例:\n"
        '    dt select data.jsonl "id,text"                              # 只留两列\n'
        '    dt select data.jsonl "id,n=len(x.messages),last=x.messages[-1].content"\n'
        '    dt select data.jsonl "prompt=x.instruction,answer=x.output" # 重命名',
    ),
)
def select_cmd(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    spec: str = typer.Argument(
        ...,
        metavar="FIELDS",
        help=t(
            "Field list: literal field names or new_name=expression, comma-separated",
            "字段列表: 字面字段名 或 新名=表达式, 逗号分隔",
        ),
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    strict: bool = typer.Option(False, "--strict", help=_STRICT_HELP),
):
    _select(filename, spec, output, strict)


@app.command(
    "map",
    help=t(
        "Run Python statements on each row (modifying x in place)\n\n"
        "Examples:\n"
        '    dt map data.jsonl "x.text = x.text.strip()"\n'
        '    dt map data.jsonl "x.n = len(x.messages); del x.debug"\n'
        "    dt map data.jsonl \"x.messages.append({'role': 'assistant', 'content': x.answer})\"",
        "对每行执行 Python 语句 (原地修改 x)\n\n"
        "示例:\n"
        '    dt map data.jsonl "x.text = x.text.strip()"\n'
        '    dt map data.jsonl "x.n = len(x.messages); del x.debug"\n'
        "    dt map data.jsonl \"x.messages.append({'role': 'assistant', 'content': x.answer})\"",
    ),
)
def map_cmd(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    code: str = typer.Argument(
        ...,
        help=t(
            "Python statements that modify x in place (separate with ; or newlines)",
            "Python 语句, 原地修改 x (; 或换行分隔多句)",
        ),
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    strict: bool = typer.Option(False, "--strict", help=_STRICT_HELP),
):
    _map(filename, code, output, strict)


@app.command(
    "explode",
    help=t(
        "Explode a list field into multiple rows (other fields are copied)\n\n"
        "Examples:\n"
        "    dt explode data.jsonl --field messages                 # one row per message\n"
        "    dt explode data.jsonl --field tags --as tag --index-as i",
        "把 list 字段展开为多行 (其余字段复制)\n\n"
        "示例:\n"
        "    dt explode data.jsonl --field messages                 # 每条消息一行\n"
        "    dt explode data.jsonl --field tags --as tag --index-as i",
    ),
)
def explode_cmd(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    field: str = typer.Option(
        ...,
        "--field",
        "-f",
        help=t("List field to explode (top level)", "要展开的 list 字段 (顶层)"),
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    as_name: Optional[str] = typer.Option(
        None,
        "--as",
        help=t(
            "Field name for exploded elements (default: same name)", "展开后元素的字段名 (默认同名)"
        ),
    ),
    index_as: Optional[str] = typer.Option(
        None, "--index-as", help=t("Write the element index to this field", "把元素下标写入该字段")
    ),
):
    _explode(filename, field, output, as_name, index_as)


@app.command(
    "sort",
    help=t(
        "Sort by expression (loads everything; rows whose key fails sort last)\n\n"
        "Examples:\n"
        "    dt sort data.jsonl --by x.score --desc\n"
        '    dt sort data.jsonl --by "len(x.messages)"\n'
        '    dt sort data.jsonl --by "(x.source, -x.score)"',
        "按表达式排序 (全量加载; 键求值失败的行排最后)\n\n"
        "示例:\n"
        "    dt sort data.jsonl --by x.score --desc\n"
        '    dt sort data.jsonl --by "len(x.messages)"\n'
        '    dt sort data.jsonl --by "(x.source, -x.score)"',
    ),
)
def sort_cmd(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    by: str = typer.Option(
        ...,
        "--by",
        "-b",
        help=t(
            "Sort key expression, e.g. x.score or (x.a, -x.b)",
            "排序键表达式, 如 x.score 或 (x.a, -x.b)",
        ),
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    desc: bool = typer.Option(False, "--desc", help=t("Sort descending", "降序")),
    strict: bool = typer.Option(False, "--strict", help=_STRICT_HELP),
):
    _sort(filename, by, output, desc, strict)


@app.command(
    "shuffle",
    help=t(
        "Shuffle all rows\n\nExamples:\n    dt shuffle data.jsonl --seed 42 -o shuffled.jsonl",
        "全量打乱\n\n示例:\n    dt shuffle data.jsonl --seed 42 -o shuffled.jsonl",
    ),
)
def shuffle_cmd(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    seed: Optional[int] = typer.Option(None, "--seed", help=t("Random seed", "随机种子")),
):
    _shuffle(filename, output, seed)


@app.command(
    "group",
    help=t(
        "Group by expression: streaming counts by default, custom aggregations with --agg\n\n"
        "Examples:\n"
        '    dt group data.jsonl --by x.meta.source                 # {"key","count","pct"} sorted by count desc\n'
        '    dt group data.jsonl --by "roles(x)" --top 10           # the 10 largest groups (--agg mode: by n)\n'
        '    dt group data.jsonl --by x.label --agg "avg=mean(len(r.text) for r in g)"',
        "按表达式分组: 默认流式计数, --agg 自定义聚合\n\n"
        "示例:\n"
        '    dt group data.jsonl --by x.meta.source                 # {"key","count","pct"} 按 count 降序\n'
        '    dt group data.jsonl --by "roles(x)" --top 10           # 只留最大的 10 组 (--agg 模式按 n)\n'
        '    dt group data.jsonl --by x.label --agg "avg=mean(len(r.text) for r in g)"',
    ),
)
def group_cmd(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    by: str = typer.Option(..., "--by", "-b", help=t("Group key expression", "分组键表达式")),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    agg: Optional[str] = typer.Option(
        None,
        "--agg",
        help=t(
            "Aggregations: name=expression,... using g (rows in group) / key / n / mean / median",
            "聚合: name=表达式,... 可用 g(组内行) / key / n / mean / median",
        ),
    ),
    strict: bool = typer.Option(False, "--strict", help=_STRICT_HELP),
    top: Optional[int] = typer.Option(
        None, "--top", help=t("Keep only the N largest groups", "只保留最大的 N 组")
    ),
):
    _group(filename, by, output, agg, strict, top)


@app.command(
    "join",
    help=t(
        "Join two datasets by key (left streamed, right in memory; left fields win)\n\n"
        "Examples:\n"
        "    dt join data.jsonl meta.jsonl --on x.id\n"
        "    dt join data.jsonl meta.jsonl --left-on x.uid --right-on x.user_id --prefix m_\n"
        "    dt join data.jsonl labels.jsonl --on x.id --inner -o labeled.jsonl",
        "按键连接两个数据集 (左表流式, 右表入内存; 左表字段优先)\n\n"
        "示例:\n"
        "    dt join data.jsonl meta.jsonl --on x.id\n"
        "    dt join data.jsonl meta.jsonl --left-on x.uid --right-on x.user_id --prefix m_\n"
        "    dt join data.jsonl labels.jsonl --on x.id --inner -o labeled.jsonl",
    ),
)
def join_cmd(
    left: str = typer.Argument(
        ..., help=t("Left table (streamed); - for stdin", "左表 (流式); - 表示 stdin")
    ),
    right: str = typer.Argument(..., help=t("Right table (loaded into memory)", "右表 (入内存)")),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    on: Optional[str] = typer.Option(
        None,
        "--on",
        help=t("Key expression shared by both sides, e.g. x.id", "两侧共用的键表达式, 如 x.id"),
    ),
    left_on: Optional[str] = typer.Option(
        None, "--left-on", help=t("Left key expression", "左表键表达式")
    ),
    right_on: Optional[str] = typer.Option(
        None, "--right-on", help=t("Right key expression", "右表键表达式")
    ),
    inner: bool = typer.Option(
        False,
        "--inner",
        help=t(
            "Inner join: drop unmatched left rows (default: left join)",
            "内连接: 丢弃未命中的左行 (默认左连接)",
        ),
    ),
    prefix: Optional[str] = typer.Option(
        None, "--prefix", help=t("Prefix for all right-table fields", "右表字段统一加前缀")
    ),
    anti: bool = typer.Option(
        False,
        "--anti",
        help=t(
            "Anti join: keep only left rows with no match on the right (e.g. drop test-set overlap)",
            "反连接: 只保留右表无匹配的左行 (如去掉与测试集重合的样本)",
        ),
    ),
    strict: bool = typer.Option(False, "--strict", help=_STRICT_HELP),
):
    _join(left, right, output, on, left_on, right_on, inner, prefix, anti, strict)


# ============ 数据统计命令 ============


@app.command(
    help=t(
        "Show statistics for a data file\n\n"
        "Examples:\n"
        "    dt stats data.jsonl                       # quick mode: field structure\n"
        "    dt stats data.jsonl --schema              # nested schema (get the big picture before writing expressions)\n"
        "    dt stats data.jsonl --full                # full mode: value distributions / unique counts\n"
        "    dt stats data.jsonl --full --field=label  # stats for the label field only\n"
        "    dt stats data.jsonl --full --expand=tags  # expand a list field\n"
        "    dt --format=json stats data.jsonl         # machine-readable report",
        "显示数据文件的统计信息\n\n"
        "示例:\n"
        "    dt stats data.jsonl                       # 快速模式: 字段结构\n"
        "    dt stats data.jsonl --schema              # 嵌套 schema (先了解全貌再写表达式)\n"
        "    dt stats data.jsonl --full                # 完整模式: 值分布/唯一值\n"
        "    dt stats data.jsonl --full --field=label  # 仅统计 label 字段\n"
        "    dt stats data.jsonl --full --expand=tags  # 展开 list 字段\n"
        "    dt --format=json stats data.jsonl         # 机器可读报告",
    )
)
def stats(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    top: int = typer.Option(10, "--top", "-n", help=t("Show the top N values", "显示 Top N 值")),
    full: bool = typer.Option(
        False,
        "--full",
        "-f",
        help=t(
            "Full mode: value distributions, unique counts and other details",
            "完整模式：统计值分布、唯一值等详细信息",
        ),
    ),
    field: Optional[List[str]] = typer.Option(
        None,
        "--field",
        help=t(
            "Field to analyze (repeatable); nested paths supported",
            "指定统计字段（可多次使用），支持嵌套路径",
        ),
    ),
    expand: Optional[List[str]] = typer.Option(
        None,
        "--expand",
        help=t("Expand a list field for stats (repeatable)", "展开 list 字段统计（可多次使用）"),
    ),
    schema: bool = typer.Option(
        False,
        "--schema",
        "-s",
        help=t(
            "Infer nested structure (types / non-null rate / list elements / low-cardinality values); agents should start here",
            "推断嵌套结构 (类型/非空率/list 元素/低基数取值), agent 先看这个",
        ),
    ),
    sample: int = typer.Option(
        1000,
        "--sample",
        help=t("Rows scanned by --schema (0 = all)", "--schema 扫描前 N 行 (0=全量)"),
    ),
):
    _stats(filename, top, full, field, expand, schema=schema, sample=sample)


@app.command(
    "token-stats",
    help=t(
        "Token statistics for a dataset\n\n"
        "Examples:\n"
        "    dt token-stats data.jsonl --field=messages          # default cl100k_base\n"
        "    dt token-stats data.jsonl --field=text --model=qwen2.5\n"
        "    dt token-stats data.jsonl --detailed\n"
        "    dt --format=json token-stats data.jsonl             # JSON report",
        "统计数据集的 Token 信息\n\n"
        "示例:\n"
        "    dt token-stats data.jsonl --field=messages          # 默认 cl100k_base\n"
        "    dt token-stats data.jsonl --field=text --model=qwen2.5\n"
        "    dt token-stats data.jsonl --detailed\n"
        "    dt --format=json token-stats data.jsonl             # JSON 报告",
    ),
)
def token_stats(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    field: str = typer.Option("messages", "--field", "-f", help=t("Field to count", "统计字段")),
    model: str = typer.Option(
        "cl100k_base",
        "--model",
        "-m",
        help=t(
            "Tokenizer: cl100k_base (default), qwen2.5, llama3, gpt-4, etc.",
            "分词器: cl100k_base (默认), qwen2.5, llama3, gpt-4 等",
        ),
    ),
    detailed: bool = typer.Option(
        False, "--detailed", "-d", help=t("Show detailed stats", "显示详细统计")
    ),
    workers: Optional[int] = typer.Option(
        None,
        "--workers",
        "-w",
        help=t(
            "Worker processes (default: auto; 1 disables parallelism)",
            "并行进程数 (默认自动, 1 禁用并行)",
        ),
    ),
):
    _token_stats(filename, field, model, detailed, workers)


@app.command(
    help=t(
        "Numeric distribution of one or more expressions: n / null / min / max / mean / std / "
        "p25 p50 p75 p90 p99, plus a histogram in a terminal (dt view's S snapshot, for the CLI)\n\n"
        "Non-numeric, None and failing rows count as null. Non-TTY output is a JSON array.\n\n"
        "Examples:\n"
        '    dt describe chat.jsonl "turns(x)" "chars(x)"          # turns / characters per sample\n'
        '    dt describe data.jsonl "x.score" "len(x.messages[-1].content)"\n'
        '    dt filter d.jsonl "search(x, \'refund\')" | dt describe - "chars(x)"\n'
        '    dt --format=json describe data.jsonl "x.score" | jq ".[0].p99"',
        "一个或多个表达式的数值分布: n / null / min / max / mean / std / p25 p50 p75 p90 p99, "
        "终端里附直方图 (dt view 的 S 列快照的 CLI 版)\n\n"
        "非数值、None、求值失败的行计入 null。非 TTY 输出 JSON 数组。\n\n"
        "示例:\n"
        '    dt describe chat.jsonl "turns(x)" "chars(x)"          # 每条样本的轮数 / 字符数分布\n'
        '    dt describe data.jsonl "x.score" "len(x.messages[-1].content)"\n'
        '    dt filter d.jsonl "search(x, \'退款\')" | dt describe - "chars(x)"\n'
        '    dt --format=json describe data.jsonl "x.score" | jq ".[0].p99"',
    )
)
def describe(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    exprs: List[str] = typer.Argument(
        ...,
        metavar="EXPR...",
        help=t("Expressions (row is x), numeric", "表达式 (当前行 x), 取数值"),
    ),
    bins: int = typer.Option(10, "--bins", help=t("Histogram buckets", "直方图桶数")),
):
    _describe(filename, exprs, bins=bins)


@app.command(
    help=t(
        "Compare two datasets\n\n"
        "Examples:\n"
        "    dt diff v1.jsonl v2.jsonl                    # no key: compare by line number\n"
        "    dt diff v1.jsonl v2.jsonl --key=id           # align by the id field\n"
        "    dt diff v1.jsonl v2.jsonl --key=meta.uuid    # by a nested field\n"
        "    dt --format=json diff a.jsonl b.jsonl --key=id | jq .",
        "对比两个数据集的差异\n\n"
        "示例:\n"
        "    dt diff v1.jsonl v2.jsonl                    # 无 key, 按行号对比\n"
        "    dt diff v1.jsonl v2.jsonl --key=id           # 按 id 字段对齐\n"
        "    dt diff v1.jsonl v2.jsonl --key=meta.uuid    # 按嵌套字段\n"
        "    dt --format=json diff a.jsonl b.jsonl --key=id | jq .",
    )
)
def diff(
    file1: str = typer.Argument(..., help=t("First file (may be -)", "第一个文件 (可为 -)")),
    file2: str = typer.Argument(..., help=t("Second file (may be -)", "第二个文件 (可为 -)")),
    key: Optional[str] = typer.Option(
        None, "--key", "-k", help=t("Key field to match on", "匹配键字段")
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help=t("Report output path", "报告输出路径")
    ),
):
    _diff(file1, file2, key, output)


@app.command(
    help=t(
        "Show the lineage history of a data file\n\n"
        "Examples:\n"
        "    dt history processed.jsonl                   # TTY: table, non-TTY: JSON\n"
        "    dt --format=json history processed.jsonl     # force JSON",
        "显示数据文件的血缘历史\n\n"
        "示例:\n"
        "    dt history processed.jsonl                   # TTY: 表格, 非 TTY: JSON\n"
        "    dt --format=json history processed.jsonl     # 强制 JSON",
    )
)
def history(
    filename: str = typer.Argument(..., help=t("Data file path", "数据文件路径")),
    json: bool = typer.Option(
        False,
        "--json",
        "-j",
        help=t(
            "Output JSON (deprecated; use --format=json)",
            "JSON 格式输出 (已废弃, 建议用 --format=json)",
        ),
    ),
):
    _history(filename, json)


# ============ 切分与导出命令 ============


@app.command(
    help=t(
        "Split a dataset into train/test (or train/val/test)\n\n"
        "Examples:\n"
        "    dt split data.jsonl --ratio=0.8\n"
        "    dt split data.jsonl --ratio=0.7,0.15,0.15 --seed=42\n"
        "    dt split data.jsonl --ratio=0.8 --dry-run\n"
        '    dt sample data.jsonl -w "x.ok" | dt split - -o out/ --name clean',
        "分割数据集为 train/test (或 train/val/test)\n\n"
        "示例:\n"
        "    dt split data.jsonl --ratio=0.8\n"
        "    dt split data.jsonl --ratio=0.7,0.15,0.15 --seed=42\n"
        "    dt split data.jsonl --ratio=0.8 --dry-run\n"
        '    dt sample data.jsonl -w "x.ok" | dt split - -o out/ --name clean',
    )
)
def split(
    filename: str = typer.Argument(
        ...,
        help=t(
            "Input file path; - for stdin (requires -o and --name)",
            "输入文件路径; - 表示 stdin (需 -o 与 --name)",
        ),
    ),
    ratio: str = typer.Option(
        "0.8",
        "--ratio",
        "-r",
        help=t("Split ratio, e.g. 0.8 or 0.7,0.15,0.15", "分割比例，如 0.8 或 0.7,0.15,0.15"),
    ),
    seed: Optional[int] = typer.Option(None, "--seed", help=t("Random seed", "随机种子")),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help=t("Output directory (default: same as input)", "输出目录（默认同目录）"),
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        help=t(
            "Output file name prefix (default: input file name); produces <name>_train.jsonl etc.",
            "输出文件名前缀 (默认取输入文件名), 生成 <name>_train.jsonl 等",
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=t(
            "Dry run: compute split sizes without writing (exit code 10)",
            "预演: 计算各切分行数但不写出 (退出码 10)",
        ),
    ),
):
    _split(filename, ratio, seed, output, dry_run=dry_run, name=name)


@app.command(
    help=t(
        "Export data for training frameworks (LLaMA-Factory, ms-swift, Axolotl)\n\n"
        "Examples:\n"
        "    dt export data.jsonl --framework=llama-factory\n"
        "    dt export data.jsonl --framework=swift -o dataset/\n"
        "    dt export data.jsonl --framework=axolotl --dry-run",
        "导出数据到训练框架 (LLaMA-Factory, ms-swift, Axolotl)\n\n"
        "示例:\n"
        "    dt export data.jsonl --framework=llama-factory\n"
        "    dt export data.jsonl --framework=swift -o dataset/\n"
        "    dt export data.jsonl --framework=axolotl --dry-run",
    )
)
def export(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    framework: Framework = typer.Option(
        ...,
        "--framework",
        "-f",
        help=t(
            "Target framework: llama-factory|swift|axolotl", "目标框架: llama-factory|swift|axolotl"
        ),
        case_sensitive=False,
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help=t("Output directory", "输出目录")
    ),
    name: Optional[str] = typer.Option(None, "--name", "-n", help=t("Dataset name", "数据集名称")),
    check: bool = typer.Option(
        False,
        "--check",
        help=t(
            "Only check compatibility, don't export (same as --dry-run)",
            "仅检查兼容性，不导出 (等价 --dry-run)",
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=t("Dry run: same as --check (exit code 10)", "预演: 同 --check (退出码 10)"),
    ),
):
    framework_value = framework.value if isinstance(framework, Framework) else framework
    _export(filename, framework_value, output, name, check, dry_run=dry_run)


# ============ 评估命令 ============


@app.command(
    help=t(
        "Parse model outputs and compute metrics\n\n"
        "Two-stage parsing: automatic cleanup (strip think tags, extract code blocks) + piped extraction.\n\n"
        "Examples:\n"
        "    dt eval result.jsonl --label-col=label\n"
        '    dt eval result.jsonl --extract="tag:label" --mapping="yes:1,no:0"\n'
        "    dt eval result.jsonl --source=input.jsonl --response-col=api_output.content\n"
        '    dt eval result.jsonl --extract="json_key:result | index:0" --sep=","\n'
        '    dt eval result.jsonl --extract="lines | index:1" --sep="|"\n'
        "    dt eval result.jsonl --label-col=label --dry-run",
        "对模型输出进行解析和指标评估\n\n"
        "两阶段解析：自动清洗（去 think 标签、提取代码块）+ 管道式提取。\n\n"
        "示例:\n"
        "    dt eval result.jsonl --label-col=label\n"
        '    dt eval result.jsonl --extract="tag:标签" --mapping="是:1,否:0"\n'
        "    dt eval result.jsonl --source=input.jsonl --response-col=api_output.content\n"
        '    dt eval result.jsonl --extract="json_key:result | index:0" --sep=","\n'
        '    dt eval result.jsonl --extract="lines | index:1" --sep="|"\n'
        "    dt eval result.jsonl --label-col=label --dry-run",
    )
)
def eval(
    result_file: str = typer.Argument(
        ...,
        help=t(
            "Path to the model output .jsonl file; - for stdin",
            "模型输出的 .jsonl 文件路径; - 表示 stdin",
        ),
    ),
    source: Optional[str] = typer.Option(
        None,
        "--source",
        "-s",
        help=t("Original input file, merged by line number", "原始输入文件，按行号对齐合并"),
    ),
    response_col: str = typer.Option(
        "content", "--response-col", "-r", help=t("Model response field name", "模型响应字段名")
    ),
    label_col: Optional[str] = typer.Option(
        None,
        "--label-col",
        "-l",
        help=t("Label field name (auto-detected if omitted)", "标签字段名（不指定时自动检测）"),
    ),
    extract: str = typer.Option(
        "direct",
        "--extract",
        "-e",
        help=t(
            "Piped extraction rules; operators: direct/tag:X/json_key:X/index:N/line:N/lines/regex:X",
            "管道式提取规则，算子: direct/tag:X/json_key:X/index:N/line:N/lines/regex:X",
        ),
    ),
    sep: Optional[str] = typer.Option(
        None, "--sep", help=t("Separator used by the index operator", "配合 index 算子使用的分隔符")
    ),
    mapping: Optional[str] = typer.Option(
        None, "--mapping", "-m", help=t("Value mapping (k1:v1,k2:v2)", "值映射 (k1:v1,k2:v2)")
    ),
    output_dir: str = typer.Option(
        "record",
        "--output-dir",
        "-o",
        help=t("Output directory for the metrics report", "指标报告输出目录"),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=t(
            "Dry run: preview parsing without generating the metrics report (exit code 10)",
            "预演: 解析预览但不生成 metrics 报告 (退出码 10)",
        ),
    ),
):
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


@app.command(
    help=t(
        "Validate data against a preset schema\n\n"
        "Available presets: openai_chat, alpaca, dpo, sharegpt\n\n"
        "Examples:\n"
        "    dt validate data.jsonl --preset=openai_chat\n"
        "    dt validate data.jsonl --preset=alpaca -o valid.jsonl\n"
        "    dt validate data.jsonl --preset=openai_chat --filter   # filter out invalid rows\n"
        "    dt --format=json validate data.jsonl --preset=openai_chat  # JSON report\n\n"
        "Exit codes: 0 all valid (or valid rows written with --filter/-o), 1 invalid rows found, 2 bad arguments (unknown preset), 3 file not found",
        "使用预设 Schema 验证数据格式\n\n"
        "可用预设: openai_chat, alpaca, dpo, sharegpt\n\n"
        "示例:\n"
        "    dt validate data.jsonl --preset=openai_chat\n"
        "    dt validate data.jsonl --preset=alpaca -o valid.jsonl\n"
        "    dt validate data.jsonl --preset=openai_chat --filter   # 过滤无效\n"
        "    dt --format=json validate data.jsonl --preset=openai_chat  # JSON 报告\n\n"
        "退出码: 0 全部有效 (或 --filter/-o 已写出有效数据), 1 存在无效记录, 2 参数错误 (未知预设), 3 文件不存在",
    )
)
def validate(
    filename: str = typer.Argument(
        ..., help=t("Input file path; - for stdin", "输入文件路径; - 表示 stdin")
    ),
    preset: Optional[ValidatePreset] = typer.Option(
        None,
        "--preset",
        "-p",
        help=t(
            "Preset schema: openai_chat|alpaca|dpo|sharegpt",
            "预设 Schema: openai_chat|alpaca|dpo|sharegpt",
        ),
        case_sensitive=False,
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help=t("File path to write valid records to", "输出有效数据的文件路径"),
    ),
    filter: bool = typer.Option(
        False,
        "--filter",
        "-f",
        help=t(
            "Output only valid records (stdout without -o; the report goes to stderr)",
            "只输出有效数据 (无 -o 则写 stdout, 报告转 stderr)",
        ),
    ),
    max_errors: int = typer.Option(
        20, "--max-errors", help=t("Maximum number of errors to show", "最多显示的错误数量")
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help=t("Show details", "显示详细信息")),
    workers: Optional[int] = typer.Option(
        None,
        "--workers",
        "-w",
        help=t(
            "Worker processes (default: auto; 1 disables parallelism)",
            "并行进程数 (默认自动, 1 禁用并行)",
        ),
    ),
):
    preset_value = preset.value if isinstance(preset, ValidatePreset) else preset
    _validate(filename, preset_value, output, filter, max_errors, verbose, workers)


# ============ 工具命令 ============


@app.command(
    help=t(
        "How to use the log viewer",
        "日志查看工具使用说明",
    )
)
def logs():
    from .cli.output import log

    help_text = t(
        """
Log viewer (tl)

dtflow bundles the toolong log viewer; once installed, use the tl command:

Usage:
    tl app.log              view a log file (interactive TUI)
    tl app.log error.log    view several logs at once
    tl --tail app.log       follow mode (like tail -f)
    tl *.log                match multiple files with a glob

Keys:
    /     search
    n/N   next/previous match
    g/G   jump to start/end
    f     filter
    q     quit

Install:
    pip install dtflow[logs]   # log viewer only
    pip install dtflow[full]   # all optional dependencies
""",
        """
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
""",
    )
    log(help_text)


# ============ 界面语言 ============


@app.command(
    "lang",
    help=t(
        "Show or set the interface language (en | zh).\n\n"
        "Applies to all dt output: help, messages, errors and dt view.\n"
        "Saved to ~/.config/dtflow/config.json; the DT_LANG env var overrides it.\n\n"
        "Examples:\n"
        "    dt lang          # print the current language\n"
        "    dt lang zh       # switch to Chinese\n"
        "    dt lang en       # switch to English",
        "查看或设置界面语言 (en | zh)。\n\n"
        "作用于 dt 的全部输出: 帮助、提示、报错和 dt view。\n"
        "保存在 ~/.config/dtflow/config.json; 环境变量 DT_LANG 优先于它。\n\n"
        "示例:\n"
        "    dt lang          # 输出当前语言\n"
        "    dt lang zh       # 切换为中文\n"
        "    dt lang en       # 切换为英文",
    ),
)
def lang_cmd(
    value: Optional[str] = typer.Argument(
        None, help=t("Language to set: en | zh", "要设置的语言: en | zh"), metavar="LANG"
    ),
):
    from .cli.output import die_io_error, die_usage, log
    from .i18n import CONFIG_PATH, save_lang

    if value is None:
        typer.echo(LANG)
        return
    if value not in LANGS:
        die_usage(
            t(f"Unsupported language: {value}", f"不支持的语言: {value}"),
            suggestion=t("Choices: en | zh", "可选值: en | zh"),
        )
    try:
        save_lang(value)
    except OSError as e:
        die_io_error(e, operation=t("Save", "保存"), path=str(CONFIG_PATH))
    # 用新语言回显, 用户立即看到效果
    log("Language set to English" if value == "en" else "界面语言已设置为中文", style="green")
    env = os.environ.get("DT_LANG")
    if env in LANGS and env != value:
        log(
            t(
                f"Note: DT_LANG={env} is set in this shell and takes precedence",
                f"注意: 当前 shell 设置了 DT_LANG={env}, 它的优先级更高",
            ),
            style="yellow",
        )


# ============ Skill 命令 ============


@app.command(
    "schema",
    help=t(
        "Output the command tree and parameter definitions (JSON) for agent introspection.\n\n"
        "Examples:\n"
        "    dt schema                    # full command tree\n"
        "    dt schema clean              # parameter definitions of the clean command\n"
        "    dt schema | jq '.commands[].name'",
        "输出命令树与参数定义 (JSON), 供 agent 内省使用.\n\n"
        "示例:\n"
        "    dt schema                    # 输出完整命令树\n"
        "    dt schema clean              # 输出 clean 命令的参数定义\n"
        "    dt schema | jq '.commands[].name'",
    ),
)
def schema_cmd(
    command: Optional[str] = typer.Argument(
        None,
        help=t(
            "If given, output only this command's schema; otherwise the full schema of all commands",
            "若指定则只输出该命令的 schema；否则输出所有命令的完整 schema",
        ),
    ),
):
    from .cli.schema import schema as _schema

    _schema(command, app=app)


@app.command(
    "install-skill",
    help=t(
        "Install the dtflow skill into Claude Code or Codex.",
        "安装 dtflow skill 到 Claude Code 或 Codex。",
    ),
)
def install_skill(
    target: SkillTarget = typer.Option(
        SkillTarget.claude, "--target", help=t("Agent to install for", "安装目标 agent")
    ),
):
    _install_skill(target.value)


@app.command(
    "uninstall-skill",
    help=t(
        "Uninstall the dtflow skill from Claude Code or Codex.",
        "从 Claude Code 或 Codex 卸载 dtflow skill。",
    ),
)
def uninstall_skill(
    target: SkillTarget = typer.Option(
        SkillTarget.claude, "--target", help=t("Agent to uninstall from", "卸载目标 agent")
    ),
):
    _uninstall_skill(target.value)


@app.command(
    "skill-status",
    help=t(
        "Show the skill installation status in Claude Code or Codex.",
        "查看 Claude Code 或 Codex 的 skill 安装状态。",
    ),
)
def skill_status(
    target: SkillTarget = typer.Option(
        SkillTarget.claude, "--target", help=t("Agent to check", "查询目标 agent")
    ),
):
    _skill_status(target.value)


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
    console.print(
        t(
            "[dim]💡 Tip: run [green]dt --install-completion[/green] to enable shell completion[/dim]",
            "[dim]💡 提示: 运行 [green]dt --install-completion[/green] 启用命令补全[/dim]",
        )
    )

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
