# `dt view`: the interactive browser

`dt view <file>` opens a master-detail terminal browser built for training data.

**Table pane**: derived columns `turns/roles/first_user/chars/calls` (plus `imgs` when the window has images) and metadata columns. **Detail pane**: the current row rendered by format. Each chat turn opens with a role-colored badge and its length (`roles` in the table uses the same colors); code blocks and JSON are syntax-highlighted on a shaded background; a tool call is titled `assistant → fn` followed by `⚙ fn call_id` and its formatted arguments, with a red mark when the arguments are not valid JSON; `reasoning_content` is shown dimmed; a tool result is titled `tool ← call_id` with its JSON formatted; dpo rows show chosen and rejected side by side; alpaca rows are split into sections; generic rows are fully expanded. No drilling down. Long samples (hundreds of turns) render the first screens at once and the rest in the background, so holding `j` never stalls. The layout is side by side by default; `z` switches to top/bottom.

**Pane borders** carry the identity info: table top-left `file · format`, bottom-right the cursor position `N / total`; detail top-left `#row · turns · chars`, bottom-right the current field. The status bar keeps only changing state (hits, sort, window, multi-select) on the left and the `z` / `?` hints on the right.

Formats are auto-detected: `openai_chat` / `sharegpt` / `dpo` / `alpaca` / `generic` (tables such as CSV show every column). `--format` forces one.

```bash
dt view data.jsonl                                # open, ? for keys
dt view data.jsonl -100                           # start at the last 100 rows
dt view app.jsonl -100 -f                         # follow the last 100 rows and log rotation (-f = --follow)
dt view data.csv                                  # CSV / Parquet / any table
dt view data.jsonl --format=dpo                   # force the detail format
dt view big.jsonl --cap=50000                     # raise the window size (default 10k rows)
dt view data.jsonl -S -chars                      # start sorted (longest first)
dt view data.jsonl -w "turns(x)>=6" -s error      # start filtered + searched (-w repeatable, -s = --search)
dt view data.jsonl --pipe 'dt filter - "turns(x)>=6" | dt head - 200'   # run a pipe over the file first, browse its output
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
| `P` | Copy the same conditions as a **processing chain**: `dt filter FILE '…' \| dt sort - --by '…'`; append `-o out.jsonl` or more pipes to process what you are looking at |
| `\|` | **Run a shell pipe** over the whole file and browse its output (see below); `r` returns to the file |
| `S` | Column snapshot: `n·min·max·mean·non-null rate` of one column over the current sequence (full distributions: `dt stats`) |
| `c` | Choose columns (a tick panel that applies to both table columns and detail fields) |
| Drag a header `│` | **Resize columns** (Excel style): the `│` to the right of every header (last column included) is a handle, it turns into `┃` under the mouse with a status-bar hint, drag to resize; double-click restores auto width. Widths are remembered per column name across windows, filters and column sets |
| Double-click a header | **Rename the column**: an input box appears over the header cell, pre-filled with the current name (Enter confirms, Esc cancels); the header, the detail pane and the column picker update at once, the file is untouched until you quit (see below). Derived columns and `#` can't be renamed |
| `y` `v` | Copy the current sample as JSON · `v` multi-select then `y` copies several |
| `i` | **View the sample's images** full-size in a popup (`←/→` switch, `Esc` closes); clicking the `imgs` cell or a `🖼` line in detail opens it too (see [Images](#images-vlm-data)) |
| Drag in detail + `Ctrl+c` | **Select any text with the mouse**: hold the left button and drag (what you see is what you select, wrapped lines stay aligned), `Ctrl+c` copies and clears. Multi-click widens the selection: double-click a word (hyphens and underscores count as word characters), triple-click a line, four clicks a field block, five clicks the whole detail pane; a single click or `Esc` clears. Copying uses OSC52 plus local `wl-copy`/`xclip`/`xsel`, so it reaches your local clipboard over SSH and inside tmux. Dragging in the table means something else (resize / select rows); use `y` for whole samples |
| Drag the split | **Resize the two panes with the mouse**: the border between table and detail is the handle, it brightens under the mouse with a status-bar hint, drag it anywhere (cell by cell); double-click restores the default 65:35. `+/-` still move it in 5 % steps |
| `Enter` | Zoom into the current sample (`Esc` returns) · `z` side-by-side / stacked layout · `+/-` resize panes |
| `?` | Help · `q` quit |

## Filter syntax

