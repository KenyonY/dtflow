# 高级数据分析功能指南

本文档介绍 DataTransformer 的高级数据分析功能，包括多种主题建模方法、自动聚类优化等。

## 🎯 新增功能概览

### 1. 多种主题提取方法

#### **c-TF-IDF**（推荐，默认）
- **优势**: 在全局层面计算 IDF，避免普通 TF-IDF 的局部高频词问题
- **适用场景**: 中小型数据集（1K - 50K 样本）
- **特点**: 快速、准确、自动过滤停用词

```bash
python scripts/convert_and_analyze.py \
  --input data/data_11_14_sharegpt.jsonl \
  --sample-size 5000 \
  --topic-method ctfidf
```

#### **BERTopic**（高质量，需要GPU）
- **优势**: 基于预训练语言模型，语义理解能力强
- **适用场景**: 复杂主题、跨领域数据
- **要求**: 需要安装 `bertopic` 和 `sentence-transformers`

```bash
# 安装依赖
pip install -e ".[analysis-advanced]"

# 使用 BERTopic
python scripts/convert_and_analyze.py \
  --input data/data_11_14_sharegpt.jsonl \
  --sample-size 5000 \
  --topic-method bertopic
```

#### **增强 LDA**
- **优势**: 经典主题模型，支持自动确定最佳主题数
- **适用场景**: 大规模数据集、长文本
- **特点**: 概率主题分布、可解释性强

```bash
python scripts/convert_and_analyze.py \
  --input data/data_11_14_sharegpt.jsonl \
  --sample-size 5000 \
  --topic-method lda_enhanced  # 自动搜索最佳主题数
```

---

### 2. 自动聚类数优化

#### **Elbow Method**（肘部法则）
- 基于簇内平方和（Inertia）曲线的拐点
- 适合大多数场景

#### **Silhouette Method**（轮廓系数）
- 基于聚类质量评分
- 更精确但计算较慢

#### **Combined Method**（综合方法，默认）
- 结合 Elbow 和 Silhouette
- 更稳定的结果

```bash
# 启用自动聚类数（默认已启用）
python scripts/convert_and_analyze.py \
  --input data/data_11_14_sharegpt.jsonl \
  --sample-size 5000 \
  --auto-clusters

# 禁用自动聚类，使用固定数量
python scripts/convert_and_analyze.py \
  --input data/data_11_14_sharegpt.jsonl \
  --sample-size 5000 \
  --no-auto-clusters \
  --n-clusters 20
```

---

### 3. 中文字体自动配置

系统会自动检测并配置中文字体（SimHei/Microsoft YaHei），解决可视化中文显示问题。

---

## 📊 完整参数说明

```bash
python scripts/convert_and_analyze.py \
  --input <文件路径>              # 必需：输入文件
  --output-dir <目录>             # 可选：输出目录（默认：./analysis_output）
  --sample-size <数量>            # 可选：采样大小（默认：全部数据）
  --topic-method <方法>           # 可选：主题方法（默认：ctfidf）
  --auto-clusters                 # 可选：自动聚类数（默认：启用）
  --n-clusters <数量>             # 可选：固定聚类数（默认：30）
  --skip-convert                  # 可选：跳过格式转换
```

### 主题方法选项

| 方法 | 说明 | 速度 | 质量 | 依赖 |
|------|------|------|------|------|
| `tfidf` | 基础 TF-IDF | ⚡⚡⚡ | ⭐⭐ | 无 |
| `ctfidf` | c-TF-IDF（推荐） | ⚡⚡ | ⭐⭐⭐⭐ | 无 |
| `textrank` | TextRank 算法 | ⚡⚡ | ⭐⭐⭐ | 无 |
| `lda` | 标准 LDA | ⚡ | ⭐⭐⭐ | gensim |
| `lda_enhanced` | 自动优化 LDA | ⚡ | ⭐⭐⭐⭐ | gensim |
| `bertopic` | BERTopic | ⚡ | ⭐⭐⭐⭐⭐ | bertopic, transformers |

