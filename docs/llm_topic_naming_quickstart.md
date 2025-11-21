# LLM主题命名快速开始指南

## 功能说明

传统的主题建模只能提取词级别的关键词,LLM主题命名可以生成更高层次的语义描述:

```
传统: Python / 编程 / 函数 / 代码
↓
LLM: "Python编程基础" - Python语言的基本语法、函数定义和代码实践
```

## 5分钟快速开始

### 1. 安装Ollama服务

```bash
# macOS/Linux
curl -fsSL https://ollama.com/install.sh | sh

# 启动服务
ollama serve
```

### 2. 下载模型

```bash
# embedding模型(用于文本向量化)
ollama pull bge-m3:latest

# LLM模型(用于生成主题名称)
ollama pull gemma2:4b
```

### 3. 测试连接

```bash
cd /Users/kunyuan/github/DataTransformer
python scripts/test_llm_naming.py
```

如果看到"✓ 所有测试通过!"表示环境配置成功。

### 4. 运行分析

```bash
# 使用示例数据(如果有的话)
python scripts/analyze_with_llm.py \
    --input data/sample_10k.jsonl \
    --output analysis_results_llm \
    --use-ollama-embedding

# 或使用你自己的数据
python scripts/analyze_with_llm.py \
    --input /path/to/your/data.jsonl \
    --output ./my_analysis \
    --use-ollama-embedding
```

### 5. 查看结果

```bash
# 列出所有主题
python scripts/view_topic_samples.py \
    --list \
    --analysis-dir analysis_results_llm

# 查看特定主题的样本
python scripts/view_topic_samples.py \
    --topic 0 \
    --data data/sample_10k.jsonl \
    --analysis-dir analysis_results_llm
```

输出示例:
```
================================================================================
主题列表
================================================================================
ID     样本数      LLM主题名称                    关键词
--------------------------------------------------------------------------------
0      150        Python编程基础                Python, 编程, 函数, 代码
1      230        数学应用题求解                数学, 计算, 应用题, 解答
2      180        历史人物与事件                历史, 人物, 事件, 朝代
...
```

## 命令参数说明

### 常用参数

```bash
--input            # 输入数据文件(必需)
--output           # 输出目录
--use-ollama-embedding  # 使用Ollama embedding(推荐)
```

### 进阶参数

```bash
--ollama-embed-model   # embedding模型名称(默认: bge-m3:latest)
--ollama-llm-model     # LLM模型名称(默认: gemma2:4b)
--ollama-url           # Ollama服务地址(默认: http://localhost:11434)
--sample-size          # 采样大小(用于大数据集)
--n-clusters           # 聚类数量(默认: 100)
--no-llm-naming        # 禁用LLM主题命名
```

## 性能考虑

### 小数据集 (< 1万样本)
```bash
# 全量分析,使用Ollama embedding
python scripts/analyze_with_llm.py \
    --input data.jsonl \
    --use-ollama-embedding
```
预计时间: 5-15分钟

### 中等数据集 (1万-10万样本)
```bash
# 使用BM25向量化(更快),但启用LLM主题命名
python scripts/analyze_with_llm.py \
    --input data.jsonl \
    --output analysis_results
```
预计时间: 3-10分钟

### 大数据集 (> 10万样本)
```bash
# 采样分析
python scripts/analyze_with_llm.py \
    --input large_data.jsonl \
    --sample-size 20000 \
    --output analysis_results
```
预计时间: 5-15分钟

## 常见问题

### 1. 连接失败
```
错误: Ollama API调用失败
```

**解决方案:**
```bash
# 检查服务是否运行
curl http://localhost:11434/api/version

# 如果未运行,启动服务
ollama serve
```

### 2. 模型未找到
```
错误: model 'bge-m3:latest' not found
```

**解决方案:**
```bash
ollama pull bge-m3:latest
ollama pull gemma2:4b
```

### 3. 主题质量不佳

**解决方案:**
- 使用更大的模型: `--ollama-llm-model gemma2:9b`
- 增加聚类数量: `--n-clusters 150`
- 使用Ollama embedding: `--use-ollama-embedding`

### 4. 速度太慢

**解决方案:**
- 使用采样: `--sample-size 10000`
- 不使用Ollama embedding(去掉`--use-ollama-embedding`)
- 使用更小的模型: `--ollama-llm-model gemma2:2b`

## Python API使用

如果你想在代码中使用:

```python
from data_transformer.analysis import SFTDataAnalyzer

# 创建分析器
analyzer = SFTDataAnalyzer(
    output_dir="./results",
    use_ollama_embedding=True,
    ollama_embed_model="bge-m3:latest",
    ollama_llm_model="gemma2:4b"
)

# 执行分析
results = analyzer.analyze(
    data="data.jsonl",
    use_llm_topic_naming=True
)

# 访问结果
for topic_id, info in results['topics'].items():
    print(f"{info['llm_topic_name']}: {info['llm_topic_description']}")
```

## 下一步

- 查看完整文档: `docs/sft_dataset_analysis.md`
- 了解设计原理: `docs/architecture/`
- 贡献代码: 提交PR到GitHub仓库

## 支持

如果遇到问题:
1. 查看完整文档
2. 运行测试脚本: `python scripts/test_llm_naming.py`
3. 提交Issue到GitHub
