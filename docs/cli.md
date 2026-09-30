# CLI reference

`dt` is the command. `dtflow` is an alias. `dt --help` lists everything, `dt <cmd> --help` has examples, and `dt schema [cmd]` prints the same information as JSON for programs and agents.

## Conventions every data command follows

- **`FILE` may be `-`**: read NDJSON from stdin. `.gz` input is detected by magic bytes.
- **No `-o` → data goes to stdout** as NDJSON (`--format json|csv` for whole documents). Progress, warnings and summaries go to stderr, so stdout is always machine-readable. When stdout is a terminal and no format is forced, only the first 50 rows are shown as a preview.
- **`-o FILE`** writes the file (atomically, via a temp file in the same directory) and prints an action summary: a panel on stderr in a terminal, a JSON object on stdout otherwise.
- **`-o -`** is the same as no `-o`.
- **`-i` / `--in-place`** (clean, dedupe) writes back to the input file. Nothing overwrites your input unless you ask.
- **`--dry-run`** on every side-effecting command runs the whole computation, writes nothing, prints the summary and exits with code 10.
- **Formats**: JSONL/NDJSON (also `.gz`), JSON (also `.gz`), CSV/TSV, Parquet, Arrow/Feather, Excel, FlaxKV. Output format follows the extension. Only `.jsonl.gz` / `.json.gz` support compressed output.
- **Exit codes**: 0 ok · 1 runtime error · 2 usage error · 3 not found · 4 permission · 5 conflict · 10 dry-run ok. Errors are JSON on stderr (`{error, message, suggestion, exit_code, context}`) when stderr is not a terminal.
- **Language**: messages, help and `dt view` are in English by default. `dt lang zh` switches everything to Chinese and `dt lang en` switches back. The choice is saved in `~/.config/dtflow/config.json`; the `DT_LANG` environment variable overrides it for one run. Machine-readable output (JSON keys, error codes) is the same in both languages.
- **Expressions** (`filter`, `select`, `map`, `sort --by`, `group --by`, `join --on`, `--where`) are Python with the row as `x`; **field paths** (`--key`, `--by` for sampling, `--field`, `--drop-empty`, `--min-len`, …) name one field with the `a.b[0].c` syntax. See [expressions.md](expressions.md).

## Primitives (compose with pipes)

```bash
dt filter  data.jsonl "x.score > 0.5 and 'wiki' in x.meta.source"
dt filter  data.jsonl "len(x.messages) >= 2 and x.messages[-1].role == 'assistant'"
dt select  data.jsonl "id,text,n=len(x.messages),src=x.meta.source"   # project / rename / derive
dt map     data.jsonl "x.text = x.text.strip(); del x.debug"          # mutate in place
dt explode data.jsonl --field messages --index-as turn                # one row per list element
dt sort    data.jsonl --by "len(x.messages)" --desc
dt shuffle data.jsonl --seed 42 -o shuffled.jsonl
dt group   data.jsonl --by x.meta.source                              # {"key","count"} sorted by count
dt group   data.jsonl --by x.label --agg "avg=mean(len(r.text) for r in g),ids=[r.id for r in g][:3]"
dt join    data.jsonl meta.jsonl --on x.id --prefix m_                # left join, right side in memory
dt stats   data.jsonl --schema                                        # nested schema: see the shape before writing expressions

dt filter d.jsonl "x.score>0.5" | dt select - "id,n=len(x.messages)" | dt sort - --by x.n --desc | dt head - 5
dt sample d.jsonl 0 -w "x.ok" | dt clean - --strip | dt dedupe - --key=text -o clean.jsonl
dt group d.jsonl --by x.label | dt sort - --by x.count --desc
cat big.jsonl.gz | dt filter - "x.lang=='zh'" | dt transform - --preset=openai_chat | dt view -
```