---

## 🚀 使用示例

### 示例 1: 快速分析（推荐新手）

```bash
python scripts/convert_and_analyze.py \
  --input data/data_11_14_sharegpt.jsonl \
  --sample-size 5000
```

**特点**:
- 使用 c-TF-IDF（默认）
- 自动确定聚类数
- 5000 样本采样
- 约 20-30 秒完成

---

### 示例 2: 高质量分析（BERTopic）

```bash
# 首次使用需安装高级依赖
pip install -e ".[analysis-advanced]"

python scripts/convert_and_analyze.py \
  --input data/data_11_14_sharegpt.jsonl \
  --sample-size 5000 \
  --topic-method bertopic
```

**特点**:
- 使用语义嵌入
- 主题质量最高
- 需要 2-5 分钟（首次下载模型）

---

### 示例 3: 自定义聚类数

```bash
python scripts/convert_and_analyze.py \
  --input data/data_11_14_sharegpt.jsonl \
  --sample-size 5000 \
  --no-auto-clusters \
  --n-clusters 20 \
  --topic-method ctfidf
```

**特点**:
- 固定 20 个聚类
- 适合已知数据特征的场景

---

## 🔧 解决问题

### 问题 1: 主题高度相似

**原因**: 数据集同质性高，包含大量重复的系统提示词

**解决方案**:
1. 使用 **c-TF-IDF** 或 **BERTopic** 替代 tfidf
2. 减少聚类数量（使用自动聚类）
3. 检查并更新停用词表 `data_transformer/analysis/stopwords_zh.txt`

---

### 问题 2: 中文显示为方框

**原因**: 系统缺少中文字体

**解决方案**:
1. Windows: 系统自带，应自动识别
2. Linux: 安装中文字体
   ```bash
   sudo apt-get install fonts-wqy-microhei
   ```
3. macOS: 系统自带，应自动识别

---

### 问题 3: UMAP 未安装

**原因**: 缺少降维可视化库

**解决方案**:
```bash
pip install -e ".[analysis-advanced]"
```

---

## 📈 性能优化建议

### 数据量建议

| 样本数 | 推荐方法 | 预期时间 | 内存需求 |
|--------|----------|----------|----------|
| < 1K | tfidf/ctfidf | < 10s | < 500MB |
| 1K - 10K | ctfidf/lda | 20-60s | 1-2GB |
| 10K - 50K | ctfidf/lda_enhanced | 2-5min | 2-4GB |
| 50K - 100K | ctfidf（采样） | 5-10min | 4-8GB |
| > 100K | 分批处理 | - | - |

### 加速技巧

1. **使用采样**: 对大数据集先采样分析
   ```bash
   --sample-size 10000
   ```

2. **启用缓存**: 重复分析时复用向量化结果（默认启用）

3. **减少聚类数**: 使用自动聚类或设置较小的 n_clusters

---

## 📦 依赖安装

### 基础功能
```bash
pip install -e .
```

### 完整分析功能
```bash
pip install -e ".[analysis-advanced]"
```

包含:
- umap-learn (降维可视化)
- hdbscan (密度聚类)
- bertopic (语义主题模型)
- sentence-transformers (预训练嵌入)
- gensim (LDA 主题模型)

---

## 💡 最佳实践

1. **首次使用**: 用小样本（1000-5000）快速测试
2. **探索阶段**: 使用 c-TF-IDF + 自动聚类
3. **生产环境**: 根据结果选择最佳方法和参数
4. **定期更新**: 根据数据特点调整停用词表

---

## 📚 相关文档

- [主题分析详细文档](./sft_dataset_analysis.md)
- [架构设计原则](./architecture/design-principles.md)
- [项目 README](../README.md)

---

**版本**: v0.2.0
**更新日期**: 2025-11-20
