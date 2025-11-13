# MllmClient 和 OpenAIClient 快速开始

简洁的使用指南，包含最常用的调用方式。

---

## OpenAIClient

### 同步调用
```python
from sparrow import OpenAIClient

client = OpenAIClient(
    base_url="http://localhost:9999/v1",
    api_key="EMPTY",
)

result = client.chat_completions_sync(
    messages=[{"role": "user", "content": "你好"}],
    model="Qwen/Qwen2.5-7B-Instruct",
    temperature=0.5,
)
print(result)
```

### 异步调用
```python
import asyncio
from sparrow import OpenAIClient

async def main():
    client = OpenAIClient(base_url="http://localhost:9999/v1")
    result = await client.chat_completions(
        messages=[{"role": "user", "content": "你好"}],
        model="Qwen/Qwen2.5-7B-Instruct",
    )
    print(result)

asyncio.run(main())
```

### 批量处理
```python
client.chat_completions_batch_sync(
    messages_list=[
        [{"role": "user", "content": "问题1"}],
        [{"role": "user", "content": "问题2"}],
    ],
    model="Qwen/Qwen2.5-7B-Instruct",
    show_progress=True,
)
```

### 关键参数
| 参数 | 说明 |
|------|------|
| `base_url` | API 基础 URL |
| `api_key` | API 密钥 |
| `concurrency_limit` | 并发限制（默认10） |
| `timeout` | 超时时间秒数（默认100） |
| `retry_times` | 重试次数（默认3） |

---

## MllmClient

### 纯文本
```python
import asyncio
from sparrow import MllmClient

client = MllmClient(
    model="gemma3:12b",
    base_url="http://localhost:11434/v1/",
)

result = asyncio.run(client.call_llm(
    messages_list=[[{"role": "user", "content": "Hello"}]]
))
print(result)
```

### 单张图像
```python
from sparrow import relp

messages = [[{
    "role": "user",
    "content": [
        {"type": "text", "text": "描述这张图"},
        {"type": "image_url", "image_url": {"url": relp("./images/cat.jpeg")}}
    ]
}]]

result = asyncio.run(client.call_llm(messages_list=messages))
print(result)
```

### 多张图像
```python
messages = [[{
    "role": "user",
    "content": [
        {"type": "text", "text": "这两张图有什么区别？"},
        {"type": "image_url", "image_url": {"url": relp("./images/cat.jpeg")}},
        {"type": "image_url", "image_url": {"url": relp("./images/dog.png")}},
    ]
}]]

result = asyncio.run(client.call_llm(messages_list=messages))
```

### 批量处理
```python
messages_list = [
    [{"role": "user", "content": [
        {"type": "text", "text": f"图片 {i}"},
        {"type": "image_url", "image_url": {"url": relp("./images/cat.jpeg")}}
    ]}]
    for i in range(10)
]

results = asyncio.run(client.call_llm(
    messages_list=messages_list,
    show_progress=True,
))
```

### 关键参数
| 参数 | 说明 |
|------|------|
| `model` | 模型名称 |
| `base_url` | API 基础 URL |
| `concurrency_limit` | 并发限制（默认10） |
| `max_qps` | 最大每秒请求数（默认50） |
| `cache_image` | 是否启用图像缓存（默认False） |

### 常用 call_llm 参数
```python
client.call_llm(
    messages_list=messages,
    model="gemma3:12b",              # 可选，不指定用初始化的模型
    temperature=0.5,                 # 温度参数（默认0.1）
    max_tokens=2000,                 # 最大生成token（默认2000）
    top_p=0.95,                      # top_p采样（默认0.95）
    show_progress=True,              # 显示进度条
)
```

---

## 消息格式

### 纯文本格式
```python
{"role": "user", "content": "文本内容"}
```

### 文本+图像格式
```python
{
    "role": "user",
    "content": [
        {"type": "text", "text": "提示词"},
        {"type": "image_url", "image_url": {"url": "图像路径或URL"}}
    ]
}
```

### 多张图像
```python
{
    "role": "user",
    "content": [
        {"type": "text", "text": "提示词"},
        {"type": "image_url", "image_url": {"url": "图像1"}},
        {"type": "image_url", "image_url": {"url": "图像2"}},
    ]
}
```

---

## 快速对比

| 功能 | OpenAIClient | MllmClient |
|------|--------------|-----------|
| 纯文本调用 | ✅ | ✅ |
| 图像处理 | ✅ 基础 | ✅✅ 强大 |
| 图像缓存 | ✅ | ✅ |
| 批量处理 | ✅ | ✅ |
| 异步支持 | ✅ | ✅ |
| 表格处理 | ❌ | ✅ |
| 文件夹处理 | ❌ | ✅ |

---

## 常见用法

### OpenAI 兼容服务
```python
# 调用本地或远程 OpenAI 兼容 API
client = OpenAIClient(
    base_url="http://localhost:8000/v1",
    api_key="your-key"
)
```

### 本地 Ollama 服务
```python
# 调用本地 Ollama
client = MllmClient(
    model="gemma3:12b",
    base_url="http://localhost:11434/v1/"
)
```

### vLLM 服务
```python
# 调用 vLLM 服务
client = OpenAIClient(
    base_url="http://localhost:8000/v1",
    api_key="EMPTY"
)
```

---

## 提示

- 使用 `relp()` 函数处理相对路径
- 异步函数用 `asyncio.run()` 运行
- 同步函数直接调用（带 `_sync` 后缀）
- 支持本地路径和网络 URL
- 启用 `cache_image=True` 可提升性能
