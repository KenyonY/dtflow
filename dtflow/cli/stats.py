"""
CLI 数据统计相关命令
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import orjson

from ..storage.io import load_data
from ..utils.field_path import get_field_with_spec
from .common import (
    _check_file_format,
    _infer_type,
    _is_numeric,
    _pad_to_width,
    _require_file_exists,
    _truncate,
)
from .output import die, die_io_error, emit_json, log, log_panel, log_table, resolve_format


def stats(
    filename: str,
    top: int = 10,
    full: bool = False,
    fields: Optional[List[str]] = None,
    expand_fields: Optional[List[str]] = None,
    format: Optional[str] = None,
) -> None:
    """
    显示数据文件的统计信息。

    默认快速模式：只统计行数和字段结构。
    完整模式（--full）：统计值分布、唯一值、长度等详细信息。

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        top: 显示频率最高的前 N 个值，默认 10（仅完整模式）
        full: 完整模式，统计值分布、唯一值等详细信息
        fields: 指定统计的字段列表（支持嵌套路径）
        expand_fields: 展开 list 字段统计的字段列表

    Examples:
        dt stats data.jsonl            # 快速模式（默认）
        dt stats data.jsonl --full     # 完整模式
        dt stats data.csv -f --top=5   # 完整模式，显示 Top 5
        dt stats data.jsonl --full --field=category  # 指定字段
        dt stats data.jsonl --full --expand=tags     # 展开 list 字段
    """
    filepath = Path(filename)

    _require_file_exists(filepath)
    _check_file_format(filepath)

    fmt = resolve_format(format, default_for_tty="table")

    # 快速模式：忽略 --field 和 --expand 参数
    if not full:
        if fields or expand_fields:
            log("[yellow]⚠️  警告: --field 和 --expand 参数仅在完整模式 (--full) 下生效[/yellow]")
        _quick_stats(filepath, fmt=fmt)
        return

    # 加载数据
    try:
        data = load_data(str(filepath))
    except Exception as e:
        die_io_error(e, operation="读取", path=str(filepath))

    if not data:
        die("empty_file", "文件为空", exit_code=1)

    # 计算统计信息
    total = len(data)
    field_stats = _compute_field_stats(data, top, fields, expand_fields)

    # 输出统计信息
    if fmt == "table":
        _print_stats(filepath.name, total, field_stats)
    else:
        payload = {
            "file": filepath.name,
            "total": total,
            "fields": field_stats,
        }
        emit_json(payload)


def _quick_stats(filepath: Path, fmt: str = "table") -> None:
    """
    快速统计模式：只统计行数和字段结构，不遍历全部数据。

    特点:
    - 使用流式计数，不加载全部数据到内存
    - 只读取前几条数据来推断字段结构
    - 不计算值分布、唯一值等耗时统计
    - FlaxList 源：利用 O(1) 随机访问，免加载统计
    """
    from ..streaming import _count_rows_fast, _is_flaxkv_path

    ext = filepath.suffix.lower()

    # FlaxList 是目录，不能用 stat().st_size
    if ext in (".flaxkv", ".kv") or _is_flaxkv_path(filepath):
        file_size = None
    else:
        file_size = filepath.stat().st_size

    # 格式化文件大小
    def format_size(size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    # 快速统计行数
    total = _count_rows_fast(str(filepath))
    if total is None:
        # 回退：手动计数
        total = 0
        try:
            with open(filepath, "rb") as f:
                for line in f:
                    if line.strip():
                        total += 1
        except Exception:
            total = -1

    # 读取前几条数据推断字段结构
    sample_data = []
    sample_size = 5
    try:
        if ext in (".flaxkv", ".kv") or _is_flaxkv_path(filepath):
            # FlaxList：O(1) 索引访问，免加载
            from ..storage.io import _open_flaxlist

            with _open_flaxlist(filepath) as lst:
                n = min(sample_size, len(lst))
                sample_data = lst[:n] if n > 0 else []
        elif ext == ".jsonl":
            with open(filepath, "rb") as f:
                for i, line in enumerate(f):
                    if i >= sample_size:
                        break
                    line = line.strip()
                    if line:
                        sample_data.append(orjson.loads(line))
        elif ext == ".csv":
            import polars as pl

            df = pl.scan_csv(str(filepath)).head(sample_size).collect()
            sample_data = df.to_dicts()
        elif ext == ".parquet":
            import polars as pl

            df = pl.scan_parquet(str(filepath)).head(sample_size).collect()
            sample_data = df.to_dicts()
        elif ext in (".arrow", ".feather"):
            import polars as pl

            df = pl.scan_ipc(str(filepath)).head(sample_size).collect()
            sample_data = df.to_dicts()
        elif ext == ".json":
            with open(filepath, "rb") as f:
                data = orjson.loads(f.read())
                if isinstance(data, list):
                    sample_data = data[:sample_size]
    except Exception:
        pass

    # 分析字段结构
    fields = []
    if sample_data:
        all_keys = set()
        for item in sample_data:
            all_keys.update(item.keys())

        for key in sorted(all_keys):
            # 从采样数据中推断类型
            sample_values = [item.get(key) for item in sample_data if key in item]
            non_null = [v for v in sample_values if v is not None]
            if non_null:
                field_type = _infer_type(non_null)
            else:
                field_type = "unknown"
            fields.append({"field": key, "type": field_type})

    # 非 table 模式：输出结构化 JSON
    if fmt != "table":
        payload = {
            "file": filepath.name,
            "total": total,
            "file_size": file_size,
            "fields": fields,
        }
        emit_json(payload)
        return

    # TTY table 模式：rich 渲染到 stderr
    from rich.table import Table

    size_line = f"\n[bold]大小:[/bold] {format_size(file_size)}" if file_size is not None else ""
    log_panel(
        (
            f"[bold]文件:[/bold] {filepath.name}{size_line}\n"
            f"[bold]总数:[/bold] {total:,} 条\n"
            f"[bold]字段:[/bold] {len(fields)} 个"
        ),
        title="📊 快速统计",
    )

    if fields:
        table = Table(title="📋 字段结构", show_header=True, header_style="bold cyan")
        table.add_column("#", style="dim", justify="right")
        table.add_column("字段", style="green")
        table.add_column("类型", style="yellow")

        for i, f in enumerate(fields, 1):
            table.add_row(str(i), f["field"], f["type"])

        log_table(table)


def _extract_with_wildcard(item: dict, field_spec: str) -> List[Any]:
    """处理包含 [*] 的字段路径，返回所有值"""
    if "[*]" not in field_spec:
        # 无 [*]，直接返回单个值的列表
        value = get_field_with_spec(item, field_spec)
        return [value] if value is not None else []

    # 分割路径：messages[*].role -> ("messages", ".role")
    before, after = field_spec.split("[*]", 1)
    after = after.lstrip(".")  # 移除开头的点

    # 获取数组
    array = get_field_with_spec(item, before) if before else item
    if not isinstance(array, list):
        return []

    # 提取每个元素的后续路径
    results = []
    for elem in array:
        if after:
            val = get_field_with_spec(elem, after)
        else:
            val = elem
        if val is not None:
            results.append(val)

    return results


def _extract_field_values(
    data: List[Dict],
    field_spec: str,
    expand: bool = False,
) -> List[Any]:
    """
    从数据中提取字段值。

    Args:
        data: 数据列表
        field_spec: 字段路径规格（如 "messages[*].role"）
        expand: 是否展开 list

    Returns:
        值列表（展开或不展开）
    """
    all_values = []

    for item in data:
        if "[*]" in field_spec or expand:
            # 使用通配符提取所有值
            values = _extract_with_wildcard(item, field_spec)

            if expand and len(values) == 1 and isinstance(values[0], list):
                # 展开模式：如果返回单个列表，展开其元素
                all_values.extend(values[0])
            elif expand and values and isinstance(values[0], list):
                # 多个列表，全部展开
                for v in values:
                    if isinstance(v, list):
                        all_values.extend(v)
                    else:
                        all_values.append(v)
            else:
                # 不展开或非列表值
                all_values.extend(values)
        else:
            # 普通字段路径
            value = get_field_with_spec(item, field_spec)
            if expand and isinstance(value, list):
                # 展开 list
                all_values.extend(value)
            else:
                all_values.append(value)

    return all_values


def _compute_field_stats(
    data: List[Dict],
    top: int,
    fields: Optional[List[str]] = None,
    expand_fields: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    单次遍历计算每个字段的统计信息。

    优化：将多次遍历合并为单次遍历，在遍历过程中同时收集所有统计数据。

    Args:
        data: 数据列表
        top: Top N 值数量
        fields: 指定统计的字段列表
        expand_fields: 展开 list 字段统计的字段列表
    """
    from collections import Counter, defaultdict

    if not data:
        return []

    total = len(data)

    # 如果没有指定字段，统计所有顶层字段（保持向后兼容）
    if not fields and not expand_fields:
        # 单次遍历收集所有字段的值和统计信息
        field_values = defaultdict(list)  # 存储每个字段的所有值
        field_counters = defaultdict(Counter)  # 存储每个字段的值频率（用于 top N）

        for item in data:
            for k, v in item.items():
                field_values[k].append(v)
                # 对值进行截断后计数（用于 top N 显示）
                displayable = _truncate(v if v is not None else "", 30)
                field_counters[k][displayable] += 1

        # 根据收集的数据计算统计信息
        stats_list = []
        for field in sorted(field_values.keys()):
            values = field_values[field]
            non_null = [v for v in values if v is not None and v != ""]
            non_null_count = len(non_null)

            # 推断类型（从第一个非空值）
            field_type = _infer_type(non_null)

            # 基础统计
            stat = {
                "field": field,
                "non_null": non_null_count,
                "null_rate": f"{non_null_count / total * 100:.1f}%",
                "type": field_type,
            }

            # 类型特定统计
            if non_null:
                # 唯一值计数（对复杂类型使用 hash 节省内存）
                stat["unique"] = _count_unique(non_null, field_type)

                # 字符串类型：计算长度统计
                if field_type == "str":
                    lengths = [len(str(v)) for v in non_null]
                    stat["len_min"] = min(lengths)
                    stat["len_max"] = max(lengths)
                    stat["len_avg"] = sum(lengths) / len(lengths)

                # 数值类型：计算数值统计
                elif field_type in ("int", "float"):
                    nums = [float(v) for v in non_null if _is_numeric(v)]
                    if nums:
                        stat["min"] = min(nums)
                        stat["max"] = max(nums)
                        stat["avg"] = sum(nums) / len(nums)

                # 列表类型：计算长度统计
                elif field_type == "list":
                    lengths = [len(v) if isinstance(v, list) else 0 for v in non_null]
                    stat["len_min"] = min(lengths)
                    stat["len_max"] = max(lengths)
                    stat["len_avg"] = sum(lengths) / len(lengths)

                # Top N 值（已在遍历时收集）
                stat["top_values"] = field_counters[field].most_common(top)

            stats_list.append(stat)

        return stats_list

    # 指定了字段：收集指定字段的统计
    stats_list = []
    expand_set = set(expand_fields) if expand_fields else set()

    # 合并字段列表
    all_fields = set(fields) if fields else set()
    all_fields.update(expand_set)

    for field_spec in sorted(all_fields):
        is_expanded = field_spec in expand_set

        # 提取字段值
        values = _extract_field_values(data, field_spec, expand=is_expanded)

        # 过滤 None 和空值
        non_null = [v for v in values if v is not None and v != ""]
        non_null_count = len(non_null)

        # 推断类型
        field_type = _infer_type(non_null)

        # 基础统计
        if is_expanded:
            # 展开模式：显示元素总数和平均数，而非非空率
            stat = {
                "field": field_spec,
                "non_null": non_null_count,
                "null_rate": f"总元素: {len(values)}",
                "type": field_type,
                "is_expanded": is_expanded,
            }
        else:
            # 普通模式：显示非空率
            stat = {
                "field": field_spec,
                "non_null": non_null_count,
                "null_rate": f"{non_null_count / total * 100:.1f}%",
                "type": field_type,
                "is_expanded": is_expanded,
            }

        # 类型特定统计
        if non_null:
            # 唯一值计数
            stat["unique"] = _count_unique(non_null, field_type)

            # 字符串类型：计算长度统计
            if field_type == "str":
                lengths = [len(str(v)) for v in non_null]
                stat["len_min"] = min(lengths)
                stat["len_max"] = max(lengths)
                stat["len_avg"] = sum(lengths) / len(lengths)

            # 数值类型：计算数值统计
            elif field_type in ("int", "float"):
                nums = [float(v) for v in non_null if _is_numeric(v)]
                if nums:
                    stat["min"] = min(nums)
                    stat["max"] = max(nums)
                    stat["avg"] = sum(nums) / len(nums)

            # 列表类型：计算长度统计
            elif field_type == "list":
                lengths = [len(v) if isinstance(v, list) else 0 for v in non_null]
                stat["len_min"] = min(lengths)
                stat["len_max"] = max(lengths)
                stat["len_avg"] = sum(lengths) / len(lengths)

            # Top N 值（需要重新计数）
            counter = Counter()
            for v in non_null:
                displayable = _truncate(v if v is not None else "", 30)
                counter[displayable] += 1
            stat["top_values"] = counter.most_common(top)

        stats_list.append(stat)

    return stats_list


