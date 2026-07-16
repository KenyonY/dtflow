"""
CLI Schema 验证命令
"""

from pathlib import Path
from typing import Optional

from rich.markup import escape

from ..schema import alpaca_schema, dpo_schema, openai_chat_schema, sharegpt_schema
from ..storage.io import load_data, save_data
from .common import _check_file_format, _require_file_exists
from .output import (
    die,
    die_io_error,
    die_usage,
    emit_json,
    is_stdout_tty,
    log,
    log_panel,
    resolve_format,
)

# 预设 Schema 映射
PRESET_SCHEMAS = {
    "openai_chat": openai_chat_schema,
    "openai-chat": openai_chat_schema,
    "chat": openai_chat_schema,
    "alpaca": alpaca_schema,
    "dpo": dpo_schema,
    "dpo_pair": dpo_schema,
    "sharegpt": sharegpt_schema,
}

AVAILABLE_PRESETS = ["openai_chat", "alpaca", "dpo", "sharegpt"]


def validate(
    filename: str,
    preset: Optional[str] = None,
    output: Optional[str] = None,
    filter_invalid: bool = False,
    max_errors: int = 20,
    verbose: bool = False,
    workers: Optional[int] = None,
    format: Optional[str] = None,
) -> None:
    """
    使用 Schema 验证数据文件。

    Args:
        filename: 输入文件路径
        preset: 预设 Schema 名称 (openai_chat, alpaca, dpo, sharegpt)
        output: 输出文件路径（保存有效数据）
        filter_invalid: 过滤无效数据并保存
        max_errors: 最多显示的错误数量
        verbose: 显示详细信息
        workers: 并行进程数，None 自动检测，1 禁用并行
        format: 输出格式 (json|ndjson|table); 非 TTY 默认 json, TTY 默认 table

    Examples:
        dt validate data.jsonl --preset=openai_chat
        dt validate data.jsonl --preset=alpaca -o valid.jsonl
        dt validate data.jsonl --preset=chat --filter
        dt validate data.jsonl --preset=chat --workers=4
        dt --format=json validate data.jsonl --preset=chat   # stdout JSON 报告
    """
    filepath = Path(filename)

    _require_file_exists(filepath)
    _check_file_format(filepath)

    # 确定 Schema
    if preset is None:
        die_usage(
            "必须指定预设 Schema (--preset)",
            suggestion=f"可用预设: {', '.join(AVAILABLE_PRESETS)}; 例如: dt validate {filename} --preset=openai_chat",
        )

    preset_lower = preset.lower().replace("-", "_")
    if preset_lower not in PRESET_SCHEMAS:
        die_usage(
            f"未知的预设 Schema: {preset}",
            suggestion=f"可用预设: {', '.join(AVAILABLE_PRESETS)}",
        )

    schema = PRESET_SCHEMAS[preset_lower]()

    # 加载数据
    try:
        data = load_data(str(filepath))
    except Exception as e:
        die_io_error(e, operation="读取", path=str(filepath))

    if not data:
        die(
            "empty_file",
            "文件为空",
            suggestion=f"确认输入文件包含有效记录: {filepath}",
            exit_code=1,
        )

    total = len(data)
    log(f"[bold]验证文件:[/bold] {filepath.name}")
    log(f"[bold]预设 Schema:[/bold] {preset}")
    log(f"[bold]总记录数:[/bold] {total}")

    # 验证（使用并行或串行）
    use_parallel = workers != 1 and total >= 1000

    if use_parallel:
        # 使用进度条（如果有 rich），并输出到 stderr
        try:
            from rich.console import Console
            from rich.progress import (
                BarColumn,
                Progress,
                SpinnerColumn,
                TaskProgressColumn,
                TextColumn,
            )

            _progress_console = Console(stderr=True, highlight=False)

            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]验证数据"),
                BarColumn(),
                TaskProgressColumn(),
                console=_progress_console,
            ) as progress:
                task = progress.add_task("", total=total)

                def update_progress(current: int, total_count: int):
                    progress.update(task, completed=current)

                valid_data, invalid_results = schema.validate_parallel(
                    data, workers=workers, progress_callback=update_progress
                )
        except ImportError:
            log("🔍 验证数据...")
            valid_data, invalid_results = schema.validate_parallel(data, workers=workers)

        invalid_count = len(invalid_results)
        error_samples = invalid_results[:max_errors]
    else:
        # 串行验证
        valid_data = []
        invalid_count = 0
        error_samples = []

        for i, item in enumerate(data):
            result = schema.validate(item)
            if result.valid:
                valid_data.append(item)
            else:
                invalid_count += 1
                if len(error_samples) < max_errors:
                    error_samples.append((i, result))

    valid_count = len(valid_data)
    valid_ratio = valid_count / total if total > 0 else 0.0

    # 构造机器可读的结构
    errors_payload = []
    for idx, result in error_samples:
        errors_payload.append(
            {
                "index": idx,
                "errors": list(result.errors),
            }
        )

    report = {
        "file": str(filepath),
        "preset": preset_lower,
        "total": total,
        "valid": valid_count,
        "invalid": invalid_count,
        "valid_ratio": round(valid_ratio, 4),
        "errors": errors_payload,
    }

    # 输出：TTY table / 非 TTY JSON
    fmt = resolve_format(format, default_for_tty="table")
    if fmt == "table" and is_stdout_tty():
        _render_validate_report(report, max_errors)
    else:
        emit_json(report)

    # 保存有效数据
    if output or filter_invalid:
        output_path = output or str(filepath).replace(filepath.suffix, f"_valid{filepath.suffix}")
        try:
            save_data(valid_data, output_path)
        except Exception as e:
            die_io_error(e, operation="保存", path=str(output_path))
        log(f"[green]✅ 有效数据已保存:[/green] {output_path} ({valid_count} 条)")

    # 详细模式：显示 Schema 定义
    if verbose:
        log("[bold]Schema 定义:[/bold]")
        log(str(schema))


def _render_validate_report(report: dict, max_errors: int) -> None:
    """TTY 模式下把验证报告渲染成 Panel 到 stderr。"""
    total = report["total"]
    valid = report["valid"]
    invalid = report["invalid"]
    ratio_pct = report["valid_ratio"] * 100

    if invalid == 0:
        body = f"[green]✅ 全部通过![/green] {valid}/{total} 条记录有效 (100%)"
    else:
        body = (
            f"[yellow]⚠ 验证结果:[/yellow] {valid}/{total} 条有效 ({ratio_pct:.1f}%)\n"
            f"[red]无效记录:[/red] {invalid} 条"
        )
    log_panel(body, title=f"Schema · {report['preset']}")

    if invalid > 0 and report["errors"]:
        log(f"[bold]错误示例 (最多显示 {max_errors} 条):[/bold]")
        log("-" * 60)
        for entry in report["errors"]:
            log(f"[dim]第 {entry['index']} 行:[/dim]")
            errs = entry["errors"]
            for err in errs[:3]:
                # 错误消息内嵌用户数据值 (got: ...), 转义避免被当 markup 解析
                log(f"  - {escape(str(err))}")
            if len(errs) > 3:
                log(f"  ... 还有 {len(errs) - 3} 个错误")