**The `f` filter (and `--where`) is plain Python**, with the current row named `x`, and it is **exactly the language of `dt filter`**. The header's derived columns (`chars`/`turns`/`roles`/`first_user`/`calls`) are **row helpers**, called on `x`: `turns(x)` is an int, `first_user(x)` is the **full text** (not the 160-character table preview). Everything else goes through `x.`:

```
turns(x)>=6 and chars(x)<2000
x.source=='alpaca'
len(x.messages)>=2 and x.messages[-1].role=='assistant'
'refund' in first_user(x)                    # contains, on the full first user message
'get_weather' in calls(x)                    # samples that called this function (non-empty calls = has tool calls)
search(x, 'refund')                          # the whole record, case-insensitive, same as /
'error' in x.messages[0].content
any('keyword' in m.content for m in x.messages)   # whole conversation
'word' in first_user(x).lower()              # case-insensitive
```

`and`/`or`/`not` and parentheses work as usual. `in` is case-sensitive; `search()`, `/` and the value-picker search box are case-insensitive. Rows whose expression fails (missing field) simply do not match. A bare `turns>=6` (the old form) is rejected with the hint `write turns(x)`. See [expressions.md](expressions.md) for the full language and the helper table.

## Search, filter and sort stack, and they are full-file

`/`, `f`, `F` and `s` always scan the whole file rather than the current window; the resulting sequence of global row numbers becomes the new browsing sequence (paging does not invalidate it), and the status bar shows `hits M/N (ratio)`. The three kinds of constraints have separate slots: one `/` (a new search replaces the old one), `f` stacks (multiple filters are **and**-ed), and `F` keeps a per-column "kept values" set so it can be adjusted or widened again. **`r` clears everything and returns to the full file.**

`/` searches **every value of every record**, not just the table columns: the table is a derived summary, `first_user` is only the first user message, and searching by column would miss assistant replies entirely. Hits are painted yellow in both panes, and `*` walks through them.

**Scans run in parallel**: once the JSONL/NDJSON index is ready, the file is split into byte ranges and handed to a process pool (constraints are serialized to a spec and each worker rebuilds the same predicate). Measured on 300k rows / 440 MB, a `/` search drops from 1.9 s to 0.2 s. `DTFLOW_VIEW_WORKERS=1` forces serial; non-JSONL inputs (CSV / Parquet / stdin) are already in memory and scan serially. Two cases skip the scan entirely: when a new constraint only **tightens** the old one (another `f`, a narrower value set) only the current subset is re-read (when the subset is under 1/10 of the file); and confirming an `F` selection reuses the value → row-number map recorded while scanning the candidates.

## Renaming columns

Double-click a column header: an input box opens over the header cell; type the new name, Enter. The rename is applied to what you see (header, detail pane, `c` column picker) and to what `w` exports. **Type the names you see** everywhere: `f` (`x.quality > 0.5`), `s`, `S`, `F`, and the `|` pipe (it is fed the renamed rows). Conditions are stored against the on-disk names, so a filter written before a rename keeps working after it, and what `C`/`P`/lineage record stays valid for the file as it is on disk: `P` ends with `| dt clean - --rename old:new` so its output looks like the browser; `C` notes that renames are not part of `dt view` options. Renaming is a layer over the file, so it is disabled while a pipe result is shown (`r` returns to the file). The status bar shows `renamed ×N · q to save`.

Pressing `q` with pending renames asks:

- **Save** rewrites the file with the new field names (streamed through a temp file in the same directory and swapped in atomically, `.gz` included) and records a `view_rename` operation with the equivalent `dt clean FILE --rename old:new -i` command in `FILE.lineage.json`, then exits.
- **Discard** exits without touching the file.
- **Cancel** (Esc) returns to the browser.

Saving is not offered for stdin input or in follow mode (the file is still being written); use `w` to export with the new names instead. A single click on a header still opens the value picker, delayed by 0.2 s; a slower second click on the same header while the picker is up also counts as a double-click.

## Closing the loop

