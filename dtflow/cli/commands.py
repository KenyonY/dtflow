"""
CLI 命令实现
"""

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import orjson

from ..core import DataTransformer, DictWrapper
from ..lineage import format_lineage_report, get_lineage_chain, has_lineage, load_lineage
from ..pipeline import run_pipeline, validate_pipeline
from ..presets import get_preset, list_presets
from ..storage.io import load_data, sample_file, save_data
from ..streaming import load_stream

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


def sample(
    filename: str,
    num: int = 10,
    type: Literal["random", "head", "tail"] = "head",
    output: Optional[str] = None,
    seed: Optional[int] = None,
    by: Optional[str] = None,
    uniform: bool = False,
    fields: Optional[str] = None,
) -> None:
    """
    从数据文件中采样指定数量的数据。

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        num: 采样数量，默认 10
            - num > 0: 采样指定数量
            - num = 0: 采样所有数据
            - num < 0: Python 切片风格（如 -1 表示最后 1 条，-10 表示最后 10 条）
        type: 采样方式，可选 random/head/tail，默认 head
        output: 输出文件路径，不指定则打印到控制台
        seed: 随机种子（仅在 type=random 时有效）
        by: 分层采样字段名，按该字段的值分组采样
        uniform: 均匀采样模式（需配合 --by 使用），各组采样相同数量
        fields: 只显示指定字段（逗号分隔），仅在预览模式下有效

    Examples:
        dt sample data.jsonl 5
        dt sample data.csv 100 --type=head
        dt sample data.xlsx 50 --output=sampled.jsonl
        dt sample data.jsonl 0   # 采样所有数据
        dt sample data.jsonl -10 # 最后 10 条数据
        dt sample data.jsonl 1000 --by=category           # 按比例分层采样
        dt sample data.jsonl 1000 --by=category --uniform # 均匀分层采样
        dt sample data.jsonl --fields=question,answer     # 只显示指定字段
    """
    filepath = Path(filename)

    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
        return

    # uniform 必须配合 by 使用
    if uniform and not by:
        print("错误: --uniform 必须配合 --by 使用")
        return

    # 分层采样模式
    if by:
        try:
            sampled = _stratified_sample(filepath, num, by, uniform, seed, type)
        except Exception as e:
            print(f"错误: {e}")
            return
    else:
        # 普通采样
        try:
            sampled = sample_file(
                str(filepath),
                num=num,
                sample_type=type,
                seed=seed,
                output=None,  # 先不保存，统一在最后处理
            )
        except Exception as e:
            print(f"错误: {e}")
            return

    # 输出结果
    if output:
        save_data(sampled, output)
        print(f"已保存 {len(sampled)} 条数据到 {output}")
    else:
        # 获取文件总行数用于显示
        total_count = _get_file_row_count(filepath)
        # 解析 fields 参数
        field_list = _parse_field_list(fields) if fields else None
        _print_samples(sampled, filepath.name, total_count, field_list)


def _stratified_sample(
    filepath: Path,
    num: int,
    stratify_field: str,
    uniform: bool,
    seed: Optional[int],
    sample_type: str,
) -> List[Dict]:
    """
    分层采样实现。

    Args:
        filepath: 文件路径
        num: 目标采样总数
        stratify_field: 分层字段
        uniform: 是否均匀采样（各组相同数量）
        seed: 随机种子
        sample_type: 采样方式（用于组内采样）

    Returns:
        采样后的数据列表
    """
    import random
    from collections import defaultdict

    if seed is not None:
        random.seed(seed)

    # 加载数据
    data = load_data(str(filepath))
    total = len(data)

    if num <= 0 or num > total:
        num = total

    # 按字段分组
    groups: Dict[Any, List[Dict]] = defaultdict(list)
    for item in data:
        key = item.get(stratify_field, "__null__")
        groups[key].append(item)

    group_keys = list(groups.keys())
    num_groups = len(group_keys)

    # 打印分组信息
    print(f"📊 分层采样: 字段={stratify_field}, 共 {num_groups} 组")
    for key in sorted(group_keys, key=lambda x: -len(groups[x])):
        count = len(groups[key])
        pct = count / total * 100
        display_key = key if key != "__null__" else "[空值]"
        print(f"   {display_key}: {count} 条 ({pct:.1f}%)")

    # 计算各组采样数量
    if uniform:
        # 均匀采样：各组数量相等
        per_group = num // num_groups
        remainder = num % num_groups
        sample_counts = {key: per_group for key in group_keys}
        # 余数分配给数据量最多的组
        for key in sorted(group_keys, key=lambda x: -len(groups[x]))[:remainder]:
            sample_counts[key] += 1
    else:
        # 按比例采样：保持原有比例
        sample_counts = {}
        allocated = 0
        # 按组大小降序处理，确保小组也能分到
        sorted_keys = sorted(group_keys, key=lambda x: -len(groups[x]))
        for i, key in enumerate(sorted_keys):
            if i == len(sorted_keys) - 1:
                # 最后一组分配剩余
                sample_counts[key] = num - allocated
            else:
                # 按比例计算
                ratio = len(groups[key]) / total
                count = int(num * ratio)
                # 确保至少 1 条（如果组有数据）
                count = max(1, count) if groups[key] else 0
                sample_counts[key] = count
                allocated += count

    # 执行各组采样
    result = []
    print(f"🔄 执行采样...")
    for key in group_keys:
        group_data = groups[key]
        target = min(sample_counts[key], len(group_data))

        if target <= 0:
            continue

        # 组内采样
        if sample_type == "random":
            sampled = random.sample(group_data, target)
        elif sample_type == "head":
            sampled = group_data[:target]
        else:  # tail
            sampled = group_data[-target:]

        result.extend(sampled)

    # 打印采样结果
    print(f"\n📋 采样结果:")
    result_groups: Dict[Any, int] = defaultdict(int)
    for item in result:
        key = item.get(stratify_field, "__null__")
        result_groups[key] += 1

    for key in sorted(group_keys, key=lambda x: -len(groups[x])):
        orig = len(groups[key])
        sampled_count = result_groups.get(key, 0)
        display_key = key if key != "__null__" else "[空值]"
        print(f"   {display_key}: {orig} → {sampled_count}")

    print(f"\n✅ 总计: {total} → {len(result)} 条")

    return result


def head(
    filename: str,
    num: int = 10,
    output: Optional[str] = None,
    fields: Optional[str] = None,
) -> None:
    """
    显示文件的前 N 条数据（dt sample --type=head 的快捷方式）。

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        num: 显示数量，默认 10
            - num > 0: 显示指定数量
            - num = 0: 显示所有数据
            - num < 0: Python 切片风格（如 -10 表示最后 10 条）
        output: 输出文件路径，不指定则打印到控制台
        fields: 只显示指定字段（逗号分隔），仅在预览模式下有效

    Examples:
        dt head data.jsonl          # 显示前 10 条
        dt head data.jsonl 20       # 显示前 20 条
        dt head data.csv 0          # 显示所有数据
        dt head data.xlsx --output=head.jsonl
        dt head data.jsonl --fields=question,answer
    """
    sample(filename, num=num, type="head", output=output, fields=fields)


