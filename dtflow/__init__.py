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
from .tokenizers import count_tokens, token_counter, token_filter, token_stats
from .converters import (
    to_hf_dataset, from_hf_dataset, to_hf_chat_format,
    from_openai_batch, to_openai_batch,
    to_llama_factory, to_axolotl, messages_to_text,
)

__version__ = '0.2.0'

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
    # converters
    'to_hf_dataset',
    'from_hf_dataset',
    'to_hf_chat_format',
    'from_openai_batch',
    'to_openai_batch',
    'to_llama_factory',
    'to_axolotl',
    'messages_to_text',
]
