# SFT数据集分析模块使用指南

## 概述

本模块为DataTransformer新增了强大的SFT数据集分析能力，可以对80-100万量级的训练样本进行深度分析，包括数据分布、聚类、主题提取、质量评估等功能。

## 安装

### 基础安装（支持基本分析功能）

```bash
pip install -e ".[analysis]"
```

### 高级安装（包含HDBSCAN、LSH、UMAP等高级算法）

```bash
pip install -e ".[analysis-advanced]"
```

## 核心功能

### 1. 文本向量化（BM25）

- 使用BM25算法进行轻量级文本向量化
- 支持中英文分词（jieba）
- 生成稀疏向量表示，适合大规模数据

### 2. 多层次聚类分析

- **K-Means聚类**：快速粗粒度聚类（100-200个主题簇）
- **HDBSCAN聚类**：密度聚类，自动发现子主题和异常点
- **LSH聚类**：局部敏感哈希，快速发现重复或相似样本
- **层次化聚类**：组合多种算法进行多层次分析

### 3. 主题建模

- 基于TF-IDF的关键词提取
- TextRank算法
- LDA主题模型
- 自动生成主题摘要和关键词

### 4. 质量评估

- **长度分布分析**：指令、输出、总长度统计
- **多样性评估**：词汇多样性、N-gram多样性、模板多样性
- **复杂度分析**：句子长度、词汇复杂度、代码内容检测
- **重复性检测**：完全重复、近似重复、唯一样本比例
- **格式质量检查**：完整性、缺失字段检测

### 5. 可视化

- 聚类分布图（UMAP/t-SNE/PCA降维）
- 主题分布条形图
- 质量指标仪表盘
- 关键词云图
- 综合HTML分析报告

## 快速开始

### 基本使用

```python
from data_transformer.analysis import SFTDataAnalyzer

# 创建分析器
analyzer = SFTDataAnalyzer(
    n_clusters=100,        # K-Means聚类数
    min_cluster_size=50,   # HDBSCAN最小簇大小
    use_jieba=True,        # 使用jieba中文分词
    output_dir="./output"  # 输出目录
)

# 执行分析
results = analyzer.analyze(
    data="path/to/your/data.jsonl",  # 或直接传入数据列表
    sample_size=10000,                # 采样大小（可选）
    clustering_method='hierarchical', # 聚类方法
    topic_method='tfidf',             # 主题提取方法
    generate_report=True              # 生成HTML报告
)
```

### 命令行使用

```bash
# 分析真实数据集
python examples/analyze_sft_dataset.py \
    --data_file your_dataset.jsonl \
    --n_clusters 100 \
    --clustering_method hierarchical \
    --topic_method tfidf \
    --output_dir ./analysis_output

# 使用示例数据测试
python examples/analyze_sft_dataset.py \
    --use_sample_data \
    --n_clusters 50 \
    --output_dir ./test_output
```

## 数据格式要求

输入数据应为JSON或JSONL格式，每个样本包含以下字段：

```json
{
    "instruction": "用户指令或问题",
    "input": "额外的输入信息（可选）",
    "output": "期望的输出或回答"
}
```

## 分析结果解读

### 1. 聚类结果

- **粗粒度聚类**：将数据分为100-200个主要话题
- **细粒度聚类**：在每个主要话题内进一步细分
- **噪声点**：不属于任何聚类的异常样本

### 2. 主题信息

每个主题包含：
- 关键词列表（按重要性排序）
- 样本数量
- 主题摘要
- 示例文档

### 3. 质量指标

- **总体质量分数**（0-100）：综合评估数据集质量
- **词汇多样性**：Type-Token Ratio，越高越好
- **重复率**：完全重复和近似重复的比例
- **长度分布**：是否有过短或过长的样本

### 4. 警告与建议

系统会自动生成：
- 质量警告（如重复率过高、多样性不足）
- 改进建议（如增加词汇多样性、去除重复）

## 性能优化

### 处理大规模数据

1. **采样分析**：先在10%样本上快速分析
```python
results = analyzer.analyze(data, sample_size=100000)
```

