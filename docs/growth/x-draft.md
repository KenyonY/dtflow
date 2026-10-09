# X 草稿（维护者审阅后发布）

以下是三条独立帖子组成的线程，各条都适配普通 280 字符限制。上传媒体后检查预览。

## 1 — 问题

LLM training data is a batch of conversations, not just JSON rows. jq is great for JSON plumbing; I wanted to inspect whole samples, search assistant replies, then clean and ship the dataset from the same CLI. That's why I built dtflow.

## 2 — 样本入口

dt view renders one complete training sample: roles, turns, tool calls and metadata. Search covers the whole file, then filter and export the subset. The demo uses 308 synthetic records; the visible window starts at 20. Attach: entry.mp4.

发布时删除最后的 `Attach: entry.mp4.`，上传 [入口视频](../images/growth/entry.mp4)。

## 3 — 完整工作台

The same file continues through stats → filter → dedupe → validate → transform → export. Our synthetic text-SFT demo goes from 308 to 252 valid samples, with LLaMA-Factory data + config. Try: pip install dtflow. https://github.com/KenyonY/dtflow

上传 [工作流视频](../images/growth/workflow.mp4)。仓库链接提供完整复现命令。

## 后续帖 — 完整流程

A viewer is one entry point. dtflow also cleans training files, converts OpenAI/ShareGPT/Alpaca/DPO layouts and exports framework configs. Here's a reproducible text-SFT workflow with commands and exit codes: https://github.com/KenyonY/dtflow/tree/main/docs/growth

附工作流视频。实际发布时可以用一次用户反馈替换泛泛描述；尚无反馈时不要编造案例。