| Command | What it does | Memory |
|---------|--------------|--------|
| `filter FILE EXPR` | keep rows where the expression is true | streaming |
| `select FILE FIELDS` | `id,text,n=len(x.m)`: literal field names (omitted when missing) and `name=expr` derived fields; output key order = spec order | streaming |
| `map FILE CODE` | run statements on every row, mutating `x` in place | streaming |
| `explode FILE --field F [--as NAME] [--index-as I]` | one row per element of a list field; non-list rows pass through | streaming |
| `sort FILE --by EXPR [--desc]` | sort; rows whose key fails go last | whole input |
| `shuffle FILE [--seed]` | uniform shuffle | whole input |
| `group FILE --by EXPR [--agg SPEC]` | count per key (sorted by count) or custom aggregates with `g` (rows of the group), `key`, `n`, `mean`, `median` | counts stream |
| `join LEFT RIGHT --on EXPR [--left-on/--right-on] [--inner] [--prefix P]` | left join, left side streams, right side in memory; left fields win on conflict; duplicate right keys keep the first | right side |
| `stats FILE --schema [--sample N]` | nested schema inferred from the first N rows (types, non-null rates, list element types, low-cardinality values) | N rows |

Failure policy (`--strict` to fail fast instead): `filter` drops the row, `select` sets the item to `null`, `map` keeps the row, `sort` puts the row last, `group --agg` sets the item to `null`. One summary line on stderr at the end.

## Sampling and previews

```bash
dt sample data.jsonl --num=10
dt sample data.csv --num=100 --type=head
dt sample data.jsonl 1000 --by=category           # stratified
dt sample data.jsonl 1000 --by=meta.source        # stratified by nested field
dt sample data.jsonl 1000 --by=messages.#         # stratified by message count
dt sample data.jsonl 1000 --by=label --dist='{"A":0.5,"B":0.5}'
dt sample data.jsonl --where="x.category=='tech'"        # filter then sample (-w repeatable, AND)
dt sample data.jsonl -w "len(x.messages)>=2" -w "x.score>0.8"

dt head data.jsonl 20 · dt tail data.jsonl 20
dt head data.jsonl --pretty                       # format-aware rendering (chat bubbles / dpo / alpaca / table)
dt slice data.jsonl 10:20                         # rows 10-19 (0-based, half open); :100, 100:, -10:
dt slice data.jsonl 10:20 -f question,answer      # only these fields
```

In a terminal, previews print one pretty JSON object per row; `--pretty` or `--format=table` uses the same rendering as `dt view`. When piped they emit NDJSON.

## Interactive browser

```bash
dt view data.jsonl                                # open, ? for keys
dt view data.jsonl -100                           # start at the last 100 rows
dt view app.jsonl -100 -f                         # follow the last 100 rows and log rotation
dt view data.csv                                  # CSV / Parquet / any table
dt view data.jsonl --format=dpo                   # force the detail format
dt view big.jsonl --cap=50000                     # raise the window size (default 10k rows)
dt view data.jsonl -S -chars                      # start sorted (longest first)
dt view data.jsonl -w "turns>=6" -s error         # start filtered + searched
dt sample data.jsonl 500 | dt view -              # browse the output of a pipeline
```

Everything about the viewer: [view.md](view.md).

## Converting between training formats

Presets detect the input shape (OpenAI `messages`, ShareGPT `conversations`, Alpaca, DPO, `q`/`a`) and convert to the target; tool calls survive the ShareGPT ↔ OpenAI round trip (`function_call`/`observation` ↔ `tool_calls`/`tool`). Rows of an unrecognised shape are skipped and summarised on stderr instead of producing empty content.

```bash
dt transform data.jsonl --preset=openai_chat -o out.jsonl   # openai_chat | alpaca | sharegpt | dpo_pair | simple_qa
dt transform sharegpt.jsonl --preset=openai_chat | dt view -
dt transform data.jsonl --preset=alpaca | dt head -

dt transform data.jsonl                    # config mode, first run writes .dt/data.py
# edit .dt/data.py (a Python transform(item) function with the fields pre-filled), then
dt transform data.jsonl --num=100          # run (output path from the config)
dt transform data.jsonl --preset=alpaca --dry-run
```

## Cleaning, deduplicating, splitting

