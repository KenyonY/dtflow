"""Datatron MCP 文档内容

提供 Datatron 的用法文档，供 MCP 服务使用。
"""

# 可用的文档主题
TOPICS = [
    "overview",
    "basic_usage",
    "presets",
    "cli",
    "storage",
    "chain_api",
]

# 文档内容
DOCS = {
    "overview": """# Datatron 概述

Datatron 是一个专业的数据格式转换工具，专注于机器学习训练数据的格式转换。

## 核心特点

1. **简洁的 API**: 链式调用，代码简洁
2. **多格式支持**: JSONL、JSON、CSV、Parquet
3. **预设模板**: OpenAI Chat、Alpaca、ShareGPT、DPO 等
4. **属性访问**: lambda 中使用 `x.field` 代替 `x["field"]`

## 安装

```bash
pip install dtflow

# 完整安装（含存储、显示等）
pip install dtflow[full]
```

## 快速开始

```python
from dtflow import DataTransformer

# 加载数据
dt = DataTransformer.load("data.jsonl")

# 查看数据
print(dt.fields())  # 查看字段
print(dt.stats())   # 统计信息
print(len(dt))      # 数据量

# 转换格式
result = dt.to(lambda x: {
    "instruction": x.q,
    "output": x.a
})

# 链式调用
dt.filter(lambda x: len(x.q) > 10) \\
  .sample(100) \\
  .transform(lambda x: {"q": x.q, "a": x.a}) \\
  .save("output.jsonl")
```

## CLI 使用

```bash
# 使用预设转换
dt transform data.jsonl --preset=openai_chat

# 配置文件模式（首次生成配置，编辑后再次运行）
dt transform data.jsonl

# 采样数据
dt sample data.jsonl --num=10
```
""",

    "basic_usage": """# Datatron 基本用法

## 加载与保存

```python
from dtflow import DataTransformer

# 加载（支持 jsonl, json, csv, parquet）
dt = DataTransformer.load("data.jsonl")

# 保存（根据扩展名自动选择格式）
dt.save("output.jsonl")
```

## 数据转换

### 使用 to() - 返回列表
```python
# lambda 参数支持属性访问
result = dt.to(lambda x: {
    "instruction": x.q,
    "output": x.a
})
```

### 使用 transform() - 返回 DataTransformer（支持链式调用）
```python
new_dt = dt.transform(lambda x: {
    "instruction": x.q,
    "output": x.a
})
new_dt.save("output.jsonl")
```

## 数据筛选

```python
# 筛选
dt.filter(lambda x: len(x.text) > 10)

# 采样
dt.sample(100)           # 随机采样 100 条
dt.sample(100, seed=42)  # 指定随机种子

# 取前/后 N 条
dt.head(10)
dt.tail(10)
```

## 数据信息

```python
# 查看字段
print(dt.fields())
# ['a', 'meta.source', 'q']

# 统计信息
print(dt.stats())
# {'total': 1000, 'fields': ['q', 'a'], 'field_stats': {...}}
```

## 工具方法

```python
# 深拷贝
new_dt = dt.copy()

# 打乱顺序
dt.shuffle()
dt.shuffle(seed=42)

# 分割数据集
train, test = dt.split(ratio=0.8)
```
""",

    "presets": """# 预设转换模板

Datatron 提供常用的格式转换预设，可直接用于 CLI 或 Python API。

## 可用预设

| 预设名称 | 输出格式 | 用途 |
|---------|---------|------|
| openai_chat | OpenAI Chat 格式 | 对话微调 |
| alpaca | Alpaca 指令格式 | 指令微调 |
| sharegpt | ShareGPT 多轮对话 | 对话训练 |
| dpo_pair | DPO 偏好对格式 | RLHF 训练 |
| simple_qa | 简单问答格式 | 问答任务 |

## CLI 使用

```bash
# 使用预设转换
dt transform data.jsonl --preset=openai_chat
dt transform data.jsonl --preset=alpaca --output=alpaca.jsonl
```

## Python API 使用

```python
from dtflow.presets import get_preset, list_presets

# 列出所有预设
print(list_presets())
# ['openai_chat', 'alpaca', 'sharegpt', 'dpo_pair', 'simple_qa']

# 获取预设转换函数
transform_fn = get_preset("openai_chat",
                          user_field="q",
                          assistant_field="a")

# 使用预设
dt = DataTransformer.load("data.jsonl")
result = dt.to(transform_fn)
```

## 预设输出格式详情

### openai_chat
```python
{
    "messages": [
        {"role": "system", "content": "..."},  # 可选
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."}
    ]
}
```

### alpaca
```python
{
    "instruction": "...",
    "input": "...",
    "output": "..."
}
```

### sharegpt
```python
{
    "conversations": [
        {"from": "human", "value": "..."},
        {"from": "gpt", "value": "..."}
    ]
}
```

### dpo_pair
```python
{
    "prompt": "...",
    "chosen": "...",
    "rejected": "..."
}
```
""",

    "cli": """# CLI 命令行工具

Datatron 提供 `dt` 命令行工具。

## transform 命令 - 数据转换

### 预设模式
```bash
# 使用预设直接转换
dt transform data.jsonl --preset=openai_chat
dt transform data.jsonl --preset=alpaca --output=alpaca.jsonl

# 只转换前 N 条
dt transform data.jsonl --preset=openai_chat --num=100
```

### 配置文件模式
```bash
# 首次运行：生成配置文件（.dt/data.py）
dt transform data.jsonl

# 编辑配置文件后再次运行：执行转换
dt transform data.jsonl
```

配置文件示例（.dt/data.py）:
```python
def transform(item):
    return {
        "instruction": item.get("q", ""),
        "output": item.get("a", ""),
    }
```

## sample 命令 - 数据采样

```bash
# 随机采样 10 条（默认）
dt sample data.jsonl

# 指定采样数量
dt sample data.jsonl --num=50

# 采样方式：random(默认), head, tail
dt sample data.jsonl --sample_type=head --num=20

# 输出到文件
dt sample data.jsonl --num=100 --output=sampled.jsonl

# 指定随机种子
dt sample data.jsonl --num=50 --seed=42
```

## 支持的文件格式

- JSONL (.jsonl)
- JSON (.json)
- CSV (.csv)
- Excel (.xlsx, .xls) - 需要安装 pandas
- Parquet (.parquet) - 需要安装 pyarrow
""",

    "storage": """# 存储格式支持

Datatron 支持多种常用数据格式。

## 支持的格式

| 格式 | 扩展名 | 依赖 |
|-----|-------|------|
| JSONL | .jsonl | 无（内置） |
| JSON | .json | 无（内置） |
| CSV | .csv | 无（内置） |
| Excel | .xlsx, .xls | pandas, openpyxl |
| Parquet | .parquet | pyarrow |

## 使用示例

```python
from dtflow import DataTransformer

# 加载不同格式（自动检测）
dt1 = DataTransformer.load("data.jsonl")
dt2 = DataTransformer.load("data.csv")
dt3 = DataTransformer.load("data.parquet")

# 保存不同格式（根据扩展名）
dt.save("output.jsonl")
dt.save("output.csv")
dt.save("output.parquet")
```

## 直接使用 IO 函数

```python
from dtflow.storage import load_data, save_data

# 加载
data = load_data("input.jsonl")

# 保存
save_data(data, "output.jsonl")
```

## 安装额外依赖

```bash
# 完整安装（含所有格式支持）
pip install dtflow[full]

# 仅存储格式支持
pip install dtflow[storage]
```
""",

    "chain_api": """# 链式 API 设计

Datatron 支持流畅的链式调用。

## 链式调用示例

```python
from dtflow import DataTransformer

# 加载 -> 筛选 -> 采样 -> 转换 -> 保存
DataTransformer.load("input.jsonl") \\
    .filter(lambda x: len(x.q) > 10) \\
    .sample(1000) \\
    .transform(lambda x: {
        "instruction": x.q,
        "output": x.a
    }) \\
    .save("output.jsonl")
```

## 可链式调用的方法

| 方法 | 返回类型 | 说明 |
|-----|---------|------|
| `filter(func)` | DataTransformer | 筛选数据 |
| `sample(n)` | DataTransformer | 随机采样 |
| `head(n)` | DataTransformer | 取前 N 条 |
| `tail(n)` | DataTransformer | 取后 N 条 |
| `transform(func)` | DataTransformer | 格式转换 |
| `shuffle()` | DataTransformer | 打乱顺序 |
| `copy()` | DataTransformer | 深拷贝 |

## 终结方法

| 方法 | 返回类型 | 说明 |
|-----|---------|------|
| `to(func)` | List | 转换并返回列表 |
| `save(path)` | None | 保存到文件 |
| `fields()` | List[str] | 获取字段列表 |
| `stats()` | Dict | 获取统计信息 |
| `split(ratio)` | Tuple | 分割数据集 |

## 属性访问

lambda 参数支持属性访问，更简洁：

```python
# 使用属性访问（推荐）
dt.filter(lambda x: x.score > 0.8)
dt.transform(lambda x: {"q": x.question, "a": x.answer})

# 支持嵌套属性
dt.filter(lambda x: x.meta.source == "wiki")

# 也支持字典访问
dt.filter(lambda x: x["score"] > 0.8)

# 安全获取（带默认值）
dt.transform(lambda x: {"q": x.get("question", "")})
```
""",
}


def get_doc(topic: str) -> str:
    """获取指定主题的文档"""
    if topic not in DOCS:
        available = ", ".join(TOPICS)
        return f"未知主题: {topic}\n\n可用主题: {available}"
    return DOCS[topic]
