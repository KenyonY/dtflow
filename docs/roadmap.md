# dtflow 进化路线图

> 版本：v0.7.0 → v1.0
> 更新日期：2025-12-20

## 现状总结

**当前能力**：
- 链式 API：`dt.load().filter().transform().save()`
- 流式处理：`load_stream().filter().transform().save()` - O(1) 内存
- Pipeline：YAML 配置的可复现数据处理流程
- 数据血缘：操作追踪与历史记录
- CLI 命令：transform, sample, stats, dedupe, concat, clean, run, token-stats, diff, history
- 格式支持：JSONL, JSON, CSV, Excel, Parquet, Arrow, Feather, FlaxKV
- 训练框架转换：LLaMA-Factory, ms-swift, Axolotl 等 12 种格式
- 性能优化：蓄水池采样、流式处理、orjson、并行处理、Polars I/O（比 Pandas 快 3x）

**核心模块**：
- `core.py` - DataTransformer 核心类（含血缘追踪）
- `streaming.py` - 流式处理（惰性 filter/transform，分片加载保存）
- `pipeline.py` - Pipeline YAML 执行引擎
- `lineage.py` - 数据血缘追踪
- `presets.py` - 5 个预设转换模板
- `tokenizers.py` - Token 统计和过滤（tiktoken/transformers）
- `converters.py` - 12 个格式转换器
- `storage/io.py` - 8 种文件格式 + 流式采样（Polars 引擎）

---

## 进化方向

### 方向一：可复现性 / Pipeline 导出 ✅ 已完成

**实现**：`dtflow/pipeline.py`

```python
# CLI 执行 Pipeline
# dt run pipeline.yaml --input new_data.jsonl --output result.jsonl

# Python API
from dtflow.pipeline import run_pipeline
result = run_pipeline("pipeline.yaml", input_file="data.jsonl")
```

**配置文件示例**：
```yaml
version: "1.0"
seed: 42
input: raw.jsonl
output: processed.jsonl
steps:
  - type: filter
    condition: "score > 0.5"
  - type: transform
    preset: openai_chat
    params:
      user_field: q
      assistant_field: a
  - type: dedupe
    key: text
```

支持步骤：filter, transform, dedupe, sample, head, tail, shuffle, split

---

### 方向二：数据血缘与版本管理 ✅ 已完成

**实现**：`dtflow/lineage.py`

```python
# 启用血缘追踪
dt = DataTransformer.load("raw.jsonl", track_lineage=True)
result = dt.filter(...).transform(...).dedupe("text")
result.save("output.jsonl", lineage=True)
# 自动生成 output.jsonl.lineage.json

# CLI 查看历史
# dt history output.jsonl
# dt diff v1/train.jsonl v2/train.jsonl
```

**已实现能力**：
| 能力 | 状态 | 说明 |
|------|------|------|
| 血缘记录 | ✅ | sidecar `.lineage.json` 文件 |
| 版本对比 | ✅ | `dt diff` 命令 |
| 历史查看 | ✅ | `dt history` 命令 |
| 数据溯源 | 🔲 | 可选，单条数据追踪 |

---

### 方向三：大文件流式处理 ✅ 已完成

**实现**：`dtflow/streaming.py`

```python
from dtflow import load_stream, load_sharded

# 惰性加载，流式处理（O(1) 内存）
# 支持 JSONL、CSV、Parquet、Arrow 格式
(load_stream("huge_100gb.jsonl")
    .filter(lambda x: x["score"] > 0.5)
    .transform(lambda x: {"text": x["content"]})
    .save("output.jsonl"))

# 跨格式转换
(load_stream("data.csv")
    .filter(lambda x: x["score"] > 0.5)
    .save("output.parquet"))

# 分片加载（支持多格式）
(load_sharded("data_*.parquet")
    .filter(lambda x: len(x["text"]) > 10)
    .save("merged.jsonl"))

# 分片保存
(load_stream("huge.jsonl")
    .save_sharded("output/", shard_size=100000))
# 生成: output/part-00000.jsonl, output/part-00001.jsonl, ...

# 批次处理
for batch in load_stream("data.jsonl").batch(1000):
    process_batch(batch)
```

**已实现能力**：
| 能力 | 状态 | 说明 |
|------|------|------|
| 惰性 filter/transform | ✅ | 基于 generator，延迟执行 |
| 多格式支持 | ✅ | JSONL、CSV、Parquet、Arrow |
| 分片加载 | ✅ | `load_sharded()` 支持 glob + 多格式 |
| 分片保存 | ✅ | `save_sharded()` 自动分片 |
| 批次迭代 | ✅ | `batch()` 分批处理 |
| 跨格式转换 | ✅ | CSV→Parquet、Parquet→JSONL 等 |

---

### 方向四：CLI 增强 ✅ 已完成

