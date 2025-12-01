# DataTransformer

一个专业的数据标注、分析和转换平台，支持 SFT（Supervised Fine-Tuning）和 DPO（Direct Preference Optimization）等多种格式，集成 FlaxKV2 存储后端。

## ✨ 主要功能

- 🎯 **数据标注平台** - Web 界面的交互式数据标注工具
- 📊 **智能数据分析** - 自动化的数据质量评估、聚类分析和主题建模
- 🔄 **格式转换** - 支持 CSV、Excel、JSON 等多种格式互转
- 💾 **高性能存储** - FlaxKV2 键值存储，读写性能提升 10-500 倍

## 🚀 5 分钟快速开始

### 数据分析（推荐新手使用）

不需要编程经验，三种方式任选其一：

**方式1: 交互式向导（最简单）**
```bash
python scripts/analyze_wizard.py
# 按提示操作即可，全程引导
```

**方式2: 一键分析**
```bash
# 分析任意 JSONL 格式数据集
python scripts/analyze your_dataset.jsonl

# 查看支持的数据格式
python scripts/analyze --formats
```

**方式3: 先转换再分析**
```bash
# CSV → JSONL
python scripts/convert_to_jsonl.py \
  -i data.csv -o data.jsonl \
  --question-col "问题" --answer-col "答案"

# 然后分析
python scripts/analyze data.jsonl
```

> 📖 详细教程请看：[5分钟快速开始](QUICKSTART.md) | [零门槛使用指南](docs/lowering_barrier_guide.md)

### 数据标注平台

启动 Web 标注平台：

```bash
# 启动后端
cd label-app/backend
python run.py

# 启动前端（新终端）
cd label-app/frontend
npm install && npm run dev

# 访问 http://localhost:5173
```

### SFT 数据集上传

```bash
# 使用命令行工具上传
python scripts/upload_sft_dataset.py \
  --file data/sft_dataset_example.jsonl \
  --name "我的数据集"

# 或使用 Web 界面
# http://localhost:5173/datasets
```

## 📚 完整文档

### 核心功能文档
- 📖 [5分钟快速开始](QUICKSTART.md) - 最快上手方式
- 🎓 [零门槛使用指南](docs/lowering_barrier_guide.md) - 面向非技术用户
- 📊 [性能测试报告](docs/performance_test_report.md) - 大规模数据集性能基准

### 数据格式与转换
- 📝 [SFT 数据集上传指南](docs/guides/sft-upload-guide.md) - 完整的格式说明
- 🔄 [格式转换工具](scripts/convert_to_jsonl.py) - CSV/Excel/JSON → JSONL
- 📁 [示例数据文件](data/examples/) - 各种格式的样例

### 工具与脚本
- 🛠️ [分析工具](scripts/analyze) - 一键数据分析
- 🧙 [交互式向导](scripts/analyze_wizard.py) - 零基础友好
- 🔧 [工具脚本说明](scripts/README.md) - 所有命令行工具

### 开发文档
- 💡 [示例代码](examples/README.md) - 各种集成示例
- 🏗️ [架构文档](docs/architecture/) - 系统设计
- 🔌 [API 文档](docs/api/) - RESTful API 接口

## 设计原则

1. 组合大于继承: 永远尽可能少的使用继承
2. KISS原则: Keep it simple, stupid

