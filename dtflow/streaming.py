"""
流式处理模块

支持大文件的惰性处理，避免全量加载内存。
支持格式：JSONL, CSV, Parquet, Arrow
"""

import glob
import os
from pathlib import Path
from typing import Any, Callable, Dict, Generator, Iterator, List, Optional, Union

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

# 支持的流式格式
STREAMING_FORMATS = {".jsonl", ".csv", ".parquet", ".arrow", ".feather"}


def _count_rows_fast(filepath: str) -> Optional[int]:
    """快速统计文件行数（不加载数据）"""
    path = Path(filepath)
    ext = path.suffix.lower()

    try:
        if ext == ".jsonl":
            # JSONL: 直接数换行符
            with open(filepath, "rb") as f:
                return sum(1 for line in f if line.strip())
        elif ext == ".csv":
            # CSV: Polars LazyFrame
            return pl.scan_csv(filepath).select(pl.len()).collect().item()
        elif ext == ".parquet":
            # Parquet: Polars LazyFrame
            return pl.scan_parquet(filepath).select(pl.len()).collect().item()
        elif ext in (".arrow", ".feather"):
            # Arrow: Polars LazyFrame
            return pl.scan_ipc(filepath).select(pl.len()).collect().item()
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
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {filepath}")

        ext = path.suffix.lower()
        if ext not in STREAMING_FORMATS:
            raise ValueError(f"不支持的流式格式: {ext}，支持: {STREAMING_FORMATS}")

        # 快速统计总行数（用于进度条）
        total = _count_rows_fast(filepath)

        if ext == ".jsonl":
            return cls(_stream_jsonl(filepath), source_path=filepath, total=total)
        elif ext == ".csv":
            return cls(_stream_csv(filepath, batch_size), source_path=filepath, total=total)
        elif ext == ".parquet":
            return cls(_stream_parquet(filepath, batch_size), source_path=filepath, total=total)
        elif ext in (".arrow", ".feather"):
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
                ext = Path(filepath).suffix.lower()
                if ext == ".jsonl":
                    yield from _stream_jsonl(filepath)
                elif ext == ".csv":
                    yield from _stream_csv(filepath, batch_size)
                elif ext == ".parquet":
                    yield from _stream_parquet(filepath, batch_size)
                elif ext in (".arrow", ".feather"):
                    yield from _stream_arrow(filepath)
                else:
                    # 默认当作 JSONL
                    yield from _stream_jsonl(filepath)

        return cls(generator(), source_path=pattern)

    def filter(self, func: Callable[[Dict], bool]) -> "StreamingTransformer":
        """
        惰性过滤。

        Args:
            func: 过滤函数，返回 True 保留

        Returns:
            新的 StreamingTransformer（惰性，不立即执行）
        """

        def filtered_iterator():
            for item in self._iterator:
                try:
                    if func(item):
                        yield item
                except Exception:
                    pass  # 跳过错误

        # 过滤后数量未知，不传递 total
        new_st = StreamingTransformer(filtered_iterator(), self._source_path, total=None)
        new_st._operations = self._operations + [{"type": "filter", "func": func}]
        return new_st

    def transform(self, func: Callable[[Dict], Dict]) -> "StreamingTransformer":
        """
        惰性转换。

        Args:
            func: 转换函数

        Returns:
            新的 StreamingTransformer（惰性，不立即执行）
        """
        # transform 是 1:1 转换，保留 total
        new_st = StreamingTransformer(iter([]), self._source_path, total=self._total)
        new_st._operations = self._operations + [{"type": "transform", "func": func}]

        def transformed_iterator():
            for item in self._iterator:
                try:
                    yield func(item)
                except Exception as e:
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
        ext = path.suffix.lower()

        if ext == ".jsonl":
            count = self._save_jsonl(filepath, show_progress)
        elif ext == ".csv":
            count = self._save_batched(filepath, "csv", batch_size, show_progress)
        elif ext == ".parquet":
            count = self._save_batched(filepath, "parquet", batch_size, show_progress)
        elif ext in (".arrow", ".feather"):
            count = self._save_batched(filepath, "arrow", batch_size, show_progress)
        else:
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

            if fmt == "csv":
                if is_first:
                    df.write_csv(path)
                else:
                    # CSV 追加模式：不写表头
                    with open(path, "ab") as f:
                        f.write(df.write_csv(include_header=False).encode("utf-8"))

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
        .filter(lambda x: x is not None)
        .save_sharded(output_dir, shard_size=shard_size)
    )


# ============ 流式读取函数 ============


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
                    except json.JSONDecodeError:
                        raise


def _stream_csv(filepath: str, batch_size: int = 10000) -> Generator[Dict[str, Any], None, None]:
    """CSV 流式读取（使用 Polars BatchedCsvReader）"""
    reader = pl.read_csv_batched(filepath, batch_size=batch_size)
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
