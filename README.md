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

<p align="left">English | <a href="README_zh.md">中文</a></p>

**A terminal browser for LLM training data, plus a CLI toolbox to filter, clean, convert and export it.**

`dt view` opens an SFT / DPO / agent JSONL file as a table-plus-detail browser: conversations rendered as colored chat turns, tool calls formatted with bad JSON flagged, full-file search across every field, mouse support, and windowed loading that keeps a 900k-line file under 100 MB of RAM. The rest of `dt` is a pipeable Unix-style toolkit for the same data.

<p align="center">
  <img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/demo.gif" alt="dt view: table + detail terminal browser with full-file search, filters, value picker, zoom and dpo comparison" width="900">
</p>
<p align="center"><sub><code>dt view data.jsonl</code> — one command turns a training set into a searchable, filterable terminal browser (<a href="#interactive-data-browser-dt-view">details</a>)</sub></p>

```bash
pip install dtflow                      # or: uvx --from dtflow dt view data.jsonl   (no install)
dt view data.jsonl
```

## Install

```bash
pip install dtflow

# optional extras
pip install "dtflow[tokenizers-hf]"   # token stats with HuggingFace tokenizers
pip install "dtflow[converters]"      # HuggingFace Dataset conversion
pip install "dtflow[similarity]"      # near-duplicate removal (MinHash)
```

## dt view: browse training data in the terminal

`dt view <file>` opens a master-detail browser. The **table** on the left summarizes each sample (derived columns `turns/roles/first_user/chars/calls` plus your metadata columns); the **detail** pane on the right renders the current row by format: chat turns colored by role, code blocks syntax-highlighted, tool calls formatted with invalid arguments flagged, dpo chosen/rejected side by side. JSONL, CSV and Parquet all open, and files with hundreds of thousands of lines open instantly thanks to windowed loading; search, filter and sort run as parallel full-file scans.

<table>
  <tr>
    <td width="50%"><img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/main.png" alt="openai_chat main screen: table and detail linked, code blocks highlighted"></td>
    <td width="50%"><img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/search.png" alt="/ full-file search across every value, hits highlighted, hit ratio in the status bar"></td>
  </tr>
  <tr>
    <td align="center"><sub><b>Main screen</b>: pick a row, detail renders by role with code highlighting</sub></td>
    <td align="center"><sub><b><code>/</code> full-file search</b>: every value of every record (assistant replies included), hits in yellow</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/value_filter.png" alt="F column value picker: unique values with counts, tick to keep"></td>
    <td width="50%"><img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/dpo.png" alt="dpo format: prompt / chosen / rejected rendered side by side"></td>
  </tr>
  <tr>
    <td align="center"><sub><b><code>F</code> value picker</b>: Excel AutoFilter style, unique values + counts, keep what you tick</sub></td>
    <td align="center"><sub><b>dpo comparison</b>: chosen / rejected in different colors, format auto-detected</sub></td>
  </tr>
</table>

```bash
dt view data.jsonl                          # open, press ? for keys
dt view app.jsonl -100 -f                   # follow the last 100 lines (log mode)
dt view data.jsonl -w "turns>=6" -s error   # start filtered + searched
dt sample data.jsonl 500 | dt view -        # pipe: inspect sampled / processed output
```

| Keys | What they do |
|------|------|
| `/` `f` `F` `s` | Full-file search · expression filter (`turns>=6 and x.source=='alpaca'`, plain Python) · column value picker · sort. They stack; `r` clears all |
| `Enter` `n/N` `*` | Zoom into the sample · jump field by field · jump only between search hits |
| `w` `C` | Export the filtered subset to a file (lineage written automatically) · copy a `dt view` command that reproduces the current view |
| `y` / drag + `Ctrl+c` | Copy the whole sample as JSON / copy any text you drag-select in the detail pane (works over SSH and inside tmux) |

