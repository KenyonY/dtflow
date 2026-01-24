---
name: dtflow
description: 数据文件处理（JSONL/CSV/Parquet）- 去重/采样/统计/过滤/转换/Schema验证/训练框架导出
---

# dtflow - 机器学习训练数据格式转换工具

## 设计理念

- **函数式优于类继承**：直接用 lambda/函数做转换，不需要 OOP 抽象
- **KISS 原则**：一个 `DataTransformer` 类搞定所有操作
- **链式 API**：`dt.filter(...).to(...).save(...)`

## Python API

```python
from dtflow import DataTransformer

# 加载数据（支持 JSONL/JSON/CSV/Parquet/Arrow，使用 Polars 引擎）
dt = DataTransformer.load("data.jsonl")

# 链式操作
(dt.filter(lambda x: x.score > 0.8)
   .to(lambda x: {"q": x.question, "a": x.answer})
   .dedupe("text")
   .save("output.jsonl"))
```

### 数据过滤

```python
dt.filter(lambda x: x.score > 0.8)
dt.filter(lambda x: x.language == "zh")
```

### 数据验证

```python
# 简单验证
errors = dt.validate(lambda x: len(x.messages) >= 2)

# Schema 验证
from dtflow import Schema, Field, openai_chat_schema

result = dt.validate_schema(openai_chat_schema)  # 预设 Schema
valid_dt = dt.validate_schema(schema, filter_invalid=True)  # 过滤无效数据
```

**预设 Schema**：`openai_chat_schema`、`alpaca_schema`、`sharegpt_schema`、`dpo_schema`

### 数据转换

```python
# 自定义转换
dt.to(lambda x: {"question": x.q, "answer": x.a})

# 使用预设模板
dt.to(preset="openai_chat", user_field="q", assistant_field="a")
```

**预设模板**：`openai_chat`、`alpaca`、`sharegpt`、`dpo_pair`、`simple_qa`

### Token 统计

```python
from dtflow import count_tokens, token_counter, token_filter, token_stats

count = count_tokens("Hello world", model="gpt-4")
dt.transform(token_counter("text")).save("with_tokens.jsonl")
dt.filter(token_filter("text", max_tokens=2048))

# Messages Token 统计（多轮对话）
from dtflow import messages_token_counter, messages_token_filter
dt.transform(messages_token_counter(model="gpt-4", detailed=True))
dt.filter(messages_token_filter(min_turns=2, max_turns=10))
```

### 格式转换器

```python
from dtflow import (
    to_hf_dataset, from_hf_dataset,      # HuggingFace Dataset
    to_openai_batch, from_openai_batch,  # OpenAI Batch API
    to_llama_factory, to_llama_factory_sharegpt,  # LLaMA-Factory
    to_swift_messages, to_swift_query_response,   # ms-swift
    messages_to_text,                    # messages 转纯文本
)
```

### 训练框架导出

```python
# 检查兼容性
result = dt.check_compatibility("llama-factory")

# 一键导出
files = dt.export_for("llama-factory", "./output/")  # 生成 data.json + dataset_info.json + train_args.yaml
files = dt.export_for("swift", "./output/")          # 生成 data.jsonl + train_swift.sh
files = dt.export_for("axolotl", "./output/")        # 生成 data.jsonl + config.yaml
```

### 大文件流式处理

```python
from dtflow import load_stream, load_sharded

# O(1) 内存，100GB 文件也能处理
(load_stream("huge.jsonl")
    .filter(lambda x: x["score"] > 0.5)
    .save("output.jsonl"))

# 分片文件加载
(load_sharded("data/train_*.parquet")
    .filter(lambda x: len(x["text"]) > 10)
    .save("merged.jsonl"))

# 分片保存
load_stream("huge.jsonl").save_sharded("output/", shard_size=100000)
```

### 其他操作

```python
dt.sample(100)                    # 随机采样
dt.head(10) / dt.tail(10)         # 取前/后 N 条
train, test = dt.split(ratio=0.8) # 分割
dt.shuffle(seed=42)               # 打乱
dt.stats()                        # 统计
```

## CLI 命令

