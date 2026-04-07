#!/usr/bin/env python
"""
ShareGPT 数据集性能测试报告生成器

使用 data/sharegpt_all.json (261MB, 75,532条) 进行真实数据性能测试
"""

import os
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from dtflow.cli.clean import clean, dedupe
from dtflow.cli.io_ops import concat, diff
from dtflow.cli.sample import head, sample, tail
from dtflow.cli.stats import stats
from dtflow.cli.transform import transform
from dtflow.storage.io import load_data, save_data


@dataclass
class BenchmarkResult:
    """性能测试结果"""

    name: str
    elapsed: float
    input_size: int
    output_size: int = 0
    throughput: float = 0.0  # 条/秒
    notes: str = ""


class PerformanceBenchmark:
    """性能测试器"""

    def __init__(self, data_file: str):
        self.data_file = Path(data_file)
        self.file_size_mb = self.data_file.stat().st_size / (1024 * 1024)
        self.results: List[BenchmarkResult] = []
        self.temp_dir = tempfile.mkdtemp(prefix="benchmark_")

        # 预加载数据获取条数
        print(f"📂 加载数据: {self.data_file}")
        start = time.perf_counter()
        self.data = load_data(str(self.data_file))
        load_time = time.perf_counter() - start
        self.data_count = len(self.data)

        print(f"   文件大小: {self.file_size_mb:.1f} MB")
        print(f"   数据条数: {self.data_count:,}")
        print(f"   加载耗时: {load_time:.2f}s")
        print(f"   临时目录: {self.temp_dir}")
        print()

        # 记录加载性能
        self.results.append(
            BenchmarkResult(
                name="load_data (JSON)",
                elapsed=load_time,
                input_size=self.data_count,
                throughput=self.data_count / load_time,
                notes=f"{self.file_size_mb:.1f}MB JSON 文件",
            )
        )

        # 保存为 JSONL 格式用于后续测试
        self.jsonl_file = Path(self.temp_dir) / "sharegpt.jsonl"
        print("📝 转换为 JSONL 格式...")
        start = time.perf_counter()
        save_data(self.data, str(self.jsonl_file))
        save_time = time.perf_counter() - start
        jsonl_size = self.jsonl_file.stat().st_size / (1024 * 1024)
        print(f"   JSONL 大小: {jsonl_size:.1f} MB")
        print(f"   保存耗时: {save_time:.2f}s")
        print()

        self.results.append(
            BenchmarkResult(
                name="save_data (JSONL)",
                elapsed=save_time,
                input_size=self.data_count,
                throughput=self.data_count / save_time,
                notes=f"输出 {jsonl_size:.1f}MB JSONL",
            )
        )

    def run(
        self, name: str, func: Callable, input_size: int = 0, notes: str = ""
    ) -> BenchmarkResult:
        """运行单个测试"""
        print(f"  ⏱ {name}...", end=" ", flush=True)
        start = time.perf_counter()
        try:
            result = func()
            elapsed = time.perf_counter() - start
            output_size = result if isinstance(result, int) else 0
            throughput = (input_size or self.data_count) / elapsed if elapsed > 0 else 0
            print(f"{elapsed:.3f}s ({throughput:,.0f} 条/秒)")

            br = BenchmarkResult(
                name=name,
                elapsed=elapsed,
                input_size=input_size or self.data_count,
                output_size=output_size,
                throughput=throughput,
                notes=notes,
            )
            self.results.append(br)
            return br
        except Exception as e:
            elapsed = time.perf_counter() - start
            print(f"失败: {e}")
            br = BenchmarkResult(
                name=name,
                elapsed=elapsed,
                input_size=input_size or self.data_count,
                notes=f"错误: {e}",
            )
            self.results.append(br)
            return br

    def benchmark_sample(self):
        """采样命令性能测试"""
        print("\n📊 Sample 命令性能测试")
        print("-" * 50)

        # head 采样
        output = Path(self.temp_dir) / "sample_head.jsonl"
        self.run(
            "head 1000条",
            lambda: head(str(self.jsonl_file), num=1000, output=str(output)),
            notes="从头部采样",
        )

        # head 大量采样
        output = Path(self.temp_dir) / "sample_head_large.jsonl"
        self.run(
            "head 10000条",
            lambda: head(str(self.jsonl_file), num=10000, output=str(output)),
            notes="从头部采样",
        )

        # tail 采样
        output = Path(self.temp_dir) / "sample_tail.jsonl"
        self.run(
            "tail 1000条",
            lambda: tail(str(self.jsonl_file), num=1000, output=str(output)),
            notes="从尾部采样",
        )

        # 随机采样
        output = Path(self.temp_dir) / "sample_random.jsonl"
        self.run(
            "random 5000条",
            lambda: sample(
                str(self.jsonl_file), num=5000, type="random", output=str(output), seed=42
            ),
            notes="随机采样",
        )

    def benchmark_stats(self):
        """统计命令性能测试"""
        print("\n📊 Stats 命令性能测试")
        print("-" * 50)

        # 快速统计
        self.run(
            "stats 快速模式",
            lambda: stats(str(self.jsonl_file), full=False),
            notes="只统计行数和字段结构",
        )

        # 完整统计（较慢）
        self.run(
            "stats 完整模式", lambda: stats(str(self.jsonl_file), full=True), notes="完整值分布统计"
        )

    def benchmark_clean(self):
        """清洗命令性能测试"""
        print("\n📊 Clean 命令性能测试")
        print("-" * 50)

        # strip 清洗
        output = Path(self.temp_dir) / "clean_strip.jsonl"
        self.run(
            "clean --strip",
            lambda: clean(str(self.jsonl_file), strip=True, output=str(output)),
            notes="去除字符串首尾空白",
        )

        # drop-empty 清洗
        output = Path(self.temp_dir) / "clean_drop_empty.jsonl"
        self.run(
            "clean --drop-empty=system",
            lambda: clean(str(self.jsonl_file), drop_empty="system", output=str(output)),
            notes="删除 system 为空的记录",
        )

        # keep 字段
        output = Path(self.temp_dir) / "clean_keep.jsonl"
        self.run(
            "clean --keep=conversations",
            lambda: clean(str(self.jsonl_file), keep="conversations", output=str(output)),
            notes="只保留 conversations 字段",
        )

    def benchmark_dedupe(self):
        """去重命令性能测试"""
        print("\n📊 Dedupe 命令性能测试")
        print("-" * 50)

        # 全量去重
        output = Path(self.temp_dir) / "dedupe_full.jsonl"
        self.run(
            "dedupe 全量精确去重",
            lambda: dedupe(str(self.jsonl_file), output=str(output)),
            notes="基于完整内容哈希",
        )

        # 按字段去重
        output = Path(self.temp_dir) / "dedupe_system.jsonl"
        self.run(
            "dedupe --key=system",
            lambda: dedupe(str(self.jsonl_file), key="system", output=str(output)),
            notes="按 system 字段去重",
        )

    def benchmark_io(self):
        """IO 命令性能测试"""
        print("\n📊 IO 命令性能测试")
        print("-" * 50)

        # 拆分文件用于 concat 测试
        part1 = Path(self.temp_dir) / "part1.jsonl"
        part2 = Path(self.temp_dir) / "part2.jsonl"
        save_data(self.data[:30000], str(part1))
        save_data(self.data[30000:60000], str(part2))

        # concat
        output = Path(self.temp_dir) / "concat_result.jsonl"
        self.run(
            "concat 2个文件 (各30000条)",
            lambda: concat(str(part1), str(part2), output=str(output)),
            input_size=60000,
            notes="合并两个文件",
        )

        # diff
        self.run(
            "diff 2个文件 (各30000条)",
            lambda: diff(str(part1), str(part2)),
            input_size=60000,
            notes="对比两个文件",
        )

    def benchmark_transform(self):
        """转换命令性能测试"""
        print("\n📊 Transform 命令性能测试")
        print("-" * 50)

        # 使用 sharegpt 预设
        output = Path(self.temp_dir) / "transform_sharegpt.jsonl"
        self.run(
            "transform --preset=sharegpt",
            lambda: transform(str(self.jsonl_file), preset="sharegpt", output=str(output)),
            notes="ShareGPT 格式转换",
        )

        # 使用 openai_chat 预设（限制数量）
        # 先创建小数据集
        small_file = Path(self.temp_dir) / "small_10000.jsonl"
        save_data(self.data[:10000], str(small_file))

        output = Path(self.temp_dir) / "transform_openai.jsonl"
        self.run(
            "transform --preset=openai_chat (10000条)",
            lambda: transform(str(small_file), preset="openai_chat", output=str(output)),
            input_size=10000,
            notes="转换为 OpenAI Chat 格式",
        )

    def generate_report(self) -> str:
        """生成性能测试报告"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        report = []
        report.append("=" * 70)
        report.append("dtflow CLI 性能测试报告")
        report.append("=" * 70)
        report.append(f"测试时间: {now}")
        report.append(f"测试文件: {self.data_file}")
        report.append(f"文件大小: {self.file_size_mb:.1f} MB")
        report.append(f"数据条数: {self.data_count:,}")
        report.append("")

        # 按类别分组
        categories = {}
        for r in self.results:
            cat = r.name.split()[0]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(r)

        # 生成详细结果表格
        report.append("-" * 70)
        report.append(f"{'测试项':<35} {'耗时(s)':<10} {'吞吐量(条/s)':<15} {'备注'}")
        report.append("-" * 70)

        for _cat, items in categories.items():
            for r in items:
                throughput_str = f"{r.throughput:,.0f}" if r.throughput > 0 else "-"
                report.append(f"{r.name:<35} {r.elapsed:<10.3f} {throughput_str:<15} {r.notes}")

        report.append("-" * 70)

        # 汇总统计
        total_time = sum(r.elapsed for r in self.results)
        report.append("")
        report.append("📊 汇总统计")
        report.append("-" * 40)
        report.append(f"总测试项: {len(self.results)}")
        report.append(f"总耗时: {total_time:.2f}s")

        # 找出最快和最慢的操作
        sorted_results = sorted(self.results, key=lambda x: x.throughput, reverse=True)
        fastest = [r for r in sorted_results if r.throughput > 0][:3]
        slowest = [r for r in sorted_results if r.throughput > 0][-3:]

        report.append("")
        report.append("🚀 最快操作 (吞吐量):")
        for r in fastest:
            report.append(f"   {r.name}: {r.throughput:,.0f} 条/秒")

        report.append("")
        report.append("🐢 最慢操作 (吞吐量):")
        for r in reversed(slowest):
            report.append(f"   {r.name}: {r.throughput:,.0f} 条/秒")

        report.append("")
        report.append("=" * 70)

        return "\n".join(report)

    def cleanup(self):
        """清理临时文件"""
        import shutil

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            print(f"\n🧹 已清理临时目录: {self.temp_dir}")


def main():
    """运行性能测试"""
    data_file = "data/sharegpt_all.json"

    if not os.path.exists(data_file):
        print(f"错误: 文件不存在 - {data_file}")
        sys.exit(1)

    print("=" * 70)
    print("dtflow CLI 性能测试")
    print("=" * 70)
    print()

    benchmark = PerformanceBenchmark(data_file)

    try:
        # 运行各类测试
        benchmark.benchmark_sample()
        benchmark.benchmark_stats()
        benchmark.benchmark_clean()
        benchmark.benchmark_dedupe()
        benchmark.benchmark_io()
        benchmark.benchmark_transform()

        # 生成报告
        report = benchmark.generate_report()
        print("\n" + report)

        # 保存报告
        report_file = "benchmark_report.txt"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n📄 报告已保存: {report_file}")

    finally:
        benchmark.cleanup()


if __name__ == "__main__":
    main()
