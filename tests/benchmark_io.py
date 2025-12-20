"""
I/O 性能对比测试：Pandas vs Polars

测试内容：
1. CSV 读取/写入
2. Parquet 读取/写入

运行方式：
    python tests/benchmark_io.py
"""
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple


def generate_test_data(num_records: int) -> List[Dict[str, Any]]:
    """生成测试数据"""
    data = []
    for i in range(num_records):
        data.append({
            "id": i,
            "name": f"user_{i}",
            "email": f"user_{i}@example.com",
            "score": i * 0.01,
            "category": f"cat_{i % 10}",
            "description": f"This is a sample description for record {i}. " * 5,
            "active": i % 2 == 0,
            "count": i * 100,
        })
    return data


def benchmark(func: Callable, name: str, runs: int = 3) -> float:
    """运行基准测试，返回平均时间"""
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        func()
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    avg_time = sum(times) / len(times)
    return avg_time


# ============ Pandas I/O ============

def pandas_write_csv(data: List[Dict], filepath: str) -> None:
    import pandas as pd
    df = pd.DataFrame(data)
    df.to_csv(filepath, index=False)


def pandas_read_csv(filepath: str) -> List[Dict]:
    import pandas as pd
    df = pd.read_csv(filepath)
    return df.to_dict('records')


def pandas_write_parquet(data: List[Dict], filepath: str) -> None:
    import pandas as pd
    df = pd.DataFrame(data)
    df.to_parquet(filepath, index=False)


def pandas_read_parquet(filepath: str) -> List[Dict]:
    import pandas as pd
    df = pd.read_parquet(filepath)
    return df.to_dict('records')


# ============ Polars I/O ============

def polars_write_csv(data: List[Dict], filepath: str) -> None:
    import polars as pl
    df = pl.DataFrame(data)
    df.write_csv(filepath)


def polars_read_csv(filepath: str) -> List[Dict]:
    import polars as pl
    df = pl.read_csv(filepath)
    return df.to_dicts()


def polars_write_parquet(data: List[Dict], filepath: str) -> None:
    import polars as pl
    df = pl.DataFrame(data)
    df.write_parquet(filepath)


def polars_read_parquet(filepath: str) -> List[Dict]:
    import polars as pl
    df = pl.read_parquet(filepath)
    return df.to_dicts()


# ============ Benchmark Runner ============

def run_benchmark(num_records: int, tmpdir: str) -> Dict[str, Dict[str, float]]:
    """运行单个规模的基准测试"""
    data = generate_test_data(num_records)

    csv_path = f"{tmpdir}/test.csv"
    parquet_path = f"{tmpdir}/test.parquet"

    results = {}

    # CSV 写入
    pandas_write_time = benchmark(lambda: pandas_write_csv(data, csv_path), "pandas_write_csv")
    polars_write_time = benchmark(lambda: polars_write_csv(data, csv_path), "polars_write_csv")
    results["csv_write"] = {"pandas": pandas_write_time, "polars": polars_write_time}

    # CSV 读取（使用 pandas 写的文件）
    pandas_write_csv(data, csv_path)
    pandas_read_time = benchmark(lambda: pandas_read_csv(csv_path), "pandas_read_csv")
    polars_read_time = benchmark(lambda: polars_read_csv(csv_path), "polars_read_csv")
    results["csv_read"] = {"pandas": pandas_read_time, "polars": polars_read_time}

    # Parquet 写入
    pandas_write_time = benchmark(lambda: pandas_write_parquet(data, parquet_path), "pandas_write_parquet")
    polars_write_time = benchmark(lambda: polars_write_parquet(data, parquet_path), "polars_write_parquet")
    results["parquet_write"] = {"pandas": pandas_write_time, "polars": polars_write_time}

    # Parquet 读取
    pandas_write_parquet(data, parquet_path)
    pandas_read_time = benchmark(lambda: pandas_read_parquet(parquet_path), "pandas_read_parquet")
    polars_read_time = benchmark(lambda: polars_read_parquet(parquet_path), "polars_read_parquet")
    results["parquet_read"] = {"pandas": pandas_read_time, "polars": polars_read_time}

    return results


def print_results(num_records: int, results: Dict[str, Dict[str, float]]) -> None:
    """打印测试结果"""
    print(f"\n{'='*60}")
    print(f"数据规模: {num_records:,} 条记录")
    print(f"{'='*60}")
    print(f"{'操作':<20} {'Pandas':>12} {'Polars':>12} {'加速比':>12}")
    print(f"{'-'*60}")

    for op, times in results.items():
        pandas_time = times["pandas"]
        polars_time = times["polars"]
        speedup = pandas_time / polars_time
        print(f"{op:<20} {pandas_time:>10.3f}s {polars_time:>10.3f}s {speedup:>10.1f}x")


def check_dependencies() -> Tuple[bool, bool]:
    """检查依赖是否安装"""
    has_pandas = False
    has_polars = False

    try:
        import pandas
        has_pandas = True
    except ImportError:
        pass

    try:
        import polars
        has_polars = True
    except ImportError:
        pass

    return has_pandas, has_polars


def main():
    print("=" * 60)
    print("I/O 性能对比测试：Pandas vs Polars")
    print("=" * 60)

    # 检查依赖
    has_pandas, has_polars = check_dependencies()

    if not has_pandas:
        print("❌ pandas 未安装，请运行: pip install pandas")
        return

    if not has_polars:
        print("❌ polars 未安装，请运行: pip install polars")
        return

    print("✅ pandas 和 polars 已安装")

    # 运行测试
    sizes = [10_000, 50_000, 100_000]

    with tempfile.TemporaryDirectory() as tmpdir:
        all_results = {}

        for size in sizes:
            print(f"\n⏳ 测试 {size:,} 条记录...")
            results = run_benchmark(size, tmpdir)
            all_results[size] = results
            print_results(size, results)

        # 打印总结
        print(f"\n{'='*60}")
        print("📊 总结")
        print(f"{'='*60}")

        # 计算平均加速比
        avg_speedups = {}
        for op in ["csv_read", "csv_write", "parquet_read", "parquet_write"]:
            speedups = []
            for size in sizes:
                pandas_time = all_results[size][op]["pandas"]
                polars_time = all_results[size][op]["polars"]
                speedups.append(pandas_time / polars_time)
            avg_speedups[op] = sum(speedups) / len(speedups)

        print(f"\n平均加速比:")
        for op, speedup in avg_speedups.items():
            print(f"  {op}: {speedup:.1f}x")

        overall_avg = sum(avg_speedups.values()) / len(avg_speedups)
        print(f"\n整体平均加速: {overall_avg:.1f}x")

        if overall_avg > 1.5:
            print("\n✅ 结论: Polars 显著快于 Pandas，建议在 I/O 层使用 Polars")
        else:
            print("\n⚠️ 结论: 加速效果不明显，可能与数据规模或环境有关")


if __name__ == "__main__":
    main()