def tail(
    filename: str,
    num: int = 10,
    output: Optional[str] = None,
    fields: Optional[str] = None,
) -> None:
    """
    显示文件的后 N 条数据（dt sample --type=tail 的快捷方式）。

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        num: 显示数量，默认 10
            - num > 0: 显示指定数量
            - num = 0: 显示所有数据
            - num < 0: Python 切片风格（如 -10 表示最后 10 条）
        output: 输出文件路径，不指定则打印到控制台
        fields: 只显示指定字段（逗号分隔），仅在预览模式下有效

    Examples:
        dt tail data.jsonl          # 显示后 10 条
        dt tail data.jsonl 20       # 显示后 20 条
        dt tail data.csv 0          # 显示所有数据
        dt tail data.xlsx --output=tail.jsonl
        dt tail data.jsonl --fields=question,answer
    """
    sample(filename, num=num, type="tail", output=output, fields=fields)


def _get_file_row_count(filepath: Path) -> Optional[int]:
    """
    快速获取文件行数（不加载全部数据）。

    对于 JSONL 文件，直接计算行数；其他格式返回 None。
    """
    ext = filepath.suffix.lower()
    if ext == ".jsonl":
        try:
            with open(filepath, "rb") as f:
                return sum(1 for _ in f)
        except Exception:
            return None
    # 其他格式暂不支持快速计数
    return None


def _format_value(value: Any, max_len: int = 80) -> str:
    """格式化单个值，长文本截断。"""
    if value is None:
        return "[dim]null[/dim]"
    if isinstance(value, bool):
        return "[cyan]true[/cyan]" if value else "[cyan]false[/cyan]"
    if isinstance(value, (int, float)):
        return f"[cyan]{value}[/cyan]"
    if isinstance(value, str):
        # 处理多行文本
        if "\n" in value:
            lines = value.split("\n")
            if len(lines) > 3:
                preview = lines[0][:max_len] + f"... [dim]({len(lines)} 行)[/dim]"
            else:
                preview = value.replace("\n", "\\n")
                if len(preview) > max_len:
                    preview = preview[:max_len] + "..."
            return f'"{preview}"'
        if len(value) > max_len:
            return f'"{value[:max_len]}..." [dim]({len(value)} 字符)[/dim]'
        return f'"{value}"'
    return str(value)


def _format_nested(
    value: Any,
    indent: str = "",
    is_last: bool = True,
    max_len: int = 80,
) -> List[str]:
    """
    递归格式化嵌套结构，返回行列表。

    使用树形符号展示结构：
    ├─ 中间项
    └─ 最后一项
    """
    lines = []
    branch = "└─ " if is_last else "├─ "
    cont = "   " if is_last else "│  "

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
) -> None:
    """
    打印采样结果。

    Args:
        samples: 采样数据列表
        filename: 文件名（用于显示概览）
        total_count: 文件总行数（用于显示概览）
        fields: 只显示指定字段
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
            else:
                print(f"   采样: {len(samples)} 条 | 字段: {len(all_fields)} 个")
            print(f"   字段: {', '.join(sorted(all_fields))}")
            print()

        for i, item in enumerate(samples, 1):
            print(f"--- 第 {i} 条 ---")
            print(orjson.dumps(item, option=orjson.OPT_INDENT_2).decode("utf-8"))
            print()


# ============ Transform Command ============

CONFIG_DIR = ".dt"


def _get_config_path(input_path: Path, config_override: Optional[str] = None) -> Path:
    """获取配置文件路径"""
    if config_override:
        return Path(config_override)

    # 使用输入文件名（不含扩展名）作为配置文件名
    config_name = input_path.stem + ".py"
    return input_path.parent / CONFIG_DIR / config_name


def transform(
    filename: str,
    num: Optional[int] = None,
    preset: Optional[str] = None,
    config: Optional[str] = None,
    output: Optional[str] = None,
) -> None:
    """
    转换数据格式。

    两种使用方式：
    1. 配置文件模式（默认）：自动生成配置文件，编辑后再次运行
    2. 预设模式：使用 --preset 直接转换

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        num: 只转换前 N 条数据（可选）
        preset: 使用预设模板（openai_chat, alpaca, sharegpt, dpo_pair, simple_qa）
        config: 配置文件路径（可选，默认 .dt/<filename>.py）
        output: 输出文件路径

    Examples:
        dt transform data.jsonl                        # 首次生成配置
        dt transform data.jsonl 10                     # 只转换前 10 条
        dt transform data.jsonl --preset=openai_chat   # 使用预设
        dt transform data.jsonl 100 --preset=alpaca    # 预设 + 限制数量
    """
    filepath = Path(filename)
    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
        return

    # 预设模式：直接使用预设转换
    if preset:
        _execute_preset_transform(filepath, preset, output, num)
        return

    # 配置文件模式
    config_path = _get_config_path(filepath, config)

    if not config_path.exists():
        _generate_config(filepath, config_path)
    else:
        _execute_transform(filepath, config_path, output, num)


def _generate_config(input_path: Path, config_path: Path) -> None:
    """分析输入数据并生成配置文件"""
    print(f"📊 分析输入数据: {input_path}")

    # 读取数据
    try:
        data = load_data(str(input_path))
    except Exception as e:
        print(f"错误: 无法读取文件 - {e}")
        return

    if not data:
        print("错误: 文件为空")
        return

    total_count = len(data)
    sample_item = data[0]

    print(f"   检测到 {total_count} 条数据")

    # 生成配置内容
    config_content = _build_config_content(sample_item, input_path.name, total_count)

    # 确保配置目录存在
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # 写入配置文件
    config_path.write_text(config_content, encoding="utf-8")

    print(f"\n📝 已生成配置文件: {config_path}")
    print("\n👉 下一步:")
    print(f"   1. 编辑 {config_path}，定义 transform 函数")
    print(f"   2. 再次执行 dt transform {input_path.name} 完成转换")


def _build_config_content(sample: Dict[str, Any], filename: str, total: int) -> str:
    """构建配置文件内容"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 生成 Item 类的字段定义
    fields_def = _generate_fields_definition(sample)

    # 生成默认的 transform 函数（简单重命名）
    field_names = list(sample.keys())

    # 生成规范化的字段名用于示例
    safe_field1 = _sanitize_field_name(field_names[0])[0] if field_names else "field1"
    safe_field2 = _sanitize_field_name(field_names[1])[0] if len(field_names) > 1 else "field2"

    # 生成默认输出文件名
    base_name = Path(filename).stem
    output_filename = f"{base_name}_output.jsonl"

    config = f'''"""
DataTransformer 配置文件
生成时间: {now}
输入文件: {filename} ({total} 条)
"""


# ===== 输入数据结构（自动生成，IDE 可补全）=====

class Item:
{fields_def}


# ===== 定义转换逻辑 =====
# 提示：输入 item. 后 IDE 会自动补全可用字段

def transform(item: Item):
    return {{
{_generate_default_transform(field_names)}
    }}


# 输出文件路径
output = "{output_filename}"


# ===== 示例 =====
#
# 示例1: 构建 OpenAI Chat 格式
# def transform(item: Item):
#     return {{
#         "messages": [
#             {{"role": "user", "content": item.{safe_field1}}},
#             {{"role": "assistant", "content": item.{safe_field2}}},
#         ]
#     }}
#
# 示例2: Alpaca 格式
# def transform(item: Item):
#     return {{
#         "instruction": item.{safe_field1},
#         "input": "",
#         "output": item.{safe_field2},
#     }}
'''
    return config


