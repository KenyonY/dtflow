"""
CLI 命令实现
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from ..core import DataTransformer
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
) -> None:
    """
    从数据文件中采样指定数量的数据。

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        num: 采样数量，默认 10
        sample_type: 采样方式，可选 random/head/tail，默认 random
        output: 输出文件路径，不指定则打印到控制台
        seed: 随机种子（仅在 sample_type=random 时有效）

    Examples:
        dt sample data.jsonl 5
        dt sample data.csv 100 --sample_type=head
        dt sample data.xlsx 50 --output=sampled.jsonl
    """
    filepath = Path(filename)

    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
        return

    # 调用核心实现
    try:
        sampled = sample_file(
            str(filepath),
            num=num,
            sample_type=sample_type,
            seed=seed,
            output=output,
        )
    except Exception as e:
        print(f"错误: {e}")
        return

    # 输出结果
    if output:
        print(f"已保存 {len(sampled)} 条数据到 {output}")
    else:
        _print_samples(sampled)


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
