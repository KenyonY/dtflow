"""
CLI 核心方法性能测试

使用方式:
    pytest tests/test_cli_benchmark.py -v
    pytest tests/test_cli_benchmark.py -v -k "test_sample"  # 单个测试
    pytest tests/test_cli_benchmark.py -v --benchmark-only  # 仅运行 benchmark

注意: 需要安装 pytest-benchmark: pip install pytest-benchmark
"""

import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List

import pytest

# 尝试导入 benchmark，如果没有则使用简单计时
try:
    from pytest_benchmark.fixture import BenchmarkFixture

    HAS_BENCHMARK = True
except ImportError:
    HAS_BENCHMARK = False

from dtflow.cli.sample import sample, head, tail
from dtflow.cli.stats import stats, token_stats
from dtflow.cli.io_ops import concat, diff
from dtflow.cli.clean import dedupe, clean
from dtflow.cli.transform import transform
from dtflow.cli.validate import validate
from dtflow.storage.io import save_data


# ============ 测试数据生成 ============


def generate_test_data(num_rows: int, data_type: str = "simple") -> List[Dict]:
    """
    生成测试数据

    Args:
        num_rows: 数据行数
        data_type: 数据类型
            - simple: 简单键值对
            - messages: OpenAI 消息格式
            - nested: 嵌套结构
    """
    if data_type == "simple":
        return [
            {
                "id": i,
                "text": f"这是第 {i} 条测试数据，用于性能测试。" * 5,
                "label": i % 10,
                "score": i * 0.1,
            }
            for i in range(num_rows)
        ]
    elif data_type == "messages":
        return [
            {
                "id": i,
                "messages": [
                    {"role": "system", "content": "你是一个助手。"},
                    {"role": "user", "content": f"问题 {i}: 请解释什么是机器学习？"},
                    {"role": "assistant", "content": f"回答 {i}: 机器学习是人工智能的一个分支..." * 10},
                ],
            }
            for i in range(num_rows)
        ]
    elif data_type == "nested":
        return [
            {
                "id": i,
                "meta": {
                    "source": f"source_{i % 5}",
                    "timestamp": f"2024-01-{(i % 28) + 1:02d}",
                    "tags": [f"tag_{j}" for j in range(i % 5)],
                },
                "content": {
                    "title": f"标题 {i}",
                    "body": f"正文内容 {i}" * 20,
                },
            }
            for i in range(num_rows)
        ]
    else:
        raise ValueError(f"未知数据类型: {data_type}")


class Timer:
    """简单计时器，用于没有 pytest-benchmark 时"""

    def __init__(self, name: str):
        self.name = name
        self.start_time = None
        self.elapsed = None

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed = time.perf_counter() - self.start_time
        print(f"\n  {self.name}: {self.elapsed:.4f}s")


# ============ Fixtures ============


