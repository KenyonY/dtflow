"""
DataTransformer: 简洁的数据格式转换工具

核心功能:
- DataTransformer: 数据加载、转换、保存
- presets: 预设转换模板 (openai_chat, alpaca, sharegpt, dpo_pair, simple_qa)
- tokenizers: Token 统计和过滤
- converters: HuggingFace/OpenAI 等格式转换
"""
from .core import DataTransformer, DictWrapper, TransformError, TransformErrors
from .presets import get_preset, list_presets
from .storage import save_data, load_data, sample_file
from .tokenizers import (
    count_tokens, token_counter, token_filter, token_stats,
    messages_token_counter, messages_token_filter, messages_token_stats,
)
from .converters import (
    to_hf_dataset, from_hf_dataset, to_hf_chat_format,
    from_openai_batch, to_openai_batch,
    to_llama_factory, to_axolotl, messages_to_text,
    # LLaMA-Factory 扩展
    to_llama_factory_sharegpt, to_llama_factory_vlm, to_llama_factory_vlm_sharegpt,
    # ms-swift
    to_swift_messages, to_swift_query_response, to_swift_vlm,
)

__version__ = '0.3.0'

__all__ = [
    # core
    'DataTransformer',
    'DictWrapper',
    'TransformError',
    'TransformErrors',
    # presets
    'get_preset',
    'list_presets',
    # storage
    'save_data',
    'load_data',
    'sample_file',
    # tokenizers
    'count_tokens',
    'token_counter',
    'token_filter',
    'token_stats',
    'messages_token_counter',
    'messages_token_filter',
    'messages_token_stats',
    # converters
    'to_hf_dataset',
    'from_hf_dataset',
    'to_hf_chat_format',
    'from_openai_batch',
    'to_openai_batch',
    'to_llama_factory',
    'to_axolotl',
    'messages_to_text',
    # LLaMA-Factory 扩展
    'to_llama_factory_sharegpt',
    'to_llama_factory_vlm',
    'to_llama_factory_vlm_sharegpt',
    # ms-swift
    'to_swift_messages',
    'to_swift_query_response',
    'to_swift_vlm',
]
