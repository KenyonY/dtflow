# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

DataTransformer 是一个专业的数据标注和转换平台,支持多种机器学习训练格式(SFT、RLHF、Pretrain),集成 FlaxKV2 高性能存储后端。

## 核心架构

### 1. 三层架构设计

**数据转换核心层** (`data_transformer/`)
- `core.py`: DataTransformer 核心类,提供链式 API 和格式转换
- `formats/`: 格式解析器(SFT、RLHF、Pretrain),继承自 `BaseFormatter`
- `storage/io.py`: 文件存储抽象(支持 JSONL、JSON、CSV、Parquet)
- `utils/`: 工具模块(相似度计算、数据展示)

**Web 标注平台** (`label-app/`)
- **Backend**: FastAPI 应用,使用 FlaxKV2 存储
  - `app/main.py`: FastAPI 主应用入口
  - `app/api/`: RESTful API 路由(datasets、annotations)
  - `app/core/storage_flaxkv.py`: FlaxKV2 存储管理器(替代 JSONL 文件)
  - `app/models.py`: Pydantic 数据模型
- **Frontend**: React + TypeScript + Vite + Ant Design
  - 使用 Zustand 进行状态管理
  - React Router 用于路由
  - Axios 用于 API 调用

**下一代数据处理框架** (`next-gen-designer/light_transformer/`)
- 基于契约式编程(Contract-based)的轻量级数据流水线框架
- `core/base.py`: BaseProcessor 抽象基类
- `core/pipeline.py`: 流水线组合器,支持类型验证
- `core/contract.py`: 数据契约,定义输入输出类型
- `processors/`: 内置处理器(MLLM、文本/图像相似度等)

### 2. 设计原则

项目严格遵循以下原则:
- **KISS 原则**: Keep it simple, stupid
- **组合大于继承**: 尽可能少地使用继承

### 3. 存储后端: FlaxKV2

使用 FlaxKV2 键值数据库替代传统 JSONL 文件存储:
- 读写性能提升 10-500倍
- 类字典接口,使用简单
- 线程安全,支持并发
- 自动序列化复杂对象

数据库结构:
- `metadata`: 存储所有数据集元信息
- `dataset_{id}`: 每个数据集独立的键值数据库
  - `item:{id}`: 数据项
  - `_metadata`: 数据集统计信息

## 常用命令

### 开发环境设置

```bash
# 安装核心库依赖
pip install -e .

# 安装完整依赖(包括存储、显示、相似度等)
pip install -e ".[full]"

# 安装开发依赖
pip install -e ".[dev]"
```

### 测试

```bash
# 运行所有测试
pytest

# 运行核心库测试
pytest tests/

# 运行后端测试
cd label-app/backend && pytest

# 运行带覆盖率的测试
pytest --cov=data_transformer --cov-report=html

# 使用 hatch 运行测试(推荐)
hatch test
hatch test-cov
```

### 代码质量检查

```bash
# 使用 hatch 进行代码格式化
hatch run lint:fmt

# 检查代码风格
hatch run lint:style

# 类型检查
hatch run lint:typing

# 运行所有检查
hatch run lint:all
```

### Web 应用开发

```bash
# 启动后端服务器(开发模式,自动重载)
cd label-app/backend
python run.py
# 或
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 启动前端开发服务器
cd label-app/frontend
npm install
npm run dev

# 构建前端
npm run build

# 前端代码检查
npm run lint
```

### 数据集上传

```bash
# 使用命令行工具上传 SFT 数据集
python scripts/upload_sft_dataset.py \
  --file data/sft_dataset_example.jsonl \
  --name "我的数据集"
```

## 关键约定

### 1. 格式转换器开发

所有格式转换器必须继承 `BaseFormatter` 并实现:
- `format(item: Dict) -> Dict`: 单个数据项转换
- `parse(item: Dict) -> Dict`: 反向解析

### 2. FlaxKV2 存储管理

使用 `FlaxKVStorageManager` 进行所有数据库操作,不直接操作 FlaxKV 实例:
- 数据集操作: `create_dataset()`, `list_datasets()`, `delete_dataset()`
- 数据项操作: `add_item()`, `get_items()`, `update_item()`, `delete_item()`
- 标注操作: `get_next_item()`, `annotate_item()`

### 3. API 路由结构

- `/datasets`: 数据集管理
  - GET: 列表, POST: 创建, DELETE: 删除
  - POST `/datasets/{id}/upload`: 批量上传数据
  - GET `/datasets/{id}/export`: 导出数据集
- `/annotations`: 标注管理
  - GET `/annotations/{dataset_id}/items`: 获取数据项列表
  - POST `/annotations/{dataset_id}/items/{item_id}`: 提交标注

### 4. 下一代框架(light_transformer)

创建处理器时:
- 继承 `BaseProcessor`
- 在 `process(data, context)` 方法中添加类型注解
- 可选: 定义 `CONFIG_SCHEMA` 用于配置参数验证
- 使用 `context` 字典在处理器之间传递元数据和状态

流水线组合:
```python
from light_transformer.core.pipeline import DataPipeline
from light_transformer.processors.text_similarity import TextSimilarityProcessor

pipeline = DataPipeline(strict=True)  # 启用类型检查
pipeline.add_processor(ProcessorA())
pipeline.add_processor(ProcessorB())
result = pipeline.process(data, context={"user_id": 123})
```

## 项目结构特点

- **不使用 Cursor/Copilot rules**: 项目中无 `.cursorrules` 或 `.github/copilot-instructions.md`
- **包管理**: 使用 `hatchling` 作为构建后端,支持现代 Python 打包
- **前端技术栈**: React 18 + TypeScript + Vite + Ant Design 5
- **后端技术栈**: FastAPI + Pydantic v2 + FlaxKV2
- **测试框架**: pytest,配置在 `pyproject.toml` 和 `label-app/backend/pytest.ini`

## 文档位置

项目文档存放在各模块对应目录:
- SFT 数据集上传: `SFT数据集上传指南.md`
- 工具脚本: `scripts/README.md`
- 示例代码: `examples/README.md`
- 前端应用: `label-app/frontend/*.md`
- 后端 API: `label-app/backend/README.md`

## Git 工作流

- 主分支: `main`
- 当前未跟踪文件:
  - `SFT数据集上传指南.md`
  - `examples/`
  - `scripts/`
