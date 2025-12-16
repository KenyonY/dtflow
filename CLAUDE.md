# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

dtflow 是一个简洁的机器学习训练数据格式转换工具，支持 SFT、RLHF、Pretrain 等格式。

## 核心设计理念

- **函数式优于类继承**: 直接用 lambda/函数做转换，不需要 BaseFormatter 等 OOP 抽象
- **KISS 原则**: 一个 `DataTransformer` 类搞定所有操作
- **链式 API**: `dt.filter(...).to(...).save(...)`

## 项目结构

```
dtflow/              # 核心库
├── core.py          # DataTransformer 核心类
├── presets.py       # 预设转换函数 (openai_chat, alpaca, sharegpt, dpo_pair, simple_qa)
├── storage/io.py    # 文件 I/O (JSONL, JSON, CSV, Parquet)
├── cli/commands.py  # CLI 命令实现
└── mcp/             # MCP 服务

label-app/           # Web 标注平台
├── backend/         # FastAPI + FlaxKV2
└── frontend/        # React + TypeScript + Vite + Ant Design

next-gen-designer/light_transformer/  # 下一代数据处理框架（实验性）
├── core/base.py     # BaseProcessor 抽象基类
├── core/pipeline.py # 线性流水线
├── core/dag_pipeline.py  # DAG 流水线
└── processors/      # 内置处理器
```

## 常用命令

### 开发环境

```bash
pip install -e .                  # 基础安装
pip install -e ".[full]"          # 完整依赖
pip install -e ".[dev]"           # 开发依赖
```

### 测试

```bash
pytest tests/                              # 运行测试
pytest tests/test_core.py::test_add_item   # 运行单个测试
hatch test                                 # 使用 hatch 运行
```

### 代码质量

```bash
hatch run lint:fmt     # 格式化代码
hatch run lint:style   # 检查代码风格
hatch run lint:all     # 运行所有检查
```

### CLI 命令 (dt)

```bash
# 数据采样
dt sample data.jsonl --num=10
dt head data.jsonl 20
dt tail data.jsonl 20

# 数据转换
dt transform data.jsonl --preset=openai_chat    # 使用预设
dt transform data.jsonl                          # 生成配置文件模式

# 数据去重
dt dedupe data.jsonl --key=text                  # 精确去重
dt dedupe data.jsonl --key=text --similar=0.8    # 相似度去重

# 数据拼接
dt concat a.jsonl b.jsonl -o merged.jsonl

# 数据统计
dt stats data.jsonl

# 数据清洗
dt clean data.jsonl --drop-empty --strip
dt clean data.jsonl --min-len=text:10 --max-len=text:1000
```

### Web 应用

```bash
# 后端
cd label-app/backend && python run.py

# 前端
cd label-app/frontend && npm run dev
```

## 关键约定

### 添加新预设
1. 在 `dtflow/presets.py` 添加函数
2. 在 `tests/` 添加测试
3. 更新 README.md 预设表格

### Web 后端 (FlaxKV2 存储)
- 使用 `FlaxKVStorageManager` (`label-app/backend/app/core/storage_flaxkv.py`) 进行数据库操作
- API 路由: `/datasets` (数据集管理), `/annotations` (标注管理)

### light_transformer 处理器
- 继承 `BaseProcessor`，实现 `process(data, context)` 方法
- 流水线类型: `DataPipeline` (线性), `DAGPipeline` (DAG), `AsyncDataPipeline` (异步)

## 技术栈

- **包管理**: hatchling
- **代码风格**: Black (行长度 100) + isort + flake8
- **测试**: pytest
- **Python**: >= 3.8

## Git 工作流

- 主分支: `main`
- 提交消息: 使用清晰的中文描述
- 提交前运行: `hatch run lint:fmt && hatch test`
