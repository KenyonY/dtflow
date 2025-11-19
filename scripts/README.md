# DataTransformer 工具脚本

本目录包含用于数据分析、格式转换、数据集上传等实用脚本。

## 🎯 核心分析工具

### analyze（一键分析工具）⭐

零门槛的数据分析命令行工具，自动检测数据格式并生成完整分析报告。

**快速使用：**
```bash
# 直接分析 JSONL 文件
python scripts/analyze data.jsonl

# 查看支持的数据格式
python scripts/analyze --formats
```

**主要功能：**
- ✅ 自动检测 4 种 SFT 数据格式
- ✅ 生成质量评估报告（多样性、复杂度、重复度）
- ✅ 聚类分析和主题建模
- ✅ 可视化图表（聚类分布、词云等）
- ✅ 详细的 HTML 和 Markdown 报告

### analyze_wizard.py（交互式向导）🧙

面向完全不懂编程的用户，全程引导式操作。

**启动方式：**
```bash
python scripts/analyze_wizard.py
```

**特点：**
- 🎨 彩色终端界面，友好提示
- 📝 逐步引导，每步验证
- 🔍 显示数据样例供确认
- 🎯 智能参数推荐
- 📊 自动执行分析并显示结果

### convert_to_jsonl.py（格式转换器）🔄

将各种常见数据格式转换为 JSONL 格式。

**支持的格式：**
- CSV / TSV
- Excel (.xlsx, .xls)
- JSON 数组
- 纯文本对话

**使用示例：**

```bash
# CSV 转 JSONL
python scripts/convert_to_jsonl.py \
  -i data.csv -o data.jsonl \
  --question-col "问题" --answer-col "答案"

# Excel 转 JSONL
python scripts/convert_to_jsonl.py \
  -i data.xlsx -o data.jsonl \
  --question-col "Question" --answer-col "Answer"

# JSON 数组转 JSONL
python scripts/convert_to_jsonl.py \
  -i data.json -o data.jsonl \
  --question-key "prompt" --answer-key "completion"
```

## 🔬 性能测试与开发工具

### performance_test.py（性能测试）

大规模数据集性能基准测试工具，生成详细的性能报告。

**使用方式：**
```bash
python scripts/performance_test.py
```

**测试内容：**
- 100、500、1000 样本的处理速度
- 内存使用情况
- 吞吐量（items/sec）
- 算法线性度评估

### generate_large_test_dataset.py（测试数据生成器）

生成大规模的 SFT 格式测试数据集。

**使用方式：**
```bash
# 生成 1000 条测试数据
python scripts/generate_large_test_dataset.py \
  -o test_data.jsonl -n 1000
```

**数据特点：**
- 5 个主题领域（机器学习、深度学习、Python、数据科学、Web开发）
- 多样化的问答模板
- 随机化内容填充

## 📦 数据集管理工具

### upload_sft_dataset.py

用于验证和上传 SFT（Supervised Fine-Tuning）数据集的命令行工具。

#### 功能特性

- ✅ 完整的数据格式验证
- ✅ 支持多模态数据（文本 + 图片）
- ✅ 详细的错误报告
- ✅ 自动创建数据集并上传
- ✅ 显示上传统计信息

#### 使用方法

**1. 仅验证数据格式（不上传）**

```bash
python scripts/upload_sft_dataset.py \
  --file data/sft_dataset_example.jsonl \
  --validate-only
```

**2. 验证并上传数据**

```bash
python scripts/upload_sft_dataset.py \
  --file data/sft_dataset_example.jsonl \
  --name "医疗问答数据集 V1" \
  --description "包含100条医疗相关问答"
```

**3. 指定 API 服务器地址**

```bash
python scripts/upload_sft_dataset.py \
  --file data/sft_dataset_example.jsonl \
  --name "我的数据集" \
  --api http://192.168.1.100:8000
```

**4. 转换其他格式数据**

```bash
python scripts/upload_sft_dataset.py \
  --file data/other_format.jsonl \
  --name "转换数据集" \
  --source-format rlhf
```

#### 参数说明

| 参数 | 简写 | 必需 | 说明 |
|------|------|------|------|
| `--file` | `-f` | ✓ | 数据文件路径（JSONL 格式） |
| `--name` | `-n` | * | 数据集名称（上传时必需） |
| `--description` | `-d` | ✗ | 数据集描述 |
| `--api` | - | ✗ | API 服务器地址（默认: http://localhost:8000） |
| `--validate-only` | - | ✗ | 仅验证格式，不上传 |
| `--source-format` | - | ✗ | 源格式（sft/rlhf/pretrain），用于格式转换 |

#### 输出示例

```
📁 正在处理文件: data/sft_dataset_example.jsonl
============================================================
🔍 验证数据格式...
✅ 数据格式验证通过！共 6 条数据

📦 创建数据集: 医疗问答数据集 V1
✅ 数据集创建成功！ID: ds_abc123

⬆️  上传数据文件...
✅ Successfully uploaded 6 items

📊 获取数据集统计...
✅ 统计信息:
   • 总数: 6
   • 已标注: 0
   • 待标注: 6

============================================================
🎉 数据集上传完成！

访问 Web 界面开始标注:
  http://localhost:5173/datasets

或直接开始标注:
  http://localhost:5173/annotate/sft/ds_abc123
```

#### 错误处理

脚本会检测以下常见错误：

