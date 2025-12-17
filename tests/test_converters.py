"""
Tests for converters module.
"""
import pytest
from dtflow import DataTransformer
from dtflow.converters import (
    to_hf_dataset,
    from_hf_dataset,
    to_hf_chat_format,
    from_openai_batch,
    to_openai_batch,
    to_llama_factory,
    to_axolotl,
    messages_to_text,
)


class TestHuggingFaceConverters:
    """Test cases for HuggingFace converters."""

    @pytest.fixture
    def sample_data(self):
        return [
            {"text": "Hello", "label": "positive"},
            {"text": "World", "label": "negative"},
        ]

    def test_to_hf_dataset(self, sample_data):
        """Test conversion to HuggingFace Dataset."""
        pytest.importorskip("datasets")

        ds = to_hf_dataset(sample_data)

        assert len(ds) == 2
        assert "text" in ds.column_names
        assert "label" in ds.column_names
        assert ds[0]["text"] == "Hello"

    def test_from_hf_dataset_object(self, sample_data):
        """Test conversion from HuggingFace Dataset object."""
        datasets = pytest.importorskip("datasets")

        ds = datasets.Dataset.from_list(sample_data)
        data = from_hf_dataset(ds)

        assert len(data) == 2
        assert data[0]["text"] == "Hello"

    def test_to_hf_chat_format(self):
        """Test conversion to HuggingFace chat format."""
        data = [{"messages": [{"role": "user", "content": "Hi"}]}]
        dt = DataTransformer(data)

        result = dt.to(to_hf_chat_format())

        assert "messages" in result[0]
        assert result[0]["messages"][0]["role"] == "user"

    def test_to_hf_chat_format_with_generation_prompt(self):
        """Test with generation prompt flag."""
        data = [{"messages": [{"role": "user", "content": "Hi"}]}]
        dt = DataTransformer(data)

        result = dt.to(to_hf_chat_format(add_generation_prompt=True))

        assert result[0]["add_generation_prompt"] is True


class TestOpenAIBatchConverters:
    """Test cases for OpenAI Batch API converters."""

    def test_to_openai_batch(self):
        """Test conversion to OpenAI batch format."""
        data = [{
            "messages": [
                {"role": "user", "content": "Hello"}
            ]
        }]
        dt = DataTransformer(data)

        result = dt.to(to_openai_batch(model="gpt-4o"))

        assert len(result) == 1
        assert result[0]["method"] == "POST"
        assert result[0]["url"] == "/v1/chat/completions"
        assert result[0]["body"]["model"] == "gpt-4o"
        assert result[0]["body"]["messages"] == data[0]["messages"]
        assert "custom_id" in result[0]

    def test_to_openai_batch_with_custom_id(self):
        """Test with custom ID field."""
        data = [{
            "id": "my-request-1",
            "messages": [{"role": "user", "content": "Hello"}]
        }]
        dt = DataTransformer(data)

        result = dt.to(to_openai_batch(custom_id_field="id"))

        assert result[0]["custom_id"] == "my-request-1"

    def test_from_openai_batch(self):
        """Test conversion from OpenAI batch results."""
        batch_output = [{
            "custom_id": "req-1",
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [{"message": {"content": "Hi there!"}}],
                    "model": "gpt-4o",
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}
                }
            }
        }]

        results = from_openai_batch(batch_output)

        assert len(results) == 1
        assert results[0]["custom_id"] == "req-1"
        assert results[0]["content"] == "Hi there!"
        assert results[0]["model"] == "gpt-4o"

    def test_from_openai_batch_filters_errors(self):
        """Test that failed requests are filtered out."""
        batch_output = [
            {
                "custom_id": "req-1",
                "response": {
                    "status_code": 200,
                    "body": {
                        "choices": [{"message": {"content": "Success"}}],
                        "model": "gpt-4o"
                    }
                }
            },
            {
                "custom_id": "req-2",
                "response": {
                    "status_code": 500,
                    "body": {"error": "Internal error"}
                }
            }
        ]

        results = from_openai_batch(batch_output)

        assert len(results) == 1
        assert results[0]["custom_id"] == "req-1"


