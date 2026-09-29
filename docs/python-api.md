# Python API

Everything the CLI does is available as a chainable class. `DataTransformer` holds the data in memory; `StreamingTransformer` is lazy and uses constant memory. Rows are plain dicts; inside callbacks `x.field` attribute access works on nested dicts and lists (`DictWrapper`).

## Load, save, chain

```python
from dtflow import DataTransformer

# JSONL/NDJSON (.gz too), JSON, CSV/TSV, Parquet, Arrow, Excel (Polars engine)
dt = DataTransformer.load("data.jsonl")
dt = DataTransformer([{"q": "question", "a": "answer"}])

(dt.filter(lambda x: x.score > 0.8)
   .to(lambda x: {"q": x.question, "a": x.answer})
   .save("output.jsonl"))

dt.sample(100)           # random sample
dt.head(10); dt.tail(10)
dt.shuffle(seed=42)
train, test = dt.split(ratio=0.8, shuffle=True, seed=42)
stats = dt.stats()
count = dt.count(lambda x: x.score > 0.9)
dt.dedupe("messages[0].content")            # field path, or a list of paths, or a callable
dt.dedupe_similar("text", threshold=0.8)    # MinHash, needs dtflow[similarity]
```

## Filter and validate

```python
dt.filter(lambda x: x.score > 0.8)
dt.filter(lambda x: x.language == "zh")

errors = dt.validate(lambda x: len(x.messages) >= 2)      # failing records
for e in errors[:5]:
    print(f"row {e.index}: {e.error}")
```

### Schema validation

```python
from dtflow import Schema, Field, openai_chat_schema

result = dt.validate_schema(openai_chat_schema)
print(result)  # ValidationResult(valid=950, invalid=50, errors=[...])

schema = Schema({
    "messages": Field(type="list", required=True, min_length=1),
    "messages[*].role": Field(type="str", choices=["user", "assistant", "system"]),
    "messages[*].content": Field(type="str", min_length=1),
    "score": Field(type="float", min=0, max=1),
})
result = dt.validate_schema(schema)
valid_dt = dt.validate_schema(schema, filter_invalid=True)   # keep only valid rows
```

Preset schemas: `openai_chat_schema`, `alpaca_schema`, `sharegpt_schema`, `dpo_schema`.

