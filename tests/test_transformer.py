"""
Basic tests for DataTransformer.
"""
import pytest
import tempfile
import os
from pathlib import Path
from data_transformer import DataTransformer


class TestDataTransformer:
    """Test cases for DataTransformer class."""

    def test_init_empty(self):
        """Test initialization with no data."""
        dt = DataTransformer()
        assert len(dt) == 0
        assert dt.count() == 0

    def test_init_with_data(self):
        """Test initialization with data."""
        data = [{"text": "hello"}, {"text": "world"}]
        dt = DataTransformer(data)
        assert len(dt) == 2

    def test_add_single_item(self):
        """Test adding a single item."""
        dt = DataTransformer()
        dt.add({"text": "test"})
        assert len(dt) == 1
        assert dt[0]["text"] == "test"

    def test_add_multiple_items(self):
        """Test adding multiple items."""
        dt = DataTransformer()
        dt.add([{"text": "test1"}, {"text": "test2"}])
        assert len(dt) == 2

    def test_modify_by_index(self):
        """Test modifying item by index."""
        dt = DataTransformer([{"text": "hello"}])
        dt.modify(index=0, updates={"label": "positive"})
        assert dt[0]["label"] == "positive"

    def test_modify_by_condition(self):
        """Test modifying items by condition."""
        dt = DataTransformer([
            {"score": 0.8},
            {"score": 0.3},
            {"score": 0.9}
        ])
        dt.modify(
            condition=lambda x: x["score"] > 0.5,
            updates={"label": "high"}
        )
        assert dt[0]["label"] == "high"
        assert "label" not in dt[1]
        assert dt[2]["label"] == "high"

    def test_delete_by_index(self):
        """Test deleting item by index."""
        dt = DataTransformer([{"text": "a"}, {"text": "b"}])
        dt.delete(index=0)
        assert len(dt) == 1
        assert dt[0]["text"] == "b"

    def test_delete_by_condition(self):
        """Test deleting items by condition."""
        dt = DataTransformer([
            {"score": 0.8},
            {"score": 0.3},
            {"score": 0.9}
        ])
        dt.delete(condition=lambda x: x["score"] < 0.5)
        assert len(dt) == 2

    def test_filter(self):
        """Test filtering data."""
        dt = DataTransformer([
            {"score": 0.8},
            {"score": 0.3},
            {"score": 0.9}
        ])
        dt.filter(lambda x: x["score"] > 0.5)
        assert len(dt) == 2

    def test_map(self):
        """Test mapping transformation."""
        dt = DataTransformer([{"text": "hello"}])
        dt.map(lambda x: {**x, "processed": True})
        assert dt[0]["processed"] is True

    def test_count(self):
        """Test counting items."""
        dt = DataTransformer([
            {"label": "positive"},
            {"label": "negative"},
            {"label": "positive"}
        ])
        assert dt.count() == 3
        assert dt.count(lambda x: x["label"] == "positive") == 2

    def test_to_sft_messages(self):
        """Test SFT conversion to messages format."""
        dt = DataTransformer([{
            "instruction": "Translate to French",
            "input": "Hello",
            "output": "Bonjour"
        }])
        sft_data = dt.to_sft(style='messages')
        assert "messages" in sft_data[0]
        assert len(sft_data[0]["messages"]) > 0

    def test_to_sft_simple(self):
        """Test SFT conversion to simple format."""
        dt = DataTransformer([{
            "question": "What is AI?",
            "answer": "AI is artificial intelligence"
        }])
        sft_data = dt.to_sft(style='simple')
        assert "instruction" in sft_data[0]
        assert "output" in sft_data[0]

    def test_to_rlhf_pair(self):
        """Test RLHF conversion to pair format."""
        dt = DataTransformer([{
            "prompt": "What is ML?",
            "chosen": "Machine Learning is...",
            "rejected": "I don't know"
        }])
        rlhf_data = dt.to_rlhf(style='pair')
        assert "prompt" in rlhf_data[0]
        assert "chosen" in rlhf_data[0]
        assert "rejected" in rlhf_data[0]

    def test_to_pretrain(self):
        """Test pre-training format conversion."""
        dt = DataTransformer([{
            "instruction": "Test",
            "output": "Result"
        }])
        pretrain_data = dt.to_pretrain()
        assert "text" in pretrain_data[0]
        assert len(pretrain_data[0]["text"]) > 0

    def test_save_load_jsonl(self):
        """Test saving and loading JSONL format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.jsonl"

            dt = DataTransformer([{"text": "hello"}, {"text": "world"}])
            dt.save(str(filepath), file_format='jsonl')

            dt_loaded = DataTransformer.load(str(filepath))
            assert len(dt_loaded) == 2
            assert dt_loaded[0]["text"] == "hello"

    def test_save_load_json(self):
        """Test saving and loading JSON format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.json"

            dt = DataTransformer([{"text": "test"}])
            dt.save(str(filepath), file_format='json')

            dt_loaded = DataTransformer.load(str(filepath))
            assert len(dt_loaded) == 1

    def test_copy(self):
        """Test copying DataTransformer."""
        dt = DataTransformer([{"text": "hello"}])
        dt_copy = dt.copy()

        dt_copy.add({"text": "world"})

        assert len(dt) == 1
        assert len(dt_copy) == 2

    def test_shuffle(self):
        """Test shuffling data."""
        dt = DataTransformer([{"id": i} for i in range(10)])
        original_order = [item["id"] for item in dt.data]

        dt.shuffle(seed=42)
        shuffled_order = [item["id"] for item in dt.data]

        # Should have same elements but potentially different order
        assert sorted(original_order) == sorted(shuffled_order)

    def test_split(self):
        """Test splitting dataset."""
        dt = DataTransformer([{"id": i} for i in range(100)])
        train, val = dt.split(ratio=0.8, shuffle=False)

        assert len(train) == 80
        assert len(val) == 20
        assert len(train) + len(val) == len(dt)

    def test_stats(self):
        """Test dataset statistics."""
        dt = DataTransformer([
            {"text": "hello", "label": "positive"},
            {"text": "world", "label": "negative"}
        ])
        stats = dt.stats()

        assert stats["total"] == 2
        assert "text" in stats["fields"]
        assert "label" in stats["fields"]

    def test_similarity_cosine(self):
        """Test cosine similarity calculation."""
        dt = DataTransformer([
            {"text": "the quick brown fox"},
            {"text": "the fast brown fox"},
            {"text": "python programming"}
        ])

        sim_01 = dt.similarity(0, 1, method='cosine', text_field='text')
        sim_02 = dt.similarity(0, 2, method='cosine', text_field='text')

        # Items 0 and 1 should be more similar than 0 and 2
        assert sim_01 > sim_02

    def test_find_similar(self):
        """Test finding similar items."""
        dt = DataTransformer([
            {"text": "the quick brown fox"},
            {"text": "the fast brown fox"},
            {"text": "a lazy dog"},
            {"text": "the speedy brown fox"}
        ])

        similar = dt.find_similar(reference=0, top_k=2, method='cosine', text_field='text')

        assert len(similar) == 2
        assert all(isinstance(item, tuple) for item in similar)
        assert all(len(item) == 2 for item in similar)

    def test_chain_operations(self):
        """Test chaining multiple operations."""
        result = (DataTransformer()
                  .add([{"score": i * 0.1} for i in range(20)])
                  .filter(lambda x: x["score"] > 0.5)
                  .map(lambda x: {**x, "category": "high"})
                  .shuffle(seed=42))

        assert len(result) == 14  # 0.6 to 1.9
        assert all(item["category"] == "high" for item in result.data)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
