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

### 1. 文本向量化

- **BM25算法**: 轻量级文本向量化，支持中英文分词（jieba），生成稀疏向量表示，适合大规模数据
- **Ollama Embedding** (新增): 使用Ollama的深度学习模型(如bge-m3)生成稠密向量，语义理解能力更强

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
- **新增**: 使用LLM生成高层次语义主题名称(支持Ollama)

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
# 基础分析(使用BM25向量化)
python examples/analyze_sft_dataset.py \
    --data_file your_dataset.jsonl \
    --n_clusters 100 \
    --clustering_method hierarchical \
    --topic_method tfidf \
    --output_dir ./analysis_output

# 使用LLM主题命名(需要Ollama服务)
python scripts/analyze_with_llm.py \
    --input data/sample_10k.jsonl \
    --output analysis_results_llm \
    --ollama-llm-model gemma2:4b

# 使用Ollama Embedding + LLM主题命名(最佳效果)
python scripts/analyze_with_llm.py \
    --input data/sample_10k.jsonl \
    --output analysis_results_llm \
    --use-ollama-embedding \
    --ollama-embed-model bge-m3:latest \
    --ollama-llm-model gemma2:4b

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
- 主题摘要（词级别）
- **LLM生成的主题名称**（高层次语义，如"Python编程问答"）(新增)
- **LLM生成的主题描述**（一句话总结主题核心内容）(新增)
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

## LLM主题命名功能 (新增)

### 功能介绍

传统的主题建模只能提取词级别的关键词(如"Python"、"编程"、"函数"),无法体现更高层次的语义。LLM主题命名功能使用大语言模型为每个主题生成人类可读的高层次语义描述。

**对比示例:**

| 传统方法 | LLM主题命名 |
|---------|------------|
| Python / 编程 / 函数 / 代码 | **Python编程基础** - Python语言的基本语法、函数定义和代码实践 |
| 数学 / 计算 / 应用题 / 解答 | **数学应用题求解** - 使用数学知识解决实际应用问题 |
| 历史 / 人物 / 事件 / 朝代 | **历史人物与事件** - 重要历史人物及其相关历史事件介绍 |

### 使用前准备

1. **安装Ollama**
```bash
# macOS/Linux
curl -fsSL https://ollama.com/install.sh | sh

# 启动服务
ollama serve
```

2. **下载模型**
```bash
# 下载embedding模型(用于向量化)
ollama pull bge-m3:latest

# 下载LLM模型(用于主题命名)
ollama pull gemma2:4b
```

3. **验证安装**
```bash
# 测试连接
python scripts/test_llm_naming.py
```

### 基本使用

#### 方式1: 使用命令行脚本

```bash
# 使用LLM主题命名(仅主题命名,向量化仍用BM25)
python scripts/analyze_with_llm.py \
    --input data/sample_10k.jsonl \
    --output analysis_results_llm

# 使用Ollama embedding + LLM主题命名(推荐)
python scripts/analyze_with_llm.py \
    --input data/sample_10k.jsonl \
    --output analysis_results_llm \
    --use-ollama-embedding

# 自定义模型
python scripts/analyze_with_llm.py \
    --input data/sample_10k.jsonl \
    --output analysis_results_llm \
    --use-ollama-embedding \
    --ollama-embed-model bge-m3:latest \
    --ollama-llm-model gemma2:4b \
    --ollama-url http://localhost:11434
```

#### 方式2: Python API

```python
from data_transformer.analysis import SFTDataAnalyzer

# 创建分析器(启用Ollama功能)
analyzer = SFTDataAnalyzer(
    output_dir="./analysis_results",
    use_ollama_embedding=True,           # 使用Ollama embedding
    ollama_embed_model="bge-m3:latest",  # embedding模型
    ollama_llm_model="gemma2:4b",        # LLM模型
    ollama_base_url="http://localhost:11434"
)

# 执行分析(启用LLM主题命名)
results = analyzer.analyze(
    data="data/sample_10k.jsonl",
    use_llm_topic_naming=True  # 启用LLM主题命名
)

# 查看主题
for topic_id, topic_info in results['topics'].items():
    print(f"主题 {topic_id}:")
    print(f"  LLM名称: {topic_info['llm_topic_name']}")
    print(f"  LLM描述: {topic_info['llm_topic_description']}")
    print(f"  关键词: {', '.join([kw[0] for kw in topic_info['keywords'][:5]])}")
```

### 查看分析结果

```bash
# 列出所有主题(包含LLM生成的名称)
python scripts/view_topic_samples.py \
    --list \
    --analysis-dir analysis_results_llm

# 查看特定主题的详细信息
python scripts/view_topic_samples.py \
    --topic 5 \
    --data data/sample_10k.jsonl \
    --analysis-dir analysis_results_llm

# 导出主题样本
python scripts/view_topic_samples.py \
    --topic 5 \
    --data data/sample_10k.jsonl \
    --analysis-dir analysis_results_llm \
    --export topic_5_samples.jsonl
```

### 性能说明

- **Embedding速度**: bge-m3处理速度约100-200样本/秒(取决于硬件)
- **LLM命名速度**: 每个主题约1-3秒
- **建议**: 对于大数据集,先采样分析,验证效果后再全量处理

### 常见问题

**Q: Ollama服务无法连接?**

A: 确保Ollama服务已启动:
```bash
ollama serve
# 或检查服务状态
curl http://localhost:11434/api/version
```

**Q: 模型下载失败?**

A: 检查网络连接,或使用代理:
```bash
export https_proxy=http://proxy:port
ollama pull bge-m3:latest
```

**Q: LLM生成的主题名称质量不好?**

A: 尝试:
1. 使用更大的模型(如gemma2:9b)
2. 增加每个主题的样本数量
3. 调整temperature参数

**Q: 可以使用其他LLM服务吗?**

A: 当前只支持Ollama。未来版本将支持OpenAI API、本地Transformers等。

### 技术细节

**主题命名流程:**

1. 从每个聚类中提取3-5个代表性样本
2. 提取该聚类的TF-IDF关键词
3. 将样本和关键词组合成提示词
4. 调用LLM生成主题名称和描述
5. 解析并保存结果

**Prompt模板示例:**

```
你是一个数据分析专家。请根据以下样本数据和关键词,为这个主题生成一个简洁的名称和描述。

关键词: Python, 编程, 函数, 代码, 调试

样本数据:
---
如何使用Python编写一个函数来计算斐波那契数列?
---
Python中如何进行异常处理和错误调试?
---
请解释Python装饰器的工作原理

请按以下格式输出(只输出两行,不要其他内容):
主题名称: [一个简短的主题名称,不超过10个字]
主题描述: [一句话描述这个主题的核心内容,不超过30个字]
```

## 更新日志

- v0.2.0 (最新):
  - ✨ 新增LLM主题命名功能(支持Ollama)
  - ✨ 新增Ollama Embedding向量化支持
  - 🔧 改进主题建模结果展示
  - 📝 更新文档和示例脚本

- v0.1.0: 初始版本
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