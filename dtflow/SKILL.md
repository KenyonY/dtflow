---
name: dtflow
description: >
  处理结构化数据文件 (JSONL/NDJSON/JSON/CSV/TSV/Parquet/Arrow/Excel) 时使用此 skill。
  提供 CLI 工具 `dt` 和 Python API `DataTransformer`。
  典型场景：数据预览/交互式浏览 (dt view，含全量搜索筛选排序/导出子集)/统计/清洗/去重/Schema 验证、
  filter/select/map/sort/group/join 等数据原语 (Python 表达式, 可管道拼接)、格式转换
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
dt --version             # 版本号 (裸值, 直接可比对; 同 dt schema 的 version 字段)
dt --help                # 命令列表 + 全局选项 (标题行含版本号)
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
| **管道** | `FILE` 写 `-` 从 stdin 读 NDJSON；数据命令不加 `-o` 时数据写 stdout | `dt filter a.jsonl "..." \| dt select - "..." \| dt head -` |

**退出码约定：**
- `0` 成功
- `1` 一般错误（读写失败、运行时错误；`validate` 纯校验发现无效记录也是 1）
- `2` 参数错误（未知预设、非法取值、必填缺失）
- `3` 资源不存在（文件找不到）
- `4` 权限拒绝
- `5` 冲突
- `10` **dry-run 预演成功**（仍然是"成功"，但没有真正写出）

**Agent 规则：** 判断成败 **只看退出码**，不要解析文本输出。

**界面语言：** 默认英文，`dt lang zh` 或 `DT_LANG=zh` 切为中文。只影响人类可读文本，JSON 键、`error` 码、退出码与语言无关。

## 输出格式

- **非 TTY**（管道/重定向） → 默认 `ndjson`（记录类） 或 `json`（报告类）—— agent 场景取此
- **TTY** → 数据命令（filter/select/map/sort/group/join/clean/dedupe…）默认画**表格**（列与 `dt view` 同源：对话数据出 turns/roles/first_user/chars/calls），只看前 50 行，`--format=table` 全量；预览命令（head/sample/tail/slice）默认逐条 pretty JSON；加 `--pretty` 或 `--format=table` 走格式感知渲染
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

1. **探结构** — `dt stats data.jsonl --schema`（嵌套类型/非空率/list 元素/低基数取值）或 `dt head data.jsonl`
   - **看分布** — `dt describe d.jsonl "turns(x)" "chars(x)" "x.score"`（分位数+直方图）、`dt group d.jsonl --by "roles(x)"`（角色序列占比）、`dt group d.jsonl --by "bool(calls(x))"`（带工具调用的占比）；`stats --full` 的 `null_rate` 是空值占比 (0-1)
2. **探内容** — `dt group data.jsonl --by x.<key>` 看分布；`dt filter data.jsonl "<表达式>" | dt head -` 抽样看命中
3. **小样本跑通** — 先在 100 条上验证转换逻辑，避免大文件反复
4. **dry-run 预演** — `... --dry-run`，确认影响范围
5. **大规模执行** — 去掉 `--dry-run`，看最终退出码

**筛选/派生/排序/分组/连接一律写 Python 表达式**（见下节）；只"指定一个字段"的参数用字段路径 DSL。

## 表达式语法（filter / select / map / sort / group / join / --where / pipeline 共用）

表达式就是 Python，当前行叫 **`x`**（属性访问：`x.messages[-1].role`、`x.meta.source`；缺字段抛 AttributeError）。
命名空间另有 `re` / `json` / `math`、`get(x, "messages[*].role:join")` 通向字段路径 DSL，以及**行函数**（与 `dt view` 派生列同一实现）：`turns(x)` 消息条数、`roles(x)` 角色签名如 `u→a→t→a`、`first_user(x)` 首条 user 全文、`chars(x)` 全部消息字符数（含思维链与工具参数）、`calls(x)` 调用过的函数名（逗号分隔，无则空串）、`fulltext(x)` 整条记录所有值拼成的文本、`search(x, 词)` 整条记录不分大小写子串（`re:` 前缀正则，同 view 的 `/`）。裸写 `turns>=6` 是语法错误（提示改 `turns(x)`）。

