"""
DataTransformer 核心模块

专注于数据格式转换，提供简洁的 API。
"""
from typing import List, Dict, Any, Optional, Callable, Union, Tuple, Literal
from copy import deepcopy
from dataclasses import dataclass

from .storage.io import save_data, load_data


# ============ 错误处理 ============

@dataclass
class TransformError:
    """转换错误信息"""
    index: int          # 原始数据索引
    item: Dict          # 原始数据项
    error: Exception    # 异常对象

    def __repr__(self) -> str:
        return f"TransformError(index={self.index}, error={self.error!r})"

    def __str__(self) -> str:
        # 截断过长的数据展示
        item_str = str(self.item)
        if len(item_str) > 100:
            item_str = item_str[:100] + "..."
        return f"第 {self.index} 行转换失败: {self.error}\n  数据: {item_str}"


class TransformErrors(Exception):
    """批量转换错误，包含所有失败的记录"""

    def __init__(self, errors: List[TransformError]):
        self.errors = errors
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        if len(self.errors) == 1:
            return str(self.errors[0])
        return f"转换失败 {len(self.errors)} 条记录:\n" + "\n".join(
            f"  [{e.index}] {e.error}" for e in self.errors[:5]
        ) + (f"\n  ... 还有 {len(self.errors) - 5} 条错误" if len(self.errors) > 5 else "")

    def __iter__(self):
        return iter(self.errors)

    def __len__(self):
        return len(self.errors)


def _print_error_summary(errors: List[TransformError], total: int) -> None:
    """打印错误摘要到 stderr"""
    import sys

    error_count = len(errors)
    success_count = total - error_count

    # 简洁的警告信息
    print(f"⚠ 转换完成: {success_count}/{total} 成功, {error_count} 失败", file=sys.stderr)

    # 显示前几条错误详情
    show_count = min(3, error_count)
    for err in errors[:show_count]:
        print(f"  [{err.index}] {err.error}", file=sys.stderr)

    if error_count > show_count:
        print(f"  ... 还有 {error_count - show_count} 条错误", file=sys.stderr)


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

    def to(
        self,
        func: Callable[[Any], Any],
        on_error: Literal["skip", "raise", "null"] = "skip",
        return_errors: bool = False,
    ) -> Union[List[Any], Tuple[List[Any], List[TransformError]]]:
        """
        使用函数转换数据格式。

        Args:
            func: 转换函数，参数支持属性访问 (item.field)
            on_error: 错误处理策略
                - "skip": 跳过错误行，打印警告（默认）
                - "raise": 遇到错误立即抛出异常
                - "null": 错误行返回 None
            return_errors: 是否返回错误列表（仅当 on_error != "raise" 时有效）

        Returns:
            - 默认返回转换后的数据列表
            - 如果 return_errors=True，返回 (结果列表, 错误列表)

        Raises:
            TransformErrors: 当 on_error="raise" 且有转换失败时

        Examples:
            >>> dt = DataTransformer([{"q": "问题", "a": "回答"}])
            >>> dt.to(lambda x: {"instruction": x.q, "output": x.a})
            [{"instruction": "问题", "output": "回答"}]

            >>> # 严格模式：遇错即停
            >>> results = dt.to(transform_func, on_error="raise")

            >>> # 获取错误详情
            >>> results, errors = dt.to(transform_func, return_errors=True)
        """
        results = []
        errors = []

        for i, item in enumerate(self._data):
            try:
                result = func(DictWrapper(item))
                results.append(result)
            except Exception as e:
                err = TransformError(index=i, item=item, error=e)

                if on_error == "raise":
                    raise TransformErrors([err]) from e
                elif on_error == "skip":
                    errors.append(err)
                elif on_error == "null":
                    results.append(None)
                    errors.append(err)

        # 打印错误摘要
        if errors and not return_errors:
            _print_error_summary(errors, len(self._data))

        if return_errors:
            return results, errors
        return results

    def transform(
        self,
        func: Callable[[Any], Any],
        on_error: Literal["skip", "raise", "null"] = "skip",
    ) -> 'DataTransformer':
        """
        转换数据并返回新的 DataTransformer（支持链式调用）。

        Args:
            func: 转换函数
            on_error: 错误处理策略（同 to() 方法）

        Examples:
            >>> dt.transform(lambda x: {"q": x.q}).save("output.jsonl")
            >>> dt.transform(transform_func, on_error="raise").save("output.jsonl")
        """
        return DataTransformer(self.to(func, on_error=on_error))

    # ============ 数据筛选 ============

    def filter(
        self,
        func: Callable[[Any], bool],
        on_error: Literal["skip", "raise", "keep"] = "skip",
    ) -> 'DataTransformer':
        """
        筛选数据。

        Args:
            func: 筛选函数，返回 True 保留，参数支持属性访问
            on_error: 错误处理策略
                - "skip": 跳过错误行，打印警告（默认，不保留错误行）
                - "raise": 遇到错误立即抛出异常
                - "keep": 保留错误行

        Examples:
            >>> dt.filter(lambda x: len(x.text) > 10)
            >>> dt.filter(lambda x: x.score > 0.5, on_error="raise")
        """
        filtered = []
        errors = []

        for i, item in enumerate(self._data):
            try:
                if func(DictWrapper(item)):
                    filtered.append(item)
            except Exception as e:
                err = TransformError(index=i, item=item, error=e)
                if on_error == "raise":
                    raise TransformErrors([err]) from e
                elif on_error == "keep":
                    filtered.append(item)
                    errors.append(err)
                else:  # skip
                    errors.append(err)

        # 打印错误摘要
        if errors:
            _print_error_summary(errors, len(self._data))

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
