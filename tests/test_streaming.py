"""流式处理模块测试"""

import importlib.util as _ilu
import json
import os
import tempfile

import pytest

from dtflow.streaming import StreamingTransformer, load_sharded, load_stream, process_shards

# flaxkv 后端为可选依赖 (flaxkv2 未必在公共 PyPI); 未安装时跳过相关测试
requires_flaxkv = pytest.mark.skipif(_ilu.find_spec("flaxkv2") is None, reason="flaxkv2 未安装")


@pytest.fixture
def temp_jsonl():
    """创建临时 JSONL 文件"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        for i in range(100):
            f.write(json.dumps({"id": i, "score": i * 0.01, "text": f"text_{i}"}) + "\n")
        return f.name


@pytest.fixture
def temp_shards(tmp_path):
    """创建分片文件"""
    for shard_idx in range(3):
        shard_file = tmp_path / f"data_{shard_idx:03d}.jsonl"
        with open(shard_file, "w") as f:
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
        result = (
            st.filter(lambda x: x["id"] >= 50)
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
        count = (
            st.filter(lambda x: x["id"] < 10)
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
        files = st.save_sharded(str(output_dir), shard_size=12, prefix="out", show_progress=False)

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

        files = process_shards(temp_shards, str(output_dir), func=process_func, shard_size=10)

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

        # 错误应被跳过（raw=True 保持原有 dict 访问）
        items = st.filter(bad_filter, raw=True).collect()
        assert len(items) == 59  # 0-49 + 51-59 (跳过 50)
        os.unlink(temp_jsonl)

    def test_filter_with_dict_wrapper(self, temp_jsonl):
        """测试 filter 支持 DictWrapper 属性访问"""
        st = load_stream(temp_jsonl)
        items = st.filter(lambda x: x.score > 0.5).collect()
        assert len(items) == 49
        assert all(item["score"] > 0.5 for item in items)
        os.unlink(temp_jsonl)

    def test_filter_on_error_raise(self, temp_jsonl):
        """测试 filter on_error=raise"""
        st = load_stream(temp_jsonl)

        def bad_filter(x):
            if x.id == 50:
                raise ValueError("Error at 50")
            return x.id < 60

        with pytest.raises(ValueError, match="Error at 50"):
            st.filter(bad_filter, on_error="raise").collect()
        os.unlink(temp_jsonl)

    def test_filter_on_error_keep(self, temp_jsonl):
        """测试 filter on_error=keep 保留错误行"""
        st = load_stream(temp_jsonl)

        def bad_filter(x):
            if x.id == 50:
                raise ValueError("Error at 50")
            return x.id < 60

        items = st.filter(bad_filter, on_error="keep").collect()
        # 0-49 通过 + 50 错误保留 + 51-59 通过 = 60
        assert len(items) == 60
        assert any(item["id"] == 50 for item in items)
        os.unlink(temp_jsonl)

    def test_filter_raw_mode(self, temp_jsonl):
        """测试 filter raw 模式跳过 DictWrapper"""
        st = load_stream(temp_jsonl)
        items = st.filter(lambda x: x["id"] < 5, raw=True).collect()
        assert len(items) == 5
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


@requires_flaxkv
class TestFlaxKVStreaming:
    """FlaxKV (FlaxList backend) 流式处理测试"""

    @pytest.fixture
    def flaxkv_file(self, tmp_path):
        """创建临时 FlaxKV 文件"""
        from dtflow.storage.io import save_data

        data = [{"id": i, "score": i * 0.01, "text": f"text_{i}"} for i in range(100)]
        filepath = tmp_path / "data.flaxkv"
        save_data(data, str(filepath))
        return str(filepath)

    def test_load_stream(self, flaxkv_file):
        st = load_stream(flaxkv_file)
        items = st.collect()
        assert len(items) == 100
        assert items[0]["id"] == 0
        assert items[99]["id"] == 99

    def test_filter(self, flaxkv_file):
        st = load_stream(flaxkv_file)
        items = st.filter(lambda x: x["id"] < 10).collect()
        assert len(items) == 10
        assert all(item["id"] < 10 for item in items)

    def test_transform(self, flaxkv_file):
        st = load_stream(flaxkv_file)
        items = st.transform(lambda x: {"doubled": x["id"] * 2}).collect()
        assert len(items) == 100
        assert items[0] == {"doubled": 0}
        assert items[50] == {"doubled": 100}

    def test_chain_operations(self, flaxkv_file):
        st = load_stream(flaxkv_file)
        items = (
            st.filter(lambda x: x["id"] >= 50)
            .transform(lambda x: {"new_id": x["id"]})
            .head(10)
            .collect()
        )
        assert len(items) == 10
        assert items[0]["new_id"] == 50

    def test_head(self, flaxkv_file):
        st = load_stream(flaxkv_file)
        items = st.head(5).collect()
        assert len(items) == 5
        assert [item["id"] for item in items] == [0, 1, 2, 3, 4]

    def test_skip(self, flaxkv_file):
        st = load_stream(flaxkv_file)
        items = st.skip(95).collect()
        assert len(items) == 5
        assert [item["id"] for item in items] == [95, 96, 97, 98, 99]

    def test_count(self, flaxkv_file):
        st = load_stream(flaxkv_file)
        count = st.filter(lambda x: x["id"] < 30).count()
        assert count == 30

    def test_count_rows_fast(self, flaxkv_file):
        from dtflow.streaming import _count_rows_fast

        count = _count_rows_fast(flaxkv_file)
        assert count == 100

    def test_save_to_jsonl(self, flaxkv_file, tmp_path):
        """FlaxKV 流式读 → JSONL 保存"""
        output = tmp_path / "out.jsonl"
        st = load_stream(flaxkv_file)
        count = st.filter(lambda x: x["id"] < 20).save(str(output), show_progress=False)

        assert count == 20
        loaded = load_stream(str(output)).collect()
        assert len(loaded) == 20

    def test_save_to_flaxkv(self, flaxkv_file, tmp_path):
        """FlaxKV 流式读 → FlaxKV 保存"""
        output = tmp_path / "out.flaxkv"
        st = load_stream(flaxkv_file)
        count = st.filter(lambda x: x["id"] < 50).save(str(output), show_progress=False)

        assert count == 50
        loaded = load_stream(str(output)).collect()
        assert len(loaded) == 50
        assert loaded[0]["id"] == 0
        assert loaded[49]["id"] == 49

    def test_save_to_flaxkv_large(self, tmp_path):
        """FlaxKV 流式保存大数据（验证分批 extend）"""
        # 先创建一个 JSONL 源
        src = tmp_path / "src.jsonl"
        with open(src, "w") as f:
            for i in range(15000):
                f.write(json.dumps({"id": i}) + "\n")

        output = tmp_path / "out.flaxkv"
        st = load_stream(str(src))
        count = st.save(str(output), show_progress=False, batch_size=5000)

        assert count == 15000
        loaded = load_stream(str(output)).collect()
        assert len(loaded) == 15000

    def test_jsonl_to_flaxkv_roundtrip(self, tmp_path):
        """JSONL → FlaxKV → JSONL 往返测试"""
        # 创建 JSONL
        src = tmp_path / "src.jsonl"
        with open(src, "w") as f:
            for i in range(50):
                f.write(json.dumps({"id": i, "msg": f"hello_{i}"}) + "\n")

        # JSONL → FlaxKV
        mid = tmp_path / "mid.flaxkv"
        count1 = load_stream(str(src)).save(str(mid), show_progress=False)
        assert count1 == 50

        # FlaxKV → JSONL
        dst = tmp_path / "dst.jsonl"
        count2 = load_stream(str(mid)).save(str(dst), show_progress=False)
        assert count2 == 50

        # 验证内容一致
        original = load_stream(str(src)).collect()
        final = load_stream(str(dst)).collect()
        assert original == final

    def test_file_not_found(self, tmp_path):
        filepath = tmp_path / "nonexistent.flaxkv"
        with pytest.raises(FileNotFoundError):
            load_stream(str(filepath))

    def test_empty(self, tmp_path):
        from dtflow.storage.io import save_data

        filepath = tmp_path / "empty.flaxkv"
        save_data([], str(filepath))

        st = load_stream(str(filepath))
        items = st.collect()
        assert items == []

    def test_batch_iteration(self, flaxkv_file):
        st = load_stream(flaxkv_file)
        batches = list(st.batch(30))
        assert len(batches) == 4  # 30 + 30 + 30 + 10
        assert len(batches[0]) == 30
        assert len(batches[3]) == 10


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
        with open(large_file, "w") as f:
            for i in range(1000):
                f.write(json.dumps({"id": i, "value": i * 2}) + "\n")

        output_path = tmp_path / "large_output.csv"

        st = load_stream(str(large_file))
        count = st.save(str(output_path), show_progress=False, batch_size=100)

        assert count == 1000

        import polars as pl

        df = pl.read_csv(output_path)
        assert len(df) == 1000


class TestStreamingEnhancements:
    """StreamingTransformer 增强方法测试"""

    # ---- transform 增强 ----

    def test_transform_dict_wrapper(self, temp_jsonl):
        """测试 transform 支持 DictWrapper 属性访问"""
        st = load_stream(temp_jsonl)
        items = st.transform(lambda x: {"doubled": x.id * 2}).collect()
        assert len(items) == 100
        assert items[0] == {"doubled": 0}
        assert items[50] == {"doubled": 100}
        os.unlink(temp_jsonl)

    def test_transform_on_error_raise(self, temp_jsonl):
        """测试 transform on_error=raise"""
        st = load_stream(temp_jsonl)

        def bad_transform(x):
            if x.id == 50:
                raise ValueError("Error at 50")
            return {"new_id": x.id}

        with pytest.raises(ValueError, match="Error at 50"):
            st.transform(bad_transform, on_error="raise").collect()
        os.unlink(temp_jsonl)

    def test_transform_raw_mode(self, temp_jsonl):
        """测试 transform raw 模式跳过 DictWrapper"""
        st = load_stream(temp_jsonl)
        items = st.transform(lambda x: {"new_id": x["id"]}, raw=True).collect()
        assert len(items) == 100
        assert items[0] == {"new_id": 0}
        os.unlink(temp_jsonl)

    def test_transform_on_error_skip_drops_total(self, temp_jsonl):
        """on_error=skip 时 total 应为 None（可能跳行）"""
        st = load_stream(temp_jsonl)
        t = st.transform(lambda x: {"id": x.id})
        assert t._total is None  # skip 模式不保留 total

    def test_transform_on_error_raise_keeps_total(self, temp_jsonl):
        """on_error=raise 时保留 total"""
        st = load_stream(temp_jsonl)
        t = st.transform(lambda x: {"id": x.id}, on_error="raise")
        assert t._total == 100
        os.unlink(temp_jsonl)

    # ---- dedupe ----

    def test_dedupe_by_field(self, tmp_path):
        """按字段去重"""
        f = tmp_path / "dup.jsonl"
        with open(f, "w") as fp:
            for item in [
                {"id": 1, "name": "a"},
                {"id": 2, "name": "b"},
                {"id": 1, "name": "c"},  # id 重复
                {"id": 3, "name": "a"},
            ]:
                fp.write(json.dumps(item) + "\n")

        items = load_stream(str(f)).dedupe("id").collect()
        assert len(items) == 3
        assert [x["id"] for x in items] == [1, 2, 3]

    def test_dedupe_full(self, tmp_path):
        """全量去重"""
        f = tmp_path / "dup.jsonl"
        with open(f, "w") as fp:
            for item in [
                {"id": 1, "name": "a"},
                {"id": 1, "name": "a"},  # 完全重复
                {"id": 1, "name": "b"},  # 不同
            ]:
                fp.write(json.dumps(item) + "\n")

        items = load_stream(str(f)).dedupe().collect()
        assert len(items) == 2

    def test_dedupe_callable_key(self, tmp_path):
        """callable key 去重"""
        f = tmp_path / "dup.jsonl"
        with open(f, "w") as fp:
            for item in [
                {"name": "Alice"},
                {"name": "alice"},
                {"name": "Bob"},
            ]:
                fp.write(json.dumps(item) + "\n")

        items = load_stream(str(f)).dedupe(lambda x: x.name.lower()).collect()
        assert len(items) == 2
        assert items[0]["name"] == "Alice"
        assert items[1]["name"] == "Bob"

    def test_dedupe_multi_field(self, tmp_path):
        """多字段组合去重"""
        f = tmp_path / "dup.jsonl"
        with open(f, "w") as fp:
            for item in [
                {"a": 1, "b": "x"},
                {"a": 1, "b": "y"},
                {"a": 1, "b": "x"},  # (a, b) 重复
            ]:
                fp.write(json.dumps(item) + "\n")

        items = load_stream(str(f)).dedupe(["a", "b"]).collect()
        assert len(items) == 2

    # ---- flat_map ----

    def test_flat_map_basic(self, tmp_path):
        """基本一对多拆分"""
        f = tmp_path / "multi.jsonl"
        with open(f, "w") as fp:
            fp.write(json.dumps({"items": [1, 2, 3]}) + "\n")
            fp.write(json.dumps({"items": [4, 5]}) + "\n")

        items = load_stream(str(f)).flat_map(lambda x: [{"val": v} for v in x.items]).collect()
        assert len(items) == 5
        assert [x["val"] for x in items] == [1, 2, 3, 4, 5]

    def test_flat_map_error_skip(self, tmp_path):
        """flat_map 错误跳过"""
        f = tmp_path / "data.jsonl"
        with open(f, "w") as fp:
            fp.write(json.dumps({"items": [1, 2]}) + "\n")
            fp.write(json.dumps({"no_items": True}) + "\n")
            fp.write(json.dumps({"items": [3]}) + "\n")

        items = load_stream(str(f)).flat_map(lambda x: [{"val": v} for v in x.items]).collect()
        assert len(items) == 3
        assert [x["val"] for x in items] == [1, 2, 3]

    def test_flat_map_error_raise(self, tmp_path):
        """flat_map on_error=raise"""
        f = tmp_path / "data.jsonl"
        with open(f, "w") as fp:
            fp.write(json.dumps({"items": [1]}) + "\n")
            fp.write(json.dumps({"no_items": True}) + "\n")

        with pytest.raises(AttributeError):
            (
                load_stream(str(f))
                .flat_map(lambda x: [{"val": v} for v in x.items], on_error="raise")
                .collect()
            )

    def test_flat_map_total_is_none(self, tmp_path):
        """flat_map 的 total 应为 None"""
        f = tmp_path / "data.jsonl"
        with open(f, "w") as fp:
            fp.write(json.dumps({"v": 1}) + "\n")

        st = load_stream(str(f)).flat_map(lambda x: [x])
        assert st._total is None

    # ---- tail ----

    def test_tail_basic(self, temp_jsonl):
        """取最后 N 条"""
        items = load_stream(temp_jsonl).tail(5).collect()
        assert len(items) == 5
        assert [x["id"] for x in items] == [95, 96, 97, 98, 99]
        os.unlink(temp_jsonl)

    def test_tail_more_than_data(self, tmp_path):
        """数据不足时返回全部"""
        f = tmp_path / "small.jsonl"
        with open(f, "w") as fp:
            for i in range(3):
                fp.write(json.dumps({"id": i}) + "\n")

        items = load_stream(str(f)).tail(10).collect()
        assert len(items) == 3

    # ---- sample ----

    def test_sample_basic(self, temp_jsonl):
        """基本采样"""
        items = load_stream(temp_jsonl).sample(10).collect()
        assert len(items) == 10
        # 采样结果应是原始数据的子集
        ids = {x["id"] for x in items}
        assert all(0 <= i < 100 for i in ids)
        os.unlink(temp_jsonl)

    def test_sample_seed_reproducible(self, temp_jsonl):
        """seed 可重现"""
        items1 = load_stream(temp_jsonl).sample(10, seed=42).collect()
        items2 = load_stream(temp_jsonl).sample(10, seed=42).collect()
        assert items1 == items2
        os.unlink(temp_jsonl)

    def test_sample_more_than_data(self, tmp_path):
        """采样数大于数据量时返回全部"""
        f = tmp_path / "small.jsonl"
        with open(f, "w") as fp:
            for i in range(3):
                fp.write(json.dumps({"id": i}) + "\n")

        items = load_stream(str(f)).sample(100).collect()
        assert len(items) == 3

    # ---- peek ----

    def test_peek_side_effect(self, temp_jsonl):
        """peek 触发副作用但不改变数据"""
        seen = []
        items = load_stream(temp_jsonl).head(5).peek(lambda x: seen.append(x["id"])).collect()

        assert len(items) == 5
        assert seen == [0, 1, 2, 3, 4]
        # 数据不变
        assert items[0] == {"id": 0, "score": 0.0, "text": "text_0"}
        os.unlink(temp_jsonl)

    def test_peek_preserves_total(self, temp_jsonl):
        """peek 保留 total"""
        st = load_stream(temp_jsonl)
        peeked = st.peek(lambda x: None)
        assert peeked._total == st._total
        os.unlink(temp_jsonl)

    # ---- shuffle ----

    def test_shuffle_basic(self, temp_jsonl):
        """洗牌后数据量不变，顺序改变"""
        original = load_stream(temp_jsonl).collect()
        shuffled = load_stream(temp_jsonl).shuffle(seed=42).collect()
        assert len(shuffled) == len(original)
        assert {x["id"] for x in shuffled} == {x["id"] for x in original}
        # 极大概率顺序不同
        assert [x["id"] for x in shuffled] != [x["id"] for x in original]
        os.unlink(temp_jsonl)

    def test_shuffle_seed_reproducible(self, temp_jsonl):
        """shuffle seed 可重现"""
        s1 = load_stream(temp_jsonl).shuffle(seed=123).collect()
        s2 = load_stream(temp_jsonl).shuffle(seed=123).collect()
        assert s1 == s2
        os.unlink(temp_jsonl)

    # ---- split ----

    def test_split_basic(self, temp_jsonl):
        """按比例切分"""
        train, val, test = load_stream(temp_jsonl).split([0.8, 0.1, 0.1], seed=42)
        train_data = train.collect()
        val_data = val.collect()
        test_data = test.collect()

        assert len(train_data) + len(val_data) + len(test_data) == 100
        assert len(train_data) == 80
        assert len(val_data) == 10
        assert len(test_data) == 10

        # 无重复
        all_ids = [x["id"] for x in train_data + val_data + test_data]
        assert len(set(all_ids)) == 100
        os.unlink(temp_jsonl)

    def test_split_two_way(self, temp_jsonl):
        """二分切分"""
        parts = load_stream(temp_jsonl).split([0.7, 0.3], seed=0)
        assert len(parts) == 2
        assert len(parts[0].collect()) + len(parts[1].collect()) == 100
        os.unlink(temp_jsonl)