def _count_unique(values: List[Any], field_type: str) -> int:
    """
    计算唯一值数量。

    对于简单类型直接比较，对于 list/dict 或混合类型使用 hash。
    """
    if field_type in ("list", "dict"):
        return _count_unique_by_hash(values)
    else:
        # 简单类型：尝试直接比较，失败则回退到 hash 方式
        try:
            return len(set(values))
        except TypeError:
            # 混合类型（如字段中既有 str 又有 dict），回退到 hash
            return _count_unique_by_hash(values)


def _count_unique_by_hash(values: List[Any]) -> int:
    """使用 orjson 序列化后计算 hash 来统计唯一值"""
    import hashlib

    seen = set()
    for v in values:
        try:
            h = hashlib.md5(orjson.dumps(v, option=orjson.OPT_SORT_KEYS)).digest()
            seen.add(h)
        except TypeError:
            # 无法序列化的值，用 repr 兜底
            seen.add(repr(v))
    return len(seen)


def _print_stats(filename: str, total: int, field_stats: List[Dict[str, Any]]) -> None:
    """渲染统计信息为 TTY 表格到 stderr。

    注意：此函数只负责 TTY 渲染，不处理 JSON 输出。JSON 路径在 `stats()` 顶层处理。
    """
    from rich.table import Table

    log_panel(
        (
            f"[bold]文件:[/bold] {filename}\n"
            f"[bold]总数:[/bold] {total:,} 条\n"
            f"[bold]字段:[/bold] {len(field_stats)} 个"
        ),
        title="📊 数据概览",
    )

    # 字段统计表
    table = Table(title="📋 字段统计", show_header=True, header_style="bold cyan")
    table.add_column("字段", style="green")
    table.add_column("类型", style="yellow")
    table.add_column("非空率", justify="right")
    table.add_column("唯一值", justify="right")
    table.add_column("统计", style="dim")

    for stat in field_stats:
        if "null_rate" in stat:
            non_null_rate = stat["null_rate"]
        else:
            non_null_rate = f"{stat['non_null'] / total * 100:.0f}%"
        unique = str(stat.get("unique", "-"))

        field_name = stat["field"]
        if stat.get("is_expanded"):
            field_name += " (展开)"

        extra = []
        if "len_avg" in stat:
            extra.append(f"长度: {stat['len_min']}-{stat['len_max']} (avg {stat['len_avg']:.0f})")
        if "avg" in stat:
            if stat["type"] == "int":
                extra.append(f"范围: {int(stat['min'])}-{int(stat['max'])} (avg {stat['avg']:.1f})")
            else:
                extra.append(f"范围: {stat['min']:.2f}-{stat['max']:.2f} (avg {stat['avg']:.2f})")

        table.add_row(
            field_name,
            stat["type"],
            non_null_rate,
            unique,
            "; ".join(extra) if extra else "-",
        )

    log_table(table)

    # Top 值统计（仅显示有意义的字段）
    for stat in field_stats:
        top_values = stat.get("top_values", [])
        if not top_values:
            continue

        unique_count = stat.get("unique", 0)

        # 数值类型：仅当为低基数（枚举/类别，如 0/1 标签）时才显示值分布，
        # 连续型数值（大量不同取值）看分布无意义，跳过。
        if stat["type"] in ("int", "float") and unique_count > 20:
            continue

        unique_ratio = unique_count / total if total > 0 else 0
        if unique_ratio > 0.9 and unique_count > 100:
            continue

        field_display = stat["field"]
        if stat.get("is_expanded"):
            field_display += " (展开)"

        log(f"\n[bold cyan]{field_display}[/bold cyan] 值分布 (Top {len(top_values)}):")
        max_count = max(c for _, c in top_values) if top_values else 1
        base_count = stat["non_null"] if stat.get("is_expanded") else total
        for value, count in top_values:
            pct = count / base_count * 100 if base_count > 0 else 0
            bar_len = int(count / max_count * 20)
            bar = "█" * bar_len
            display_value = value if value else "[空]"
            padded_value = _pad_to_width(display_value, 32)
            log(f"  {padded_value} {count:>6} ({pct:>5.1f}%) {bar}")