class TestLLaMAFactoryConverter:
    """Test cases for LLaMA-Factory format converter."""

    def test_to_llama_factory_basic(self):
        """Test basic conversion."""
        data = [{
            "instruction": "写一首诗",
            "input": "",
            "output": "春风吹过..."
        }]
        dt = DataTransformer(data)

        result = dt.to(to_llama_factory())

        assert result[0]["instruction"] == "写一首诗"
        assert result[0]["input"] == ""
        assert result[0]["output"] == "春风吹过..."

    def test_to_llama_factory_custom_fields(self):
        """Test with custom field mapping."""
        data = [{"q": "问题", "ctx": "上下文", "a": "回答"}]
        dt = DataTransformer(data)

        result = dt.to(to_llama_factory(
            instruction_field="q",
            input_field="ctx",
            output_field="a"
        ))

        assert result[0]["instruction"] == "问题"
        assert result[0]["input"] == "上下文"
        assert result[0]["output"] == "回答"

    def test_to_llama_factory_with_system(self):
        """Test with system prompt."""
        data = [{
            "instruction": "问题",
            "input": "",
            "output": "回答",
            "sys": "你是助手"
        }]
        dt = DataTransformer(data)

        result = dt.to(to_llama_factory(system_field="sys"))

        assert result[0]["system"] == "你是助手"


class TestAxolotlConverter:
    """Test cases for Axolotl format converter."""

    def test_to_axolotl_with_conversations(self):
        """Test conversion with existing conversations."""
        data = [{
            "conversations": [
                {"from": "human", "value": "Hi"},
                {"from": "gpt", "value": "Hello!"}
            ]
        }]
        dt = DataTransformer(data)

        result = dt.to(to_axolotl())

        assert result[0]["conversations"][0]["from"] == "human"
        assert result[0]["conversations"][1]["from"] == "gpt"

    def test_to_axolotl_from_messages(self):
        """Test conversion from messages format."""
        data = [{
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"}
            ]
        }]
        dt = DataTransformer(data)

        result = dt.to(to_axolotl())

        assert result[0]["conversations"][0]["from"] == "human"
        assert result[0]["conversations"][0]["value"] == "Hi"
        assert result[0]["conversations"][1]["from"] == "gpt"


class TestMessagesToText:
    """Test cases for messages to text conversion."""

    @pytest.fixture
    def messages_data(self):
        return [{
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"}
            ]
        }]

    def test_messages_to_text_chatml(self, messages_data):
        """Test ChatML template."""
        dt = DataTransformer(messages_data)

        result = dt.to(messages_to_text(template="chatml"))

        assert "<|im_start|>system" in result[0]["text"]
        assert "<|im_start|>user" in result[0]["text"]
        assert "<|im_start|>assistant" in result[0]["text"]
        assert "<|im_end|>" in result[0]["text"]

    def test_messages_to_text_simple(self, messages_data):
        """Test simple template."""
        dt = DataTransformer(messages_data)

        result = dt.to(messages_to_text(template="simple"))

        assert "System:" in result[0]["text"]
        assert "User:" in result[0]["text"]
        assert "Assistant:" in result[0]["text"]

    def test_messages_to_text_custom_output_field(self, messages_data):
        """Test custom output field."""
        dt = DataTransformer(messages_data)

        result = dt.to(messages_to_text(output_field="formatted"))

        assert "formatted" in result[0]
        assert "text" not in result[0]

    def test_messages_to_text_invalid_template(self, messages_data):
        """Test error for invalid template."""
        dt = DataTransformer(messages_data)

        with pytest.raises(ValueError):
            dt.to(messages_to_text(template="invalid"))


