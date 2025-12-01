"""
数据分析模块 - 用于大规模SFT数据集的分布分析

主要功能：
1. 文本向量化（BM25）
2. 多层次聚类分析
3. 主题建模
4. 质量评估
5. 可视化
"""

from .analyzer import SFTDataAnalyzer
from .embedding import BM25Vectorizer
from .clustering import (
    KMeansClusterer,
    HDBSCANClusterer,
    LSHClusterer,
    HierarchicalClusterer
)
from .topic_modeling import TopicModeler
from .quality import QualityEvaluator
from .visualization import DataVisualizer

__all__ = [
    'SFTDataAnalyzer',
    'BM25Vectorizer',
    'KMeansClusterer',
    'HDBSCANClusterer',
    'LSHClusterer',
    'HierarchicalClusterer',
    'TopicModeler',
    'QualityEvaluator',
    'DataVisualizer'
]

__version__ = '0.1.0'