"""
DataTransformer 核心模块

专注于数据格式转换，提供简洁的 API。
"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Union

import orjson

from .lineage import LineageTracker
from .storage.io import load_data, save_data
from .utils.field_path import get_field_with_spec


def _fast_json_dumps(obj: Any) -> str:
    """快速 JSON 序列化（使用 orjson，比标准 json 快约 10 倍）"""
    return orjson.dumps(obj, option=orjson.OPT_SORT_KEYS).decode("utf-8")


# ============ 错误处理 ============


@dataclass
class TransformError:
    """转换错误信息"""

    index: int  # 原始数据索引
    item: Dict  # 原始数据项
    error: Exception  # 异常对象

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
        return (
            f"转换失败 {len(self.errors)} 条记录:\n"
            + "\n".join(f"  [{e.index}] {e.error}" for e in self.errors[:5])
            + (f"\n  ... 还有 {len(self.errors) - 5} 条错误" if len(self.errors) > 5 else "")
        )

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

    def __init__(
        self,
        data: Optional[List[Dict[str, Any]]] = None,
        _source_path: Optional[str] = None,
        _lineage_tracker: Optional[LineageTracker] = None,
    ):
        self._data = data if data is not None else []
        self._source_path = _source_path
        self._lineage_tracker = _lineage_tracker

    @property
    def _is_persistent(self) -> bool:
        """后端是否为持久化存储 (FlaxList)"""
        try:
            from flaxkv2 import FlaxList

            return isinstance(self._data, FlaxList)
        except ImportError:
            return False

    @property
    def data(self) -> List[Dict[str, Any]]:
        """获取原始数据（FlaxList 后端会物化为 list）"""
        if self._is_persistent:
            return self._data.to_list()
        return self._data

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, idx: Union[int, slice]) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        return self._data[idx]

    def __repr__(self) -> str:
        return f"DataTransformer({len(self._data)} items)"

    # ============ 加载/保存 ============

    @classmethod
    def load(cls, filepath: str, track_lineage: bool = False) -> "DataTransformer":
        """
        从文件加载数据。

        支持格式: jsonl, json, csv, parquet, flaxkv（自动检测）
        .kv/.flaxkv 格式使用 FlaxList 持久化后端，不物化到内存。

        Args:
            filepath: 文件路径
            track_lineage: 是否追踪血缘（默认 False）
        """
        from pathlib import Path

        from .storage.io import _detect_format, _open_flaxlist

        fmt = _detect_format(Path(filepath))
        if fmt == "flaxkv":
            db_dir = Path(filepath).parent / (Path(filepath).stem or "data")
            if not db_dir.exists():
                raise FileNotFoundError(f"FlaxKV database not found: {db_dir}")
            data = _open_flaxlist(Path(filepath))
        else:
            data = load_data(filepath)
        tracker = LineageTracker(filepath) if track_lineage else None
        return cls(data, _source_path=filepath, _lineage_tracker=tracker)

    def save(self, filepath: str, lineage: bool = False) -> None:
        """
        保存数据到文件。

        支持格式: jsonl, json, csv, parquet, flaxkv（根据扩展名）
        FlaxList 后端保存到同路径时为无操作（数据已自动持久化）。

        Args:
            filepath: 文件路径
            lineage: 是否保存血缘元数据（默认 False）
        """
        from pathlib import Path

        # 同路径 + FlaxList 后端 → 无操作（已自动持久化）
        if self._is_persistent and self._source_path:
            if Path(filepath).resolve() == Path(self._source_path).resolve():
                return

        save_data(self._data, filepath)

        # 保存血缘记录
        if lineage and self._lineage_tracker:
            lineage_path = self._lineage_tracker.save(filepath, len(self._data))
            import sys

            print(f"📜 血缘记录已保存: {lineage_path}", file=sys.stderr)

    # ============ 增量操作 ============

    def append(self, item: Dict) -> "DataTransformer":
        """追加一条数据。FlaxList 后端原地追加并返回 self，list 后端返回新实例。"""
        if self._is_persistent:
            self._data.append(item)
            return self
        return DataTransformer(self._data + [item])

    def extend(self, items) -> "DataTransformer":
        """批量追加数据。FlaxList 后端原地追加并返回 self，list 后端返回新实例。"""
        if isinstance(items, DataTransformer):
            items = items.data
        if self._is_persistent:
            self._data.extend(items)
            return self
        return DataTransformer(self._data + list(items))

    # ============ 资源管理 ============

    def close(self):
        """关闭持久化后端资源"""
        if self._is_persistent:
            self._data.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

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
    ) -> "DataTransformer":
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
        input_count = len(self._data)
        result = self.to(func, on_error=on_error, raw=raw)
        output_count = len(result)

        # 传递血缘追踪器并记录操作
        tracker = self._lineage_tracker
        if tracker:
            tracker.record("transform", {"func": func}, input_count, output_count)

        return DataTransformer(result, _lineage_tracker=tracker)

    # ============ 数据筛选 ============

    def filter(
        self,
        func: Callable[[Any], bool],
        on_error: Literal["skip", "raise", "keep"] = "skip",
        raw: bool = False,
    ) -> "DataTransformer":
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

        # 传递血缘追踪器并记录操作
        tracker = self._lineage_tracker
        if tracker:
            tracker.record("filter", {"func": func}, len(self._data), len(filtered))

        return DataTransformer(filtered, _lineage_tracker=tracker)

    def sample(self, n: int, seed: Optional[int] = None) -> "DataTransformer":
        """
        随机采样 n 条数据。

        Args:
            n: 采样数量
            seed: 随机种子
        """
        import random

        if seed is not None:
            random.seed(seed)

        input_count = len(self._data)
        if n >= input_count:
            data = self._data[:] if not self._is_persistent else self._data.to_list()
        elif self._is_persistent:
            # FlaxList 不是 abc.Sequence，用随机索引 + O(1) 随机访问
            indices = random.sample(range(input_count), n)
            data = [self._data[i] for i in indices]
        else:
            data = random.sample(self._data, n)

        tracker = self._lineage_tracker
        if tracker:
            tracker.record("sample", {"n": n, "seed": seed}, input_count, len(data))

        return DataTransformer(data, _lineage_tracker=tracker)

    def head(self, n: int = 10) -> "DataTransformer":
        """取前 n 条"""
        data = self._data[:n]
        tracker = self._lineage_tracker
        if tracker:
            tracker.record("head", {"n": n}, len(self._data), len(data))
        return DataTransformer(data, _lineage_tracker=tracker)

    def tail(self, n: int = 10) -> "DataTransformer":
        """取后 n 条"""
        data = self._data[-n:]
        tracker = self._lineage_tracker
        if tracker:
            tracker.record("tail", {"n": n}, len(self._data), len(data))
        return DataTransformer(data, _lineage_tracker=tracker)

    def validate(
        self,
        func: Callable[[Any], bool],
        raw: bool = False,
    ) -> List[TransformError]:
        """
        验证数据，返回不通过的记录列表。

        Args:
            func: 验证函数，返回 True 表示通过，False 表示失败
            raw: 原始模式，跳过 DictWrapper 包装

        Returns:
            验证失败的记录列表（TransformError）

        Examples:
            >>> dt = DataTransformer([{"a": 1}, {"a": -1}])
            >>> errors = dt.validate(lambda x: x.a > 0)
            >>> len(errors)  # 1
            >>> errors[0].index  # 1
        """
        errors = []
        wrapper_func = (lambda x: x) if raw else DictWrapper

        for i, item in enumerate(self._data):
            try:
                if not func(wrapper_func(item)):
                    errors.append(
                        TransformError(index=i, item=item, error=ValueError("验证未通过"))
                    )
            except Exception as e:
                errors.append(TransformError(index=i, item=item, error=e))

        return errors

    def validate_schema(
        self,
        schema: "Schema",  # noqa: F821
        on_error: Literal["skip", "raise", "filter"] = "skip",
        max_errors: int = 100,
    ) -> Union["DataTransformer", List[tuple]]:
        """
        使用 Schema 验证数据结构。

        Args:
            schema: Schema 对象，定义数据结构验证规则
            on_error: 错误处理方式
                - "skip": 打印警告，返回验证失败的记录列表
                - "raise": 第一个错误时抛出异常
                - "filter": 过滤掉验证失败的记录，返回新的 DataTransformer
            max_errors: 最大错误数量（on_error="skip" 时生效）

        Returns:
            - on_error="skip": 返回 [(index, ValidationResult), ...] 失败记录列表
            - on_error="raise": 无返回（成功）或抛出 ValueError
            - on_error="filter": 返回过滤后的新 DataTransformer

        Examples:
            >>> from dtflow import Schema, Field
            >>> schema = Schema({
            ...     "messages": Field(type="list", required=True, min_length=1),
            ...     "messages[*].role": Field(type="str", choices=["user", "assistant"]),
            ... })

            >>> # 获取验证失败的记录
            >>> errors = dt.validate_schema(schema)
            >>> for idx, result in errors:
            ...     print(f"第 {idx} 行验证失败: {result.errors}")

            >>> # 过滤掉无效记录
            >>> valid_dt = dt.validate_schema(schema, on_error="filter")

            >>> # 遇到错误立即停止
            >>> dt.validate_schema(schema, on_error="raise")
        """
        from .schema import Schema  # noqa: F401

        failed: List[tuple] = []
        valid_data: List[dict] = []
        error_count = 0

        for i, item in enumerate(self._data):
            result = schema.validate(item)
            if result.valid:
                valid_data.append(item)
            else:
                failed.append((i, result))
                error_count += len(result.errors)

                if on_error == "raise":
                    error_msgs = [str(e) for e in result.errors[:3]]
                    raise ValueError(f"第 {i} 行验证失败:\n  " + "\n  ".join(error_msgs))

                if on_error == "skip" and error_count >= max_errors:
                    print(f"⚠️ 已达到最大错误数 {max_errors}，停止验证")
                    break

        if on_error == "skip":
            if failed:
                print(f"⚠️ 验证失败 {len(failed)} 条记录（共 {error_count} 个错误）")
            return failed

        if on_error == "filter":
            tracker = self._lineage_tracker
            if tracker:
                tracker.record(
                    "validate_schema",
                    {"schema": repr(schema), "on_error": on_error},
                    len(self._data),
                    len(valid_data),
                )
            return DataTransformer(valid_data, _lineage_tracker=tracker)

        return failed

    def dedupe(
        self,
        key: Union[None, str, List[str], Callable[[Any], Any]] = None,
    ) -> "DataTransformer":
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

        tracker = self._lineage_tracker
        if tracker:
            tracker.record("dedupe", {"key": key}, len(self._data), len(result))

        return DataTransformer(result, _lineage_tracker=tracker)

    def _get_dedupe_key(
        self,
        item: Dict[str, Any],
        key: Union[None, str, List[str], Callable[[Any], Any]],
    ) -> Any:
        """
        获取去重用的 key。

        支持字段路径语法：
            - meta.source        嵌套字段
            - messages[0].role   数组索引
            - messages[-1].role  负索引
            - messages.#         数组长度
            - messages[*].role   展开所有元素（可加 :join/:unique 模式）
        """
        if key is None:
            # 全量去重：使用快速 JSON 序列化
            return _fast_json_dumps(item)
        elif isinstance(key, str):
            # 单字段（支持嵌套路径）
            val = get_field_with_spec(item, key)
            # 确保可哈希
            if isinstance(val, list):
                return tuple(val)
            return val
        elif isinstance(key, list):
            # 多字段组合（每个字段都支持嵌套路径）
            vals = []
            for k in key:
                v = get_field_with_spec(item, k)
                if isinstance(v, list):
                    v = tuple(v)
                vals.append(v)
            return tuple(vals)
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
    ) -> "DataTransformer":
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
            from datasketch import MinHashLSH
        except ImportError as e:
            raise ImportError("相似度去重需要 datasketch 库，请安装: pip install datasketch") from e

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
                UserWarning,
                stacklevel=2,
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

        tracker = self._lineage_tracker
        if tracker:
            tracker.record(
                "dedupe_similar",
                {"key": key, "threshold": threshold, "num_perm": num_perm, "ngram": ngram},
                len(self._data),
                len(result),
            )

        return DataTransformer(result, _lineage_tracker=tracker)

    def _get_text_for_similarity(
        self,
        item: Dict[str, Any],
        key: Union[str, Callable[[Any], str]],
    ) -> str:
        """
        获取用于相似度比较的文本。

        支持字段路径语法（同 _get_dedupe_key）。
        """
        if isinstance(key, str):
            val = get_field_with_spec(item, key, default="")
            return str(val) if val else ""
        elif callable(key):
            return str(key(DictWrapper(item)))
        else:
            raise ValueError(f"不支持的 key 类型: {type(key)}")

    def _create_minhash(self, text: str, num_perm: int, ngram: int):
        """创建文本的 MinHash 签名"""
        from datasketch import MinHash

        m = MinHash(num_perm=num_perm)
        # 使用字符级 n-gram（对中英文都适用）
        for i in range(len(text) - ngram + 1):
            m.update(text[i : i + ngram].encode("utf-8"))
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

    def _extract_fields(self, obj: Any, prefix: str = "") -> List[str]:
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
                "type": type(values[0]).__name__ if values else "unknown",
            }

        return {"total": len(self._data), "fields": sorted(all_keys), "field_stats": field_stats}

    # ============ 工具方法 ============

    def copy(self) -> "DataTransformer":
        """深拷贝（FlaxList 后端物化为 list）"""
        if self._is_persistent:
            return DataTransformer(self._data.to_list())
        return DataTransformer(deepcopy(self._data))

    # ============ 数据合并 ============

    @classmethod
    def concat(cls, *sources: Union[str, "DataTransformer"]) -> "DataTransformer":
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

    def __add__(self, other: Union[str, "DataTransformer"]) -> "DataTransformer":
        """
        使用 + 运算符拼接数据。

        Examples:
            >>> merged = dt1 + dt2
            >>> merged = dt1 + "other.jsonl"
        """
        return DataTransformer.concat(self, other)

    def shuffle(self, seed: Optional[int] = None) -> "DataTransformer":
        """打乱顺序（返回新实例）"""
        import random

        data = self._data[:]
        if seed is not None:
            random.seed(seed)
        random.shuffle(data)

        tracker = self._lineage_tracker
        if tracker:
            tracker.record("shuffle", {"seed": seed}, len(self._data), len(data))

        return DataTransformer(data, _lineage_tracker=tracker)

    def split(self, ratio: float = 0.8, seed: Optional[int] = None) -> tuple:
        """
        分割数据集。

        Args:
            ratio: 第一部分的比例
            seed: 随机种子

        Returns:
            (train, test) 两个 DataTransformer，各自拥有独立的血缘追踪器
        """
        data = self.shuffle(seed).data
        split_idx = int(len(data) * ratio)

        # 分割后血缘追踪器各自独立（使用深拷贝避免相互影响）
        tracker = self._lineage_tracker
        train_tracker = None
        test_tracker = None

        if tracker:
            tracker.record("split", {"ratio": ratio, "seed": seed}, len(self._data), len(data))
            # 为每个子数据集创建独立的追踪器副本
            train_tracker = tracker.copy()
            train_tracker.record(
                "split_part", {"part": "train", "ratio": ratio}, len(data), split_idx
            )
            test_tracker = tracker.copy()
            test_tracker.record(
                "split_part", {"part": "test", "ratio": 1 - ratio}, len(data), len(data) - split_idx
            )

        return (
            DataTransformer(data[:split_idx], _lineage_tracker=train_tracker),
            DataTransformer(data[split_idx:], _lineage_tracker=test_tracker),
        )

    # ============ 并行处理 ============

    def map_parallel(
        self,
        func: Callable[[Dict], Any],
        workers: Optional[int] = None,
        chunksize: int = 1000,
        timeout: Optional[float] = None,
    ) -> List[Any]:
        """
        并行执行转换函数（使用多进程）。

        注意：func 必须是可 pickle 的（不能是 lambda，需要是模块级函数）。

        Args:
            func: 转换函数，接收原始 dict，返回转换结果
            workers: 进程数，默认为 CPU 核心数
            chunksize: 每个进程处理的数据块大小
            timeout: 超时时间（秒），None 表示无超时

        Returns:
            转换后的结果列表

        Raises:
            TypeError: 如果 func 无法被 pickle（如 lambda 函数）
            RuntimeError: 如果子进程执行出错或超时

        Examples:
            >>> def transform(item):
            ...     return {"id": item["id"], "text": item["text"].upper()}
            >>> results = dt.map_parallel(transform)
        """
        import pickle
        from multiprocessing import Pool, TimeoutError, cpu_count

        if not self._data:
            return []

        # 检查函数是否可 pickle
        try:
            pickle.dumps(func)
        except (pickle.PicklingError, AttributeError, TypeError) as e:
            func_name = getattr(func, "__name__", str(func))
            raise TypeError(
                f"函数 '{func_name}' 无法被 pickle，不能用于并行处理。"
                f"请使用模块级函数而非 lambda 或闭包。错误: {e}"
            ) from e

        workers = workers or cpu_count()

        try:
            with Pool(workers) as pool:
                async_result = pool.map_async(func, self._data, chunksize=chunksize)
                results = async_result.get(timeout=timeout)
        except TimeoutError as e:
            raise RuntimeError(f"并行处理超时（{timeout}秒）") from e
        except Exception as e:
            raise RuntimeError(f"并行处理失败: {type(e).__name__}: {e}") from e

        return results

    def filter_parallel(
        self,
        func: Callable[[Dict], bool],
        workers: Optional[int] = None,
        chunksize: int = 1000,
        timeout: Optional[float] = None,
    ) -> "DataTransformer":
        """
        并行执行过滤函数（使用多进程）。

        注意：func 必须是可 pickle 的（不能是 lambda，需要是模块级函数）。

        Args:
            func: 过滤函数，接收原始 dict，返回 True 保留
            workers: 进程数，默认为 CPU 核心数
            chunksize: 每个进程处理的数据块大小
            timeout: 超时时间（秒），None 表示无超时

        Returns:
            过滤后的新 DataTransformer

        Raises:
            TypeError: 如果 func 无法被 pickle（如 lambda 函数）
            RuntimeError: 如果子进程执行出错或超时

        Examples:
            >>> def is_valid(item):
            ...     return len(item["text"]) > 10
            >>> filtered = dt.filter_parallel(is_valid)
        """
        import pickle
        from multiprocessing import Pool, TimeoutError, cpu_count

        if not self._data:
            return DataTransformer([])

        # 检查函数是否可 pickle
        try:
            pickle.dumps(func)
        except (pickle.PicklingError, AttributeError, TypeError) as e:
            func_name = getattr(func, "__name__", str(func))
            raise TypeError(
                f"函数 '{func_name}' 无法被 pickle，不能用于并行处理。"
                f"请使用模块级函数而非 lambda 或闭包。错误: {e}"
            ) from e

        workers = workers or cpu_count()

        try:
            with Pool(workers) as pool:
                async_result = pool.map_async(func, self._data, chunksize=chunksize)
                mask = async_result.get(timeout=timeout)
        except TimeoutError as e:
            raise RuntimeError(f"并行处理超时（{timeout}秒）") from e
        except Exception as e:
            raise RuntimeError(f"并行处理失败: {type(e).__name__}: {e}") from e

        filtered = [item for item, keep in zip(self._data, mask) if keep]
        return DataTransformer(filtered)

    # ============ 训练框架集成 ============

    def check_compatibility(
        self,
        framework: Literal["llama-factory", "swift", "axolotl"],
    ):
        """
        检查数据与目标训练框架的兼容性。

        Args:
            framework: 目标框架名称
                - "llama-factory": LLaMA-Factory
                - "swift": ms-swift (ModelScope)
                - "axolotl": Axolotl

        Returns:
            CompatibilityResult 对象，包含 valid, errors, warnings, suggestions

        Examples:
            >>> result = dt.check_compatibility("llama-factory")
            >>> if result.valid:
            ...     print("兼容!")
            >>> else:
            ...     print(result.errors)
        """
        from .framework import check_compatibility

        return check_compatibility(self._data, framework)

    def export_for(
        self,
        framework: Literal["llama-factory", "swift", "axolotl"],
        output_dir: str,
        dataset_name: str = "custom_dataset",
        **kwargs,
    ) -> Dict[str, str]:
        """
        一键导出数据和配置文件到目标训练框架。

        Args:
            framework: 目标框架名称
            output_dir: 输出目录
            dataset_name: 数据集名称
            **kwargs: 框架特定参数（如 model_name）

        Returns:
            生成的文件路径字典 {"data": "...", "config": "...", ...}

        Examples:
            >>> # 导出到 LLaMA-Factory
            >>> dt.export_for("llama-factory", "./llama_ready")
            # 生成:
            # - ./llama_ready/custom_dataset.json
            # - ./llama_ready/dataset_info.json
            # - ./llama_ready/train_args.yaml

            >>> # 导出到 ms-swift
            >>> dt.export_for("swift", "./swift_ready", dataset_name="my_data")

            >>> # 导出到 Axolotl
            >>> dt.export_for("axolotl", "./axolotl_ready")
        """
        from .framework import export_for

        return export_for(
            self._data,
            framework,
            output_dir,
            dataset_name=dataset_name,
            **kwargs,
        )


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
        object.__setattr__(self, "_data", data)
        # 构建规范化名称到原始名称的映射
        alias_map = {}
        for key in data.keys():
            sanitized = _sanitize_key(key)
            if sanitized != key:
                alias_map[sanitized] = key
        object.__setattr__(self, "_alias_map", alias_map)

    def __getattr__(self, name: str) -> Any:
        data = object.__getattribute__(self, "_data")
        alias_map = object.__getattribute__(self, "_alias_map")

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
        data = object.__getattribute__(self, "_data")
        value = data[key]
        if isinstance(value, dict):
            return DictWrapper(value)
        return value

    def __contains__(self, key: str) -> bool:
        data = object.__getattribute__(self, "_data")
        return key in data

    def __repr__(self) -> str:
        data = object.__getattribute__(self, "_data")
        return repr(data)

    def get(self, key: str, default: Any = None) -> Any:
        """安全获取字段值"""
        data = object.__getattribute__(self, "_data")
        value = data.get(key, default)
        if isinstance(value, dict):
            return DictWrapper(value)
        return value

    def to_dict(self) -> Dict[str, Any]:
        """返回原始字典"""
        return object.__getattribute__(self, "_data")
