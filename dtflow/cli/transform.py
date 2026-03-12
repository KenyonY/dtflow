"""
CLI 数据转换相关命令
"""

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import orjson

from ..core import DataTransformer, DictWrapper
from ..presets import get_preset, list_presets
from ..storage.io import load_data, save_data
from ..streaming import load_stream
from .common import _check_file_format, _is_streaming_supported

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


def _unwrap(obj: Any) -> Any:
    """递归将 DictWrapper 转换为普通 dict"""
    if hasattr(obj, "to_dict"):
        return _unwrap(obj.to_dict())
    if isinstance(obj, dict):
        return {k: _unwrap(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_unwrap(v) for v in obj]
    return obj


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
                result = transform_func(DictWrapper(item))
                return _unwrap(result)

            st = load_stream(str(input_path))
            if num:
                st = st.head(num)
            count = st.transform(wrapped_transform, raw=True).save(output_path)
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
                result = transform_func(DictWrapper(item))
                return _unwrap(result)

            st = load_stream(str(input_path))
            if num:
                st = st.head(num)
            count = st.transform(wrapped_transform, raw=True).save(actual_output)

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