```bash
dt filter d.jsonl "x.score > 0.8 and 'wiki' in x.meta.source"
dt filter d.jsonl "len(x.messages) >= 2 and x.messages[-1].role == 'assistant'"
dt filter d.jsonl "any('退款' in m.content for m in x.messages)"
dt filter d.jsonl "turns(x) >= 6 and 'get_weather' in calls(x) and search(x, '退款')"   # 行函数
dt group  d.jsonl --by "roles(x)"                                        # 角色序列分布
dt select d.jsonl "id,n=len(x.messages),last=x.messages[-1].content"     # 字面字段名 | 新名=表达式
dt map    d.jsonl "x.text = x.text.strip(); del x.debug"                # 语句, 原地改 x
dt sort   d.jsonl --by "(x.source, -x.score)"
dt group  d.jsonl --by x.label --agg "avg=mean(len(r.text) for r in g)"  # g=组内行列表, key, n
dt join   d.jsonl meta.jsonl --on x.id --prefix m_
dt join   train.jsonl test.jsonl --on "first_user(x)" --anti           # 去掉与测试集重合的样本
```

- 求值失败的行（缺字段、`None > 0.5`）默认不中断并在 stderr 汇总一次：filter 判不匹配、select 该项置 null、map 该行原样保留、sort 排末尾、group --agg 该项置 null（一进一出的命令不会静默少行）；`--strict` 首错即退出码 1
- 漏写 `x.` 的裸字段名（`score > 0.5`、`--by id`）编译期即退出码 2；字段路径参数（`--key/--by/--field`）写成 `x.a` 也会被拦下
- 语法错误退出码 2 并指出位置；`in` 区分大小写，不分大小写写 `.lower()`
- 旧的 `字段 运算符 值` / `~=` 语法已删除：`category=tech` → `x.category=='tech'`，`messages.#>=2` → `len(x.messages)>=2`，`content~=词` → `'词' in x.content.lower()`

## 数据原语与管道

| 命令 | 作用 | 内存 |
|------|------|------|
| `filter FILE EXPR` | 保留表达式为真的行 | 流式 |
| `select FILE SPEC` | 投影 / 重命名 / 派生（`id,text,n=len(x.m)`，输出键序=SPEC 序，字面字段缺失则省略） | 流式 |
| `map FILE CODE` | 逐行执行语句原地修改 | 流式 |
| `explode FILE --field F [--as NAME --index-as I]` | list 展开成多行 | 流式 |
| `sort FILE --by EXPR [--desc]` | 排序，键求值失败的行排最后 | 全量 |
| `shuffle FILE [--seed]` | 打乱 | 全量 |
| `group FILE --by EXPR [--agg SPEC] [--top N]` | 计数 `{"key","count","pct"}` 降序 / 自定义聚合；`--top` 只留最大 N 组 | 计数流式 |
| `describe FILE EXPR...` | 表达式数值分布：n/null/min/max/mean/std/p25..p99，TTY 附直方图（view `S` 快照的 CLI 版） | 全量 |
| `join LEFT RIGHT --on EXPR [--inner\|--anti] [--prefix P]` | 左连接（默认）/ 内连接 / 反连接 `--anti`（只留右表无匹配的左行：去测试集污染、找未处理样本）；左表流式，右表入内存，左表字段优先 | 右表 |
| `stats FILE --schema` | 嵌套 schema 推断 | 前 1000 行 |

所有数据命令：`FILE` 可为 `-`，也可为**目录**（其中全部数据文件，按名排序首尾相接）或**加引号的 glob**（`'shards/*.jsonl'`）；无 `-o` 写 stdout（终端直出只预览前 50 行）；`clean`/`dedupe` 用 `-i` 原地写回（需单个文件）。`.jsonl.gz` 透明读写。`dt concat a.jsonl -o a.parquet` 单文件即格式转换。

## 字段路径语法（指定单个字段的参数用）

| 语法 | 含义 | 示例 |
|------|------|------|
| `a.b.c` | 嵌套字段 | `meta.source` |
| `a[0].b` | 索引（支持负索引） | `messages[0].role`, `messages[-1].content` |
| `a.#` | 数组长度 | `messages.#` |
| `a[*].b` | 展开所有元素 | `messages[*].role` |

用于：`--key`、`--by`（sample 分层）、`--field`、`--drop-empty`、`--min-len` 等；**不用于 `--where`**（那是表达式）。

## 交互式浏览 (dt view)

