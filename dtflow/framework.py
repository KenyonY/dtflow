"""
训练框架集成模块

支持一键导出数据和配置文件到主流训练框架：
- LLaMA-Factory
- ms-swift
- Axolotl

用法:
    from dtflow import DataTransformer

    # 检查兼容性
    result = dt.check_compatibility("llama-factory")

    # 一键导出
    dt.export_for("llama-factory", output_dir="./output")
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Union

# 支持的框架类型
FrameworkType = Literal["llama-factory", "swift", "axolotl"]


@dataclass
class CompatibilityResult:
    """兼容性检查结果"""

    valid: bool
    framework: str
    format: str  # 识别的格式类型
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.valid

    def __str__(self) -> str:
        status = "✅ 兼容" if self.valid else "❌ 不兼容"
        lines = [f"{status} - {self.framework} ({self.format})"]

        if self.errors:
            lines.append("\n错误:")
            for err in self.errors:
                lines.append(f"  - {err}")

        if self.warnings:
            lines.append("\n警告:")
            for warn in self.warnings:
                lines.append(f"  - {warn}")

        if self.suggestions:
            lines.append("\n建议:")
            for sug in self.suggestions:
                lines.append(f"  - {sug}")

        return "\n".join(lines)


# ============================================================================
# 格式检测
# ============================================================================


def detect_format(data: List[dict]) -> str:
    """
    自动检测数据格式

    Returns:
        格式名称: alpaca, sharegpt, openai_chat, dpo, unknown
    """
    if not data:
        return "unknown"

    sample = data[0]

    # OpenAI Chat 格式
    if "messages" in sample:
        messages = sample["messages"]
        if isinstance(messages, list) and len(messages) > 0:
            first_msg = messages[0]
            if isinstance(first_msg, dict) and "role" in first_msg and "content" in first_msg:
                return "openai_chat"

    # ShareGPT 格式
    if "conversations" in sample:
        convs = sample["conversations"]
        if isinstance(convs, list) and len(convs) > 0:
            first_conv = convs[0]
            if isinstance(first_conv, dict) and "from" in first_conv and "value" in first_conv:
                return "sharegpt"

    # Alpaca 格式
    if "instruction" in sample and "output" in sample:
        return "alpaca"

    # DPO 格式
    if "prompt" in sample and "chosen" in sample and "rejected" in sample:
        return "dpo"

    # 简单 QA 格式
    if ("question" in sample and "answer" in sample) or ("q" in sample and "a" in sample):
        return "simple_qa"

    return "unknown"


# ============================================================================
# 兼容性检查
# ============================================================================


def check_compatibility(
    data: List[dict],
    framework: FrameworkType,
) -> CompatibilityResult:
    """
    检查数据与目标框架的兼容性

    Args:
        data: 数据列表
        framework: 目标框架名称

    Returns:
        CompatibilityResult 对象
    """
    framework = framework.lower().replace("_", "-")

    if framework in ("llama-factory", "llamafactory", "lf"):
        return _check_llama_factory_compatibility(data)
    elif framework in ("swift", "ms-swift", "modelscope-swift"):
        return _check_swift_compatibility(data)
    elif framework == "axolotl":
        return _check_axolotl_compatibility(data)
    else:
        return CompatibilityResult(
            valid=False,
            framework=framework,
            format="unknown",
            errors=[f"不支持的框架: {framework}"],
            suggestions=["支持的框架: llama-factory, swift, axolotl"],
        )


def _check_llama_factory_compatibility(data: List[dict]) -> CompatibilityResult:
    """检查 LLaMA-Factory 兼容性"""
    format_type = detect_format(data)
    errors = []
    warnings = []
    suggestions = []

    # 检查格式兼容性
    if format_type == "unknown":
        errors.append("无法识别数据格式")
        suggestions.append("LLaMA-Factory 支持: alpaca, sharegpt, openai_chat")
        return CompatibilityResult(
            valid=False,
            framework="LLaMA-Factory",
            format=format_type,
            errors=errors,
            suggestions=suggestions,
        )

    # 格式特定检查
    sample = data[0] if data else {}

    if format_type == "openai_chat":
        # 需要转换为 sharegpt 格式
        suggestions.append("建议使用 to_llama_factory_sharegpt() 转换")

    elif format_type == "alpaca":
        # 直接兼容
        if "input" not in sample:
            warnings.append("缺少 'input' 字段，将使用空字符串")

    elif format_type == "sharegpt":
        # 检查角色名
        if data:
            roles = set()
            for item in data[:10]:  # 只检查前 10 条
                for conv in item.get("conversations", []):
                    roles.add(conv.get("from", ""))
            valid_roles = {"human", "gpt", "user", "assistant", "system"}
            invalid_roles = roles - valid_roles
            if invalid_roles:
                warnings.append(f"非标准角色名: {invalid_roles}")
                suggestions.append("标准角色: human/gpt 或 user/assistant")

    elif format_type == "dpo":
        # LLaMA-Factory 支持 DPO
        pass

    elif format_type == "simple_qa":
        suggestions.append("建议使用 to_llama_factory() 转换为 alpaca 格式")

    return CompatibilityResult(
        valid=len(errors) == 0,
        framework="LLaMA-Factory",
        format=format_type,
        errors=errors,
        warnings=warnings,
        suggestions=suggestions,
    )


def _check_swift_compatibility(data: List[dict]) -> CompatibilityResult:
    """检查 ms-swift 兼容性"""
    format_type = detect_format(data)
    errors = []
    warnings = []
    suggestions = []

    if format_type == "unknown":
        errors.append("无法识别数据格式")
        suggestions.append("ms-swift 支持: messages, query-response, sharegpt")
        return CompatibilityResult(
            valid=False,
            framework="ms-swift",
            format=format_type,
            errors=errors,
            suggestions=suggestions,
        )

    # ms-swift 支持多种格式
    if format_type == "openai_chat":
        # messages 格式直接支持
        pass
    elif format_type == "alpaca":
        suggestions.append("建议使用 to_swift_query_response() 转换")
    elif format_type == "sharegpt":
        # 需要转换角色
        pass

    return CompatibilityResult(
        valid=len(errors) == 0,
        framework="ms-swift",
        format=format_type,
        errors=errors,
        warnings=warnings,
        suggestions=suggestions,
    )


def _check_axolotl_compatibility(data: List[dict]) -> CompatibilityResult:
    """检查 Axolotl 兼容性"""
    format_type = detect_format(data)
    errors = []
    warnings = []
    suggestions = []

    if format_type == "unknown":
        errors.append("无法识别数据格式")
        suggestions.append("Axolotl 支持: alpaca, sharegpt, openai_chat")
        return CompatibilityResult(
            valid=False,
            framework="Axolotl",
            format=format_type,
            errors=errors,
            suggestions=suggestions,
        )

    if format_type == "openai_chat":
        # Axolotl 直接支持 messages 格式
        pass
    elif format_type == "alpaca":
        pass
    elif format_type == "sharegpt":
        pass

    return CompatibilityResult(
        valid=len(errors) == 0,
        framework="Axolotl",
        format=format_type,
        errors=errors,
        warnings=warnings,
        suggestions=suggestions,
    )


# ============================================================================
# 导出功能
# ============================================================================


def export_for(
    data: List[dict],
    framework: FrameworkType,
    output_dir: str,
    dataset_name: str = "custom_dataset",
    format_type: Optional[str] = None,
    **kwargs,
) -> Dict[str, str]:
    """
    一键导出数据和配置文件到目标框架

    Args:
        data: 数据列表
        framework: 目标框架
        output_dir: 输出目录
        dataset_name: 数据集名称
        format_type: 强制指定格式类型（默认自动检测）
        **kwargs: 框架特定参数

    Returns:
        生成的文件路径字典 {"data": "...", "config": "...", ...}
    """
    framework = framework.lower().replace("_", "-")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 自动检测格式
    if format_type is None:
        format_type = detect_format(data)

    if framework in ("llama-factory", "llamafactory", "lf"):
        return _export_llama_factory(data, output_path, dataset_name, format_type, **kwargs)
    elif framework in ("swift", "ms-swift", "modelscope-swift"):
        return _export_swift(data, output_path, dataset_name, format_type, **kwargs)
    elif framework == "axolotl":
        return _export_axolotl(data, output_path, dataset_name, format_type, **kwargs)
    else:
        raise ValueError(f"不支持的框架: {framework}")


def _export_llama_factory(
    data: List[dict],
    output_path: Path,
    dataset_name: str,
    format_type: str,
    **kwargs,
) -> Dict[str, str]:
    """导出为 LLaMA-Factory 格式"""
    files = {}

    # 1. 保存数据文件
    data_file = output_path / f"{dataset_name}.json"
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    files["data"] = str(data_file)

    # 2. 生成 dataset_info.json
    dataset_info = _generate_llama_factory_dataset_info(dataset_name, format_type)
    info_file = output_path / "dataset_info.json"
    with open(info_file, "w", encoding="utf-8") as f:
        json.dump(dataset_info, f, ensure_ascii=False, indent=2)
    files["dataset_info"] = str(info_file)

    # 3. 生成训练参数模板
    train_args = _generate_llama_factory_train_args(dataset_name, **kwargs)
    args_file = output_path / "train_args.yaml"
    with open(args_file, "w", encoding="utf-8") as f:
        f.write(train_args)
    files["train_args"] = str(args_file)

    print(f"✅ LLaMA-Factory 导出完成:")
    print(f"   数据文件: {data_file}")
    print(f"   配置文件: {info_file}")
    print(f"   训练参数: {args_file}")

    return files


def _generate_llama_factory_dataset_info(dataset_name: str, format_type: str) -> dict:
    """生成 LLaMA-Factory dataset_info.json"""
    if format_type in ("openai_chat", "sharegpt"):
        # ShareGPT/对话格式
        return {
            dataset_name: {
                "file_name": f"{dataset_name}.json",
                "formatting": "sharegpt",
                "columns": {
                    "messages": "conversations",
                },
                "tags": {
                    "role_tag": "from",
                    "content_tag": "value",
                    "user_tag": "human",
                    "assistant_tag": "gpt",
                },
            }
        }
    elif format_type == "alpaca":
        return {
            dataset_name: {
                "file_name": f"{dataset_name}.json",
                "columns": {
                    "prompt": "instruction",
                    "query": "input",
                    "response": "output",
                },
            }
        }
    elif format_type == "dpo":
        return {
            dataset_name: {
                "file_name": f"{dataset_name}.json",
                "ranking": True,
                "columns": {
                    "prompt": "prompt",
                    "chosen": "chosen",
                    "rejected": "rejected",
                },
            }
        }
    else:
        # 默认 alpaca 格式
        return {
            dataset_name: {
                "file_name": f"{dataset_name}.json",
            }
        }


def _generate_llama_factory_train_args(
    dataset_name: str,
    model_name: str = "Qwen/Qwen2.5-7B-Instruct",
    **kwargs,
) -> str:
    """生成 LLaMA-Factory 训练参数模板"""
    return f"""### LLaMA-Factory 训练参数模板
