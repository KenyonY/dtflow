# dtflow 进化路线图

> 版本：v0.3.0 → v1.0
> 更新日期：2025-12-20

## 现状总结

**当前能力**：
- 链式 API：`dt.load().filter().transform().save()`
- CLI 命令：transform, sample (--by 分层采样), stats (top N 分布), dedupe, concat, clean
- 格式支持：JSONL, JSON, CSV, Excel, Parquet, Arrow, Feather
- 训练框架转换：LLaMA-Factory, ms-swift, Axolotl 等 12 种格式
- 性能优化：蓄水池采样、orjson、并行处理

**核心模块**：
- `core.py` - DataTransformer 核心类
- `presets.py` - 5 个预设转换模板
- `tokenizers.py` - Token 统计和过滤
- `converters.py` - 12 个格式转换器
- `storage/io.py` - 8 种文件格式支持

---

## 进化方向

### 方向一：大文件流式处理

**痛点**：当前实现全量加载内存，几十 GB 数据会 OOM。

**期望 API**：
```python
# 惰性加载，流式处理
dt.load_stream("huge_100gb.jsonl")
  .filter(lambda x: len(x.text) > 10)
  .transform(openai_chat())
  .save("output.jsonl")  # 流式写入

# 分片处理
dt.load_sharded("data_*.jsonl")
  .process_shards(func=transform_func, workers=4)
  .save_sharded("output/", shard_size=100000)
```

**关键能力**：
| 能力 | 说明 | 实现思路 |
|------|------|----------|
| 惰性迭代 | 按需读取，不全量加载 | generator + ijson |
| 流式写入 | 边处理边写入 | 缓冲写入 |
| 分片处理 | 大文件自动分片 | glob + 并行处理 |

**优先级**：⭐⭐⭐⭐⭐（规模化刚需）

---

### 方向二：数据血缘与版本管理

**痛点**：数据处理后无法追溯来源，出问题难以定位。

**期望 API**：
```python
# 保存时记录血缘
dt.load("v1/train.jsonl")
  .filter(lambda x: x.score > 0.5)
  .transform(openai_chat())
  .save("v2/train.jsonl", lineage=True)

# 版本对比
dt.diff("v1/train.jsonl", "v2/train.jsonl").report()

# 数据溯源
dt.trace("v2/train.jsonl", item_id=123)

# CLI
dt diff v1/train.jsonl v2/train.jsonl
dt history v2/train.jsonl
```

**关键能力**：
| 能力 | 说明 | 实现思路 |
|------|------|----------|
| 血缘记录 | 记录数据来源和转换链 | sidecar 元数据文件 |
| 版本对比 | diff 两个版本的数据集 | 哈希 + 增量比较 |
| 数据溯源 | 追踪单条数据的来源 | 唯一 ID + 血缘图 |

**优先级**：⭐⭐⭐⭐⭐（合规审计、问题定位）

---

### 方向三：可复现性 / Pipeline 导出

**痛点**：数据处理流程无法复用，团队协作困难。

**期望 API**：
```python
# Pipeline 导出为配置
pipeline = dt.load("raw.jsonl")
  .filter(lambda x: x.score > 0.5)
  .transform(openai_chat())
  .dedupe("text")

pipeline.export_config("pipeline.yaml")

# 从配置复现
dt.run_pipeline("pipeline.yaml", input="new_raw.jsonl", output="result.jsonl")

# CLI
dt run pipeline.yaml --input new_data.jsonl --output result.jsonl
```