def _generate_fields_definition(sample: Dict[str, Any], indent: int = 4) -> str:
    """生成 Item 类的字段定义"""
    lines = []
    prefix = " " * indent

    for key, value in sample.items():
        type_name = _get_type_name(value)
        example = _format_example_value(value)
        safe_key, changed = _sanitize_field_name(key)
        comment = f"  # 原字段名: {key}" if changed else ""
        lines.append(f"{prefix}{safe_key}: {type_name} = {example}{comment}")

    return "\n".join(lines) if lines else f"{prefix}pass"


def _get_type_name(value: Any) -> str:
    """获取值的类型名称"""
    if value is None:
        return "str"
    if isinstance(value, str):
        return "str"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "str"


def _format_example_value(value: Any, max_len: int = 50) -> str:
    """格式化示例值"""
    if value is None:
        return '""'
    if isinstance(value, str):
        # 截断长字符串
        if len(value) > max_len:
            value = value[:max_len] + "..."
        # 使用 repr() 自动处理所有转义字符
        return repr(value)
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        s = orjson.dumps(value).decode("utf-8")
        if len(s) > max_len:
            return repr(s[:max_len] + "...")
        return s
    return '""'


def _sanitize_field_name(name: str) -> tuple:
    """
    将字段名规范化为合法的 Python 标识符。

    Returns:
        tuple: (规范化后的名称, 是否被修改)
    """
    if name.isidentifier():
        return name, False

    # 替换常见的非法字符
    sanitized = name.replace("-", "_").replace(" ", "_").replace(".", "_")

    # 如果以数字开头，添加前缀
    if sanitized and sanitized[0].isdigit():
        sanitized = "f_" + sanitized

    # 移除其他非法字符
    sanitized = "".join(c if c.isalnum() or c == "_" else "_" for c in sanitized)

    # 确保不为空
    if not sanitized:
        sanitized = "field"

    return sanitized, True


def _generate_default_transform(field_names: List[str]) -> str:
    """生成默认的 transform 函数体"""
    lines = []
    for name in field_names[:5]:  # 最多显示 5 个字段
        safe_name, _ = _sanitize_field_name(name)
        lines.append(f'        "{name}": item.{safe_name},')
    return "\n".join(lines) if lines else "        # 在这里定义输出字段"


def _execute_transform(
    input_path: Path,
    config_path: Path,
    output_override: Optional[str],
    num: Optional[int],
) -> None:
    """执行数据转换（默认流式处理）"""
    print(f"📂 加载配置: {config_path}")

    # 动态加载配置文件
    try:
        config_ns = _load_config(config_path)
    except Exception as e:
        print(f"错误: 无法加载配置文件 - {e}")
        return

    # 获取 transform 函数
    if "transform" not in config_ns:
        print("错误: 配置文件中未定义 transform 函数")
        return

    transform_func = config_ns["transform"]

    # 获取输出路径
    output_path = output_override or config_ns.get("output", "output.jsonl")

    # 对于 JSONL 文件使用流式处理
    if _is_streaming_supported(input_path):
        print(f"📊 流式加载: {input_path}")
        print("🔄 执行转换...")
        try:
            # 包装转换函数以支持属性访问（配置文件中定义的 Item 类）
            def wrapped_transform(item):
                return transform_func(DictWrapper(item))

            st = load_stream(str(input_path))
            if num:
                st = st.head(num)
            count = st.transform(wrapped_transform).save(output_path)
            print(f"💾 保存结果: {output_path}")
            print(f"\n✅ 完成! 已转换 {count} 条数据到 {output_path}")
        except Exception as e:
            print(f"错误: 转换失败 - {e}")
            import traceback

            traceback.print_exc()
        return

    # 非 JSONL 文件使用传统方式
    print(f"📊 加载数据: {input_path}")
    try:
        dt = DataTransformer.load(str(input_path))
    except Exception as e:
        print(f"错误: 无法读取文件 - {e}")
        return

    total = len(dt)
    if num:
        dt = DataTransformer(dt.data[:num])
        print(f"   处理前 {len(dt)}/{total} 条数据")
    else:
        print(f"   共 {total} 条数据")

    # 执行转换（使用 Core 的 to 方法，自动支持属性访问）
    print("🔄 执行转换...")
    try:
        results = dt.to(transform_func)
    except Exception as e:
        print(f"错误: 转换失败 - {e}")
        import traceback

        traceback.print_exc()
        return

    # 保存结果
    print(f"💾 保存结果: {output_path}")
    try:
        save_data(results, output_path)
    except Exception as e:
        print(f"错误: 无法保存文件 - {e}")
        return

    print(f"\n✅ 完成! 已转换 {len(results)} 条数据到 {output_path}")


def _execute_preset_transform(
    input_path: Path,
    preset_name: str,
    output_override: Optional[str],
    num: Optional[int],
) -> None:
    """使用预设模板执行转换（默认流式处理）"""
    print(f"📂 使用预设: {preset_name}")

    # 获取预设函数
    try:
        transform_func = get_preset(preset_name)
    except ValueError as e:
        print(f"错误: {e}")
        print(f"可用预设: {', '.join(list_presets())}")
        return

    output_path = output_override or f"{input_path.stem}_{preset_name}.jsonl"

    # 检查输入输出是否相同
    input_resolved = input_path.resolve()
    output_resolved = Path(output_path).resolve()
    use_temp_file = input_resolved == output_resolved

    # 对于 JSONL 文件使用流式处理
    if _is_streaming_supported(input_path):
        print(f"📊 流式加载: {input_path}")
        print("🔄 执行转换...")

        # 如果输入输出相同，使用临时文件
        if use_temp_file:
            print("⚠ 检测到输出文件与输入文件相同，将使用临时文件")
            temp_fd, temp_path = tempfile.mkstemp(
                suffix=output_resolved.suffix,
                prefix=".tmp_",
                dir=output_resolved.parent,
            )
            os.close(temp_fd)
            actual_output = temp_path
        else:
            actual_output = output_path

        try:
            # 包装转换函数以支持属性访问
            def wrapped_transform(item):
                return transform_func(DictWrapper(item))

            st = load_stream(str(input_path))
            if num:
                st = st.head(num)
            count = st.transform(wrapped_transform).save(actual_output)

            # 如果使用了临时文件，移动到目标位置
            if use_temp_file:
                shutil.move(temp_path, output_path)

            print(f"💾 保存结果: {output_path}")
            print(f"\n✅ 完成! 已转换 {count} 条数据到 {output_path}")
        except Exception as e:
            # 清理临时文件
            if use_temp_file and os.path.exists(temp_path):
                os.unlink(temp_path)
            print(f"错误: 转换失败 - {e}")
            import traceback

            traceback.print_exc()
        return

    # 非 JSONL 文件使用传统方式
    print(f"📊 加载数据: {input_path}")
    try:
        dt = DataTransformer.load(str(input_path))
    except Exception as e:
        print(f"错误: 无法读取文件 - {e}")
        return

    total = len(dt)
    if num:
        dt = DataTransformer(dt.data[:num])
        print(f"   处理前 {len(dt)}/{total} 条数据")
    else:
        print(f"   共 {total} 条数据")

    # 执行转换
    print("🔄 执行转换...")
    try:
        results = dt.to(transform_func)
    except Exception as e:
        print(f"错误: 转换失败 - {e}")
        import traceback

        traceback.print_exc()
        return

    # 保存结果
    print(f"💾 保存结果: {output_path}")
    try:
        save_data(results, output_path)
    except Exception as e:
        print(f"错误: 无法保存文件 - {e}")
        return

    print(f"\n✅ 完成! 已转换 {len(results)} 条数据到 {output_path}")