### 使用: llamafactory-cli train train_args.yaml

### 模型
model_name_or_path: {model_name}

### 方法
stage: sft
do_train: true
finetuning_type: lora

### 数据集
dataset: {dataset_name}
dataset_dir: .
template: qwen
cutoff_len: 2048

### 输出
output_dir: ./output
logging_steps: 10
save_steps: 500
plot_loss: true

### 训练参数
per_device_train_batch_size: 2
gradient_accumulation_steps: 4
learning_rate: 1.0e-4
num_train_epochs: 3.0
lr_scheduler_type: cosine

### LoRA 参数
lora_rank: 8
lora_alpha: 16
lora_dropout: 0.1
lora_target: all
"""


def _export_swift(
    data: List[dict],
    output_path: Path,
    dataset_name: str,
    format_type: str,
    **kwargs,
) -> Dict[str, str]:
    """导出为 ms-swift 格式"""
    files = {}

    # 1. 保存数据文件 (JSONL 格式)
    data_file = output_path / f"{dataset_name}.jsonl"
    with open(data_file, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    files["data"] = str(data_file)

    # 2. 生成训练脚本
    train_script = _generate_swift_train_script(dataset_name, format_type, **kwargs)
    script_file = output_path / "train.sh"
    with open(script_file, "w", encoding="utf-8") as f:
        f.write(train_script)
    files["train_script"] = str(script_file)

    print(f"✅ ms-swift 导出完成:")
    print(f"   数据文件: {data_file}")
    print(f"   训练脚本: {script_file}")

    return files


def _generate_swift_train_script(
    dataset_name: str,
    format_type: str,
    model_name: str = "qwen2_5-7b-instruct",
    **kwargs,
) -> str:
    """生成 ms-swift 训练脚本"""
    # 确定数据集格式
    if format_type in ("openai_chat", "sharegpt"):
        dataset_format = "messages"
    else:
        dataset_format = "query-response"

    return f"""#!/bin/bash