**配置文件示例**：
```yaml
version: "1.0"
seed: 42
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

**优先级**：⭐⭐⭐⭐（团队协作、实验追踪）

---

### 方向四：CLI 交互式数据探索

**痛点**：当前 CLI 命令分散，数据探索不便。

**期望命令**：
```bash
dt explore data.jsonl          # 交互式探索（类似 datasette）
dt profile data.jsonl --full   # 完整数据剖析报告
dt diff a.jsonl b.jsonl        # 数据集对比
dt viz data.jsonl --field=token_count  # 数据分布可视化
```

**关键能力**：
| 能力 | 说明 |
|------|------|
| 交互式探索 | TUI 界面浏览数据 |
| 数据剖析 | 自动生成完整报告 |
| 可视化 | 终端内图表展示 |

**优先级**：⭐⭐⭐⭐

---

### 方向五：数据质量控制

**痛点**：缺少数据结构验证和质量检测。

**期望 API**：
```python
dt.load("data.jsonl")
  .validate(schema=SFTSchema)      # Schema 验证
  .detect_quality(                 # 质量检测
      pii_detection=True,
      language_mix=True,
  )
  .filter_quality(min_score=0.7)
  .report()
```

**关键能力**：
| 能力 | 说明 | 实现思路 |
|------|------|----------|
| Schema 验证 | 数据结构验证 | pydantic |
| PII 检测 | 敏感信息识别 | 正则 + presidio |
| 语言检测 | 中英混杂识别 | fasttext |

**优先级**：⭐⭐⭐⭐

---

### 方向六：数据平衡

**痛点**：训练数据类别不平衡影响模型效果。

**期望 API**：
```python
dt.load("data.jsonl")
  .balance("category", strategy="oversample")  # 过采样
  .save("balanced.jsonl")

dt.load("data.jsonl")
  .balance("category", strategy="undersample", target_ratio=0.5)
```

**关键能力**：
| 能力 | 说明 |
|------|------|
| 过采样 | 复制少数类样本 |
| 欠采样 | 减少多数类样本 |
| 目标比例 | 指定平衡程度 |

**优先级**：⭐⭐⭐

---

### 方向七：训练框架深度集成

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

**关键能力**：
| 能力 | 说明 |
|------|------|
| 配置生成 | 自动生成训练框架配置文件 |
| 序列打包 | packing 优化训练效率 |
| 数据划分 | 训练/验证集自动划分 |

**优先级**：⭐⭐⭐

---

## 优先级总览

| 方向 | 优先级 | 理由 |
|------|--------|------|
| 大文件流式处理 | ⭐⭐⭐⭐⭐ | 规模化刚需，解决 OOM |
| 数据血缘/版本 | ⭐⭐⭐⭐⭐ | 合规审计、问题定位 |
| 可复现性/Pipeline | ⭐⭐⭐⭐ | 团队协作、实验追踪 |
| CLI 交互式探索 | ⭐⭐⭐⭐ | 用户体验 |
| 数据质量控制 | ⭐⭐⭐⭐ | 差异化能力 |
| 数据平衡 | ⭐⭐⭐ | 新功能，但相对简单 |
| 训练框架集成 | ⭐⭐⭐ | 已有基础，增强 |

---

## 版本规划

### v0.4.0 - 大文件流式处理
- [ ] `load_stream()` 惰性加载
- [ ] 流式 filter/transform
- [ ] 流式 save
- [ ] 分片处理 `load_sharded()` / `save_sharded()`

### v0.5.0 - 数据血缘与版本
- [ ] 血缘元数据记录
- [ ] `dt.diff()` 版本对比
- [ ] `dt.trace()` 数据溯源
- [ ] CLI: `dt diff`, `dt history`

### v0.6.0 - 可复现性
- [ ] Pipeline 配置导出 (YAML)
- [ ] `dt.run_pipeline()` 配置执行
- [ ] CLI: `dt run`
- [ ] 全局随机种子管理

### v0.7.0 - CLI 增强
- [ ] `dt explore` 交互式探索
- [ ] `dt profile` 数据剖析
- [ ] `dt viz` 可视化

### v0.8.0 - 数据质量
- [ ] Schema 验证（pydantic）
- [ ] PII 检测
- [ ] 质量报告生成

### v0.9.0 - 数据平衡 & 训练集成
- [ ] `balance()` 过采样/欠采样
- [ ] `prepare_for()` 一站式导出
- [ ] 序列打包

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
