"""公共辅助函数"""

from typing import Any


def get_field_value(item: Any, field: str, default: Any = "") -> Any:
    """
    获取字段值，支持 DictWrapper 和普通 dict。

    优先尝试 dict.get()，如果没有 get 方法则使用 getattr()。

    Args:
        item: 数据对象（dict 或 DictWrapper）
        field: 字段名
        default: 默认值

    Returns:
        字段值或默认值

    Examples:
        >>> get_field_value({"name": "test"}, "name")
        'test'
        >>> get_field_value({"name": ""}, "name", "default")
        'default'
    """
    if hasattr(item, "get"):
        value = item.get(field, default)
    else:
        value = getattr(item, field, default)
    return value if value else default