def _load_config(config_path: Path) -> Dict[str, Any]:
    """动态加载 Python 配置文件"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("dt_config", config_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return {name: getattr(module, name) for name in dir(module) if not name.startswith("_")}


# ============ Dedupe Command ============


def dedupe(
    filename: str,
    key: Optional[str] = None,
    similar: Optional[float] = None,
    output: Optional[str] = None,
) -> None:
    """
    数据去重。

    支持两种模式：
    1. 精确去重（默认）：完全相同的数据才去重
    2. 相似度去重：使用 MinHash+LSH 算法，相似度超过阈值则去重

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        key: 去重依据字段，多个字段用逗号分隔。不指定则全量去重
        similar: 相似度阈值（0-1），指定后启用相似度去重模式，需要指定 --key
        output: 输出文件路径，不指定则覆盖原文件

    Examples:
        dt dedupe data.jsonl                       # 全量精确去重
        dt dedupe data.jsonl --key=text            # 按 text 字段精确去重
        dt dedupe data.jsonl --key=user,timestamp  # 按多字段组合精确去重
        dt dedupe data.jsonl --key=text --similar=0.8   # 相似度去重
        dt dedupe data.jsonl --output=clean.jsonl  # 指定输出文件
    """
    filepath = Path(filename)

    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
        return

    # 相似度去重模式必须指定 key
    if similar is not None and not key:
        print("错误: 相似度去重需要指定 --key 参数")
        return

    if similar is not None and (similar <= 0 or similar > 1):
        print("错误: --similar 参数必须在 0-1 之间")
        return

    # 加载数据
    print(f"📊 加载数据: {filepath}")
    try:
        dt = DataTransformer.load(str(filepath))
    except Exception as e:
        print(f"错误: 无法读取文件 - {e}")
        return

    original_count = len(dt)
    print(f"   共 {original_count} 条数据")

    # 执行去重
    if similar is not None:
        # 相似度去重模式
        print(f"🔑 相似度去重: 字段={key}, 阈值={similar}")
        print("🔄 执行去重（MinHash+LSH）...")
        try:
            result = dt.dedupe_similar(key, threshold=similar)
        except ImportError as e:
            print(f"错误: {e}")
            return
    else:
        # 精确去重模式
        dedupe_key: Any = None
        if key:
            keys = [k.strip() for k in key.split(",")]
            if len(keys) == 1:
                dedupe_key = keys[0]
                print(f"🔑 按字段精确去重: {dedupe_key}")
            else:
                dedupe_key = keys
                print(f"🔑 按多字段组合精确去重: {', '.join(dedupe_key)}")
        else:
            print("🔑 全量精确去重")

        print("🔄 执行去重...")
        result = dt.dedupe(dedupe_key)

    dedupe_count = len(result)
    removed_count = original_count - dedupe_count

    # 保存结果
    output_path = output or str(filepath)
    print(f"💾 保存结果: {output_path}")
    try:
        result.save(output_path)
    except Exception as e:
        print(f"错误: 无法保存文件 - {e}")
        return

    print(f"\n✅ 完成! 去除 {removed_count} 条重复数据，剩余 {dedupe_count} 条")


# ============ Concat Command ============


def concat(
    *files: str,
    output: Optional[str] = None,
    strict: bool = False,
) -> None:
    """
    拼接多个数据文件（流式处理，内存占用 O(1)）。

    Args:
        *files: 输入文件路径列表，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        output: 输出文件路径，必须指定
        strict: 严格模式，字段必须完全一致，否则报错

    Examples:
        dt concat a.jsonl b.jsonl -o merged.jsonl
        dt concat data1.csv data2.csv data3.csv -o all.jsonl
        dt concat a.jsonl b.jsonl --strict -o merged.jsonl
    """
    if len(files) < 2:
        print("错误: 至少需要两个文件")
        return

    if not output:
        print("错误: 必须指定输出文件 (-o/--output)")
        return

    # 验证所有文件
    file_paths = []
    for f in files:
        filepath = Path(f).resolve()  # 使用绝对路径进行比较
        if not filepath.exists():
            print(f"错误: 文件不存在 - {f}")
            return
        if not _check_file_format(filepath):
            return
        file_paths.append(filepath)

    # 检查输出文件是否与输入文件冲突
    output_path = Path(output).resolve()
    use_temp_file = output_path in file_paths
    if use_temp_file:
        print("⚠ 检测到输出文件与输入文件相同，将使用临时文件")

    # 流式分析字段（只读取每个文件的第一行）
    print("📊 文件字段分析:")
    file_fields = []  # [(filepath, fields)]

    for filepath in file_paths:
        try:
            # 只读取第一行来获取字段（根据格式选择加载方式）
            if _is_streaming_supported(filepath):
                first_row = load_stream(str(filepath)).head(1).collect()
            else:
                # 非流式格式（如 .json, .xlsx）使用全量加载
                data = load_data(str(filepath))
                first_row = data[:1] if data else []
            if not first_row:
                print(f"警告: 文件为空 - {filepath}")
                fields = set()
            else:
                fields = set(first_row[0].keys())
        except Exception as e:
            print(f"错误: 无法读取文件 {filepath} - {e}")
            return

        file_fields.append((filepath, fields))
        fields_str = ", ".join(sorted(fields)) if fields else "(空)"
        print(f"   {filepath.name}: {fields_str}")

    # 分析字段差异
    all_fields = set()
    common_fields = None
    for _, fields in file_fields:
        all_fields.update(fields)
        if common_fields is None:
            common_fields = fields.copy()
        else:
            common_fields &= fields

    common_fields = common_fields or set()
    diff_fields = all_fields - common_fields

    if diff_fields:
        if strict:
            print(f"\n❌ 严格模式: 字段不一致")
            print(f"   共同字段: {', '.join(sorted(common_fields)) or '(无)'}")
            print(f"   差异字段: {', '.join(sorted(diff_fields))}")
            return
        else:
            print(f"\n⚠ 字段差异: {', '.join(sorted(diff_fields))} 仅在部分文件中存在")

    # 流式拼接
    print("\n🔄 流式拼接...")

    # 如果输出文件与输入文件冲突，使用临时文件（在输出文件同一目录下）
    if use_temp_file:
        output_dir = output_path.parent
        temp_fd, temp_path = tempfile.mkstemp(
            suffix=output_path.suffix,
            prefix=".tmp_",
            dir=output_dir,
        )
        os.close(temp_fd)
        actual_output = temp_path
        print(f"💾 写入临时文件: {temp_path}")
    else:
        actual_output = output
        print(f"💾 保存结果: {output}")

    try:
        total_count = _concat_streaming(file_paths, actual_output)

        # 如果使用了临时文件，重命名为目标文件
        if use_temp_file:
            shutil.move(temp_path, output)
            print(f"💾 移动到目标文件: {output}")
    except Exception as e:
        # 清理临时文件
        if use_temp_file and os.path.exists(temp_path):
            os.unlink(temp_path)
        print(f"错误: 拼接失败 - {e}")
        return

    file_count = len(files)
    print(f"\n✅ 完成! 已合并 {file_count} 个文件，共 {total_count} 条数据到 {output}")


def _concat_streaming(file_paths: List[Path], output: str) -> int:
    """流式拼接多个文件"""
    from ..streaming import (
        StreamingTransformer,
        _stream_arrow,
        _stream_csv,
        _stream_jsonl,
        _stream_parquet,
    )

    def generator():
        for filepath in file_paths:
            ext = filepath.suffix.lower()
            if ext == ".jsonl":
                yield from _stream_jsonl(str(filepath))
            elif ext == ".csv":
                yield from _stream_csv(str(filepath))
            elif ext == ".parquet":
                yield from _stream_parquet(str(filepath))
            elif ext in (".arrow", ".feather"):
                yield from _stream_arrow(str(filepath))
            elif ext in (".json",):
                # JSON 需要全量加载
                data = load_data(str(filepath))
                yield from data
            elif ext in (".xlsx", ".xls"):
                # Excel 需要全量加载
                data = load_data(str(filepath))
                yield from data
            else:
                yield from _stream_jsonl(str(filepath))

    st = StreamingTransformer(generator())
    return st.save(output, show_progress=True)


# ============ Stats Command ============


def stats(
    filename: str,
    top: int = 10,
) -> None:
    """
    显示数据文件的统计信息（类似 pandas df.info() + df.describe()）。

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        top: 显示频率最高的前 N 个值，默认 10

    Examples:
        dt stats data.jsonl
        dt stats data.csv --top=5
    """
    filepath = Path(filename)

    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
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

    对于简单类型直接比较，对于 list/dict 使用 hash 节省内存。
    """
    if field_type in ("list", "dict"):
        # 复杂类型：使用 orjson 序列化后计算 hash
        import hashlib

        import orjson

        seen = set()
        for v in values:
            h = hashlib.md5(orjson.dumps(v, option=orjson.OPT_SORT_KEYS)).digest()
            seen.add(h)
        return len(seen)
    else:
        # 简单类型：直接比较
        return len(set(values))


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
        print(f"📊 数据概览")
        print(f"{'=' * 50}")
        print(f"文件: {filename}")
        print(f"总数: {total:,} 条")
        print(f"字段: {len(field_stats)} 个")

        print(f"\n{'=' * 50}")
        print(f"📋 字段统计")
        print(f"{'=' * 50}")
        print(f"{'字段':<20} {'类型':<8} {'非空率':<8} {'唯一值':<8}")
        print("-" * 50)

        for stat in field_stats:
            non_null_rate = f"{stat['non_null'] / total * 100:.0f}%"
            unique = str(stat.get("unique", "-"))
            print(f"{stat['field']:<20} {stat['type']:<8} {non_null_rate:<8} {unique:<8}")