2. **批处理**：自动批量处理，避免内存溢出
```python
vectorizer = BM25Vectorizer()
embeddings = vectorizer.fit_transform(texts, batch_size=5000)
```

3. **缓存机制**：自动缓存向量化结果
```python
analyzer = SFTDataAnalyzer(cache_dir="./cache")
```

### 并行计算

- 多进程批量编码
- GPU加速（如果可用）
- 分布式聚类（MiniBatch K-Means）

## 高级用法

### 自定义聚类参数

```python
from data_transformer.analysis.clustering import KMeansClusterer

# 创建自定义聚类器
kmeans = KMeansClusterer(
    n_clusters=150,
    batch_size=10000,
    max_iter=100
)

# 使用自定义聚类器
analyzer = SFTDataAnalyzer()
analyzer.kmeans_clusterer = kmeans
```

### 自定义质量评估标准

```python
from data_transformer.analysis.quality import QualityEvaluator

# 创建自定义评估器
evaluator = QualityEvaluator(
    min_length=20,      # 最小长度要求
    max_length=5000,    # 最大长度要求
    target_diversity=0.9 # 目标多样性
)

analyzer.quality_evaluator = evaluator
```

### 导出分析结果

```python
# 导出为JSON
import json
with open('results.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# 导出聚类标签
import numpy as np
np.save('cluster_labels.npy', results['clustering']['labels'])

# 导出主题关键词
topics = results['topics']
with open('topics.txt', 'w') as f:
    for topic_id, info in topics.items():
        keywords = [kw[0] for kw in info['keywords'][:10]]
        f.write(f"Topic {topic_id}: {', '.join(keywords)}\n")
```

## 常见问题

### Q: 如何处理内存不足的问题？

A: 使用采样分析或增加batch_size：
```python
analyzer.analyze(data, sample_size=50000)
```

### Q: 如何加速分析过程？

A: 启用缓存并使用MiniBatch算法：
```python
analyzer = SFTDataAnalyzer(cache_dir="./cache")
```

### Q: 如何分析中文数据？

A: 确保安装了jieba并设置use_jieba=True：
```python
analyzer = SFTDataAnalyzer(use_jieba=True)
```

### Q: 如何自定义可视化？

A: 使用DataVisualizer类：
```python
from data_transformer.analysis.visualization import DataVisualizer

visualizer = DataVisualizer(interactive=True)
visualizer.visualize_clustering(embeddings, labels, save_path="plot.html")
```

## 最佳实践

1. **逐步分析**：先小样本快速分析，再全量深度分析
2. **合理设置聚类数**：根据数据规模，通常设置50-200个聚类
3. **关注质量警告**：及时处理数据质量问题
4. **定期分析**：随着数据增长，定期重新分析
5. **结果验证**：人工抽检聚类结果的合理性

## 示例输出

分析完成后，会在输出目录生成：

```
analysis_output/
├── analysis_report.html      # 综合分析报告
├── analysis_results.json     # 详细分析结果
├── clustering_plot.html      # 聚类分布图
├── topics_plot.html          # 主题分布图
├── quality_metrics.html      # 质量指标图
└── wordcloud.png            # 关键词云图
```

## 依赖说明

### 必需依赖
- numpy: 数值计算
- scipy: 科学计算
- scikit-learn: 机器学习算法
- jieba: 中文分词
- matplotlib: 静态可视化
- plotly: 交互式可视化

### 可选依赖
- hdbscan: HDBSCAN聚类算法
- datasketch: LSH算法实现
- umap-learn: UMAP降维算法
- wordcloud: 词云生成

## 更新日志

- v0.1.0: 初始版本，支持基本的聚类和主题分析
- 新增BM25向量化
- 支持K-Means、HDBSCAN、LSH三种聚类算法
- 完整的质量评估体系
- HTML报告生成

## 贡献指南

欢迎提交Issue和Pull Request来改进本模块。重点改进方向：

1. 添加更多向量化方法（如Sentence-BERT）
2. 支持流式处理超大规模数据集
3. 添加更多质量评估指标
4. 改进可视化效果
5. 优化性能和内存使用