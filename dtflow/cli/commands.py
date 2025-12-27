"""
CLI 命令统一导出入口

各命令已按功能拆分到独立模块:
- sample.py    采样相关 (sample, head, tail)
- transform.py 转换相关 (transform)
- stats.py     统计相关 (stats, token_stats)
- clean.py     清洗相关 (clean, dedupe)
- io_ops.py    IO 操作 (concat, diff)
- pipeline.py  Pipeline (run)
- lineage.py   血缘追踪 (history)
- common.py    通用工具函数
"""

# 采样命令
from .sample import head, sample, tail

# 转换命令
from .transform import transform

# 统计命令
from .stats import stats, token_stats

# 清洗命令
from .clean import clean, dedupe

# IO 操作命令
from .io_ops import concat, diff

# Pipeline 命令
from .pipeline import run

# 血缘追踪命令
from .lineage import history

__all__ = [
    # 采样
    "sample",
    "head",
    "tail",
    # 转换
    "transform",
    # 统计
    "stats",
    "token_stats",
    # 清洗
    "clean",
    "dedupe",
    # IO 操作
    "concat",
    "diff",
    # Pipeline
    "run",
    # 血缘
    "history",
]
