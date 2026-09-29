# Example data

Small, fully synthetic datasets in the formats `dt` understands, so every command in the README can be tried without your own data. Regenerate with `python examples/make_examples.py` (deterministic).

| File | Format | Rows | What's inside |
|------|--------|-----:|---------------|
| `chat.jsonl` | OpenAI `messages` | 308 | bilingual support chats, coding Q&A, general Q&A, and ~14% agent traces with `tool_calls` / `tool` messages and `reasoning_content`. Metadata: `id`, `source`, `lang`, `score`, `tags`, `created_at`, `meta.{annotator,reviewed}` |
| `sharegpt.jsonl` | ShareGPT `conversations` | 100 | same pool in `from`/`value` form, a few with `function_call` / `observation` turns |
| `alpaca.jsonl` | Alpaca | 120 | `instruction` / `input` / `output` |
| `dpo.jsonl` | DPO | 120 | `prompt` / `chosen` / `rejected` with `source` and `margin` |
| `labels.jsonl` | key → label | 216 | human labels for ~70% of `chat.jsonl` ids, for `dt join` |

`chat.jsonl` deliberately contains a little dirt, so the cleaning commands have something to find:

- 8 exact duplicates (same `id`) → `dt dedupe chat.jsonl --key=id`
- 6 rows without a `score` field → `dt filter chat.jsonl "x.score > 0.9"` reports them on stderr, `--strict` fails on them
- 5 rows whose last assistant turn is empty → `dt clean chat.jsonl --drop-empty='messages[-1].content'` or `dt validate chat.jsonl --preset=openai_chat`
- 1 tool call whose `arguments` is not valid JSON (`chat-0024`) → shown in red by `dt view`
- 4 agent traces with **parallel** tool calls (two `tool_calls` in one assistant message) → survive `dt transform --preset=sharegpt | dt transform - --preset=openai_chat` unchanged

## Try

```bash
cd examples

dt view chat.jsonl                                        # ? for keys; try  f  turns>=4   /  退款   F on source
dt view dpo.jsonl                                         # chosen / rejected side by side
dt stats chat.jsonl --schema

dt group chat.jsonl --by x.source
dt group chat.jsonl --by x.lang --agg "avg_score=mean(r.get('score') or 0 for r in g),n_tool=sum(1 for r in g if r.source=='agent_traces')"
dt filter chat.jsonl "any(m.get('tool_calls') for m in x.messages)" | dt select - "id,tool=x.messages[2].tool_calls[0].function.name"
dt filter chat.jsonl "'退款' in x.messages[0].content or 'refund' in x.messages[0].content.lower()" | dt head - 3
dt join chat.jsonl labels.jsonl --on x.id --inner | dt group - --by x.label
dt dedupe chat.jsonl --key=id | dt clean - --drop-empty='messages[-1].content' | dt split - -o out/ --name clean --ratio=0.9

dt transform sharegpt.jsonl --preset=openai_chat | dt validate - --preset=openai_chat
dt transform alpaca.jsonl --preset=openai_chat -o alpaca_as_chat.jsonl
dt export chat.jsonl -f llama-factory --check
```

All text was written for this repository; no real user data or third-party datasets are included.
