---
name: dtflow
description: >
  处理结构化数据文件 (JSONL/JSON/CSV/Parquet/Arrow/TSV) 时使用此 skill。
  提供 CLI 工具 `dt` 和 Python API `DataTransformer`。
  典型场景：数据预览/统计/清洗/去重/Schema 验证、格式转换
  (openai_chat/alpaca/sharegpt/dpo)、数据集切分、导出到训练框架
  (llama-factory/swift/axolotl)、Token 统计、大文件流式处理。
  不涉及 LLM 调用（LLM 调用用 flexllm）。
---

# dtflow - 数据转换工具

## 何时使用

- **使用 dtflow** —— 结构化数据文件的读/写、统计、清洗、转换、去重、切分
- **使用 flexllm** —— 需要调用大模型生成/评估
- **用 Python 直写** —— 纯业务脚本、一次性处理、无格式转换需求

## Agent 探索入口

**永远先问 CLI 自己**，不要凭记忆猜参数：

```bash
dt --help                # 命令列表 + 全局选项
dt schema                # 机器可读命令树 (JSON)，适合 jq 解析
dt schema <cmd>          # 单个命令完整 schema
dt <cmd> --help          # 具体命令的参数/示例/退出码
```

`dt schema | jq '.commands[] | .name'` 一眼看完所有命令名。

## 输出契约（Agent 必读）

| 通道 | 承载 | 场景 |
|------|------|------|
| **stdout** | 数据 (JSON/NDJSON/CSV/Table) | 被管道消费 |
| **stderr** | 进度/警告/错误/动作摘要 | 人类阅读或日志 |
| **退出码** | 任务状态 | **必须** 检查 |

**退出码约定：**
- `0` 成功
- `1` 一般错误（读写失败、运行时错误）
- `2` 参数错误（未知预设、非法取值、必填缺失）
- `3` 资源不存在（文件找不到）
- `4` 权限拒绝
- `5` 冲突
- `10` **dry-run 预演成功**（仍然是"成功"，但没有真正写出）

**Agent 规则：** 判断成败 **只看退出码**，不要解析文本输出。

## 输出格式

- **TTY** → 默认 `table`（彩色表格 + panel 到 stderr）
- **非 TTY**（管道/重定向） → 默认 `ndjson`（记录类） 或 `json`（报告类）
- 任意时候可用 `dt --format=json <cmd>` 强制指定

## 副作用命令都有 --dry-run

修改数据前先预演，所有副作用命令都支持：

```
clean / transform / concat / dedupe / split / export / run / eval
```

Dry-run 会：
1. 完整执行所有读/过滤/计算
2. **不写出**到 output
3. 输出结构化 `action` 摘要到 stdout（`action`, `input_rows`, `output_rows`, `removed_rows`, …）
4. **退出码 10**（区别于 0 的实际执行成功）

Agent 工作流：`dry-run → 看摘要 → 确认无误 → 去掉 --dry-run 再执行`。

## 典型思维模型

**从"未知数据"到"训练文件"的路径：**

1. **探结构** — `dt stats data.jsonl` 或 `dt head data.jsonl`，搞清字段类型和嵌套结构
2. **探内容** — `dt stats --full --field=<key>` 看值分布；必要时用 `dt sample --where=...` 抽样
3. **小样本跑通** — 先在 100 条上验证转换逻辑，避免大文件反复
4. **dry-run 预演** — `... --dry-run`，确认影响范围
5. **大规模执行** — 去掉 `--dry-run`，看最终退出码

**遇到字段嵌套问题：** dtflow 的字段路径 DSL 在所有命令中语义一致，见下表。

## 字段路径语法

| 语法 | 含义 | 示例 |
|------|------|------|
| `a.b.c` | 嵌套字段 | `meta.source` |
| `a[0].b` | 索引（支持负索引） | `messages[0].role`, `messages[-1].content` |
| `a.#` | 数组长度 | `messages.#` |
| `a[*].b` | 展开所有元素 | `messages[*].role` |

用于：`--key`、`--by`、`--field`、`--drop-empty`、`--where` 等等。

## Python API 何时用

CLI 覆盖 80% 场景。**转向 Python API** 当：

- 需要自定义 lambda/函数做转换（CLI 预设不够用）
- 需要复杂的 filter/validate 逻辑
- 需要组合多个步骤但又不想写 YAML pipeline
- 大文件流式处理（`load_stream` / `load_sharded`，O(1) 内存）

```python
from dtflow import DataTransformer, load_stream

# 链式 API
(DataTransformer.load("data.jsonl")
    .filter(lambda x: x.score > 0.8)
    .to(lambda x: {"q": x.question, "a": x.answer})
    .dedupe("q")
    .save("output.jsonl"))

# 流式（100GB+ 文件）
(load_stream("huge.jsonl")
    .filter(lambda x: x["score"] > 0.5)
    .save("output.jsonl"))
```

**Python 侧对外 API**（详见源码 docstring，这里只列路标）：

- `DataTransformer` / `DictWrapper` — 核心类，支持 `.filter / .to / .map / .dedupe / .split / .save`
- 预设模板：`openai_chat / alpaca / sharegpt / dpo_pair / simple_qa`（`dt.to(preset="openai_chat", ...)`）
- Schema：`openai_chat_schema / alpaca_schema / sharegpt_schema / dpo_schema`（`dt.validate_schema(...)`）
- Token：`count_tokens / token_counter / token_filter / messages_token_counter`
- 转换器：`to_hf_dataset / to_openai_batch / to_llama_factory / to_swift_messages / messages_to_text`
- 导出：`dt.export_for("llama-factory" | "swift" | "axolotl", output_dir)`
- 流式：`load_stream("data.jsonl") / load_sharded("data/*.parquet")`

## Pipeline 配置 (YAML)

当需要把多步操作固化为可复用/可版本化的流程时：

```yaml
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

运行：`dt run pipeline.yaml`（支持 `--dry-run` 打印步骤链）。

## 常见坑

1. **大文件 OOM** — `dt` 默认内存模式，>1GB 文件用 Python `load_stream(...)`。
2. **字段路径不通** — CLI 支持 `a.b[0].c`，但 `--where` 只支持简单表达式，复杂逻辑转 Python。
3. **TTY vs 非 TTY 输出差异** — 被 agent 管道捕获时自动变 ndjson；测试命令时用 `dt --format=json <cmd>` 强制一致。
4. **`--preset` 误写** — 不同命令预设名不同：`transform/validate` 都用 `openai_chat`；`alpaca` vs `dpo` vs `sharegpt` 拼写要准。
5. **dry-run 退出码** — 10 不是 0；脚本里用 `[[ $? == 0 || $? == 10 ]]` 区分真正失败。
6. **history --json 已过渡** — 新代码用 `dt --format=json history ...`，旧 `--json` 仅作向后兼容。

## 补全安装

```bash
dt --install-completion    # bash/zsh/fish 自动补全
```