@pytest.fixture(scope="module")
def temp_dir():
    """创建临时目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(scope="module")
def small_data_file(temp_dir):
    """小数据集 (1000 条)"""
    filepath = temp_dir / "small_data.jsonl"
    data = generate_test_data(1000, "simple")
    save_data(data, str(filepath))
    return filepath


@pytest.fixture(scope="module")
def medium_data_file(temp_dir):
    """中等数据集 (10000 条)"""
    filepath = temp_dir / "medium_data.jsonl"
    data = generate_test_data(10000, "simple")
    save_data(data, str(filepath))
    return filepath


@pytest.fixture(scope="module")
def large_data_file(temp_dir):
    """大数据集 (50000 条)"""
    filepath = temp_dir / "large_data.jsonl"
    data = generate_test_data(50000, "simple")
    save_data(data, str(filepath))
    return filepath


@pytest.fixture(scope="module")
def messages_data_file(temp_dir):
    """消息格式数据集 (5000 条)"""
    filepath = temp_dir / "messages_data.jsonl"
    data = generate_test_data(5000, "messages")
    save_data(data, str(filepath))
    return filepath


@pytest.fixture(scope="module")
def nested_data_file(temp_dir):
    """嵌套结构数据集 (5000 条)"""
    filepath = temp_dir / "nested_data.jsonl"
    data = generate_test_data(5000, "nested")
    save_data(data, str(filepath))
    return filepath


@pytest.fixture(scope="module")
def duplicate_data_file(temp_dir):
    """含重复数据集 (10000 条，约 50% 重复)"""
    filepath = temp_dir / "duplicate_data.jsonl"
    base_data = generate_test_data(5000, "simple")
    # 复制一半数据制造重复
    data = base_data + base_data[:5000]
    save_data(data, str(filepath))
    return filepath


# ============ Sample 命令性能测试 ============


class TestSampleBenchmark:
    """sample/head/tail 命令性能测试"""

    def test_sample_head_small(self, small_data_file, temp_dir):
        """head 采样小数据集"""
        output = temp_dir / "sample_head_small.jsonl"
        with Timer("head 1000条 取100条"):
            head(str(small_data_file), num=100, output=str(output))
        assert output.exists()

    def test_sample_head_medium(self, medium_data_file, temp_dir):
        """head 采样中等数据集"""
        output = temp_dir / "sample_head_medium.jsonl"
        with Timer("head 10000条 取1000条"):
            head(str(medium_data_file), num=1000, output=str(output))
        assert output.exists()

    def test_sample_head_large(self, large_data_file, temp_dir):
        """head 采样大数据集"""
        output = temp_dir / "sample_head_large.jsonl"
        with Timer("head 50000条 取5000条"):
            head(str(large_data_file), num=5000, output=str(output))
        assert output.exists()

    def test_sample_tail_small(self, small_data_file, temp_dir):
        """tail 采样小数据集"""
        output = temp_dir / "sample_tail_small.jsonl"
        with Timer("tail 1000条 取100条"):
            tail(str(small_data_file), num=100, output=str(output))
        assert output.exists()

    def test_sample_tail_medium(self, medium_data_file, temp_dir):
        """tail 采样中等数据集"""
        output = temp_dir / "sample_tail_medium.jsonl"
        with Timer("tail 10000条 取1000条"):
            tail(str(medium_data_file), num=1000, output=str(output))
        assert output.exists()

    def test_sample_tail_large(self, large_data_file, temp_dir):
        """tail 采样大数据集"""
        output = temp_dir / "sample_tail_large.jsonl"
        with Timer("tail 50000条 取5000条"):
            tail(str(large_data_file), num=5000, output=str(output))
        assert output.exists()

    def test_sample_random_small(self, small_data_file, temp_dir):
        """随机采样小数据集"""
        output = temp_dir / "sample_random_small.jsonl"
        with Timer("random 1000条 取100条"):
            sample(str(small_data_file), num=100, type="random", output=str(output), seed=42)
        assert output.exists()

    def test_sample_random_medium(self, medium_data_file, temp_dir):
        """随机采样中等数据集"""
        output = temp_dir / "sample_random_medium.jsonl"
        with Timer("random 10000条 取1000条"):
            sample(str(medium_data_file), num=1000, type="random", output=str(output), seed=42)
        assert output.exists()

    def test_sample_random_large(self, large_data_file, temp_dir):
        """随机采样大数据集"""
        output = temp_dir / "sample_random_large.jsonl"
        with Timer("random 50000条 取5000条"):
            sample(str(large_data_file), num=5000, type="random", output=str(output), seed=42)
        assert output.exists()

    def test_sample_random_high_ratio(self, medium_data_file, temp_dir):
        """随机采样高比例 (50%)"""
        output = temp_dir / "sample_random_high.jsonl"
        with Timer("random 10000条 取5000条 (50%)"):
            sample(str(medium_data_file), num=5000, type="random", output=str(output), seed=42)
        assert output.exists()

    def test_sample_stratified(self, medium_data_file, temp_dir):
        """分层采样"""
        output = temp_dir / "sample_stratified.jsonl"
        with Timer("分层采样 10000条 按label分组 取1000条"):
            sample(str(medium_data_file), num=1000, by="label", output=str(output))
        assert output.exists()


# ============ Stats 命令性能测试 ============


class TestStatsBenchmark:
    """stats 命令性能测试"""

    def test_stats_quick_small(self, small_data_file, capsys):
        """快速统计小数据集"""
        with Timer("快速统计 1000条"):
            stats(str(small_data_file), full=False)

    def test_stats_quick_medium(self, medium_data_file, capsys):
        """快速统计中等数据集"""
        with Timer("快速统计 10000条"):
            stats(str(medium_data_file), full=False)

    def test_stats_quick_large(self, large_data_file, capsys):
        """快速统计大数据集"""
        with Timer("快速统计 50000条"):
            stats(str(large_data_file), full=False)

    def test_stats_full_small(self, small_data_file, capsys):
        """完整统计小数据集"""
        with Timer("完整统计 1000条"):
            stats(str(small_data_file), full=True)

    def test_stats_full_medium(self, medium_data_file, capsys):
        """完整统计中等数据集"""
        with Timer("完整统计 10000条"):
            stats(str(medium_data_file), full=True)


# ============ Token Stats 命令性能测试 ============


class TestTokenStatsBenchmark:
    """token_stats 命令性能测试"""

    def test_token_stats_messages_small(self, messages_data_file, capsys):
        """消息格式 token 统计小数据集"""
        with Timer("token统计 5000条消息格式"):
            token_stats(str(messages_data_file), field="messages", model="cl100k_base")

    def test_token_stats_text_medium(self, medium_data_file, capsys):
        """文本字段 token 统计"""
        with Timer("token统计 10000条 text字段"):
            token_stats(str(medium_data_file), field="text", model="cl100k_base")


# ============ Validate 命令性能测试 ============


class TestValidateBenchmark:
    """validate 命令性能测试"""

    def test_validate_openai_chat(self, messages_data_file, capsys):
        """验证 OpenAI Chat 格式"""
        with Timer("验证 5000条 preset=openai_chat"):
            validate(str(messages_data_file), preset="openai_chat")

    def test_validate_sharegpt(self, messages_data_file, temp_dir):
        """验证 ShareGPT 格式并过滤"""
        output = temp_dir / "validate_valid.jsonl"
        with Timer("验证过滤 5000条 preset=sharegpt"):
            validate(str(messages_data_file), preset="sharegpt", output=str(output), filter_invalid=True)


# ============ Clean 命令性能测试 ============


class TestCleanBenchmark:
    """clean/dedupe 命令性能测试"""

    def test_dedupe_exact_small(self, duplicate_data_file, temp_dir):
        """精确去重小数据集"""
        output = temp_dir / "dedupe_exact.jsonl"
        with Timer("精确去重 10000条(50%重复)"):
            dedupe(str(duplicate_data_file), output=str(output))
        assert output.exists()

    def test_dedupe_by_field(self, duplicate_data_file, temp_dir):
        """按字段去重"""
        output = temp_dir / "dedupe_by_field.jsonl"
        with Timer("按字段去重 10000条 key=text"):
            dedupe(str(duplicate_data_file), key="text", output=str(output))
        assert output.exists()

    def test_clean_drop_empty(self, medium_data_file, temp_dir):
        """清洗-删除空值"""
        output = temp_dir / "clean_drop_empty.jsonl"
        with Timer("清洗 10000条 drop-empty"):
            clean(str(medium_data_file), drop_empty="text", output=str(output))
        assert output.exists()

    def test_clean_min_len(self, medium_data_file, temp_dir):
        """清洗-最小长度过滤"""
        output = temp_dir / "clean_min_len.jsonl"
        with Timer("清洗 10000条 min-len=text:50"):
            clean(str(medium_data_file), min_len="text:50", output=str(output))
        assert output.exists()

    def test_clean_strip(self, medium_data_file, temp_dir):
        """清洗-去除空白"""
        output = temp_dir / "clean_strip.jsonl"
        with Timer("清洗 10000条 strip"):
            clean(str(medium_data_file), strip=True, output=str(output))
        assert output.exists()

    def test_clean_keep_fields(self, medium_data_file, temp_dir):
        """清洗-保留指定字段"""
        output = temp_dir / "clean_keep.jsonl"
        with Timer("清洗 10000条 keep=id,text"):
            clean(str(medium_data_file), keep="id,text", output=str(output))
        assert output.exists()


# ============ IO 命令性能测试 ============


class TestIOBenchmark:
    """concat/diff 命令性能测试"""

    def test_concat_two_files(self, small_data_file, temp_dir):
        """拼接两个文件"""
        # 创建第二个文件
        file2 = temp_dir / "small_data2.jsonl"
        data = generate_test_data(1000, "simple")
        save_data(data, str(file2))

        output = temp_dir / "concat_result.jsonl"
        with Timer("拼接 2个文件 各1000条"):
            concat(str(small_data_file), str(file2), output=str(output))
        assert output.exists()

    def test_concat_multiple_files(self, temp_dir):
        """拼接多个文件"""
        files = []
        for i in range(5):
            filepath = temp_dir / f"concat_part_{i}.jsonl"
            data = generate_test_data(2000, "simple")
            save_data(data, str(filepath))
            files.append(str(filepath))

        output = temp_dir / "concat_multi_result.jsonl"
        with Timer("拼接 5个文件 各2000条"):
            concat(*files, output=str(output))
        assert output.exists()

    def test_diff_small(self, temp_dir):
        """对比两个小文件"""
        # 创建两个有差异的文件
        file1 = temp_dir / "diff_file1.jsonl"
        file2 = temp_dir / "diff_file2.jsonl"

        data1 = generate_test_data(1000, "simple")
        data2 = generate_test_data(1000, "simple")
        # 修改部分数据制造差异
        for i in range(100):
            data2[i]["text"] = f"修改后的文本 {i}"

        save_data(data1, str(file1))
        save_data(data2, str(file2))

        with Timer("diff 2个文件 各1000条"):
            diff(str(file1), str(file2))

    def test_diff_by_key(self, temp_dir):
        """按 key 对比文件"""
        file1 = temp_dir / "diff_key_file1.jsonl"
        file2 = temp_dir / "diff_key_file2.jsonl"

        data1 = generate_test_data(5000, "simple")
        data2 = generate_test_data(5000, "simple")
        # 删除一些记录，添加一些新记录
        data2 = data2[100:] + generate_test_data(100, "simple")

        save_data(data1, str(file1))
        save_data(data2, str(file2))

        with Timer("diff by key 2个文件 各5000条"):
            diff(str(file1), str(file2), key="id")


# ============ Transform 命令性能测试 ============


class TestTransformBenchmark:
    """transform 命令性能测试"""

    def test_transform_preset_small(self, small_data_file, temp_dir):
        """使用预设转换小数据集"""
        output = temp_dir / "transform_preset_small.jsonl"
        with Timer("预设转换 1000条 preset=simple_qa"):
            transform(str(small_data_file), preset="simple_qa", output=str(output))
        # 可能不存在（如果字段不匹配）

    def test_transform_preset_medium(self, messages_data_file, temp_dir):
        """使用预设转换中等消息数据集"""
        output = temp_dir / "transform_preset_medium.jsonl"
        with Timer("预设转换 5000条消息格式 preset=openai_chat"):
            transform(str(messages_data_file), preset="openai_chat", output=str(output))


# ============ 嵌套路径性能测试 ============


class TestNestedPathBenchmark:
    """嵌套路径字段操作性能测试"""

    def test_sample_by_nested_field(self, nested_data_file, temp_dir):
        """按嵌套字段分层采样"""
        output = temp_dir / "sample_nested.jsonl"
        with Timer("分层采样 5000条 by=meta.source"):
            sample(str(nested_data_file), num=1000, by="meta.source", output=str(output))
        assert output.exists()

    def test_clean_nested_drop_empty(self, nested_data_file, temp_dir):
        """清洗-检查嵌套字段空值"""
        output = temp_dir / "clean_nested_empty.jsonl"
        with Timer("清洗 5000条 drop-empty=meta.source"):
            clean(str(nested_data_file), drop_empty="meta.source", output=str(output))
        assert output.exists()

    def test_clean_nested_min_len(self, nested_data_file, temp_dir):
        """清洗-嵌套字段长度过滤"""
        output = temp_dir / "clean_nested_len.jsonl"
        with Timer("清洗 5000条 min-len=content.body:100"):
            clean(str(nested_data_file), min_len="content.body:100", output=str(output))
        assert output.exists()

    def test_dedupe_nested_key(self, nested_data_file, temp_dir):
        """按嵌套字段去重"""
        output = temp_dir / "dedupe_nested.jsonl"
        with Timer("去重 5000条 key=meta.source"):
            dedupe(str(nested_data_file), key="meta.source", output=str(output))
        assert output.exists()


# ============ 综合性能测试 ============


class TestComprehensiveBenchmark:
    """综合场景性能测试"""

    def test_pipeline_sample_clean_dedupe(self, large_data_file, temp_dir):
        """模拟完整处理流程: 采样 -> 清洗 -> 去重"""
        step1_output = temp_dir / "pipeline_step1.jsonl"
        step2_output = temp_dir / "pipeline_step2.jsonl"
        step3_output = temp_dir / "pipeline_step3.jsonl"

        with Timer("完整流程 50000条 -> 采样10000 -> 清洗 -> 去重"):
            # Step 1: 采样
            sample(str(large_data_file), num=10000, type="random", output=str(step1_output), seed=42)

            # Step 2: 清洗
            clean(str(step1_output), min_len="text:10", strip=True, output=str(step2_output))

            # Step 3: 去重
            dedupe(str(step2_output), key="text", output=str(step3_output))

        assert step3_output.exists()

    def test_large_file_stats(self, large_data_file, capsys):
        """大文件快速统计"""
        with Timer("大文件快速统计 50000条"):
            stats(str(large_data_file), full=False)


# ============ 性能基准汇总 ============


def test_performance_summary():
    """输出性能测试说明"""
    print("\n" + "=" * 60)
    print("CLI 性能测试说明")
    print("=" * 60)
    print("""
测试覆盖的核心 CLI 方法:
  - sample/head/tail: 数据采样 (random/head/tail/stratified)
  - stats/token-stats: 数据统计和 Token 统计
  - clean/dedupe: 数据清洗和去重
  - concat/diff: 数据合并和对比
  - transform: 数据转换
  - validate: 数据格式验证

测试数据规模:
  - 小数据集: 1,000 条
  - 中等数据集: 10,000 条
  - 大数据集: 50,000 条
  - 消息格式: 5,000 条

运行完整性能测试:
  pytest tests/test_cli_benchmark.py -v

运行特定测试:
  pytest tests/test_cli_benchmark.py -v -k "sample"
  pytest tests/test_cli_benchmark.py -v -k "stats"
  pytest tests/test_cli_benchmark.py -v -k "token"
  pytest tests/test_cli_benchmark.py -v -k "validate"
  pytest tests/test_cli_benchmark.py -v -k "clean"

使用 pytest-benchmark (可选):
  pip install pytest-benchmark
  pytest tests/test_cli_benchmark.py --benchmark-only
""")
    print("=" * 60)
