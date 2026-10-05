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

**LLM 训练数据的工作台。** 浏览它、用纯 Python 查询它、修好它、交付它——人能干，agent 也能干。

训练文件里的一行不是一行：它是一段对话、一对偏好、一条指令。多数工具看到的是不透明的 JSON；dtflow 看到的是样本，其余一切都从这个事实长出来——一个按识别出的格式渲染样本的终端浏览器，约 30 个可管道拼接、按对话结构筛选的命令，带血缘的格式转换与训练框架导出，以及一个能把整件事干完的 agent。

<p align="center">
  <img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/demo.gif" alt="dt view：表格 + 详情联动的终端数据浏览器，全量搜索 / 筛选 / 列值勾选 / 放大 / dpo 对比" width="900">
</p>
<p align="center"><sub><code>dt view data.jsonl</code> —— 一屏一条完整样本。按 <code>P</code>，刚才的操作就变成一条 <code>dt filter … \| dt sort …</code> 管道。</sub></p>

## 30 秒上手

```bash
pip install dtflow                      # 或不装直接跑: uvx --from dtflow dt view data.jsonl

dt view data.jsonl                                              # 浏览（按 ? 看快捷键）
dt stats data.jsonl --schema                                    # 嵌套 schema：类型 / 非空率 / 取值
dt filter data.jsonl "turns(x) >= 2 and search(x, '退款')" \
  | dt select - "id,turns=turns(x),last=x.messages[-1].content" \
  | dt sort - --by x.turns --desc | dt head - 5
dt transform data.jsonl --preset=openai_chat -o train.jsonl     # sharegpt / alpaca / dpo → OpenAI messages
```

支持 JSONL/NDJSON（含 `.gz`）、JSON、CSV/TSV、Parquet、Arrow、Excel。所有数据命令 `FILE` 写 `-` 读 stdin，不加 `-o` 写 stdout，所以任意拼接。界面默认英文，运行 `dt lang zh` 切换为中文。手头没数据？[`examples/`](examples/) 里有几份合成的 chat / ShareGPT / Alpaca / DPO 小文件可以直接试。

## 为什么是 dtflow

- **它知道什么是一条训练样本。** 通用表格工具把 `messages` 显示成 `{3}` 或截断的字符串。dtflow 识别 `openai_chat` / `sharegpt` / `dpo` / `alpaca`，并且在每个环节都以样本为单位工作：viewer 一屏渲染一条完整样本（按 role 上色、工具调用格式化并标出坏 JSON、VLM 图片一键查看），行函数 `turns(x)` / `roles(x)` / `calls(x)` / `search(x, '退款')` 按对话结构筛选，预设转换在格式之间搬运，`token-stats` 按角色拆分 token。
- **看和处理是同一个闭环、同一种语言。** 所有条件都是 Python，当前行叫 `x`——没有 DSL，viewer 编译的和 `dt filter` 编译的是同一个字符串。闭环是真实存在的：viewer 里按 `P`，刚才的操作变成 `dt filter … | dt sort …`；按 `|`，对整个文件跑一段 shell 管道，结果就地浏览；按 `w`，筛出的子集导出并自动记血缘。浏览时做的事变成脚本，脚本的输出用 `dt … | dt view -` 再拿回来看。
- **agent 能驱动它的全部。** stdout 只有数据，退出码有契约，stdout 非终端时报错是结构化 JSON，`--dry-run` 预览副作用，`dt schema` 输出 JSON 命令树。`dt install-skill` 一条命令把完整参考装进 Claude Code 或 Codex——然后"把这个数据集清洗一下"才真正是 agent 能接的活。

底下还有两条底线：`filter` / `select` / `map` / `clean` / `dedupe` / `transform` 流式处理、从不整文件加载；裸字段名或不存在的行函数在编译期就报错，而不是退出码 0 的空结果。

## 工作台实战

**去污染——删掉与测试集重合的训练样本。** join 键是 Python 表达式，所以按第一条 user 消息匹配，而不是比整行 JSON；只差元数据的近重复样本也逃不掉。

```bash
dt join train.jsonl test.jsonl --on "first_user(x)" --anti -o clean.jsonl
dt view clean.jsonl                    # 拿去训练前先扫一眼
```

**浏览到理解数据为止，再把刚才做的事变成管道。**

```bash
dt view data.jsonl        # / 搜每个值 · F 勾选列值保留 · f 按表达式筛选
                          # P 把刚才做的事复制成：  dt filter … | dt sort …
dt filter data.jsonl "turns(x) >= 4 and x.score > 0.7" | dt view -    # 处理完，再看一眼
```

**转格式，交付给训练框架。**

```bash
dt transform shards/ --preset=openai_chat -o sft.jsonl   # 目录也行；sharegpt/alpaca/dpo → messages
dt validate sft.jsonl --preset=openai_chat               # schema 校验；--filter 只留有效行
dt token-stats sft.jsonl --model=gpt-4                   # 分角色 token 分布
dt export sft.jsonl -f llama-factory                     # 数据 + 可直接用的配置（也支持 ms-swift、Axolotl）
```

**或者把整件事交给 agent。**

