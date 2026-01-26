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
    _truncate,
)


def stats(
    filename: str,
    top: int = 10,
    full: bool = False,
) -> None:
    """
    显示数据文件的统计信息。

    默认快速模式：只统计行数和字段结构。
    完整模式（--full）：统计值分布、唯一值、长度等详细信息。

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        top: 显示频率最高的前 N 个值，默认 10（仅完整模式）
        full: 完整模式，统计值分布、唯一值等详细信息

    Examples:
        dt stats data.jsonl            # 快速模式（默认）
        dt stats data.jsonl --full     # 完整模式
        dt stats data.csv -f --top=5   # 完整模式，显示 Top 5
    """
    filepath = Path(filename)

    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
        return

    if not full:
        _quick_stats(filepath)
        return

    # 加载数据
    try:
        data = load_data(str(filepath))
    except Exception as e:
        print(f"错误: 无法读取文件 - {e}")
        return

    if not data:
        print("文件为空")
        return

    # 计算统计信息
    total = len(data)
    field_stats = _compute_field_stats(data, top)

    # 输出统计信息
    _print_stats(filepath.name, total, field_stats)


def _quick_stats(filepath: Path) -> None:
    """
    快速统计模式：只统计行数和字段结构，不遍历全部数据。

    特点:
    - 使用流式计数，不加载全部数据到内存
    - 只读取前几条数据来推断字段结构
    - 不计算值分布、唯一值等耗时统计
    """
    from ..streaming import _count_rows_fast

    ext = filepath.suffix.lower()
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
        if ext == ".jsonl":
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

    # 输出
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console()

        # 概览
        console.print(
            Panel(
                f"[bold]文件:[/bold] {filepath.name}\n"
                f"[bold]大小:[/bold] {format_size(file_size)}\n"
                f"[bold]总数:[/bold] {total:,} 条\n"
                f"[bold]字段:[/bold] {len(fields)} 个",
                title="📊 快速统计",
                expand=False,
            )
        )

        if fields:
            table = Table(title="📋 字段结构", show_header=True, header_style="bold cyan")
            table.add_column("#", style="dim", justify="right")
            table.add_column("字段", style="green")
            table.add_column("类型", style="yellow")

            for i, f in enumerate(fields, 1):
                table.add_row(str(i), f["field"], f["type"])

            console.print(table)

    except ImportError:
        # 没有 rich，使用普通打印
        print(f"\n{'=' * 40}")
        print("📊 快速统计")
        print(f"{'=' * 40}")
        print(f"文件: {filepath.name}")
        print(f"大小: {format_size(file_size)}")
        print(f"总数: {total:,} 条")
        print(f"字段: {len(fields)} 个")

        if fields:
            print("\n📋 字段结构:")
            for i, f in enumerate(fields, 1):
                print(f"  {i}. {f['field']} ({f['type']})")


