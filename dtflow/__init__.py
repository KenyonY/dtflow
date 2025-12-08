"""
DataTransformer: 简洁的数据格式转换工具

核心功能:
- DataTransformer: 数据加载、转换、保存
- presets: 预设转换模板 (openai_chat, alpaca, sharegpt, dpo_pair, simple_qa)
"""
from .core import DataTransformer, DictWrapper, TransformError, TransformErrors
from .presets import get_preset, list_presets
from .storage import save_data, load_data, sample_file

__version__ = '0.1.3'

__all__ = [
    'DataTransformer',
    'DictWrapper',
    'TransformError',
    'TransformErrors',
    'get_preset',
    'list_presets',
    'save_data',
    'load_data',
    'sample_file',
]
