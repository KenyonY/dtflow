"""
CLI 命令实现
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from ..core import DataTransformer, DictWrapper
from ..presets import get_preset, list_presets
from ..storage.io import load_data, save_data, sample_file


# 支持的文件格式
SUPPORTED_FORMATS = {".csv", ".jsonl", ".json", ".xlsx", ".xls", ".parquet", ".arrow", ".feather"}


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
    sample_type: Literal["random", "head", "tail"] = "head",
    output: Optional[str] = None,
    seed: Optional[int] = None,
    by: Optional[str] = None,
    uniform: bool = False,
) -> None:
    """
    从数据文件中采样指定数量的数据。

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        num: 采样数量，默认 10
            - num > 0: 采样指定数量
            - num = 0: 采样所有数据
            - num < 0: Python 切片风格（如 -1 表示最后 1 条，-10 表示最后 10 条）
        sample_type: 采样方式，可选 random/head/tail，默认 head
        output: 输出文件路径，不指定则打印到控制台
        seed: 随机种子（仅在 sample_type=random 时有效）
        by: 分层采样字段名，按该字段的值分组采样
        uniform: 均匀采样模式（需配合 --by 使用），各组采样相同数量

    Examples:
        dt sample data.jsonl 5
        dt sample data.csv 100 --sample_type=head
        dt sample data.xlsx 50 --output=sampled.jsonl
        dt sample data.jsonl 0   # 采样所有数据
        dt sample data.jsonl -10 # 最后 10 条数据
        dt sample data.jsonl 1000 --by=category           # 按比例分层采样
        dt sample data.jsonl 1000 --by=category --uniform # 均匀分层采样
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
            sampled = _stratified_sample(
                filepath, num, by, uniform, seed, sample_type
            )
        except Exception as e:
            print(f"错误: {e}")
            return
    else:
        # 普通采样
        try:
            sampled = sample_file(
                str(filepath),
                num=num,
                sample_type=sample_type,
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
        _print_samples(sampled)


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
) -> None:
    """
    显示文件的前 N 条数据（dt sample --sample_type=head 的快捷方式）。

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        num: 显示数量，默认 10
            - num > 0: 显示指定数量
            - num = 0: 显示所有数据
            - num < 0: Python 切片风格（如 -10 表示最后 10 条）
        output: 输出文件路径，不指定则打印到控制台

    Examples:
        dt head data.jsonl          # 显示前 10 条
        dt head data.jsonl 20       # 显示前 20 条
        dt head data.csv 0          # 显示所有数据
        dt head data.xlsx --output=head.jsonl
    """
    sample(filename, num=num, sample_type="head", output=output)


def tail(
    filename: str,
    num: int = 10,
    output: Optional[str] = None,
) -> None:
    """
    显示文件的后 N 条数据（dt sample --sample_type=tail 的快捷方式）。

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        num: 显示数量，默认 10
            - num > 0: 显示指定数量
            - num = 0: 显示所有数据
            - num < 0: Python 切片风格（如 -10 表示最后 10 条）
        output: 输出文件路径，不指定则打印到控制台

    Examples:
        dt tail data.jsonl          # 显示后 10 条
        dt tail data.jsonl 20       # 显示后 20 条
        dt tail data.csv 0          # 显示所有数据
        dt tail data.xlsx --output=tail.jsonl
    """
    sample(filename, num=num, sample_type="tail", output=output)


def _print_samples(samples: list) -> None:
    """打印采样结果。"""
    if not samples:
        print("没有数据")
        return

    try:
        from rich.console import Console
        from rich.json import JSON
        from rich.table import Table

        console = Console()

        # 尝试以表格形式展示
        if isinstance(samples[0], dict):
            keys = list(samples[0].keys())
            # 适合表格展示：字段不太多且值不太长
            if len(keys) <= 5 and all(
                len(str(s.get(k, ""))) < 100 for s in samples[:3] for k in keys
            ):
                table = Table(title=f"采样结果 ({len(samples)} 条)")
                for key in keys:
                    table.add_column(key, overflow="fold")
                for item in samples:
                    table.add_row(*[str(item.get(k, "")) for k in keys])
                console.print(table)
                return

        # 以 JSON 形式展示
        for i, item in enumerate(samples, 1):
            console.print(f"\n[bold cyan]--- 第 {i} 条 ---[/bold cyan]")
            console.print(JSON.from_data(item))

    except ImportError:
        # 没有 rich，使用普通打印
        import json

        for i, item in enumerate(samples, 1):
            print(f"\n--- 第 {i} 条 ---")
            print(json.dumps(item, ensure_ascii=False, indent=2))

    print(f"\n共 {len(samples)} 条数据")


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
        # 转义并加引号
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        s = json.dumps(value, ensure_ascii=False)
        if len(s) > max_len:
            return f"{s[:max_len]}..."
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
    return "\n".join(lines) if lines else '        # 在这里定义输出字段'


