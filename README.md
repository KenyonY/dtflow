# dtflow

简洁的数据格式转换工具，专为机器学习训练数据设计。

## 安装

```bash
pip install dtflow
```

## 快速开始

```python
from dtflow import DataTransformer

# 加载数据
dt = DataTransformer.load("data.jsonl")

# 链式操作：过滤 -> 转换 -> 保存
(dt.filter(lambda x: x.score > 0.8)
   .to(lambda x: {"q": x.question, "a": x.answer})
   .save("output.jsonl"))
```

## 核心功能

### 数据加载与保存

```python
# 支持 JSONL、JSON、CSV、Parquet
dt = DataTransformer.load("data.jsonl")
dt.save("output.jsonl")

# 从列表创建
dt = DataTransformer([{"q": "问题", "a": "答案"}])
```

### 数据过滤

```python
# Lambda 过滤
dt.filter(lambda x: x.score > 0.8)

# 支持属性访问
dt.filter(lambda x: x.language == "zh")
```

### 数据转换

```python
# 自定义转换
dt.to(lambda x: {"question": x.q, "answer": x.a})

# 使用预设模板
dt.to(preset="openai_chat", user_field="q", assistant_field="a")
```

### 预设模板

| 预设名称 | 输出格式 |
|---------|---------|
| `openai_chat` | `{"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}` |
| `alpaca` | `{"instruction": ..., "input": ..., "output": ...}` |
| `sharegpt` | `{"conversations": [{"from": "human", ...}, {"from": "gpt", ...}]}` |
| `dpo_pair` | `{"prompt": ..., "chosen": ..., "rejected": ...}` |
| `simple_qa` | `{"question": ..., "answer": ...}` |

### 其他操作

```python
# 采样
dt.sample(100)           # 随机采样 100 条
dt.head(10)              # 前 10 条
dt.tail(10)              # 后 10 条

# 分割
train, test = dt.split(ratio=0.8, shuffle=True, seed=42)

# 统计
stats = dt.stats()       # 总数、字段信息
count = dt.count(lambda x: x.score > 0.9)

# 打乱
dt.shuffle(seed=42)
```

## CLI 命令

```bash
# 数据采样
dt sample data.jsonl --num=10
dt sample data.csv --num=100 --sample_type=head

# 数据转换 - 预设模式
dt transform data.jsonl --preset=openai_chat
dt transform data.jsonl --preset=alpaca

# 数据转换 - 配置文件模式
dt transform data.jsonl                    # 首次运行生成配置文件
# 编辑 .dt/data.py 后再次运行
dt transform data.jsonl --num=100          # 执行转换
```

## 错误处理

```python
# 跳过错误项（默认）
dt.to(transform_func, on_error="skip")

# 抛出异常
dt.to(transform_func, on_error="raise")

# 保留原始数据
dt.to(transform_func, on_error="keep")

# 返回错误信息
result, errors = dt.to(transform_func, return_errors=True)
```

## 设计原则

- **KISS**: 简单直接，一个类搞定所有操作
- **链式 API**: 流畅的函数式编程风格
- **属性访问**: `x.field` 代替 `x["field"]`

## License

MIT
