# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

DataTransformer 是一个专业的数据标注和转换平台,支持多种机器学习训练格式(SFT、RLHF、Pretrain),集成 FlaxKV2 高性能存储后端。

## 核心架构

### 1. 三层架构设计

**数据转换核心层** (`data_transformer/`)
- `core.py`: DataTransformer 核心类,提供链式 API 和格式转换
- `formats/`: 格式解析器(SFT、RLHF、Pretrain),继承自 `BaseFormatter`
  - `base.py`: BaseFormatter 抽象基类,定义 `format()` 和 `parse()` 方法
  - `sft.py`, `rlhf.py`, `pretrain.py`: 具体格式实现
- `storage/io.py`: 文件存储抽象(支持 JSONL、JSON、CSV、Parquet)
- `utils/`: 工具模块(相似度计算、数据展示)
- `analysis/`: SFT数据集分析模块(嵌入、聚类、主题建模、质量评估、可视化)
- `presets.py`: 预设转换模板(openai_chat、alpaca、sharegpt、dpo_pair、simple_qa)
- `cli/`: 命令行工具(sample、transform 命令)
- `mcp/`: MCP 服务，提供 AI 工具集成支持

**Web 标注平台** (`label-app/`)
- **Backend** (`label-app/backend/`): FastAPI 应用,使用 FlaxKV2 存储
  - `app/main.py`: FastAPI 主应用入口,包含 CORS 配置
  - `app/api/`: RESTful API 路由
    - `datasets.py`: 数据集管理 API
    - `annotations.py`: 标注功能 API
  - `app/core/storage_flaxkv.py`: FlaxKV2 存储管理器(替代 JSONL 文件)
  - `app/models.py`: Pydantic 数据模型(v2 API)
  - `app/config.py`: 应用配置(存储路径等)
  - `app/exceptions.py`: 自定义异常类
  - `run.py`: 开发服务器启动脚本
- **Frontend** (`label-app/frontend/`): React + TypeScript + Vite + Ant Design
  - 使用 Zustand 进行状态管理
  - React Router 用于路由
  - Axios 用于 API 调用
  - 构建工具: Vite

**下一代数据处理框架** (`next-gen-designer/light_transformer/`)
- 基于契约式编程(Contract-based)的轻量级数据流水线框架
- `core/base.py`: BaseProcessor 抽象基类,定义 `process(data, context)` 方法
- `core/pipeline.py`: 线性流水线组合器,支持类型验证
- `core/dag_pipeline.py`: DAG (有向无环图) 流水线,支持复杂的数据流
- `core/async_pipeline.py`: 异步流水线支持
- `core/contract.py`: 数据契约,定义输入输出类型
- `core/registry.py`: 处理器注册表,支持配置文件加载
- `processors/`: 内置处理器(MLLM、文本/图像相似度等)
- `config/loader.py`: 从 YAML 配置文件加载流水线

### 2. 设计原则

项目严格遵循以下原则(详见 `docs/architecture/design-principles.md`):
- **KISS 原则**: Keep it simple, stupid - 优先选择简单直接的解决方案
- **组合大于继承**: 尽可能少地使用继承,优先使用组合和委托
- **单一职责原则**: 每个类或模块应该只有一个变化的理由
- **契约式编程**: 使用类型注解定义输入输出契约(在 light_transformer 中)
- **链式 API 设计**: DataTransformer 支持流畅的链式调用
- **显式优于隐式**: 明确的参数传递,清晰的错误消息

### 3. 存储后端: FlaxKV2

使用 FlaxKV2 键值数据库替代传统 JSONL 文件存储:
- 读写性能提升 10-500倍
- 类字典接口,使用简单
- 线程安全,支持并发
- 自动序列化复杂对象

数据库结构(在 `app/core/storage_flaxkv.py` 中实现):
- `metadata`: 存储所有数据集元信息
- `dataset_{id}`: 每个数据集独立的键值数据库
  - `item:{id}`: 数据项
  - `_metadata`: 数据集统计信息

存储位置: `label-app/backend/data/flaxkv/`

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

# 运行特定测试文件
pytest tests/test_core.py

# 运行特定测试函数
pytest tests/test_core.py::test_add_item

# 运行后端测试
cd label-app/backend && pytest

# 运行 light_transformer 测试
cd next-gen-designer && pytest

