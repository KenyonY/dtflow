# V2EX 待发布文案

标题：做了个训练数据 CLI：先看完整样本，再清洗、转换、导出给 LLaMA-Factory

我做了 dtflow，用一个 CLI 检查、清洗、转换并交付 LLM 训练数据，`dt view` 是交互式入口。
处理聊天数据时，我经常想找某条 assistant 回复、看多轮上下文，然后把筛出的样本变成训练文件。
这篇用仓库里生成的合成数据演示，完全不含真实用户数据。

## 先看样本

`dt view chat.jsonl` 左侧概览样本，右侧显示完整对话、工具调用和元数据。
`/` 搜整条记录的每个值，`f` 写 Python 筛选表达式，`w` 导出子集。
条件对整个文件生效，当前显示的 20 条只是窗口。

插入入口截图或视频：https://github.com/KenyonY/dtflow/tree/main/docs/images/growth

## 一个清洗问题，完整跑到底

生成器产出 308 条数据，其中有重复 id、末轮空回复和工具轨迹。本例只做普通文本 SFT，
所以排除工具轨迹与空回复，再按 id 去重。过滤后剩 259 条，去重后 252 条。

```bash
pip install dtflow==0.10.6 uv
git clone --depth 1 https://github.com/KenyonY/dtflow.git
cd dtflow
python scripts/growth_demo.py --from dtflow==0.10.6 --output .growth/try
```

脚本在独立安装环境跑真实 CLI，并保存每条命令的 stdout、stderr 和退出码。
下面是它实际执行的核心命令（工作目录为生成数据的目录）：

```bash
dt stats chat.jsonl --schema
dt filter chat.jsonl "not calls(x) and bool(x.messages[-1].content)" -o filtered.jsonl
dt dedupe filtered.jsonl --key=id -o clean.jsonl
dt validate clean.jsonl --preset=openai_chat
dt transform clean.jsonl --preset=sharegpt -o sharegpt.jsonl
dt transform sharegpt.jsonl --preset=openai_chat -o sft.jsonl
dt validate sft.jsonl --preset=openai_chat
dt export sft.jsonl -f llama-factory -o llama
```

结果：转换前后都 252/252 条有效，所有步骤退出码 0。
导出生成 `custom_dataset.json`、`dataset_info.json` 和 `train_args.yaml`。
标准 OpenAI 对话保留 `messages/role/content`，配置使用对应的字段和角色映射。
训练参数是起点模板，需要按自己的模型、数据和硬件修改。

导出命令被脚本捕获时，stdout 是单个 JSON 摘要，进度和文件路径写 stderr。
例如摘要里的 `stats.input_rows` 是 252，`detected_format` 是 `openai_chat`。
这也方便 agent 或脚本继续处理。

插入完整工作流视频：https://github.com/KenyonY/dtflow/tree/main/docs/images/growth

## 适用边界

- 做表格 join/pivot/列图时，我会选 VisiData；要在表格上跑 SQL 可看 tabiew；
  看一个 JSON 文档的结构可用 jless。dtflow 面向一批训练样本的浏览和加工。
- `run --dry-run` 只检查 YAML、表达式和步骤链，不跑输入数据；
  `export --dry-run` 检查格式和框架兼容性，退出码 10。不是所有写文件命令都有 dry-run。
- 本例验证普通文本对话的导出，并用 LLaMA-Factory 0.9.5 的真实解析器验证映射；
  没跑 GPU 训练，也不拿这个结果证明工具训练或多模态训练已通过。
- filter/clean/dedupe/transform 等可流式处理；sort/shuffle、全量统计、框架导出等步骤会用更多内存，
  大文件先筛小，再做需要全量的操作。

项目：https://github.com/KenyonY/dtflow

如果你试了，欢迎带一份脱敏的格式示例或具体失败命令反馈；最想知道的是哪一步卡住了，
以及你现在用什么办法处理这一步。
