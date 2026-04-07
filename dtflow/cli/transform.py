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
from .common import _check_file_format, _is_streaming_supported, _require_file_exists
from .output import die, die_io_error, die_usage, emit_action, log

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
    dry_run: bool = False,
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
        dry_run: 预演模式。转换前 N 条到内存后输出摘要 + 首条示例，不写出文件

    Examples:
        dt transform data.jsonl                        # 首次生成配置
        dt transform data.jsonl 10                     # 只转换前 10 条
        dt transform data.jsonl --preset=openai_chat   # 使用预设
        dt transform data.jsonl 100 --preset=alpaca    # 预设 + 限制数量
        dt transform data.jsonl --preset=alpaca --dry-run  # 预演转换
    """
    filepath = Path(filename)
    _require_file_exists(filepath)
    _check_file_format(filepath)

    # 预设模式：直接使用预设转换
    if preset:
        _execute_preset_transform(filepath, preset, output, num, dry_run=dry_run)
        return

    # 配置文件模式
    config_path = _get_config_path(filepath, config)

    if not config_path.exists():
        if dry_run:
            die_usage(
                "首次使用需要先生成配置，--dry-run 对配置生成无效",
                suggestion=f"先执行: dt transform {filename}",
            )
        _generate_config(filepath, config_path)
    else:
        _execute_transform(filepath, config_path, output, num, dry_run=dry_run)


def _generate_config(input_path: Path, config_path: Path) -> None:
    """分析输入数据并生成配置文件"""
    log(f"📊 分析输入数据: {input_path}")

    # 读取数据
    try:
        data = load_data(str(input_path))
    except Exception as e:
        die_io_error(e, operation="读取", path=str(input_path))

    if not data:
        die("empty_file", "文件为空", exit_code=1)

    total_count = len(data)
    sample_item = data[0]

    log(f"   检测到 {total_count} 条数据")

    # 生成配置内容
    config_content = _build_config_content(sample_item, input_path.name, total_count)

    # 确保配置目录存在
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # 写入配置文件
    config_path.write_text(config_content, encoding="utf-8")

    log(f"\n📝 已生成配置文件: {config_path}")
    log("\n👉 下一步:")
    log(f"   1. 编辑 {config_path}，定义 transform 函数")
    log(f"   2. 再次执行 dt transform {input_path.name} 完成转换")
    emit_action(
        "transform",
        status="config_generated",
        input_files=[str(input_path)],
        output=str(config_path),
        stats={"rows": total_count},
    )


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
    dry_run: bool = False,
) -> None:
    """执行数据转换（默认流式处理）"""
    log(f"📂 加载配置: {config_path}")

    # 动态加载配置文件
    try:
        config_ns = _load_config(config_path)
    except Exception as e:
        die("config_load_failed", f"无法加载配置文件: {e}")

    # 获取 transform 函数
    if "transform" not in config_ns:
        die_usage(
            "配置文件中未定义 transform 函数",
            suggestion=f"编辑 {config_path} 并添加 transform(item) 函数",
        )

    transform_func = config_ns["transform"]

    # 获取输出路径
    output_path = output_override or config_ns.get("output", "output.jsonl")

    def wrapped_transform(item):
        result = transform_func(DictWrapper(item))
        return _unwrap(result)

    # 对于 JSONL 文件使用流式处理（dry-run 时强制走内存模式统计）
    if _is_streaming_supported(input_path) and not dry_run:
        log(f"📊 流式加载: {input_path}")
        log("🔄 执行转换...")
        try:
            st = load_stream(str(input_path))
            if num:
                st = st.head(num)
            count = st.transform(wrapped_transform, raw=True).save(output_path)
            log(f"💾 保存结果: {output_path}")
            emit_action(
                "transform",
                input_files=[str(input_path)],
                output=output_path,
                stats={"output_rows": count},
            )
        except Exception as e:
            die("transform_failed", f"转换失败: {e}")
        return

    # 内存模式（非流式或 dry-run）
    log(f"📊 加载数据: {input_path}")
    try:
        dt = DataTransformer.load(str(input_path))
    except Exception as e:
        die_io_error(e, operation="读取", path=str(input_path))

    total = len(dt)
    if num:
        dt = DataTransformer(dt.data[:num])
        log(f"   处理前 {len(dt)}/{total} 条数据")
    else:
        log(f"   共 {total} 条数据")

    log("🔄 执行转换...")
    try:
        results = dt.to(transform_func)
    except Exception as e:
        die("transform_failed", f"转换失败: {e}")

    stats = {"input_rows": total, "output_rows": len(results)}
    if dry_run:
        preview = results[0] if results else None
        emit_action(
            "transform",
            input_files=[str(input_path)],
            output=output_path,
            stats=stats,
            extra={"preview": preview} if preview is not None else None,
            dry_run=True,
        )
        return

    log(f"💾 保存结果: {output_path}")
    try:
        save_data(results, output_path)
    except Exception as e:
        die_io_error(e, operation="保存", path=output_path)

    emit_action(
        "transform",
        input_files=[str(input_path)],
        output=output_path,
        stats=stats,
    )


def _execute_preset_transform(
    input_path: Path,
    preset_name: str,
    output_override: Optional[str],
    num: Optional[int],
    dry_run: bool = False,
) -> None:
    """使用预设模板执行转换（默认流式处理）"""
    log(f"📂 使用预设: {preset_name}")

    # 获取预设函数
    try:
        transform_func = get_preset(preset_name)
    except ValueError as e:
        die_usage(
            str(e),
            suggestion=f"可用预设: {', '.join(list_presets())}",
        )

    output_path = output_override or f"{input_path.stem}_{preset_name}.jsonl"

    def wrapped_transform(item):
        result = transform_func(DictWrapper(item))
        return _unwrap(result)

    # 对于 JSONL 文件使用流式处理（dry-run 时走内存模式）
    if _is_streaming_supported(input_path) and not dry_run:
        input_resolved = input_path.resolve()
        output_resolved = Path(output_path).resolve()
        use_temp_file = input_resolved == output_resolved

        log(f"📊 流式加载: {input_path}")
        log("🔄 执行转换...")

        if use_temp_file:
            log("⚠ 检测到输出文件与输入文件相同，将使用临时文件")
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
            st = load_stream(str(input_path))
            if num:
                st = st.head(num)
            count = st.transform(wrapped_transform, raw=True).save(actual_output)

            if use_temp_file:
                shutil.move(temp_path, output_path)

            log(f"💾 保存结果: {output_path}")
            emit_action(
                "transform",
                input_files=[str(input_path)],
                output=output_path,
                stats={"output_rows": count, "preset": preset_name},
            )
        except Exception as e:
            if use_temp_file and os.path.exists(temp_path):
                os.unlink(temp_path)
            die("transform_failed", f"转换失败: {e}")
        return

    # 内存模式（非流式或 dry-run）
    log(f"📊 加载数据: {input_path}")
    try:
        dt = DataTransformer.load(str(input_path))
    except Exception as e:
        die_io_error(e, operation="读取", path=str(input_path))

    total = len(dt)
    if num:
        dt = DataTransformer(dt.data[:num])
        log(f"   处理前 {len(dt)}/{total} 条数据")
    else:
        log(f"   共 {total} 条数据")

    log("🔄 执行转换...")
    try:
        results = dt.to(transform_func)
    except Exception as e:
        die("transform_failed", f"转换失败: {e}")

    stats = {"input_rows": total, "output_rows": len(results), "preset": preset_name}
    if dry_run:
        preview = results[0] if results else None
        emit_action(
            "transform",
            input_files=[str(input_path)],
            output=output_path,
            stats=stats,
            extra={"preview": preview} if preview is not None else None,
            dry_run=True,
        )
        return

    log(f"💾 保存结果: {output_path}")
    try:
        save_data(results, output_path)
    except Exception as e:
        die_io_error(e, operation="保存", path=output_path)

    emit_action(
        "transform",
        input_files=[str(input_path)],
        output=output_path,
        stats=stats,
    )


def _load_config(config_path: Path) -> Dict[str, Any]:
    """动态加载 Python 配置文件"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("dt_config", config_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return {name: getattr(module, name) for name in dir(module) if not name.startswith("_")}
