"""
CLI 采样相关命令
"""

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import orjson

from ..storage.io import load_data, sample_file, save_data
from ..utils.field_path import get_field_with_spec
from .common import (
    _check_file_format,
    _get_file_row_count,
    _parse_field_list,
    _print_samples,
)


def sample(
    filename: str,
    num: int = 10,
    type: Literal["random", "head", "tail"] = "head",
    output: Optional[str] = None,
    seed: Optional[int] = None,
    by: Optional[str] = None,
    uniform: bool = False,
    fields: Optional[str] = None,
    raw: bool = False,
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
        raw: 输出原始 JSON 格式（不截断，完整显示所有内容）

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
    elif raw:
        # 原始 JSON 输出（不截断）
        for item in sampled:
            print(orjson.dumps(item, option=orjson.OPT_INDENT_2).decode("utf-8"))
    else:
        # 大文件跳过行数统计（50MB 阈值）
        file_size = filepath.stat().st_size
        if file_size < 50 * 1024 * 1024:
            total_count = _get_file_row_count(filepath)
        else:
            total_count = None
        # 解析 fields 参数
        field_list = _parse_field_list(fields) if fields else None
        _print_samples(sampled, filepath.name, total_count, field_list, file_size)


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
        stratify_field: 分层字段，支持嵌套路径语法：
            - meta.source        嵌套字段
            - messages[0].role   数组索引
            - messages[-1].role  负索引
            - messages.#         数组长度
            - messages[*].role   展开所有元素（可加 :join/:unique 模式）
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

    # 按字段分组（支持嵌套路径语法）
    groups: Dict[Any, List[Dict]] = defaultdict(list)
    for item in data:
        key = get_field_with_spec(item, stratify_field, default="__null__")
        # 确保 key 可哈希
        if isinstance(key, list):
            key = tuple(key)
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
    print("🔄 执行采样...")
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
    print("\n📋 采样结果:")
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
    raw: bool = False,
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
        raw: 输出原始 JSON 格式（不截断，完整显示所有内容）

    Examples:
        dt head data.jsonl          # 显示前 10 条
        dt head data.jsonl 20       # 显示前 20 条
        dt head data.csv 0          # 显示所有数据
        dt head data.xlsx --output=head.jsonl
        dt head data.jsonl --fields=question,answer
        dt head data.jsonl 1 --raw  # 完整 JSON 输出
    """
    sample(filename, num=num, type="head", output=output, fields=fields, raw=raw)


def tail(
    filename: str,
    num: int = 10,
    output: Optional[str] = None,
    fields: Optional[str] = None,
    raw: bool = False,
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
        raw: 输出原始 JSON 格式（不截断，完整显示所有内容）

    Examples:
        dt tail data.jsonl          # 显示后 10 条
        dt tail data.jsonl 20       # 显示后 20 条
        dt tail data.csv 0          # 显示所有数据
        dt tail data.xlsx --output=tail.jsonl
        dt tail data.jsonl --fields=question,answer
        dt tail data.jsonl 1 --raw  # 完整 JSON 输出
    """
    sample(filename, num=num, type="tail", output=output, fields=fields, raw=raw)
