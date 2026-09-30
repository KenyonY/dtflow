# Pipelines

Freeze a chain of commands in YAML and run it reproducibly with `dt run`. **A step's `type` is the CLI command name and its parameters are the CLI option names** (underscored), so there is one syntax for the shell and for the file.

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

```bash
dt run pipeline.yaml
dt run pipeline.yaml --input=new_data.jsonl --output=result.jsonl
cat data.jsonl | dt run pipeline.yaml -i - | dt head -     # without output, data goes to stdout
dt run pipeline.yaml --dry-run                             # validate and print the step chain, exit 10
```

## Steps

| Step | Parameters (= CLI options) | Notes |
|------|------|------|
| `filter` | `expr`, `strict` | Python expression |
| `select` | `fields`, `strict` | project / rename / derive |
| `map` | `code`, `strict` | mutate in place |
| `explode` | `field`, `as`, `index_as` | one row per list element |
| `sort` | `by`, `desc`, `strict` | sort (whole input) |
| `shuffle` | `seed` | shuffle (whole input) |
| `group` | `by`, `agg`, `strict`, `top` | group count (with `pct`) / aggregate; `top` keeps the N largest groups |
| `join` | `right`, `on` or `left_on`+`right_on`, `inner`, `prefix` | key join, right side loaded from a file |
| `dedupe` | `key`, `similar` | exact / near-duplicate |
| `sample` / `head` / `tail` | `num`, `seed` | sample / first or last N |
| `clean` | `strip`, `drop_empty`, `min_len`, `max_len`, `keep`, `drop`, `rename`, `promote`, `add_field`, `fill`, `reorder`, `min_tokens`, `max_tokens`, `model` | same as `dt clean` |
| `transform` | `preset` + `params`, or `config` | preset / `.dt/*.py` config |
| `split` | `ratio`, `seed` | terminal step, writes `<output>_train`, `_val`, `_test` |

Execution is streaming: steps that can be lazy do not hold the data in memory. `split` must be the last step.

## Validation

`dt run --dry-run` (and `validate_pipeline()` in Python) checks before anything runs:

- unknown step types and **unknown parameters** (a typo like `stirp: true` is an error, not a silently ignored key)
- required parameters (`filter.expr`, `select.fields`, `sort.by`, `join.right`, …)
- expression syntax, with the position marked
- `split` not being last; `join` given both `on` and `left_on`

Errors come back as a list on stderr (JSON when not a terminal) with exit code 2.

## Python

```python
from dtflow.pipeline import run_pipeline, build_pipeline

run_pipeline("pipeline.yaml")                                   # {"output": ..., "rows": n}
run_pipeline("pipeline.yaml", input_file="a.jsonl", output_file="b.jsonl")

st = build_pipeline(config_dict, "a.jsonl")                     # a lazy StreamingTransformer
for row in st: ...
```

`generate_pipeline_template("data.jsonl", "pipeline.yaml")` writes a starting config inferred from the first row.
