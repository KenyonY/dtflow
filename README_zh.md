# dtflow

<p align="left">
    <a href="https://pypi.org/project/dtflow/">
        <img src="https://img.shields.io/pypi/v/dtflow?color=brightgreen&style=flat-square" alt="PyPI version">
    </a>
    <a href="https://github.com/KenyonY/dtflow/actions/workflows/run_tests.yml">
        <img src="https://img.shields.io/github/actions/workflow/status/KenyonY/dtflow/run_tests.yml?branch=main&style=flat-square&label=tests" alt="Tests">
    </a>
    <a href="https://pypi.org/project/dtflow/">
        <img src="https://img.shields.io/pypi/pyversions/dtflow?style=flat-square" alt="Python versions">
    </a>
    <a href="https://github.com/KenyonY/dtflow/blob/main/LICENSE">
        <img alt="License" src="https://img.shields.io/github/license/KenyonY/dtflow.svg?color=blue&style=flat-square">
    </a>
    <a href="https://pypistats.org/packages/dtflow">
        <img alt="pypi downloads" src="https://img.shields.io/pypi/dm/dtflow?style=flat-square">
    </a>
</p>

<p align="left"><a href="README.md">English</a> | 中文</p>

**LLM 训练数据的终端浏览器，外加一套筛选、清洗、转换、导出的 CLI 工具箱。**

`dt view` 把 SFT / DPO / agent 的 JSONL 打开成"表格 + 详情"的浏览器：对话按 role 上色，工具调用格式化并标出坏 JSON，`/` 搜整个文件的每个字段，鼠标可用，窗口化加载让 90 万行的文件只占不到 100 MB 内存。其余的 `dt` 命令是同一批数据的 Unix 风格工具箱，可管道拼接，条件直接写 Python。

<p align="center">
  <img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/demo.gif" alt="dt view：表格 + 详情联动的终端数据浏览器，全量搜索 / 筛选 / 列值勾选 / 放大 / dpo 对比" width="900">
</p>
<p align="center"><sub><code>dt view data.jsonl</code> —— 一条命令把训练数据变成可搜索、可筛选的终端浏览器</sub></p>

## 30 秒上手

```bash
pip install dtflow                      # 或不装直接跑: uvx --from dtflow dt view data.jsonl

dt view data.jsonl                                              # 浏览（按 ? 看快捷键）
dt stats data.jsonl --schema                                    # 嵌套 schema：类型 / 非空率 / 取值
dt filter data.jsonl "len(x.messages) >= 2 and x.messages[-1].role == 'assistant'" \
  | dt select - "id,turns=len(x.messages),last=x.messages[-1].content" \
  | dt sort - --by x.turns --desc | dt head - 5
dt transform data.jsonl --preset=openai_chat -o train.jsonl     # sharegpt / alpaca / dpo → OpenAI messages
```

支持 JSONL/NDJSON（含 `.gz`）、JSON、CSV/TSV、Parquet、Arrow、Excel。所有数据命令 `FILE` 写 `-` 读 stdin，不加 `-o` 写 stdout，所以任意拼接。界面默认英文，运行 `dt lang zh` 切换为中文。手头没数据？[`examples/`](examples/) 里有几份合成的 chat / ShareGPT / Alpaca / DPO 小文件可以直接试。

## 为什么是 dtflow

- **它知道什么是一条训练样本。** 通用表格工具把 `messages` 显示成 `{3}` 或截断的字符串；`dt view` 先识别 `openai_chat` / `sharegpt` / `dpo` / `alpaca`，一屏画一条完整样本：按 role 上色、代码高亮、`tool_calls` 与 `reasoning_content` 展开、坏参数标红。
- **条件是 Python，不是自造 DSL。** `x.score > 0.8 and 'wiki' in x.meta.source`、`any('退款' in m.content for m in x.messages)`。同一套表达式贯穿 `filter`、`select`、`map`、`sort`、`group`、`join`、viewer 和 YAML pipeline。
- **给 agent 用和给人用同等重要。** stdout 只有数据，stderr 只有消息，退出码有契约，`dt schema` 输出机器可读的命令树，`dt install-skill` 一条命令把用法教给 Claude Code 或 Codex。
- **默认流式。** `filter` / `select` / `map` / `clean` / `dedupe` / `transform` 从不整文件加载；viewer 打开 91 万行 JSONL 约 90 MB 内存，全量扫描并行。

