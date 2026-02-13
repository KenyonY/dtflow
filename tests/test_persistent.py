"""Tests for FlaxList persistent backend in DataTransformer."""

import pytest

from dtflow import DataTransformer
from dtflow.storage.io import save_data


@pytest.fixture
def sample_data():
    return [{"id": i, "text": f"item_{i}"} for i in range(100)]


@pytest.fixture
def kv_file(tmp_path, sample_data):
    """Create a .kv file with sample data."""
    filepath = tmp_path / "test.kv"
    save_data(sample_data, str(filepath))
    return filepath


class TestPersistentLoad:
    """Test loading .kv files as persistent backend."""

    def test_load_is_persistent(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        assert dt._is_persistent
        dt.close()

    def test_list_backend_not_persistent(self):
        dt = DataTransformer([{"id": 1}])
        assert not dt._is_persistent

    def test_load_len(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        assert len(dt) == 100
        dt.close()

    def test_load_getitem(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        assert dt[0]["id"] == 0
        assert dt[99]["id"] == 99
        dt.close()

    def test_load_slice(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        items = dt[:5]
        assert len(items) == 5
        assert items[0]["id"] == 0
        assert items[4]["id"] == 4
        dt.close()

    def test_data_property_materializes(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        data = dt.data
        assert isinstance(data, list)
        assert len(data) == 100
        dt.close()

    def test_load_not_found(self, tmp_path):
        filepath = tmp_path / "nonexistent.kv"
        with pytest.raises(FileNotFoundError):
            DataTransformer.load(str(filepath))


class TestPersistentOperations:
    """Test DataTransformer operations with FlaxList backend."""

    def test_head(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        result = dt.head(5)
        assert len(result) == 5
        assert result[0]["id"] == 0
        assert not result._is_persistent
        dt.close()

    def test_tail(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        result = dt.tail(5)
        assert len(result) == 5
        assert result[0]["id"] == 95
        assert not result._is_persistent
        dt.close()

    def test_filter(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        result = dt.filter(lambda x: x.id < 10)
        assert len(result) == 10
        assert not result._is_persistent
        dt.close()

    def test_transform(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        result = dt.transform(lambda x: {"new_id": x.id * 2})
        assert len(result) == 100
        assert result[0]["new_id"] == 0
        assert result[5]["new_id"] == 10
        assert not result._is_persistent
        dt.close()

    def test_sample(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        result = dt.sample(10, seed=42)
        assert len(result) == 10
        assert not result._is_persistent
        dt.close()

    def test_dedupe(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        result = dt.dedupe("id")
        assert len(result) == 100
        assert not result._is_persistent
        dt.close()

    def test_stats(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        s = dt.stats()
        assert s["total"] == 100
        assert "id" in s["fields"]
        assert "text" in s["fields"]
        dt.close()

    def test_fields(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        f = dt.fields()
        assert "id" in f
        assert "text" in f
        dt.close()

    def test_copy_materializes(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        cp = dt.copy()
        assert not cp._is_persistent
        assert len(cp) == 100
        dt.close()


class TestPersistentAppendExtend:
    """Test append/extend with persistent backend."""

    def test_append_persistent(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        result = dt.append({"id": 999, "text": "new"})
        assert result is dt  # in-place
        assert len(dt) == 101
        assert dt[100]["id"] == 999
        dt.close()

    def test_extend_persistent(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        items = [{"id": 1000 + i, "text": f"ext_{i}"} for i in range(5)]
        result = dt.extend(items)
        assert result is dt  # in-place
        assert len(dt) == 105
        dt.close()

    def test_append_list_backend(self):
        dt = DataTransformer([{"id": 1}])
        result = dt.append({"id": 2})
        assert result is not dt  # new instance
        assert len(result) == 2
        assert len(dt) == 1  # original unchanged

    def test_extend_list_backend(self):
        dt = DataTransformer([{"id": 1}])
        result = dt.extend([{"id": 2}, {"id": 3}])
        assert result is not dt  # new instance
        assert len(result) == 3
        assert len(dt) == 1  # original unchanged

    def test_extend_with_datatransformer(self, kv_file):
        dt = DataTransformer.load(str(kv_file))
        other = DataTransformer([{"id": 999, "text": "extra"}])
        dt.extend(other)
        assert len(dt) == 101
        dt.close()


class TestPersistentSave:
    """Test save behavior with persistent backend."""

    def test_save_same_path_noop(self, kv_file):
        """同路径保存应为无操作"""
        dt = DataTransformer.load(str(kv_file))
        dt.save(str(kv_file))
        assert len(dt) == 100
        dt.close()

    def test_save_to_jsonl(self, kv_file, tmp_path):
        """保存到 JSONL 格式"""
        dt = DataTransformer.load(str(kv_file))
        output = tmp_path / "output.jsonl"
        dt.save(str(output))
        assert output.exists()
        dt2 = DataTransformer.load(str(output))
        assert len(dt2) == 100
        dt.close()

    def test_save_to_different_kv(self, kv_file, tmp_path):
        """保存到不同的 .kv 路径"""
        dt = DataTransformer.load(str(kv_file))
        output = tmp_path / "other.kv"
        dt.save(str(output))
        dt2 = DataTransformer.load(str(output))
        assert len(dt2) == 100
        assert dt2._is_persistent
        dt.close()
        dt2.close()

    def test_append_then_reload(self, kv_file):
        """追加后重新加载应能看到新数据"""
        dt = DataTransformer.load(str(kv_file))
        dt.append({"id": 999, "text": "appended"})
        dt.close()

        dt2 = DataTransformer.load(str(kv_file))
        assert len(dt2) == 101
        assert dt2[100]["id"] == 999
        dt2.close()


class TestPersistentContextManager:
    """Test context manager support."""

    def test_context_manager_persistent(self, kv_file):
        with DataTransformer.load(str(kv_file)) as dt:
            assert len(dt) == 100
            assert dt._is_persistent

    def test_context_manager_list_backend(self):
        with DataTransformer([{"id": 1}]) as dt:
            assert len(dt) == 1
            assert not dt._is_persistent

    def test_context_manager_operations(self, kv_file):
        with DataTransformer.load(str(kv_file)) as dt:
            filtered = dt.filter(lambda x: x.id < 5)
            assert len(filtered) == 5
            dt.append({"id": 1000, "text": "in_context"})
            assert len(dt) == 101
