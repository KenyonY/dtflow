"""
CLI 采样相关命令
"""

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional

import orjson

from ..storage.io import load_data, sample_file, save_data
from ..utils.field_path import get_field_with_spec
from .common import (
    _check_file_format,
    _file_exists,
    _get_file_row_count,
    _is_flaxkv_path,
    _parse_field_list,
    _print_samples,
)

# where 条件解析正则：field op value
_WHERE_PATTERN = re.compile(r"^(.+?)(!=|~=|>=|<=|>|<|=)(.*)$")


def _parse_where(condition: str) -> Callable[[dict], bool]:
    """
    解析 where 条件字符串，返回筛选函数。

    支持的操作符:
        =   等于
        !=  不等于
        ~=  包含（字符串）
        >   大于
        >=  大于等于
        <   小于
        <=  小于等于

    Examples:
        _parse_where("category=tech")
        _parse_where("meta.source!=wiki")
        _parse_where("content~=机器学习")
        _parse_where("messages.#>=2")
    """
    match = _WHERE_PATTERN.match(condition)
    if not match:
        raise ValueError(f"无效的 where 条件: {condition}")

    field, op, value = match.groups()

    # 尝试转换 value 为数值
    def parse_value(v: str) -> Any:
        if v.lower() == "true":
            return True
        if v.lower() == "false":
            return False
        try:
            return int(v)
        except ValueError:
            try:
                return float(v)
            except ValueError:
                return v

    parsed_value = parse_value(value)

    def filter_fn(item: dict) -> bool:
        field_value = get_field_with_spec(item, field)

        if op == "=":
            # 字符串比较或数值比较
            if field_value is None:
                return value == "" or value.lower() == "none"
            return str(field_value) == value or field_value == parsed_value
        elif op == "!=":
            if field_value is None:
                return value != "" and value.lower() != "none"
            return str(field_value) != value and field_value != parsed_value
        elif op == "~=":
            # 包含
            if field_value is None:
                return False
            return value in str(field_value)
        elif op in (">", ">=", "<", "<="):
            # 数值比较
            if field_value is None:
                return False
            try:
                num_field = float(field_value)
                num_value = float(value)
                if op == ">":
                    return num_field > num_value
                elif op == ">=":
                    return num_field >= num_value
                elif op == "<":
                    return num_field < num_value
                else:  # <=
                    return num_field <= num_value
            except (ValueError, TypeError):
                return False
        return False

    return filter_fn


def _apply_where_filters(data: List[Dict], where_conditions: List[str]) -> List[Dict]:
    """应用多个 where 条件（AND 关系）"""
    if not where_conditions:
        return data

    filters = [_parse_where(cond) for cond in where_conditions]
    return [item for item in data if all(f(item) for f in filters)]


def _sample_from_list(
    data: List[Dict],
    num: int,
    sample_type: str,
    seed: Optional[int] = None,
) -> List[Dict]:
    """从列表中采样"""
    import random

    if seed is not None:
        random.seed(seed)

    total = len(data)
    if num <= 0 or num > total:
        num = total

    if sample_type == "random":
        return random.sample(data, num)
    elif sample_type == "head":
        return data[:num]
    else:  # tail
        return data[-num:]