def token_stats(
    filename: str,
    field: str = "messages",
    model: str = "cl100k_base",
    detailed: bool = False,
    workers: Optional[int] = None,
    format: Optional[str] = None,
) -> None:
    """
    统计数据集的 Token 信息。

    Args:
        filename: 输入文件路径
        field: 要统计的字段（默认 messages），支持嵌套路径语法
        model: 分词器: cl100k_base (默认), qwen2.5, llama3, gpt-4 等
        detailed: 是否显示详细统计
        workers: 并行进程数，None 自动检测，1 禁用并行

    Examples:
        dt token-stats data.jsonl
        dt token-stats data.jsonl --field=text --model=qwen2.5
        dt token-stats data.jsonl --field=conversation.messages
        dt token-stats data.jsonl --field=messages[-1].content   # 统计最后一条消息
        dt token-stats data.jsonl --detailed
        dt token-stats data.jsonl --workers=4   # 使用 4 进程
    """
    filepath = Path(filename)

    _require_file_exists(filepath)
    _check_file_format(filepath)

    fmt = resolve_format(format, default_for_tty="table")

    # 加载数据
    log(f"📊 加载数据: {filepath}")
    try:
        data = load_data(str(filepath))
    except Exception as e:
        die_io_error(e, operation="读取", path=str(filepath))

    if not data:
        die("empty_file", "文件为空", exit_code=1)

    total = len(data)
    log(f"   共 {total:,} 条数据")

    # 检查字段类型并选择合适的统计方法（支持嵌套路径）
    sample = data[0]
    field_value = get_field_with_spec(sample, field)
    is_messages = isinstance(field_value, list) and field_value and isinstance(field_value[0], dict)

    # 进度条（TTY + table 模式才显示）
    use_progress = fmt == "table"
    try:
        if use_progress:
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
                TextColumn("[bold blue]统计 Token"),
                BarColumn(),
                TaskProgressColumn(),
                TextColumn(f"(模型: {model})"),
                console=_progress_console,
                transient=True,
            ) as progress:
                task = progress.add_task("", total=total)

                def update_progress(current: int, total_count: int):
                    progress.update(task, completed=current)

                stats_result = _compute_token_stats(
                    data, field, model, workers, is_messages, update_progress
                )
        else:
            log(f"🔢 统计 Token (模型: {model}, 字段: {field})...")
            stats_result = _compute_token_stats(data, field, model, workers, is_messages, None)
    except ImportError as e:
        die("missing_dependency", str(e), suggestion="安装相关依赖或使用 cl100k_base 模型")
    except Exception as e:
        die("stats_error", f"统计失败: {e}")

    # 输出
    if fmt == "table":
        if is_messages:
            _print_messages_token_stats(stats_result, detailed)
        else:
            _print_text_token_stats(stats_result, detailed)
    else:
        payload = dict(stats_result)
        payload["file"] = filepath.name
        payload["field"] = field
        payload["model"] = model
        emit_json(payload)