# ms-swift 训练脚本
# 使用: bash train.sh

swift sft \\
    --model_type {model_name} \\
    --dataset {dataset_name}.jsonl \\
    --output_dir ./output \\
    --max_length 2048 \\
    --learning_rate 1e-4 \\
    --num_train_epochs 3 \\
    --per_device_train_batch_size 2 \\
    --gradient_accumulation_steps 4 \\
    --save_steps 500 \\
    --logging_steps 10 \\
    --lora_rank 8 \\
    --lora_alpha 32
"""


def _export_axolotl(
    data: List[dict],
    output_path: Path,
    dataset_name: str,
    format_type: str,
    **kwargs,
) -> Dict[str, str]:
    """导出为 Axolotl 格式"""
    files = {}

    # 1. 保存数据文件
    data_file = output_path / f"{dataset_name}.jsonl"
    with open(data_file, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    files["data"] = str(data_file)

    # 2. 生成配置文件
    config = _generate_axolotl_config(dataset_name, format_type, **kwargs)
    config_file = output_path / "config.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        f.write(config)
    files["config"] = str(config_file)

    print(f"✅ Axolotl 导出完成:")
    print(f"   数据文件: {data_file}")
    print(f"   配置文件: {config_file}")

    return files


def _generate_axolotl_config(
    dataset_name: str,
    format_type: str,
    model_name: str = "Qwen/Qwen2.5-7B-Instruct",
    **kwargs,
) -> str:
    """生成 Axolotl 配置文件"""
    # 确定数据集格式类型
    if format_type in ("openai_chat",):
        ds_type = "chat_template"
    elif format_type == "sharegpt":
        ds_type = "sharegpt"
    elif format_type == "alpaca":
        ds_type = "alpaca"
    else:
        ds_type = "completion"

    return f"""# Axolotl 配置文件
# 使用: accelerate launch -m axolotl.cli.train config.yaml

base_model: {model_name}
model_type: AutoModelForCausalLM

datasets:
  - path: {dataset_name}.jsonl
    type: {ds_type}

sequence_len: 2048
sample_packing: true
pad_to_sequence_len: true

adapter: lora
lora_r: 8
lora_alpha: 16
lora_dropout: 0.05
lora_target_linear: true

learning_rate: 1e-4
num_epochs: 3
micro_batch_size: 2
gradient_accumulation_steps: 4

output_dir: ./output
logging_steps: 10
save_steps: 500

bf16: auto
tf32: true
gradient_checkpointing: true

warmup_ratio: 0.1
lr_scheduler: cosine
"""