def _execute_transform(
    input_path: Path,
    config_path: Path,
    output_override: Optional[str],
    num: Optional[int],
) -> None:
    """执行数据转换"""
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

    # 加载数据并使用 DataTransformer 执行转换
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
    """使用预设模板执行转换"""
    print(f"📂 使用预设: {preset_name}")

    # 获取预设函数
    try:
        transform_func = get_preset(preset_name)
    except ValueError as e:
        print(f"错误: {e}")
        print(f"可用预设: {', '.join(list_presets())}")
        return

    # 加载数据
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
    output_path = output_override or f"{input_path.stem}_{preset_name}.jsonl"
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
    拼接多个数据文件。

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
        filepath = Path(f)
        if not filepath.exists():
            print(f"错误: 文件不存在 - {f}")
            return
        if not _check_file_format(filepath):
            return
        file_paths.append(filepath)

    # 分析各文件的字段
    print("📊 文件字段分析:")
    file_infos = []  # [(filepath, data, fields, count)]

    for filepath in file_paths:
        try:
            data = load_data(str(filepath))
        except Exception as e:
            print(f"错误: 无法读取文件 {filepath} - {e}")
            return

        if not data:
            print(f"警告: 文件为空 - {filepath}")
            fields = set()
        else:
            fields = set(data[0].keys())

        file_infos.append((filepath, data, fields, len(data)))
        fields_str = ", ".join(sorted(fields)) if fields else "(空)"
        print(f"   {filepath.name}: {fields_str} ({len(data)} 条)")

    # 分析字段差异
    all_fields = set()
    common_fields = None
    for _, _, fields, _ in file_infos:
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

    # 执行拼接
    print("\n🔄 执行拼接...")
    all_data = []
    for _, data, _, _ in file_infos:
        all_data.extend(data)

    # 保存结果
    print(f"💾 保存结果: {output}")
    try:
        save_data(all_data, output)
    except Exception as e:
        print(f"错误: 无法保存文件 - {e}")
        return

    total_count = len(all_data)
    file_count = len(files)
    print(f"\n✅ 完成! 已合并 {file_count} 个文件，共 {total_count} 条数据到 {output}")


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
            # 唯一值计数
            stat["unique"] = len(set(str(v) for v in non_null))

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
        if '\u4e00' <= char <= '\u9fff' or '\u3000' <= char <= '\u303f' or '\uff00' <= char <= '\uffef':
            char_width = 2
        else:
            char_width = 1
        if width + char_width > max_width - 3:  # 预留 ... 的宽度
            return ''.join(result) + "..."
        result.append(char)
        width += char_width
    return s


def _display_width(s: str) -> int:
    """计算字符串的显示宽度（中文字符算 2，ASCII 字符算 1）"""
    width = 0
    for char in s:
        # CJK 字符范围
        if '\u4e00' <= char <= '\u9fff' or '\u3000' <= char <= '\u303f' or '\uff00' <= char <= '\uffef':
            width += 2
        else:
            width += 1
    return width


def _pad_to_width(s: str, target_width: int) -> str:
    """将字符串填充到指定的显示宽度"""
    current_width = _display_width(s)
    if current_width >= target_width:
        return s
    return s + ' ' * (target_width - current_width)


def _print_stats(filename: str, total: int, field_stats: List[Dict[str, Any]]) -> None:
    """打印统计信息"""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel

        console = Console()

        # 概览
        console.print(Panel(
            f"[bold]文件:[/bold] {filename}\n"
            f"[bold]总数:[/bold] {total:,} 条\n"
            f"[bold]字段:[/bold] {len(field_stats)} 个",
            title="📊 数据概览",
            expand=False,
        ))

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
                extra.append(f"长度: {stat['len_min']}-{stat['len_max']} (avg {stat['len_avg']:.0f})")
            if "avg" in stat:
                if stat["type"] == "int":
                    extra.append(f"范围: {int(stat['min'])}-{int(stat['max'])} (avg {stat['avg']:.1f})")
                else:
                    extra.append(f"范围: {stat['min']:.2f}-{stat['max']:.2f} (avg {stat['avg']:.2f})")

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

            console.print(f"\n[bold cyan]{stat['field']}[/bold cyan] 值分布 (Top {len(top_values)}):")
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
    数据清洗。

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

    # 加载数据
    print(f"📊 加载数据: {filepath}")
    try:
        dt = DataTransformer.load(str(filepath))
    except Exception as e:
        print(f"错误: 无法读取文件 - {e}")
        return

    original_count = len(dt)
    print(f"   共 {original_count} 条数据")

    # 解析参数（fire 可能会将逗号分隔的值解析为元组）
    min_len_field, min_len_value = _parse_len_param(min_len) if min_len else (None, None)
    max_len_field, max_len_value = _parse_len_param(max_len) if max_len else (None, None)
    keep_fields = _parse_field_list(keep) if keep else None
    drop_fields = _parse_field_list(drop) if drop else None

    # 构建清洗配置
    empty_fields = None
    if drop_empty is not None:
        if drop_empty == "" or drop_empty is True:
            print("🔄 删除任意字段为空的记录...")
            empty_fields = []  # 空列表表示检查所有字段
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
    if drop_fields:
        print(f"🔄 删除字段: {', '.join(drop_fields)}")

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
        drop_fields=set(drop_fields) if drop_fields else None,
    )

    # 保存结果
    final_count = len(data)
    output_path = output or str(filepath)
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
