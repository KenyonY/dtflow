"""
dt describe: 对每个表达式的数值分布做摘要 (n / null / min / max / mean / std / 分位数 + 直方图)。

这是 dt view 里 ``S`` 列快照的 CLI 版本, 也是 stats --full 做不到的"任意表达式"分布:
``dt describe chat.jsonl "turns(x)" "chars(x)" "x.score"``。单遍扫描, 每个表达式一个数组。
"""

from __future__ import annotations

from array import array
from math import isnan
from typing import Any, Dict, List, Optional

from rich.markup import escape

from ..expr import ExprSyntaxError, compile_value
from ..i18n import t
from ..utils.stats import histogram, render_histogram_lines, summarize
from .output import (
    die,
    die_usage,
    emit_data,
    get_state,
    is_stdout_tty,
    log,
    log_panel,
    log_table,
)
from .pipe import input_label, open_input


def describe(
    filename: str,
    exprs: List[str],
    format: Optional[str] = None,
    bins: int = 10,
) -> None:
    """
    对表达式的数值分布做摘要。非数值 / None / 求值失败计入 null, 不中断。

    Examples:
        dt describe chat.jsonl "turns(x)" "chars(x)"           # 轮数 / 字符数分布
        dt describe data.jsonl "x.score" "len(x.messages[-1].content)"
        dt --format=json describe data.jsonl "x.score" | jq '.[0].p99'
    """
    if bins < 1:
        die_usage(t("--bins must be at least 1", "--bins 至少为 1"))
    fns = []
    for e in exprs:
        try:
            fns.append(compile_value(e))
        except ExprSyntaxError as err:
            die_usage(str(err), suggestion=err.caret())
    values = [array("d") for _ in exprs]
    nulls = [0] * len(exprs)
    total = 0
    for row in open_input(filename):
        total += 1
        for j, fn in enumerate(fns):
            try:
                v = fn(row)
            except Exception:
                nulls[j] += 1
                continue
            if isinstance(v, bool):
                v = int(v)
            if isinstance(v, (int, float)) and not (isinstance(v, float) and isnan(v)):
                values[j].append(float(v))
            else:
                nulls[j] += 1
    if total == 0:
        die("empty_file", t("No data to describe", "没有数据可统计"), exit_code=1)

    results: List[Dict[str, Any]] = [
        {"expr": e, "null": nulls[j], **summarize(values[j])} for j, e in enumerate(exprs)
    ]
    # 显式 --format 照办 (csv/ndjson 也行); 未指定时 TTY 画表, 非 TTY 输出 JSON 数组 (报告类约定)
    fmt = format or get_state().fmt or ("table" if is_stdout_tty() else "json")
    if fmt != "table":
        emit_data(results, format=fmt)
        return
    _render(input_label(filename), total, results, values, bins)


_STATS = ("n", "null", "min", "p25", "p50", "mean", "p75", "p90", "p99", "max", "std")


def _fmt(v: Optional[float]) -> str:
    if v is None:
        return "-"
    return f"{int(v)}" if float(v).is_integer() else f"{v:.4g}"


def _render(label: str, total: int, results: List[Dict[str, Any]], values, bins: int) -> None:
    from rich.table import Table
    from rich.text import Text

    log_panel(
        t(
            f"[bold]File:[/bold] {label}\n[bold]Rows:[/bold] {total:,}",
            f"[bold]文件:[/bold] {label}\n[bold]总数:[/bold] {total:,} 条",
        ),
        title=t("📐 describe", "📐 分布摘要"),
    )
    # 统计量作行、表达式作列 (pandas describe 的形态): 列数只随表达式数增长, 80 列终端也放得下
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("", style="cyan", no_wrap=True)
    for r in results:
        table.add_column(Text(r["expr"]), justify="right", overflow="fold")
    for k in _STATS:
        table.add_row(k, *(_fmt(r[k]) for r in results))
    log_table(table)
    for r, vals in zip(results, values, strict=True):
        lines = render_histogram_lines(histogram(vals, bins))
        if lines:
            log(f"[bold]{escape(r['expr'])}[/bold]")
            for ln in lines:
                log("  " + escape(ln))
