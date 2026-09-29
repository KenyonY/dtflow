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

from .cli.commands import clean as _clean
from .cli.commands import concat as _concat
from .cli.commands import dedupe as _dedupe
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
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
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
    by: Optional[str] = typer.Option(
        None, "--by", help="分层采样字段 (字段路径, 如 meta.source; 不是表达式)"
    ),
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
        help="筛选表达式 (Python, 当前行为 x, 如 \"x.score>0.5 and 'a' in x.text\"), 可多次 (与关系)",
    ),
):
    """从数据文件中采样指定数量的数据

    示例:
        dt sample data.jsonl --num=10                     # 随机 10 条
        dt sample data.jsonl 100 --by=category            # 按字段分层 100 条
        dt sample data.jsonl --where="len(x.messages)>=2"      # 筛选后采样
        dt sample data.jsonl -w "'alpaca' in x.meta.source"   # 包含子串
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
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
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
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
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


@app.command(context_settings={"ignore_unknown_options": True})
def view(
    filename: str = typer.Argument(..., help="输入文件路径；- 表示从 stdin 读（管道模式）"),
    num_arg: Optional[int] = typer.Argument(
        None,
        metavar="NUM",
        help="窗口行数；正数从开头、负数从末尾打开，仍可 ]/[ 翻窗口",
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
        "-w",
        help="启动即筛选 (Python 表达式, 当前行为 x, 派生列名 turns/chars 等可直接用), 可多次 (与关系)",
    ),
    search: Optional[str] = typer.Option(
        None, "--search", "-s", help="启动即全字段搜索（不分大小写；re: 前缀走正则），命中处高亮"
    ),
    sort: Optional[str] = typer.Option(
        None, "--sort", "-S", help="启动即全量排序，列名前加 - 为降序（如 -chars）"
    ),
    follow: bool = typer.Option(
        False,
        "--follow",
        "-f",
        help="实时追踪 JSONL/NDJSON 追加与日志轮转，从最新尾窗开始",
    ),
):
    """交互式浏览数据（表格 + 详情联动，Textual TUI）

    表格扫视 + 详情按格式渲染（对话气泡/dpo对比/alpaca分段），无需逐层展开。
    大文件靠偏移索引窗口化浏览：只 parse 当前窗口，TUI 内按 ] / [ 翻窗口、: 跳行。
    NUM 为负数时快速从文件尾部打开；--follow 在 JSONL/NDJSON 追加或轮转时持续追尾。
    筛选/搜索/排序都是全量的（扫整个文件），可叠加，按 r 一键清空回到全量浏览；
    TUI 内按 w 把结果导出成文件，按 C 复制"复现当前视图"的命令。
    JSONL 的全量扫描按字节区间分片并行（环境变量 DTFLOW_VIEW_WORKERS 可调并行度，
    设为 1 强制串行）。管道模式 dt view - 从 stdin 读 NDJSON 全量入内存。
    需要交互式终端（TTY）。按 ? 查看快捷键。

    示例:
        dt view data.jsonl                       # 打开浏览器（顺序从第 1 行）
        dt view data.jsonl 100                   # 从开头浏览，窗口 100 行
        dt view data.jsonl -100                  # 快速从倒数 100 行开始
        dt view app.jsonl -100 -f                # 追踪最新 100 行 (-f=--follow)
        dt view data.jsonl --format=dpo          # 强制按 dpo 渲染
        dt view big.jsonl --offset=20000         # 从第 2 万行开始（默认每窗口 1 万行）
        dt view big.jsonl --cap=50000            # 每窗口加载 5 万行
        dt view data.jsonl -S -chars             # 按长度降序 (-S=--sort)
        dt view data.jsonl -w "turns>=6" -w "source==alpaca"   # 多条为与关系
        dt view data.jsonl -s 报错               # 全量搜索并高亮 (-s=--search)
        dt sample data.jsonl 500 | dt view -     # 管道: 看采样/筛选等处理后结果
    """
    from pathlib import Path

    from .cli.output import die_usage

    actual_cap = abs(num_arg) if num_arg is not None else cap
    tail = bool(num_arg is not None and num_arg < 0)
    if actual_cap <= 0:
        die_usage("dt view 的窗口大小必须大于 0", suggestion="例如: dt view data.jsonl 100")
    if tail and offset:
        die_usage("-NUM 不能与 --offset 同时使用", suggestion="删除 --offset")
    if follow and offset:
        die_usage("--follow 不能与 --offset 同时使用", suggestion="追尾模式固定从最新处开始")
    if follow and sort:
        die_usage(
            "--follow 不能与启动排序 --sort 同时使用",
            suggestion="先进入 follow，需要时再按 s 对固定高水位排序",
        )
    if follow and filename == "-":
        die_usage("--follow 不支持 stdin", suggestion="请直接传入 JSONL/NDJSON 文件路径")
    if follow and Path(filename).suffix.lower() not in (".jsonl", ".ndjson"):
        die_usage(
            "--follow 仅支持 JSONL/NDJSON 文件",
            suggestion="纯文本日志可使用 tl --tail FILE",
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
    )


@app.command("slice")
def slice_cmd(
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
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
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
    num: Optional[int] = typer.Argument(None, help="只转换前 N 条数据"),
    preset: Optional[TransformPreset] = typer.Option(
        None,
        "--preset",
        "-p",
        help="目标格式: openai_chat|alpaca|sharegpt|dpo_pair|simple_qa; 自动识别输入 (messages/sharegpt/alpaca/dpo/q-a, dpo_pair 除外), 工具调用互转, 认不出的行跳过并汇总",
        case_sensitive=False,
    ),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="配置文件路径"),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="输出文件路径 (不指定则写 stdout; 配置模式取配置里的 output)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="预演: 计算结果但不写出 (退出码 10)"),
):
    """转换数据格式

    示例:
        dt transform data.jsonl --preset=openai_chat -o out.jsonl
        dt transform data.jsonl --config=./config.py -o out.jsonl
        dt transform data.jsonl --preset=alpaca --dry-run
        dt sample data.jsonl -w "x.ok" | dt transform - --preset=openai_chat | dt head -
    """
    preset_value = preset.value if isinstance(preset, TransformPreset) else preset
    _transform(filename, num, preset_value, config, output, dry_run=dry_run)


@app.command()
def run(
    config: str = typer.Argument(..., help="Pipeline YAML 配置文件"),
    input: Optional[str] = typer.Option(
        None, "--input", "-i", help="输入文件路径 (覆盖配置; - 为 stdin)"
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径 (覆盖配置; 都没有则写 stdout; split 结尾按它派生 _train/_test)",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="预演: 验证配置并打印步骤链 (退出码 10)"),
):
    """执行 Pipeline 配置文件 (step 的 type 即 CLI 命令名, 参数即选项名)

    示例:
        dt run pipeline.yaml
        dt run pipeline.yaml --input=data.jsonl --output=result.jsonl
        cat data.jsonl | dt run pipeline.yaml -i - | dt head -
        dt run pipeline.yaml --dry-run
    """
    _run(config, input, output, dry_run=dry_run)


# ============ 数据处理命令 ============


@app.command()
def dedupe(
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="去重依据字段"),
    similar: Optional[float] = typer.Option(None, "--similar", "-s", help="相似度阈值 (0-1)"),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="输出文件路径 (不指定则写 stdout)"
    ),
    in_place: bool = typer.Option(False, "--in-place", "-i", help="原地写回输入文件"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预演: 计算结果但不写出 (退出码 10)"),
):
    """数据去重 (精确去重流式, O(唯一键) 内存)

    示例:
        dt dedupe data.jsonl --key=text -i               # 精确去重, 原地写回
        dt dedupe data.jsonl --key=messages[0].content -o out.jsonl   # 按嵌套字段去重
        dt dedupe data.jsonl --key=text --similar=0.9    # 模糊去重（相似度 >= 0.9）→ stdout
        dt dedupe data.jsonl --key=text --dry-run        # 预演
    """
    _dedupe(filename, key, similar, output, in_place=in_place, dry_run=dry_run)


@app.command()
def concat(
    files: List[str] = typer.Argument(..., help="输入文件列表 (至少两个; 至多一个 - 表示 stdin)"),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="输出文件路径 (不指定则写 stdout)"
    ),
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
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
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
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="输出文件路径 (不指定则写 stdout)"
    ),
    in_place: bool = typer.Option(False, "--in-place", "-i", help="原地写回输入文件"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预演: 计算结果但不写出 (退出码 10)"),
):
    """数据清洗 (流式; 无 -o 写 stdout, -i 原地写回)

    示例:
        dt clean data.jsonl --drop-empty=text -o out.jsonl
        dt clean data.jsonl --min-len=messages.#:2 -i    # 至少 2 条消息, 原地写回
        dt clean data.jsonl --rename=old:new --drop=debug | dt head -
        dt clean data.jsonl --promote=meta.label --strip -i  # 提升嵌套字段 + 去空白
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
        in_place=in_place,
        dry_run=dry_run,
    )