## dt view：在终端里浏览训练数据

`dt view <file>` 打开 master-detail 浏览器：左侧**表格**概览每条样本（派生列 `turns/roles/first_user/chars/calls` + 元数据列），右侧**详情**按格式渲染当前行。JSONL/CSV/Parquet 都能开，几十万行秒开。

<table>
  <tr>
    <td width="50%"><img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/main.png" alt="openai_chat 主界面：表格 + 详情联动，代码块语法高亮"></td>
    <td width="50%"><img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/search.png" alt="/ 全量搜索：整条记录任意值，命中处黄底高亮"></td>
  </tr>
  <tr>
    <td align="center"><sub><b>主界面</b>：表格选行，详情按 role 上色、代码块高亮</sub></td>
    <td align="center"><sub><b><code>/</code> 全量搜索</b>：搜整条记录（含 assistant 回复），命中黄底</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/value_filter.png" alt="F 列值勾选筛选：唯一值与频次，勾选保留"></td>
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
dt view data.jsonl -w "turns(x)>=6" -s 报错 # 启动即筛选 + 搜索
dt sample data.jsonl 500 | dt view -        # 管道：看采样/处理后的结果
```

| 按键 | 作用 |
|------|------|
| `/` `f` `F` `s` | 全量搜索 · 表达式筛选（`turns(x)>=6 and x.source=='alpaca'`，与 `dt filter` 同一套 Python 表达式）· 列值勾选 · 排序，可叠加，`r` 一键清空 |
| `Enter` `n/N` `*` | 放大当前样本 · 逐字段跳 · 只在搜索命中间跳 |
| `w` `C` `P` | 把筛出的子集导出成文件（自动写血缘）· 复制一条能复现当前视图的 `dt view` 命令 · 把同一套条件复制成 `dt filter … \| dt sort …` 去处理 |
| `y` / 鼠标拖选 + `Ctrl+c` | 复制整条样本 JSON / 复制详情里任意一段文字（SSH/tmux 下也进本机剪贴板） |
| 双击列头 | 重命名列：界面立即改，`q` 时询问写回文件（记血缘）或丢弃 |

完整快捷键、筛选语法、大文件与 follow 模式：[docs/view.md](docs/view.md)（英文）。

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

**什么时候不该用 dt view**：要做 join、透视、按列画图，用 VisiData；要对表写 SQL，用 tabiew；只想看一个 JSON 文件的层级，用 jless。dt view 只在"这是一批训练样本，我要扫、找、筛、导出"这件事上比它们好，但这正是训练数据每天要做的事。

<sub>内存为同一台 Linux 机器上打开文件后静置的峰值 RSS（2026-09），其余各项按各工具的 README 与源码核对，版本见表头。</sub>

## CLI：训练数据的瑞士军刀

所有数据命令遵守同一套约定：`FILE` 写 `-` 从 stdin 读 NDJSON，也可以是目录或加引号的 glob；不加 `-o` 数据写 stdout，进度和摘要只走 stderr。筛选条件、派生字段、排序键、分组键、连接键一律是 **Python 表达式，当前行叫 `x`**。

```bash
# 数据原语
dt filter  data.jsonl "x.score > 0.5 and 'wiki' in x.meta.source"
dt select  data.jsonl "id,text,n=len(x.messages),src=x.meta.source"     # 投影 / 重命名 / 派生
dt map     data.jsonl "x.text = x.text.strip(); del x.debug"            # 原地修改
dt explode data.jsonl --field messages --index-as turn                  # list 展开成多行
dt sort    data.jsonl --by "len(x.messages)" --desc
dt group   data.jsonl --by x.meta.source                                # {"key","count"} 按 count 降序
dt group   data.jsonl --by x.label --agg "avg=mean(len(r.text) for r in g)"
dt join    data.jsonl meta.jsonl --on x.id --prefix m_                  # 左连接，右表入内存
dt dedupe  data.jsonl --key=messages[0].content -i                      # 精确去重，原地写回
dt clean   data.jsonl --drop-empty=text --min-len=messages.#:2 -o clean.jsonl
dt split   data.jsonl --ratio=0.9 --seed=42                             # train/test
dt stats   data.jsonl --schema                                          # 先看全貌再写表达式