Export the filtered subset with `w` (`.jsonl` streams, so hundreds of thousands of rows do not touch memory; other extensions go through the normal writers). A lineage sidecar is written automatically, so `dt history <out>` shows the source file and every condition in effect. `C` translates the current view back into a `dt view ... --where=... --search=... --sort=...` command that restores it when pasted (value-picker filters become expressions like `str(x.get('col')) in (...)`; when a truncated table value cannot be restored the command says so and the lineage file is authoritative). `P` translates the same conditions into the processing form, `dt filter FILE '…' | dt sort - --by '…'`: paste it, append `-o out.jsonl` or another pipe, and the subset you were looking at goes through the rest of the toolkit. That works because the browser and the CLI share one expression language (see [expressions.md](expressions.md#row-helpers)). The other direction is `|`: run a pipeline over the file and browse its output without leaving view (see [Run a pipeline inside view](#run-a-pipeline-inside-view)).

Instant filtering while browsing belongs to view; full distributions (histograms, quantiles, value counts, tokens) belong to `dt stats` / `dt token-stats`.

## Run a pipeline inside view

`|` opens a prompt for a shell pipeline. Every row of the **whole file** (never the current subset) is written to its stdin as NDJSON, its stdout is read back as NDJSON, and the result replaces what you are browsing: format re-detected, columns rebuilt, filters cleared.

```
dt filter - "turns(x)>=6" | dt sort - --by "chars(x)" --desc | dt head - 200
dt select - "id,n=chars(x),last=x.messages[-1].content" | dt sort - --by x.n --desc
dt join - labels.jsonl --on x.id --anti
dt filter - "search(x, 'refund')" | jq -c '{id, n: (.messages | length)}'
```

It is the exact line you would type after `dt concat FILE |` in a shell: `dt`, `jq`, `grep`, `python` all work, and new `dt` options are available without any view change. Each run starts from the original file and replaces the previous result (there is no stack); `r` leaves the pipe and returns to the file. Pressing `|` again pre-fills the last command so it can be edited. `Esc` cancels a running pipe (the process is killed). A non-zero exit shows the command's error (dt's structured message) and keeps the current data; an empty result shows an empty table.

The pipe travels with everything else: `C` produces `dt view FILE --pipe '…' --where …`, `P` produces the pipe rerun against the file (`dt filter FILE … | …`) followed by the current filter/sort, and `w` records `pipe`, `pipe_command` and `pipe_rows` in the lineage sidecar. `--pipe CMD` on the command line runs the pipe before applying `--where/--search/--sort`. Column renames cannot be written back while a pipe result is shown (`r` first, or `w`).

The result lives in memory (like `dt view -`), so later `/` `f` `s` scans run serially rather than in parallel; for very large outputs put a `dt filter` or `dt head` before `dt sort`. `--follow` and `|` are mutually exclusive.

## Images (VLM data)

Image references are read from inline content parts (OpenAI `image_url`, Responses `input_image`, qwen/swift `{"type":"image","image":…}`, Anthropic `source`) and from sample-level `images` (LLaMA-Factory / swift) or `image` (LLaVA), which are matched in order to the `<image>` placeholders in the text. Each message in detail lists its images as `🖼 path` lines (searchable; data URIs are shortened to header + size), and a sample whose `<image>` count differs from its image count gets a warning at the top, the most common broken VLM sample: red when placeholders outnumber images, yellow when images outnumber placeholders (ms-swift then prepends the missing tags to the first non-system message, and the extra images are shown there; LLaMA-Factory rejects it). `imgs(x)` counts them in filters: `dt filter d.jsonl "imgs(x)==0"`.

When the terminal draws real images (kitty graphics or sixel, detected at startup), each message's images also appear as a 10-row **thumbnail strip right below the message** in detail; a click opens that image full size. While the detail pane scrolls the thumbnails are left blank and drawn once it stops (≈0.2 s), so a page-down costs one image per visible thumbnail instead of one per animation frame; with half-block rendering only the `🖼` lines are shown.

`i` (or a click on the `imgs` cell / a `🖼` line / a thumbnail) opens the images one by one at full size, titled `2/3 · msg0 user · path · 1024×768 PNG 120.5 KB`; unreadable ones show the reason (missing file, HTTP 404, decode error). Sources: local paths (`file://` too), `http(s)://` URLs (downloaded in the background, cached in `~/.cache/dtflow/images`) and `data:` URIs; relative paths resolve against the data file's directory, or `--image-root DIR`. The picture is drawn with the best protocol the terminal reports (kitty graphics, sixel, else half-block characters); the terminal is asked once at startup, and only when the first window has images. Inside tmux: kitty graphics needs `set -g allow-passthrough on`; sixel (e.g. Windows Terminal 1.22+) needs a tmux built with sixel, `set -as terminal-features '*:sixel'` (re-attach afterwards), and, when the connection reports no pixel size (Windows Terminal → WSL → ssh reports 0×0), tmux ≥ 3.6, which asks the terminal instead; older tmux shows a `SIXEL IMAGE (WxH)+++` placeholder. dt view keeps the image traffic down to one send per visible image per action (opening, scrolling, switching samples); under tmux with sixel it turns off synchronized output, because tmux redraws the whole pane, images included, at the end of every synchronized frame.

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
