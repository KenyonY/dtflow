"""
DataTransformer: A flexible data transformation tool for ML training formats.
"""
from .core import DataTransformer
from .formats import SFTFormatter, RLHFFormatter, PretrainFormatter
from .utils import calculate_similarity, display_data, print_stats
from .storage import save_data, load_data

__version__ = '0.1.0'

__all__ = [
    'DataTransformer',
    'SFTFormatter',
    'RLHFFormatter',
    'PretrainFormatter',
    'calculate_similarity',
    'display_data',
    'print_stats',
    'save_data',
    'load_data',
]
