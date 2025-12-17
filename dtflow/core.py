"""
DataTransformer 核心模块

专注于数据格式转换，提供简洁的 API。
"""
from typing import List, Dict, Any, Optional, Callable, Union, Tuple, Literal
from copy import deepcopy
from dataclasses import dataclass
import json

from .storage.io import save_data, load_data

# 尝试使用 orjson（更快的 JSON 序列化库）
try:
    import orjson
    _HAS_ORJSON = True
except ImportError:
    _HAS_ORJSON = False


def _fast_json_dumps(obj: Any) -> str:
    """
    快速 JSON 序列化，优先使用 orjson。

    orjson 比标准 json 快约 10 倍，特别适合大量数据的序列化场景。
    """
    if _HAS_ORJSON:
        # orjson.dumps 返回 bytes，需要 decode
        return orjson.dumps(obj, option=orjson.OPT_SORT_KEYS).decode('utf-8')
    else:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False)


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
        raw: bool = False,
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
            raw: 原始模式，直接传递 dict 而不包装为 DictWrapper（性能优化）

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

            >>> # 原始模式（性能优化，大数据集推荐）
            >>> dt.to(lambda x: {"q": x["q"]}, raw=True)
        """
        results = []
        errors = []

        # raw 模式：直接传递 dict，跳过 DictWrapper 包装
        wrapper_func = (lambda x: x) if raw else DictWrapper

        for i, item in enumerate(self._data):
            try:
                result = func(wrapper_func(item))
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
        raw: bool = False,
    ) -> 'DataTransformer':
        """
        转换数据并返回新的 DataTransformer（支持链式调用）。

        Args:
            func: 转换函数
            on_error: 错误处理策略（同 to() 方法）
            raw: 原始模式，直接传递 dict 而不包装为 DictWrapper（性能优化）

        Examples:
            >>> dt.transform(lambda x: {"q": x.q}).save("output.jsonl")
            >>> dt.transform(transform_func, on_error="raise").save("output.jsonl")
            >>> # 原始模式（大数据集推荐）
            >>> dt.transform(lambda x: {"q": x["q"]}, raw=True).save("output.jsonl")
        """
        return DataTransformer(self.to(func, on_error=on_error, raw=raw))

    # ============ 数据筛选 ============

    def filter(
        self,
        func: Callable[[Any], bool],
        on_error: Literal["skip", "raise", "keep"] = "skip",
        raw: bool = False,
    ) -> 'DataTransformer':
        """
        筛选数据。

        Args:
            func: 筛选函数，返回 True 保留，参数支持属性访问
            on_error: 错误处理策略
                - "skip": 跳过错误行，打印警告（默认，不保留错误行）
                - "raise": 遇到错误立即抛出异常
                - "keep": 保留错误行
            raw: 原始模式，直接传递 dict 而不包装为 DictWrapper（性能优化）

        Examples:
            >>> dt.filter(lambda x: len(x.text) > 10)
            >>> dt.filter(lambda x: x.score > 0.5, on_error="raise")
            >>> # 原始模式（大数据集推荐）
            >>> dt.filter(lambda x: len(x["text"]) > 10, raw=True)
        """
        filtered = []
        errors = []

        # raw 模式：直接传递 dict，跳过 DictWrapper 包装
        wrapper_func = (lambda x: x) if raw else DictWrapper

        for i, item in enumerate(self._data):
            try:
                if func(wrapper_func(item)):
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

    def dedupe(
        self,
        key: Union[None, str, List[str], Callable[[Any], Any]] = None,
    ) -> 'DataTransformer':
        """
        数据去重。

        Args:
            key: 去重依据，可以是：
                - None: 全量去重（整条数据比较）
                - str: 按单个字段去重
                - list[str]: 按多个字段组合去重
                - callable: 自定义 key 函数

        Returns:
            去重后的新 DataTransformer

        Examples:
            >>> dt.dedupe()                            # 全量去重
            >>> dt.dedupe('text')                      # 按 text 字段去重
            >>> dt.dedupe(['user', 'timestamp'])       # 按多字段组合去重
            >>> dt.dedupe(lambda x: x.text.lower())    # 自定义 key
        """
        seen = set()
        result = []

        for item in self._data:
            k = self._get_dedupe_key(item, key)
            if k not in seen:
                seen.add(k)
                result.append(item)

        return DataTransformer(result)

    def _get_dedupe_key(
        self,
        item: Dict[str, Any],
        key: Union[None, str, List[str], Callable[[Any], Any]],
    ) -> Any:
        """获取去重用的 key"""
        if key is None:
            # 全量去重：使用快速 JSON 序列化
            return _fast_json_dumps(item)
        elif isinstance(key, str):
            # 单字段
            return item.get(key)
        elif isinstance(key, list):
            # 多字段组合
            return tuple(item.get(k) for k in key)
        elif callable(key):
            # 自定义函数
            return key(DictWrapper(item))
        else:
            raise ValueError(f"不支持的 key 类型: {type(key)}")

    def dedupe_similar(
        self,
        key: Union[str, Callable[[Any], str]],
        threshold: float = 0.8,
        num_perm: int = 128,
        ngram: int = 3,
    ) -> 'DataTransformer':
        """
        基于 MinHash + LSH 的相似度去重。

        Args:
            key: 用于比较的文本字段，可以是字段名或提取函数
            threshold: 相似度阈值，0-1 之间，默认 0.8
            num_perm: MinHash 签名长度，越大越精确但越慢，默认 128
            ngram: n-gram 大小，默认 3（字符级）

        Returns:
            去重后的新 DataTransformer

        Examples:
            >>> dt.dedupe_similar('text')                    # 按 text 字段相似度去重
            >>> dt.dedupe_similar('text', threshold=0.9)     # 更严格的阈值
            >>> dt.dedupe_similar(lambda x: x.title + x.content)  # 自定义文本
        """
        try:
            from datasketch import MinHash, MinHashLSH
        except ImportError:
            raise ImportError(
                "相似度去重需要 datasketch 库，请安装: pip install datasketch"
            )

        if not self._data:
            return DataTransformer([])

        # 验证并调整参数
        # MinHashLSH 在高阈值时需要更大的 num_perm，否则 bands 数量会过小
        # threshold=0.99 需要 num_perm>=512，threshold>=0.999 会需要极大的值(4096+)
        if threshold >= 0.999:
            import warnings
            warnings.warn(
                f"阈值 {threshold} 过高，已自动调整为 0.99。"
                f"如需更高精度，建议使用 dedupe() 精确去重。",
                UserWarning
            )
            threshold = 0.99

        if threshold >= 0.99 and num_perm < 512:
            num_perm = 512
        elif threshold >= 0.95 and num_perm < 256:
            num_perm = 256

        # 创建 LSH 索引
        lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        minhashes = []

        # 为每个文档创建 MinHash
        for i, item in enumerate(self._data):
            text = self._get_text_for_similarity(item, key)
            m = self._create_minhash(text, num_perm, ngram)
            minhashes.append(m)
            lsh.insert(str(i), m)

        # 找出要保留的索引（每个相似组保留第一个）
        keep_indices = set()
        removed_indices = set()

        for i in range(len(self._data)):
            if i in removed_indices:
                continue

            keep_indices.add(i)

            # 查询相似文档
            similar = lsh.query(minhashes[i])
            for idx_str in similar:
                idx = int(idx_str)
                if idx != i and idx not in keep_indices:
                    removed_indices.add(idx)

        # 按原顺序保留数据
        result = [self._data[i] for i in sorted(keep_indices)]
        return DataTransformer(result)

    def _get_text_for_similarity(
        self,
        item: Dict[str, Any],
        key: Union[str, Callable[[Any], str]],
    ) -> str:
        """获取用于相似度比较的文本"""
        if isinstance(key, str):
            return str(item.get(key, ""))
        elif callable(key):
            return str(key(DictWrapper(item)))
        else:
            raise ValueError(f"不支持的 key 类型: {type(key)}")

    def _create_minhash(self, text: str, num_perm: int, ngram: int) -> 'MinHash':
        """创建文本的 MinHash 签名"""
        from datasketch import MinHash

        m = MinHash(num_perm=num_perm)
        # 使用字符级 n-gram（对中英文都适用）
        for i in range(len(text) - ngram + 1):
            m.update(text[i:i + ngram].encode('utf-8'))
        return m

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

    # ============ 数据合并 ============

    @classmethod
    def concat(cls, *sources: Union[str, 'DataTransformer']) -> 'DataTransformer':
        """
        拼接多个数据源。

        Args:
            *sources: 数据源，可以是文件路径或 DataTransformer 实例

        Returns:
            合并后的 DataTransformer

        Examples:
            >>> DataTransformer.concat("a.jsonl", "b.jsonl")
            >>> DataTransformer.concat(dt1, dt2, dt3)
            >>> DataTransformer.concat("a.jsonl", dt2)
        """
        if not sources:
            return cls([])

        all_data = []
        for source in sources:
            if isinstance(source, str):
                data = load_data(source)
            elif isinstance(source, DataTransformer):
                data = source.data
            else:
                raise TypeError(f"不支持的数据源类型: {type(source)}")
            all_data.extend(data)

        return cls(all_data)

    def __add__(self, other: Union[str, 'DataTransformer']) -> 'DataTransformer':
        """
        使用 + 运算符拼接数据。

        Examples:
            >>> merged = dt1 + dt2
            >>> merged = dt1 + "other.jsonl"
        """
        return DataTransformer.concat(self, other)

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

    # ============ 并行处理 ============

    def map_parallel(
        self,
        func: Callable[[Dict], Any],
        workers: Optional[int] = None,
        chunksize: int = 1000,
    ) -> List[Any]:
        """
        并行执行转换函数（使用多进程）。

        注意：func 必须是可 pickle 的（不能是 lambda，需要是模块级函数）。

        Args:
            func: 转换函数，接收原始 dict，返回转换结果
            workers: 进程数，默认为 CPU 核心数
            chunksize: 每个进程处理的数据块大小

        Returns:
            转换后的结果列表

        Examples:
            >>> def transform(item):
            ...     return {"id": item["id"], "text": item["text"].upper()}
            >>> results = dt.map_parallel(transform)
        """
        from multiprocessing import Pool, cpu_count

        if not self._data:
            return []

        workers = workers or cpu_count()

        with Pool(workers) as pool:
            results = pool.map(func, self._data, chunksize=chunksize)

        return results

    def filter_parallel(
        self,
        func: Callable[[Dict], bool],
        workers: Optional[int] = None,
        chunksize: int = 1000,
    ) -> 'DataTransformer':
        """
        并行执行过滤函数（使用多进程）。

        注意：func 必须是可 pickle 的（不能是 lambda，需要是模块级函数）。

        Args:
            func: 过滤函数，接收原始 dict，返回 True 保留
            workers: 进程数，默认为 CPU 核心数
            chunksize: 每个进程处理的数据块大小

        Returns:
            过滤后的新 DataTransformer

        Examples:
            >>> def is_valid(item):
            ...     return len(item["text"]) > 10
            >>> filtered = dt.filter_parallel(is_valid)
        """
        from multiprocessing import Pool, cpu_count

        if not self._data:
            return DataTransformer([])

        workers = workers or cpu_count()

        with Pool(workers) as pool:
            mask = pool.map(func, self._data, chunksize=chunksize)

        filtered = [item for item, keep in zip(self._data, mask) if keep]
        return DataTransformer(filtered)


def _sanitize_key(name: str) -> str:
    """将字段名规范化为合法的 Python 标识符"""
    if name.isidentifier():
        return name
    sanitized = name.replace("-", "_").replace(" ", "_").replace(".", "_")
    if sanitized and sanitized[0].isdigit():
        sanitized = "f_" + sanitized
    sanitized = "".join(c if c.isalnum() or c == "_" else "_" for c in sanitized)
    return sanitized or "field"


class DictWrapper:
    """
    字典包装器，支持属性访问。

    支持通过规范化后的字段名访问原始键（如 item.原始_风险大类 访问 "原始-风险大类"）。

    Examples:
        >>> w = DictWrapper({"a": {"b": 1}})
        >>> w.a.b  # 1
        >>> w["a"]["b"]  # 1
        >>> w = DictWrapper({"原始-风险": "值"})
        >>> w.原始_风险  # "值"
    """

    def __init__(self, data: Dict[str, Any]):
        object.__setattr__(self, '_data', data)
        # 构建规范化名称到原始名称的映射
        alias_map = {}
        for key in data.keys():
            sanitized = _sanitize_key(key)
            if sanitized != key:
                alias_map[sanitized] = key
        object.__setattr__(self, '_alias_map', alias_map)

    def __getattr__(self, name: str) -> Any:
        data = object.__getattribute__(self, '_data')
        alias_map = object.__getattribute__(self, '_alias_map')

        # 先尝试直接匹配
        if name in data:
            value = data[name]
            if isinstance(value, dict):
                return DictWrapper(value)
            return value

        # 再尝试通过别名映射
        if name in alias_map:
            value = data[alias_map[name]]
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
