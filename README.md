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

## 🤖 Claude Code 集成

dtflow 内置了 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill：

```bash
dt install-skill      # 安装 skill
dt skill-status       # 查看状态
```

安装后在 Claude Code 中输入 `/dtflow`，Claude 将掌握 dtflow 的完整用法，可直接协助你完成数据处理任务。

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
# 支持 JSONL、JSON、CSV、Parquet、Arrow（使用 Polars 引擎，比 Pandas 快 3x）
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

### 数据验证

```python
# 简单验证，返回不通过的记录列表
errors = dt.validate(lambda x: len(x.messages) >= 2)

if errors:
    for e in errors[:5]:
        print(f"第 {e.index} 行: {e.error}")
```

### Schema 验证

使用 Schema 进行结构化数据验证：

```python
from dtflow import Schema, Field, openai_chat_schema

# 使用预设 Schema
result = dt.validate_schema(openai_chat_schema)
print(result)  # ValidationResult(valid=950, invalid=50, errors=[...])

# 自定义 Schema
schema = Schema({
    "messages": Field(type="list", required=True, min_length=1),
    "messages[*].role": Field(type="str", choices=["user", "assistant", "system"]),
    "messages[*].content": Field(type="str", min_length=1),
    "score": Field(type="float", min=0, max=1),
})

result = dt.validate_schema(schema)

# 过滤出有效数据
valid_dt = dt.validate_schema(schema, filter_invalid=True)
valid_dt.save("valid.jsonl")
```

**预设 Schema**：

| Schema 名称 | 用途 |
|------------|------|
| `openai_chat_schema` | OpenAI messages 格式验证 |
| `alpaca_schema` | Alpaca instruction/output 格式 |
| `sharegpt_schema` | ShareGPT conversations 格式 |
| `dpo_schema` | DPO prompt/chosen/rejected 格式 |

**Field 参数**：

| 参数 | 说明 | 示例 |
|------|------|------|
| `type` | 类型验证 | `"str"`, `"int"`, `"float"`, `"bool"`, `"list"`, `"dict"` |
| `required` | 是否必填 | `True` / `False` |
| `min` / `max` | 数值范围 | `min=0, max=1` |
| `min_length` / `max_length` | 长度范围 | `min_length=1` |
| `choices` | 枚举值 | `choices=["user", "assistant"]` |
| `pattern` | 正则匹配 | `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `custom` | 自定义验证 | `custom=lambda x: x > 0` |

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

### 训练框架一键导出

将数据导出为目标训练框架可直接使用的格式，自动生成配置文件：

```python
from dtflow import DataTransformer

dt = DataTransformer.load("data.jsonl")

# 1. 检查框架兼容性
result = dt.check_compatibility("llama-factory")
print(result)
# ✅ 兼容 - LLaMA-Factory (openai_chat)
# 或
# ❌ 不兼容 - 错误: xxx

# 2. 一键导出到 LLaMA-Factory
files = dt.export_for("llama-factory", "./llama_ready/")
# 生成文件:
# - ./llama_ready/custom_dataset.json      # 数据文件
# - ./llama_ready/dataset_info.json        # 数据集配置
# - ./llama_ready/train_args.yaml          # 训练参数模板

# 3. 导出到 ms-swift
files = dt.export_for("swift", "./swift_ready/")
# 生成: data.jsonl + train_swift.sh

# 4. 导出到 Axolotl
files = dt.export_for("axolotl", "./axolotl_ready/")
# 生成: data.jsonl + config.yaml