# 运行带覆盖率的测试
pytest --cov=data_transformer --cov-report=html

# 使用 hatch 运行测试(推荐,无需手动切换目录)
hatch test                    # 运行所有测试
hatch test-cov                # 带覆盖率
hatch run cov-report          # 生成 HTML 报告并在浏览器打开
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
# 后端开发
cd label-app/backend

# 首次安装(推荐使用安装脚本)
./install.sh              # 自动安装核心库和后端依赖

# 或手动安装
cd ../.. && pip install -e .           # 先安装核心库
cd label-app/backend && pip install -r requirements.txt

# 启动后端服务器(开发模式,自动重载)
python run.py                          # 推荐方式
# 或
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 访问 API 文档
# Swagger UI: http://localhost:8000/docs
# ReDoc: http://localhost:8000/redoc

# 前端开发
cd label-app/frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev               # 默认在 http://localhost:5173

# 构建生产版本
npm run build

# 预览构建结果
npm run preview

# 代码检查
npm run lint
```

### CLI 命令（dt）

```bash
# 数据采样
dt sample data.jsonl --num=10                    # 随机采样 10 条
dt sample data.csv --num=100 --sample_type=head  # 取前 100 条
dt sample data.xlsx --output=sampled.jsonl       # 采样并保存

# 数据转换 - 预设模式（推荐）
dt transform data.jsonl --preset=openai_chat     # 转换为 OpenAI Chat 格式
dt transform data.jsonl --preset=alpaca          # 转换为 Alpaca 格式
dt transform data.jsonl --preset=sharegpt        # 转换为 ShareGPT 格式
dt transform data.jsonl --preset=dpo_pair        # 转换为 DPO 格式
dt transform data.jsonl --preset=simple_qa       # 转换为简单问答格式

# 数据转换 - 配置文件模式
dt transform data.jsonl                          # 首次运行生成配置文件 .dt/data.py
# 编辑配置文件后再次运行
dt transform data.jsonl                          # 执行转换
dt transform data.jsonl --num=100                # 只转换前 100 条
```

### MCP 服务

DataTransformer 提供 MCP (Model Context Protocol) 服务，可集成到支持 MCP 的 AI 工具中：

```bash
# 安装 MCP 依赖
pip install -e ".[mcp]"

# 启动 MCP 服务（由 AI 工具自动调用）
python -m data_transformer.mcp
```

### 数据集操作

```bash
# 使用命令行工具上传 SFT 数据集
python scripts/upload_sft_dataset.py \
  --file data/sft_dataset_example.jsonl \
  --name "我的数据集"

# SFT 数据集分析
python -m data_transformer.analysis.analyzer \
  --input data/sft_dataset_example.jsonl \
  --output analysis_results/

# 查看分析报告
open analysis_results/sft_analysis_report.html
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
- 继承 `BaseProcessor` (位于 `light_transformer.core.base`)
- 实现 `process(data: Any, context: Optional[Dict[str, Any]] = None) -> Any` 方法
- 在 `process()` 方法中添加类型注解以启用契约验证
- 可选: 定义 `CONFIG_SCHEMA` 类变量用于配置参数验证
- 使用 `context` 字典在处理器之间传递元数据和状态

流水线类型:
- **线性流水线** (`DataPipeline`): 顺序执行的处理器链
- **DAG 流水线** (`DAGPipeline`): 支持条件分支和并行处理的复杂数据流
- **异步流水线** (`AsyncDataPipeline`): 支持异步处理器

流水线组合示例:
```python
from light_transformer.core.pipeline import DataPipeline
from light_transformer.processors.text_similarity import TextSimilarityProcessor

# 线性流水线
pipeline = DataPipeline(strict=True)  # 启用类型检查
pipeline.add_processor(ProcessorA())
pipeline.add_processor(ProcessorB())
result = pipeline.process(data, context={"user_id": 123})

# DAG 流水线
from light_transformer.core.dag_pipeline import DAGPipeline
dag = DAGPipeline()
dag.add_processor("step1", ProcessorA())
dag.add_processor("step2", ProcessorB(), depends_on=["step1"])
dag.add_processor("step3", ProcessorC(), depends_on=["step1"])
result = dag.process(data)

# 从配置文件加载
from light_transformer.config.loader import load_pipeline_from_yaml
pipeline = load_pipeline_from_yaml("pipeline_config.yaml")
result = pipeline.process(data)
```

