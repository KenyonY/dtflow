# dtflow

<p align="left"><a href="README.md">English</a> | 中文</p>

<p align="left">
    <a href="https://pypi.org/project/dtflow/">
        <img src="https://img.shields.io/pypi/v/dtflow?color=brightgreen&style=flat-square" alt="PyPI version">
    </a>
    <a href="https://github.com/KenyonY/dtflow/blob/main/LICENSE">
        <img alt="License" src="https://img.shields.io/github/license/KenyonY/dtflow.svg?color=blue&style=flat-square">
    </a>
    <a href="https://pypistats.org/packages/dtflow">
        <img alt="pypi downloads" src="https://img.shields.io/pypi/dm/dtflow?style=flat-square">
    </a>
</p>

简洁的数据格式转换工具，专为机器学习训练数据设计。

<p align="center">
  <img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/demo.gif" alt="dt view：表格 + 详情联动的终端数据浏览器，全量搜索 / 筛选 / 列值勾选 / 放大 / dpo 对比" width="900">
</p>
<p align="center"><sub><code>dt view data.jsonl</code> —— 一条命令把训练数据变成可搜索、可筛选的终端浏览器（<a href="#交互式数据浏览dt-view">详细介绍</a>）</sub></p>

## 安装

```bash
pip install dtflow

# 可选依赖
pip install "dtflow[tokenizers-hf]"   # HuggingFace 分词器的 Token 统计
pip install "dtflow[converters]"      # HuggingFace Dataset 转换
pip install "dtflow[similarity]"      # 相似度去重 (MinHash)
```

## 交互式数据浏览：dt view

`dt view <file>` 打开一个 master-detail 终端浏览器：左侧表格扫视样本（`turns/roles/first_user/chars/calls` 派生列 + 元数据列），右侧详情按格式渲染当前行——对话按 role 上色、代码块语法高亮、工具调用格式化并标出坏参数、dpo 左右对比。JSONL/CSV/Parquet 都能开，几十万行的文件也是秒开（窗口化加载，搜索/筛选/排序走并行全量扫描）。

<table>
  <tr>
    <td width="50%"><img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/main.png" alt="openai_chat 主界面：表格 + 详情联动，代码块语法高亮"></td>
    <td width="50%"><img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/search.png" alt="/ 全量搜索：整条记录任意值，命中处黄底高亮，状态栏显示命中占比"></td>
  </tr>
  <tr>
    <td align="center"><sub><b>主界面</b>：表格选行，详情按 role 上色、代码块高亮</sub></td>
    <td align="center"><sub><b><code>/</code> 全量搜索</b>：搜整条记录（含 assistant 回复），命中黄底高亮</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/value_filter.png" alt="F 列值勾选筛选：列出唯一值与频次，勾选保留"></td>
    <td width="50%"><img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/dpo.png" alt="dpo 格式：prompt / chosen / rejected 对比渲染"></td>
  </tr>
  <tr>
    <td align="center"><sub><b><code>F</code> 列值勾选</b>：Excel AutoFilter 式，唯一值 + 频次，勾谁留谁</sub></td>
    <td align="center"><sub><b>dpo 对比</b>：chosen / rejected 分色渲染，格式自动检测</sub></td>
  </tr>
</table>

```bash
dt view data.jsonl                          # 打开即用，? 看快捷键
dt view app.jsonl -100 -f                   # 追尾最新 100 行（日志模式）
dt view data.jsonl -w "turns>=6" -s 报错    # 启动即筛选 + 搜索
dt sample data.jsonl 500 | dt view -        # 管道：看采样/处理后的结果
```

| 按键 | 作用 |
|------|------|
| `/` `f` `F` `s` | 全量搜索 · 表达式筛选（`turns>=6 and x.source=='alpaca'`，Python 表达式）· 列值勾选 · 排序，可叠加，`r` 一键清空 |
| `Enter` `n/N` `*` | 放大当前样本 · 逐字段跳 · 只在搜索命中间跳 |
| `w` `C` | 把筛出的子集导出成文件（自动写血缘）· 复制一条能复现当前视图的 `dt view` 命令 |
| `y` / 鼠标拖选 + `Ctrl+c` | 复制整条样本 JSON / 复制详情里任意一段文字（SSH/tmux 下也进本机剪贴板） |

