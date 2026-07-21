"""Tests for FlaxKV (.kv/.flaxkv) format support in dtflow.

FlaxList 定位：持久化 I/O 格式 + CLI 只读加速器。
DataTransformer.load() 对 .kv 文件物化为 list，与其他格式行为一致。
CLI 命令（sample/head/tail/stats）利用 FlaxList 随机访问做免加载优化。
"""

import importlib.util

import pytest

from dtflow import DataTransformer
from dtflow.storage.io import load_data, save_data

# 整个文件测的是 flaxkv (.kv) 格式; flaxkv2 为可选依赖 (未必在公共 PyPI), 缺失则整体跳过
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("flaxkv2") is None, reason="flaxkv2 未安装"
)


@pytest.fixture
def sample_data():
    return [{"id": i, "text": f"item_{i}"} for i in range(100)]


@pytest.fixture
def kv_file(tmp_path, sample_data):
    """Create a .kv file with sample data."""
    filepath = tmp_path / "test.kv"
    save_data(sample_data, str(filepath))
    return filepath


class TestKvFormatLoadSave:
    """Test .kv format as a regular I/O format."""

    def test_load_returns_list(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        assert isinstance(dt.data, list)
        assert len(dt) == 100

    def test_load_data(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        assert dt[0]["id"] == 0
        assert dt[99]["id"] == 99

    def test_load_slice(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        items = dt[:5]
        assert len(items) == 5
        assert items[0]["id"] == 0

    def test_load_not_found(self, tmp_path):
        filepath = tmp_path / "nonexistent.kv"
        with pytest.raises(FileNotFoundError):
            DataTransformer.load(str(filepath))

    def test_save_to_jsonl(self, kv_file, tmp_path):
        dt = DataTransformer.load(str(kv_file))
        output = tmp_path / "output.jsonl"
        dt.save(str(output))
        assert output.exists()
        dt2 = DataTransformer.load(str(output))
        assert len(dt2) == 100

    def test_save_to_different_kv(self, kv_file, tmp_path):
        dt = DataTransformer.load(str(kv_file))
        output = tmp_path / "other.kv"
        dt.save(str(output))
        dt2 = DataTransformer.load(str(output))
        assert len(dt2) == 100


class TestKvFormatOperations:
    """Test DataTransformer operations with .kv loaded data."""

    def test_head(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        result = dt.head(5)
        assert len(result) == 5
        assert result[0]["id"] == 0

    def test_tail(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        result = dt.tail(5)
        assert len(result) == 5
        assert result[0]["id"] == 95

    def test_filter(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        result = dt.filter(lambda x: x.id < 10)
        assert len(result) == 10

    def test_transform(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        result = dt.transform(lambda x: {"new_id": x.id * 2})
        assert len(result) == 100
        assert result[0]["new_id"] == 0
        assert result[5]["new_id"] == 10

    def test_sample(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        result = dt.sample(10, seed=42)
        assert len(result) == 10

    def test_dedupe(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        result = dt.dedupe("id")
        assert len(result) == 100

    def test_stats(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        s = dt.stats()
        assert s["total"] == 100
        assert "id" in s["fields"]
        assert "text" in s["fields"]

    def test_fields(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        f = dt.fields()
        assert "id" in f
        assert "text" in f

    def test_copy(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        cp = dt.copy()
        assert len(cp) == 100


class TestAppendExtend:
    """Test append/extend always return new instances."""

    def test_append_returns_new(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        result = dt.append({"id": 999, "text": "new"})
        assert result is not dt
        assert len(result) == 101
        assert len(dt) == 100  # original unchanged

    def test_extend_returns_new(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        items = [{"id": 1000 + i, "text": f"ext_{i}"} for i in range(5)]
        result = dt.extend(items)
        assert result is not dt
        assert len(result) == 105
        assert len(dt) == 100  # original unchanged

    def test_append_list_backend(self):
        dt = DataTransformer([{"id": 1}])
        result = dt.append({"id": 2})
        assert result is not dt
        assert len(result) == 2
        assert len(dt) == 1

    def test_extend_list_backend(self):
        dt = DataTransformer([{"id": 1}])
        result = dt.extend([{"id": 2}, {"id": 3}])
        assert result is not dt
        assert len(result) == 3
        assert len(dt) == 1


class TestFlaxListCliOptimization:
    """Test FlaxList I/O optimizations used by CLI commands."""

    def test_stream_head_flaxkv(self, kv_file):
        from dtflow.storage.io import _stream_head_flaxkv

        result = _stream_head_flaxkv(kv_file, 5)
        assert len(result) == 5
        assert result[0]["id"] == 0

    def test_stream_tail_flaxkv(self, kv_file):
        from dtflow.storage.io import _stream_tail_flaxkv

        result = _stream_tail_flaxkv(kv_file, 5)
        assert len(result) == 5
        assert result[0]["id"] == 95

    def test_stream_random_flaxkv(self, kv_file):
        from dtflow.storage.io import _stream_random_flaxkv

        result = _stream_random_flaxkv(kv_file, 10, seed=42)
        assert len(result) == 10
        # 确保是不同的记录
        ids = {item["id"] for item in result}
        assert len(ids) == 10

    def test_load_data_materializes(self, kv_file, sample_data):
        """load_data 对 .kv 文件返回普通 list"""
        data = load_data(str(kv_file))
        assert isinstance(data, list)
        assert len(data) == 100
        assert data[0]["id"] == 0

    def test_count_rows_fast(self, kv_file):
        from dtflow.streaming import _count_rows_fast

        count = _count_rows_fast(str(kv_file))
        assert count == 100
