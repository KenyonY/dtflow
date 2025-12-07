"""
DataTransformer 核心模块

专注于数据格式转换，提供简洁的 API。
"""
from typing import List, Dict, Any, Optional, Callable, Union
from copy import deepcopy

from .storage.io import save_data, load_data


class DataTransformer:
    """
    数据格式转换工具。

    核心功能：
    - load/save: 加载和保存数据
    - to/transform: 格式转换
    - filter/sample: 数据筛选
    - fields/stats: 数据信息
    """

    def __init__(self, data: Optional[List[Dict[str, Any]]] = None):
        self._data = data if data is not None else []

    @property
    def data(self) -> List[Dict[str, Any]]:
        """获取原始数据"""
        return self._data

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, idx: Union[int, slice]) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        return self._data[idx]

    def __repr__(self) -> str:
        return f"DataTransformer({len(self._data)} items)"

    # ============ 加载/保存 ============

    @classmethod
    def load(cls, filepath: str) -> 'DataTransformer':
        """
        从文件加载数据。

        支持格式: jsonl, json, csv, parquet（自动检测）
        """
        data = load_data(filepath)
        return cls(data)

    def save(self, filepath: str) -> None:
        """
        保存数据到文件。

        支持格式: jsonl, json, csv, parquet（根据扩展名）
        """
        save_data(self._data, filepath)

    # ============ 核心转换 ============

    def to(self, func: Callable[[Any], Any]) -> List[Any]:
        """
        使用函数转换数据格式。

        Args:
            func: 转换函数，参数支持属性访问 (item.field)

        Returns:
            转换后的数据列表

        Examples:
            >>> dt = DataTransformer([{"q": "问题", "a": "回答"}])
            >>> dt.to(lambda x: {"instruction": x.q, "output": x.a})
            [{"instruction": "问题", "output": "回答"}]
        """
        return [func(DictWrapper(item)) for item in self._data]

    def transform(self, func: Callable[[Any], Any]) -> 'DataTransformer':
        """
        转换数据并返回新的 DataTransformer（支持链式调用）。

        Examples:
            >>> dt.transform(lambda x: {"q": x.q}).save("output.jsonl")
        """
        return DataTransformer(self.to(func))

    # ============ 数据筛选 ============

    def filter(self, func: Callable[[Any], bool]) -> 'DataTransformer':
        """
        筛选数据。

        Args:
            func: 筛选函数，返回 True 保留，参数支持属性访问

        Examples:
            >>> dt.filter(lambda x: len(x.text) > 10)
        """
        filtered = [item for item in self._data if func(DictWrapper(item))]
        return DataTransformer(filtered)

    def sample(self, n: int, seed: Optional[int] = None) -> 'DataTransformer':
        """
        随机采样 n 条数据。

        Args:
            n: 采样数量
            seed: 随机种子
        """
        import random
        if seed is not None:
            random.seed(seed)

        data = self._data[:] if n >= len(self._data) else random.sample(self._data, n)
        return DataTransformer(data)

    def head(self, n: int = 10) -> 'DataTransformer':
        """取前 n 条"""
        return DataTransformer(self._data[:n])

    def tail(self, n: int = 10) -> 'DataTransformer':
        """取后 n 条"""
        return DataTransformer(self._data[-n:])

    # ============ 数据信息 ============

    def fields(self) -> List[str]:
        """
        获取所有字段名。

        Returns:
            字段名列表（按字母排序）
        """
        if not self._data:
            return []

        all_fields = set()
        for item in self._data:
            all_fields.update(self._extract_fields(item))

        return sorted(all_fields)

    def _extract_fields(self, obj: Any, prefix: str = '') -> List[str]:
        """递归提取字段名"""
        fields = []
        if isinstance(obj, dict):
            for key, value in obj.items():
                field_path = f"{prefix}.{key}" if prefix else key
                fields.append(field_path)
                if isinstance(value, dict):
                    fields.extend(self._extract_fields(value, field_path))
        return fields

    def stats(self) -> Dict[str, Any]:
        """
        获取数据统计信息。

        Returns:
            包含 total, fields, field_stats 的字典
        """
        if not self._data:
            return {"total": 0, "fields": []}

        all_keys = set()
        for item in self._data:
            all_keys.update(item.keys())

        field_stats = {}
        for key in all_keys:
            values = [item.get(key) for item in self._data if key in item]
            field_stats[key] = {
                "count": len(values),
                "missing": len(self._data) - len(values),
                "type": type(values[0]).__name__ if values else "unknown"
            }

        return {
            "total": len(self._data),
            "fields": sorted(all_keys),
            "field_stats": field_stats
        }

    # ============ 工具方法 ============

    def copy(self) -> 'DataTransformer':
        """深拷贝"""
        return DataTransformer(deepcopy(self._data))

    def shuffle(self, seed: Optional[int] = None) -> 'DataTransformer':
        """打乱顺序（返回新实例）"""
        import random
        data = self._data[:]
        if seed is not None:
            random.seed(seed)
        random.shuffle(data)
        return DataTransformer(data)

    def split(self, ratio: float = 0.8, seed: Optional[int] = None) -> tuple:
        """
        分割数据集。

        Args:
            ratio: 第一部分的比例
            seed: 随机种子

        Returns:
            (train, test) 两个 DataTransformer
        """
        data = self.shuffle(seed).data
        split_idx = int(len(data) * ratio)
        return DataTransformer(data[:split_idx]), DataTransformer(data[split_idx:])


class DictWrapper:
    """
    字典包装器，支持属性访问。

    Examples:
        >>> w = DictWrapper({"a": {"b": 1}})
        >>> w.a.b  # 1
        >>> w["a"]["b"]  # 1
    """

    def __init__(self, data: Dict[str, Any]):
        object.__setattr__(self, '_data', data)

    def __getattr__(self, name: str) -> Any:
        data = object.__getattribute__(self, '_data')
        if name in data:
            value = data[name]
            if isinstance(value, dict):
                return DictWrapper(value)
            return value
        raise AttributeError(f"字段不存在: {name}")

    def __getitem__(self, key: str) -> Any:
        data = object.__getattribute__(self, '_data')
        value = data[key]
        if isinstance(value, dict):
            return DictWrapper(value)
        return value

    def __contains__(self, key: str) -> bool:
        data = object.__getattribute__(self, '_data')
        return key in data

    def __repr__(self) -> str:
        data = object.__getattribute__(self, '_data')
        return repr(data)

    def get(self, key: str, default: Any = None) -> Any:
        """安全获取字段值"""
        data = object.__getattribute__(self, '_data')
        value = data.get(key, default)
        if isinstance(value, dict):
            return DictWrapper(value)
        return value

    def to_dict(self) -> Dict[str, Any]:
        """返回原始字典"""
        return object.__getattribute__(self, '_data')