# 管道拼接
dt filter d.jsonl "x.score>0.5" | dt select - "id,n=len(x.messages)" | dt sort - --by x.n --desc | dt head - 5
cat big.jsonl.gz | dt filter - "x.lang=='zh'" | dt transform - --preset=openai_chat | dt view -
dt group d.jsonl --by x.label | dt sort - --by x.count --desc

# 其余命令
dt sample data.jsonl 1000 --by=meta.source      # 分层采样
dt token-stats data.jsonl --model=gpt-4         # 分角色 token 分布
dt validate data.jsonl --preset=openai_chat     # schema 校验，--filter 只留有效行
dt diff a.jsonl b.jsonl --key=id                # 两个版本差异
dt export data.jsonl -f llama-factory           # 数据 + 配置，LLaMA-Factory / ms-swift / Axolotl
dt run pipeline.yaml                            # 可复现 pipeline，step 即 CLI 命令
```

表达式求值失败的行（缺字段、`None > 0.5`）不中断运行：`filter` 丢弃、`select` 该项置 `null`、`map` 原样保留，结束时 stderr 汇总一次；`--strict` 首错即退出码 1。漏写 `x.` 的裸字段名在编译期就报错，不会静默 0 命中。

命令参考：[docs/cli.md](docs/cli.md) · 表达式与字段路径（含 0.9 迁移表）：[docs/expressions.md](docs/expressions.md) · pipeline：[docs/pipeline.md](docs/pipeline.md)。

## Python API

同样的操作提供链式类；回调里 `x.field` 属性访问对嵌套 dict / list 都有效。

```python
from dtflow import DataTransformer, load_stream

(DataTransformer.load("data.jsonl")
    .filter(lambda x: x.score > 0.8)
    .transform(preset="openai_chat", user_field="q", assistant_field="a")
    .dedupe("messages[0].content")
    .save("train.jsonl"))

(load_stream("huge.jsonl")                 # 装不下内存的文件，常量内存
    .filter(lambda x: x["score"] > 0.5)
    .save("filtered.parquet"))
```

预设模板（`openai_chat`、`alpaca`、`sharegpt`、`dpo_pair`）、Schema 校验、tiktoken / HuggingFace 分词器的 token 统计、LLaMA-Factory / ms-swift / Axolotl / HuggingFace datasets / OpenAI Batch 转换器、数据血缘：[docs/python-api.md](docs/python-api.md)。

## Agent Skill

```bash
dt install-skill                         # Claude Code（默认）
dt install-skill --target codex          # Codex
```

安装后在 Claude Code 输入 `/dtflow`、在 Codex 输入 `$dtflow`，agent 即掌握完整用法。CLI 本身就是按 agent 驱动设计的：`dt schema` 输出 JSON 命令树，`dt <cmd> --help` 带示例，所有副作用命令支持 `--dry-run`（退出码 10），stdout 非终端时错误为结构化 JSON。

## 文档

- [快速入门](docs/quickstart.md)
- [CLI 参考](docs/cli.md)
- [`dt view`](docs/view.md)
- [表达式与字段路径](docs/expressions.md)（含 0.9 迁移对照表）
- [Pipeline](docs/pipeline.md)
- [Python API](docs/python-api.md)
- [更新日志](CHANGELOG.md)

文档为英文；中文完整说明以本页和各命令的 `--help` 为准。

## 设计

- **函数式优于类继承。** `dt.to(lambda x: {...})` 而不是 `class MyFormatter(BaseFormatter)`；预设是便利层，不是核心抽象。
- **一种表达式语言。** Python 本身就是 DSL，viewer、CLI、pipeline 用同一个引擎编译同一个字符串。
- **一套契约。** 内存用 `DataTransformer`，装不下用 `StreamingTransformer`；CLI 契约（stdout=数据、stderr=消息、退出码有含义）从不妥协。

## License

MIT