# ============ Clean Command ============


def clean(
    filename: str,
    drop_empty: Optional[str] = None,
    min_len: Optional[str] = None,
    max_len: Optional[str] = None,
    keep: Optional[str] = None,
    drop: Optional[str] = None,
    strip: bool = False,
    output: Optional[str] = None,
) -> None:
    """
    数据清洗（默认流式处理）。

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        drop_empty: 删除空值记录
            - 不带值：删除任意字段为空的记录
            - 指定字段：删除指定字段为空的记录（逗号分隔）
        min_len: 最小长度过滤，格式 "字段:长度"（如 text:10）
        max_len: 最大长度过滤，格式 "字段:长度"（如 text:1000）
        keep: 只保留指定字段（逗号分隔）
        drop: 删除指定字段（逗号分隔）
        strip: 去除所有字符串字段的首尾空白
        output: 输出文件路径，不指定则覆盖原文件

    Examples:
        dt clean data.jsonl --drop-empty                    # 删除任意空值记录
        dt clean data.jsonl --drop-empty=text,answer        # 删除指定字段为空的记录
        dt clean data.jsonl --min-len=text:10               # text 字段最少 10 字符
        dt clean data.jsonl --max-len=text:1000             # text 字段最多 1000 字符
        dt clean data.jsonl --keep=question,answer          # 只保留这些字段
        dt clean data.jsonl --drop=metadata,timestamp       # 删除这些字段
        dt clean data.jsonl --strip                         # 去除字符串首尾空白
        dt clean data.jsonl --drop-empty --strip -o out.jsonl
    """
    filepath = Path(filename)

    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
        return

    # 解析参数
    min_len_field, min_len_value = _parse_len_param(min_len) if min_len else (None, None)
    max_len_field, max_len_value = _parse_len_param(max_len) if max_len else (None, None)
    keep_fields = _parse_field_list(keep) if keep else None
    drop_fields_set = set(_parse_field_list(drop)) if drop else None
    keep_set = set(keep_fields) if keep_fields else None

    # 构建清洗配置
    empty_fields = None
    if drop_empty is not None:
        if drop_empty == "" or drop_empty is True:
            print("🔄 删除任意字段为空的记录...")
            empty_fields = []
        else:
            empty_fields = _parse_field_list(drop_empty)
            print(f"🔄 删除字段为空的记录: {', '.join(empty_fields)}")

    if strip:
        print("🔄 去除字符串首尾空白...")
    if min_len_field:
        print(f"🔄 过滤 {min_len_field} 长度 < {min_len_value} 的记录...")
    if max_len_field:
        print(f"🔄 过滤 {max_len_field} 长度 > {max_len_value} 的记录...")
    if keep_fields:
        print(f"🔄 只保留字段: {', '.join(keep_fields)}")
    if drop_fields_set:
        print(f"🔄 删除字段: {', '.join(drop_fields_set)}")

    output_path = output or str(filepath)

    # 检查输入输出是否相同（流式处理需要临时文件）
    input_resolved = filepath.resolve()
    output_resolved = Path(output_path).resolve()
    use_temp_file = input_resolved == output_resolved

    # 对于 JSONL 文件使用流式处理
    if _is_streaming_supported(filepath):
        print(f"📊 流式加载: {filepath}")

        # 如果输入输出相同，使用临时文件
        if use_temp_file:
            print("⚠ 检测到输出文件与输入文件相同，将使用临时文件")
            temp_fd, temp_path = tempfile.mkstemp(
                suffix=output_resolved.suffix,
                prefix=".tmp_",
                dir=output_resolved.parent,
            )
            os.close(temp_fd)
            actual_output = temp_path
        else:
            actual_output = output_path

        try:
            count = _clean_streaming(
                str(filepath),
                actual_output,
                strip=strip,
                empty_fields=empty_fields,
                min_len_field=min_len_field,
                min_len_value=min_len_value,
                max_len_field=max_len_field,
                max_len_value=max_len_value,
                keep_set=keep_set,
                drop_fields_set=drop_fields_set,
            )

            # 如果使用了临时文件，移动到目标位置
            if use_temp_file:
                shutil.move(temp_path, output_path)

            print(f"💾 保存结果: {output_path}")
            print(f"\n✅ 完成! 清洗后 {count} 条数据")
        except Exception as e:
            # 清理临时文件
            if use_temp_file and os.path.exists(temp_path):
                os.unlink(temp_path)
            print(f"错误: 清洗失败 - {e}")
            import traceback

            traceback.print_exc()
        return

    # 非 JSONL 文件使用传统方式
    print(f"📊 加载数据: {filepath}")
    try:
        dt = DataTransformer.load(str(filepath))
    except Exception as e:
        print(f"错误: 无法读取文件 - {e}")
        return

    original_count = len(dt)
    print(f"   共 {original_count} 条数据")

    # 单次遍历执行所有清洗操作
    data, step_stats = _clean_data_single_pass(
        dt.data,
        strip=strip,
        empty_fields=empty_fields,
        min_len_field=min_len_field,
        min_len_value=min_len_value,
        max_len_field=max_len_field,
        max_len_value=max_len_value,
        keep_fields=keep_fields,
        drop_fields=drop_fields_set,
    )

    # 保存结果
    final_count = len(data)
    print(f"💾 保存结果: {output_path}")

    try:
        save_data(data, output_path)
    except Exception as e:
        print(f"错误: 无法保存文件 - {e}")
        return

    # 打印统计
    removed_count = original_count - final_count
    print(f"\n✅ 完成!")
    print(f"   原始: {original_count} 条 -> 清洗后: {final_count} 条 (删除 {removed_count} 条)")
    if step_stats:
        print(f"   步骤: {' | '.join(step_stats)}")