def _compute_field_stats(data: List[Dict], top: int) -> List[Dict[str, Any]]:
    """
    单次遍历计算每个字段的统计信息。

    优化：将多次遍历合并为单次遍历，在遍历过程中同时收集所有统计数据。
    """
    from collections import Counter, defaultdict

    if not data:
        return []

    total = len(data)

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
            "null_rate": f"{(total - non_null_count) / total * 100:.1f}%",
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
    """打印统计信息"""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console()

        # 概览
        console.print(
            Panel(
                f"[bold]文件:[/bold] {filename}\n"
                f"[bold]总数:[/bold] {total:,} 条\n"
                f"[bold]字段:[/bold] {len(field_stats)} 个",
                title="📊 数据概览",
                expand=False,
            )
        )

        # 字段统计表
        table = Table(title="📋 字段统计", show_header=True, header_style="bold cyan")
        table.add_column("字段", style="green")
        table.add_column("类型", style="yellow")
        table.add_column("非空率", justify="right")
        table.add_column("唯一值", justify="right")
        table.add_column("统计", style="dim")

        for stat in field_stats:
            non_null_rate = f"{stat['non_null'] / total * 100:.0f}%"
            unique = str(stat.get("unique", "-"))

            # 构建统计信息字符串
            extra = []
            if "len_avg" in stat:
                extra.append(
                    f"长度: {stat['len_min']}-{stat['len_max']} (avg {stat['len_avg']:.0f})"
                )
            if "avg" in stat:
                if stat["type"] == "int":
                    extra.append(
                        f"范围: {int(stat['min'])}-{int(stat['max'])} (avg {stat['avg']:.1f})"
                    )
                else:
                    extra.append(
                        f"范围: {stat['min']:.2f}-{stat['max']:.2f} (avg {stat['avg']:.2f})"
                    )

            table.add_row(
                stat["field"],
                stat["type"],
                non_null_rate,
                unique,
                "; ".join(extra) if extra else "-",
            )

        console.print(table)

        # Top 值统计（仅显示有意义的字段）
        for stat in field_stats:
            top_values = stat.get("top_values", [])
            if not top_values:
                continue

            # 跳过数值类型（min/max/avg 已足够）
            if stat["type"] in ("int", "float"):
                continue

            # 跳过唯一值过多的字段（基本都是唯一的）
            unique_ratio = stat.get("unique", 0) / total if total > 0 else 0
            if unique_ratio > 0.9 and stat.get("unique", 0) > 100:
                continue

            console.print(
                f"\n[bold cyan]{stat['field']}[/bold cyan] 值分布 (Top {len(top_values)}):"
            )
            max_count = max(c for _, c in top_values) if top_values else 1
            for value, count in top_values:
                pct = count / total * 100
                bar_len = int(count / max_count * 20)  # 按相对比例，最长 20 字符
                bar = "█" * bar_len
                display_value = value if value else "[空]"
                # 使用显示宽度对齐（处理中文字符）
                padded_value = _pad_to_width(display_value, 32)
                console.print(f"  {padded_value} {count:>6} ({pct:>5.1f}%) {bar}")

    except ImportError:
        # 没有 rich，使用普通打印
        print(f"\n{'=' * 50}")
        print("📊 数据概览")
        print(f"{'=' * 50}")
        print(f"文件: {filename}")
        print(f"总数: {total:,} 条")
        print(f"字段: {len(field_stats)} 个")

        print(f"\n{'=' * 50}")
        print("📋 字段统计")
        print(f"{'=' * 50}")
        print(f"{'字段':<20} {'类型':<8} {'非空率':<8} {'唯一值':<8}")
        print("-" * 50)

        for stat in field_stats:
            non_null_rate = f"{stat['non_null'] / total * 100:.0f}%"
            unique = str(stat.get("unique", "-"))
            print(f"{stat['field']:<20} {stat['type']:<8} {non_null_rate:<8} {unique:<8}")


def token_stats(
    filename: str,
    field: str = "messages",
    model: str = "cl100k_base",
    detailed: bool = False,
    workers: Optional[int] = None,
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

    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
        return

    # 加载数据
    print(f"📊 加载数据: {filepath}")
    try:
        data = load_data(str(filepath))
    except Exception as e:
        print(f"错误: 无法读取文件 - {e}")
        return

    if not data:
        print("文件为空")
        return

    total = len(data)
    print(f"   共 {total:,} 条数据")

    # 检查字段类型并选择合适的统计方法（支持嵌套路径）
    sample = data[0]
    field_value = get_field_with_spec(sample, field)

    # 尝试使用 rich 进度条
    try:
        from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]统计 Token"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn(f"(模型: {model})"),
        ) as progress:
            task = progress.add_task("", total=total)

            def update_progress(current: int, total_count: int):
                progress.update(task, completed=current)

            if isinstance(field_value, list) and field_value and isinstance(field_value[0], dict):
                from ..tokenizers import messages_token_stats

                stats_result = messages_token_stats(
                    data,
                    messages_field=field,
                    model=model,
                    progress_callback=update_progress,
                    workers=workers,
                )
                _print_messages_token_stats(stats_result, detailed)
            else:
                from ..tokenizers import token_stats as compute_token_stats

                stats_result = compute_token_stats(
                    data,
                    fields=field,
                    model=model,
                    progress_callback=update_progress,
                    workers=workers,
                )
                _print_text_token_stats(stats_result, detailed)

    except ImportError:
        # 没有 rich，显示简单进度
        print(f"🔢 统计 Token (模型: {model}, 字段: {field})...")
        try:
            if isinstance(field_value, list) and field_value and isinstance(field_value[0], dict):
                from ..tokenizers import messages_token_stats

                stats_result = messages_token_stats(
                    data, messages_field=field, model=model, workers=workers
                )
                _print_messages_token_stats(stats_result, detailed)
            else:
                from ..tokenizers import token_stats as compute_token_stats

                stats_result = compute_token_stats(data, fields=field, model=model, workers=workers)
                _print_text_token_stats(stats_result, detailed)
        except ImportError as e:
            print(f"错误: {e}")
            return
        except Exception as e:
            print(f"错误: 统计失败 - {e}")
            import traceback

            traceback.print_exc()