# ============ 数据原语命令 (可管道拼接; 表达式即 Python, 当前行为 x) ============

_OUT_HELP = "输出文件路径 (不指定则写 stdout)"
_STRICT_HELP = "表达式求值失败即报错退出 (默认: filter 跳过该行 / select 该项置 null / map 该行原样保留 / sort 排末尾, 结束时汇总)"


@app.command("filter")
def filter_cmd(
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
    expr: str = typer.Argument(..., help="Python 表达式, 当前行为 x"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    strict: bool = typer.Option(False, "--strict", help=_STRICT_HELP),
):
    """保留表达式为真的行

    示例:
        dt filter data.jsonl "x.score > 0.5 and 'wiki' in x.meta.source"
        dt filter data.jsonl "len(x.messages) >= 2 and x.messages[-1].role == 'assistant'"
        dt filter data.jsonl "any('退款' in m.content for m in x.messages)" -o hit.jsonl
        dt filter data.jsonl "re.search(r'\\d{4}', x.text)" | dt head -
    """
    _filter(filename, expr, output, strict)


@app.command("select")
def select_cmd(
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
    spec: str = typer.Argument(
        ..., metavar="FIELDS", help="字段列表: 字面字段名 或 新名=表达式, 逗号分隔"
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    strict: bool = typer.Option(False, "--strict", help=_STRICT_HELP),
):
    """投影 / 重命名 / 派生字段 (输出键序 = SPEC 序)

    示例:
        dt select data.jsonl "id,text"                              # 只留两列
        dt select data.jsonl "id,n=len(x.messages),last=x.messages[-1].content"
        dt select data.jsonl "prompt=x.instruction,answer=x.output" # 重命名
    """
    _select(filename, spec, output, strict)


@app.command("map")
def map_cmd(
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
    code: str = typer.Argument(..., help="Python 语句, 原地修改 x (; 或换行分隔多句)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    strict: bool = typer.Option(False, "--strict", help=_STRICT_HELP),
):
    """对每行执行 Python 语句 (原地修改 x)

    示例:
        dt map data.jsonl "x.text = x.text.strip()"
        dt map data.jsonl "x.n = len(x.messages); del x.debug"
        dt map data.jsonl "x.messages.append({'role': 'assistant', 'content': x.answer})"
    """
    _map(filename, code, output, strict)


@app.command("explode")
def explode_cmd(
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
    field: str = typer.Option(..., "--field", "-f", help="要展开的 list 字段 (顶层)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    as_name: Optional[str] = typer.Option(None, "--as", help="展开后元素的字段名 (默认同名)"),
    index_as: Optional[str] = typer.Option(None, "--index-as", help="把元素下标写入该字段"),
):
    """把 list 字段展开为多行 (其余字段复制)

    示例:
        dt explode data.jsonl --field messages                 # 每条消息一行
        dt explode data.jsonl --field tags --as tag --index-as i
    """
    _explode(filename, field, output, as_name, index_as)


@app.command("sort")
def sort_cmd(
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
    by: str = typer.Option(..., "--by", "-b", help="排序键表达式, 如 x.score 或 (x.a, -x.b)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    desc: bool = typer.Option(False, "--desc", help="降序"),
    strict: bool = typer.Option(False, "--strict", help=_STRICT_HELP),
):
    """按表达式排序 (全量加载; 键求值失败的行排最后)

    示例:
        dt sort data.jsonl --by x.score --desc
        dt sort data.jsonl --by "len(x.messages)"
        dt sort data.jsonl --by "(x.source, -x.score)"
    """
    _sort(filename, by, output, desc, strict)


@app.command("shuffle")
def shuffle_cmd(
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    seed: Optional[int] = typer.Option(None, "--seed", help="随机种子"),
):
    """全量打乱

    示例:
        dt shuffle data.jsonl --seed 42 -o shuffled.jsonl
    """
    _shuffle(filename, output, seed)


@app.command("group")
def group_cmd(
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
    by: str = typer.Option(..., "--by", "-b", help="分组键表达式"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    agg: Optional[str] = typer.Option(
        None, "--agg", help="聚合: name=表达式,... 可用 g(组内行) / key / n / mean / median"
    ),
    strict: bool = typer.Option(False, "--strict", help=_STRICT_HELP),
):
    """按表达式分组: 默认流式计数, --agg 自定义聚合

    示例:
        dt group data.jsonl --by x.meta.source                 # {"key","count"} 按 count 降序
        dt group data.jsonl --by "len(x.messages)"
        dt group data.jsonl --by x.label --agg "avg=mean(len(r.text) for r in g)"
    """
    _group(filename, by, output, agg, strict)


@app.command("join")
def join_cmd(
    left: str = typer.Argument(..., help="左表 (流式); - 表示 stdin"),
    right: str = typer.Argument(..., help="右表 (入内存)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUT_HELP),
    on: Optional[str] = typer.Option(None, "--on", help="两侧共用的键表达式, 如 x.id"),
    left_on: Optional[str] = typer.Option(None, "--left-on", help="左表键表达式"),
    right_on: Optional[str] = typer.Option(None, "--right-on", help="右表键表达式"),
    inner: bool = typer.Option(False, "--inner", help="内连接: 丢弃未命中的左行 (默认左连接)"),
    prefix: Optional[str] = typer.Option(None, "--prefix", help="右表字段统一加前缀"),
):
    """按键连接两个数据集 (左表流式, 右表入内存; 左表字段优先)

    示例:
        dt join data.jsonl meta.jsonl --on x.id
        dt join data.jsonl meta.jsonl --left-on x.uid --right-on x.user_id --prefix m_
        dt join data.jsonl labels.jsonl --on x.id --inner -o labeled.jsonl
    """
    _join(left, right, output, on, left_on, right_on, inner, prefix)


# ============ 数据统计命令 ============


@app.command()
def stats(
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
    top: int = typer.Option(10, "--top", "-n", help="显示 Top N 值"),
    full: bool = typer.Option(False, "--full", "-f", help="完整模式：统计值分布、唯一值等详细信息"),
    field: Optional[List[str]] = typer.Option(
        None, "--field", help="指定统计字段（可多次使用），支持嵌套路径"
    ),
    expand: Optional[List[str]] = typer.Option(
        None, "--expand", help="展开 list 字段统计（可多次使用）"
    ),
    schema: bool = typer.Option(
        False,
        "--schema",
        "-s",
        help="推断嵌套结构 (类型/非空率/list 元素/低基数取值), agent 先看这个",
    ),
    sample: int = typer.Option(1000, "--sample", help="--schema 扫描前 N 行 (0=全量)"),
):
    """显示数据文件的统计信息

    示例:
        dt stats data.jsonl                       # 快速模式: 字段结构
        dt stats data.jsonl --schema              # 嵌套 schema (先了解全貌再写表达式)
        dt stats data.jsonl --full                # 完整模式: 值分布/唯一值
        dt stats data.jsonl --full --field=label  # 仅统计 label 字段
        dt stats data.jsonl --full --expand=tags  # 展开 list 字段
        dt --format=json stats data.jsonl         # 机器可读报告
    """
    _stats(filename, top, full, field, expand, schema=schema, sample=sample)


@app.command("token-stats")
def token_stats(
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
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
    file1: str = typer.Argument(..., help="第一个文件 (可为 -)"),
    file2: str = typer.Argument(..., help="第二个文件 (可为 -)"),
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
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin (需 -o 与 --name)"),
    ratio: str = typer.Option("0.8", "--ratio", "-r", help="分割比例，如 0.8 或 0.7,0.15,0.15"),
    seed: Optional[int] = typer.Option(None, "--seed", help="随机种子"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出目录（默认同目录）"),
    name: Optional[str] = typer.Option(
        None, "--name", help="输出文件名前缀 (默认取输入文件名), 生成 <name>_train.jsonl 等"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="预演: 计算各切分行数但不写出 (退出码 10)"
    ),
):
    """分割数据集为 train/test (或 train/val/test)

    示例:
        dt split data.jsonl --ratio=0.8
        dt split data.jsonl --ratio=0.7,0.15,0.15 --seed=42
        dt split data.jsonl --ratio=0.8 --dry-run
        dt sample data.jsonl -w "x.ok" | dt split - -o out/ --name clean
    """
    _split(filename, ratio, seed, output, dry_run=dry_run, name=name)


@app.command()
def export(
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
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
    result_file: str = typer.Argument(..., help="模型输出的 .jsonl 文件路径; - 表示 stdin"),
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
    filename: str = typer.Argument(..., help="输入文件路径; - 表示 stdin"),
    preset: Optional[ValidatePreset] = typer.Option(
        None,
        "--preset",
        "-p",
        help="预设 Schema: openai_chat|alpaca|dpo|sharegpt",
        case_sensitive=False,
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出有效数据的文件路径"),
    filter: bool = typer.Option(
        False, "--filter", "-f", help="只输出有效数据 (无 -o 则写 stdout, 报告转 stderr)"
    ),
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
def install_skill(
    target: SkillTarget = typer.Option(SkillTarget.claude, "--target", help="安装目标 agent"),
):
    """安装 dtflow skill 到 Claude Code 或 Codex。"""
    _install_skill(target.value)


@app.command("uninstall-skill")
def uninstall_skill(
    target: SkillTarget = typer.Option(SkillTarget.claude, "--target", help="卸载目标 agent"),
):
    """从 Claude Code 或 Codex 卸载 dtflow skill。"""
    _uninstall_skill(target.value)


@app.command("skill-status")
def skill_status(
    target: SkillTarget = typer.Option(SkillTarget.claude, "--target", help="查询目标 agent"),
):
    """查看 Claude Code 或 Codex 的 skill 安装状态。"""
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