def _parse_len_param(param: str) -> tuple:
    """解析长度参数，格式 'field:length'"""
    if ":" not in param:
        raise ValueError(f"长度参数格式错误: {param}，应为 '字段:长度'")
    parts = param.split(":", 1)
    field = parts[0].strip()
    try:
        length = int(parts[1].strip())
    except ValueError:
        raise ValueError(f"长度必须是整数: {parts[1]}")
    return field, length


def _parse_field_list(value: Any) -> List[str]:
    """解析字段列表参数（处理 fire 将逗号分隔的值解析为元组的情况）"""
    if isinstance(value, (list, tuple)):
        return [str(f).strip() for f in value]
    elif isinstance(value, str):
        return [f.strip() for f in value.split(",")]
    else:
        return [str(value)]


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
    """获取值的长度"""
    if value is None:
        return 0
    if isinstance(value, (str, list, dict)):
        return len(value)
    return len(str(value))


def _clean_data_single_pass(
    data: List[Dict],
    strip: bool = False,
    empty_fields: Optional[List[str]] = None,
    min_len_field: Optional[str] = None,
    min_len_value: Optional[int] = None,
    max_len_field: Optional[str] = None,
    max_len_value: Optional[int] = None,
    keep_fields: Optional[List[str]] = None,
    drop_fields: Optional[set] = None,
) -> tuple:
    """
    单次遍历执行所有清洗操作。

    Args:
        data: 原始数据列表
        strip: 是否去除字符串首尾空白
        empty_fields: 检查空值的字段列表，空列表表示检查所有字段，None 表示不检查
        min_len_field: 最小长度检查的字段
        min_len_value: 最小长度值
        max_len_field: 最大长度检查的字段
        max_len_value: 最大长度值
        keep_fields: 只保留的字段列表
        drop_fields: 要删除的字段集合

    Returns:
        (清洗后的数据, 统计信息列表)
    """
    result = []
    stats = {
        "drop_empty": 0,
        "min_len": 0,
        "max_len": 0,
    }

    # 预先计算 keep_fields 集合（如果有的话）
    keep_set = set(keep_fields) if keep_fields else None

    for item in data:
        # 1. strip 处理（在过滤前执行，这样空值检测更准确）
        if strip:
            item = {k: v.strip() if isinstance(v, str) else v for k, v in item.items()}

        # 2. 空值过滤
        if empty_fields is not None:
            if len(empty_fields) == 0:
                # 检查所有字段
                if any(_is_empty_value(v) for v in item.values()):
                    stats["drop_empty"] += 1
                    continue
            else:
                # 检查指定字段
                if any(_is_empty_value(item.get(f)) for f in empty_fields):
                    stats["drop_empty"] += 1
                    continue

        # 3. 最小长度过滤
        if min_len_field is not None:
            if _get_value_len(item.get(min_len_field, "")) < min_len_value:
                stats["min_len"] += 1
                continue

        # 4. 最大长度过滤
        if max_len_field is not None:
            if _get_value_len(item.get(max_len_field, "")) > max_len_value:
                stats["max_len"] += 1
                continue

        # 5. 字段管理（keep/drop）
        if keep_set is not None:
            item = {k: v for k, v in item.items() if k in keep_set}
        elif drop_fields is not None:
            item = {k: v for k, v in item.items() if k not in drop_fields}

        result.append(item)

    # 构建统计信息字符串列表
    step_stats = []
    if strip:
        step_stats.append("strip")
    if stats["drop_empty"] > 0:
        step_stats.append(f"drop-empty: -{stats['drop_empty']}")
    if stats["min_len"] > 0:
        step_stats.append(f"min-len: -{stats['min_len']}")
    if stats["max_len"] > 0:
        step_stats.append(f"max-len: -{stats['max_len']}")
    if keep_fields:
        step_stats.append(f"keep: {len(keep_fields)} 字段")
    if drop_fields:
        step_stats.append(f"drop: {len(drop_fields)} 字段")

    return result, step_stats


