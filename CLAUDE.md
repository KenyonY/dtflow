# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

项目skill文件编写注意：需要保持信息密度足够高。

## 项目概述

dtflow 是一个简洁的机器学习训练数据格式转换工具，支持 SFT、RLHF、Pretrain 等格式。

## 核心设计理念

- **函数式优于类继承**: 直接用 lambda/函数做转换，不需要 BaseFormatter 等 OOP 抽象
- **KISS 原则**: 一个 `DataTransformer` 类搞定所有操作
- **链式 API**: `dt.filter(...).to(...).save(...)`

## 项目结构

```
dtflow/                    # 核心库
├── __main__.py           # CLI 入口 (typer，定义命令参数和帮助信息)
├── core.py               # DataTransformer 核心类 + DictWrapper/ListWrapper/unwrap
├── expr.py               # 统一 Python 表达式引擎 (compile_where/compile_value/compile_map, 当前行 x)
├── ops.py                # 数据原语库层 (filter/select/map/explode/sort/shuffle/group/join/clean/transform/split), CLI 与 pipeline 共用
├── presets.py            # 预设转换函数 (openai_chat, alpaca, sharegpt, dpo_pair, simple_qa)
├── schema.py             # Schema 验证 (Field, Schema, openai_chat_schema 等)
├── tokenizers.py         # Token 统计和过滤 (tiktoken/transformers 后端)
├── converters.py         # 格式转换器 (HuggingFace, OpenAI Batch, LLaMA-Factory, ms-swift)
├── framework.py          # 训练框架导出 (export_for, check_compatibility)
├── streaming.py          # 大文件流式处理 (StreamingTransformer, load_stream, load_sharded)
├── lineage.py            # 数据血缘追踪
├── i18n.py               # 界面语言: t("English", "中文"), dt lang / DT_LANG 切换, 默认 en
├── pipeline.py           # Pipeline YAML 执行器 (step = CLI 命令名, 参数 = 选项名, 直接调 ops)
├── storage/io.py         # 文件 I/O (JSONL, JSON, CSV, Parquet, Arrow) - 使用 Polars
├── cli/                  # CLI 命令实现（模块化）
│   ├── commands.py       # 命令汇总导出
│   ├── pipe.py           # 管道层: FILE=- 读 stdin, 无 -o 写 stdout, -i 原地写回, TTY 预览截断
│   ├── ops.py            # filter/select/map/explode/sort/shuffle/group/join 命令 (参数解析, 逻辑在 dtflow/ops.py)
│   ├── sample.py         # sample/head/tail 命令
│   ├── transform.py      # transform 命令
│   ├── clean.py          # clean 命令
│   ├── validate.py       # validate 命令
│   ├── stats.py          # stats/token-stats/diff 命令
│   ├── io_ops.py         # concat/dedupe 命令
│   ├── pipeline.py       # run 命令
│   ├── lineage.py        # history 命令
│   └── common.py         # 公共工具函数
└── utils/
    ├── field_path.py     # 字段路径解析 (a.b, a[0].b, a.#, a[*].b 语法)
    ├── display.py        # Rich 终端输出格式化
    └── helpers.py        # 通用辅助函数
```

**CLI 结构**: 使用 typer 框架，支持自动补全
- `__main__.py` - 定义命令入口和参数
- `cli/` - 各命令实现已模块化拆分
- 安装补全: `dt --install-completion`

## 常用命令

### 开发环境

```bash
pip install -e .                  # 基础安装
pip install -e ".[full]"          # 完整依赖
pip install -e ".[dev]"           # 开发依赖
```

### 测试

```bash
pytest tests/                              # 运行测试
pytest tests/test_core.py::test_add_item   # 运行单个测试
hatch test                                 # 使用 hatch 运行
```

### 代码质量

```bash
hatch run lint:fmt     # 格式化代码 (black + isort)
hatch run lint:style   # 检查代码风格 (flake8 + black --check)
hatch run lint:all     # 运行所有检查
```

### CLI 命令 (dt)

```bash
# 数据原语 (表达式即 Python, 当前行 x; FILE 可为 -, 无 -o 写 stdout, 可管道拼接)
dt filter data.jsonl "len(x.messages)>=2 and x.messages[-1].role=='assistant'"
dt select data.jsonl "id,n=len(x.messages)" | dt sort - --by x.n --desc | dt head - 5
dt group data.jsonl --by x.meta.source
dt stats data.jsonl --schema                     # 嵌套 schema

# 数据采样
dt sample data.jsonl --num=10
dt sample data.jsonl 1000 --by=meta.source       # 按嵌套字段分层采样
dt sample data.jsonl --where="len(x.messages)>=2"  # 筛选后采样

# 数据转换
dt transform data.jsonl --preset=openai_chat
dt transform data.jsonl                          # 生成配置文件模式

# 数据验证
dt validate data.jsonl --preset=openai_chat

# 数据清洗 (无 -o 写 stdout, -i 原地写回)
dt clean data.jsonl --drop-empty=meta.source -i  # 删除嵌套字段为空的记录
dt clean data.jsonl --min-len=messages.#:2 -o out.jsonl   # 至少 2 条消息

# 数据去重
dt dedupe data.jsonl --key=messages[0].content -i   # 按第一条消息内容去重

# 其他命令
dt concat a.jsonl b.jsonl -o merged.jsonl
dt stats data.jsonl
dt token-stats data.jsonl --field=messages --model=gpt-4
dt diff a.jsonl b.jsonl --key=meta.uuid
dt run pipeline.yaml
dt history processed.jsonl
```

**字段路径语法**（指定单个字段的参数用）: `a.b`(嵌套)、`a[0].b`(索引)、`a[-1].b`(负索引)、`a.#`(长度)、`a[*].b`(展开)
**表达式语法**（filter/select/map/sort/group/join/--where/pipeline 共用）: Python 表达式, 当前行 `x`, 见 `dtflow/expr.py`

## 关键约定

### 添加新预设
1. 在 `dtflow/presets.py` 添加函数
2. 在 `tests/` 添加测试
3. 更新 docs/python-api.md 的预设表格

### 添加新转换器
1. 在 `dtflow/converters.py` 添加函数
2. 在 `dtflow/__init__.py` 导出
3. 在 docs/python-api.md 添加使用示例

### 界面文本
面向用户的文本 (帮助、报错、提示、dt view) 一律写 `t("English", "中文")`, 含变量时两边各写 f-string; typer 命令帮助写在 `@app.command(help=t(...))`, 不用 docstring。`tests/test_i18n.py` 守卫: 源码里 t() 之外出现中文字符串 (docstring 除外) 即失败, 英文模式下任何 `--help` 含中文即失败。测试进程固定 `DT_LANG=zh` (tests/conftest.py)。

### 核心类关系
- `DataTransformer`: 内存模式，数据全部加载
- `StreamingTransformer`: 流式模式，惰性执行，O(1) 内存
- `DictWrapper`: 让 dict 支持属性访问 (`x.field` 代替 `x["field"]`)

## 技术栈

- **包管理**: hatchling
- **代码风格**: Black (行长度 100) + isort + flake8
- **测试**: pytest
- **Python**: >= 3.8
- **文件 I/O**: Polars（比 Pandas 快 3x）
- **JSON**: orjson（比标准 json 快 10x）

## Git 工作流

- 主分支: `main`
- 提交消息: 使用清晰的中文描述
- 提交前运行: `hatch run lint:fmt && pytest tests/`