class TestConvertersEdgeCases:
    """Edge case tests for converters module."""

    def test_to_openai_batch_auto_increment_id(self):
        """Test auto-increment custom_id for multiple items."""
        data = [
            {"messages": [{"role": "user", "content": "Q1"}]},
            {"messages": [{"role": "user", "content": "Q2"}]},
            {"messages": [{"role": "user", "content": "Q3"}]},
        ]
        dt = DataTransformer(data)

        result = dt.to(to_openai_batch())

        assert result[0]["custom_id"] == "request-0"
        assert result[1]["custom_id"] == "request-1"
        assert result[2]["custom_id"] == "request-2"

    def test_from_openai_batch_empty_input(self):
        """Test from_openai_batch with empty input."""
        results = from_openai_batch([])
        assert results == []

    def test_to_llama_factory_missing_fields(self):
        """Test LLaMA-Factory converter with missing fields."""
        data = [{"instruction": "问题"}]  # 缺少 input 和 output
        dt = DataTransformer(data)

        result = dt.to(to_llama_factory())

        assert result[0]["instruction"] == "问题"
        assert result[0]["input"] == ""
        assert result[0]["output"] == ""

    def test_to_llama_factory_with_history(self):
        """Test LLaMA-Factory converter with history field."""
        data = [{
            "instruction": "问题",
            "input": "",
            "output": "回答",
            "hist": [["之前的问题", "之前的回答"]]
        }]
        dt = DataTransformer(data)

        result = dt.to(to_llama_factory(history_field="hist"))

        assert result[0]["history"] == [["之前的问题", "之前的回答"]]

    def test_to_axolotl_empty_conversations(self):
        """Test Axolotl converter with empty conversations."""
        data = [{"conversations": []}]
        dt = DataTransformer(data)

        result = dt.to(to_axolotl())

        assert result[0]["conversations"] == []

    def test_to_axolotl_custom_keys(self):
        """Test Axolotl converter with custom keys."""
        data = [{
            "conversations": [
                {"speaker": "human", "text": "Hi"},
                {"speaker": "gpt", "text": "Hello!"}
            ]
        }]
        dt = DataTransformer(data)

        result = dt.to(to_axolotl(from_key="speaker", value_key="text"))

        assert result[0]["conversations"][0]["speaker"] == "human"
        assert result[0]["conversations"][0]["text"] == "Hi"

    def test_messages_to_text_empty_messages(self):
        """Test messages_to_text with empty messages."""
        data = [{"messages": []}]
        dt = DataTransformer(data)

        result = dt.to(messages_to_text())

        assert result[0]["text"] == ""

    def test_messages_to_text_preserves_original_fields(self):
        """Test that messages_to_text preserves original fields."""
        data = [{
            "id": "123",
            "messages": [{"role": "user", "content": "Hi"}],
            "metadata": {"source": "test"}
        }]
        dt = DataTransformer(data)

        result = dt.to(messages_to_text())

        assert result[0]["id"] == "123"
        assert result[0]["metadata"] == {"source": "test"}
        assert "text" in result[0]

    def test_messages_to_text_llama2_template(self):
        """Test llama2 template format."""
        data = [{
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"}
            ]
        }]
        dt = DataTransformer(data)

        result = dt.to(messages_to_text(template="llama2"))

        assert "[INST]" in result[0]["text"]
        assert "[/INST]" in result[0]["text"]

    def test_to_hf_chat_format_custom_field(self):
        """Test HF chat format with custom messages field."""
        data = [{"conv": [{"role": "user", "content": "Hi"}]}]
        dt = DataTransformer(data)

        result = dt.to(to_hf_chat_format(messages_field="conv"))

        assert result[0]["messages"] == data[0]["conv"]

    def test_to_openai_batch_custom_model(self):
        """Test OpenAI batch with custom model."""
        data = [{"messages": [{"role": "user", "content": "Hi"}]}]
        dt = DataTransformer(data)

        result = dt.to(to_openai_batch(model="gpt-4-turbo"))

        assert result[0]["body"]["model"] == "gpt-4-turbo"

    def test_from_openai_batch_with_usage(self):
        """Test from_openai_batch extracts usage info."""
        batch_output = [{
            "custom_id": "req-1",
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [{"message": {"content": "Response"}}],
                    "model": "gpt-4o",
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
                }
            }
        }]

        results = from_openai_batch(batch_output)

        assert results[0]["usage"]["prompt_tokens"] == 10
        assert results[0]["usage"]["completion_tokens"] == 20
        assert results[0]["usage"]["total_tokens"] == 30


class TestHuggingFaceDatasetDict:
    """Test cases for HuggingFace DatasetDict handling."""

    def test_from_hf_dataset_dict_with_split(self):
        """Test from_hf_dataset with DatasetDict and split."""
        datasets = pytest.importorskip("datasets")

        # 创建一个 DatasetDict
        ds_dict = datasets.DatasetDict({
            "train": datasets.Dataset.from_list([{"text": "train"}]),
            "test": datasets.Dataset.from_list([{"text": "test"}]),
        })

        data = from_hf_dataset(ds_dict, split="test")

        assert len(data) == 1
        assert data[0]["text"] == "test"

    def test_from_hf_dataset_dict_default_split(self):
        """Test from_hf_dataset with DatasetDict uses first split."""
        datasets = pytest.importorskip("datasets")

        ds_dict = datasets.DatasetDict({
            "train": datasets.Dataset.from_list([{"text": "first"}]),
            "test": datasets.Dataset.from_list([{"text": "second"}]),
        })

        data = from_hf_dataset(ds_dict)

        assert len(data) == 1
        # 应该取第一个 split（通常是 train）
        assert data[0]["text"] == "first"

    def test_to_hf_dataset_empty(self):
        """Test to_hf_dataset with empty data."""
        datasets = pytest.importorskip("datasets")

        ds = to_hf_dataset([])

        assert len(ds) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