def _clean_streaming(
    input_path: str,
    output_path: str,
    strip: bool = False,
    empty_fields: Optional[List[str]] = None,
    min_len_field: Optional[str] = None,
    min_len_value: Optional[int] = None,
    max_len_field: Optional[str] = None,
    max_len_value: Optional[int] = None,
    keep_set: Optional[set] = None,
    drop_fields_set: Optional[set] = None,
) -> int:
    """
    流式清洗数据。

    Returns:
        处理后的数据条数
    """

    def clean_filter(item: Dict) -> bool:
        """过滤函数：返回 True 保留，False 过滤"""
        # 空值过滤
        if empty_fields is not None:
            if len(empty_fields) == 0:
                if any(_is_empty_value(v) for v in item.values()):
                    return False
            else:
                if any(_is_empty_value(item.get(f)) for f in empty_fields):
                    return False

        # 最小长度过滤
        if min_len_field is not None:
            if _get_value_len(item.get(min_len_field, "")) < min_len_value:
                return False

        # 最大长度过滤
        if max_len_field is not None:
            if _get_value_len(item.get(max_len_field, "")) > max_len_value:
                return False

        return True

    def clean_transform(item: Dict) -> Dict:
        """转换函数：strip + 字段管理"""
        # strip 处理
        if strip:
            item = {k: v.strip() if isinstance(v, str) else v for k, v in item.items()}

        # 字段管理
        if keep_set is not None:
            item = {k: v for k, v in item.items() if k in keep_set}
        elif drop_fields_set is not None:
            item = {k: v for k, v in item.items() if k not in drop_fields_set}

        return item

    # 构建流式处理链
    st = load_stream(input_path)

    # 如果需要 strip，先执行 strip 转换（在过滤之前，这样空值检测更准确）
    if strip:
        st = st.transform(
            lambda x: {k: v.strip() if isinstance(v, str) else v for k, v in x.items()}
        )

    # 执行过滤
    if empty_fields is not None or min_len_field is not None or max_len_field is not None:
        st = st.filter(clean_filter)

    # 执行字段管理（如果没有 strip，也需要在这里处理）
    if keep_set is not None or drop_fields_set is not None:

        def field_transform(item):
            if keep_set is not None:
                return {k: v for k, v in item.items() if k in keep_set}
            elif drop_fields_set is not None:
                return {k: v for k, v in item.items() if k not in drop_fields_set}
            return item

        st = st.transform(field_transform)

    return st.save(output_path)


# ============ Run Command ============


def run(
    config: str,
    input: Optional[str] = None,
    output: Optional[str] = None,
) -> None:
    """
    执行 Pipeline 配置文件。

    Args:
        config: Pipeline YAML 配置文件路径
        input: 输入文件路径（覆盖配置中的 input）
        output: 输出文件路径（覆盖配置中的 output）

    Examples:
        dt run pipeline.yaml
        dt run pipeline.yaml --input=new_data.jsonl
        dt run pipeline.yaml --input=data.jsonl --output=result.jsonl
    """
    config_path = Path(config)

    if not config_path.exists():
        print(f"错误: 配置文件不存在 - {config}")
        return

    if config_path.suffix.lower() not in (".yaml", ".yml"):
        print(f"错误: 配置文件必须是 YAML 格式 (.yaml 或 .yml)")
        return

    # 验证配置
    errors = validate_pipeline(config)
    if errors:
        print("❌ 配置文件验证失败:")
        for err in errors:
            print(f"   - {err}")
        return

    # 执行 pipeline
    try:
        run_pipeline(config, input_file=input, output_file=output, verbose=True)
    except Exception as e:
        print(f"错误: {e}")
        import traceback

        traceback.print_exc()


# ============ Token Stats Command ============


