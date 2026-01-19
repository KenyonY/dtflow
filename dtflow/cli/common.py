"""
CLI 通用工具函数
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import orjson

# 支持的文件格式
SUPPORTED_FORMATS = {".csv", ".jsonl", ".json", ".xlsx", ".xls", ".parquet", ".arrow", ".feather"}

# 支持流式处理的格式（与 streaming.py 保持一致）
STREAMING_FORMATS = {".jsonl", ".csv", ".parquet", ".arrow", ".feather"}


def _is_streaming_supported(filepath: Path) -> bool:
    """检查文件是否支持流式处理"""
    return filepath.suffix.lower() in STREAMING_FORMATS


def _check_file_format(filepath: Path) -> bool:
    """检查文件格式是否支持，不支持则打印错误信息并返回 False"""
    ext = filepath.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        print(f"错误: 不支持的文件格式 - {ext}")
        print(f"支持的格式: {', '.join(sorted(SUPPORTED_FORMATS))}")
        return False
    return True


def _get_file_row_count(filepath: Path) -> Optional[int]:
    """
    快速获取文件行数（不加载全部数据）。

    支持 JSONL、CSV、Parquet、Arrow 格式的快速计数。
    对于不支持的格式（如 JSON、Excel），会加载数据计数。
    """
    from ..streaming import _count_rows_fast

    # 先尝试快速计数（支持 JSONL/CSV/Parquet/Arrow）
    count = _count_rows_fast(str(filepath))
    if count is not None:
        return count

    # 对于其他格式（JSON、Excel），需要加载数据
    ext = filepath.suffix.lower()
    if ext in (".json", ".xlsx", ".xls"):
        try:
            from ..storage.io import load_data

            data = load_data(str(filepath))
            return len(data)
        except Exception:
            return None

    return None


def _format_value(value: Any, max_len: int = 120) -> str:
    """格式化单个值，长文本截断。"""
    if value is None:
        return "[dim]null[/dim]"
    if isinstance(value, bool):
        return "[cyan]true[/cyan]" if value else "[cyan]false[/cyan]"
    if isinstance(value, (int, float)):
        return f"[cyan]{value}[/cyan]"
    if isinstance(value, str):
        half_len = max_len // 2
        # 处理多行文本
        if "\n" in value:
            lines = value.split("\n")
            preview = value.replace("\n", "\\n")
            if len(preview) > max_len:
                # 前半 + 省略标记 + 后半
                head = preview[:half_len]
                tail = preview[-half_len:]
                return f'"{head} [yellow]<<<{len(lines)}行>>>[/yellow] {tail}"'
            return f'"{preview}"'
        if len(value) > max_len:
            # 前半 + 省略标记 + 后半
            head = value[:half_len]
            tail = value[-half_len:]
            return f'"{head} [yellow]<<<{len(value)}字符>>>[/yellow] {tail}"'
        return f'"{value}"'
    return str(value)


def _format_nested(
    value: Any,
    indent: str = "",
    is_last: bool = True,
    max_len: int = 120,
) -> List[str]:
    """
    递归格式化嵌套结构，返回行列表。

    使用树形符号展示结构：
    ├─ 中间项
    └─ 最后一项
    """
    lines = []

    if isinstance(value, dict):
        items = list(value.items())
        for i, (k, v) in enumerate(items):
            is_last_item = i == len(items) - 1
            b = "└─ " if is_last_item else "├─ "
            c = "   " if is_last_item else "│  "

            if isinstance(v, (dict, list)) and v:
                # 嵌套结构
                if isinstance(v, list):
                    # 检测是否为 messages 格式
                    is_messages = (
                        v and isinstance(v[0], dict) and "role" in v[0] and "content" in v[0]
                    )
                    if is_messages:
                        lines.append(
                            f"{indent}{b}[green]{k}[/green]: ({len(v)} items) [dim]→ \\[role]: content[/dim]"
                        )
                    else:
                        lines.append(f"{indent}{b}[green]{k}[/green]: ({len(v)} items)")
                else:
                    lines.append(f"{indent}{b}[green]{k}[/green]:")
                lines.extend(_format_nested(v, indent + c, True, max_len))
            else:
                # 简单值
                lines.append(f"{indent}{b}[green]{k}[/green]: {_format_value(v, max_len)}")

    elif isinstance(value, list):
        for i, item in enumerate(value):
            is_last_item = i == len(value) - 1
            b = "└─ " if is_last_item else "├─ "
            c = "   " if is_last_item else "│  "

            if isinstance(item, dict):
                # 列表中的字典项 - 检测是否为 messages 格式
                if "role" in item and "content" in item:
                    role = item.get("role", "")
                    content = item.get("content", "")
                    # 截断长内容
                    if len(content) > max_len:
                        content = content[:max_len].replace("\n", "\\n") + "..."
                    else:
                        content = content.replace("\n", "\\n")
                    # 使用 \[ 转义避免被 rich 解析为样式
                    lines.append(f"{indent}{b}[yellow]\\[{role}]:[/yellow] {content}")
                else:
                    # 普通字典
                    lines.append(f"{indent}{b}[dim]{{...}}[/dim]")
                    lines.extend(_format_nested(item, indent + c, True, max_len))
            elif isinstance(item, list):
                lines.append(f"{indent}{b}[dim][{len(item)} items][/dim]")
                lines.extend(_format_nested(item, indent + c, True, max_len))
            else:
                lines.append(f"{indent}{b}{_format_value(item, max_len)}")

    return lines


def _is_simple_data(samples: List[Dict]) -> bool:
    """判断数据是否适合表格展示（无嵌套结构）。"""
    if not samples or not isinstance(samples[0], dict):
        return False
    keys = list(samples[0].keys())
    if len(keys) > 6:
        return False
    for s in samples[:3]:
        for k in keys:
            v = s.get(k)
            if isinstance(v, (dict, list)):
                return False
            if isinstance(v, str) and len(v) > 80:
                return False
    return True


def _print_samples(
    samples: list,
    filename: Optional[str] = None,
    total_count: Optional[int] = None,
    fields: Optional[List[str]] = None,
    file_size: Optional[int] = None,
) -> None:
    """
    打印采样结果。

    Args:
        samples: 采样数据列表
        filename: 文件名（用于显示概览）
        total_count: 文件总行数（用于显示概览），大文件时可能为 None
        fields: 只显示指定字段
        file_size: 文件大小（字节），当 total_count 为 None 时显示
    """
    if not samples:
        print("没有数据")
        return

    # 过滤字段
    if fields and isinstance(samples[0], dict):
        field_set = set(fields)
        samples = [{k: v for k, v in item.items() if k in field_set} for item in samples]

    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console()

        # 显示数据概览头部
        if filename:
            all_fields = set()
            for item in samples:
                if isinstance(item, dict):
                    all_fields.update(item.keys())
            field_names = ", ".join(sorted(all_fields))

            if total_count is not None:
                info = f"总行数: {total_count:,} | 采样: {len(samples)} 条 | 字段: {len(all_fields)} 个"
            elif file_size is not None:
                info = f"文件大小: {_format_file_size(file_size)} | 采样: {len(samples)} 条 | 字段: {len(all_fields)} 个"
            else:
                info = f"采样: {len(samples)} 条 | 字段: {len(all_fields)} 个"

            console.print(
                Panel(
                    f"[dim]{info}[/dim]\n[dim]字段: {field_names}[/dim]",
                    title=f"[bold]📊 {filename}[/bold]",
                    expand=False,
                    border_style="dim",
                )
            )
            console.print()

        # 简单数据用表格展示
        if _is_simple_data(samples):
            keys = list(samples[0].keys())
            table = Table(show_header=True, header_style="bold cyan")
            for key in keys:
                table.add_column(key, overflow="fold")
            for item in samples:
                table.add_row(*[str(item.get(k, "")) for k in keys])
            console.print(table)
            return

        # 嵌套数据用树形结构展示
        for i, item in enumerate(samples, 1):
            console.print(f"[bold cyan]--- 第 {i} 条 ---[/bold cyan]")
            if isinstance(item, dict):
                for line in _format_nested(item):
                    console.print(line)
            else:
                console.print(_format_value(item))
            console.print()

    except ImportError:
        # 没有 rich，使用普通打印
        if filename:
            all_fields = set()
            for item in samples:
                if isinstance(item, dict):
                    all_fields.update(item.keys())

            print(f"\n📊 {filename}")
            if total_count is not None:
                print(
                    f"   总行数: {total_count:,} | 采样: {len(samples)} 条 | 字段: {len(all_fields)} 个"
                )
            elif file_size is not None:
                print(
                    f"   文件大小: {_format_file_size(file_size)} | 采样: {len(samples)} 条 | 字段: {len(all_fields)} 个"
                )
            else:
                print(f"   采样: {len(samples)} 条 | 字段: {len(all_fields)} 个")
            print(f"   字段: {', '.join(sorted(all_fields))}")
            print()

        for i, item in enumerate(samples, 1):
            print(f"--- 第 {i} 条 ---")
            print(orjson.dumps(item, option=orjson.OPT_INDENT_2).decode("utf-8"))
            print()


def _parse_field_list(value: Any) -> List[str]:
    """解析字段列表参数（处理 fire 将逗号分隔的值解析为元组的情况）"""
    if isinstance(value, (list, tuple)):
        return [str(f).strip() for f in value]
    elif isinstance(value, str):
        return [f.strip() for f in value.split(",")]
    else:
        return [str(value)]


def _format_file_size(size: int) -> str:
    """格式化文件大小"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _is_empty_value(v: Any) -> bool:
    """判断值是否为空"""
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    if isinstance(v, (list, dict)) and len(v) == 0:
        return True
    return False


