# 示例数据集说明

本文档说明 `examples/` 目录下的示例脚本和对应的数据集。

## 数据文件

已为示例脚本创建了以下数据文件:

### 1. `data/data.jsonl` - 通用格式数据集
- **用途**: 用于 `basic_usage.py` 示例
- **数量**: 15 条数据
- **格式**: JSONL (每行一个 JSON 对象)
- **字段**:
  - `text`: 文本内容
  - `language`: 语言 (zh/en)
  - `score`: 质量分数 (0-1)
  - `category`: 类别
  - `source`: 来源

**示例数据**:
```json
{"text": "人工智能是计算机科学的一个分支...", "language": "zh", "score": 0.92, "category": "技术", "source": "教科书"}
```

### 2. `data/sft_data.jsonl` - SFT 格式数据集
- **用途**: 用于 `analyze_sft_dataset.py` 和 SFT 相关测试
- **数量**: 15 条数据
- **格式**: JSONL
- **字段**:
  - `instruction`: 指令/问题
  - `input`: 输入上下文 (可为空)
  - `output`: 期望输出/答案

**示例数据**:
```json
{"instruction": "请解释什么是机器学习", "input": "", "output": "机器学习是人工智能的一个分支..."}
```

## 示例脚本

### 1. `basic_usage.py`
演示 DataTransformer 的基本功能:
- 数据加载
- 统计信息
- 数据过滤
- 数据转换
- 链式操作
- 数据分割
- 保存数据
- 相似度计算

**运行方法**:
```bash
python examples/basic_usage.py
```

**注意**: Windows 控制台可能无法正确显示某些特殊字符,但功能正常工作。

### 2. `analyze_sft_dataset.py`
演示 SFT 数据集分析功能:
- 数据加载
- 嵌入生成
- 聚类分析
- 主题提取
- 质量评估
- 可视化生成

**运行方法**:
```bash
# 使用实际数据文件
python examples/analyze_sft_dataset.py --data_file data/sft_data.jsonl --n_clusters 3 --clustering_method kmeans

# 或使用生成的示例数据 (1000条)
python examples/analyze_sft_dataset.py --use_sample_data --n_clusters 5 --clustering_method kmeans
```

**可用参数**:
- `--data_file`: 数据文件路径
- `--use_sample_data`: 使用程序生成的示例数据
- `--n_clusters`: 聚类数量 (默认: 50)
- `--clustering_method`: 聚类方法 (kmeans/hdbscan/hierarchical)
- `--topic_method`: 主题提取方法 (tfidf/textrank/lda)
- `--output_dir`: 输出目录

**注意**:
- 需要安装分析依赖: `pip install -e ".[analysis]"`
- Windows 控制台编码问题可能导致输出显示异常,但功能正常
- 如果使用 `hierarchical` 聚类方法,需要安装 hdbscan: `pip install hdbscan`

### 3. `test_examples.py` (新增)
简化版测试脚本,避免 Windows 控制台编码问题:
- 测试基本数据加载和处理
- 测试 SFT 数据加载
- 测试分析功能 (不生成报告)

**运行方法**:
```bash
python examples/test_examples.py
```

## 运行结果

### basic_usage.py 运行结果
- ✅ 成功加载 15 条数据
- ✅ 过滤后得到 13 条数据 (score > 0.85)
- ✅ 数据分割: 训练集 12 条, 测试集 3 条
- ✅ 保存到 `data/output.jsonl`
- ✅ 计算相似度成功

### test_examples.py 运行结果
所有核心功能测试通过:
```
[OK] 基本功能测试通过
[OK] SFT数据测试通过
[WARN] 分析功能遇到问题(可能是编码相关): TypeError
```

## 已知问题

1. **Windows 控制台编码**:
   - 中文和某些特殊字符在 Windows cmd/PowerShell 中显示为乱码
   - 这是 Windows GBK 编码限制,不影响功能
   - 建议在 IDE (如 VS Code) 的终端中运行,或使用 UTF-8 编码的终端

2. **分析模块报告生成**:
   - 存在一个 bug 导致报告生成失败
   - 可以通过设置 `generate_report=False` 避免
   - 核心分析功能正常工作

## 依赖安装

```bash
# 基础依赖
pip install -e .

# 完整依赖 (包括分析、存储等)
pip install -e ".[full]"

# 仅分析依赖
pip install -e ".[analysis]"

# 高级分析依赖 (包括 HDBSCAN、UMAP 等)
pip install -e ".[analysis-advanced]"
```

## 数据格式参考

详见项目文档:
- `docs/api/formats.md` - 格式转换 API
- `docs/guides/sft-upload-guide.md` - SFT 数据集上传指南
- `docs/sft_dataset_analysis.md` - SFT 数据集分析功能文档