def token_stats(
    filename: str,
    field: str = "messages",
    model: str = "cl100k_base",
    detailed: bool = False,
) -> None:
    """
    统计数据集的 Token 信息。

    Args:
        filename: 输入文件路径
        field: 要统计的字段（默认 messages）
        model: 分词器: cl100k_base (默认), qwen2.5, llama3, gpt-4 等
        detailed: 是否显示详细统计

    Examples:
        dt token-stats data.jsonl
        dt token-stats data.jsonl --field=text --model=qwen2.5
        dt token-stats data.jsonl --detailed
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
    print(f"   共 {total} 条数据")
    print(f"🔢 统计 Token (模型: {model}, 字段: {field})...")

    # 检查字段类型并选择合适的统计方法
    sample = data[0]
    field_value = sample.get(field)

    try:
        if isinstance(field_value, list) and field_value and isinstance(field_value[0], dict):
            # messages 格式
            from ..tokenizers import messages_token_stats

            stats = messages_token_stats(data, messages_field=field, model=model)
            _print_messages_token_stats(stats, detailed)
        else:
            # 普通文本字段
            from ..tokenizers import token_stats as compute_token_stats

            stats = compute_token_stats(data, fields=field, model=model)
            _print_text_token_stats(stats, detailed)
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
        overview = (
            f"[bold]总样本数:[/bold] {stats['count']:,}\n"
            f"[bold]总 Token:[/bold] {stats['total_tokens']:,}\n"
            f"[bold]平均 Token:[/bold] {stats['avg_tokens']:,}\n"
            f"[bold]中位数:[/bold] {stats['median_tokens']:,}\n"
            f"[bold]范围:[/bold] {stats['min_tokens']:,} - {stats['max_tokens']:,}"
        )
        console.print(Panel(overview, title="📊 Token 统计概览", expand=False))

        if detailed:
            # 详细统计
            table = Table(title="📋 分角色统计")
            table.add_column("角色", style="cyan")
            table.add_column("Token 数", justify="right")
            table.add_column("占比", justify="right")

            total = stats["total_tokens"]
            for role, key in [
                ("User", "user_tokens"),
                ("Assistant", "assistant_tokens"),
                ("System", "system_tokens"),
            ]:
                tokens = stats.get(key, 0)
                pct = tokens / total * 100 if total > 0 else 0
                table.add_row(role, f"{tokens:,}", f"{pct:.1f}%")

            console.print(table)
            console.print(f"\n平均对话轮数: {stats.get('avg_turns', 0)}")

    except ImportError:
        # 没有 rich，使用普通打印
        print(f"\n{'=' * 40}")
        print("📊 Token 统计概览")
        print(f"{'=' * 40}")
        print(f"总样本数: {stats['count']:,}")
        print(f"总 Token: {stats['total_tokens']:,}")
        print(f"平均 Token: {stats['avg_tokens']:,}")
        print(f"中位数: {stats['median_tokens']:,}")
        print(f"范围: {stats['min_tokens']:,} - {stats['max_tokens']:,}")

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

        console = Console()

        overview = (
            f"[bold]总样本数:[/bold] {stats['count']:,}\n"
            f"[bold]总 Token:[/bold] {stats['total_tokens']:,}\n"
            f"[bold]平均 Token:[/bold] {stats['avg_tokens']:.1f}\n"
            f"[bold]中位数:[/bold] {stats['median_tokens']:,}\n"
            f"[bold]范围:[/bold] {stats['min_tokens']:,} - {stats['max_tokens']:,}"
        )
        console.print(Panel(overview, title="📊 Token 统计", expand=False))

    except ImportError:
        print(f"\n{'=' * 40}")
        print("📊 Token 统计")
        print(f"{'=' * 40}")
        print(f"总样本数: {stats['count']:,}")
        print(f"总 Token: {stats['total_tokens']:,}")
        print(f"平均 Token: {stats['avg_tokens']:.1f}")
        print(f"中位数: {stats['median_tokens']:,}")
        print(f"范围: {stats['min_tokens']:,} - {stats['max_tokens']:,}")


# ============ Diff Command ============


def diff(
    file1: str,
    file2: str,
    key: Optional[str] = None,
    output: Optional[str] = None,
) -> None:
    """
    对比两个数据集的差异。

    Args:
        file1: 第一个文件路径
        file2: 第二个文件路径
        key: 用于匹配的键字段（可选）
        output: 差异报告输出路径（可选）

    Examples:
        dt diff v1/train.jsonl v2/train.jsonl
        dt diff a.jsonl b.jsonl --key=id
        dt diff a.jsonl b.jsonl --output=diff_report.json
    """
    path1 = Path(file1)
    path2 = Path(file2)

    # 验证文件
    for p, name in [(path1, "file1"), (path2, "file2")]:
        if not p.exists():
            print(f"错误: 文件不存在 - {p}")
            return
        if not _check_file_format(p):
            return

    # 加载数据
    print(f"📊 加载数据...")
    try:
        data1 = load_data(str(path1))
        data2 = load_data(str(path2))
    except Exception as e:
        print(f"错误: 无法读取文件 - {e}")
        return

    print(f"   文件1: {path1.name} ({len(data1)} 条)")
    print(f"   文件2: {path2.name} ({len(data2)} 条)")

    # 计算差异
    print("🔍 计算差异...")
    diff_result = _compute_diff(data1, data2, key)

    # 打印差异报告
    _print_diff_report(diff_result, path1.name, path2.name)

    # 保存报告
    if output:
        print(f"\n💾 保存报告: {output}")
        save_data([diff_result], output)


def _compute_diff(
    data1: List[Dict],
    data2: List[Dict],
    key: Optional[str] = None,
) -> Dict[str, Any]:
    """计算两个数据集的差异"""
    result = {
        "summary": {
            "file1_count": len(data1),
            "file2_count": len(data2),
            "added": 0,
            "removed": 0,
            "modified": 0,
            "unchanged": 0,
        },
        "field_changes": {},
        "details": {
            "added": [],
            "removed": [],
            "modified": [],
        },
    }

    if key:
        # 基于 key 的精确匹配
        dict1 = {item.get(key): item for item in data1 if item.get(key) is not None}
        dict2 = {item.get(key): item for item in data2 if item.get(key) is not None}

        keys1 = set(dict1.keys())
        keys2 = set(dict2.keys())

        # 新增
        added_keys = keys2 - keys1
        result["summary"]["added"] = len(added_keys)
        result["details"]["added"] = [dict2[k] for k in list(added_keys)[:10]]  # 最多显示 10 条

        # 删除
        removed_keys = keys1 - keys2
        result["summary"]["removed"] = len(removed_keys)
        result["details"]["removed"] = [dict1[k] for k in list(removed_keys)[:10]]

        # 修改/未变
        common_keys = keys1 & keys2
        for k in common_keys:
            if dict1[k] == dict2[k]:
                result["summary"]["unchanged"] += 1
            else:
                result["summary"]["modified"] += 1
                if len(result["details"]["modified"]) < 10:
                    result["details"]["modified"].append(
                        {
                            "key": k,
                            "before": dict1[k],
                            "after": dict2[k],
                        }
                    )
    else:
        # 基于哈希的比较
        def _hash_item(item):
            return orjson.dumps(item, option=orjson.OPT_SORT_KEYS)

        set1 = {_hash_item(item) for item in data1}
        set2 = {_hash_item(item) for item in data2}

        added = set2 - set1
        removed = set1 - set2
        unchanged = set1 & set2

        result["summary"]["added"] = len(added)
        result["summary"]["removed"] = len(removed)
        result["summary"]["unchanged"] = len(unchanged)

        # 详情
        result["details"]["added"] = [orjson.loads(h) for h in list(added)[:10]]
        result["details"]["removed"] = [orjson.loads(h) for h in list(removed)[:10]]

    # 字段变化分析
    fields1 = set()
    fields2 = set()
    for item in data1[:1000]:  # 采样分析
        fields1.update(item.keys())
    for item in data2[:1000]:
        fields2.update(item.keys())

    result["field_changes"] = {
        "added_fields": list(fields2 - fields1),
        "removed_fields": list(fields1 - fields2),
        "common_fields": list(fields1 & fields2),
    }

    return result


def _print_diff_report(diff_result: Dict[str, Any], name1: str, name2: str) -> None:
    """打印差异报告"""
    summary = diff_result["summary"]
    field_changes = diff_result["field_changes"]

    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console()

        # 概览
        overview = (
            f"[bold]{name1}:[/bold] {summary['file1_count']:,} 条\n"
            f"[bold]{name2}:[/bold] {summary['file2_count']:,} 条\n"
            f"\n"
            f"[green]+ 新增:[/green] {summary['added']:,} 条\n"
            f"[red]- 删除:[/red] {summary['removed']:,} 条\n"
            f"[yellow]~ 修改:[/yellow] {summary['modified']:,} 条\n"
            f"[dim]= 未变:[/dim] {summary['unchanged']:,} 条"
        )
        console.print(Panel(overview, title="📊 差异概览", expand=False))

        # 字段变化
        if field_changes["added_fields"] or field_changes["removed_fields"]:
            console.print("\n[bold]📋 字段变化:[/bold]")
            if field_changes["added_fields"]:
                console.print(
                    f"  [green]+ 新增字段:[/green] {', '.join(field_changes['added_fields'])}"
                )
            if field_changes["removed_fields"]:
                console.print(
                    f"  [red]- 删除字段:[/red] {', '.join(field_changes['removed_fields'])}"
                )

    except ImportError:
        print(f"\n{'=' * 50}")
        print("📊 差异概览")
        print(f"{'=' * 50}")
        print(f"{name1}: {summary['file1_count']:,} 条")
        print(f"{name2}: {summary['file2_count']:,} 条")
        print()
        print(f"+ 新增: {summary['added']:,} 条")
        print(f"- 删除: {summary['removed']:,} 条")
        print(f"~ 修改: {summary['modified']:,} 条")
        print(f"= 未变: {summary['unchanged']:,} 条")

        if field_changes["added_fields"] or field_changes["removed_fields"]:
            print(f"\n📋 字段变化:")
            if field_changes["added_fields"]:
                print(f"  + 新增字段: {', '.join(field_changes['added_fields'])}")
            if field_changes["removed_fields"]:
                print(f"  - 删除字段: {', '.join(field_changes['removed_fields'])}")


# ============ History Command ============


def history(
    filename: str,
    json: bool = False,
) -> None:
    """
    显示数据文件的血缘历史。

    Args:
        filename: 数据文件路径
        json: 以 JSON 格式输出

    Examples:
        dt history data.jsonl
        dt history data.jsonl --json
    """
    filepath = Path(filename)

    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not has_lineage(str(filepath)):
        print(f"文件 {filename} 没有血缘记录")
        print("\n提示: 使用 track_lineage=True 加载数据，并在保存时使用 lineage=True 来记录血缘")
        print("示例:")
        print("  dt = DataTransformer.load('data.jsonl', track_lineage=True)")
        print("  dt.filter(...).transform(...).save('output.jsonl', lineage=True)")
        return

    if json:
        # JSON 格式输出
        chain = get_lineage_chain(str(filepath))
        output = [record.to_dict() for record in chain]
        print(orjson.dumps(output, option=orjson.OPT_INDENT_2).decode("utf-8"))
    else:
        # 格式化报告
        report = format_lineage_report(str(filepath))
        print(report)