# 指定数据集名称
dt.export_for("llama-factory", "./output/", dataset_name="my_sft_data")
```

**支持的框架**：

| 框架 | 导出内容 | 使用方式 |
|------|---------|---------|
| `llama-factory` | data.json + dataset_info.json + train_args.yaml | `llamafactory-cli train train_args.yaml` |
| `swift` | data.jsonl + train_swift.sh | `bash train_swift.sh` |
| `axolotl` | data.jsonl + config.yaml | `accelerate launch -m axolotl.cli.train config.yaml` |

**自动格式检测**：

| 检测到的格式 | 数据结构 |
|------------|---------|
| `openai_chat` | `{"messages": [{"role": "user", ...}]}` |
| `alpaca` | `{"instruction": ..., "output": ...}` |
| `sharegpt` | `{"conversations": [{"from": "human", ...}]}` |
| `dpo` | `{"prompt": ..., "chosen": ..., "rejected": ...}` |

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
dt sample data.jsonl 1000 --by=category           # 分层采样
dt sample data.jsonl 1000 --by=meta.source        # 按嵌套字段分层采样
dt sample data.jsonl 1000 --by=messages.#         # 按消息数量分层采样
dt sample data.jsonl --where="category=tech"      # 筛选后采样
dt sample data.jsonl --where="messages.#>=2"      # 多条件筛选

# 数据转换 - 预设模式
dt transform data.jsonl --preset=openai_chat
dt transform data.jsonl --preset=alpaca

# 数据转换 - 配置文件模式
dt transform data.jsonl                    # 首次运行生成配置文件
# 编辑 .dt/data.py 后再次运行
dt transform data.jsonl --num=100          # 执行转换

# Pipeline 执行（可复现的数据处理流程）
dt run pipeline.yaml
dt run pipeline.yaml --input=new_data.jsonl --output=result.jsonl

# Token 统计
dt token-stats data.jsonl --field=messages --model=gpt-4
dt token-stats data.jsonl --field=messages[-1].content   # 统计最后一条消息
dt token-stats data.jsonl --field=text --detailed

# 数据对比
dt diff v1/train.jsonl v2/train.jsonl
dt diff a.jsonl b.jsonl --key=id
dt diff a.jsonl b.jsonl --key=meta.uuid    # 按嵌套字段匹配

# 数据清洗
dt clean data.jsonl --drop-empty                    # 删除任意空值记录
dt clean data.jsonl --drop-empty=text,answer        # 删除指定字段为空的记录
dt clean data.jsonl --drop-empty=meta.source        # 删除嵌套字段为空的记录
dt clean data.jsonl --min-len=text:10               # text 字段最少 10 字符
dt clean data.jsonl --min-len=messages.#:2          # 至少 2 条消息
dt clean data.jsonl --max-len=messages[-1].content:500  # 最后一条消息最多 500 字符
dt clean data.jsonl --keep=question,answer          # 只保留这些字段
dt clean data.jsonl --drop=metadata                 # 删除指定字段
dt clean data.jsonl --strip                         # 去除字符串首尾空白

# 数据去重
dt dedupe data.jsonl                            # 全量精确去重
dt dedupe data.jsonl --key=text                 # 按字段精确去重
dt dedupe data.jsonl --key=meta.id              # 按嵌套字段去重
dt dedupe data.jsonl --key=messages[0].content  # 按第一条消息内容去重
dt dedupe data.jsonl --key=text --similar=0.8   # 相似度去重

# 文件拼接
dt concat a.jsonl b.jsonl -o merged.jsonl

# 数据统计
dt stats data.jsonl                                       # 快速模式
dt stats data.jsonl --full                                # 完整模式（含值分布）
dt stats data.jsonl --full --field=category               # 指定字段统计
dt stats data.jsonl --full --expand=tags                  # 展开 list 字段统计元素分布
dt stats data.jsonl --full --expand='messages[*].role'    # 展开嵌套 list 字段

# Claude Code Skill 安装
dt install-skill                              # 安装到 ~/.claude/skills/
dt skill-status                               # 查看安装状态

# 数据验证
dt validate data.jsonl --preset=openai_chat           # 使用预设 schema 验证
dt validate data.jsonl --preset=alpaca --verbose      # 详细输出
dt validate data.jsonl --preset=sharegpt --filter-invalid -o valid.jsonl  # 过滤出有效数据
dt validate data.jsonl --preset=dpo --max-errors=100  # 限制错误输出数量
```

### 字段路径语法

CLI 命令中的字段参数支持嵌套路径语法，可访问深层嵌套的数据：

| 语法 | 含义 | 示例 |
|------|------|------|
| `a.b.c` | 嵌套字段 | `meta.source` |
| `a[0].b` | 数组索引 | `messages[0].role` |
| `a[-1].b` | 负索引 | `messages[-1].content` |
| `a.#` | 数组长度 | `messages.#` |
| `a[*].b` | 展开所有元素 | `messages[*].role` |
| `a[*].b:join` | 展开并用 `\|` 拼接 | `messages[*].role:join` |
| `a[*].b:unique` | 展开去重后拼接 | `messages[*].role:unique` |

支持字段路径的命令参数：

| 命令 | 参数 | 示例 |
|------|------|------|
| `sample` | `--by=`, `--where=` | `--by=meta.source`、`--where=messages.#>=2` |
| `dedupe` | `--key=` | `--key=meta.id`、`--key=messages[0].content` |
| `clean` | `--drop-empty=` | `--drop-empty=meta.source` |
| `clean` | `--min-len=` | `--min-len=messages.#:2` |
| `clean` | `--max-len=` | `--max-len=messages[-1].content:500` |
| `token-stats` | `--field=` | `--field=messages[-1].content` |
| `diff` | `--key=` | `--key=meta.uuid` |

`--where` 支持的操作符：

| 操作符 | 含义 | 示例 |
|--------|------|------|
| `=` | 等于 | `--where="category=tech"` |
| `!=` | 不等于 | `--where="source!=wiki"` |
| `~=` | 包含 | `--where="content~=机器学习"` |
| `>` | 大于 | `--where="score>0.8"` |
| `>=` | 大于等于 | `--where="messages.#>=2"` |
| `<` | 小于 | `--where="length<1000"` |
| `<=` | 小于等于 | `--where="turns<=10"` |