| Field option | Meaning | Example |
|------|------|------|
| `type` | type check | `"str"`, `"int"`, `"float"`, `"bool"`, `"list"`, `"dict"` |
| `required` | must be present | `True` / `False` |
| `min` / `max` | numeric range | `min=0, max=1` |
| `min_length` / `max_length` | length range | `min_length=1` |
| `choices` | enum | `choices=["user", "assistant"]` |
| `pattern` | regex | `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `custom` | custom check | `custom=lambda x: x > 0` |

## Transform and presets

```python
dt.to(lambda x: {"question": x.q, "answer": x.a})           # custom, returns a new list
dt.to(preset="openai_chat", user_field="q", assistant_field="a")
dt.transform(func)                                          # same, returns a DataTransformer
```

| Preset | Output |
|---------|---------|
| `openai_chat` | `{"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}` |
| `alpaca` | `{"instruction": ..., "input": ..., "output": ...}` |
| `sharegpt` | `{"conversations": [{"from": "human", ...}, {"from": "gpt", ...}]}` |
| `dpo_pair` | `{"prompt": ..., "chosen": ..., "rejected": ...}` |
| `simple_qa` | `{"question": ..., "answer": ...}` |

Presets are a convenience layer. `transform(lambda x: ...)` covers everything else, and nested output such as `{"messages": x.messages}` is returned as plain lists and dicts.

### Error handling

```python
dt.to(func, on_error="skip")    # skip failing rows (default), summary on stderr
dt.to(func, on_error="raise")   # raise on the first failure
dt.to(func, on_error="keep")    # keep the original row
result, errors = dt.to(func, return_errors=True)
```

## Tokens

```python
from dtflow import count_tokens, token_counter, token_filter, token_stats

count = count_tokens("Hello world", model="gpt-4")
dt.transform(token_counter("text")).save("with_tokens.jsonl")          # adds token_count
dt.filter(token_filter("text", max_tokens=2048))
dt.filter(token_filter(["question", "answer"], min_tokens=10, max_tokens=4096))
stats = token_stats(dt.data, "text")
# {"total_tokens": 12345, "avg_tokens": 123, "min_tokens": 5, "max_tokens": 500, ...}
```

The backend is chosen from the model name: `gpt-4` → tiktoken; `Qwen/Qwen2-7B` or a local path → `transformers` tokenizers (`pip install "dtflow[tokenizers-hf]"`).

For conversations:

```python
from dtflow import messages_token_counter, messages_token_filter, messages_token_stats

dt.transform(messages_token_counter(model="gpt-4"))                 # total only
dt.transform(messages_token_counter(model="gpt-4", detailed=True))  # per role + turns
dt.filter(messages_token_filter(min_tokens=100, max_tokens=4096))
dt.filter(messages_token_filter(min_turns=2, max_turns=10))
stats = messages_token_stats(dt.data, model="gpt-4")
```

## Converters

```python
from dtflow import (
    to_hf_dataset, from_hf_dataset,     # HuggingFace Dataset (dtflow[converters])
    to_openai_batch, from_openai_batch, # OpenAI Batch API files
    to_llama_factory,                   # LLaMA-Factory alpaca format
    to_axolotl,                         # Axolotl
    messages_to_text,                   # messages -> plain text (chatml / llama2 / simple)
)

ds = to_hf_dataset(dt.data); ds.push_to_hub("my-dataset")
data = from_hf_dataset("tatsu-lab/alpaca", split="train")
batch_input = dt.to(to_openai_batch(model="gpt-4o")); results = from_openai_batch(batch_output)
dt.transform(messages_to_text(template="chatml"))
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
```

### ms-swift

```python
from dtflow import to_swift_messages, to_swift_query_response, to_swift_vlm

dt.transform(to_swift_messages()).save("swift_messages.jsonl")
# {"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
dt.transform(to_swift_query_response(query_field="messages")).save("swift_qr.jsonl")
# {"query": "...", "response": "...", "system": "...", "history": [["q1", "a1"], ...]}
dt.transform(to_swift_vlm(images_field="images")).save("swift_vlm.jsonl")
```

### One-shot export for a training framework

```python
result = dt.check_compatibility("llama-factory")   # ✅ compatible - LLaMA-Factory (openai_chat) / ❌ ...
files = dt.export_for("llama-factory", "./llama_ready/", dataset_name="my_sft_data")
files = dt.export_for("swift", "./swift_ready/")
files = dt.export_for("axolotl", "./axolotl_ready/")
```

| Framework | Output | Run with |
|------|---------|---------|
| `llama-factory` | data.json + dataset_info.json + train_args.yaml | `llamafactory-cli train train_args.yaml` |
| `swift` | data.jsonl + train_swift.sh | `bash train_swift.sh` |
| `axolotl` | data.jsonl + config.yaml | `accelerate launch -m axolotl.cli.train config.yaml` |

The input format (`openai_chat`, `alpaca`, `sharegpt`, `dpo`) is detected automatically.

## Streaming for huge files

Constant memory on the read side, for JSONL/NDJSON (also `.gz`), CSV/TSV, Parquet, Arrow and FlaxKV. Operations are lazy and run only on `save()` / `collect()` / iteration.

```python
from dtflow import load_stream, load_sharded

(load_stream("huge_100gb.jsonl")
    .filter(lambda x: x["score"] > 0.5)
    .transform(lambda x: {"text": x["content"]})
    .save("output.jsonl"))

(load_stream("data.csv").filter(lambda x: x["score"] > 0.5).save("output.parquet"))   # cross-format

(load_sharded("data/train_*.parquet").filter(lambda x: len(x["text"]) > 10).save("merged.jsonl"))

(load_stream("huge.jsonl")
    .transform(lambda x: {"q": x["question"], "a": x["answer"]})
    .save_sharded("output/", shard_size=100000))      # output/part-00000.jsonl, ...

for batch in load_stream("data.jsonl").batch(1000):
    results = call_api(batch)
```

`StreamingTransformer` also has `head`, `tail`, `skip`, `sample` (reservoir), `dedupe` (O(unique keys)), `flat_map`, `shuffle`, `split`, `peek`, `count`. `open_stream(path_or_dash)` is the entry point the CLI uses: it reads `-` from stdin and picks streaming or in-memory loading by format.

The CLI primitives are exposed as functions in `dtflow.ops` (`filter_rows`, `select_rows`, `map_rows`, `explode_rows`, `sort_rows`, `shuffle_rows`, `group_rows`, `join_rows`, `clean_rows`, `transform_rows`, `dedupe_rows`, `split_rows`, `infer_schema`) taking and returning a `StreamingTransformer`; `dtflow.expr` compiles the expression strings (`compile_where`, `compile_value`, `compile_map`).

## Data lineage

```python
dt = DataTransformer.load("raw.jsonl", track_lineage=True)
result = (dt
    .filter(lambda x: x.score > 0.5)
    .transform(lambda x: {"q": x.q, "a": x.a})
    .dedupe("q"))
result.save("processed.jsonl", lineage=True)    # writes processed.jsonl.lineage.json
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
```

`dt view`'s `w` export writes the same sidecar automatically, including every search / filter / sort condition that produced the subset.
