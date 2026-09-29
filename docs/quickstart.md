# dtflow 快速入门

## 安装

```bash
pip install dtflow
```

## Python API（30秒上手）

```python
from dtflow import DataTransformer

# 加载 -> 过滤 -> 转换 -> 保存
(DataTransformer.load("data.jsonl")
    .filter(lambda x: x.score > 0.8)
    .to(lambda x: {"q": x.question, "a": x.answer})
    .save("output.jsonl"))
```

## 常用操作

```python
dt = DataTransformer.load("data.jsonl")

# 过滤
dt.filter(lambda x: x.score > 0.5)
dt.filter(lambda x: len(x.text) > 10)

# 转换
dt.to(lambda x: {"q": x.q, "a": x.a})
dt.to(preset="openai_chat", user_field="q", assistant_field="a")

# 采样
dt.sample(100)      # 随机 100 条
dt.head(10)         # 前 10 条

# 去重
dt.dedupe("text")   # 按字段去重

# 分割
train, test = dt.split(ratio=0.8)

# 保存
dt.save("output.jsonl")
```

## 预设模板

| 预设 | 输出格式 |
|-----|---------|
| `openai_chat` | `{"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}` |
| `alpaca` | `{"instruction": ..., "input": ..., "output": ...}` |
| `sharegpt` | `{"conversations": [{"from": "human", ...}, {"from": "gpt", ...}]}` |

## CLI 命令

```bash
# 采样
dt sample data.jsonl --num=100
dt head data.jsonl --num=10

# 转换
dt transform data.jsonl --preset=openai_chat

# 筛选 / 投影 / 排序 / 分组 (表达式即 Python, 当前行 x; 可管道拼接)
dt filter data.jsonl "x.score > 0.5 and len(x.messages) >= 2"
dt select data.jsonl "id,text,n=len(x.messages)"
dt filter data.jsonl "x.ok" | dt sort - --by x.score --desc | dt head - 5
dt group data.jsonl --by x.meta.source
dt stats data.jsonl --schema

# 去重 (无 -o 写 stdout; -i 原地写回)
dt dedupe data.jsonl --key=text -o deduped.jsonl

# 清洗
dt clean data.jsonl --drop-empty=text --min-len=text:10 -i

# 统计
dt stats data.jsonl
dt token-stats data.jsonl --field=text

# 合并
dt concat a.jsonl b.jsonl -o merged.jsonl
```

## 大文件流式处理

```python
from dtflow import load_stream

# 100GB 文件也只用常量内存
(load_stream("huge.jsonl")
    .filter(lambda x: x["score"] > 0.5)
    .save("output.jsonl"))
```

## 字段路径语法

```bash
# CLI 中支持嵌套路径
dt sample data.jsonl --by=meta.source       # 嵌套字段
dt sample data.jsonl --by=messages.#        # 数组长度
dt dedupe data.jsonl --key=messages[0].content  # 数组索引
```

---

完整文档见 [README.md](../README.md)
