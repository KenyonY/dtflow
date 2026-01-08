# dtflow 进化路线图

> 版本：v0.5.0 → v1.0
> 更新日期：2026-01-08

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

### 方向五：数据质量控制 ⭐⭐⭐⭐⭐ 【P0 优先级】

**痛点**：缺少数据结构验证和质量检测，导致训练失败或模型效果差。

**期望 API**：
```python
from dtflow import Schema, Field

# 1. Schema 验证
schema = Schema({
    "messages": Field(type="list", required=True, min_length=1),
    "messages[*].role": Field(type="str", choices=["user", "assistant", "system"]),
    "messages[*].content": Field(type="str", min_length=1),
    "score": Field(type="float", min=0, max=1),
})

dt.load("data.jsonl")
  .validate_schema(schema)  # 返回验证结果
  .save("valid.jsonl")

# 2. PII 检测
dt.load("data.jsonl")
  .detect_pii(fields=["content"])      # 检测敏感信息
  .mask_pii(fields=["content"])        # 脱敏处理
  .save("safe.jsonl")

# 3. 数据质量评分
report = dt.quality_report()
# {
#   "total": 1000,
#   "valid": 950,
#   "invalid": 50,
#   "completeness": 0.95,    # 完整性
#   "uniqueness": 0.88,      # 唯一性（去重后比例）
#   "field_stats": {...}
# }

# 4. 异常值检测
anomalies = dt.detect_anomalies(field="token_count", method="zscore", threshold=3)
```

**关键能力**：
| 能力 | 说明 | 状态 | 优先级 |
|------|------|------|--------|
| Schema 验证 | 数据结构验证（类型、范围、必填） | ✅ | P0 |
| PII 检测 | 敏感信息识别（邮箱、电话、身份证） | 🔲 | P0 |
| 数据质量评分 | 完整性、一致性、唯一性 | 🔲 | P1 |
| 异常值检测 | 统计异常（zscore/IQR） | 🔲 | P1 |

**实现思路**：
- Schema 验证：轻量级自研（不依赖 pydantic，保持简洁）
- PII 检测：正则表达式 + 可选 presidio 集成
- 质量评分：基于 stats() 扩展

---

### 方向六：数据平衡 ⭐⭐⭐⭐ 【P1 优先级】

**痛点**：训练数据类别不平衡影响模型效果。

**期望 API**：
```python
# 1. 类别平衡
dt.load("data.jsonl")
  .balance("category", strategy="oversample")   # 过采样（复制少数类）
  .save("balanced.jsonl")

dt.load("data.jsonl")
  .balance("category", strategy="undersample")  # 欠采样（减少多数类）
  .save("balanced.jsonl")

# 2. 长度平衡
dt.load("data.jsonl")
  .balance_length("content", bins=[0, 100, 500, 2000, float("inf")])
  .save("balanced.jsonl")

# 3. 分布可视化
dt.plot_distribution("category")           # 类别分布直方图
dt.plot_length_distribution("content")     # 长度分布图
```

**关键能力**：
| 能力 | 说明 | 状态 | 优先级 |
|------|------|------|--------|
| 类别过采样 | 复制少数类样本 | 🔲 | P1 |
| 类别欠采样 | 减少多数类样本 | 🔲 | P1 |
| 长度平衡 | 按长度区间平衡 | 🔲 | P2 |
| 分布可视化 | 直方图展示 | 🔲 | P2 |

---

### 方向七：数据增强 ⭐⭐⭐⭐ 【P2 优先级】

**痛点**：小数据集需要扩充，提高模型泛化能力。

**期望 API**：
```python
# 1. 文本增强
dt.load("data.jsonl")
  .augment("content", method="synonym_replace", ratio=0.1)  # 同义词替换
  .augment("content", method="random_swap", ratio=0.1)      # 随机交换
  .save("augmented.jsonl")

# 2. 基于 LLM 的增强（需要 maque 库）
dt.load("data.jsonl")
  .augment("content", method="paraphrase", model="qwen2.5")  # 改写
  .augment("content", method="backtranslation", lang="en")   # 回译
  .save("augmented.jsonl")

# 3. 对话增强
dt.load("data.jsonl")
  .augment_conversation(method="role_swap")     # user/assistant 互换
  .augment_conversation(method="truncate")      # 随机截断对话
  .save("augmented.jsonl")
```

