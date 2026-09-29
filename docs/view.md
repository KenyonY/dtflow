# `dt view`: the interactive browser

`dt view <file>` opens a master-detail terminal browser built for training data.

**Table pane**: derived columns `turns/roles/first_user/chars/calls` plus metadata columns. **Detail pane**: the current row rendered by format. Chat turns are colored by role with code blocks highlighted; a tool call is drawn as `[assistant → fn]` followed by `⚙ fn call_id` and its formatted arguments, with a red mark when the arguments are not valid JSON; `reasoning_content` is shown dimmed; a tool result is labelled `[tool ← call_id]` with its JSON formatted; dpo rows show chosen and rejected side by side; alpaca rows are split into sections; generic rows are fully expanded. No drilling down. The layout is side by side by default; `z` switches to top/bottom.

Formats are auto-detected: `openai_chat` / `sharegpt` / `dpo` / `alpaca` / `generic` (tables such as CSV show every column). `--format` forces one.

```bash
dt view data.jsonl                                # open, ? for keys
dt view data.jsonl -100                           # start at the last 100 rows
dt view app.jsonl -100 -f                         # follow the last 100 rows and log rotation (-f = --follow)
dt view data.csv                                  # CSV / Parquet / any table
dt view data.jsonl --format=dpo                   # force the detail format
dt view big.jsonl --cap=50000                     # raise the window size (default 10k rows)
dt view data.jsonl -S -chars                      # start sorted (longest first)
dt view data.jsonl -w "turns>=6" -s error         # start filtered + searched (-w repeatable, -s = --search)
dt sample data.jsonl 500 | dt view -              # stdin (NDJSON, held in memory)
```

## Keys

| Key | Action |
|------|------|
| `↑/↓` `j/k` | Select row (detail follows) |
| `PgUp/PgDn` | Page · `d/u` (or `Ctrl+d/u`) half page |
| `g/G` | First / last row of the whole sequence; in follow mode `G` resumes following · `Tab` switches focus |
| `←/→` `h/l` | Scroll the table horizontally (`h/l` move 4 characters) |
| `s` | **Full-file sort** (type a column name, prefix `-` to reverse, e.g. `-chars`): scans the whole file, valid across windows |
| `/` `f` | **Full-file search / filter**: `/` searches every value of every record (assistant replies included; `re:` prefix for regex), `f` takes a Python expression. Both scan the whole file with progress, `Esc` cancels, hits become a pageable subset; `r` clears |
| `F` / click a header | **Column value picker** (Excel AutoFilter style): unique values with counts, a search box narrows the candidates, nothing ticked by default, tick what to keep → subset |
| `n/N` `*` | Move field by field in the detail pane (conversations go turn by turn as `msg0/msg1…`); `*` jumps only between fields **containing a search hit** |
| `w` | **Export** the current subset (or the `v` selection) to a file, format by extension; a lineage sidecar is written alongside |
| `C` | Copy a `dt view` command that reproduces the current view |
| `S` | Column snapshot: `n·min·max·mean·non-null rate` of one column over the current sequence (full distributions: `dt stats`) |
| `c` | Choose columns (a tick panel that applies to both table columns and detail fields) |
| Drag a header `│` | **Resize columns** (Excel style): the `│` to the right of every header (last column included) is a handle, it turns into `┃` under the mouse with a status-bar hint, drag to resize; double-click restores auto width. Widths are remembered per column name across windows, filters and column sets |
| `y` `v` | Copy the current sample as JSON · `v` multi-select then `y` copies several |
| Drag in detail + `Ctrl+c` | **Select any text with the mouse**: hold the left button and drag (what you see is what you select, wrapped lines stay aligned), `Ctrl+c` copies and clears. Multi-click widens the selection: double-click a word (hyphens and underscores count as word characters), triple-click a line, four clicks a field block, five clicks the whole detail pane; a single click or `Esc` clears. Copying uses OSC52 plus local `wl-copy`/`xclip`/`xsel`, so it reaches your local clipboard over SSH and inside tmux. Dragging in the table means something else (resize / select rows); use `y` for whole samples |
| Drag the split | **Resize the two panes with the mouse**: the border between table and detail is the handle, it brightens under the mouse with a status-bar hint, drag it anywhere (cell by cell); double-click restores the default 65:35. `+/-` still move it in 5 % steps |
| `Enter` | Zoom into the current sample (`Esc` returns) · `z` side-by-side / stacked layout · `+/-` resize panes |
| `?` | Help · `q` quit |

## Filter syntax

**The `f` filter (and `--where`) is plain Python**, with the current row named `x`. **Derived column names** from the header (`chars`/`turns`/`roles`/`first_user`/`calls`…) are variables with their raw types (`turns` is an int, `first_user` is the **full text**, not the 160-character table preview); everything else goes through `x.`:

