"""
流式处理模块

支持大文件的惰性处理，避免全量加载内存。
支持格式：JSONL, CSV, Parquet, Arrow
"""

import collections
import glob
import os
import random
from pathlib import Path
from typing import Any, Callable, Dict, Generator, Iterator, List, Literal, Optional, Union

import orjson
import polars as pl
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

# 支持的流式格式。分发一律走 storage.io._detect_format, 不再各处比较扩展名字符串 ——
# "这是什么格式"只该有一个答案, 分散成 5 处 ext== 比较, 新格式必然漏掉其中几处
# (.ndjson 就是这么掉出流式路径的: 它和 .jsonl 是同一种东西, 却因为字符串不等而全量入内存)。
STREAMING_FORMATS = {
    ".jsonl",
    ".ndjson",
    ".csv",
    ".tsv",
    ".parquet",
    ".arrow",
    ".feather",
    ".flaxkv",
    ".kv",
}


def _fmt_of(filepath) -> str:
    """该文件的规范格式名 (jsonl/csv/tsv/parquet/arrow/excel/json/flaxkv)。"""
    from dtflow.storage.io import _detect_format

    return _detect_format(Path(filepath))


def _is_flaxkv_path(path: Path) -> bool:
    """判断路径是否为 flaxkv（.flaxkv 后缀或无后缀且 DB 目录存在）"""
    ext = path.suffix.lower()
    if ext in (".flaxkv", ".kv"):
        return True
    if ext == "":
        db_dir = path.parent / (path.stem or "data")
        return db_dir.exists()
    return False


def _count_rows_fast(filepath: str) -> Optional[int]:
    """快速统计文件行数（不加载数据）"""
    path = Path(filepath)
    ext = path.suffix.lower()
    fmt = _fmt_of(path)

    try:
        if fmt == "jsonl":
            from .utils.jsonl import count_jsonl_rows

            return count_jsonl_rows(path)
        elif fmt in ("csv", "tsv"):
            # CSV/TSV: Polars LazyFrame
            sep = "\t" if fmt == "tsv" else ","
            return pl.scan_csv(filepath, separator=sep).select(pl.len()).collect().item()
        elif ext == ".parquet":
            # Parquet: Polars LazyFrame
            return pl.scan_parquet(filepath).select(pl.len()).collect().item()
        elif ext in (".arrow", ".feather"):
            # Arrow: Polars LazyFrame
            return pl.scan_ipc(filepath).select(pl.len()).collect().item()
        elif ext in (".xlsx", ".xls"):
            # Excel: 无 lazy scan，只能全量读取
            return pl.read_excel(filepath).height
        elif ext == ".json":
            # JSON: 整体是一个数组，必须全量解析
            import orjson

            with open(filepath, "rb") as f:
                obj = orjson.loads(f.read())
            return len(obj) if isinstance(obj, list) else 1
        elif ext in (".flaxkv", ".kv") or _is_flaxkv_path(path):
            from dtflow.storage.io import _open_flaxlist

            with _open_flaxlist(path) as lst:
                return len(lst)
    except Exception:
        pass
    return None