完整快捷键、筛选语法、大文件与 follow 模式的细节见 [交互式数据浏览 (dt view)](#交互式数据浏览-dt-view)。

### 和其他终端数据查看器有什么不同

VisiData / tabiew 是通用表格工具，jless / fx 是 JSON 树查看器，csvlens 只看 CSV。它们都没有"这是一条训练样本"的概念：`messages` 在表格里是一个 `{3}` 或一段字符串，要看对话得逐层展开、一条一条点。dt view 反过来，先认格式再画界面，一屏就是一条完整样本。

| | dt view | VisiData 3.4 | tabiew 0.15 | jless 0.9 / fx 39 | csvlens 0.15 |
|---|---|---|---|---|---|
| 定位 | LLM 训练数据浏览器 | 通用表格瑞士军刀 | 通用表格（Polars） | JSON 树查看器 | CSV 极简查看器 |
| 对话 / dpo / alpaca / tool_calls 按格式渲染 | 气泡按 role 上色、代码高亮、工具调用参数格式化并标出坏 JSON | 无，嵌套字段显示为 `{3}`，按 `(` 逐层展开 | 无，嵌套字段显示为字符串 | 通用树形，一次只看一条 | 不支持 JSONL |
| 鼠标 | 点列头筛选、拖列宽、拖两区分界、拖选文本复制、连击选词/行/段、滚轮 | 点击选格、滚轮 | 无（鼠标事件被丢弃） | 点击选行、滚轮 | 无 |
| 155MB / 91 万行 JSONL 打开后峰值内存 | **91 MB**（窗口化，不随文件涨） | 550 MB | 565 MB | 824 MB / 2.3 GB | 不支持 |
| 搜索范围 | 整条记录的每个值（含 assistant 回复），并行扫全文件 | 当前列或全部列的正则 | 模糊搜索、SQL | 树内正则 | 行正则 |
| 筛出来之后 | `w` 导出子集并自动写血缘，`C` 复制一条可复现命令 | 导出 | 导出 | 无 | 无 |
| JSONL 追尾（`-f`） | 有 | 无 | 无 | 无 | 无 |
| 它们更强的地方 | — | 透视、频次表、join、绘图、几十种格式 | SQL 查询、Rust 单二进制 | 深层 JSON 折叠、jq 路径 | 零依赖、秒开 |

**什么时候不该用 dt view**：要做 join、透视、按列画图，用 VisiData；要对表写 SQL，用 tabiew；只想看一个 JSON 文件的层级，用 jless。dt view 只在"这是一批训练样本，我要扫、找、筛、导出"这件事上比它们好——但这正是训练数据每天要做的事。

<sub>内存为同一台 Linux 机器上打开文件后静置的峰值 RSS（2026-09），其余各项按各工具的 README 与源码核对，版本见表头。</sub>

## 🤖 Agent Skill 集成

dtflow 内置 Agent Skill，可安装到 Claude Code 或 Codex：

```bash
dt install-skill                         # 安装到 Claude Code（兼容默认）
dt install-skill --target codex          # 安装到 Codex
dt skill-status --target codex           # 查看 Codex 安装状态
```

安装后可在 Claude Code 中输入 `/dtflow`，或在 Codex 中使用 `$dtflow`，让 agent
掌握 dtflow 的完整用法并协助完成数据处理任务。

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
# 支持 JSONL/NDJSON、JSON、CSV/TSV、Parquet、Arrow、Excel（使用 Polars 引擎，比 Pandas 快 3x）
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

所有数据命令遵守同一套约定：**`FILE` 写 `-` 从 stdin 读 NDJSON；不加 `-o` 数据写 stdout**（进度/摘要只走 stderr），
所以命令可以像 Unix 工具一样用管道拼接；筛选/派生/排序/分组的条件一律是 **Python 表达式，当前行叫 `x`**。

```bash
# 数据原语（可任意拼接; 表达式即 Python, 当前行为 x）
dt filter data.jsonl "x.score > 0.5 and 'wiki' in x.meta.source"
dt filter data.jsonl "len(x.messages) >= 2 and x.messages[-1].role == 'assistant'"
dt select data.jsonl "id,text,n=len(x.messages),src=x.meta.source"   # 投影 / 重命名 / 派生
dt map    data.jsonl "x.text = x.text.strip(); del x.debug"          # 原地修改
dt explode data.jsonl --field messages --index-as turn                # list 展开成多行
dt sort   data.jsonl --by "len(x.messages)" --desc
dt shuffle data.jsonl --seed 42 -o shuffled.jsonl
dt group  data.jsonl --by x.meta.source                               # {"key","count"} 按 count 降序
dt group  data.jsonl --by x.label --agg "avg=mean(len(r.text) for r in g),ids=[r.id for r in g][:3]"
dt join   data.jsonl meta.jsonl --on x.id --prefix m_                 # 左连接, 右表入内存
dt stats  data.jsonl --schema                                         # 嵌套 schema: 先看全貌再写表达式

# 管道拼接
dt filter d.jsonl "x.score>0.5" | dt select - "id,n=len(x.messages)" | dt sort - --by x.n --desc | dt head - 5
dt sample d.jsonl 0 -w "x.ok" | dt clean - --strip | dt dedupe - --key=text -o clean.jsonl
dt group d.jsonl --by x.label | dt sort - --by x.count --desc
cat big.jsonl.gz | dt filter - "x.lang=='zh'" | dt transform - --preset=openai_chat | dt view -

# 数据采样
dt sample data.jsonl --num=10
dt sample data.csv --num=100 --type=head
dt sample data.jsonl 1000 --by=category           # 分层采样
dt sample data.jsonl 1000 --by=meta.source        # 按嵌套字段分层采样
dt sample data.jsonl 1000 --by=messages.#         # 按消息数量分层采样
dt sample data.jsonl --where="x.category=='tech'"        # 筛选后采样 (-w 可多次, 多条 AND)
dt sample data.jsonl -w "len(x.messages)>=2" -w "x.score>0.8"

# 交互式浏览（表格 + 详情联动 TUI，需交互式终端）
dt view data.jsonl                                # 打开浏览器，按 ? 看快捷键
dt view data.jsonl -100                           # 快速从倒数 100 行开始
dt view app.jsonl -100 -f                         # 持续追踪最新 100 行及日志轮转 (-f=--follow)
dt view data.csv                                  # CSV/Parquet 等表格数据
dt view data.jsonl --format=dpo                   # 强制按指定格式渲染详情
dt view big.jsonl --cap=50000                     # 提高大文件加载上限（默认 1 万行）
dt view data.jsonl -S -chars                      # 启动即全量排序（-S=--sort，最长的排前面）
dt view data.jsonl -w "turns>=6" -s 报错          # 启动即筛选 + 搜索（-w=--where 可多次，-s=--search）

# 静态预览（--pretty 走格式感知渲染：对话气泡/dpo对比/alpaca分段/表格）
dt head data.jsonl --pretty                       # 前 N 条，格式化渲染
dt sample data.jsonl --pretty                     # 采样 + 格式化渲染

# 按行范围查看（Python 切片语法）
dt slice data.jsonl 10:20                          # 第 10-19 行（0-based，左闭右开）
dt slice data.jsonl :100                           # 前 100 行
dt slice data.jsonl 100:                           # 第 100 行到末尾
dt slice data.jsonl 10:20 -o sliced.jsonl          # 保存到文件
dt slice data.jsonl 10:20 -f question,answer       # 只显示指定字段

# 数据转换 - 预设模式 (无 -o 写 stdout)
dt transform data.jsonl --preset=openai_chat -o out.jsonl
dt transform data.jsonl --preset=alpaca | dt head -

# 数据转换 - 配置文件模式
dt transform data.jsonl                    # 首次运行生成配置文件
# 编辑 .dt/data.py 后再次运行
dt transform data.jsonl --num=100          # 执行转换 (落到配置里的 output)

# Pipeline 执行（可复现的数据处理流程; step 即 CLI 命令名）
dt run pipeline.yaml
dt run pipeline.yaml --input=new_data.jsonl --output=result.jsonl
cat data.jsonl | dt run pipeline.yaml -i - | dt head -

# Token 统计
dt token-stats data.jsonl --field=messages --model=gpt-4
dt token-stats data.jsonl --field=messages[-1].content   # 统计最后一条消息
dt token-stats data.jsonl --field=text --detailed
dt token-stats data.jsonl --workers=4                    # 多进程加速（数据量大时自动启用）

# 数据对比
dt diff v1/train.jsonl v2/train.jsonl
dt diff a.jsonl b.jsonl --key=id
dt diff a.jsonl b.jsonl --key=meta.uuid    # 按嵌套字段匹配

# 数据清洗 (无 -o 写 stdout; -i 原地写回)
dt clean data.jsonl --drop-empty -o out.jsonl       # 删除任意空值记录
dt clean data.jsonl --drop-empty=text,answer -i     # 删除指定字段为空的记录, 原地写回
dt clean data.jsonl --drop-empty=meta.source        # 删除嵌套字段为空的记录 → stdout
dt clean data.jsonl --min-len=text:10               # text 字段最少 10 字符
dt clean data.jsonl --min-len=messages.#:2          # 至少 2 条消息
dt clean data.jsonl --max-len=messages[-1].content:500  # 最后一条消息最多 500 字符
dt clean data.jsonl --keep=question,answer          # 只保留这些字段 (更灵活的投影用 dt select)
dt clean data.jsonl --drop=metadata                 # 删除指定字段
dt clean data.jsonl --strip                         # 去除字符串首尾空白
dt clean data.jsonl --min-tokens=content:10          # 最少 10 tokens
dt clean data.jsonl --max-tokens=content:1000        # 最多 1000 tokens
dt clean data.jsonl --min-tokens=text:50 -m gpt-4    # 指定分词器

# 数据去重 (精确去重流式, 支持 stdin)
dt dedupe data.jsonl -i                         # 全量精确去重, 原地写回
dt dedupe data.jsonl --key=text -o out.jsonl    # 按字段精确去重
dt dedupe data.jsonl --key=meta.id              # 按嵌套字段去重 → stdout
dt dedupe data.jsonl --key=messages[0].content  # 按第一条消息内容去重
dt dedupe data.jsonl --key=text --similar=0.8   # 相似度去重

# 数据集切分
dt split data.jsonl --ratio=0.8 --seed=42           # 二分: train/test
dt split data.jsonl --ratio=0.7,0.15,0.15           # 三分: train/val/test
dt split data.jsonl --ratio=0.8 -o /tmp/output      # 指定输出目录
dt filter data.jsonl "x.ok" | dt split - -o out/ --name clean   # stdin 需给目录与前缀

# 训练框架导出
dt export data.jsonl --framework=llama-factory       # 导出到 LLaMA-Factory
dt export data.jsonl -f swift -o ./swift_out         # 导出到 ms-swift
dt export data.jsonl -f axolotl                      # 导出到 Axolotl
dt export data.jsonl -f llama-factory --check        # 仅检查兼容性

# 文件拼接 (无 -o 写 stdout; 至多一个 - 读 stdin)
dt concat a.jsonl b.jsonl -o merged.jsonl
dt concat a.jsonl.gz b.parquet | dt head -

# 数据统计
dt stats data.jsonl                                       # 快速模式
dt stats data.jsonl --schema                              # 嵌套 schema (类型/非空率/list 元素/低基数取值)
dt stats data.jsonl --full                                # 完整模式（含值分布）
dt stats data.jsonl --full --field=category               # 指定字段统计
dt stats data.jsonl --full --expand=tags                  # 展开 list 字段统计元素分布
dt stats data.jsonl --full --expand='messages[*].role'    # 展开嵌套 list 字段

# Agent Skill 安装
dt install-skill                              # 安装到 ~/.claude/skills/（默认）
dt install-skill --target codex               # 安装到 ~/.agents/skills/
dt skill-status --target codex                # 查看 Codex 安装状态

# 数据验证
dt validate data.jsonl --preset=openai_chat           # 使用预设 schema 验证
dt validate data.jsonl --preset=alpaca --verbose      # 详细输出
dt validate data.jsonl --preset=sharegpt --filter -o valid.jsonl  # 过滤出有效数据 (无 -o 则 stdout)
dt validate data.jsonl --preset=dpo --max-errors=100  # 限制错误输出数量
dt validate data.jsonl --preset=openai_chat --workers=4  # 多进程加速
```

`.jsonl.gz` / `.json.gz` 透明读写：所有命令直接接受（`cat x.jsonl.gz | dt filter - ...` 按魔数自动解压），输出文件带 `.gz` 后缀即压缩写出；其它格式不支持 `.gz`，会报用法错误。`-o -` 等同于写 stdout。

### 交互式数据浏览 (dt view)

`dt view <file>` 打开一个 master-detail 终端浏览器，专为查看训练数据设计：**表格区**扫视样本（派生列 turns/roles/first_user/chars/calls + 元数据），**详情区**按格式渲染当前行（对话气泡按 role 上色、代码块高亮；工具调用画成 `[assistant → 函数名]` + `⚙ 函数名 call_id` + 格式化参数，参数不是合法 JSON 标红；`reasoning_content` 思维链暗色显示；工具返回标 `[tool ← call_id]` 并格式化 JSON；dpo 对比；alpaca 分段；通用数据全展开）——无需逐层展开。默认左右布局，`z` 切上下。大文件走窗口化加载（`--cap`，默认 1 万行）。JSONL/NDJSON 普通打开只索引并加载首窗口，`]` 向后翻页时继续增量读取；总行数先显示为待定，完成计数或读到文件末尾后显示准确值。正数跳行只扫描到目标窗口；`G` 和负数跳行通过 Polars 快速统计准确总行数，再反向读取尾窗，保留绝对行号而不建立全文件偏移索引。计数及前后两端索引会复用，从末尾向前翻页也只补相邻窗口；全量搜索/筛选/排序/导出才补全中间缺失的索引。后台操作可按 `Esc` 取消。`--offset` 需要扫描目标行之前的内容。`dt view file -100` 不扫全文件即可从倒数 100 行开始；首次向前翻页、绝对跳转或全量操作时才建历史索引。行号列会随位数增加扩宽，窄终端也保留完整行号。JSONL 的列目录会扫描当前窗口全部记录，并在翻页或跳转时按首次出现顺序增量补充，不会为找列而预先解析全文件；通用格式的顶层对象/数组字段也会成为列。训练格式默认只展开前 8 个元数据列，其余字段保留在 `c` 列面板中。

**实时日志**：`dt view app.jsonl --follow` 从最新尾窗开始，每 0.5 秒批量接收新的完整行，并自动跟随 rename 轮转或可见的 truncate。正在写的未换行尾巴保持 pending，不会被误报成坏 JSON；已换行的非法 JSON 仍显示诊断占位行。光标上移后界面暂停自动滚动并累计新行，按 `G` 回到最新处继续追尾。`/` / `f` / `F` 首先扫描一个固定高水位，之后把相同约束增量应用于新行；`s` 对固定快照排序并暂停追尾，按 `r` 重置回到实时顺序。`--follow` 只支持可 seek 的 JSONL/NDJSON 文件；纯文本日志使用 `tl --tail FILE`。

| 按键 | 功能 |
|------|------|
| `↑/↓` `j/k` | 选行（详情联动） |
| `PgUp/PgDn` | 整页 · `d/u`(或 `Ctrl+d/u`) 半屏 |
| `g/G` | 整个浏览序列的首/末行；follow 中 `G` 恢复追尾 · `Tab` 切焦点 |
| `←/→` `h/l` | 水平滚动表格（`h/l` 每次 4 字符） |
| `s` | **全量排序**（输入列名，加 `-` 反向，如 `-chars`）：扫全文件，跨窗口有效 |
| `/` `f` | **全量搜索/筛选**：`/` 搜整条记录（含 assistant 回复，`re:` 前缀走正则）、`f` where——扫描整个文件（带进度，`Esc` 取消），命中聚成可分页子集；`r` 清除 |
| `F` / 点列头 | **列值勾选筛选**（Excel AutoFilter 式）：列出该列唯一值+频次，顶部搜索框按子串过滤候选值，默认全不选，勾选保留哪些 → 子集 |
| `n/N` `*` | 详情内逐字段导航（对话按条走 `msg0/msg1…`）；`*` 只在**含搜索命中**的字段间跳 |
| `w` | **导出**当前子集（或 `v` 选区）到文件，按扩展名定格式；同时写血缘 |
| `C` | 复制「复现当前视图」的 `dt view` 命令到剪贴板 |
| `S` | 列快照：某列的 `n·min·max·mean·非空率`（当前浏览序列；完整分布用 `dt stats`） |
| `c` | 选列（勾选面板，同时作用于表格列与详情字段；未选过列时默认只勾 `#`，选过则回显当前列） |
| 拖表头的 `│` | **改列宽**（Excel 式）：表头每列右侧（含末列）那道 `│` 就是分隔线，鼠标压上去变 `┃`（状态栏同时提示），按住左右拖即改宽；双击恢复自适应。列宽记在列名上，翻窗口 / 改筛选 / 换可见列后都还在 |
| `y` `v` | 复制当前样本 JSON · `v` 多选后 `y` 复制多条 |
| 详情区拖选 + `Ctrl+c` | **鼠标拖选任意文本**：按住左键拖出高亮（所见即所选，自动换行处不错位），`Ctrl+c` 复制走并清除选区；连击逐级放大：双击取词（id/字段值，连字符与下划线算词内）、三击整行、四击整个字段块、五击整屏详情，点一下或 `Esc` 清除。复制走 OSC52 + 本地 `wl-copy`/`xclip`/`xsel` 双通道（SSH/tmux 下也能进本机剪贴板）。表格区的拖拽另有语义（改列宽/选行），整条样本用 `y` |
| 拖两区分界 | **鼠标拖分界调两区大小**：表格与详情之间那两行边框（横排时是两列）即分界，鼠标压上去边框变亮、状态栏提示，按住拖到哪分界就到哪（按格连续，不是 5% 一跳）；双击恢复默认 65:35。键盘仍可用 `+/-` 走 5% 档 |
| `Enter` | 放大当前样本（`Esc` 返回）· `z` 左右/上下布局（默认左右） · `+/-` 调整分区 |
| `?` | 帮助 · `q` 退出 |

**搜索/筛选/排序都是全量的、且可叠加**：`/`、`f`、`F`、`s` 一律扫描整个文件而非仅当前窗口，得到的全局行号序列即新的浏览序列（翻窗口不失效），状态栏显示「命中 M/N (占比%)」。三类约束各占独立槽位：`/` 一个（新搜索覆盖旧的）、`f` 可反复叠加（多条之间是 **and**，用来表达无括号语法写不出的 `(a or b) and (c or d)`）、`F` 按列独立记「保留值集」故可反复调整/加回。**`r` 一键清空全部条件回到全量浏览**（筛选态的状态栏也会提示这个出口）。

**全量扫描是并行的**：JSONL/NDJSON 在索引就绪后按字节区间切片交给进程池（约束会序列化成 spec，子进程各自重建同一个谓词），实测 30 万行 / 440MB 的 `/` 搜索由 1.9s 降到 0.2s。`DTFLOW_VIEW_WORKERS=1` 可强制串行；非 JSONL（CSV/Parquet/stdin）本就全量在内存，走串行。两种情况连扫都省了：新条件只是把旧条件**收紧**（叠加一条 `f`、收窄某列值集）时只回读当前子集（子集小于全量 1/10 才划算，否则重扫更快）；`F` 勾选确定时直接用扫候选值那趟顺带记下的「值 → 行号表」拼出子集，不再扫第二遍。

`/` 搜的是**整条记录的每个值**（不只是表格列——表格列只是派生摘要，`first_user` 只是第一条用户消息，靠列搜会把 assistant 回复整个漏掉），命中处在表格与详情里画黄底，`*` 逐个跳过去。

**闭环到落地**：筛出来的子集用 `w` 导出成文件（`.jsonl` 流式写，几十万行不占内存；其他扩展名走 `save_data` 分派），导出时自动写血缘 sidecar，`dt history <out>` 能查到来源文件与当时的全部条件。`C` 把当前视图翻译回一条 `dt view ... --where=... --search=... --sort=...` 命令——粘回终端即还原（列值勾选翻译成 `str(x.get('col')) in (...)` 这类可回吃的表达式；表格里被截断过的值无法还原时会明说，完整条件以血缘为准）。

查看数据时的即时筛选归 view；完整分布统计（直方图/分位数/value_counts/token）归 `dt stats` / `dt token-stats`。

**坏行（非法 JSON）不会拦住浏览**：`dt view` 把它显示成一条占位行（`_parse_error` / `_raw_line` 两列），行号不错位，还能用 `/` 直接把坏行搜出来定位——语法坏掉的行恰恰是你打开浏览器要找的东西。其他命令按「会不会写出新文件」区别对待：`head`/`tail`/`sample` 跳过但在 stderr 报出第几行，`clean`/`transform` 等直接抛错（附行号与行内容），不静默丢数据。

> **`f` 筛选语法就是 Python 表达式**，当前行叫 `x`；表头上的**派生列名**（`chars`/`turns`/`roles`/`first_user`/`calls`…）可直接当变量用（值是原始类型：`turns` 是 int，`first_user` 是**全文**而非表格里那 160 字预览），其余字段走 `x.`：`turns>=6 and chars<2000`、`x.source=='alpaca'`、`len(x.messages)>=2`、`x.messages[-1].role=='assistant'`。`and`/`or`/`not`/括号随意。
>
> **按内容包含**：`'退款' in first_user`、`'get_weather' in calls`（调用过该函数的 agent 样本；`calls` 非空即带工具调用）、`'报错' in x.messages[0].content`、`any('关键词' in m.content for m in x.messages)`（搜整段对话）。`in` 区分大小写，不分大小写写 `'词' in first_user.lower()`；`/` 搜索与值面板搜索框则一律不分大小写。

格式自动检测：`openai_chat` / `sharegpt` / `dpo` / `alpaca` / `generic`（CSV 等表格数据全部列展示）。`--format` 可强制指定。

`dt head/sample/tail/slice` 的 `--pretty` 复用同一套渲染，做静态一次性预览（可管道时自动降级为 ndjson，agent 友好）。

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
| `sample` | `--by=` | `--by=meta.source`、`--by=messages.#` |
| `dedupe` | `--key=` | `--key=meta.id`、`--key=messages[0].content` |
| `clean` | `--drop-empty=` | `--drop-empty=meta.source` |
| `clean` | `--min-len=` | `--min-len=messages.#:2` |
| `clean` | `--max-len=` | `--max-len=messages[-1].content:500` |
| `clean` | `--min-tokens=` | `--min-tokens=content:10` |
| `clean` | `--max-tokens=` | `--max-tokens=content:1000` |
| `token-stats` | `--field=` | `--field=messages[-1].content` |
| `diff` | `--key=` | `--key=meta.uuid` |

字段路径用于 `--key` / `--by`（sample 分层）/ `--field` / `--drop-empty` / `--min-len` 等**指定一个字段**的参数；
**筛选与派生走表达式**（见下节），表达式里要用路径 DSL 可写 `get(x, "messages[*].role:join")`。

### 表达式语法

`filter` / `select` / `map` / `sort --by` / `group --by` / `join --on` / `sample --where` / `view --where` / pipeline 里的条件，
全部是 **Python 表达式**，当前行是 `x`（支持属性访问，`x.messages[-1].role`、`x.meta.source` 都能写；缺字段抛 AttributeError）。
命名空间里还有 `re` / `json` / `math` / `get`（旧字段路径 DSL）。

```bash
dt filter d.jsonl "x.score > 0.8 and 'wiki' in x.meta.source"
dt filter d.jsonl "len(x.messages) >= 2 and x.messages[-1].role == 'assistant'"
dt filter d.jsonl "any('退款' in m.content for m in x.messages)"
dt filter d.jsonl "re.search(r'\d{4}', x.text) and x.lang in ('zh', 'en')"
dt select d.jsonl "id,n=len(x.messages),roles=[m.role for m in x.messages]"
dt map    d.jsonl "x.text = x.text.strip(); x.messages.append({'role': 'assistant', 'content': x.a})"
```

求值失败的行（缺字段、`None > 0.5`）默认不中断，结束时在 stderr 汇总一次：`filter` 判为不匹配、`select` 该项置 `null`、`map` 该行原样保留、`sort` 排到末尾、`group --agg` 该项置 `null`（map/select/group 一进一出，不会静默少行）；`--strict` 则首个错误即退出码 1。
漏写 `x.` 的裸字段名（`score > 0.5`）在编译期就报退出码 2，不会每行 NameError 却 0 命中。语法错误退出码 2 并指出位置。不做沙箱：这是你本机 shell 里的工具，和 `dt transform` 执行 `.dt/*.py` 一样。
`--key/--by(sample)/--field` 这类字段路径参数写成 `x.meta.s` 会被拦下并提示去掉 `x.`。

从旧语法迁移（0.9 起旧的 `字段 运算符 值` 写法已删除）：

| 旧 | 新 |
|----|----|
| `category=tech` | `x.category=='tech'` |
| `content~=机器学习`（包含，不分大小写） | `'机器学习' in x.content.lower()` |
| `score>0.8` / `messages.#>=2` | `x.score>0.8` / `len(x.messages)>=2` |
| `messages[0].role=user` | `x.messages[0].role=='user'` |
| `messages[*].content:join~=词` | `any('词' in m.content for m in x.messages)` |
| view 里 `turns>=6 and chars<2000` | 不变；`source==alpaca` → `x.source=='alpaca'`；`first_user~=退款` → `'退款' in first_user` |
| pipeline `condition: "len(text) > 10"` / `field: text` | `expr: "len(x.text) > 10"` / `expr: "x.text"` |
| `dt clean f.jsonl --strip`（默认覆盖原文件） | `dt clean f.jsonl --strip -i`；不加 `-i`/`-o` 输出到 stdout |

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

用 YAML 把一串命令固化下来，可复现执行。**step 的 `type` 就是 CLI 命令名，参数就是 CLI 选项名**（下划线形式），一套语法两处用：

```yaml
# pipeline.yaml
version: "1.0"
seed: 42
input: raw_data.jsonl
output: processed.jsonl

steps:
  - type: filter
    expr: "x.score > 0.5 and len(x.text) > 10"
  - type: select
    fields: "id,text,n=len(x.messages)"
  - type: clean
    strip: true
    drop_empty: text
    min_len: "text:10"
  - type: dedupe
    key: text
  - type: transform
    preset: openai_chat
    params: {user_field: q, assistant_field: a}
  - type: split            # 只能是最后一步: 按 output 派生 processed_train.jsonl / processed_test.jsonl
    ratio: 0.9
    seed: 42
```

| 步骤 | 参数（= CLI 选项） | 说明 |
|------|------|------|
| `filter` | `expr`, `strict` | Python 表达式筛选 |
| `select` | `fields`, `strict` | 投影 / 重命名 / 派生 |
| `map` | `code`, `strict` | 原地修改 |
| `explode` | `field`, `as`, `index_as` | list 展开成多行 |
| `sort` | `by`, `desc` | 排序（全量） |
| `shuffle` | `seed` | 打乱（全量） |
| `group` | `by`, `agg` | 分组计数 / 聚合 |
| `join` | `right`, `on` 或 `left_on`+`right_on`, `inner`, `prefix` | 键连接 |
| `dedupe` | `key`, `similar` | 精确 / 相似度去重 |
| `sample` / `head` / `tail` | `num`, `seed` | 采样 / 取前后 N 条 |
| `clean` | `strip`, `drop_empty`, `min_len`, `max_len`, `keep`, `drop`, `rename`, `promote`, `add_field`, `fill`, `reorder`, `min_tokens`, `max_tokens`, `model` | 与 `dt clean` 一致 |
| `transform` | `preset` + `params`，或 `config` | 预设 / `.dt/*.py` 配置 |
| `split` | `ratio`, `seed` | 终态步骤，输出多个文件 |

执行载体是流式的：能惰性的步骤不落内存。`dt run pipeline.yaml --dry-run` 校验配置（含表达式语法）并打印步骤链。

```bash
dt run pipeline.yaml
dt run pipeline.yaml --input=new_data.jsonl --output=result.jsonl
cat data.jsonl | dt run pipeline.yaml -i - | dt head -     # 无 output 时数据走 stdout
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

专为超大文件设计的流式处理接口，内存占用 O(1)，支持 JSONL/NDJSON、CSV/TSV、Parquet、Arrow 格式：

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
- **多格式支持**：JSONL/NDJSON、CSV/TSV、Parquet、Arrow 均支持流式处理
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