- JSON 格式错误
- 缺少必需字段（`messages`）
- 无效的角色类型（`role`）
- 空内容（`content`）
- 多模态内容格式错误
- 文件编码问题

示例错误输出：

```
❌ 发现 3 个错误:

  • 第 5 行: 缺少 'messages' 字段
  • 第 8 行，消息 1: 无效的 role 'bot'（必须是 'system', 'user', 或 'assistant'）
  • 第 12 行: JSON 格式错误 - Expecting ',' delimiter: line 1 column 45 (char 44)
```

## 依赖要求

```bash
pip install requests
```

## 快速开始

1. **准备数据文件**

   创建一个 JSONL 文件，每行一个 JSON 对象：

   ```json
   {"messages":[{"role":"user","content":"你好"},{"role":"assistant","content":"你好！有什么可以帮助你的吗？"}]}
   {"messages":[{"role":"user","content":"什么是AI？"},{"role":"assistant","content":"AI（人工智能）是..."}]}
   ```

2. **验证数据**

   ```bash
   python scripts/upload_sft_dataset.py -f my_data.jsonl --validate-only
   ```

3. **上传数据**

   ```bash
   python scripts/upload_sft_dataset.py -f my_data.jsonl -n "我的数据集"
   ```

4. **开始标注**

   在浏览器中访问提示的 URL 开始标注工作。

## 数据格式参考

详细的数据格式说明请参考：[SFT数据集上传指南.md](../SFT数据集上传指南.md)

示例数据文件：[data/sft_dataset_example.jsonl](../data/sft_dataset_example.jsonl)

## 故障排除

### 连接错误

如果遇到连接错误：

```
❌ 创建数据集失败: HTTPConnectionPool(host='localhost', port=8000)
```

请确认：
1. 后端服务是否正在运行
2. API 地址是否正确
3. 防火墙设置

启动后端服务：

```bash
cd label-app/backend
python run.py
```

### 编码错误

确保文件使用 UTF-8 编码：

```bash
# 检查文件编码
file -I my_data.jsonl

# 转换编码
iconv -f GBK -t UTF-8 my_data.jsonl > my_data_utf8.jsonl
```

### 超时错误

对于大文件，可能需要增加超时时间。可以修改脚本中的 `timeout` 参数。

## 🎯 工具选择指南

| 你的需求 | 推荐工具 | 原因 |
|---------|---------|------|
| 完全不懂编程，想分析数据 | `analyze_wizard.py` | 交互式引导，零门槛 |
| 会用命令行，想快速分析 | `analyze` | 一条命令搞定 |
| 数据不是 JSONL 格式 | `convert_to_jsonl.py` | 支持多种格式转换 |
| 想上传到标注平台 | `upload_sft_dataset.py` | 验证+上传一步到位 |
| 测试系统性能 | `performance_test.py` | 完整性能基准测试 |
| 需要大量测试数据 | `generate_large_test_dataset.py` | 快速生成测试集 |

## 📚 相关文档

- 📖 [5分钟快速开始](../QUICKSTART.md) - 最快上手方式
- 🎓 [零门槛使用指南](../docs/lowering_barrier_guide.md) - 完整教程
- 📊 [性能测试报告](../docs/performance_test_report.md) - 性能基准
- 📝 [SFT 数据格式指南](../docs/guides/sft-upload-guide.md) - 格式说明
- 📁 [示例数据文件](../data/examples/) - 各种格式样例

## 💡 使用流程建议

### 场景1: 分析现有数据集

```bash
# 1. 如果数据是 CSV/Excel，先转换
python scripts/convert_to_jsonl.py -i data.csv -o data.jsonl \
  --question-col "问题" --answer-col "答案"

# 2. 分析数据
python scripts/analyze data.jsonl

# 3. 查看报告
open analysis_results/report.html
```

### 场景2: 准备训练数据

```bash
# 1. 转换格式
python scripts/convert_to_jsonl.py -i raw_data.xlsx -o dataset.jsonl \
  --question-col "Q" --answer-col "A"

# 2. 分析质量
python scripts/analyze dataset.jsonl

# 3. 上传到平台
python scripts/upload_sft_dataset.py -f dataset.jsonl -n "训练数据集V1"
```

### 场景3: 性能基准测试

```bash
# 1. 生成测试数据
python scripts/generate_large_test_dataset.py -o test.jsonl -n 1000

# 2. 运行性能测试
python scripts/performance_test.py

# 3. 查看报告
cat docs/performance_test_report.md
```

## 🆘 常见问题

### Q: analyze 和 analyze_wizard.py 有什么区别？

**A:**
- `analyze`: 命令行工具，一条命令完成分析，适合熟悉终端的用户
- `analyze_wizard.py`: 交互式向导，逐步引导操作，适合完全不懂编程的用户

### Q: 支持哪些数据格式？

**A:**
- **直接分析**: JSONL（4种SFT格式：messages、instruction-output、prompt-completion、question-answer）
- **转换后分析**: CSV、TSV、Excel、JSON 数组、纯文本对话

### Q: 分析大数据集需要多久？

**A:** 根据性能测试：
- 100 样本: ~5 秒
- 500 样本: ~1.3 秒
- 1000 样本: ~2.3 秒
- 平均吞吐量: 275 items/sec

### Q: 生成的报告在哪里？

**A:** 默认在 `analysis_results/` 目录下：
- `report.html` - 交互式可视化报告
- `report.md` - Markdown 格式报告
- `*.png` - 各种可视化图表

## 贡献

欢迎提交问题和改进建议！
