# dtflow

简洁的数据格式转换工具，专为机器学习训练数据设计。

## 安装

```bash
pip install dtflow

# 可选依赖
pip install tiktoken          # Token 统计（OpenAI 模型）
pip install transformers      # Token 统计（HuggingFace 模型）
pip install datasets          # HuggingFace Dataset 转换
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

### Token 统计

```python
from dtflow import count_tokens, token_counter, token_filter, token_stats

# 计算 token 数量
count = count_tokens("Hello world", model="gpt-4")

# 添加 token_count 字段
dt.transform(token_counter("text")).save("with_tokens.jsonl")

# 按 token 长度过滤
dt.filter(token_filter("text", max_tokens=2048))
dt.filter(token_filter(["question", "answer"], min_tokens=10, max_tokens=4096))

# 统计 token 分布
stats = token_stats(dt.data, "text")
# {"total_tokens": 12345, "avg_tokens": 123, "min_tokens": 5, "max_tokens": 500, ...}
```

支持 `tiktoken`（OpenAI，默认）和 `transformers` 后端，**自动检测**：

```python
# OpenAI 模型 -> 自动使用 tiktoken
count_tokens("Hello", model="gpt-4")

# HuggingFace/本地模型 -> 自动使用 transformers
count_tokens("Hello", model="Qwen/Qwen2-7B")
count_tokens("Hello", model="/home/models/qwen")
```

### Messages Token 统计

专为多轮对话设计的 token 统计功能：

```python
from dtflow import messages_token_counter, messages_token_filter, messages_token_stats

# 为每条数据添加 token 统计
dt.transform(messages_token_counter(model="gpt-4"))  # 简单模式，输出总数
dt.transform(messages_token_counter(model="gpt-4", detailed=True))  # 详细模式
# 详细模式输出: {"total": 500, "user": 200, "assistant": 280, "system": 20, "turns": 5, ...}

# 按 token 数和轮数过滤
dt.filter(messages_token_filter(min_tokens=100, max_tokens=4096))
dt.filter(messages_token_filter(min_turns=2, max_turns=10))

# 统计整个数据集
stats = messages_token_stats(dt.data, model="gpt-4")
# {"count": 1000, "total_tokens": 500000, "user_tokens": 200000, "assistant_tokens": 290000, ...}
```

### 格式转换器

```python
from dtflow import (
    to_hf_dataset, from_hf_dataset,    # HuggingFace Dataset
    to_openai_batch, from_openai_batch, # OpenAI Batch API
    to_llama_factory,                   # LLaMA-Factory Alpaca 格式
    to_axolotl,                         # Axolotl 格式
    messages_to_text,                   # messages 转纯文本
)

# HuggingFace Dataset 互转
ds = to_hf_dataset(dt.data)
ds.push_to_hub("my-dataset")

data = from_hf_dataset("tatsu-lab/alpaca", split="train")

# OpenAI Batch API
batch_input = dt.to(to_openai_batch(model="gpt-4o"))
results = from_openai_batch(batch_output)

# messages 转纯文本（支持 chatml/llama2/simple 模板）
dt.transform(messages_to_text(template="chatml"))
```

### LLaMA-Factory 格式

完整支持 LLaMA-Factory 的 SFT 训练格式：

```python
from dtflow import (
    to_llama_factory,              # Alpaca 格式（单轮）
    to_llama_factory_sharegpt,     # ShareGPT 格式（多轮对话）
    to_llama_factory_vlm,          # VLM Alpaca 格式
    to_llama_factory_vlm_sharegpt, # VLM ShareGPT 格式
)

# Alpaca 格式
dt.transform(to_llama_factory()).save("alpaca.jsonl")
# 输出: {"instruction": "...", "input": "", "output": "..."}

# ShareGPT 格式（多轮对话）
dt.transform(to_llama_factory_sharegpt()).save("sharegpt.jsonl")
# 输出: {"conversations": [{"from": "human", "value": "..."}, {"from": "gpt", "value": "..."}], "system": "..."}

# VLM 格式（图片/视频）
dt.transform(to_llama_factory_vlm(images_field="images")).save("vlm.jsonl")
# 输出: {"instruction": "...", "output": "...", "images": ["/path/to/img.jpg"]}

dt.transform(to_llama_factory_vlm_sharegpt(images_field="images", videos_field="videos"))
# 输出: {"conversations": [...], "images": [...], "videos": [...]}
```

### ms-swift 格式

支持 ModelScope ms-swift 的训练格式：

```python
from dtflow import (
    to_swift_messages,        # 标准 messages 格式
    to_swift_query_response,  # query-response 格式
    to_swift_vlm,             # VLM 格式
)

# messages 格式
dt.transform(to_swift_messages()).save("swift_messages.jsonl")
# 输出: {"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}

# query-response 格式（自动提取 history）
dt.transform(to_swift_query_response(query_field="messages")).save("swift_qr.jsonl")
# 输出: {"query": "...", "response": "...", "system": "...", "history": [["q1", "a1"], ...]}

# VLM 格式
dt.transform(to_swift_vlm(images_field="images")).save("swift_vlm.jsonl")
# 输出: {"messages": [...], "images": ["/path/to/img.jpg"]}
```

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

# 数据清洗
dt clean data.jsonl --drop-empty                    # 删除任意空值记录
dt clean data.jsonl --drop-empty=text,answer        # 删除指定字段为空的记录
dt clean data.jsonl --min-len=text:10               # text 字段最少 10 字符
dt clean data.jsonl --max-len=text:1000             # text 字段最多 1000 字符
dt clean data.jsonl --keep=question,answer          # 只保留这些字段
dt clean data.jsonl --drop=metadata                 # 删除指定字段
dt clean data.jsonl --strip                         # 去除字符串首尾空白
dt clean data.jsonl --strip --drop-empty=text --min-len=text:10 -o clean.jsonl  # 组合使用

# 数据去重
dt dedupe data.jsonl                            # 全量精确去重
dt dedupe data.jsonl --key=text                 # 按字段精确去重
dt dedupe data.jsonl --key=text --similar=0.8   # 相似度去重

# 文件拼接
dt concat a.jsonl b.jsonl -o merged.jsonl

# 数据统计
dt stats data.jsonl
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

## 设计哲学

### 函数式优于类继承

不需要复杂的 OOP 抽象，直接用函数解决问题：

```python
# ✅ 简单直接
dt.to(lambda x: {"q": x.question, "a": x.answer})

# ❌ 不需要这种设计
class MyFormatter(BaseFormatter):
    def format(self, item): ...
```

### 预设是便利层，不是核心抽象

90% 的需求用 `transform(lambda x: ...)` 就能解决。预设只是常见场景的快捷方式：

```python
# 预设：常见场景的便利函数
dt.to(preset="openai_chat")

# 自定义：完全控制转换逻辑
dt.to(lambda x: {
    "messages": [
        {"role": "user", "content": x.q},
        {"role": "assistant", "content": x.a}
    ]
})
```

### KISS 原则

- 一个核心类 `DataTransformer` 搞定所有操作
- 链式 API，代码像自然语言
- 属性访问 `x.field` 代替 `x["field"]`
- 不过度设计，不追求"可扩展框架"

### 实用主义

不追求学术上的完美抽象，只提供**足够好用的工具**。

## License

MIT
