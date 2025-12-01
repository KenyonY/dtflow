# DataTransformer 快速开始指南 🚀

5分钟上手，分析你的数据集！

## 📋 目录

- [快速开始（3步搞定）](#快速开始3步搞定)
- [三种使用方式](#三种使用方式)
- [数据格式要求](#数据格式要求)
- [常见问题](#常见问题)
- [进阶使用](#进阶使用)

---

## 快速开始（3步搞定）

### 1️⃣ 安装

```bash
# 克隆项目
git clone https://github.com/your-repo/DataTransformer.git
cd DataTransformer

# 安装（包含所有分析功能）
pip install -e ".[analysis]"
```

### 2️⃣ 准备数据

确保你的数据是 **JSONL 格式**（每行一个JSON对象），支持以下任意格式：

```jsonl
{"messages": [{"role": "user", "content": "问题"}, {"role": "assistant", "content": "答案"}]}
```

或

```jsonl
{"instruction": "问题", "output": "答案"}
```

> 💡 不知道如何准备数据？跳到 [数据格式要求](#数据格式要求) 查看详细说明

### 3️⃣ 运行分析

**最简单的方式（一行命令）：**

```bash
python scripts/analyze your_data.jsonl
```

就这么简单！🎉

---

## 三种使用方式

根据你的需求和技术水平，选择最适合你的方式：

### 方式1: 一键分析（推荐新手）⭐⭐⭐⭐⭐

**适合人群**：完全不懂编程的用户

**特点**：一行命令，自动检测格式，自动生成报告

```bash
# 最简单
python scripts/analyze your_data.jsonl

# 自定义输出目录
python scripts/analyze your_data.jsonl --output results/

# 自定义聚类数
python scripts/analyze your_data.jsonl --clusters 20

# 查看支持的格式
python scripts/analyze --formats
```

**输出**：
- ✅ 完整的分析报告（HTML）
- ✅ 可视化图表（PNG）
- ✅ 详细数据（JSON）

---

### 方式2: 交互式向导（推荐初学者）⭐⭐⭐⭐⭐

**适合人群**：希望一步步配置的用户

**特点**：完全交互式，有问有答，不需要记命令

```bash
python scripts/analyze_wizard.py
```

**流程**：
1. 选择数据文件
2. 自动检测格式并显示示例
3. 配置输出目录
4. 设置分析参数
5. 确认并运行
6. 查看结果

**示例交互**：

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║          📊 DataTransformer 交互式分析向导 📊                ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝

准备好开始了吗？ (Y/n): y

📍 步骤 1/5: 选择数据文件
──────────────────────────────────────────────────────────────
请输入数据文件路径 [data/sft_dataset_example.jsonl]: my_data.jsonl

🔍 正在检测文件格式...
✓ 文件格式: SFT消息格式
✓ 数据量: 500 条

这个数据文件正确吗？ (Y/n): y
...
```

---

### 方式3: Python代码（推荐开发者）⭐⭐⭐⭐

**适合人群**：熟悉Python的开发者

**特点**：完全控制，灵活定制

```python
from data_transformer.analysis.analyzer import SFTDataAnalyzer
import json

# 1. 加载数据
data = []
with open('your_data.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        item = json.loads(line)
        # 转换为统一格式（根据你的数据调整）
        data.append({
            'instruction': item['instruction'],
            'output': item['output']
        })

# 2. 创建分析器
analyzer = SFTDataAnalyzer(
    n_clusters=10,          # 聚类数
    output_dir='results'    # 输出目录
)

# 3. 运行分析
results = analyzer.analyze(
    data,
    generate_report=True,   # 生成HTML报告
    cache_embeddings=False  # 不缓存嵌入向量
)

# 4. 查看结果
print(f"质量分数: {results['quality']['overall_score']:.1f}/100")
print(f"聚类数: {results['clustering']['n_clusters']}")
print(f"主题数: {len(results['topics'])}")
```

---

## 数据格式要求

### 支持的格式

DataTransformer 自动识别以下格式：

#### 格式1: SFT消息格式（OpenAI风格）✨ 推荐

```jsonl
{"messages": [{"role": "user", "content": "什么是机器学习？"}, {"role": "assistant", "content": "机器学习是..."}]}
{"messages": [{"role": "user", "content": "Python如何定义函数？"}, {"role": "assistant", "content": "使用def关键字..."}]}
```

#### 格式2: Instruction-Output格式

```jsonl
{"instruction": "什么是机器学习？", "output": "机器学习是..."}
{"instruction": "Python如何定义函数？", "output": "使用def关键字..."}
```

#### 格式3: Prompt-Completion格式

```jsonl
{"prompt": "什么是机器学习？", "completion": "机器学习是..."}
{"prompt": "Python如何定义函数？", "completion": "使用def关键字..."}
```

#### 格式4: Question-Answer格式

```jsonl
{"question": "什么是机器学习？", "answer": "机器学习是..."}
{"question": "Python如何定义函数？", "answer": "使用def关键字..."}
```

### 格式要求

✅ **必须**：
- JSONL格式（每行一个完整的JSON对象）
- UTF-8编码
- 包含问题和答案字段（字段名见上方支持的格式）

❌ **不支持**：
- CSV格式（需要先转换）
- 纯文本格式
- Excel文件
- JSON数组格式（`[{...}, {...}]`）

### 数据转换

如果你的数据不是上述格式，可以使用我们的转换工具：

```bash
# CSV转JSONL
python scripts/convert_to_jsonl.py --input data.csv --output data.jsonl

# 自定义格式转换（见下一节）
```

---

## 常见问题

### Q1: 我的数据是CSV格式，怎么办？

**A**: 使用转换工具或手动转换

**方法1: 使用我们的转换工具**

```bash
python scripts/convert_to_jsonl.py \
  --input your_data.csv \
  --output your_data.jsonl \
  --question-col "问题" \
  --answer-col "答案"
```

**方法2: 使用Python**

```python
import csv
import json

with open('input.csv', 'r', encoding='utf-8') as f_in:
    reader = csv.DictReader(f_in)
    with open('output.jsonl', 'w', encoding='utf-8') as f_out:
        for row in reader:
            item = {
                "instruction": row['问题列名'],
                "output": row['答案列名']
            }
            f_out.write(json.dumps(item, ensure_ascii=False) + '\n')
```

### Q2: 数据量很大（10万+），会很慢吗？

**A**: 不会太慢，但建议优化

**性能参考**（基于实测）：
- 100条: ~5秒
- 1,000条: ~2秒
- 10,000条: ~10秒（预估）
- 100,000条: ~1-2分钟（预估）

**优化建议**：
- 使用采样：`--sample 10000`（分析1万条样本）
- 增加batch_size
- 使用更少的聚类数

### Q3: 分析结果在哪里？

**A**: 在输出目录中

**默认输出目录**: `analysis_results/`

**包含文件**：
```
analysis_results/
├── analysis_report.html      # 📊 可视化报告（浏览器打开）
├── analysis_results.json     # 📄 完整数据（JSON格式）
├── clustering_pca.png         # 📈 聚类可视化
├── wordcloud.png              # ☁️  词云图
└── ...
```

### Q4: 质量分数低怎么办？

**A**: 根据警告和建议改进数据

**常见问题和解决方案**：

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 质量分数 < 60 | 重复率高、多样性低 | 去重、增加数据来源 |
| 词汇多样性低 | 模板化严重 | 改写、使用同义词 |
| 复杂度低 | 句子太短太简单 | 增加细节和解释 |
| 重复样本多 | 数据收集问题 | 使用去重工具 |

**自动去重**：

```bash
# 去除完全重复的样本
python scripts/deduplicate.py \
  --input your_data.jsonl \
  --output clean_data.jsonl
```

### Q5: 支持哪些语言？

**A**: 主要支持中文和英文

- ✅ **中文**：完整支持，使用jieba分词
- ✅ **英文**：完整支持
- ⚠️  **其他语言**：可以运行，但分词效果可能不理想

### Q6: 需要安装什么依赖？

**A**: 一条命令安装所有依赖

```bash
# 完整安装（推荐）
pip install -e ".[analysis]"

# 或者分步安装
pip install -e .                    # 核心功能
pip install jieba scikit-learn      # 分析必需
pip install matplotlib seaborn      # 可视化
pip install hdbscan umap-learn      # 可选（高级功能）
```

### Q7: 出错了怎么办？

**A**: 按以下步骤排查

1. **检查数据格式**
   ```bash
   python scripts/analyze --formats  # 查看支持的格式
   head -1 your_data.jsonl | python -m json.tool  # 验证JSON格式
   ```

2. **查看详细错误**
   ```bash
   python scripts/analyze your_data.jsonl 2>&1 | tee error.log
   ```

3. **寻求帮助**
   - 查看文档：`docs/`
   - 提交Issue：附上错误日志和数据示例

---

## 进阶使用

### 自定义分析参数

```bash
# 完整参数列表
python scripts/analyze \
  your_data.jsonl \
  --output custom_results/ \
  --clusters 20 \
  --no-report               # 不生成HTML报告（节省时间）
```

### 批量分析多个文件

```bash
# Bash脚本
for file in data/*.jsonl; do
  python scripts/analyze "$file" --output "results/$(basename $file .jsonl)/"
done
```

### 只分析部分数据（采样）

```python
from data_transformer.analysis.analyzer import SFTDataAnalyzer

analyzer = SFTDataAnalyzer(n_clusters=10, output_dir='results')

# 只分析1000条样本
results = analyzer.analyze(
    data,
    sample_size=1000,      # 随机采样1000条
    generate_report=True
)
```

### 自定义质量评估阈值

```python
from data_transformer.analysis.quality import QualityEvaluator

evaluator = QualityEvaluator(
    min_length=10,         # 最小长度
    max_length=1000,       # 最大长度
    min_diversity=0.5      # 最小多样性阈值
)

metrics = evaluator.evaluate(data)
```

### 导出分析结果

```python
import json

# 导出为JSON
with open('results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# 导出质量指标为CSV
import pandas as pd

df = pd.DataFrame([{
    'dataset': 'my_dataset',
    'quality_score': results['quality']['overall_score'],
    'n_samples': len(data),
    'n_clusters': results['clustering']['n_clusters'],
    'vocabulary_diversity': results['quality']['diversity_scores']['vocabulary_diversity']
}])

df.to_csv('metrics.csv', index=False)
```

---

## 下一步

🎯 **现在你已经掌握了基础知识！**

**推荐阅读**：
- [详细API文档](docs/api/analysis.md)
- [性能测试报告](docs/performance_test_report.md)
- [高级功能](docs/advanced_features.md)

**示例项目**：
- [examples/basic_usage.py](examples/basic_usage.py) - 基础用法
- [examples/analyze_sft_dataset.py](examples/analyze_sft_dataset.py) - SFT分析

**获取帮助**：
- 📚 查看完整文档
- 💬 提交Issue
- 🌟 Star项目支持我们

---

## 快速参考卡

### 一键命令速查

```bash
# 基础分析
python scripts/analyze data.jsonl

# 交互式向导
python scripts/analyze_wizard.py

# 查看格式
python scripts/analyze --formats

# 自定义参数
python scripts/analyze data.jsonl -o results/ -c 20 --no-report
```

### Python API速查

```python
# 导入
from data_transformer.analysis.analyzer import SFTDataAnalyzer

# 创建
analyzer = SFTDataAnalyzer(n_clusters=10, output_dir='results')

# 分析
results = analyzer.analyze(data, generate_report=True)

# 访问结果
quality_score = results['quality']['overall_score']
n_clusters = results['clustering']['n_clusters']
topics = results['topics']
```

---

**🎉 开始你的数据分析之旅吧！**

有问题？欢迎提Issue或查看文档！
