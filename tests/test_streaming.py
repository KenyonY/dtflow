"""流式处理模块测试"""
import json
import os
import tempfile
from pathlib import Path

import pytest

from dtflow.streaming import (
    StreamingTransformer,
    load_stream,
    load_sharded,
    process_shards,
)


@pytest.fixture
def temp_jsonl():
    """创建临时 JSONL 文件"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        for i in range(100):
            f.write(json.dumps({"id": i, "score": i * 0.01, "text": f"text_{i}"}) + "\n")
        return f.name


@pytest.fixture
def temp_shards(tmp_path):
    """创建分片文件"""
    for shard_idx in range(3):
        shard_file = tmp_path / f"data_{shard_idx:03d}.jsonl"
        with open(shard_file, 'w') as f:
            for i in range(10):
                item_id = shard_idx * 10 + i
                f.write(json.dumps({"id": item_id, "value": item_id * 2}) + "\n")
    return str(tmp_path / "data_*.jsonl")


class TestStreamingTransformer:
    """StreamingTransformer 测试"""

    def test_load_stream(self, temp_jsonl):
        """测试流式加载"""
        st = StreamingTransformer.load_stream(temp_jsonl)
        assert st._source_path == temp_jsonl

        # 迭代并收集
        items = st.collect()
        assert len(items) == 100
        assert items[0]["id"] == 0
        assert items[99]["id"] == 99
        os.unlink(temp_jsonl)

    def test_filter(self, temp_jsonl):
        """测试惰性过滤"""
        st = load_stream(temp_jsonl)
        filtered = st.filter(lambda x: x["score"] > 0.5)

        # 惰性：还没执行
        assert len(filtered._operations) == 1

        # 收集时才执行
        items = filtered.collect()
        assert len(items) == 49  # score > 0.5 的有 51-99，共 49 条
        assert all(item["score"] > 0.5 for item in items)
        os.unlink(temp_jsonl)

    def test_transform(self, temp_jsonl):
        """测试惰性转换"""
        st = load_stream(temp_jsonl)
        transformed = st.transform(lambda x: {"new_id": x["id"] * 2})

        items = transformed.collect()
        assert len(items) == 100
        assert items[0] == {"new_id": 0}
        assert items[50] == {"new_id": 100}
        os.unlink(temp_jsonl)

    def test_chain_operations(self, temp_jsonl):
        """测试链式操作"""
        st = load_stream(temp_jsonl)
        result = (st
            .filter(lambda x: x["id"] >= 50)
            .transform(lambda x: {"doubled": x["id"] * 2})
            .filter(lambda x: x["doubled"] < 150)
        )

        items = result.collect()
        # id >= 50 且 id * 2 < 150 => id >= 50 且 id < 75 => 50-74，共 25 条
        assert len(items) == 25
        os.unlink(temp_jsonl)

    def test_head(self, temp_jsonl):
        """测试 head"""
        st = load_stream(temp_jsonl)
        items = st.head(5).collect()
        assert len(items) == 5
        assert [item["id"] for item in items] == [0, 1, 2, 3, 4]
        os.unlink(temp_jsonl)

    def test_skip(self, temp_jsonl):
        """测试 skip"""
        st = load_stream(temp_jsonl)
        items = st.skip(95).collect()
        assert len(items) == 5
        assert [item["id"] for item in items] == [95, 96, 97, 98, 99]
        os.unlink(temp_jsonl)

    def test_batch(self, temp_jsonl):
        """测试批次迭代"""
        st = load_stream(temp_jsonl)
        batches = list(st.batch(30))

        assert len(batches) == 4  # 30 + 30 + 30 + 10
        assert len(batches[0]) == 30
        assert len(batches[3]) == 10
        os.unlink(temp_jsonl)

    def test_save(self, temp_jsonl, tmp_path):
        """测试流式保存"""
        output_path = tmp_path / "output.jsonl"

        st = load_stream(temp_jsonl)
        count = (st
            .filter(lambda x: x["id"] < 10)
            .transform(lambda x: {"text": x["text"]})
            .save(str(output_path), show_progress=False)
        )

        assert count == 10

        # 验证输出
        with open(output_path) as f:
            lines = f.readlines()
        assert len(lines) == 10
        os.unlink(temp_jsonl)

    def test_count(self, temp_jsonl):
        """测试计数"""
        st = load_stream(temp_jsonl)
        count = st.filter(lambda x: x["id"] < 30).count()
        assert count == 30
        os.unlink(temp_jsonl)


class TestShardedProcessing:
    """分片处理测试"""

    def test_load_sharded(self, temp_shards):
        """测试加载分片文件"""
        st = load_sharded(temp_shards)
        items = st.collect()

        assert len(items) == 30  # 3 shards * 10 items
        # 验证顺序
        assert items[0]["id"] == 0
        assert items[10]["id"] == 10
        assert items[20]["id"] == 20

    def test_save_sharded(self, temp_shards, tmp_path):
        """测试分片保存"""
        output_dir = tmp_path / "output_shards"

        st = load_sharded(temp_shards)
        files = st.save_sharded(
            str(output_dir),
            shard_size=12,
            prefix="out",
            show_progress=False
        )

        assert len(files) == 3  # 30 items / 12 per shard = 3 shards

        # 验证文件名
        assert "out-00000.jsonl" in files[0]
        assert "out-00001.jsonl" in files[1]
        assert "out-00002.jsonl" in files[2]

        # 验证内容
        total = 0
        for f in files:
            with open(f) as fp:
                total += sum(1 for _ in fp)
        assert total == 30

    def test_process_shards(self, temp_shards, tmp_path):
        """测试分片处理函数"""
        output_dir = tmp_path / "processed"

        def process_func(item):
            if item["id"] % 2 == 0:
                return {"even_id": item["id"]}
            return None  # 过滤奇数

        files = process_shards(
            temp_shards,
            str(output_dir),
            func=process_func,
            shard_size=10
        )

        # 30 items, 过滤掉奇数剩 15 条
        total = 0
        for f in files:
            with open(f) as fp:
                for line in fp:
                    data = json.loads(line)
                    assert "even_id" in data
                    total += 1
        assert total == 15


class TestEdgeCases:
    """边界情况测试"""

    def test_empty_file(self, tmp_path):
        """测试空文件"""
        empty_file = tmp_path / "empty.jsonl"
        empty_file.write_text("")

        st = load_stream(str(empty_file))
        items = st.collect()
        assert items == []

    def test_file_not_found(self):
        """测试文件不存在"""
        with pytest.raises(FileNotFoundError):
            load_stream("nonexistent.jsonl")

    def test_unsupported_format(self, tmp_path):
        """测试不支持的文件格式"""
        txt_file = tmp_path / "data.txt"
        txt_file.write_text("some text")

        with pytest.raises(ValueError, match="不支持的流式格式"):
            load_stream(str(txt_file))

    def test_no_matching_shards(self):
        """测试没有匹配的分片"""
        with pytest.raises(FileNotFoundError, match="没有匹配"):
            load_sharded("/nonexistent/path/*.jsonl")

    def test_error_handling_in_filter(self, temp_jsonl):
        """测试过滤中的错误处理"""
        st = load_stream(temp_jsonl)

        def bad_filter(x):
            if x["id"] == 50:
                raise ValueError("Error at 50")
            return x["id"] < 60

        # 错误应被跳过
        items = st.filter(bad_filter).collect()
        assert len(items) == 59  # 0-49 + 51-59 (跳过 50)
        os.unlink(temp_jsonl)

    def test_error_handling_in_transform(self, temp_jsonl):
        """测试转换中的错误处理"""
        st = load_stream(temp_jsonl)

        def bad_transform(x):
            if x["id"] == 50:
                raise ValueError("Error at 50")
            return {"new_id": x["id"]}

        # 错误应被跳过
        items = st.transform(bad_transform).collect()
        assert len(items) == 99  # 跳过 50
        os.unlink(temp_jsonl)

    def test_iterator_consumed(self, temp_jsonl):
        """测试迭代器只能消费一次"""
        st = load_stream(temp_jsonl)

        # 第一次收集
        items1 = st.collect()
        assert len(items1) == 100

        # 第二次收集应该为空（迭代器已消费）
        items2 = st.collect()
        assert len(items2) == 0
        os.unlink(temp_jsonl)

    def test_transform_error_tracking(self, temp_jsonl, tmp_path):
        """测试转换错误跟踪"""
        st = load_stream(temp_jsonl)

        def bad_transform(x):
            if x["id"] % 10 == 5:  # 5, 15, 25, ... 共 10 条会出错
                raise KeyError("missing_key")
            return {"new_id": x["id"]}

        transformed = st.transform(bad_transform)
        output_path = tmp_path / "output.jsonl"
        count = transformed.save(str(output_path), show_progress=False)

        # 验证结果
        assert count == 90  # 100 - 10 = 90
        assert transformed._error_count == 10
        assert "KeyError" in transformed._first_error
        os.unlink(temp_jsonl)


class TestBatchedSave:
    """测试批量保存（CSV/Parquet/Arrow）的流式写入"""

    def test_save_csv_streaming(self, temp_jsonl, tmp_path):
        """测试流式保存到 CSV"""
        import polars as pl

        output_path = tmp_path / "output.csv"

        st = load_stream(temp_jsonl)
        count = st.filter(lambda x: x["id"] < 50).save(
            str(output_path), show_progress=False, batch_size=10
        )

        assert count == 50

        # 验证 CSV 内容
        df = pl.read_csv(output_path)
        assert len(df) == 50
        assert "id" in df.columns
        assert df["id"].min() == 0
        assert df["id"].max() == 49
        os.unlink(temp_jsonl)

    def test_save_parquet_streaming(self, temp_jsonl, tmp_path):
        """测试流式保存到 Parquet"""
        import polars as pl

        output_path = tmp_path / "output.parquet"

        st = load_stream(temp_jsonl)
        count = st.filter(lambda x: x["id"] < 30).save(
            str(output_path), show_progress=False, batch_size=10
        )

        assert count == 30

        # 验证 Parquet 内容
        df = pl.read_parquet(output_path)
        assert len(df) == 30
        os.unlink(temp_jsonl)

    def test_save_arrow_streaming(self, temp_jsonl, tmp_path):
        """测试流式保存到 Arrow"""
        import polars as pl

        output_path = tmp_path / "output.arrow"

        st = load_stream(temp_jsonl)
        count = st.filter(lambda x: x["id"] < 20).save(
            str(output_path), show_progress=False, batch_size=5
        )

        assert count == 20

        # 验证 Arrow 内容
        df = pl.read_ipc(output_path)
        assert len(df) == 20
        os.unlink(temp_jsonl)

    def test_save_csv_large_batch(self, tmp_path):
        """测试大批量数据的流式保存（验证不会 OOM）"""
        # 创建大文件
        large_file = tmp_path / "large.jsonl"
        with open(large_file, 'w') as f:
            for i in range(1000):
                f.write(json.dumps({"id": i, "value": i * 2}) + "\n")

        output_path = tmp_path / "large_output.csv"

        st = load_stream(str(large_file))
        count = st.save(str(output_path), show_progress=False, batch_size=100)

        assert count == 1000

        import polars as pl
        df = pl.read_csv(output_path)
        assert len(df) == 1000