`dt view <file> [NUM]` —— 表格 + 详情联动的 TUI，人工探查训练数据高效（**需交互式终端，agent 场景改用 `dt head --pretty` 或 `dt --format=json head`**）。`NUM>0` 从开头浏览，`NUM<0` 快速从末尾窗口开始（如 `dt view data.jsonl -100`），首次访问更早历史时才按需建索引。

- 表格区扫视（派生列 turns/roles/first_user/chars/calls + 元数据），详情区按格式渲染当前行（对话气泡/dpo对比/alpaca分段/通用全展开），无需逐层展开。默认左右布局，`z` 切上下
- **agent 数据**：每条消息以角色色反色徽章 + 字数开头（表格 `roles` 列同色），代码块/JSON 铺底色；assistant 的 `tool_calls` 标题为 `assistant → 函数名`，下接 `⚙ 函数名 call_id` + 格式化参数（参数非法 JSON 标红），`reasoning_content`/`reasoning` 思维链暗色显示，`tool` 消息标题为 `tool ← call_id` 并格式化 JSON 返回；sharegpt 的 `function_call`/`observation` 同样处理。`calls` 列列出调用过的函数名（不叫 tools：顶层 `tools` 是存工具定义的标准字段），`roles` 里工具返回记 `t`（如 `u→a→t→a`）；`chars` 计入思维链与参数
- CSV/Parquet 等表格数据全部列展示；`--format` 可强制格式
- **大文件窗口化浏览**：JSONL/NDJSON 普通打开只索引并加载当前窗口（`--cap`，默认 1 万行），不等待全文件扫描；`]`/`[` 翻下/上一窗口，正向索引按需延伸。总行数在尚未计数或读到文件末尾前显示为待定。`:` 正数跳行只扫描到目标窗口；`G` 和负数跳行使用 Polars 快速精确计数，再反向读取尾窗，显示绝对行号而不建全文件偏移索引。计数及前后两端索引复用，向前翻尾窗只补相邻窗口；全量操作才补全中间缺失的索引。后台操作可按 `Esc` 取消。`--offset=N` 从第 N 行打开（0-based，需要扫描之前的内容）。`#` 列显示全局行号；已索引区域通过字节偏移直接读取
- **实时追尾**：`dt view app.jsonl -f`（`--follow`） 从最新尾窗开始，只提交已换行的完整记录，并自动跟随日志轮转。上移光标后界面暂停并累计新行，`G` 回到最新处；全量搜索/筛选对固定高水位扫描后继续增量应用到新行。可用 `-100 -f` 把尾窗限为 100 行
- **非等字段列头**：当前窗口的全部记录参与列发现，翻页/跳转时按首次出现顺序增量补列（不为 schema 预先 parse 全文件）；generic 的顶层对象/数组也算列。训练格式只默认展开前 8 个元数据列，其余仍在 `c` 列面板中，详情不因自动收起而缺字段
- **管道模式** `... | dt view -`：从 stdin 读 NDJSON 全量入内存（流不可 seek），适合看处理结果的一小撮，如 `dt sample data.jsonl 500 | dt view -`（大文件仍用 `dt view file` 走窗口化）
- **启动即带条件**：`--where=<Python 表达式>`(可重复，多条为**与**关系)、`--search=<词>`、`--sort=[-]列名`；与 TUI 内按 `f`/`/`/`s` 完全同义（同一条扫描管线）。如 `dt view d.jsonl --where="turns(x)>=6 and x.source=='a'" --sort=-chars`
- **长样本不卡**：几百条消息的样本先渲染前两屏、其余后台补齐，长按 `j` 只渲染停下的那一行
- **详情字段定位**：切样本时详情自动停在同名字段位置（字段绑定，非绝对像素）；对话**按条拆段**(`msg0`/`msg1`…)，`n`/`N` 因此是逐条消息导航（底部字段滚动条到不了时也可达），亦可鼠标点击选中；详情边框右下角实时显示当前字段（表格边框：左上 文件·格式、右下 光标位置 N/总数）
- **全量搜索/筛选/排序，三者可叠加**：`/` 搜索、`f` where、`F` 列值勾选、`s` 排序 —— 一律**扫描整个文件**(worker 线程，带进度，`Esc` 取消)，得到的全局行号序列即新浏览序列（翻窗口不失效）；状态栏显示「命中 M/N (占比%)」；`r` 清空全部。完整分布统计(直方图/分位数/value_counts)用 `dt stats`/`dt token-stats`
  - 三类约束各占独立槽位：`/` 一个(新搜索覆盖旧的)、`f` **可反复叠加**(多条之间 and)、`F` 按列独立记「保留值集」故可反复调整/加回
  - where 就是 **Python 表达式**（当前行 `x`），**与 `dt filter` 同一套语言**：表头上的派生列是行函数 `turns(x)`/`chars(x)`/`roles(x)`/`first_user(x)`/`calls(x)`（原始类型：`turns(x)` 是 int，`first_user(x)` 是全文），其余字段走 `x.`：`turns(x)>=6 and chars(x)<2000`、`x.source=='alpaca'`、`len(x.messages)>=2`；`and`/`or`/`not`/括号随意。裸写 `turns>=6` 报错并提示 `turns(x)`
  - **按内容包含**：`'退款' in first_user(x)`(全文，非 160 字预览)、`'get_weather' in calls(x)`(调用过该函数的样本; `calls(x)` 非空即带工具调用)、`search(x, '退款')`(整条记录，同 `/`)、`'报错' in x.messages[0].content`、`any('词' in m.content for m in x.messages)`(搜整段对话)。`in` 区分大小写，不分写 `.lower()`
  - `/` 搜的是**整条记录的每个值**（含 assistant 回复、后续轮次），不是表格列——表格列只是派生摘要，`first_user` 只是第一条用户消息。`re:` 前缀走正则，一律不分大小写。命中处在表格与详情里画**黄底**，`*` 只在含命中的字段间跳
  - `s` 排序是**全量**的：扫全文件产生排序后的序列，跨窗口有效（不是只排当前窗口）
