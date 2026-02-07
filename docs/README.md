# dtflow 文档

> 简洁的数据格式转换工具，专为机器学习训练数据设计。

## 文档目录

```
docs/
├── README.md          # 本文档（主入口）
└── quickstart.md      # 快速入门指南
```

## 快速链接

- [快速入门](./quickstart.md) - 30 秒上手 dtflow
- [README](../README.md) - 项目主文档和使用说明

## 核心模块

| 模块 | 文件 | 功能 |
|------|------|------|
| **DataTransformer** | `core.py` | 核心数据处理类，链式 API |
| **预设模板** | `presets.py` | openai_chat, alpaca, sharegpt, dpo_pair, simple_qa |
| **Token 统计** | `tokenizers.py` | tiktoken/transformers 后端，messages 统计 |
| **格式转换** | `converters.py` | LLaMA-Factory, ms-swift, Axolotl, HuggingFace, OpenAI Batch |
| **流式处理** | `streaming.py` | 大文件惰性处理，O(1) 内存，支持 JSONL/CSV/Parquet/Arrow |
| **Pipeline** | `pipeline.py` | YAML 配置的可复现数据处理流程 |
| **数据血缘** | `lineage.py` | 操作追踪与历史记录 |
| **字段路径** | `utils/field_path.py` | 嵌套字段访问语法（`a.b`、`a[0].b`、`a.#`、`a[*].b`） |
| **文件 I/O** | `storage/io.py` | JSONL, JSON, CSV, Parquet, Arrow 等格式（Polars 引擎） |

## API 速览

### 基础用法

```python
from dtflow import DataTransformer

dt = DataTransformer.load("data.jsonl")
(dt.filter(lambda x: x.score > 0.8)
   .to(lambda x: {"q": x.question, "a": x.answer})
   .save("output.jsonl"))
```

### 流式处理（大文件）

```python
from dtflow import load_stream, load_sharded

# 100GB 文件也只用常量内存
(load_stream("huge.jsonl")
    .filter(lambda x: x["score"] > 0.5)
    .transform(lambda x: {"text": x["content"]})
    .save("output.jsonl"))

# 分片文件
load_sharded("data/*.jsonl").save_sharded("output/", shard_size=100000)
```

### Pipeline 配置

```yaml
# pipeline.yaml
version: "1.0"
seed: 42
input: raw.jsonl
output: processed.jsonl
steps:
  - type: filter
    condition: "score > 0.5"
  - type: transform
    preset: openai_chat
```

```bash
dt run pipeline.yaml
```

### 数据血缘

```python
dt = DataTransformer.load("raw.jsonl", track_lineage=True)
result = dt.filter(...).transform(...).dedupe("text")
result.save("output.jsonl", lineage=True)
```

```bash
dt history output.jsonl
```
