# Textual community update — 2026-10-10

Update for **dtflow 0.10.6**: the Textual browser is the interactive entry point to a training-data CLI workbench. The same file can continue through `stats → filter → dedupe → validate → transform → export`.

![Whole-file search in dt view](https://raw.githubusercontent.com/KenyonY/dtflow/v0.10.6/docs/images/growth/entry.png)

The synthetic demo has 308 records. The table starts with a 20-record window; searching `refund` finds 67 records across the whole file. `/` searches, `f` applies a Python filter, and `w` exports the subset. Each selected sample shows the conversation, tool calls and metadata together.

With [uv](https://docs.astral.sh/uv/) installed, try the browser on your own file:

```bash
uv tool run --isolated --from dtflow==0.10.6 dt view your.jsonl
```

For a reproducible dataset and the complete CLI workflow:

```bash
git clone --depth 1 --branch v0.10.6 https://github.com/KenyonY/dtflow.git
cd dtflow
python scripts/growth_demo.py --from dtflow==0.10.6 --output .growth/try
```

This text-SFT example removes tool trajectories and empty final replies, leaving 259 records, then deduplicates by id to get 252. OpenAI → ShareGPT → OpenAI conversion validates 252/252 both before and after, and all commands exit 0. The script keeps full stdout/stderr and exit codes in `evidence.json`.

The LLaMA-Factory export retains `messages/role/content` and generates matching column and role tags; redirected `dt export` stdout is one JSON summary. The generated training arguments are a starting template. This example covers ordinary text conversations, not GPU training or tool/multimodal training.

One Textual lesson from fixing my app: wait for **both text fields and thumbnail strips** to have nonzero layout sizes before calculating detail-navigation anchors. A text field can finish layout a frame before its thumbnail, otherwise the anchor misses ten image rows. [The fix and regression test](https://github.com/KenyonY/dtflow/commit/0999762) cover that partial-layout state.

[Entry demo (~39s)](https://github.com/KenyonY/dtflow/blob/v0.10.6/docs/images/growth/entry.mp4) · [Full workflow (~45s)](https://github.com/KenyonY/dtflow/blob/v0.10.6/docs/images/growth/workflow.mp4) · [Reproduction details](https://github.com/KenyonY/dtflow/tree/v0.10.6/docs/growth)

The videos use real TUI actions and real CLI output held as readable frames; their pauses are not execution-time measurements. All demo data is synthetic.

Feedback on the sample browser or a concrete format that fails conversion is welcome. This update was prepared with AI assistance; the commands and results were checked against the released package.
