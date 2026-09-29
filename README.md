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

`dt view` opens an SFT / DPO / agent JSONL file as a table-plus-detail browser: conversations rendered as colored chat turns, tool calls formatted with bad JSON flagged, full-file search across every field, mouse support, and windowed loading that keeps a 900k-line file under 100 MB of RAM. The rest of `dt` is a pipeable Unix-style toolkit for the same data, where every condition is plain Python.

<p align="center">
  <img src="https://raw.githubusercontent.com/KenyonY/dtflow/main/docs/images/view/demo.gif" alt="dt view: table + detail terminal browser with full-file search, filters, value picker, zoom and dpo comparison" width="900">
</p>
<p align="center"><sub><code>dt view data.jsonl</code> — one command turns a training set into a searchable, filterable terminal browser</sub></p>

## Try it in 30 seconds

```bash
pip install dtflow                      # or, without installing: uvx --from dtflow dt view data.jsonl

dt view data.jsonl                                              # browse (press ? for keys)
dt stats data.jsonl --schema                                    # nested schema: types, null rates, values
dt filter data.jsonl "len(x.messages) >= 2 and x.messages[-1].role == 'assistant'" \
  | dt select - "id,turns=len(x.messages),last=x.messages[-1].content" \
  | dt sort - --by x.turns --desc | dt head - 5
dt transform data.jsonl --preset=openai_chat -o train.jsonl     # sharegpt / alpaca / dpo → OpenAI messages
```

Reads JSONL/NDJSON (also `.gz`), JSON, CSV/TSV, Parquet, Arrow and Excel. Every data command accepts `-` for stdin and writes to stdout when no `-o` is given, so everything composes.

## Why dtflow

- **It knows what a training sample is.** Generic table tools show `messages` as `{3}` or a truncated string. `dt view` detects `openai_chat` / `sharegpt` / `dpo` / `alpaca` and renders one complete sample per screen: turns colored by role, code highlighted, `tool_calls` and `reasoning_content` unpacked, malformed tool arguments flagged.
- **Conditions are Python, not a DSL.** `x.score > 0.8 and 'wiki' in x.meta.source`, `any('refund' in m.content for m in x.messages)`. One expression language across `filter`, `select`, `map`, `sort`, `group`, `join`, the viewer and YAML pipelines.
- **Built for agents as much as humans.** stdout carries only data, stderr carries messages, exit codes are contractual, `dt schema` prints the machine-readable command tree, and `dt install-skill` teaches Claude Code or Codex the whole tool in one command.
- **Streams by default.** `filter` / `select` / `map` / `clean` / `dedupe` / `transform` never load the file; the viewer opens a 910k-row JSONL at ~90 MB RSS with parallel full-file scans.

## dt view: browse training data in the terminal

`dt view <file>` opens a master-detail browser. The **table** summarizes each sample (derived columns `turns/roles/first_user/chars/calls` plus your metadata); the **detail** pane renders the current row by format. JSONL, CSV and Parquet all open, and files with hundreds of thousands of lines open instantly.

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

Full key list, filter syntax, large-file and follow-mode details: [docs/view.md](docs/view.md).

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

## The CLI: a Swiss army knife for training data

Every data command follows one contract: `FILE` may be `-` (NDJSON from stdin); without `-o` data goes to stdout while progress and summaries go to stderr. Conditions, derived fields, sort keys, group keys and join keys are **Python expressions with the current row as `x`**.

