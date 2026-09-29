# Quickstart

## Install

```bash
pip install dtflow
# or try without installing
uvx --from dtflow dt view data.jsonl
```

Optional extras: `dtflow[tokenizers-hf]` (HuggingFace tokenizers), `dtflow[converters]` (HuggingFace datasets), `dtflow[similarity]` (near-duplicate removal), `dtflow[logs]` (toolong log viewer), `dtflow[eval]` (model-output scoring), `dtflow[full]`.

## Look at the data first

```bash
dt view data.jsonl            # interactive browser: ? shows the keys, / searches, f filters, w exports
dt stats data.jsonl --schema  # nested structure: types, non-null rates, low-cardinality values
dt head data.jsonl --pretty   # first rows rendered as conversations
```

## Filter, reshape, pipe

Conditions are Python; the current row is `x`.

```bash
dt filter data.jsonl "len(x.messages) >= 2 and x.messages[-1].role == 'assistant'" \
  | dt select - "id,turns=len(x.messages),last=x.messages[-1].content" \
  | dt sort - --by x.turns --desc \
  | dt head - 5

dt group data.jsonl --by x.meta.source              # distribution
dt dedupe data.jsonl --key=messages[0].content -i   # in place
dt clean data.jsonl --drop-empty=text --strip -o clean.jsonl
dt split clean.jsonl --ratio=0.9 --seed=42          # clean_train.jsonl / clean_test.jsonl
```

## Convert and export

```bash
dt transform data.jsonl --preset=openai_chat -o train.jsonl   # sharegpt / alpaca / dpo → messages
dt export train.jsonl -f llama-factory                        # data + dataset_info.json + train_args.yaml
```

## Same thing in Python

```python
from dtflow import DataTransformer, load_stream

(DataTransformer.load("data.jsonl")
    .filter(lambda x: x.score > 0.8)
    .to(preset="openai_chat", user_field="q", assistant_field="a")
    .dedupe("messages[0].content")
    .save("train.jsonl"))

(load_stream("huge.jsonl")                 # constant memory
    .filter(lambda x: x["score"] > 0.5)
    .save("filtered.parquet"))
```

## Freeze it as a pipeline

```yaml
# pipeline.yaml
input: data.jsonl
output: train.jsonl
steps:
  - type: filter
    expr: "len(x.messages) >= 2"
  - type: dedupe
    key: messages[0].content
  - type: transform
    preset: openai_chat
```

```bash
dt run pipeline.yaml --dry-run   # validate, print the steps
dt run pipeline.yaml
```

## Next

- [CLI reference](cli.md)
- [`dt view`](view.md)
- [Expressions and field paths](expressions.md)
- [Pipelines](pipeline.md)
- [Python API](python-api.md)