- **列值勾选筛选** `F` 或**点列头**（Excel AutoFilter 式）：全量列出该列唯一值+频次 → 勾选保留哪些（默认全不选）→ 子集。面板顶部搜索框按子串过滤候选值，有搜索词时「应用」= 只保留勾选∩匹配，匹配项全没勾 = 全部匹配项（「某列包含某子串」= 打字 → Enter 两步完成）；跨搜索词累积勾选：搜A全选→搜B全选→清空搜索词→应用 = A∪B。高基数列不受限（面板只渲染频次最高的 1000 项，搜索仍在全量值上过滤）；「列包含某子串」也可用 `f` 的 `'子串' in first_user(x)`（匹配全文而非 160 字预览）
- **拖拽列宽**：表头每列右侧 (含末列) 画有 `│` 分隔线，鼠标压上去变 `┃` 高亮 + 状态栏提示，按住左右拖即改该列宽度（Excel 式，拖动中实时重绘）；**双击分隔线**该列恢复自适应、让出的宽度回流给其它列。宽度记在**列名**上，翻窗口/改筛选/换可见列后仍保留；拖宽超出屏幕则横向滚动（`←/→`、`h/l`）。只点分隔线不拖不会误触发点列头的值筛选面板
- **详情区鼠标拖选 + `Ctrl+c`**：在详情区里按住左键拖出高亮即选中任意文本（所见即所选，自动换行/中文宽字符处不错位），按 `Ctrl+c` 复制并清除选区；连击逐级放大：**双击取词**（id/字段值，`-`/`_` 算词内，中文按标点空格断）、三击整行、四击整个字段块、五击整屏详情，点一下或 `Esc` 清除。复制走 **OSC52 + 本地 wl-copy/xclip/xsel 双通道**（tmux/screen 自动 passthrough，SSH 下也到本机），通知里会说明用的哪条。表格区不参与（那里的拖拽是改列宽/选行），整条样本 JSON 用 `y`
- **拖两区分界调大小**：表格与详情之间那两行边框（横排时是两列）即分界，鼠标压上去边框变亮 + 状态栏提示，按住拖到哪分界就到哪（按格连续），双击恢复默认 65:35；键盘 `+/-` 仍是 5% 一档，`z` 切左右/上下布局（默认左右）
- **导出落地** `w`：把当前子集（或 `v` 选区）写成文件，按扩展名定格式（`.jsonl` 流式写，几十万行不占内存；其他格式走 `save_data` 分派）。**自动写血缘 sidecar**，`dt history <out>` 可查来源文件 + 当时全部条件。剪贴板(`y`/`v`)走 OSC52 有长度上限，几千条必须用 `w`
- **重命名列**：**双击列头**（单击仍是值筛选，延后 0.15s 开面板）→ 提示框预填当前名 → 回车。表头/详情/选列面板立即用新名，`w` 导出也用新名；筛选/排序/`C` 命令仍用磁盘上的原名（文件未变）。`q` 退出时询问：**写回**（流式重写 + 原子替换，`FILE.lineage.json` 记 `view_rename` 与等价 `dt clean FILE --rename old:new -i`）/ **丢弃** / 取消。stdin 与 follow 模式不能写回，用 `w` 导出。派生列和 `#` 不能改名
- **可复现** `C`：把当前视图翻译回一条 `dt view ... --where=... --search=... --sort=...` 复制到剪贴板，粘回终端即还原（列值勾选→`str(x.get('col')) in (...)` 这类表达式；表格里被截断的值无法还原时会明说，以血缘为准）
- **列快照** `S`：对当前浏览序列(子集或全量)的某列给一行 `n·min·max·mean·非空率`(即时决策用，非完整分布)
- **坏行(非法 JSON)按路径区别对待**，三者都能定位到行：`dt view` 把坏行显示成占位行(`_parse_error`/`_raw_line` 两列，行号不错位，可用 `/` 搜出来)，绝不拦门；`head`/`tail`/`sample` 跳过但 stderr 报第几行；`clean`/`transform`/流式等**会写出新文件**的路径直接抛错(附行号+行内容)，不静默丢数据
- 关键键：`j/k` 选行 · `]`/`[` 翻窗口 · `:` 跳行 · `n/N` 详情逐条消息 · `*` 下一命中 · `s` 全量排序 · `S` 列快照 · `/` 全量搜索 · `f` 全量where筛选(可叠加) · `F` 列值勾选 · `c` 选列 · 双击列头重命名 · `w` 导出 · `C` 复制命令 · `y`/`v` 复制样本 · 详情区拖选文本 + `Ctrl+c` 复制 · 拖两区分界调大小 · `Enter` 放大 · `r` 清全部约束 · `?` 帮助 · `q` 退出

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
- 预设模板：`openai_chat / alpaca / sharegpt / dpo_pair / simple_qa`（`dt.transform(preset="openai_chat", ...)`）。除 dpo_pair 外都自动识别输入形态（messages / sharegpt / alpaca / dpo / q-a），sharegpt 的 function_call/observation 与 OpenAI tool_calls/tool 互转（含并行调用）；认不出的行跳过并在 stderr 汇总，不会产出空 content
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
  - type: filter          # step 的 type = CLI 命令名, 参数 = CLI 选项名
    expr: "x.score > 0.5"
  - type: select
    fields: "id,text,n=len(x.messages)"
  - type: clean
    strip: true
    drop_empty: text
  - type: dedupe
    key: text
  - type: transform
    preset: openai_chat
    params: {user_field: q, assistant_field: a}
  - type: split           # 只能是最后一步, 按 output 派生 processed_train/_test
    ratio: 0.9