**已实现命令**：
```bash
# Token 统计
dt token-stats data.jsonl --field=messages --model=gpt-4
dt token-stats data.jsonl --field=text --detailed

# 数据集对比
dt diff v1/train.jsonl v2/train.jsonl
dt diff a.jsonl b.jsonl --key=id

# Pipeline 执行
dt run pipeline.yaml
dt run pipeline.yaml --input=new_data.jsonl

# 血缘历史
dt history output.jsonl
dt history output.jsonl --json
```

**已实现能力**：
| 能力 | 状态 | 说明 |
|------|------|------|
| token-stats | ✅ | 支持 messages 和普通字段 |
| diff | ✅ | 数据集对比，支持按 key 对齐 |
| run | ✅ | Pipeline YAML 执行 |
| history | ✅ | 血缘历史查看 |
| explore | 🔲 | 可选，交互式 TUI |

---

### 方向五：数据质量控制 ⭐⭐⭐⭐

**痛点**：缺少数据结构验证和质量检测。

**期望 API**：
```python
dt.load("data.jsonl")
  .validate(schema=SFTSchema)      # Schema 验证
  .detect_quality(                 # 质量检测
      pii_detection=True,
  )
  .filter_quality(min_score=0.7)
  .report()
```

**关键能力**：
| 能力 | 说明 | 实现思路 |
|------|------|----------|
| Schema 验证 | 数据结构验证 | pydantic |
| PII 检测 | 敏感信息识别 | 正则 + presidio |

**优先级**：⭐⭐⭐⭐

---

### 方向六：数据平衡 ⭐⭐⭐

**痛点**：训练数据类别不平衡影响模型效果。

**期望 API**：
```python
dt.load("data.jsonl")
  .balance("category", strategy="oversample")  # 过采样
  .save("balanced.jsonl")

dt.load("data.jsonl")
  .balance("category", strategy="undersample", target_ratio=0.5)
```

**优先级**：⭐⭐⭐

---

### 方向七：训练框架深度集成 ⭐⭐⭐

**现状**：`converters.py` 已支持格式转换，但缺少一站式导出。

**期望 API**：
```python
dt.load("raw_data.jsonl")
  .prepare_for("llama-factory",
      template="qwen2",
      max_length=4096,
      pack_sequences=True,
      train_split=0.9,
  )
  .export("./llama_factory_dataset/")  # 生成配置 + 数据
```

**优先级**：⭐⭐⭐

---

## 优先级总览

| 方向 | 状态 | 说明 |
|------|------|------|
| 可复现性/Pipeline | ✅ 完成 | `pipeline.py`，`dt run` |
| 数据血缘/版本 | ✅ 完成 | `lineage.py`，`dt history` |
| 大文件流式处理 | ✅ 完成 | `streaming.py`，O(1) 内存 |
| CLI 增强 | ✅ 完成 | `token-stats`, `diff`, `run`, `history` |
| 数据质量控制 | 🔲 待开发 | Schema 验证、PII 检测 |
| 数据平衡 | 🔲 待开发 | 过采样/欠采样 |
| 训练框架集成 | 🔲 待开发 | 一站式导出 |

---

## 版本规划

### v0.4.0 - 可复现性 ✅
- [x] Pipeline YAML 配置格式设计
- [x] `dt run pipeline.yaml` 命令
- [x] 全局随机种子管理

### v0.5.0 - CLI 增强 ✅
- [x] `dt token-stats` 命令
- [x] `dt diff` 数据集对比
- [ ] `dt explore` 交互式探索（可选）

### v0.6.0 - 数据血缘 ✅
- [x] 血缘元数据记录（.lineage.json sidecar 文件）
- [x] `dt history` 命令
- [ ] `dt trace` 数据溯源（可选）

### v0.7.0 - 大文件流式处理 ✅
- [x] 惰性 filter/transform（StreamingTransformer + generator）
- [x] `load_sharded()` / `save_sharded()`
- [x] `process_shards()` 分片处理函数

### v0.8.0 - 数据质量
- [ ] Schema 验证（pydantic）
- [ ] PII 检测
- [ ] 质量报告生成

### v0.9.0 - 数据平衡 & 训练集成
- [ ] `balance()` 过采样/欠采样
- [ ] `prepare_for()` 一站式导出

### v1.0.0 - 生产就绪
- [ ] 完整文档
- [ ] 性能基准测试
- [ ] 稳定 API

---

## 已删除的方向

以下功能因与现有实现重复或可用外部工具替代而删除：

| 功能 | 原因 |
|------|------|
| 数据分布分析 | `dt stats --top=N` 已覆盖 |
| 分层采样 | `dt sample --by` 已覆盖 |
| 数据混合 | 过于简单，concat 足够 |
| LLM 评分/增强 | 使用 maque 库 |
| 异步 Pipeline | 使用 maque 库 |