```bash
dt clean data.jsonl --drop-empty -o out.jsonl       # drop rows with any empty value
dt clean data.jsonl --drop-empty=text,answer -i     # drop rows where these fields are empty, in place
dt clean data.jsonl --drop-empty=meta.source        # nested field -> stdout
dt clean data.jsonl --min-len=text:10               # text at least 10 chars
dt clean data.jsonl --min-len=messages.#:2          # at least 2 messages
dt clean data.jsonl --max-len=messages[-1].content:500
dt clean data.jsonl --keep=question,answer          # keep only these fields (use dt select for more)
dt clean data.jsonl --drop=metadata
dt clean data.jsonl --rename=old:new --promote=meta.label --add-field=source:v2 --fill=lang:en --reorder=id,text
dt clean data.jsonl --strip                         # strip whitespace on strings
dt clean data.jsonl --min-tokens=content:10 --max-tokens=content:1000 -m gpt-4

dt dedupe data.jsonl -i                         # exact, whole row, in place
dt dedupe data.jsonl --key=text -o out.jsonl    # by field (streams)
dt dedupe data.jsonl --key=messages[0].content  # by first message -> stdout
dt dedupe data.jsonl --key=text --similar=0.8   # near duplicates (MinHash, needs dtflow[similarity])

dt split data.jsonl --ratio=0.8 --seed=42           # train/test
dt split data.jsonl --ratio=0.7,0.15,0.15           # train/val/test
dt split data.jsonl --ratio=0.8 -o /tmp/output
dt filter data.jsonl "x.ok" | dt split - -o out/ --name clean   # stdin needs a directory and a prefix

dt concat a.jsonl b.jsonl -o merged.jsonl           # no -o -> stdout; at most one - from stdin
dt concat a.jsonl.gz b.parquet | dt head -
```

## Inspecting

```bash
dt stats data.jsonl                                       # quick: rows + field types from the head
dt stats data.jsonl --schema                              # nested schema
dt stats data.jsonl --full                                # value distributions, unique counts
dt stats data.jsonl --full --field=category --expand=tags
dt stats data.jsonl --full --expand='messages[*].role'

dt token-stats data.jsonl --field=messages --model=gpt-4  # per-role token distribution
dt token-stats data.jsonl --field=messages[-1].content
dt token-stats data.jsonl --field=text --detailed --workers=4

dt validate data.jsonl --preset=openai_chat               # openai_chat | alpaca | dpo | sharegpt
dt validate data.jsonl --preset=sharegpt --filter -o valid.jsonl   # keep valid rows (stdout without -o)
dt validate data.jsonl --preset=dpo --max-errors=100 --workers=4

dt diff v1/train.jsonl v2/train.jsonl
dt diff a.jsonl b.jsonl --key=meta.uuid                   # match rows on a (nested) key

dt history processed.jsonl                                # lineage sidecar written by dt view export or the Python API
```

## Exporting to a training framework

```bash
dt export data.jsonl --framework=llama-factory       # data + dataset_info.json + train_args.yaml
dt export data.jsonl -f swift -o ./swift_out         # data.jsonl + train_swift.sh
dt export data.jsonl -f axolotl                      # data.jsonl + config.yaml
dt export data.jsonl -f llama-factory --check        # compatibility check only
```

## Pipelines

```bash
dt run pipeline.yaml
dt run pipeline.yaml --input=new_data.jsonl --output=result.jsonl
cat data.jsonl | dt run pipeline.yaml -i - | dt head -
dt run pipeline.yaml --dry-run                       # validate (expressions included) and print the steps
```

See [pipeline.md](pipeline.md).

## Model outputs

```bash
dt eval results.jsonl --label-col=label --extract "tag:answer | json_key:label"   # parse model outputs and score them
```

`dt eval` parses a column of model responses with a small pipeline of extractors (`direct`, `tag:X`, `json_key:X`, `index:N`, `line:N`, `regex:X`), compares to labels and writes a report directory with `result.jsonl` and `bad_case.jsonl`. Needs `dtflow[eval]`.

## For agents

```bash
dt schema                # command tree as JSON (names, options, choices, examples)
dt schema filter         # one command
dt install-skill         # SKILL.md into Claude Code (~/.claude/skills/); --target codex for Codex
dt skill-status
```

Rules the CLI keeps so an agent can rely on it: stdout is data only; stderr is messages; errors are structured JSON when stderr is not a terminal; exit codes are contractual; `--dry-run` exits 10; `dt stats --schema` shows the shape of a file before you write an expression; a bare field name in an expression (`score > 0.5`) is a usage error with the fix in the message.