处理器注册:
```python
from light_transformer.core.registry import ProcessorRegistry

# 注册自定义处理器
registry = ProcessorRegistry()
registry.register("my_processor", MyCustomProcessor)

# 从配置实例化
processor = registry.create("my_processor", config={"param": "value"})
```

## 项目结构特点

- **包管理**: 使用 `hatchling` 作为构建后端,支持现代 Python 打包
- **前端技术栈**: React 18 + TypeScript + Vite + Ant Design 5
- **后端技术栈**: FastAPI + Pydantic v2 + FlaxKV2
- **测试框架**: pytest,配置在 `pyproject.toml` 和 `label-app/backend/pytest.ini`
- **代码风格**: Black (行长度 100) + isort + flake8 + mypy
- **Python 版本支持**: >= 3.8

## 文档结构

项目文档按模块组织在 `docs/` 目录:
- `docs/README.md`: 文档目录索引
- `docs/architecture/`: 架构设计文档
  - `design-principles.md`: 设计原则详解
  - `flaxkv2.md`: FlaxKV2 存储后端说明
  - `project-structure.md`: 项目结构说明
- `docs/guides/`: 使用指南
  - `sft-upload-guide.md`: SFT 数据集上传指南
  - `mllm-quickstart.md`: MLLM 处理器快速开始
- `docs/llm_topic_naming_quickstart.md`: LLM 主题命名快速开始
- `docs/ADVANCED_ANALYSIS_GUIDE.md`: 高级分析指南
- `docs/api/`: API 文档
  - `core.md`: 核心 API
  - `formats.md`: 格式转换 API
  - `storage.md`: 存储 API
- `docs/sft_dataset_analysis.md`: SFT 数据集分析功能文档

其他文档:
- `label-app/backend/README.md`: 后端 API 文档
- `label-app/frontend/README.md`: 前端应用文档
- `scripts/README.md`: 工具脚本说明
- `examples/README.md`: 示例代码说明
- `next-gen-designer/DESIGN.md`: 下一代框架设计文档
- `next-gen-designer/PROJECT_STATUS.md`: 项目状态

## 关键文件位置

- 核心类: `data_transformer/core.py:15` (DataTransformer 类)
- 格式转换基类: `data_transformer/formats/base.py:8` (BaseFormatter)
- 预设模板: `data_transformer/presets.py` (openai_chat、alpaca 等)
- CLI 命令: `data_transformer/cli/commands.py` (sample、transform)
- MCP 服务: `data_transformer/mcp/server.py`
- 存储管理器: `label-app/backend/app/core/storage_flaxkv.py:12` (FlaxKVStorageManager)
- 处理器基类: `next-gen-designer/light_transformer/core/base.py:11` (BaseProcessor)
- FastAPI 主应用: `label-app/backend/app/main.py`
- 项目配置: `pyproject.toml`

## 开发工作流

### 添加新的格式转换器
1. 在 `data_transformer/formats/` 下创建新文件
2. 继承 `BaseFormatter` 并实现 `format()` 和 `parse()` 方法
3. 在 `data_transformer/core.py` 的 `_formatters` 字典中注册
4. 在 `tests/` 下添加测试
5. 更新 `docs/api/formats.md` 文档

### 添加新的 light_transformer 处理器
1. 在 `next-gen-designer/light_transformer/processors/` 下创建新文件
2. 继承 `BaseProcessor` 并实现 `process(data, context)` 方法
3. 添加类型注解以启用契约验证
4. 可选: 定义 `CONFIG_SCHEMA` 类变量
5. 在 `next-gen-designer/tests/` 下添加测试
6. 在 `ProcessorRegistry` 中注册(如果需要从配置加载)

### 提交代码前检查清单
- [ ] 运行 `hatch run lint:fmt` 格式化代码
- [ ] 运行 `hatch run lint:style` 检查代码风格
- [ ] 运行 `hatch test` 确保测试通过
- [ ] 更新相关文档
- [ ] 遵循 KISS 原则和组合大于继承原则

## Git 工作流

- 主分支: `main`
- 提交消息: 使用清晰的中文描述变更内容
- 代码提交前确保所有测试通过
