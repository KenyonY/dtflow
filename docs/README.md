# dtflow 文档

> 简洁的数据格式转换工具，专为机器学习训练数据设计。

## 文档目录

```
docs/
├── README.md          # 本文档（主入口）
├── quickstart.md      # 快速入门指南
└── images/view/       # README 里 dt view 的截图与 GIF（由 scripts/view_showcase.py 生成）
```

## 快速链接

- [快速入门](./quickstart.md) - 30 秒上手 dtflow
- [README](../README.md) - 项目主文档和使用说明
- [dt view 展示素材](../scripts/view_showcase.py) - 重新生成截图/GIF：`python scripts/view_showcase.py`（headless 驱动真实 TUI，需 playwright + ffmpeg）

## 核心模块

| 模块 | 文件 | 功能 |
|------|------|------|
| **DataTransformer** | `core.py` | 核心数据处理类，链式 API |
| **预设模板** | `presets.py` | openai_chat, alpaca, sharegpt, dpo_pair, simple_qa |
| **Token 统计** | `tokenizers.py` | tiktoken/transformers 后端，messages 统计 |
| **格式转换** | `converters.py` | LLaMA-Factory, ms-swift, Axolotl, HuggingFace, OpenAI Batch |
| **流式处理** | `streaming.py` | 大文件惰性处理，O(1) 内存，支持 JSONL/CSV/Parquet/Arrow |
| **表达式引擎** | `expr.py` | 所有 --where / select / map / sort / group / join 共用的 Python 表达式求值（当前行 `x`） |
| **数据原语** | `ops.py` | filter/select/map/explode/sort/shuffle/group/join/clean/transform/split 的库层实现，CLI 与 pipeline 共用 |
| **管道层** | `cli/pipe.py` | FILE=`-` 读 stdin、无 `-o` 写 stdout、原地写回、TTY 预览截断 |
| **Pipeline** | `pipeline.py` | YAML 配置的可复现数据处理流程（step = CLI 命令名，参数 = 选项名） |
| **数据血缘** | `lineage.py` | 操作追踪与历史记录 |
| **字段路径** | `utils/field_path.py` | 嵌套字段访问语法（`a.b`、`a[0].b`、`a.#`、`a[*].b`） |
| **CLI 统计** | `cli/stats.py` | stats 命令，支持 --field 字段过滤、--expand list 展开统计 |
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
    expr: "x.score > 0.5"
  - type: select
    fields: "id,text,n=len(x.messages)"
  - type: transform
    preset: openai_chat
```

```bash
dt run pipeline.yaml
```

### 管道拼接（CLI）

```bash
dt filter d.jsonl "x.score>0.5 and len(x.messages)>=2" \
  | dt select - "id,n=len(x.messages)" \
  | dt sort - --by x.n --desc \
  | dt head - 5
dt stats d.jsonl --schema            # 先看嵌套 schema 再写表达式
dt group d.jsonl --by x.meta.source  # 分布
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