def _print_messages_token_stats(stats: Dict[str, Any], detailed: bool) -> None:
    """打印 messages 格式的 token 统计"""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console()

        # 概览
        std = stats.get("std_tokens", 0)
        overview = (
            f"[bold]总样本数:[/bold] {stats['count']:,}\n"
            f"[bold]总 Token:[/bold] {stats['total_tokens']:,}\n"
            f"[bold]平均 Token:[/bold] {stats['avg_tokens']:,} (std: {std:.1f})\n"
            f"[bold]范围:[/bold] {stats['min_tokens']:,} - {stats['max_tokens']:,}"
        )
        console.print(Panel(overview, title="📊 Token 统计概览", expand=False))

        # 百分位数表格
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
        console.print(table)

        if detailed:
            # 分角色统计
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

            console.print(role_table)
            console.print(f"\n平均对话轮数: {stats.get('avg_turns', 0)}")

    except ImportError:
        # 没有 rich，使用普通打印
        std = stats.get("std_tokens", 0)
        print(f"\n{'=' * 40}")
        print("📊 Token 统计概览")
        print(f"{'=' * 40}")
        print(f"总样本数: {stats['count']:,}")
        print(f"总 Token: {stats['total_tokens']:,}")
        print(f"平均 Token: {stats['avg_tokens']:,} (std: {std:.1f})")
        print(f"范围: {stats['min_tokens']:,} - {stats['max_tokens']:,}")

        print("\n📈 百分位分布:")
        print(f"  P25: {stats.get('p25', '-'):,}  P50: {stats.get('median_tokens', '-'):,}")
        print(f"  P75: {stats.get('p75', '-'):,}  P90: {stats.get('p90', '-'):,}")
        print(f"  P95: {stats.get('p95', '-'):,}  P99: {stats.get('p99', '-'):,}")

        if detailed:
            print(f"\n{'=' * 40}")
            print("📋 分角色统计")
            print(f"{'=' * 40}")
            total = stats["total_tokens"]
            for role, key in [
                ("User", "user_tokens"),
                ("Assistant", "assistant_tokens"),
                ("System", "system_tokens"),
            ]:
                tokens = stats.get(key, 0)
                pct = tokens / total * 100 if total > 0 else 0
                print(f"{role}: {tokens:,} ({pct:.1f}%)")
            print(f"\n平均对话轮数: {stats.get('avg_turns', 0)}")


def _print_text_token_stats(stats: Dict[str, Any], detailed: bool) -> None:
    """打印普通文本的 token 统计"""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console()

        std = stats.get("std_tokens", 0)
        overview = (
            f"[bold]总样本数:[/bold] {stats['count']:,}\n"
            f"[bold]总 Token:[/bold] {stats['total_tokens']:,}\n"
            f"[bold]平均 Token:[/bold] {stats['avg_tokens']:.1f} (std: {std:.1f})\n"
            f"[bold]范围:[/bold] {stats['min_tokens']:,} - {stats['max_tokens']:,}"
        )
        console.print(Panel(overview, title="📊 Token 统计", expand=False))

        # 百分位数表格
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
        console.print(table)

    except ImportError:
        std = stats.get("std_tokens", 0)
        print(f"\n{'=' * 40}")
        print("📊 Token 统计")
        print(f"{'=' * 40}")
        print(f"总样本数: {stats['count']:,}")
        print(f"总 Token: {stats['total_tokens']:,}")
        print(f"平均 Token: {stats['avg_tokens']:.1f} (std: {std:.1f})")
        print(f"范围: {stats['min_tokens']:,} - {stats['max_tokens']:,}")

        print("\n📈 百分位分布:")
        print(f"  P25: {stats.get('p25', '-'):,}  P50: {stats.get('median_tokens', '-'):,}")
        print(f"  P75: {stats.get('p75', '-'):,}  P90: {stats.get('p90', '-'):,}")
        print(f"  P95: {stats.get('p95', '-'):,}  P99: {stats.get('p99', '-'):,}")
