---
name: dtflow
description: >
  处理结构化数据文件 (JSONL/JSON/CSV/Parquet/Arrow/TSV) 时使用此 skill。
  提供 CLI 工具 `dt` 和 Python API `DataTransformer`。
  典型场景：数据预览/交互式浏览 (dt view)/统计/清洗/去重/Schema 验证、格式转换
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

- **非 TTY**（管道/重定向） → 默认 `ndjson`（记录类） 或 `json`（报告类）—— agent 场景取此
- **TTY** → 预览命令（head/sample/tail/slice）默认逐条 pretty JSON；加 `--pretty` 或 `--format=table` 走格式感知渲染
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

## 交互式浏览 (dt view)

`dt view <file> [NUM]` —— 表格 + 详情联动的 TUI，人工探查训练数据高效（**需交互式终端，agent 场景改用 `dt head --pretty` 或 `dt --format=json head`**）。打开即从第 1 行顺序浏览；位置参数 `NUM` 是 `--cap` 简写（首屏 N 行，仍可翻页），如 `dt view data.jsonl 100`。

- 上方表格扫视（派生列 turns/roles/first_user/chars + 元数据），下方按格式渲染当前行详情（对话气泡/dpo对比/alpaca分段/通用全展开），无需逐层展开
- CSV/Parquet 等表格数据全部列展示；`--format` 可强制格式
- **大文件窗口化浏览**：JSONL 靠字节偏移索引（不 parse 全文件，100 万行建索引 <0.1s），只加载当前窗口（`--cap`，默认 2 万行）；`--offset=N` 从第 N 行打开；TUI 内 `]`/`[` 翻下/上一窗口、`:` 跳到任意行号（seek 秒开，与位置无关）。`#` 列显示全局行号
- **管道模式** `... | dt view -`：从 stdin 读 NDJSON 全量入内存（流不可 seek），适合看处理结果的一小撮，如 `dt sample data.jsonl 500 | dt view -`（大文件仍用 `dt view file` 走窗口化）
- **详情字段定位**：切样本时详情自动停在同名字段位置（字段绑定，非绝对像素）；`n`/`N` 逐字段精确跳转（底部字段滚动条到不了时也可达），亦可鼠标点击详情区域选中字段；状态栏实时显示当前字段
- **全量筛选/搜索**：`f` where、`/` 子串搜索 —— 均**扫描整个文件**(worker 线程，带进度，`Esc` 取消)，命中的全局行号聚成可分页「子集」浏览；状态栏显示「命中 M/N (占比%)」；`r` 清除子集回到全量。完整分布统计(直方图/分位数/value_counts)用 `dt stats`/`dt token-stats`
  - where 语法：`列名 运算符 值`，列名取**表头所见**（派生列 `chars`/`turns`/`roles` 按该列的值比较；元数据列/深层路径 `source`、`messages.#>=2` 当字段路径）。运算符 `> >= < <= == != =` 和 `~=`(包含, 不区分大小写; 要区分用 `==`)。多列 **`and`/`or` 组合**（and 优先级高于 or），如 `turns>=6 and chars<2000`
  - **按内容包含**：`first_user~=退款`(派生列匹配全文，非表格里 80 字预览)、`source~=alpaca`、`messages[0].content~=报错`、`messages[*].content:join~=词`(搜整段对话，`:join` 不可省——不加时 `[*]` 只取第一个元素)
  - `/` 子串搜索同样搜**全文**，不是表格可见前缀
- **列值勾选筛选** `F` 或**点列头**（Excel AutoFilter 式）：全量列出该列唯一值+频次 → 勾选保留哪些 → 子集。面板顶部搜索框按子串过滤候选值，有搜索词时「全选」= 只保留匹配项（「某列包含某子串」= 打字 → 全选 → Enter）。适合类别列(source/roles/label)；唯一值 >2000 的列提示改用 `f` 的 `列~=子串`。作用于当前浏览序列，可与 `f` 叠加
- **列快照** `S`：对当前浏览序列(子集或全量)的某列给一行 `n·min·max·mean·非空率`(即时决策用，非完整分布)
- 关键键：`j/k` 选行 · `]`/`[` 翻窗口 · `:` 跳行 · `n/N` 详情字段导航 · `s` 排序(列名, `-` 反向, 仅当前窗口内) · `S` 列快照 · `/` 全量搜索 · `f` 全量where筛选 · `c` 选列(表格+详情) · `Enter` 放大 · `r` 清筛选/排序 · `?` 帮助 · `q` 退出

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