```

可用 step：filter / select / map / explode / sort / shuffle / group / join / dedupe / sample / head / tail / clean / transform / split。
运行：`dt run pipeline.yaml`（`--dry-run` 校验含表达式语法并打印步骤链；`-i -` 接 stdin，无 output 写 stdout）。

## 常见坑

1. **大文件** — filter/select/map/explode/clean/dedupe/transform 与管道都是流式的；sort/shuffle/group --agg/join 右表/`--where` 采样/split 需全量，先 `dt filter` 缩小再做。
2. **表达式里字段名与 DictWrapper 方法重名** — `x.get`/`x.to_dict` 是方法，数据里叫 `get` 的字段用 `x['get']`。
3. **TTY vs 非 TTY 输出差异** — 被 agent 管道捕获时自动变 ndjson；测试命令时用 `dt --format=json <cmd>` 强制一致。
4. **`--preset` 误写** — 不同命令预设名不同：`transform/validate` 都用 `openai_chat`；`alpaca` vs `dpo` vs `sharegpt` 拼写要准。
5. **dry-run 退出码** — 10 不是 0；脚本里用 `[[ $? == 0 || $? == 10 ]]` 区分真正失败。
6. **history --json 已过渡** — 新代码用 `dt --format=json history ...`，旧 `--json` 仅作向后兼容。

## 补全安装

```bash
dt --install-completion    # bash/zsh/fish 自动补全
```
