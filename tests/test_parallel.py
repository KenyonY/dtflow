"""
并行处理模块测试
"""

import pytest

from dtflow.parallel import get_optimal_workers, parallel_imap, parallel_map


def square(x):
    """简单平方函数（可 pickle）"""
    return x * x


def test_parallel_map_basic():
    """测试基本的并行 map"""
    data = list(range(100))
    result = parallel_map(square, data, workers=2, threshold=10)
    expected = [x * x for x in data]
    assert result == expected


def test_parallel_map_serial_fallback():
    """测试数据量小时回退到串行"""
    data = list(range(10))
    result = parallel_map(square, data, workers=2, threshold=100)
    expected = [x * x for x in data]
    assert result == expected


def test_parallel_map_workers_1():
    """测试 workers=1 时使用串行"""
    data = list(range(2000))
    result = parallel_map(square, data, workers=1)
    expected = [x * x for x in data]
    assert result == expected


def test_parallel_imap_basic():
    """测试 imap 迭代器版本"""
    data = list(range(100))
    result = list(parallel_imap(square, data, workers=2, threshold=10))
    expected = [x * x for x in data]
    assert result == expected


def test_get_optimal_workers():
    """测试最优进程数计算"""
    # 小数据量返回 1
    assert get_optimal_workers(100) == 1
    assert get_optimal_workers(999) == 1

    # 用户指定则直接返回
    assert get_optimal_workers(10000, default=4) == 4
    assert get_optimal_workers(100, default=2) == 2


def test_parallel_map_empty():
    """测试空列表"""
    result = parallel_map(square, [], workers=2)
    assert result == []


def test_parallel_map_preserves_order():
    """测试并行处理保持顺序"""
    data = list(range(1000))
    result = parallel_map(square, data, workers=4, threshold=100)
    expected = [x * x for x in data]
    assert result == expected


# 测试 token_stats 的并行
class TestTokenStatsParallel:
    """token_stats 多进程测试"""

    @pytest.fixture
    def sample_data(self):
        """生成测试数据"""
        return [{"text": f"This is sample text number {i} for testing."} for i in range(100)]

    def test_token_stats_workers_1(self, sample_data):
        """测试 workers=1 (串行)"""
        from dtflow.tokenizers import token_stats

        result = token_stats(sample_data, fields="text", workers=1)
        assert result["count"] == 100
        assert result["total_tokens"] > 0

    def test_token_stats_workers_auto(self, sample_data):
        """测试自动进程数"""
        from dtflow.tokenizers import token_stats

        # 数据量小于阈值，应该使用串行
        result = token_stats(sample_data, fields="text", workers=None)
        assert result["count"] == 100

    def test_token_stats_consistency(self, sample_data):
        """测试串行和并行结果一致性"""
        from dtflow.tokenizers import token_stats

        result_serial = token_stats(sample_data, fields="text", workers=1)
        result_auto = token_stats(sample_data, fields="text", workers=None)

        assert result_serial["total_tokens"] == result_auto["total_tokens"]
        assert result_serial["count"] == result_auto["count"]
        assert result_serial["avg_tokens"] == result_auto["avg_tokens"]


# 测试 schema 验证的并行
class TestSchemaValidateParallel:
    """Schema.validate_parallel 测试"""

    @pytest.fixture
    def sample_chat_data(self):
        """生成 openai_chat 格式测试数据"""
        valid = [{"messages": [{"role": "user", "content": f"Hello {i}"}]} for i in range(80)]
        invalid = [
            {"messages": [{"role": "invalid_role", "content": f"Bad {i}"}]} for i in range(20)
        ]
        return valid + invalid

    def test_validate_parallel_workers_1(self, sample_chat_data):
        """测试 workers=1 (串行)"""
        from dtflow.schema import openai_chat_schema

        schema = openai_chat_schema()
        valid_data, invalid_results = schema.validate_parallel(sample_chat_data, workers=1)
        assert len(valid_data) == 80
        assert len(invalid_results) == 20

    def test_validate_parallel_consistency(self, sample_chat_data):
        """测试串行和并行结果一致性"""
        from dtflow.schema import openai_chat_schema

        schema = openai_chat_schema()

        # 串行
        valid_serial, invalid_serial = schema.validate_parallel(sample_chat_data, workers=1)

        # 自动（数据量小，也会是串行）
        valid_auto, invalid_auto = schema.validate_parallel(sample_chat_data, workers=None)

        assert len(valid_serial) == len(valid_auto)
        assert len(invalid_serial) == len(invalid_auto)

    def test_validate_parallel_empty(self):
        """测试空数据"""
        from dtflow.schema import openai_chat_schema

        schema = openai_chat_schema()
        valid_data, invalid_results = schema.validate_parallel([])
        assert valid_data == []
        assert invalid_results == []