def sample(
    filename: str,
    num: int = 10,
    type: Optional[Literal["random", "head", "tail"]] = None,
    output: Optional[str] = None,
    seed: Optional[int] = None,
    by: Optional[str] = None,
    uniform: bool = False,
    fields: Optional[str] = None,
    raw: bool = True,
    where: Optional[List[str]] = None,
) -> None:
    """
    从数据文件中采样指定数量的数据。

    Args:
        filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        num: 采样数量，默认 10
            - num > 0: 采样指定数量
            - num = 0: 全量（保持原序，等同格式转换）
            - num < 0: Python 切片风格（如 -1 表示最后 1 条，-10 表示最后 10 条）
        type: 采样方式，可选 random/head/tail。默认 random，num=0 时默认 head（保持原序）
        output: 输出文件路径，不指定则打印到控制台
        seed: 随机种子（仅在 type=random 时有效）
        by: 分层采样字段名，按该字段的值分组采样
        uniform: 均匀采样模式（需配合 --by 使用），各组采样相同数量
        fields: 只显示指定字段（逗号分隔），仅在预览模式下有效
        raw: 输出原始 JSON 格式（不截断，完整显示所有内容）
        where: 筛选条件列表，支持 =, !=, ~=, >, >=, <, <= 操作符

    Examples:
        dt sample data.jsonl 5
        dt sample data.csv 100 --type=head
        dt sample data.xlsx 50 --output=sampled.jsonl
        dt sample data.jsonl 0   # 全量保持原序（格式转换）
        dt sample data.jsonl 0 --type=random  # 全量乱序
        dt sample data.jsonl -10 # 最后 10 条数据
        dt sample data.jsonl 1000 --by=category           # 按比例分层采样
        dt sample data.jsonl 1000 --by=category --uniform # 均匀分层采样
        dt sample data.jsonl --fields=question,answer     # 只显示指定字段
        dt sample data.jsonl --where="category=tech"      # 筛选 category 为 tech 的数据
        dt sample data.jsonl --where="meta.source~=wiki"  # 筛选 meta.source 包含 wiki
        dt sample data.jsonl --where="messages.#>=2"      # 筛选消息数量 >= 2
    """
    # type 未指定时：n=0 默认 head（保序），其他默认 random
    if type is None:
        type = "head" if num == 0 else "random"
    filepath = Path(filename)

    if not _file_exists(filepath):
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
        return

    # uniform 必须配合 by 使用
    if uniform and not by:
        print("错误: --uniform 必须配合 --by 使用")
        return

    # 处理 where 筛选
    where_conditions = where or []
    filtered_data = None
    original_count = None

    if where_conditions:
        # 有 where 条件时，先加载全部数据再筛选
        try:
            all_data = load_data(str(filepath))
            original_count = len(all_data)
            filtered_data = _apply_where_filters(all_data, where_conditions)
            print(f"🔍 筛选: {original_count} → {len(filtered_data)} 条")
            if not filtered_data:
                print("⚠️  筛选后无数据")
                return
        except ValueError as e:
            print(f"错误: {e}")
            return

    # 分层采样模式
    if by:
        try:
            sampled = _stratified_sample(filepath, num, by, uniform, seed, type, data=filtered_data)
        except Exception as e:
            print(f"错误: {e}")
            return
    else:
        # 普通采样
        try:
            if filtered_data is not None:
                # 已筛选的数据，直接采样
                sampled = _sample_from_list(filtered_data, num, type, seed)
            else:
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
        if _is_flaxkv_path(filepath):
            # flaxkv 是目录，用 keys_count 获取总数
            total_count = _get_file_row_count(filepath)
            file_size = None
        else:
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
    data: Optional[List[Dict]] = None,
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
        data: 预筛选的数据（可选，如果提供则不从文件加载）

    Returns:
        采样后的数据列表
    """
    import random
    from collections import defaultdict

    if seed is not None:
        random.seed(seed)

    # 加载数据（如果没有预筛选数据）
    if data is None:
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
    raw: bool = True,
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


def slice_data(
    filename: str,
    range_str: str,
    output: Optional[str] = None,
    fields: Optional[str] = None,
    raw: bool = True,
) -> None:
    """
    按行号范围查看数据（Python 切片语法）。

    Args:
        filename: 输入文件路径
        range_str: 行号范围，格式为 start:end（0-based，左闭右开）
            - 10:20    第 10-19 行（共 10 条）
            - :100     前 100 行
            - 100:     第 100 行到末尾
            - -10:     最后 10 行
        output: 输出文件路径
        fields: 只显示指定字段（逗号分隔）
        raw: 输出原始 JSON 格式

    Examples:
        dt slice data.jsonl 10:20
        dt slice data.jsonl :100
        dt slice data.jsonl 100:
        dt slice data.jsonl -10:
        dt slice data.jsonl 10:20 --output=sliced.jsonl
        dt slice data.jsonl 10:20 --fields=question,answer
    """
    filepath = Path(filename)

    if not _file_exists(filepath):
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
        return

    # 解析 range
    if ":" not in range_str:
        print(f"错误: 无效的范围格式 '{range_str}'，应为 start:end（如 10:20）")
        return

    parts = range_str.split(":", 1)
    start_str, end_str = parts[0].strip(), parts[1].strip()

    try:
        start = int(start_str) if start_str else None
        end = int(end_str) if end_str else None
    except ValueError:
        print(f"错误: 无效的范围格式 '{range_str}'，start 和 end 必须为整数")
        return

    # 加载数据并切片
    try:
        data = load_data(str(filepath))
    except Exception as e:
        print(f"错误: {e}")
        return

    sliced = data[start:end]

    if not sliced:
        total = len(data)
        print(f"⚠️  范围 [{range_str}] 无数据（文件共 {total} 行）")
        return

    # 显示范围信息
    total = len(data)
    actual_start = start if start is not None else 0
    if actual_start < 0:
        actual_start = max(0, total + actual_start)
    actual_end = min(end, total) if end is not None else total
    print(f"📍 行 {actual_start}-{actual_end - 1}（共 {len(sliced)} 条，文件共 {total} 行）")

    # 输出结果
    if output:
        save_data(sliced, output)
        print(f"已保存 {len(sliced)} 条数据到 {output}")
    elif raw:
        for item in sliced:
            print(orjson.dumps(item, option=orjson.OPT_INDENT_2).decode("utf-8"))
    else:
        field_list = _parse_field_list(fields) if fields else None
        file_size = None if _is_flaxkv_path(filepath) else filepath.stat().st_size
        _print_samples(sliced, filepath.name, total, field_list, file_size)


def tail(
    filename: str,
    num: int = 10,
    output: Optional[str] = None,
    fields: Optional[str] = None,
    raw: bool = True,
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