def _compute_token_stats(data, field, model, workers, is_messages, progress_cb):
    """内部辅助：按字段类型选择合适的 token_stats 计算函数。"""
    if is_messages:
        from ..tokenizers import messages_token_stats

        return messages_token_stats(
            data,
            messages_field=field,
            model=model,
            progress_callback=progress_cb,
            workers=workers,
        )
    from ..tokenizers import token_stats as compute_token_stats

    return compute_token_stats(
        data,
        fields=field,
        model=model,
        progress_callback=progress_cb,
        workers=workers,
    )


def _print_messages_token_stats(stats: Dict[str, Any], detailed: bool) -> None:
    """渲染 messages 格式 token 统计到 stderr（TTY table 模式）。"""
    from rich.table import Table

    std = stats.get("std_tokens", 0)
    log_panel(
        (
            f"[bold]总样本数:[/bold] {stats['count']:,}\n"
            f"[bold]总 Token:[/bold] {stats['total_tokens']:,}\n"
            f"[bold]平均 Token:[/bold] {stats['avg_tokens']:,} (std: {std:.1f})\n"
            f"[bold]范围:[/bold] {stats['min_tokens']:,} - {stats['max_tokens']:,}"
        ),
        title="📊 Token 统计概览",
    )

    table = Table(title="📈 分布统计")
    table.add_column("百分位", style="cyan", justify="center")
    table.add_column("Token 数", justify="right")
    percentiles = [
        ("Min", stats["min_tokens"]),
        ("P25", stats.get("p25", "-")),
        ("P50 (中位数)", stats.get("median_tokens", "-")),
        ("P75", stats.get("p75", "-")),
        ("P90", stats.get("p90", "-")),
        ("P95", stats.get("p95", "-")),
        ("P99", stats.get("p99", "-")),
        ("Max", stats["max_tokens"]),
    ]
    for name, val in percentiles:
        table.add_row(name, f"{val:,}" if isinstance(val, int) else str(val))
    log_table(table)

    if detailed:
        role_table = Table(title="📋 分角色统计")
        role_table.add_column("角色", style="cyan")
        role_table.add_column("Token 数", justify="right")
        role_table.add_column("占比", justify="right")

        total = stats["total_tokens"]
        for role, key in [
            ("User", "user_tokens"),
            ("Assistant", "assistant_tokens"),
            ("System", "system_tokens"),
        ]:
            tokens = stats.get(key, 0)
            pct = tokens / total * 100 if total > 0 else 0
            role_table.add_row(role, f"{tokens:,}", f"{pct:.1f}%")

        log_table(role_table)
        log(f"平均对话轮数: {stats.get('avg_turns', 0)}")


