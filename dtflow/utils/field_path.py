"""
字段路径解析模块

支持的语法:
    a.b.c        嵌套字段访问
    a[0].b       数组索引访问
    a[-1].b      负索引访问
    a.#          数组长度
    a[*].b       展开所有元素

展开模式 (用于 [*]):
    first   取第一个值（默认）
    join    拼接为字符串（用 | 分隔）
    unique  去重后排序拼接

用法:
    from dtflow.utils.field_path import get_field

    # 基础用法
    get_field(item, "meta.source")
    get_field(item, "messages[0].role")
    get_field(item, "messages[-1].content")
    get_field(item, "messages.#")

    # 展开模式
    get_field(item, "messages[*].role")              # 默认取第一个
    get_field(item, "messages[*].role", mode="join") # 拼接: "system|user|assistant"
    get_field(item, "messages[*].role", mode="unique") # 去重: "assistant|system|user"

    # 解析路径语法
    path, mode = parse_field_spec("messages[*].role:unique")
"""

import re
from typing import Any, List, Literal, Optional, Tuple, Union

# 展开模式类型
ExpandMode = Literal["first", "join", "unique"]

# 路径段解析正则
# 匹配: field, field[0], field[-1], field[*], field.#
_SEGMENT_PATTERN = re.compile(
    r"([a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*)"  # 字段名（支持中文）
    r"(?:\[(-?\d+|\*)\])?"  # 可选的索引 [0], [-1], [*]
    r"|(#)"  # 或者长度操作符 #
)


def parse_field_spec(spec: str) -> Tuple[str, ExpandMode]:
    """
    解析字段规格，分离路径和展开模式

    Args:
        spec: 字段规格，如 "messages[*].role:unique"

    Returns:
        (path, mode) 元组

    Examples:
        >>> parse_field_spec("meta.source")
        ('meta.source', 'first')
        >>> parse_field_spec("messages[*].role:join")
        ('messages[*].role', 'join')
    """
    if ":" in spec:
        path, mode_str = spec.rsplit(":", 1)
        if mode_str in ("first", "join", "unique"):
            return path, mode_str  # type: ignore
        # 冒号不是模式分隔符，可能是字段名的一部分
        return spec, "first"
    return spec, "first"


def _parse_path(path: str) -> List[Union[str, int, Literal["*", "#"]]]:
    """
    解析路径字符串为段列表

    Args:
        path: 路径字符串，如 "messages[0].role" 或 "meta.source"

    Returns:
        段列表，如 ["messages", 0, "role"] 或 ["meta", "source"]
    """
    segments: List[Union[str, int, Literal["*", "#"]]] = []

    # 按点分割，但保留方括号内容
    parts = path.replace("][", "].[").split(".")

    for part in parts:
        if not part:
            continue

        # 检查是否是长度操作符
        if part == "#":
            segments.append("#")
            continue

        # 解析 field[index] 格式
        match = re.match(
            r"([a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*)?(?:\[(-?\d+|\*)\])?", part
        )
        if match:
            field_name, index = match.groups()

            if field_name:
                segments.append(field_name)

            if index is not None:
                if index == "*":
                    segments.append("*")
                else:
                    segments.append(int(index))

    return segments


def _get_value_by_segments(
    data: Any,
    segments: List[Union[str, int, Literal["*", "#"]]],
    mode: ExpandMode = "first",
) -> Any:
    """
    根据段列表从数据中提取值

    Args:
        data: 源数据
        segments: 路径段列表
        mode: 展开模式

    Returns:
        提取的值
    """
    if not segments:
        return data

    current = data
    i = 0

    while i < len(segments):
        seg = segments[i]

        if current is None:
            return None

        # 长度操作符
        if seg == "#":
            if isinstance(current, (list, tuple, str)):
                return len(current)
            return None

        # 展开操作符
        if seg == "*":
            if not isinstance(current, (list, tuple)):
                return None

            # 获取剩余路径
            remaining = segments[i + 1 :]

            # 对每个元素递归获取值
            values = []
            for item in current:
                val = _get_value_by_segments(item, remaining, mode="first")
                if val is not None:
                    values.append(val)

            # 根据模式处理结果
            if not values:
                return None

            if mode == "first":
                return values[0]
            elif mode == "join":
                return "|".join(str(v) for v in values)
            elif mode == "unique":
                unique_vals = sorted(set(str(v) for v in values))
                return "|".join(unique_vals)

            return values

        # 字典字段访问（支持 dict 和类 dict 对象如 DictWrapper）
        if isinstance(seg, str):
            if isinstance(current, dict):
                current = current.get(seg)
            elif hasattr(current, "get"):
                current = current.get(seg)
            else:
                return None

        # 数组索引访问
        elif isinstance(seg, int):
            if isinstance(current, (list, tuple)):
                try:
                    current = current[seg]
                except IndexError:
                    return None
            else:
                return None

        i += 1

    return current


def get_field(
    data: dict,
    path: str,
    mode: ExpandMode = "first",
    default: Any = None,
) -> Any:
    """
    从字典中获取嵌套字段值

    Args:
        data: 源字典
        path: 字段路径
        mode: 展开模式（当路径包含 [*] 时生效）
        default: 默认值（当路径不存在时返回）

    Returns:
        字段值或默认值

    Examples:
        >>> data = {"meta": {"source": "wiki"}, "messages": [{"role": "user"}, {"role": "assistant"}]}

        # 嵌套字段
        >>> get_field(data, "meta.source")
        'wiki'

        # 数组索引
        >>> get_field(data, "messages[0].role")
        'user'
        >>> get_field(data, "messages[-1].role")
        'assistant'

        # 数组长度
        >>> get_field(data, "messages.#")
        2

        # 展开所有元素
        >>> get_field(data, "messages[*].role")
        'user'
        >>> get_field(data, "messages[*].role", mode="join")
        'user|assistant'
        >>> get_field(data, "messages[*].role", mode="unique")
        'assistant|user'
    """
    if not path:
        return default

    segments = _parse_path(path)
    result = _get_value_by_segments(data, segments, mode)

    return result if result is not None else default


def get_field_with_spec(data: dict, spec: str, default: Any = None) -> Any:
    """
    解析完整的字段规格并获取值

    Args:
        data: 源字典
        spec: 字段规格，如 "messages[*].role:unique"
        default: 默认值

    Returns:
        字段值

    Examples:
        >>> get_field_with_spec(data, "messages[*].role:join")
        'user|assistant'
    """
    path, mode = parse_field_spec(spec)
    return get_field(data, path, mode=mode, default=default)


# 便捷别名
extract = get_field
extract_with_spec = get_field_with_spec
