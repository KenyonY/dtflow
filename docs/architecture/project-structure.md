# 项目结构

## 整体架构

```
DataTransformer/
├── data_transformer/           # 核心库
├── label-app/                  # Web 标注平台
├── next-gen-designer/          # 下一代数据处理框架
├── scripts/                    # 工具脚本
├── examples/                   # 示例代码
├── tests/                      # 测试
├── docs/                       # 文档
└── data/                       # 数据文件
```

## 核心库 (data_transformer/)

```
data_transformer/
├── __init__.py                 # 包初始化，导出主要类
├── core.py                     # DataTransformer 核心类
├── formats/                    # 格式转换器
│   ├── __init__.py
│   ├── base.py                 # BaseFormatter 基类
│   ├── sft.py                  # SFT 格式转换器
│   ├── rlhf.py                 # RLHF 格式转换器
│   └── pretrain.py             # Pretrain 格式转换器
├── storage/                    # 存储抽象层
│   ├── __init__.py
│   └── io.py                   # 文件读写（JSONL、CSV、Parquet）
└── utils/                      # 工具模块
    ├── __init__.py
    ├── similarity.py           # 相似度计算
    └── display.py              # 数据展示
```

### 职责说明

- **core.py**: 提供 `DataTransformer` 类，实现数据的增删改查、格式转换、保存加载等核心功能
- **formats/**: 各种机器学习格式的解析和转换
- **storage/**: 文件系统操作的抽象层
- **utils/**: 辅助工具函数

## Web 标注平台 (label-app/)

```
label-app/
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI 主应用
│   │   ├── config.py           # 配置管理
│   │   ├── models.py           # Pydantic 数据模型
│   │   ├── exceptions.py       # 自定义异常
│   │   ├── api/                # API 路由
│   │   │   ├── __init__.py
│   │   │   ├── datasets.py     # 数据集管理 API
│   │   │   └── annotations.py  # 标注功能 API
│   │   └── core/               # 核心模块
│   │       ├── __init__.py
│   │       ├── storage_flaxkv.py      # FlaxKV2 存储管理器
│   │       └── storage_factory.py     # 存储工厂
│   ├── tests/                  # 后端测试
│   ├── data/                   # 数据目录
│   ├── requirements.txt        # Python 依赖
│   ├── install.sh              # 安装脚本
│   ├── run.py                  # 启动脚本
│   └── pytest.ini              # pytest 配置
│
└── frontend/                   # React 前端
    ├── src/
    │   ├── components/         # React 组件
    │   ├── pages/              # 页面组件
    │   ├── stores/             # Zustand 状态管理
    │   ├── api/                # API 客户端
    │   └── App.tsx             # 应用入口
    ├── public/
    ├── package.json            # npm 依赖
    └── vite.config.ts          # Vite 配置
```

### 职责说明

- **backend/app/main.py**: FastAPI 应用初始化、中间件配置、路由注册
- **backend/app/api/**: RESTful API 端点实现
- **backend/app/core/**: 业务逻辑和存储管理
- **frontend/**: React + TypeScript + Ant Design 前端应用

## 下一代框架 (next-gen-designer/light_transformer/)

```
light_transformer/
├── __init__.py
├── core/                       # 核心框架
│   ├── __init__.py
│   ├── base.py                 # BaseProcessor 抽象基类
│   ├── contract.py             # DataContract 数据契约
│   ├── pipeline.py             # 同步流水线
│   ├── async_pipeline.py       # 异步流水线
│   ├── dag_pipeline.py         # DAG 流水线
│   └── registry.py             # 处理器注册表
├── processors/                 # 内置处理器
│   ├── __init__.py
│   ├── mllm.py                 # 多模态大模型处理器
│   ├── text_similarity.py      # 文本相似度处理器
│   └── image_similarity.py     # 图像相似度处理器
├── config/                     # 配置加载
│   ├── __init__.py
│   └── loader.py               # YAML 配置加载器
└── examples/                   # 示例
    ├── basic_pipeline_example.py
    └── dag_pipeline_example.py
```

### 设计特点

- **契约式编程**: 使用类型注解定义处理器契约
- **流水线组合**: 支持线性、异步、DAG 等多种流水线模式
- **配置驱动**: 支持 YAML 配置文件定义流水线

## 脚本和工具 (scripts/)

```
scripts/
├── upload_sft_dataset.py       # SFT 数据集上传工具
└── README.md                   # 脚本使用说明
```

## 示例代码 (examples/)

```
examples/
├── sft_upload_demo.html        # Web 界面示例
└── README.md                   # 示例说明
```

## 测试 (tests/)

```
tests/
├── test_transformer.py         # DataTransformer 测试
└── ...                         # 其他测试文件
```

## 文档 (docs/)

```
docs/
├── README.md                   # 文档主页
├── api/                        # API 参考文档
│   ├── core.md
│   ├── formats.md
│   └── storage.md
├── guides/                     # 使用指南
│   ├── sft-upload-guide.md
│   └── mllm-quickstart.md
└── architecture/               # 架构文档
    ├── flaxkv2.md
    ├── design-principles.md
    └── project-structure.md
```

## 数据目录 (data/)

```
data/
├── sft_dataset_example.jsonl   # 示例数据
├── temp/                       # 临时文件
└── flaxkv/                     # FlaxKV2 数据库文件
    ├── metadata/               # 元数据数据库
    └── dataset_*/              # 各个数据集的数据库
```

## 配置文件

- **pyproject.toml**: Python 项目配置（hatchling）
- **.github/workflows/ci.yml**: CI/CD 配置
- **label-app/backend/.env**: 后端环境变量
- **label-app/frontend/vite.config.ts**: 前端构建配置

## 模块间依赖关系

```
┌─────────────────────────────────────┐
│         Web 标注平台                 │
│    (label-app/backend)              │
│         ↓ depends on                │
│    DataTransformer 核心库            │
│    (data_transformer/)              │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│    下一代数据处理框架                 │
│   (light_transformer/)              │
│    独立模块，未来可能替代核心库        │
└─────────────────────────────────────┘
```

## 开发工作流

1. **核心库开发**: 修改 `data_transformer/`
2. **后端开发**: 修改 `label-app/backend/`
3. **前端开发**: 修改 `label-app/frontend/`
4. **新框架探索**: 修改 `next-gen-designer/light_transformer/`

## 包管理

- **Python**: 使用 `hatchling` 构建系统
- **Node.js**: 使用 `npm` (前端)
- **依赖安装**: 参考 [CLAUDE.md](../../CLAUDE.md)

## 参考

- [设计原则](design-principles.md)
- [FlaxKV2 架构](flaxkv2.md)
- [核心 API](../api/core.md)