def _get_value_len(value: Any) -> int:
    """
    获取值的长度。

    - str/list/dict: 返回 len()
    - int/float: 直接返回该数值（用于 messages.# 这种返回数量的场景）
    - None: 返回 0
    - 其他: 转为字符串后返回长度
    """
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, (str, list, dict)):
        return len(value)
    return len(str(value))


def _infer_type(values: List[Any]) -> str:
    """推断字段类型"""
    if not values:
        return "unknown"

    sample = values[0]
    if isinstance(sample, bool):
        return "bool"
    if isinstance(sample, int):
        return "int"
    if isinstance(sample, float):
        return "float"
    if isinstance(sample, list):
        return "list"
    if isinstance(sample, dict):
        return "dict"
    return "str"


def _is_numeric(v: Any) -> bool:
    """检查值是否为数值"""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return True
    return False


def _truncate(v: Any, max_width: int) -> str:
    """按显示宽度截断值（中文字符算 2 宽度）"""
    s = str(v)
    width = 0
    result = []
    for char in s:
        # CJK 字符范围
        if (
            "\u4e00" <= char <= "\u9fff"
            or "\u3000" <= char <= "\u303f"
            or "\uff00" <= char <= "\uffef"
        ):
            char_width = 2
        else:
            char_width = 1
        if width + char_width > max_width - 3:  # 预留 ... 的宽度
            return "".join(result) + "..."
        result.append(char)
        width += char_width
    return s


def _display_width(s: str) -> int:
    """计算字符串的显示宽度（中文字符算 2，ASCII 字符算 1）"""
    width = 0
    for char in s:
        # CJK 字符范围
        if (
            "\u4e00" <= char <= "\u9fff"
            or "\u3000" <= char <= "\u303f"
            or "\uff00" <= char <= "\uffef"
        ):
            width += 2
        else:
            width += 1
    return width


def _pad_to_width(s: str, target_width: int) -> str:
    """将字符串填充到指定的显示宽度"""
    current_width = _display_width(s)
    if current_width >= target_width:
        return s
    return s + " " * (target_width - current_width)