**关键能力**：
| 能力 | 说明 | 状态 | 优先级 |
|------|------|------|--------|
| 同义词替换 | 基于词表的增强 | 🔲 | P2 |
| 随机交换/删除 | 简单的数据扰动 | 🔲 | P2 |
| LLM 改写 | 使用 maque 调用 LLM | 🔲 | P3 |
| 对话增强 | 多轮对话特化 | 🔲 | P3 |

---

### 方向八：训练框架深度集成 ⭐⭐⭐ 【P2 优先级】✅ 已完成

**实现**：`dtflow/framework.py`

**API 用法**：
```python
from dtflow import DataTransformer

dt = DataTransformer.load("data.jsonl")

# 1. 兼容性检查
result = dt.check_compatibility("llama-factory")
print(result)  # ✅ 兼容 - LLaMA-Factory (openai_chat)

# 2. 一键导出
dt.export_for("llama-factory", output_dir="./llama_ready/")
# 生成:
# - ./llama_ready/custom_dataset.json
# - ./llama_ready/dataset_info.json
# - ./llama_ready/train_args.yaml

# 3. 导出到 ms-swift
dt.export_for("swift", "./swift_ready/")

# 4. 导出到 Axolotl
dt.export_for("axolotl", "./axolotl_ready/")
```

**支持的框架**：
| 框架 | 导出内容 | 状态 |
|------|---------|------|
| LLaMA-Factory | data.json + dataset_info.json + train_args.yaml | ✅ |
| ms-swift | data.jsonl + train.sh | ✅ |
| Axolotl | data.jsonl + config.yaml | ✅ |

**关键能力**：
| 能力 | 说明 | 状态 |
|------|------|------|
| 一键导出 | 数据 + 配置文件 | ✅ |
| 兼容性检查 | 验证数据格式 | ✅ |
| 格式自动检测 | openai_chat/alpaca/sharegpt/dpo | ✅ |
| 配置推荐 | 自动生成训练参数模板 | ✅ |

---

## 优先级总览

| 方向 | 状态 | 优先级 | 说明 |
|------|------|--------|------|
| 可复现性/Pipeline | ✅ 完成 | - | `pipeline.py`，`dt run` |
| 数据血缘/版本 | ✅ 完成 | - | `lineage.py`，`dt history` |
| 大文件流式处理 | ✅ 完成 | - | `streaming.py`，O(1) 内存 |
| CLI 增强 | ✅ 完成 | - | `token-stats`, `diff`, `run`, `history` |
| **数据质量控制** | 🚧 开发中 | **P0** | Schema 验证 ✅、PII 检测 🔲 |
| **训练框架集成** | ✅ 完成 | P2 | `export_for()`, `check_compatibility()` |
| 数据平衡 | 🔲 待开发 | P1 | 过采样/欠采样 |
| 数据增强 | 🔲 待开发 | P2 | 文本增强、对话增强 |

---

## 版本规划

### v0.4.0 - 可复现性 ✅
- [x] Pipeline YAML 配置格式设计
- [x] `dt run pipeline.yaml` 命令
- [x] 全局随机种子管理
- [x] 血缘元数据记录（.lineage.json sidecar 文件）
- [x] `dt history` 命令
- [x] 惰性 filter/transform（StreamingTransformer + generator）
- [x] `load_sharded()` / `save_sharded()`
- [x] `dt token-stats` 命令
- [x] `dt diff` 数据集对比

### v0.5.0 - 数据质量控制 + 框架集成（当前开发版本）🚧
- [x] Schema 验证（轻量级自研，支持字段路径语法）
- [x] `dt validate` CLI 命令
- [x] `check_compatibility()` 兼容性检查
- [x] `export_for()` 一键导出（LLaMA-Factory/ms-swift/Axolotl）
- [ ] PII 检测（正则 + 可选 presidio）
- [ ] 质量报告生成

### v0.6.0 - 数据平衡
- [ ] `balance()` 类别过采样/欠采样
- [ ] `balance_length()` 长度平衡
- [ ] 分布可视化

### v0.7.0 - 数据增强
- [ ] 文本增强（同义词替换、随机扰动）
- [ ] 对话增强（截断、角色交换）
- [ ] LLM 增强（maque 集成）

### v1.0.0 - 生产就绪
- [ ] 完整文档和使用案例
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
