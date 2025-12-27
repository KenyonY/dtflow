"""
CLI 数据清洗和去重相关命令
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core import DataTransformer
from ..storage.io import save_data
from ..streaming import load_stream
from ..utils.field_path import get_field_with_spec
from .common import (
    _check_file_format,
    _get_value_len,
    _is_empty_value,
    _is_streaming_supported,
    _parse_field_list,
)


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
        key: 去重依据字段，支持嵌套路径语法：
            - meta.source        嵌套字段
            - messages[0].role   数组索引
            - messages[-1].content  负索引
            - messages.#         数组长度
            - messages[*].role:join  展开所有元素
            多个字段用逗号分隔。不指定则全量去重
        similar: 相似度阈值（0-1），指定后启用相似度去重模式，需要指定 --key
        output: 输出文件路径，不指定则覆盖原文件

    Examples:
        dt dedupe data.jsonl                       # 全量精确去重
        dt dedupe data.jsonl --key=text            # 按 text 字段精确去重
        dt dedupe data.jsonl --key=user,timestamp  # 按多字段组合精确去重
        dt dedupe data.jsonl --key=meta.id         # 按嵌套字段去重
        dt dedupe data.jsonl --key=messages[0].content   # 按第一条消息内容去重
        dt dedupe data.jsonl --key=text --similar=0.8    # 相似度去重
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
        drop_empty: 删除空值记录，支持嵌套路径语法
            - 不带值：删除任意字段为空的记录
            - 指定字段：删除指定字段为空的记录（逗号分隔）
        min_len: 最小长度过滤，格式 "字段:长度"，字段支持嵌套路径
        max_len: 最大长度过滤，格式 "字段:长度"，字段支持嵌套路径
        keep: 只保留指定字段（逗号分隔，仅支持顶层字段）
        drop: 删除指定字段（逗号分隔，仅支持顶层字段）
        strip: 去除所有字符串字段的首尾空白
        output: 输出文件路径，不指定则覆盖原文件

    Examples:
        dt clean data.jsonl --drop-empty                    # 删除任意空值记录
        dt clean data.jsonl --drop-empty=text,answer        # 删除指定字段为空的记录
        dt clean data.jsonl --drop-empty=meta.source        # 删除嵌套字段为空的记录
        dt clean data.jsonl --min-len=text:10               # text 字段最少 10 字符
        dt clean data.jsonl --min-len=messages.#:2          # 至少 2 条消息
        dt clean data.jsonl --max-len=messages[-1].content:500  # 最后一条消息最多 500 字符
        dt clean data.jsonl --keep=question,answer          # 只保留这些字段
        dt clean data.jsonl --drop=metadata,timestamp       # 删除这些字段
        dt clean data.jsonl --strip                         # 去除字符串首尾空白
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
        empty_fields: 检查空值的字段列表（支持嵌套路径），空列表表示检查所有字段，None 表示不检查
        min_len_field: 最小长度检查的字段（支持嵌套路径）
        min_len_value: 最小长度值
        max_len_field: 最大长度检查的字段（支持嵌套路径）
        max_len_value: 最大长度值
        keep_fields: 只保留的字段列表（仅支持顶层字段）
        drop_fields: 要删除的字段集合（仅支持顶层字段）

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
                # 检查指定字段（支持嵌套路径）
                if any(_is_empty_value(get_field_with_spec(item, f)) for f in empty_fields):
                    stats["drop_empty"] += 1
                    continue

        # 3. 最小长度过滤（支持嵌套路径）
        if min_len_field is not None:
            if _get_value_len(get_field_with_spec(item, min_len_field, default="")) < min_len_value:
                stats["min_len"] += 1
                continue

        # 4. 最大长度过滤（支持嵌套路径）
        if max_len_field is not None:
            if _get_value_len(get_field_with_spec(item, max_len_field, default="")) > max_len_value:
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
        """过滤函数：返回 True 保留，False 过滤（支持嵌套路径）"""
        # 空值过滤
        if empty_fields is not None:
            if len(empty_fields) == 0:
                if any(_is_empty_value(v) for v in item.values()):
                    return False
            else:
                # 支持嵌套路径
                if any(_is_empty_value(get_field_with_spec(item, f)) for f in empty_fields):
                    return False

        # 最小长度过滤（支持嵌套路径）
        if min_len_field is not None:
            if _get_value_len(get_field_with_spec(item, min_len_field, default="")) < min_len_value:
                return False

        # 最大长度过滤（支持嵌套路径）
        if max_len_field is not None:
            if _get_value_len(get_field_with_spec(item, max_len_field, default="")) > max_len_value:
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