class StreamingTransformer:
    """
    流式数据转换器。

    使用 generator 实现惰性处理，适合处理超大文件。
    内存占用 O(1)，不会随文件大小增长。

    Examples:
        >>> st = StreamingTransformer.load_stream("huge_100gb.jsonl")
        >>> (st
        ...     .filter(lambda x: x["score"] > 0.5)
        ...     .transform(lambda x: {"text": x["content"]})
        ...     .save("output.jsonl"))
    """

    def __init__(
        self,
        iterator: Iterator[Dict[str, Any]],
        source_path: Optional[str] = None,
        total: Optional[int] = None,
    ):
        """
        初始化流式转换器。

        Args:
            iterator: 数据迭代器
            source_path: 源文件路径（用于元数据）
            total: 总行数（用于进度条，可选）
        """
        self._iterator = iterator
        self._source_path = source_path
        self._total = total
        self._operations: List[Dict[str, Any]] = []
        self._error_count = 0
        self._first_error: Optional[str] = None

    @classmethod
    def load_stream(cls, filepath: str, batch_size: int = 10000) -> "StreamingTransformer":
        """
        流式加载文件。

        支持 JSONL、CSV、Parquet、Arrow 格式。

        Args:
            filepath: 文件路径
            batch_size: 批量读取大小（CSV/Parquet/Arrow）

        Returns:
            StreamingTransformer 实例
        """
        path = Path(filepath)
        ext = path.suffix.lower()
        is_flaxkv = _is_flaxkv_path(path)

        # 存在性检查：flaxkv 检查 DB 目录，其他格式检查文件
        if is_flaxkv:
            db_dir = path.parent / (path.stem or "data")
            if not db_dir.exists():
                raise FileNotFoundError(f"FlaxKV 数据库不存在: {db_dir}")
        elif not path.exists():
            raise FileNotFoundError(f"文件不存在: {filepath}")

        if ext not in STREAMING_FORMATS and not is_flaxkv:
            raise ValueError(f"不支持的流式格式: {ext}，支持: {STREAMING_FORMATS}")

        # 快速统计总行数（用于进度条）
        total = _count_rows_fast(filepath)

        fmt = _fmt_of(filepath)
        if is_flaxkv:
            return cls(_stream_flaxkv(filepath), source_path=filepath, total=total)
        elif fmt == "jsonl":
            return cls(_stream_jsonl(filepath), source_path=filepath, total=total)
        elif fmt in ("csv", "tsv"):
            sep = "\t" if fmt == "tsv" else ","
            return cls(
                _stream_csv(filepath, batch_size, separator=sep),
                source_path=filepath,
                total=total,
            )
        elif fmt == "parquet":
            return cls(_stream_parquet(filepath, batch_size), source_path=filepath, total=total)
        elif fmt == "arrow":
            return cls(_stream_arrow(filepath), source_path=filepath, total=total)
        else:
            raise ValueError(f"未知格式: {ext}")

    @classmethod
    def load_sharded(cls, pattern: str, batch_size: int = 10000) -> "StreamingTransformer":
        """
        加载分片文件（支持 glob 模式）。

        支持 JSONL、CSV、Parquet、Arrow 格式（根据扩展名自动检测）。

        Args:
            pattern: glob 模式，如 "data_*.jsonl" 或 "shards/part-*.parquet"
            batch_size: 批量读取大小（CSV/Parquet/Arrow）

        Returns:
            StreamingTransformer 实例

        Examples:
            >>> st = StreamingTransformer.load_sharded("data/train_*.jsonl")
            >>> st = StreamingTransformer.load_sharded("shards/part-*.parquet")
        """
        files = sorted(glob.glob(pattern))
        if not files:
            raise FileNotFoundError(f"没有匹配的文件: {pattern}")

        def generator():
            for filepath in files:
                fmt = _fmt_of(filepath)
                if fmt in ("csv", "tsv"):
                    yield from _stream_csv(
                        filepath, batch_size, separator="\t" if fmt == "tsv" else ","
                    )
                elif fmt == "parquet":
                    yield from _stream_parquet(filepath, batch_size)
                elif fmt == "arrow":
                    yield from _stream_arrow(filepath)
                else:
                    # jsonl/ndjson 及未知扩展名: 一律按 JSONL 读 (与 _detect_format 一致)
                    yield from _stream_jsonl(filepath)

        return cls(generator(), source_path=pattern)

    def filter(
        self,
        func: Callable[[Any], bool],
        on_error: Literal["skip", "raise", "keep"] = "skip",
        raw: bool = False,
    ) -> "StreamingTransformer":
        """
        惰性过滤。

        Args:
            func: 过滤函数，返回 True 保留，默认支持属性访问 (item.field)
            on_error: 错误处理策略
                - "skip": 跳过错误行（默认）
                - "raise": 遇到错误立即抛出
                - "keep": 保留错误行
            raw: 原始模式，直接传递 dict 而不包装为 DictWrapper

        Returns:
            新的 StreamingTransformer（惰性，不立即执行）

        Examples:
            >>> load_stream("data.kv").filter(lambda x: x.score > 0.5).save("out.jsonl")
            >>> load_stream("data.kv").filter(lambda x: x["id"] < 100, raw=True)
        """
        from .core import DictWrapper

        wrapper_func = (lambda x: x) if raw else DictWrapper

        def filtered_iterator():
            for item in self._iterator:
                try:
                    if func(wrapper_func(item)):
                        yield item
                except Exception:
                    if on_error == "raise":
                        raise
                    elif on_error == "keep":
                        yield item

        # 过滤后数量未知，不传递 total
        new_st = StreamingTransformer(filtered_iterator(), self._source_path, total=None)
        new_st._operations = self._operations + [{"type": "filter", "func": func}]
        return new_st

    def transform(
        self,
        func: Callable[[Any], Dict],
        on_error: Literal["skip", "raise"] = "skip",
        raw: bool = False,
    ) -> "StreamingTransformer":
        """
        惰性转换。

        Args:
            func: 转换函数，默认支持属性访问 (item.field)
            on_error: 错误处理策略
                - "skip": 跳过错误行（默认）
                - "raise": 遇到错误立即抛出
            raw: 原始模式，直接传递 dict 而不包装为 DictWrapper

        Returns:
            新的 StreamingTransformer（惰性，不立即执行）
        """
        from .core import DictWrapper

        wrapper_func = (lambda x: x) if raw else DictWrapper

        # on_error="skip" 时可能跳行，total 不准确；"raise" 时保留
        new_total = self._total if on_error == "raise" else None
        new_st = StreamingTransformer(iter([]), self._source_path, total=new_total)
        new_st._operations = self._operations + [{"type": "transform", "func": func}]

        def transformed_iterator():
            for item in self._iterator:
                try:
                    yield func(wrapper_func(item))
                except Exception as e:
                    if on_error == "raise":
                        raise
                    new_st._error_count += 1
                    if new_st._first_error is None:
                        new_st._first_error = f"{type(e).__name__}: {e}"

        new_st._iterator = transformed_iterator()
        return new_st

    def head(self, n: int) -> "StreamingTransformer":
        """
        惰性取前 N 条。

        Args:
            n: 数量

        Returns:
            新的 StreamingTransformer
        """

        def head_iterator():
            count = 0
            for item in self._iterator:
                if count >= n:
                    break
                yield item
                count += 1

        # head(n) 的 total 是 min(n, original_total)
        new_total = min(n, self._total) if self._total is not None else n
        new_st = StreamingTransformer(head_iterator(), self._source_path, total=new_total)
        new_st._operations = self._operations + [{"type": "head", "n": n}]
        return new_st

    def skip(self, n: int) -> "StreamingTransformer":
        """
        惰性跳过前 N 条。

        Args:
            n: 跳过数量

        Returns:
            新的 StreamingTransformer
        """

        def skip_iterator():
            count = 0
            for item in self._iterator:
                if count < n:
                    count += 1
                    continue
                yield item

        # skip(n) 的 total 是 max(0, original_total - n)
        new_total = max(0, self._total - n) if self._total is not None else None
        new_st = StreamingTransformer(skip_iterator(), self._source_path, total=new_total)
        new_st._operations = self._operations + [{"type": "skip", "n": n}]
        return new_st

    def dedupe(
        self,
        key: Union[None, str, List[str], Callable[[Any], Any]] = None,
        raw: bool = False,
    ) -> "StreamingTransformer":
        """
        流式精确去重。

        维护 seen set，O(unique_keys) 内存。

        Args:
            key: 去重依据，可以是：
                - None: 全量去重（整条数据比较）
                - str: 按单个字段去重（支持嵌套路径语法）
                - list[str]: 按多个字段组合去重
                - callable: 自定义 key 函数
            raw: callable key 时是否跳过 DictWrapper

        Returns:
            新的 StreamingTransformer
        """
        from .core import DictWrapper, _fast_json_dumps
        from .utils.field_path import get_field_with_spec

        wrapper_func = (lambda x: x) if raw else DictWrapper

        def _extract_key(item):
            if key is None:
                return _fast_json_dumps(item)
            elif isinstance(key, str):
                val = get_field_with_spec(item, key)
                return tuple(val) if isinstance(val, list) else val
            elif isinstance(key, list):
                vals = []
                for k in key:
                    v = get_field_with_spec(item, k)
                    vals.append(tuple(v) if isinstance(v, list) else v)
                return tuple(vals)
            elif callable(key):
                return key(wrapper_func(item))
            else:
                raise ValueError(f"不支持的 key 类型: {type(key)}")

        def deduped_iterator():
            seen = set()
            for item in self._iterator:
                k = _extract_key(item)
                if k not in seen:
                    seen.add(k)
                    yield item

        new_st = StreamingTransformer(deduped_iterator(), self._source_path, total=None)
        new_st._operations = self._operations + [{"type": "dedupe", "key": key}]
        return new_st

    def flat_map(
        self,
        func: Callable[[Any], Any],
        on_error: Literal["skip", "raise"] = "skip",
        raw: bool = False,
    ) -> "StreamingTransformer":
        """
        一对多惰性变换。

        func 返回可迭代对象，每个元素 yield 为一条输出。
        典型场景：拆分多轮对话、展开嵌套数组。

        Args:
            func: 变换函数，返回可迭代对象
            on_error: 错误处理策略
            raw: 原始模式，跳过 DictWrapper

        Returns:
            新的 StreamingTransformer（total=None，无法预知输出数量）
        """
        from .core import DictWrapper

        wrapper_func = (lambda x: x) if raw else DictWrapper

        def flat_mapped_iterator():
            for item in self._iterator:
                try:
                    results = func(wrapper_func(item))
                    yield from results
                except Exception:
                    if on_error == "raise":
                        raise

        new_st = StreamingTransformer(flat_mapped_iterator(), self._source_path, total=None)
        new_st._operations = self._operations + [{"type": "flat_map", "func": func}]
        return new_st

    def tail(self, n: int) -> "StreamingTransformer":
        """
        惰性取最后 N 条。

        使用 deque(maxlen=n) 缓冲，O(n) 内存。

        Args:
            n: 数量

        Returns:
            新的 StreamingTransformer
        """

        def tail_iterator():
            buffer = collections.deque(self._iterator, maxlen=n)
            yield from buffer

        new_total = min(n, self._total) if self._total is not None else n
        new_st = StreamingTransformer(tail_iterator(), self._source_path, total=new_total)
        new_st._operations = self._operations + [{"type": "tail", "n": n}]
        return new_st

    def sample(self, n: int, seed: Optional[int] = None) -> "StreamingTransformer":
        """
        蓄水池采样（Algorithm R），不需要预知总数。

        O(n) 内存，使用独立 Random 实例避免污染全局状态。

        Args:
            n: 采样数量
            seed: 随机种子，用于可重现

        Returns:
            新的 StreamingTransformer
        """

        def sample_iterator():
            rng = random.Random(seed)
            reservoir = []
            for i, item in enumerate(self._iterator):
                if i < n:
                    reservoir.append(item)
                else:
                    j = rng.randint(0, i)
                    if j < n:
                        reservoir[j] = item
            yield from reservoir

        new_st = StreamingTransformer(sample_iterator(), self._source_path, total=n)
        new_st._operations = self._operations + [{"type": "sample", "n": n}]
        return new_st

    def peek(self, func: Callable[[Dict], None]) -> "StreamingTransformer":
        """
        管道调试：对每条数据执行副作用函数，不改变数据流。

        Args:
            func: 副作用函数（如 print）

        Returns:
            新的 StreamingTransformer（数据不变，保留 total）
        """

        def peek_iterator():
            for item in self._iterator:
                func(item)
                yield item

        new_st = StreamingTransformer(peek_iterator(), self._source_path, total=self._total)
        new_st._operations = self._operations + [{"type": "peek", "func": func}]
        return new_st

    def shuffle(self, seed: Optional[int] = None) -> "StreamingTransformer":
        """
        全量洗牌。

        需要将所有数据加载到内存，O(n) 内存。

        Args:
            seed: 随机种子

        Returns:
            新的 StreamingTransformer
        """

        def shuffle_iterator():
            data = list(self._iterator)
            rng = random.Random(seed)
            rng.shuffle(data)
            yield from data

        new_st = StreamingTransformer(shuffle_iterator(), self._source_path, total=self._total)
        new_st._operations = self._operations + [{"type": "shuffle"}]
        return new_st

    def split(
        self,
        ratios: List[float],
        seed: Optional[int] = None,
    ) -> List["StreamingTransformer"]:
        """
        按比例切分数据集。

        需要将所有数据加载到内存并洗牌后切分。

        Args:
            ratios: 切分比例列表，如 [0.8, 0.1, 0.1]
            seed: 随机种子

        Returns:
            StreamingTransformer 列表，与 ratios 一一对应

        Examples:
            >>> train, val, test = st.split([0.8, 0.1, 0.1])
        """
        # 归一化比例
        total_ratio = sum(ratios)
        normed = [r / total_ratio for r in ratios]

        # 消耗迭代器，洗牌
        data = list(self._iterator)
        rng = random.Random(seed)
        rng.shuffle(data)

        # 按比例切分
        results = []
        start = 0
        for i, ratio in enumerate(normed):
            if i == len(normed) - 1:
                end = len(data)
            else:
                end = start + round(len(data) * ratio)
            chunk = data[start:end]
            st = StreamingTransformer(iter(chunk), self._source_path, total=len(chunk))
            st._operations = self._operations + [{"type": "split", "ratio": ratios[i]}]
            results.append(st)
            start = end

        return results

    def batch(self, size: int) -> Generator[List[Dict], None, None]:
        """
        分批迭代（用于批量处理场景）。

        Args:
            size: 批次大小

        Yields:
            数据批次列表

        Examples:
            >>> for batch in st.batch(1000):
            ...     process_batch(batch)
        """
        batch = []
        for item in self._iterator:
            batch.append(item)
            if len(batch) >= size:
                yield batch
                batch = []
        if batch:
            yield batch

    def save(self, filepath: str, show_progress: bool = True, batch_size: int = 10000) -> int:
        """
        流式保存到文件。

        支持 JSONL、CSV、Parquet、Arrow 格式（根据扩展名自动检测）。

        Args:
            filepath: 输出文件路径
            show_progress: 是否显示进度
            batch_size: 批量写入大小（CSV/Parquet/Arrow）

        Returns:
            写入的记录数
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        # flaxkv: .flaxkv 后缀或无后缀（通过 _detect_format 判断）
        fmt = _fmt_of(path)

        if fmt == "flaxkv":
            count = self._save_flaxkv_stream(filepath, batch_size, show_progress)
        elif fmt in ("csv", "tsv", "parquet", "arrow"):
            count = self._save_batched(filepath, fmt, batch_size, show_progress)
        else:
            # jsonl/ndjson 及未知扩展名: 按 JSONL 写 (与 _detect_format 一致)
            count = self._save_jsonl(filepath, show_progress)

        # 打印错误摘要
        if self._error_count > 0:
            print(f"⚠️  跳过 {self._error_count} 条错误记录: {self._first_error}")

        return count

    def _save_jsonl(self, filepath: str, show_progress: bool) -> int:
        """JSONL 逐行流式保存（使用 orjson）"""
        count = 0

        if show_progress:
            # 根据是否有总数选择进度条样式
            if self._total is not None:
                # 有总数：显示进度条、百分比、剩余时间
                columns = [
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    MofNCompleteColumn(),
                    TimeElapsedColumn(),
                    TimeRemainingColumn(),
                ]
            else:
                # 无总数：只显示已处理数量
                columns = [
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    MofNCompleteColumn(),
                    TimeElapsedColumn(),
                ]

            with Progress(*columns) as progress:
                task = progress.add_task("处理中", total=self._total)
                with open(filepath, "wb") as f:
                    for item in self._iterator:
                        f.write(orjson.dumps(item) + b"\n")
                        count += 1
                        progress.update(task, advance=1)
        else:
            with open(filepath, "wb") as f:
                for item in self._iterator:
                    f.write(orjson.dumps(item) + b"\n")
                    count += 1

        return count

    def _save_batched(self, filepath: str, fmt: str, batch_size: int, show_progress: bool) -> int:
        """
        批量流式保存（CSV/Parquet/Arrow）。

        真正的流式写入：分批处理，每批写入后释放内存。
        内存占用 O(batch_size) 而非 O(n)。
        """
        path = Path(filepath)
        count = 0
        batch = []
        first_batch = True

        # 进度条配置
        progress_columns = self._get_progress_columns()

        def write_batch(items: List[Dict], is_first: bool, writer_state: Dict):
            """写入一批数据"""
            if not items:
                return

            df = pl.DataFrame(items)

            if fmt in ("csv", "tsv"):
                sep = "\t" if fmt == "tsv" else ","
                if is_first:
                    df.write_csv(path, separator=sep)
                else:
                    # CSV/TSV 追加模式：不写表头
                    with open(path, "ab") as f:
                        f.write(df.write_csv(include_header=False, separator=sep).encode("utf-8"))

            elif fmt == "parquet":
                import pyarrow as pa
                import pyarrow.parquet as pq

                table = df.to_arrow()
                if is_first:
                    writer_state["writer"] = pq.ParquetWriter(str(path), table.schema)
                writer_state["writer"].write_table(table)

            elif fmt == "arrow":
                import pyarrow as pa

                table = df.to_arrow()
                if is_first:
                    writer_state["writer"] = pa.ipc.new_file(str(path), table.schema)
                for record_batch in table.to_batches():
                    writer_state["writer"].write_batch(record_batch)

        writer_state: Dict[str, Any] = {}

        try:
            if show_progress:
                with Progress(*progress_columns) as progress:
                    task = progress.add_task("处理中", total=self._total)
                    for item in self._iterator:
                        batch.append(item)
                        count += 1
                        progress.update(task, advance=1)

                        if len(batch) >= batch_size:
                            write_batch(batch, first_batch, writer_state)
                            first_batch = False
                            batch = []  # 释放内存

                    # 写入最后一批
                    if batch:
                        write_batch(batch, first_batch, writer_state)
            else:
                for item in self._iterator:
                    batch.append(item)
                    count += 1

                    if len(batch) >= batch_size:
                        write_batch(batch, first_batch, writer_state)
                        first_batch = False
                        batch = []

                if batch:
                    write_batch(batch, first_batch, writer_state)

        finally:
            # 关闭 writer
            if "writer" in writer_state:
                writer_state["writer"].close()

        return count

    def _save_flaxkv_stream(self, filepath: str, batch_size: int, show_progress: bool) -> int:
        """FlaxKV 流式保存（FlaxList 分块批量写入）。"""
        from dtflow.storage.io import _open_flaxlist

        path = Path(filepath)
        count = 0
        batch = []
        progress_columns = self._get_progress_columns()

        with _open_flaxlist(path, rebuild=True) as lst:

            def flush_batch():
                nonlocal batch
                if batch:
                    lst.extend(batch)
                    batch = []

            if show_progress:
                with Progress(*progress_columns) as progress:
                    task = progress.add_task("处理中", total=self._total)
                    for item in self._iterator:
                        batch.append(item)
                        count += 1
                        progress.update(task, advance=1)
                        if len(batch) >= batch_size:
                            flush_batch()
                    flush_batch()
            else:
                for item in self._iterator:
                    batch.append(item)
                    count += 1
                    if len(batch) >= batch_size:
                        flush_batch()
                flush_batch()

        return count

    def _get_progress_columns(self):
        """获取进度条列配置"""
        if self._total is not None:
            return [
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
            ]
        else:
            return [
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
            ]

    def save_sharded(
        self,
        output_dir: str,
        shard_size: int = 100000,
        prefix: str = "part",
        show_progress: bool = True,
    ) -> List[str]:
        """
        分片保存。

        Args:
            output_dir: 输出目录
            shard_size: 每个分片的记录数
            prefix: 分片文件前缀
            show_progress: 是否显示进度

        Returns:
            生成的分片文件路径列表

        Examples:
            >>> files = st.save_sharded("output/", shard_size=100000)
            >>> # 生成: output/part-00000.jsonl, output/part-00001.jsonl, ...
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        shard_files = []
        shard_idx = 0
        count_in_shard = 0
        current_file = None

        def process_items(progress=None, task=None):
            nonlocal shard_idx, count_in_shard, current_file

            for item in self._iterator:
                # 需要新分片
                if current_file is None or count_in_shard >= shard_size:
                    if current_file:
                        current_file.close()

                    shard_path = os.path.join(output_dir, f"{prefix}-{shard_idx:05d}.jsonl")
                    shard_files.append(shard_path)
                    current_file = open(shard_path, "wb")
                    shard_idx += 1
                    count_in_shard = 0
                    if progress is not None:
                        progress.update(task, description=f"分片 {shard_idx}")

                current_file.write(orjson.dumps(item) + b"\n")
                count_in_shard += 1
                if progress is not None:
                    progress.update(task, advance=1)

        try:
            if show_progress:
                if self._total is not None:
                    columns = [
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        TaskProgressColumn(),
                        MofNCompleteColumn(),
                        TimeElapsedColumn(),
                        TimeRemainingColumn(),
                    ]
                else:
                    columns = [
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        MofNCompleteColumn(),
                        TimeElapsedColumn(),
                    ]

                with Progress(*columns) as progress:
                    task = progress.add_task("分片 1", total=self._total)
                    process_items(progress, task)
            else:
                process_items()
        finally:
            if current_file:
                current_file.close()

        return shard_files

    def collect(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        收集所有数据到内存（注意内存占用）。

        Args:
            limit: 最大收集数量，None 表示全部

        Returns:
            数据列表
        """
        result = []
        for item in self._iterator:
            result.append(item)
            if limit and len(result) >= limit:
                break
        return result

    def count(self) -> int:
        """
        计数（会消耗迭代器）。

        Returns:
            记录数
        """
        count = 0
        for _ in self._iterator:
            count += 1
        return count

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        """支持直接迭代"""
        return self._iterator


# ============ 便捷函数 ============


def load_stream(filepath: str, batch_size: int = 10000) -> StreamingTransformer:
    """
    流式加载文件。

    支持 JSONL、CSV、Parquet、Arrow 格式。

    Args:
        filepath: 文件路径
        batch_size: 批量读取大小（CSV/Parquet/Arrow）

    Returns:
        StreamingTransformer 实例

    Examples:
        >>> from dtflow import load_stream
        >>> (load_stream("huge.jsonl")
        ...     .filter(lambda x: x["score"] > 0.5)
        ...     .save("filtered.jsonl"))
        >>> (load_stream("data.csv")
        ...     .filter(lambda x: x["score"] > 0.5)
        ...     .save("output.parquet"))
    """
    return StreamingTransformer.load_stream(filepath, batch_size)


def load_sharded(pattern: str, batch_size: int = 10000) -> StreamingTransformer:
    """
    加载分片文件。

    支持 JSONL、CSV、Parquet、Arrow 格式。

    Args:
        pattern: glob 模式
        batch_size: 批量读取大小（CSV/Parquet/Arrow）

    Returns:
        StreamingTransformer 实例

    Examples:
        >>> from dtflow import load_sharded
        >>> load_sharded("data/*.jsonl").save("merged.jsonl")
        >>> load_sharded("data/*.parquet").save("merged.parquet")
    """
    return StreamingTransformer.load_sharded(pattern, batch_size)


def process_shards(
    input_pattern: str,
    output_dir: str,
    func: Callable[[Dict], Optional[Dict]],
    workers: int = 1,
    shard_size: int = 100000,
) -> List[str]:
    """
    并行处理分片文件。

    Args:
        input_pattern: 输入文件 glob 模式
        output_dir: 输出目录
        func: 处理函数，返回 None 表示过滤掉
        workers: 并行工作进程数（目前仅支持 1）
        shard_size: 输出分片大小

    Returns:
        生成的输出文件列表

    Examples:
        >>> def process(item):
        ...     if item["score"] > 0.5:
        ...         return {"text": item["content"]}
        ...     return None
        >>> process_shards("input/*.jsonl", "output/", process)
    """
    # 简单实现：串行处理
    # TODO: 未来可以添加多进程支持

    def transform_func(item):
        result = func(item)
        return result

    return (
        load_sharded(input_pattern)
        .transform(transform_func)
        .filter(lambda x: x is not None, raw=True)
        .save_sharded(output_dir, shard_size=shard_size)
    )


# ============ 流式读取函数 ============


def _stream_flaxkv(filepath: str) -> Generator[Dict[str, Any], None, None]:
    """FlaxKV 流式读取（FlaxList 迭代 yield）。"""
    from dtflow.storage.io import _open_flaxlist

    path = Path(filepath)
    with _open_flaxlist(path) as lst:
        yield from lst


def _stream_jsonl(filepath: str) -> Generator[Dict[str, Any], None, None]:
    """JSONL 流式读取（使用 orjson，失败时回退到标准 json）"""
    import json
    import sys

    use_fallback = False

    with open(filepath, "rb") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue

            if use_fallback:
                yield json.loads(line)
            else:
                try:
                    yield orjson.loads(line)
                except orjson.JSONDecodeError:
                    try:
                        yield json.loads(line)
                        use_fallback = True
                        print(
                            f"[Warning] 第 {i+1} 行包含非标准 JSON（如 NaN），已切换到标准 json 解析",
                            file=sys.stderr,
                        )
                    except json.JSONDecodeError as e:
                        # 流式处理会写出新文件, 不能静默跳行; 但报错必须能定位到行
                        snippet = line.decode("utf-8", errors="replace")[:120]
                        raise ValueError(
                            f"{filepath} 第 {i + 1} 行不是合法 JSON: {e}\n"
                            f"  行内容: {snippet}\n"
                            f"  想直接看这一行用: dt view {filepath}"
                        ) from e


def _stream_csv(
    filepath: str, batch_size: int = 10000, separator: str = ","
) -> Generator[Dict[str, Any], None, None]:
    """CSV/TSV 流式读取（使用 Polars BatchedCsvReader）。separator 决定 csv 还是 tsv。"""
    reader = pl.read_csv_batched(filepath, batch_size=batch_size, separator=separator)
    while True:
        batches = reader.next_batches(1)
        if not batches:
            break
        for row in batches[0].to_dicts():
            yield row


def _stream_parquet(
    filepath: str, batch_size: int = 10000
) -> Generator[Dict[str, Any], None, None]:
    """Parquet 流式读取（使用 PyArrow iter_batches）"""
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(filepath)
    for batch in pf.iter_batches(batch_size=batch_size):
        df = pl.from_arrow(batch)
        for row in df.to_dicts():
            yield row


def _stream_arrow(filepath: str) -> Generator[Dict[str, Any], None, None]:
    """Arrow/Feather 流式读取（使用 PyArrow IPC）"""
    import pyarrow as pa

    with pa.ipc.open_file(filepath) as reader:
        for i in range(reader.num_record_batches):
            batch = reader.get_batch(i)
            df = pl.from_arrow(batch)
            for row in df.to_dicts():
                yield row