def _print_text_token_stats(stats: Dict[str, Any], detailed: bool) -> None:
    """渲染普通文本 token 统计到 stderr（TTY table 模式）。"""
    from rich.table import Table

    std = stats.get("std_tokens", 0)
    log_panel(
        (
            f"[bold]总样本数:[/bold] {stats['count']:,}\n"
            f"[bold]总 Token:[/bold] {stats['total_tokens']:,}\n"
            f"[bold]平均 Token:[/bold] {stats['avg_tokens']:.1f} (std: {std:.1f})\n"
            f"[bold]范围:[/bold] {stats['min_tokens']:,} - {stats['max_tokens']:,}"
        ),
        title="📊 Token 统计",
    )

    table = Table(title="📈 分布统计")
    table.add_column("百分位", style="cyan", justify="center")
    table.add_column("Token 数", justify="right")
    percentiles = [
        ("Min", stats["min_tokens"]),
        ("P25", stats.get("p25", "-")),
        ("P50 (中位数)", stats.get("median_tokens", "-")),
        ("P75", stats.get("p75", "-")),
        ("P90", stats.get("p90", "-")),
        ("P95", stats.get("p95", "-")),
        ("P99", stats.get("p99", "-")),
        ("Max", stats["max_tokens"]),
    ]
    for name, val in percentiles:
        table.add_row(name, f"{val:,}" if isinstance(val, int) else str(val))
    log_table(table)