示例数据：
```json
{"meta": {"source": "wiki"}, "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]}
```

- `meta.source` → `"wiki"`
- `messages[0].role` → `"user"`
- `messages[-1].content` → `"hello"`
- `messages.#` → `2`
- `messages[*].role` → `"user"` (默认取第一个)
- `messages[*].role:join` → `"user|assistant"`

### Pipeline 配置

使用 YAML 配置文件定义可复现的数据处理流程：

```yaml
# pipeline.yaml
version: "1.0"
seed: 42
input: raw_data.jsonl
output: processed.jsonl

steps:
  - type: filter
    condition: "score > 0.5"

  - type: filter
    condition: "len(text) > 10"

  - type: transform
    preset: openai_chat
    params:
      user_field: q
      assistant_field: a

  - type: dedupe
    key: text
```

支持的步骤类型：

| 步骤 | 参数 | 说明 |
|------|------|------|
| `filter` | `condition` | 条件过滤：`score > 0.5`, `len(text) > 10`, `field is not empty` |
| `transform` | `preset`, `params` | 格式转换，使用预设模板 |
| `dedupe` | `key`, `similar` | 去重，支持精确和相似度去重 |
| `sample` | `num`, `seed` | 随机采样 |
| `head` | `num` | 取前 N 条 |
| `tail` | `num` | 取后 N 条 |
| `shuffle` | `seed` | 打乱顺序 |
| `split` | `ratio`, `seed` | 数据集分割 |

执行 Pipeline：

```bash
dt run pipeline.yaml
dt run pipeline.yaml --input=new_data.jsonl  # 覆盖输入文件
```

### 数据血缘追踪

记录数据处理的完整历史，支持可复现和问题追溯：

```python
# 启用血缘追踪
dt = DataTransformer.load("raw.jsonl", track_lineage=True)

# 正常进行数据处理
result = (dt
    .filter(lambda x: x.score > 0.5)
    .transform(lambda x: {"q": x.q, "a": x.a})
    .dedupe("q")
)

# 保存时记录血缘
result.save("processed.jsonl", lineage=True)
# 自动生成 processed.jsonl.lineage.json
```

查看血缘历史：

```bash
dt history processed.jsonl
# 输出：
# 📊 数据血缘报告: processed.jsonl
# └─ 版本 1
#    来源: raw.jsonl
#    操作链:
#      ├─ filter: 1000 → 800
#      ├─ transform: 800 → 800
#      └─ dedupe: 800 → 750
#    输出数量: 750

dt history processed.jsonl --json  # JSON 格式输出
```

### 日志查看

dtflow 内置了 [toolong](https://github.com/Textualize/toolong) 日志查看器：

```bash
pip install dtflow[logs]    # 安装日志工具

tl app.log                  # 交互式 TUI 查看
tl --tail app.log           # 实时跟踪（类似 tail -f）
dt logs                     # 查看使用说明
```

### 大文件流式处理

专为超大文件设计的流式处理接口，内存占用 O(1)，支持 JSONL、CSV、Parquet、Arrow 格式：

```python
from dtflow import load_stream, load_sharded

# 流式加载和处理（100GB 文件也只用常量内存）
(load_stream("huge_100gb.jsonl")
    .filter(lambda x: x["score"] > 0.5)
    .transform(lambda x: {"text": x["content"]})
    .save("output.jsonl"))

# 跨格式转换（CSV → Parquet）
(load_stream("data.csv")
    .filter(lambda x: x["score"] > 0.5)
    .save("output.parquet"))

# 分片文件加载（支持多格式）
(load_sharded("data/train_*.parquet")
    .filter(lambda x: len(x["text"]) > 10)
    .save("merged.jsonl"))

# 分片保存
(load_stream("huge.jsonl")
    .transform(lambda x: {"q": x["question"], "a": x["answer"]})
    .save_sharded("output/", shard_size=100000))
# 生成: output/part-00000.jsonl, output/part-00001.jsonl, ...

# 批次处理（适合需要批量调用 API 的场景）
for batch in load_stream("data.jsonl").batch(1000):
    results = call_api(batch)  # 批量处理
```

特点：
- **惰性执行**：filter/transform 不会立即执行，只在 save/collect 时才触发
- **O(1) 内存**：无论文件多大，内存占用恒定（读取侧）
- **多格式支持**：JSONL、CSV、Parquet、Arrow 均支持流式处理
- **跨格式转换**：可直接从 CSV 读取并保存为 Parquet 等
- **分片支持**：支持 glob 模式加载多个分片，自动合并处理

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