```bash
# 统计（推荐首先使用）
dt stats data.jsonl                               # 基本统计（文件大小、条数、字段）
dt stats data.jsonl --full                        # 完整模式：值分布、唯一值、非空率
dt stats data.jsonl --full -n 20                  # 显示 Top 20 值分布

# Token 统计
dt token-stats data.jsonl                         # 默认统计 messages 字段
dt token-stats data.jsonl -f text                 # 指定统计字段
dt token-stats data.jsonl -m qwen2.5              # 指定分词器 (cl100k_base/qwen2.5/llama3)
dt token-stats data.jsonl --detailed              # 显示详细统计

# 采样（支持字段路径语法）
dt sample data.jsonl 100                          # 随机采样 100 条
dt sample data.jsonl 100 -t head                  # 取前 100 条 (head/tail/random)
dt sample data.jsonl 1000 --by=category           # 分层采样
dt sample data.jsonl 1000 --by=category --uniform # 均匀分层采样
dt sample data.jsonl --where="messages.#>=2"      # 条件筛选
dt sample data.jsonl 10 -f input,output           # 只显示指定字段
dt sample data.jsonl 10 --raw                     # 输出原始 JSON（不截断）
dt sample data.jsonl 100 --seed=42 -o out.jsonl   # 固定随机种子并保存

# 去重
dt dedupe data.jsonl --key=text                   # 精确去重
dt dedupe data.jsonl --key=meta.id                # 按嵌套字段去重
dt dedupe data.jsonl --key=text --similar=0.8    # 相似度去重
dt dedupe data.jsonl --key=text -o deduped.jsonl  # 指定输出文件

# 清洗
dt clean data.jsonl --drop-empty=text,answer      # 删除空值记录
dt clean data.jsonl --min-len=text:10             # 最小长度过滤
dt clean data.jsonl --max-len=text:2000           # 最大长度过滤
dt clean data.jsonl --min-len=messages.#:2        # 最少 2 条消息
dt clean data.jsonl --keep=question,answer        # 只保留指定字段
dt clean data.jsonl --drop=metadata               # 删除指定字段
dt clean data.jsonl --strip                       # 去除字符串首尾空白
dt clean data.jsonl --strip --drop-empty=input -o cleaned.jsonl  # 组合使用

# 验证
dt validate data.jsonl --preset=openai_chat       # 预设: openai_chat/alpaca/dpo/sharegpt
dt validate data.jsonl -p alpaca -f -o valid.jsonl  # 过滤无效数据并保存
dt validate data.jsonl -p openai_chat -v          # 显示详细信息
dt validate data.jsonl -p openai_chat --max-errors=50  # 最多显示 50 条错误

# 转换
dt transform data.jsonl --preset=openai_chat
dt transform data.jsonl                           # 交互式生成配置文件

# 合并与对比
dt concat a.jsonl b.jsonl -o merged.jsonl         # 合并文件
dt concat a.jsonl b.jsonl -o merged.jsonl --strict  # 严格模式（字段必须一致）
dt diff a.jsonl b.jsonl --key=id                  # 对比差异
dt diff a.jsonl b.jsonl --key=id -o report.md     # 输出对比报告

# 查看数据
dt head data.jsonl 10                             # 前 10 条
dt head data.jsonl 10 -f input,output             # 只显示指定字段
dt head data.jsonl 10 --raw                       # 输出完整 JSON（不截断）
dt tail data.jsonl 10                             # 后 10 条

# 其他
dt run pipeline.yaml                              # Pipeline 执行
dt history processed.jsonl                        # 数据血缘
dt install-skill                                  # 安装 Claude Code skill
```

## 字段路径语法

| 语法 | 含义 | 示例 |
|------|------|------|
| `a.b.c` | 嵌套字段 | `meta.source` |
| `a[0].b` | 数组索引 | `messages[0].role` |
| `a[-1].b` | 负索引 | `messages[-1].content` |
| `a.#` | 数组长度 | `messages.#` |
| `a[*].b` | 展开所有元素 | `messages[*].role` |

## Pipeline 配置

```yaml
# pipeline.yaml
version: "1.0"
seed: 42
input: raw_data.jsonl
output: processed.jsonl

steps:
  - type: filter
    condition: "score > 0.5"
  - type: transform
    preset: openai_chat
  - type: dedupe
    key: text
```