Full key list, filter syntax, large-file and follow-mode details: [Interactive data browser (dt view)](#interactive-data-browser-dt-view).

### How it compares to other terminal viewers

VisiData and tabiew are general table tools, jless and fx are JSON tree viewers, csvlens only reads CSV. None of them has the concept of "this row is a training sample": `messages` shows up as `{3}` or a string, and reading a conversation means expanding it level by level, one record at a time. dt view goes the other way: detect the format first, then draw the screen, so one screen is one complete sample.

| | dt view | VisiData 3.4 | tabiew 0.15 | jless 0.9 / fx 39 | csvlens 0.15 |
|---|---|---|---|---|---|
| Positioning | LLM training-data browser | general table Swiss army knife | general table (Polars) | JSON tree viewer | minimal CSV viewer |
| Chat / dpo / alpaca / tool_calls rendered by format | chat turns colored by role, code highlighted, tool-call arguments formatted with bad JSON flagged | no, nested fields show as `{3}`, expand with `(` | no, nested fields show as strings | generic tree, one record at a time | no JSONL support |
| Mouse | click a header to filter, drag column widths, drag the split, drag-select text to copy, multi-click to select word / line / block, wheel | click a cell, wheel | none (mouse events discarded) | click a row, wheel | none |
| Peak RSS opening a 155 MB / 910k-line JSONL | **91 MB** (windowed, does not grow with the file) | 550 MB | 565 MB | 824 MB / 2.3 GB | not supported |
| Search scope | every value of every record (assistant replies included), parallel full-file scan | regex in current or all columns | fuzzy search, SQL | regex within the tree | row regex |
| After filtering | `w` exports the subset with lineage, `C` copies a reproducible command | export | export | none | none |
| Follow a growing JSONL (`-f`) | yes | no | no | no | no |
| Where they are stronger | — | pivot, frequency tables, joins, plots, dozens of formats | SQL queries, single Rust binary | deep JSON folding, jq paths | zero dependencies, instant start |

**When not to use dt view**: for joins, pivots or per-column plots use VisiData; to run SQL over a table use tabiew; to inspect the structure of a single JSON document use jless. dt view only wins at "this is a batch of training samples and I need to scan, find, filter and export", which is exactly what you do with training data every day.

<sub>Memory is peak RSS after opening the file on the same Linux machine (2026-09). Other rows were checked against each tool's README and source; versions as in the header.</sub>

## Agent skill

dtflow ships an agent skill that can be installed into Claude Code or Codex:

```bash
dt install-skill                         # install into Claude Code (default)
dt install-skill --target codex          # install into Codex
dt skill-status --target codex           # show Codex install status
```

After installing, type `/dtflow` in Claude Code or `$dtflow` in Codex to give the agent the full dtflow reference for data-processing tasks.

## Quick start

```python
from dtflow import DataTransformer

dt = DataTransformer.load("data.jsonl")

# chain: filter -> transform -> save
(dt.filter(lambda x: x.score > 0.8)
   .to(lambda x: {"q": x.question, "a": x.answer})
   .save("output.jsonl"))
```

## Core features

### Load and save

```python
# JSONL/NDJSON, JSON, CSV/TSV, Parquet, Arrow, Excel (Polars engine, ~3x faster than pandas)
dt = DataTransformer.load("data.jsonl")
dt.save("output.jsonl")

# from a list
dt = DataTransformer([{"q": "question", "a": "answer"}])
```

### Filter

```python
dt.filter(lambda x: x.score > 0.8)
dt.filter(lambda x: x.language == "zh")   # attribute access on every row
```

### Validate

```python
# simple validation, returns the failing records
errors = dt.validate(lambda x: len(x.messages) >= 2)

if errors:
    for e in errors[:5]:
        print(f"row {e.index}: {e.error}")
```

### Schema validation

```python
from dtflow import Schema, Field, openai_chat_schema

# preset schema
result = dt.validate_schema(openai_chat_schema)
print(result)  # ValidationResult(valid=950, invalid=50, errors=[...])

# custom schema
schema = Schema({
    "messages": Field(type="list", required=True, min_length=1),
    "messages[*].role": Field(type="str", choices=["user", "assistant", "system"]),
    "messages[*].content": Field(type="str", min_length=1),
    "score": Field(type="float", min=0, max=1),
})

result = dt.validate_schema(schema)

# keep only valid rows
valid_dt = dt.validate_schema(schema, filter_invalid=True)
valid_dt.save("valid.jsonl")
```

**Preset schemas**:

| Schema | Format |
|------------|------|
| `openai_chat_schema` | OpenAI messages |
| `alpaca_schema` | Alpaca instruction/output |
| `sharegpt_schema` | ShareGPT conversations |
| `dpo_schema` | DPO prompt/chosen/rejected |

**Field options**:

| Option | Meaning | Example |
|------|------|------|
| `type` | type check | `"str"`, `"int"`, `"float"`, `"bool"`, `"list"`, `"dict"` |
| `required` | must be present | `True` / `False` |
| `min` / `max` | numeric range | `min=0, max=1` |
| `min_length` / `max_length` | length range | `min_length=1` |
| `choices` | enum | `choices=["user", "assistant"]` |
| `pattern` | regex | `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `custom` | custom check | `custom=lambda x: x > 0` |

### Transform

```python
# custom
dt.to(lambda x: {"question": x.q, "answer": x.a})

# preset
dt.to(preset="openai_chat", user_field="q", assistant_field="a")
```

### Presets

| Preset | Output |
|---------|---------|
| `openai_chat` | `{"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}` |
| `alpaca` | `{"instruction": ..., "input": ..., "output": ...}` |
| `sharegpt` | `{"conversations": [{"from": "human", ...}, {"from": "gpt", ...}]}` |
| `dpo_pair` | `{"prompt": ..., "chosen": ..., "rejected": ...}` |
| `simple_qa` | `{"question": ..., "answer": ...}` |

### Token statistics

```python
from dtflow import count_tokens, token_counter, token_filter, token_stats

count = count_tokens("Hello world", model="gpt-4")

dt.transform(token_counter("text")).save("with_tokens.jsonl")     # add a token_count field

dt.filter(token_filter("text", max_tokens=2048))                  # filter by token length
dt.filter(token_filter(["question", "answer"], min_tokens=10, max_tokens=4096))

stats = token_stats(dt.data, "text")
# {"total_tokens": 12345, "avg_tokens": 123, "min_tokens": 5, "max_tokens": 500, ...}
```

Backends are `tiktoken` (OpenAI, default) and `transformers`, **auto-detected** from the model name:

```python
count_tokens("Hello", model="gpt-4")                 # tiktoken
count_tokens("Hello", model="Qwen/Qwen2-7B")         # transformers
count_tokens("Hello", model="/home/models/qwen")     # local model -> transformers
```

### Token statistics for messages

Built for multi-turn conversations:

```python
from dtflow import messages_token_counter, messages_token_filter, messages_token_stats

dt.transform(messages_token_counter(model="gpt-4"))                 # total only
dt.transform(messages_token_counter(model="gpt-4", detailed=True))  # per role
# detailed: {"total": 500, "user": 200, "assistant": 280, "system": 20, "turns": 5, ...}

dt.filter(messages_token_filter(min_tokens=100, max_tokens=4096))
dt.filter(messages_token_filter(min_turns=2, max_turns=10))

stats = messages_token_stats(dt.data, model="gpt-4")
# {"count": 1000, "total_tokens": 500000, "user_tokens": 200000, "assistant_tokens": 290000, ...}
```

### Converters

```python
from dtflow import (
    to_hf_dataset, from_hf_dataset,     # HuggingFace Dataset
    to_openai_batch, from_openai_batch, # OpenAI Batch API
    to_llama_factory,                   # LLaMA-Factory alpaca format
    to_axolotl,                         # Axolotl
    messages_to_text,                   # messages -> plain text
)

ds = to_hf_dataset(dt.data)
ds.push_to_hub("my-dataset")
data = from_hf_dataset("tatsu-lab/alpaca", split="train")

batch_input = dt.to(to_openai_batch(model="gpt-4o"))
results = from_openai_batch(batch_output)

dt.transform(messages_to_text(template="chatml"))   # chatml / llama2 / simple
```

### LLaMA-Factory

```python
from dtflow import (
    to_llama_factory,              # alpaca (single turn)
    to_llama_factory_sharegpt,     # sharegpt (multi turn)
    to_llama_factory_vlm,          # VLM alpaca
    to_llama_factory_vlm_sharegpt, # VLM sharegpt
)

dt.transform(to_llama_factory()).save("alpaca.jsonl")
# {"instruction": "...", "input": "", "output": "..."}

dt.transform(to_llama_factory_sharegpt()).save("sharegpt.jsonl")
# {"conversations": [{"from": "human", "value": "..."}, {"from": "gpt", "value": "..."}], "system": "..."}

dt.transform(to_llama_factory_vlm(images_field="images")).save("vlm.jsonl")
# {"instruction": "...", "output": "...", "images": ["/path/to/img.jpg"]}

dt.transform(to_llama_factory_vlm_sharegpt(images_field="images", videos_field="videos"))
# {"conversations": [...], "images": [...], "videos": [...]}
```

### ms-swift

```python
from dtflow import (
    to_swift_messages,        # messages
    to_swift_query_response,  # query-response
    to_swift_vlm,             # VLM
)

dt.transform(to_swift_messages()).save("swift_messages.jsonl")
# {"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}

dt.transform(to_swift_query_response(query_field="messages")).save("swift_qr.jsonl")
# {"query": "...", "response": "...", "system": "...", "history": [["q1", "a1"], ...]}

dt.transform(to_swift_vlm(images_field="images")).save("swift_vlm.jsonl")
# {"messages": [...], "images": ["/path/to/img.jpg"]}
```

### One-shot export for training frameworks

Write data in the layout a framework expects, config files included:

```python
from dtflow import DataTransformer

dt = DataTransformer.load("data.jsonl")

result = dt.check_compatibility("llama-factory")
print(result)
# ✅ compatible - LLaMA-Factory (openai_chat)
# ❌ incompatible - error: xxx

files = dt.export_for("llama-factory", "./llama_ready/")
# ./llama_ready/custom_dataset.json
# ./llama_ready/dataset_info.json
# ./llama_ready/train_args.yaml

files = dt.export_for("swift", "./swift_ready/")       # data.jsonl + train_swift.sh
files = dt.export_for("axolotl", "./axolotl_ready/")   # data.jsonl + config.yaml

dt.export_for("llama-factory", "./output/", dataset_name="my_sft_data")
```

**Supported frameworks**:

| Framework | Output | Run with |
|------|---------|---------|
| `llama-factory` | data.json + dataset_info.json + train_args.yaml | `llamafactory-cli train train_args.yaml` |
| `swift` | data.jsonl + train_swift.sh | `bash train_swift.sh` |
| `axolotl` | data.jsonl + config.yaml | `accelerate launch -m axolotl.cli.train config.yaml` |

**Auto-detected formats**:

| Format | Structure |
|------------|---------|
| `openai_chat` | `{"messages": [{"role": "user", ...}]}` |
| `alpaca` | `{"instruction": ..., "output": ...}` |
| `sharegpt` | `{"conversations": [{"from": "human", ...}]}` |
| `dpo` | `{"prompt": ..., "chosen": ..., "rejected": ...}` |

### Other operations

```python
dt.sample(100)           # random sample
dt.head(10)
dt.tail(10)

train, test = dt.split(ratio=0.8, shuffle=True, seed=42)

stats = dt.stats()
count = dt.count(lambda x: x.score > 0.9)

dt.shuffle(seed=42)
```

## CLI

All data commands follow one convention: **`FILE` can be `-` to read NDJSON from stdin, and without `-o` data goes to stdout** (progress and summaries go to stderr), so commands pipe like Unix tools. Every filter / projection / sort / group condition is a **Python expression with the current row named `x`**.

```bash
# primitives (compose freely; expressions are Python, the row is x)
dt filter data.jsonl "x.score > 0.5 and 'wiki' in x.meta.source"
dt filter data.jsonl "len(x.messages) >= 2 and x.messages[-1].role == 'assistant'"
dt select data.jsonl "id,text,n=len(x.messages),src=x.meta.source"   # project / rename / derive
dt map    data.jsonl "x.text = x.text.strip(); del x.debug"          # mutate in place
dt explode data.jsonl --field messages --index-as turn                # one row per list element
dt sort   data.jsonl --by "len(x.messages)" --desc
dt shuffle data.jsonl --seed 42 -o shuffled.jsonl
dt group  data.jsonl --by x.meta.source                               # {"key","count"} sorted by count
dt group  data.jsonl --by x.label --agg "avg=mean(len(r.text) for r in g),ids=[r.id for r in g][:3]"
dt join   data.jsonl meta.jsonl --on x.id --prefix m_                 # left join, right side in memory
dt stats  data.jsonl --schema                                         # nested schema: see the shape before writing expressions

# pipelines
dt filter d.jsonl "x.score>0.5" | dt select - "id,n=len(x.messages)" | dt sort - --by x.n --desc | dt head - 5
dt sample d.jsonl 0 -w "x.ok" | dt clean - --strip | dt dedupe - --key=text -o clean.jsonl
dt group d.jsonl --by x.label | dt sort - --by x.count --desc
cat big.jsonl.gz | dt filter - "x.lang=='zh'" | dt transform - --preset=openai_chat | dt view -

# sampling
dt sample data.jsonl --num=10
dt sample data.csv --num=100 --type=head
dt sample data.jsonl 1000 --by=category           # stratified
dt sample data.jsonl 1000 --by=meta.source        # stratified by nested field
dt sample data.jsonl 1000 --by=messages.#         # stratified by message count
dt sample data.jsonl --where="x.category=='tech'"        # filter then sample (-w repeatable, AND)
dt sample data.jsonl -w "len(x.messages)>=2" -w "x.score>0.8"

# interactive browser (table + detail TUI, needs a terminal)
dt view data.jsonl                                # open, ? for keys
dt view data.jsonl -100                           # start at the last 100 rows
dt view app.jsonl -100 -f                         # follow the last 100 rows and log rotation (-f = --follow)
dt view data.csv                                  # CSV / Parquet / any table
dt view data.jsonl --format=dpo                   # force the detail format
dt view big.jsonl --cap=50000                     # raise the window size (default 10k rows)
dt view data.jsonl -S -chars                      # start sorted (longest first)
dt view data.jsonl -w "turns>=6" -s error         # start filtered + searched (-w repeatable, -s = --search)

# static preview (--pretty uses the same format-aware rendering)
dt head data.jsonl --pretty
dt sample data.jsonl --pretty

# row ranges (Python slice syntax)
dt slice data.jsonl 10:20                          # rows 10-19 (0-based, half open)
dt slice data.jsonl :100
dt slice data.jsonl 100:
dt slice data.jsonl 10:20 -o sliced.jsonl
dt slice data.jsonl 10:20 -f question,answer       # only these fields

# transform: presets (no -o -> stdout)
dt transform data.jsonl --preset=openai_chat -o out.jsonl
dt transform data.jsonl --preset=alpaca | dt head -

# transform: config-file mode
dt transform data.jsonl                    # first run writes a config file
# edit .dt/data.py, then
dt transform data.jsonl --num=100          # run (output path from the config)

# pipeline (reproducible; a step is a CLI command name)
dt run pipeline.yaml
dt run pipeline.yaml --input=new_data.jsonl --output=result.jsonl
cat data.jsonl | dt run pipeline.yaml -i - | dt head -

# token stats
dt token-stats data.jsonl --field=messages --model=gpt-4
dt token-stats data.jsonl --field=messages[-1].content   # last message only
dt token-stats data.jsonl --field=text --detailed
dt token-stats data.jsonl --workers=4                    # multiprocess (auto for large inputs)

# diff
dt diff v1/train.jsonl v2/train.jsonl
dt diff a.jsonl b.jsonl --key=id
dt diff a.jsonl b.jsonl --key=meta.uuid    # match on a nested field

# clean (no -o -> stdout; -i writes back in place)
dt clean data.jsonl --drop-empty -o out.jsonl       # drop rows with any empty value
dt clean data.jsonl --drop-empty=text,answer -i     # drop rows where these fields are empty, in place
dt clean data.jsonl --drop-empty=meta.source        # nested field -> stdout
dt clean data.jsonl --min-len=text:10               # text at least 10 chars
dt clean data.jsonl --min-len=messages.#:2          # at least 2 messages
dt clean data.jsonl --max-len=messages[-1].content:500
dt clean data.jsonl --keep=question,answer          # keep only these fields (use dt select for more)
dt clean data.jsonl --drop=metadata
dt clean data.jsonl --strip                         # strip whitespace on strings
dt clean data.jsonl --min-tokens=content:10
dt clean data.jsonl --max-tokens=content:1000
dt clean data.jsonl --min-tokens=text:50 -m gpt-4    # choose the tokenizer

# dedupe (exact dedupe streams; stdin ok)
dt dedupe data.jsonl -i                         # exact, whole row, in place
dt dedupe data.jsonl --key=text -o out.jsonl    # by field
dt dedupe data.jsonl --key=meta.id              # nested field -> stdout
dt dedupe data.jsonl --key=messages[0].content  # by first message
dt dedupe data.jsonl --key=text --similar=0.8   # near duplicates

# split
dt split data.jsonl --ratio=0.8 --seed=42           # train/test
dt split data.jsonl --ratio=0.7,0.15,0.15           # train/val/test
dt split data.jsonl --ratio=0.8 -o /tmp/output
dt filter data.jsonl "x.ok" | dt split - -o out/ --name clean   # stdin needs a directory and a prefix

# export for a training framework
dt export data.jsonl --framework=llama-factory
dt export data.jsonl -f swift -o ./swift_out
dt export data.jsonl -f axolotl
dt export data.jsonl -f llama-factory --check        # compatibility check only

# concat (no -o -> stdout; at most one - from stdin)
dt concat a.jsonl b.jsonl -o merged.jsonl
dt concat a.jsonl.gz b.parquet | dt head -

# stats
dt stats data.jsonl                                       # quick
dt stats data.jsonl --schema                              # nested schema (types / non-null rate / list elements / low-cardinality values)
dt stats data.jsonl --full                                # with value distributions
dt stats data.jsonl --full --field=category
dt stats data.jsonl --full --expand=tags                  # element distribution of a list field
dt stats data.jsonl --full --expand='messages[*].role'

# agent skill
dt install-skill                              # ~/.claude/skills/ (default)
dt install-skill --target codex               # ~/.agents/skills/
dt skill-status --target codex

# validate
dt validate data.jsonl --preset=openai_chat
dt validate data.jsonl --preset=alpaca --verbose
dt validate data.jsonl --preset=sharegpt --filter -o valid.jsonl  # keep valid rows (stdout without -o)
dt validate data.jsonl --preset=dpo --max-errors=100
dt validate data.jsonl --preset=openai_chat --workers=4
```

`.jsonl.gz` / `.json.gz` are transparent: every command accepts them (`cat x.jsonl.gz | dt filter - ...` detects the magic bytes), and an output path ending in `.gz` is written compressed. Other formats do not support `.gz` and fail with a usage error. `-o -` means stdout.

### Interactive data browser (dt view)

`dt view <file>` opens a master-detail terminal browser built for training data.

**Table pane**: derived columns `turns/roles/first_user/chars/calls` plus metadata columns. **Detail pane**: the current row rendered by format. Chat turns are colored by role with code blocks highlighted; a tool call is drawn as `[assistant → fn]` followed by `⚙ fn call_id` and its formatted arguments, with a red mark when the arguments are not valid JSON; `reasoning_content` is shown dimmed; a tool result is labelled `[tool ← call_id]` with its JSON formatted; dpo rows show chosen and rejected side by side; alpaca rows are split into sections; generic rows are fully expanded. No drilling down. The layout is side by side by default; `z` switches to top/bottom.

**Large files** are loaded in windows (`--cap`, default 10k rows). Opening a JSONL/NDJSON file indexes and loads only the first window; `]` reads the next one incrementally. The total row count shows as pending until counting finishes or the end of the file is reached. Jumping to a positive row number scans only up to that window; `G` and negative row numbers count rows quickly with Polars and then read the tail window backwards, keeping absolute row numbers without indexing the whole file. Counts and both end indexes are reused, so paging backwards from the tail only fills adjacent windows; only full-file search / filter / sort / export fill the gaps in between. Background work is cancelled with `Esc`. `--offset` needs to scan everything before the target row. `dt view file -100` starts from the last 100 rows without scanning the file; the history index is built on the first backward page, absolute jump or full-file operation. The row-number column widens with the digit count, and narrow terminals keep the full number. The JSONL column catalog scans every record in the current window and grows in first-seen order as you page or jump, without pre-parsing the file; top-level objects and arrays in generic data become columns too. Training formats show the first 8 metadata columns by default and keep the rest in the `c` column panel.

**Live logs**: `dt view app.jsonl --follow` starts at the latest tail window, receives new complete lines in 0.5 s batches, and follows rename rotation and visible truncation. A partial last line stays pending instead of being reported as bad JSON; complete lines that are invalid JSON still show as diagnostic placeholder rows. Moving the cursor up pauses auto-scroll and accumulates new rows; `G` returns to the end and resumes. `/`, `f` and `F` first scan a fixed high-water mark, then apply the same constraint incrementally to new rows; `s` sorts a fixed snapshot and pauses following, `r` resets to live order. `--follow` supports seekable JSONL/NDJSON only; for plain-text logs use `tl --tail FILE`.

| Key | Action |
|------|------|
| `↑/↓` `j/k` | Select row (detail follows) |
| `PgUp/PgDn` | Page · `d/u` (or `Ctrl+d/u`) half page |
| `g/G` | First / last row of the whole sequence; in follow mode `G` resumes following · `Tab` switches focus |
| `←/→` `h/l` | Scroll the table horizontally (`h/l` move 4 characters) |
| `s` | **Full-file sort** (type a column name, prefix `-` to reverse, e.g. `-chars`): scans the whole file, valid across windows |
| `/` `f` | **Full-file search / filter**: `/` searches every value of every record (assistant replies included; `re:` prefix for regex), `f` takes an expression. Both scan the whole file with progress, `Esc` cancels, hits become a pageable subset; `r` clears |
| `F` / click a header | **Column value picker** (Excel AutoFilter style): unique values with counts, a search box narrows the candidates, nothing ticked by default, tick what to keep → subset |
| `n/N` `*` | Move field by field in the detail pane (conversations go turn by turn as `msg0/msg1…`); `*` jumps only between fields **containing a search hit** |
| `w` | **Export** the current subset (or the `v` selection) to a file, format by extension; lineage is written alongside |
| `C` | Copy a `dt view` command that reproduces the current view |
| `S` | Column snapshot: `n·min·max·mean·non-null rate` of one column over the current sequence (full distributions: `dt stats`) |
| `c` | Choose columns (a tick panel that applies to both table columns and detail fields) |
| Drag a header `│` | **Resize columns** (Excel style): the `│` to the right of every header (last column included) is a handle, it turns into `┃` under the mouse with a status-bar hint, drag to resize; double-click restores auto width. Widths are remembered per column name across windows, filters and column sets |
| `y` `v` | Copy the current sample as JSON · `v` multi-select then `y` copies several |
| Drag in detail + `Ctrl+c` | **Select any text with the mouse**: hold the left button and drag (what you see is what you select, wrapped lines stay aligned), `Ctrl+c` copies and clears. Multi-click widens the selection: double-click a word (hyphens and underscores count as word characters), triple-click a line, four clicks a field block, five clicks the whole detail pane; a single click or `Esc` clears. Copying uses OSC52 plus local `wl-copy`/`xclip`/`xsel`, so it reaches your local clipboard over SSH and inside tmux. Dragging in the table means something else (resize / select rows); use `y` for whole samples |
| Drag the split | **Resize the two panes with the mouse**: the border between table and detail is the handle, it brightens under the mouse with a status-bar hint, drag it anywhere (cell by cell, not in 5 % steps); double-click restores the default 65:35. `+/-` still move it in 5 % steps |
| `Enter` | Zoom into the current sample (`Esc` returns) · `z` side-by-side / stacked layout · `+/-` resize panes |
| `?` | Help · `q` quit |

**Search, filter and sort are all full-file and they stack**: `/`, `f`, `F` and `s` always scan the whole file rather than the current window; the resulting sequence of global row numbers becomes the new browsing sequence (paging does not invalidate it), and the status bar shows `hits M/N (ratio)`. The three kinds of constraints have separate slots: one `/` (a new search replaces the old one), `f` stacks (multiple filters are **and**-ed, which expresses `(a or b) and (c or d)` without parentheses), and `F` keeps a per-column "kept values" set so it can be adjusted or widened again. **`r` clears everything and returns to the full file** (the status bar reminds you of this exit while filtered).

**Full-file scans run in parallel**: once the JSONL/NDJSON index is ready, the file is split into byte ranges and handed to a process pool (constraints are serialized to a spec and each worker rebuilds the same predicate). Measured on 300k rows / 440 MB, a `/` search drops from 1.9 s to 0.2 s. `DTFLOW_VIEW_WORKERS=1` forces serial; non-JSONL inputs (CSV / Parquet / stdin) are already in memory and scan serially. Two cases skip the scan entirely: when a new constraint only **tightens** the old one (another `f`, a narrower value set) only the current subset is re-read (worth it when the subset is under 1/10 of the file, otherwise a rescan is faster); and confirming an `F` selection reuses the value → row-number map recorded while scanning the candidates, so there is no second pass.

`/` searches **every value of every record**, not just the table columns: the table is a derived summary, `first_user` is only the first user message, and searching by column would miss assistant replies entirely. Hits are painted yellow in both the table and the detail pane, and `*` walks through them.

**Closing the loop**: export the filtered subset with `w` (`.jsonl` streams, so hundreds of thousands of rows do not touch memory; other extensions go through `save_data`); a lineage sidecar is written automatically, so `dt history <out>` shows the source file and every condition in effect. `C` translates the current view back into a `dt view ... --where=... --search=... --sort=...` command that restores it when pasted (value-picker filters become expressions like `str(x.get('col')) in (...)`; when a truncated table value cannot be restored the command says so and the lineage file is authoritative).

Instant filtering while browsing belongs to view; full distributions (histograms, quantiles, value counts, tokens) belong to `dt stats` / `dt token-stats`.

**Bad lines (invalid JSON) do not block browsing**: `dt view` shows them as placeholder rows (`_parse_error` / `_raw_line` columns), row numbers stay aligned, and `/` finds them; a syntactically broken row is usually exactly what you opened the browser to find. Other commands are split by whether they write a new file: `head`/`tail`/`sample` skip the line and report its number on stderr, while `clean`/`transform` and friends raise with the row number and content instead of dropping data silently.

> **The `f` filter syntax is plain Python**, with the current row named `x`. **Derived column names** from the header (`chars`/`turns`/`roles`/`first_user`/`calls`…) are variables with their raw types (`turns` is an int, `first_user` is the **full text**, not the 160-character table preview); everything else goes through `x.`: `turns>=6 and chars<2000`, `x.source=='alpaca'`, `len(x.messages)>=2`, `x.messages[-1].role=='assistant'`. `and`/`or`/`not` and parentheses work as usual.
>
> **Contains**: `'refund' in first_user`, `'get_weather' in calls` (agent samples that called that function; a non-empty `calls` means the sample has tool calls), `'error' in x.messages[0].content`, `any('keyword' in m.content for m in x.messages)` (whole conversation). `in` is case-sensitive; write `'word' in first_user.lower()` for case-insensitive. `/` search and the value-picker search box are always case-insensitive.

Formats are auto-detected: `openai_chat` / `sharegpt` / `dpo` / `alpaca` / `generic` (tables such as CSV show every column). `--format` forces one.

`dt head/sample/tail/slice --pretty` reuse the same rendering for a static one-shot preview (and degrade to NDJSON when piped, which is agent friendly).

### Field path syntax

Field arguments of CLI commands accept nested paths:

| Syntax | Meaning | Example |
|------|------|------|
| `a.b.c` | nested field | `meta.source` |
| `a[0].b` | list index | `messages[0].role` |
| `a[-1].b` | negative index | `messages[-1].content` |
| `a.#` | list length | `messages.#` |
| `a[*].b` | expand every element | `messages[*].role` |
| `a[*].b:join` | expand and join with `\|` | `messages[*].role:join` |
| `a[*].b:unique` | expand, dedupe, join | `messages[*].role:unique` |

Arguments that take field paths:

| Command | Argument | Example |
|------|------|------|
| `sample` | `--by=` | `--by=meta.source`, `--by=messages.#` |
| `dedupe` | `--key=` | `--key=meta.id`, `--key=messages[0].content` |
| `clean` | `--drop-empty=` | `--drop-empty=meta.source` |
| `clean` | `--min-len=` | `--min-len=messages.#:2` |
| `clean` | `--max-len=` | `--max-len=messages[-1].content:500` |
| `clean` | `--min-tokens=` | `--min-tokens=content:10` |
| `clean` | `--max-tokens=` | `--max-tokens=content:1000` |
| `token-stats` | `--field=` | `--field=messages[-1].content` |
| `diff` | `--key=` | `--key=meta.uuid` |

Field paths are for arguments that **name one field** (`--key`, `--by` for stratified sampling, `--field`, `--drop-empty`, `--min-len`, …). **Filtering and deriving use expressions** (next section); inside an expression the path DSL is available as `get(x, "messages[*].role:join")`.

### Expression syntax

Conditions in `filter` / `select` / `map` / `sort --by` / `group --by` / `join --on` / `sample --where` / `view --where` and in pipelines are all **Python expressions** with the current row as `x` (attribute access works: `x.messages[-1].role`, `x.meta.source`; a missing field raises AttributeError). The namespace also has `re` / `json` / `math` / `get` (the field-path DSL).

```bash
dt filter d.jsonl "x.score > 0.8 and 'wiki' in x.meta.source"
dt filter d.jsonl "len(x.messages) >= 2 and x.messages[-1].role == 'assistant'"
dt filter d.jsonl "any('refund' in m.content for m in x.messages)"
dt filter d.jsonl "re.search(r'\d{4}', x.text) and x.lang in ('zh', 'en')"
dt select d.jsonl "id,n=len(x.messages),roles=[m.role for m in x.messages]"
dt map    d.jsonl "x.text = x.text.strip(); x.messages.append({'role': 'assistant', 'content': x.a})"
```

Rows whose expression fails (missing field, `None > 0.5`) do not abort by default; a summary is printed to stderr at the end. `filter` treats them as non-matching, `select` sets the item to `null`, `map` keeps the row unchanged, `sort` puts them last, `group --agg` sets the item to `null` (map/select/group are one-in-one-out, no rows vanish). `--strict` exits with code 1 on the first error. A bare field name without `x.` (`score > 0.5`) is rejected at compile time with exit code 2 instead of failing on every row with zero matches. Syntax errors exit 2 with the position. There is no sandbox: this is a tool running in your own shell, like `dt transform` running `.dt/*.py`. Field-path arguments (`--key`, `--by` for sample, `--field`) written as `x.meta.s` are rejected with a hint to drop the `x.`.

Migrating from the old syntax (the `field op value` form was removed in 0.9):

| Old | New |
|----|----|
| `category=tech` | `x.category=='tech'` |
| `content~=machine learning` (contains, case-insensitive) | `'machine learning' in x.content.lower()` |
| `score>0.8` / `messages.#>=2` | `x.score>0.8` / `len(x.messages)>=2` |
| `messages[0].role=user` | `x.messages[0].role=='user'` |
| `messages[*].content:join~=word` | `any('word' in m.content for m in x.messages)` |
| in view: `turns>=6 and chars<2000` | unchanged; `source==alpaca` → `x.source=='alpaca'`; `first_user~=refund` → `'refund' in first_user` |
| pipeline `condition: "len(text) > 10"` / `field: text` | `expr: "len(x.text) > 10"` / `expr: "x.text"` |
| `dt clean f.jsonl --strip` (used to overwrite the file) | `dt clean f.jsonl --strip -i`; without `-i`/`-o` output goes to stdout |

Example row:
```json
{"meta": {"source": "wiki"}, "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]}
```

- `meta.source` → `"wiki"`
- `messages[0].role` → `"user"`
- `messages[-1].content` → `"hello"`
- `messages.#` → `2`
- `messages[*].role` → `"user"` (first element by default)
- `messages[*].role:join` → `"user|assistant"`

### Pipelines

Freeze a chain of commands in YAML and run it reproducibly. **A step's `type` is the CLI command name and its parameters are the CLI option names** (underscored), so there is one syntax for both:

```yaml
# pipeline.yaml
version: "1.0"
seed: 42
input: raw_data.jsonl
output: processed.jsonl

steps:
  - type: filter
    expr: "x.score > 0.5 and len(x.text) > 10"
  - type: select
    fields: "id,text,n=len(x.messages)"
  - type: clean
    strip: true
    drop_empty: text
    min_len: "text:10"
  - type: dedupe
    key: text
  - type: transform
    preset: openai_chat
    params: {user_field: q, assistant_field: a}
  - type: split            # must be last: writes processed_train.jsonl / processed_test.jsonl next to output
    ratio: 0.9
    seed: 42
```

| Step | Parameters (= CLI options) | Notes |
|------|------|------|
| `filter` | `expr`, `strict` | Python expression |
| `select` | `fields`, `strict` | project / rename / derive |
| `map` | `code`, `strict` | mutate in place |
| `explode` | `field`, `as`, `index_as` | one row per list element |
| `sort` | `by`, `desc` | sort (whole input) |
| `shuffle` | `seed` | shuffle (whole input) |
| `group` | `by`, `agg` | group count / aggregate |
| `join` | `right`, `on` or `left_on`+`right_on`, `inner`, `prefix` | key join |
| `dedupe` | `key`, `similar` | exact / near-duplicate |
| `sample` / `head` / `tail` | `num`, `seed` | sample / first or last N |
| `clean` | `strip`, `drop_empty`, `min_len`, `max_len`, `keep`, `drop`, `rename`, `promote`, `add_field`, `fill`, `reorder`, `min_tokens`, `max_tokens`, `model` | same as `dt clean` |
| `transform` | `preset` + `params`, or `config` | preset / `.dt/*.py` config |
| `split` | `ratio`, `seed` | terminal step, writes several files |

Execution is streaming: steps that can be lazy do not hold the data in memory. `dt run pipeline.yaml --dry-run` validates the config (expression syntax included) and prints the step chain.

```bash
dt run pipeline.yaml
dt run pipeline.yaml --input=new_data.jsonl --output=result.jsonl
cat data.jsonl | dt run pipeline.yaml -i - | dt head -     # without output, data goes to stdout
```

### Data lineage

Record the full processing history for reproducibility and debugging:

```python
dt = DataTransformer.load("raw.jsonl", track_lineage=True)

result = (dt
    .filter(lambda x: x.score > 0.5)
    .transform(lambda x: {"q": x.q, "a": x.a})
    .dedupe("q")
)

result.save("processed.jsonl", lineage=True)
# writes processed.jsonl.lineage.json
```

```bash
dt history processed.jsonl
# 📊 lineage report: processed.jsonl
# └─ version 1
#    source: raw.jsonl
#    operations:
#      ├─ filter: 1000 → 800
#      ├─ transform: 800 → 800
#      └─ dedupe: 800 → 750
#    output rows: 750

dt history processed.jsonl --json
```

### Log viewer

dtflow bundles the [toolong](https://github.com/Textualize/toolong) log viewer:

```bash
pip install dtflow[logs]

tl app.log                  # interactive TUI
tl --tail app.log           # follow (like tail -f)
dt logs                     # usage
```

### Streaming for huge files

A streaming interface with O(1) memory for JSONL/NDJSON, CSV/TSV, Parquet and Arrow:

```python
from dtflow import load_stream, load_sharded

# constant memory, even for a 100 GB file
(load_stream("huge_100gb.jsonl")
    .filter(lambda x: x["score"] > 0.5)
    .transform(lambda x: {"text": x["content"]})
    .save("output.jsonl"))

# cross-format (CSV -> Parquet)
(load_stream("data.csv")
    .filter(lambda x: x["score"] > 0.5)
    .save("output.parquet"))

# sharded inputs
(load_sharded("data/train_*.parquet")
    .filter(lambda x: len(x["text"]) > 10)
    .save("merged.jsonl"))

# sharded output
(load_stream("huge.jsonl")
    .transform(lambda x: {"q": x["question"], "a": x["answer"]})
    .save_sharded("output/", shard_size=100000))
# output/part-00000.jsonl, output/part-00001.jsonl, ...

# batches (for batched API calls)
for batch in load_stream("data.jsonl").batch(1000):
    results = call_api(batch)
```

- **Lazy**: filter/transform run only on save/collect
- **O(1) memory** on the read side regardless of file size
- **Multi-format**: JSONL/NDJSON, CSV/TSV, Parquet, Arrow
- **Cross-format**: read CSV, write Parquet
- **Shards**: glob patterns load and merge multiple files

## Error handling

```python
dt.to(transform_func, on_error="skip")    # skip failing rows (default)
dt.to(transform_func, on_error="raise")   # raise
dt.to(transform_func, on_error="keep")    # keep the original row

result, errors = dt.to(transform_func, return_errors=True)
```

## Design

### Functions over class hierarchies

```python
# ✅ this
dt.to(lambda x: {"q": x.question, "a": x.answer})

# ❌ not this
class MyFormatter(BaseFormatter):
    def format(self, item): ...
```

### Presets are a convenience layer, not the core abstraction

90 % of needs are covered by `transform(lambda x: ...)`. Presets are shortcuts for the common cases:

```python
dt.to(preset="openai_chat")

dt.to(lambda x: {
    "messages": [
        {"role": "user", "content": x.q},
        {"role": "assistant", "content": x.a}
    ]
})
```

### KISS

- One core class, `DataTransformer`, does everything
- A chainable API that reads like prose
- Attribute access `x.field` instead of `x["field"]`
- No framework ambitions, no over-design

### Pragmatism

Tools that are good enough to use every day, not the perfect abstraction.

## License

MIT
