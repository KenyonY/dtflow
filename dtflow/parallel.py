"""
并行处理模块

提供多进程并行处理工具，用于加速大数据集的 token 统计和 schema 验证。
"""

from multiprocessing import Pool, cpu_count
from typing import Callable, List, Optional, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def parallel_map(
    func: Callable[[T], R],
    data: List[T],
    workers: Optional[int] = None,
    threshold: int = 1000,
    chunksize: Optional[int] = None,
) -> List[R]:
    """
    并行 map 操作。

    Args:
        func: 处理函数（必须可 pickle，不能是 lambda 或闭包）
        data: 数据列表
        workers: 进程数，None 则使用 CPU 核数
        threshold: 数据量阈值，低于此值使用串行
        chunksize: 每个进程的任务块大小，None 则自动计算

    Returns:
        处理结果列表（保持顺序）
    """
    n = len(data)

    # 数据量小或指定单进程，使用串行
    if n < threshold or workers == 1:
        return [func(item) for item in data]

    workers = workers or cpu_count()
    workers = min(workers, n)  # 进程数不超过数据量

    # 自动计算 chunksize
    if chunksize is None:
        chunksize = max(1, n // (workers * 4))

    with Pool(processes=workers) as pool:
        return pool.map(func, data, chunksize=chunksize)


def parallel_imap(
    func: Callable[[T], R],
    data: List[T],
    workers: Optional[int] = None,
    threshold: int = 1000,
    chunksize: Optional[int] = None,
):
    """
    并行 imap 操作（惰性迭代器版本，支持进度回调）。

    Args:
        func: 处理函数（必须可 pickle）
        data: 数据列表
        workers: 进程数，None 则使用 CPU 核数
        threshold: 数据量阈值，低于此值使用串行
        chunksize: 每个进程的任务块大小

    Yields:
        处理结果（按顺序）
    """
    n = len(data)

    # 数据量小或指定单进程，使用串行
    if n < threshold or workers == 1:
        for item in data:
            yield func(item)
        return

    workers = workers or cpu_count()
    workers = min(workers, n)

    if chunksize is None:
        chunksize = max(1, n // (workers * 4))

    with Pool(processes=workers) as pool:
        for result in pool.imap(func, data, chunksize=chunksize):
            yield result


def get_optimal_workers(data_size: int, default: Optional[int] = None) -> int:
    """
    根据数据量计算最优进程数。

    Args:
        data_size: 数据量
        default: 用户指定的进程数，None 则自动计算

    Returns:
        最优进程数
    """
    if default is not None:
        return default

    cpu_cores = cpu_count()

    # 数据量小于阈值，单进程
    if data_size < 1000:
        return 1

    # 数据量适中，使用一半 CPU
    if data_size < 10000:
        return max(1, cpu_cores // 2)

    # 大数据量，使用全部 CPU
    return cpu_cores
