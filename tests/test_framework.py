"""
训练框架集成测试
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from dtflow import DataTransformer
from dtflow.framework import (
    CompatibilityResult,
    check_compatibility,
    detect_format,
    export_for,
)


class TestDetectFormat:
    """格式检测测试"""

    def test_detect_openai_chat(self):
        data = [{"messages": [{"role": "user", "content": "hi"}]}]
        assert detect_format(data) == "openai_chat"

    def test_detect_sharegpt(self):
        data = [{"conversations": [{"from": "human", "value": "hi"}]}]
        assert detect_format(data) == "sharegpt"

    def test_detect_alpaca(self):
        data = [{"instruction": "Write", "output": "Done"}]
        assert detect_format(data) == "alpaca"

    def test_detect_dpo(self):
        data = [{"prompt": "Q", "chosen": "A1", "rejected": "A2"}]
        assert detect_format(data) == "dpo"

    def test_detect_simple_qa(self):
        data = [{"question": "Q", "answer": "A"}]
        assert detect_format(data) == "simple_qa"

    def test_detect_unknown(self):
        data = [{"foo": "bar"}]
        assert detect_format(data) == "unknown"

    def test_detect_empty(self):
        assert detect_format([]) == "unknown"


class TestCheckCompatibility:
    """兼容性检查测试"""

    def test_llama_factory_openai_chat(self):
        data = [{"messages": [{"role": "user", "content": "hi"}]}]
        result = check_compatibility(data, "llama-factory")
        assert result.valid
        assert result.format == "openai_chat"

    def test_llama_factory_alpaca(self):
        data = [{"instruction": "Write", "output": "Done"}]
        result = check_compatibility(data, "llama-factory")
        assert result.valid
        assert result.format == "alpaca"

    def test_llama_factory_unknown(self):
        data = [{"foo": "bar"}]
        result = check_compatibility(data, "llama-factory")
        assert not result.valid
        assert len(result.errors) > 0

    def test_swift_compatibility(self):
        data = [{"messages": [{"role": "user", "content": "hi"}]}]
        result = check_compatibility(data, "swift")
        assert result.valid

    def test_axolotl_compatibility(self):
        data = [{"messages": [{"role": "user", "content": "hi"}]}]
        result = check_compatibility(data, "axolotl")
        assert result.valid

    def test_unknown_framework(self):
        data = [{"messages": [{"role": "user", "content": "hi"}]}]
        result = check_compatibility(data, "unknown_framework")
        assert not result.valid
        assert "不支持的框架" in result.errors[0]

    def test_compatibility_result_bool(self):
        result = CompatibilityResult(valid=True, framework="test", format="test")
        assert bool(result) is True

        result = CompatibilityResult(valid=False, framework="test", format="test")
        assert bool(result) is False


class TestExportFor:
    """导出功能测试"""

    def test_export_llama_factory(self):
        data = [
            {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]}
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            files = export_for(data, "llama-factory", tmpdir, "test_data")

            # 检查文件是否生成
            assert "data" in files
            assert "dataset_info" in files
            assert "train_args" in files

            assert Path(files["data"]).exists()
            assert Path(files["dataset_info"]).exists()
            assert Path(files["train_args"]).exists()

            # 检查数据文件内容
            with open(files["data"]) as f:
                saved_data = json.load(f)
            assert len(saved_data) == 1

            # 检查配置文件内容
            with open(files["dataset_info"]) as f:
                config = json.load(f)
            assert "test_data" in config

    def test_export_swift(self):
        data = [{"messages": [{"role": "user", "content": "hi"}]}]

        with tempfile.TemporaryDirectory() as tmpdir:
            files = export_for(data, "swift", tmpdir, "test_data")

            assert "data" in files
            assert "train_script" in files
            assert Path(files["data"]).exists()

    def test_export_axolotl(self):
        data = [{"messages": [{"role": "user", "content": "hi"}]}]

        with tempfile.TemporaryDirectory() as tmpdir:
            files = export_for(data, "axolotl", tmpdir, "test_data")

            assert "data" in files
            assert "config" in files
            assert Path(files["config"]).exists()


class TestDataTransformerIntegration:
    """DataTransformer 集成测试"""

    def test_check_compatibility_method(self):
        dt = DataTransformer([{"messages": [{"role": "user", "content": "hi"}]}])
        result = dt.check_compatibility("llama-factory")
        assert result.valid

    def test_export_for_method(self):
        dt = DataTransformer([{"messages": [{"role": "user", "content": "hi"}]}])

        with tempfile.TemporaryDirectory() as tmpdir:
            files = dt.export_for("llama-factory", tmpdir)
            assert "data" in files
            assert Path(files["data"]).exists()

    def test_export_for_with_custom_name(self):
        dt = DataTransformer([{"instruction": "Write", "output": "Done"}])

        with tempfile.TemporaryDirectory() as tmpdir:
            files = dt.export_for("llama-factory", tmpdir, dataset_name="my_custom_data")

            # 检查文件名包含自定义名称
            assert "my_custom_data" in files["data"]


class TestAlpacaFormat:
    """Alpaca 格式测试"""

    def test_alpaca_with_input(self):
        data = [{"instruction": "Translate", "input": "Hello", "output": "你好"}]
        result = check_compatibility(data, "llama-factory")
        assert result.valid
        assert result.format == "alpaca"

    def test_alpaca_without_input(self):
        data = [{"instruction": "Write a poem", "output": "Roses are red..."}]
        result = check_compatibility(data, "llama-factory")
        assert result.valid
        # 应该有警告说缺少 input
        assert any("input" in w for w in result.warnings)


class TestDPOFormat:
    """DPO 格式测试"""

    def test_dpo_format(self):
        data = [{"prompt": "Q", "chosen": "Good answer", "rejected": "Bad answer"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            files = export_for(data, "llama-factory", tmpdir, "dpo_data")

            with open(files["dataset_info"]) as f:
                config = json.load(f)

            # DPO 格式应该有 ranking: true
            assert config["dpo_data"].get("ranking") is True