```
turns>=6 and chars<2000
x.source=='alpaca'
len(x.messages)>=2 and x.messages[-1].role=='assistant'
'refund' in first_user                       # contains, on the full first user message
'get_weather' in calls                       # samples that called this function (non-empty calls = has tool calls)
'error' in x.messages[0].content
any('keyword' in m.content for m in x.messages)   # whole conversation
'word' in first_user.lower()                 # case-insensitive
```

`and`/`or`/`not` and parentheses work as usual. `in` is case-sensitive; `/` search and the value-picker search box are always case-insensitive. Rows whose expression fails (missing field) simply do not match. See [expressions.md](expressions.md) for the full language.

## Search, filter and sort stack, and they are full-file

`/`, `f`, `F` and `s` always scan the whole file rather than the current window; the resulting sequence of global row numbers becomes the new browsing sequence (paging does not invalidate it), and the status bar shows `hits M/N (ratio)`. The three kinds of constraints have separate slots: one `/` (a new search replaces the old one), `f` stacks (multiple filters are **and**-ed), and `F` keeps a per-column "kept values" set so it can be adjusted or widened again. **`r` clears everything and returns to the full file.**

`/` searches **every value of every record**, not just the table columns: the table is a derived summary, `first_user` is only the first user message, and searching by column would miss assistant replies entirely. Hits are painted yellow in both panes, and `*` walks through them.

**Scans run in parallel**: once the JSONL/NDJSON index is ready, the file is split into byte ranges and handed to a process pool (constraints are serialized to a spec and each worker rebuilds the same predicate). Measured on 300k rows / 440 MB, a `/` search drops from 1.9 s to 0.2 s. `DTFLOW_VIEW_WORKERS=1` forces serial; non-JSONL inputs (CSV / Parquet / stdin) are already in memory and scan serially. Two cases skip the scan entirely: when a new constraint only **tightens** the old one (another `f`, a narrower value set) only the current subset is re-read (when the subset is under 1/10 of the file); and confirming an `F` selection reuses the value → row-number map recorded while scanning the candidates.

## Closing the loop

Export the filtered subset with `w` (`.jsonl` streams, so hundreds of thousands of rows do not touch memory; other extensions go through the normal writers). A lineage sidecar is written automatically, so `dt history <out>` shows the source file and every condition in effect. `C` translates the current view back into a `dt view ... --where=... --search=... --sort=...` command that restores it when pasted (value-picker filters become expressions like `str(x.get('col')) in (...)`; when a truncated table value cannot be restored the command says so and the lineage file is authoritative).

Instant filtering while browsing belongs to view; full distributions (histograms, quantiles, value counts, tokens) belong to `dt stats` / `dt token-stats`.

## Large files

Files are loaded in windows (`--cap`, default 10k rows). Opening a JSONL/NDJSON file indexes and loads only the first window; `]` reads the next one incrementally. The total row count shows as pending until counting finishes or the end of the file is reached. Jumping to a positive row number scans only up to that window; `G` and negative row numbers count rows quickly with Polars and then read the tail window backwards, keeping absolute row numbers without indexing the whole file. Counts and both end indexes are reused, so paging backwards from the tail only fills adjacent windows; only full-file search / filter / sort / export fill the gaps in between. Background work is cancelled with `Esc`. `--offset` needs to scan everything before the target row. `dt view file -100` starts from the last 100 rows without scanning the file.

The JSONL column catalog scans every record in the current window and grows in first-seen order as you page or jump, without pre-parsing the file; top-level objects and arrays in generic data become columns too. Training formats show the first 8 metadata columns by default and keep the rest in the `c` column panel.

Peak RSS after opening a 155 MB / 910k-row JSONL is about 91 MB and does not grow with the file (VisiData 550 MB, tabiew 565 MB, jless 824 MB, fx 2.3 GB on the same machine).

## Live logs

`dt view app.jsonl --follow` starts at the latest tail window, receives new complete lines in 0.5 s batches, and follows rename rotation and visible truncation. A partial last line stays pending instead of being reported as bad JSON; complete lines that are invalid JSON still show as diagnostic placeholder rows. Moving the cursor up pauses auto-scroll and accumulates new rows; `G` returns to the end and resumes. `/`, `f` and `F` first scan a fixed high-water mark, then apply the same constraint incrementally to new rows; `s` sorts a fixed snapshot and pauses following, `r` resets to live order. `--follow` supports seekable JSONL/NDJSON only; for plain-text logs use `tl --tail FILE` (bundled [toolong](https://github.com/Textualize/toolong), `pip install dtflow[logs]`).

## Bad lines

Invalid JSON does not block browsing: `dt view` shows such lines as placeholder rows (`_parse_error` / `_raw_line` columns), row numbers stay aligned, and `/` finds them; a syntactically broken row is usually exactly what you opened the browser to find. Other commands are split by whether they write a new file: `head`/`tail`/`sample` skip the line and report its number on stderr, while `clean`/`transform` and friends raise with the row number and content instead of dropping data silently.

## Static previews

`dt head/sample/tail/slice --pretty` reuse the same rendering for a one-shot preview, and degrade to NDJSON when piped.