```bash
dt install-skill        # 把完整参考教给 Claude Code（或 Codex）
```

然后说："删掉最后一轮不是 assistant 的样本，按第一条 user 消息去重，导出成 LLaMA-Factory 格式。"agent 读 `dt schema`，用 `--dry-run` 预览，跑的就是上面这些命令。

## dt view：闭环的眼睛

`dt view <file>` 打开 master-detail 浏览器：左侧**表格**概览每条样本（派生列 `turns/roles/first_user/chars/calls` + 元数据列），右侧**详情**按格式渲染当前行。JSONL/CSV/Parquet 都能开，91 万行的文件秒开、约 90 MB 内存。

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
dt view app.jsonl -100 -f                   # 追尾不断增长的 JSONL（日志模式）
dt view data.jsonl -w "turns(x)>=6" -s error   # 启动即筛选 + 搜索
dt sample data.jsonl 500 | dt view -        # 管道：看采样/处理后的结果
```

| 按键 | 作用 |
|------|------|
| `/` `f` `F` | 全量搜索 · 表达式筛选（与 `dt filter` 同一套 Python）· Excel 式列值勾选。可叠加，`r` 一键清空 |
| `Enter` `n/N` `*` | 放大当前样本 · 逐字段跳 · 只在搜索命中间跳 |
| `w` `C` `P` | 导出筛出的子集（自动写血缘）· 复制一条可复现的 `dt view` 命令 · 把同一套条件复制成 `dt filter … \| dt sort …` |
| `\|` | 对整个文件跑一段 shell 管道（`dt filter - … \| dt sort - …`，接 jq 也行），结果就地浏览；`r` 回到原文件 |
| 鼠标 | 点列头打开列值勾选，拖列宽、拖两区分界，拖选文字即复制（SSH/tmux 下也进本机剪贴板） |

和其他终端查看器相比：VisiData、tabiew、jless、fx、csvlens 都是通用表格/JSON 工具——没有一家知道"这是一条训练样本"，没有一家支持鼠标筛选，打开 155 MB / 91 万行 JSONL 的峰值内存是 550 MB–2.3 GB，dt view 只要 91 MB。它们更强的地方（透视、SQL、深层 JSON 折叠）以及完整对比表见 [docs/view.md](docs/view.md)。

## 命令一览

所有数据命令遵守同一套约定：`FILE` 可以是 `-`（stdin）、目录或加引号的 glob；不加 `-o` 数据写 stdout，进度走 stderr；输出格式跟扩展名走。条件、键、派生字段一律是 Python 表达式，当前行叫 `x`。

```bash
# 动手之前先看
dt stats   data.jsonl --schema                        # 嵌套 schema：类型 / 空值率 / 取值示例
dt describe data.jsonl "turns(x)" "x.score"           # 每个表达式的分位数 + 直方图
dt token-stats data.jsonl --model=gpt-4               # 分角色 token 分布
dt diff    a.jsonl b.jsonl --key=id                   # 两个版本之间的差异

# 整形
dt select  data.jsonl "id,n=len(x.messages)"          # 投影 / 重命名 / 派生
dt map     data.jsonl "x.text = x.text.strip(); del x.debug"   # 原地修改
dt explode data.jsonl --field messages --index-as turn         # list 展开成多行
dt group   data.jsonl --by "roles(x)" --top 10        # {"key","count","pct"}
dt sort    data.jsonl --by "len(x.messages)" --desc
dt sample  data.jsonl 1000 --by=meta.source           # 分层采样
dt split   data.jsonl --ratio=0.9 --seed=42           # train/test 切分

# 合并与清洗
dt dedupe  data.jsonl --key=messages[0].content -i    # 精确去重，原地写回
dt clean   data.jsonl --drop-empty=text --min-len=messages.#:2
dt concat  a.jsonl b.jsonl -o merged.parquet          # 单文件输入即格式转换
dt run     pipeline.yaml                              # 可复现 pipeline，step 即 CLI 命令
```

表达式求值失败的行（缺字段、`None > 0.5`）不中断运行——`filter` 丢弃、`select` 该项置 `null`、`map` 原样保留，结束时 stderr 汇总一次；`--strict` 首错即退出码 1。在终端里，结果默认画成 50 行、与 `dt view` 同款列的表格；接管道时输出 NDJSON。

命令参考：[docs/cli.md](docs/cli.md) · 表达式与字段路径：[docs/expressions.md](docs/expressions.md) · pipeline：[docs/pipeline.md](docs/pipeline.md)。

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

安装后在 Claude Code 输入 `/dtflow`、在 Codex 输入 `$dtflow`，agent 即掌握完整用法。

## 文档

- [快速入门](docs/quickstart.md)
- [CLI 参考](docs/cli.md)
- [`dt view`](docs/view.md)
- [表达式与字段路径](docs/expressions.md)（含 0.9 迁移对照表）
- [Pipeline](docs/pipeline.md)
- [Python API](docs/python-api.md)
- [更新日志](CHANGELOG.md)

文档为英文；中文完整说明以本页和各命令的 `--help` 为准。

## License

MIT
