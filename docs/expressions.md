# Expressions and field paths

Two small languages, used in different places:

- **Expressions** are Python. They are the conditions and keys of `filter`, `select`, `map`, `sort --by`, `group --by`, `join --on`, `sample --where`, `view --where` / the `f` prompt, and pipeline steps.
- **Field paths** name one field with a compact `a.b[0].c` syntax. They are the arguments of `--key`, `--by` (stratified sampling), `--field`, `--drop-empty`, `--min-len`, `--max-len`, `--min-tokens`, `--max-tokens`, `--promote`.

Writing a field path where an expression is expected (or the reverse) is rejected with a hint, never silently misinterpreted.

## Expressions

The current row is **`x`**. Attribute access works through nested dicts and lists (`x.messages[-1].role`, `x.meta.source`); dict-style access returns raw values (`x["meta"]["source"]`, `x.get("score")`). The namespace also has `re`, `json`, `math`, `get(x, "<field path>")` for the path DSL, and the [row helpers](#row-helpers) below. Python builtins are available.

```bash
dt filter d.jsonl "x.score > 0.8 and 'wiki' in x.meta.source"
dt filter d.jsonl "len(x.messages) >= 2 and x.messages[-1].role == 'assistant'"
dt filter d.jsonl "any('refund' in m.content for m in x.messages)"
dt filter d.jsonl "re.search(r'\d{4}', x.text) and x.lang in ('zh', 'en')"
dt select d.jsonl "id,n=len(x.messages),roles=[m.role for m in x.messages]"
dt map    d.jsonl "x.text = x.text.strip(); x.messages.append({'role': 'assistant', 'content': x.a})"
dt sort   d.jsonl --by "(x.source, -x.score)"
dt group  d.jsonl --by "len(x.messages)"
dt group  d.jsonl --by x.label --agg "avg=mean(len(r.text) for r in g),ids=[r.id for r in g][:3]"
```

- `filter EXPR`: keep rows where the expression is truthy.
- `select FIELDS`: comma-separated at depth 0 (commas inside brackets and quotes are fine). A bare name is a literal top-level field, copied if present. `name=expr` is a derived field. Output keys follow the spec order; renaming is `new=x.old`.
- `map CODE`: statements, executed with `x` bound to the row; `x.f = ...`, `del x.f`, `x.list.append(...)` all write through. Separate statements with `;` or newlines.
- `group --agg SPEC`: each `name=expr` is evaluated once per group with `g` (the rows of the group, attribute access works on each), `key`, `n`, and `mean` / `median` in scope.
- `dt view`'s `f` prompt and `--where` take exactly this language; the header's derived columns are the row helpers below (`turns(x)`, not `turns`).

### Row helpers

Functions of the current row that summarize a training sample. They are the same code that computes `dt view`'s derived columns, so a condition written in the browser can be pasted into `dt filter` (and `P` in the browser does that for you).

| Helper | Returns | Notes |
|------|------|------|
| `turns(x)` | `int` | number of messages (`messages` or sharegpt `conversations`); 0 for non-chat rows |
| `roles(x)` | `str` | role signature such as `u→a→t→a` (tool results are `t`), truncated after 5 |
| `first_user(x)` | `str` | full text of the first user message |
| `chars(x)` | `int` | characters of all messages, including reasoning and tool-call arguments |
| `calls(x)` | `str` | called function names, comma-joined, in first-seen order; empty when there are none |
| `imgs(x)` | `int` | images the conversation references: inline image parts, or sample-level `images`/`image` matched to `<image>` placeholders |
| `fulltext(x)` | `str` | every scalar value of the record joined as text (no keys); works on a sub-structure too: `fulltext(x.messages)` |
| `search(x, pattern)` | `bool` | case-insensitive substring over the whole record, `re:` prefix for a regex; identical to `/` in `dt view` |

```bash
dt filter d.jsonl "turns(x) >= 6 and chars(x) < 4000"
dt filter d.jsonl "'get_weather' in calls(x)"                 # rows that called this tool
dt filter d.jsonl "search(x, 'refund') and not search(x, 're:^system')"
dt group  d.jsonl --by "roles(x)"
dt sort   d.jsonl --by "chars(x)" --desc
```

A helper used without a call (`turns >= 6`, the pre-0.10 `dt view` form) is a syntax error with the hint `write turns(x)`; passing one as a function (`sorted(g, key=turns)`) is fine.

### What happens when an expression fails on a row

Training data is heterogeneous; `x.score > 0.5` on a row without `score` is normal. By default no command aborts, and stderr prints one summary at the end ("12/1000 rows failed: AttributeError: score").

| Command | Failing row |
|---------|-------------|
| `filter` | treated as not matching |
| `select` | the failing item becomes `null`, the row is kept |
| `map` | the row is kept unchanged |
| `sort` | the row goes last |
| `group --agg` | the failing aggregate becomes `null` |
| `join` | a failing left key counts as unmatched (right keys must evaluate) |
| `describe` | counted as `null` |
| `view` | the row does not match |

`--strict` makes the first failure exit with code 1. Nothing silently changes the row count of `select`, `map` or `group`.

### What is rejected before reading any data

- **Syntax errors**: exit code 2, with the position marked.
- **Bare names**: `dt filter d.jsonl "score > 0.5"` is a usage error ("did you mean `x.score`"). Otherwise every row would raise NameError and the result would be an empty file with exit code 0. Comprehension variables, lambda parameters and builtins are fine; an expression that is *only* a builtin name (`--by id`) is rejected too.
- **Field paths written as expressions**: `--key x.meta.s` is rejected with the corrected `--key=meta.s`.

There is no sandbox. This is a local tool evaluating your expressions on your files, the same trust level as `python -c`; `dt transform` already runs `.dt/*.py` files you write yourself.

## Field paths

| Syntax | Meaning | Example |
|------|------|------|
| `a.b.c` | nested field | `meta.source` |
| `a[0].b` | list index | `messages[0].role` |
| `a[-1].b` | negative index | `messages[-1].content` |
| `a.#` | list length | `messages.#` |
| `a[*].b` | expand every element (first by default) | `messages[*].role` |
| `a[*].b:join` | expand and join with `\|` | `messages[*].role:join` |
| `a[*].b:unique` | expand, dedupe, join | `messages[*].role:unique` |

| Command | Argument | Example |
|------|------|------|
| `sample` | `--by=` | `--by=meta.source`, `--by=messages.#` |
| `dedupe` | `--key=` | `--key=meta.id`, `--key=messages[0].content` |
| `clean` | `--drop-empty=`, `--min-len=`, `--max-len=`, `--min-tokens=`, `--max-tokens=`, `--promote=` | `--min-len=messages.#:2`, `--max-len=messages[-1].content:500` |
| `token-stats` | `--field=` | `--field=messages[-1].content` |
| `stats` | `--field=`, `--expand=` | `--expand='messages[*].role'` |
| `diff` | `--key=` | `--key=meta.uuid` |

Example row:

```json
{"meta": {"source": "wiki"}, "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]}
```

`meta.source` → `"wiki"` · `messages[0].role` → `"user"` · `messages[-1].content` → `"hello"` · `messages.#` → `2` · `messages[*].role` → `"user"` · `messages[*].role:join` → `"user|assistant"`

Inside an expression the same DSL is `get(x, "messages[*].role:join")`.

## Migrating from the pre-0.9 syntax

The `field op value` filter form (`category=tech`, `content~=word`, `messages.#>=2`) was removed in 0.9.

| Old | New |
|----|----|
| `category=tech` | `x.category=='tech'` |
| `content~=machine learning` (contains, case-insensitive) | `'machine learning' in x.content.lower()` |
| `score>0.8` / `messages.#>=2` | `x.score>0.8` / `len(x.messages)>=2` |
| `messages[0].role=user` | `x.messages[0].role=='user'` |
| `messages[*].content:join~=word` | `any('word' in m.content for m in x.messages)` |
| in view: `turns>=6 and chars<2000` | `turns(x)>=6 and chars(x)<2000` (since 0.10 derived columns are row helpers); `source==alpaca` → `x.source=='alpaca'`; `first_user~=refund` → `'refund' in first_user(x)` |
| pipeline `condition: "len(text) > 10"` / `field: text` | `expr: "len(x.text) > 10"` / `expr: "x.text"` |
| `dt clean f.jsonl --strip` (used to overwrite the file) | `dt clean f.jsonl --strip -i`; without `-i`/`-o` output goes to stdout |