```bash
# primitives
dt filter  data.jsonl "x.score > 0.5 and 'wiki' in x.meta.source"
dt select  data.jsonl "id,text,n=len(x.messages),src=x.meta.source"     # project / rename / derive
dt map     data.jsonl "x.text = x.text.strip(); del x.debug"            # edit in place
dt explode data.jsonl --field messages --index-as turn                  # one row per list element
dt sort    data.jsonl --by "len(x.messages)" --desc
dt group   data.jsonl --by x.meta.source                                # {"key","count"} sorted by count
dt group   data.jsonl --by x.label --agg "avg=mean(len(r.text) for r in g)"
dt join    data.jsonl meta.jsonl --on x.id --prefix m_                  # left join, right side in memory
dt dedupe  data.jsonl --key=messages[0].content -i                      # exact dedupe, in place
dt clean   data.jsonl --drop-empty=text --min-len=messages.#:2 -o clean.jsonl
dt split   data.jsonl --ratio=0.9 --seed=42                             # train/test files
dt stats   data.jsonl --schema                                          # look before you write expressions

# pipes
dt filter d.jsonl "x.score>0.5" | dt select - "id,n=len(x.messages)" | dt sort - --by x.n --desc | dt head - 5
cat big.jsonl.gz | dt filter - "x.lang=='zh'" | dt transform - --preset=openai_chat | dt view -
dt group d.jsonl --by x.label | dt sort - --by x.count --desc

# and the rest
dt sample data.jsonl 1000 --by=meta.source      # stratified sampling
dt token-stats data.jsonl --model=gpt-4         # token distribution per role
dt validate data.jsonl --preset=openai_chat     # schema check, --filter to keep valid rows
dt diff a.jsonl b.jsonl --key=id                # what changed between two versions
dt export data.jsonl -f llama-factory           # data + config for LLaMA-Factory / ms-swift / Axolotl
dt run pipeline.yaml                            # reproducible pipeline, steps = CLI commands
```

Rows whose expression fails (missing field, `None > 0.5`) don't abort the run: `filter` drops them, `select` sets the item to `null`, `map` keeps the row, and stderr prints one summary at the end. `--strict` turns the first failure into exit code 1. A bare field name without `x.` is rejected at compile time instead of silently matching nothing.

Command reference: [docs/cli.md](docs/cli.md) · expressions and field paths: [docs/expressions.md](docs/expressions.md) · pipelines: [docs/pipeline.md](docs/pipeline.md).

## Python API

The same operations as a chainable class; `x.field` attribute access works on nested dicts and lists.

```python
from dtflow import DataTransformer, load_stream

(DataTransformer.load("data.jsonl")
    .filter(lambda x: x.score > 0.8 and len(x.messages) >= 2)
    .to(preset="openai_chat", user_field="q", assistant_field="a")
    .dedupe("messages[0].content")
    .save("train.jsonl"))

(load_stream("huge.jsonl")                 # constant memory for files that don't fit
    .filter(lambda x: x["score"] > 0.5)
    .save("filtered.parquet"))
```

Presets (`openai_chat`, `alpaca`, `sharegpt`, `dpo_pair`), schema validation, token counting with tiktoken or HuggingFace tokenizers, converters for LLaMA-Factory / ms-swift / Axolotl / HuggingFace datasets / OpenAI Batch, lineage tracking: [docs/python-api.md](docs/python-api.md).

## Agent skill

```bash
dt install-skill                         # Claude Code (default)
dt install-skill --target codex          # Codex
```

After installing, `/dtflow` in Claude Code or `$dtflow` in Codex gives the agent the full reference. The CLI itself is designed to be driven by an agent: `dt schema` prints the command tree as JSON, `dt <cmd> --help` carries examples, `--dry-run` previews every side-effecting command with exit code 10, and errors are structured JSON on stderr when stdout is not a terminal.

## Documentation

- [Quickstart](docs/quickstart.md)
- [CLI reference](docs/cli.md)
- [`dt view`](docs/view.md)
- [Expressions and field paths](docs/expressions.md) (includes the 0.9 migration table)
- [Pipelines](docs/pipeline.md)
- [Python API](docs/python-api.md)
- [Changelog](CHANGELOG.md)

## Design

- **Functions over class hierarchies.** `dt.to(lambda x: {...})` instead of `class MyFormatter(BaseFormatter)`. Presets are conveniences, not the core abstraction.
- **One expression language.** Python is already the DSL. The viewer, the CLI and the pipeline compile the same string with the same engine.
- **One contract.** `DataTransformer` in memory, `StreamingTransformer` for everything that shouldn't fit, and a CLI contract (stdout = data, stderr = messages, exit codes mean things) that never bends.

## License

MIT
