"""
DataTransformer: 简洁的数据格式转换工具

核心功能:
- DataTransformer: 数据加载、转换、保存
- presets: 预设转换模板 (openai_chat, alpaca, sharegpt, dpo_pair, simple_qa)
- schema: 数据结构验证 (Schema, Field)
- tokenizers: Token 统计和过滤
- converters: HuggingFace/OpenAI 等格式转换
"""

from .converters import (  # LLaMA-Factory 扩展; ms-swift
    from_hf_dataset,
    from_openai_batch,
    messages_to_text,
    to_axolotl,
    to_hf_chat_format,
    to_hf_dataset,
    to_llama_factory,
    to_llama_factory_sharegpt,
    to_llama_factory_vlm,
    to_llama_factory_vlm_sharegpt,
    to_openai_batch,
    to_swift_messages,
    to_swift_query_response,
    to_swift_vlm,
)
from .core import DataTransformer, DictWrapper, TransformError, TransformErrors
from .framework import (
    CompatibilityResult,
    check_compatibility,
    detect_format,
    export_for,
)
from .presets import get_preset, list_presets
from .schema import (
    Field,
    Schema,
    ValidationError,
    ValidationResult,
    alpaca_schema,
    dpo_schema,
    openai_chat_schema,
    sharegpt_schema,
    validate_data,
)
from .storage import load_data, sample_file, save_data
from .streaming import StreamingTransformer, load_sharded, load_stream, process_shards
from .tokenizers import (
    DEFAULT_MODEL,
    MODEL_ALIASES,
    OPENAI_MODELS,
    count_tokens,
    messages_token_counter,
    messages_token_filter,
    messages_token_stats,
    resolve_model,
    token_counter,
    token_filter,
    token_stats,
)

__version__ = "0.5.7"

__all__ = [
    # core
    "DataTransformer",
    "DictWrapper",
    "TransformError",
    "TransformErrors",
    # presets
    "get_preset",
    "list_presets",
    # schema
    "Schema",
    "Field",
    "ValidationResult",
    "ValidationError",
    "validate_data",
    "openai_chat_schema",
    "alpaca_schema",
    "dpo_schema",
    "sharegpt_schema",
    # framework
    "CompatibilityResult",
    "check_compatibility",
    "detect_format",
    "export_for",
    # storage
    "save_data",
    "load_data",
    "sample_file",
    # tokenizers
    "count_tokens",
    "token_counter",
    "token_filter",
    "token_stats",
    "messages_token_counter",
    "messages_token_filter",
    "messages_token_stats",
    "DEFAULT_MODEL",
    "MODEL_ALIASES",
    "OPENAI_MODELS",
    "resolve_model",
    # converters
    "to_hf_dataset",
    "from_hf_dataset",
    "to_hf_chat_format",
    "from_openai_batch",
    "to_openai_batch",
    "to_llama_factory",
    "to_axolotl",
    "messages_to_text",
    # LLaMA-Factory 扩展
    "to_llama_factory_sharegpt",
    "to_llama_factory_vlm",
    "to_llama_factory_vlm_sharegpt",
    # ms-swift
    "to_swift_messages",
    "to_swift_query_response",
    "to_swift_vlm",
    # streaming
    "StreamingTransformer",
    "load_stream",
    "load_sharded",
    "process_shards",
]
