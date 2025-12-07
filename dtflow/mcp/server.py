"""Datatron MCP 服务

提供 Datatron 用法查询的 MCP (Model Context Protocol) 服务。
"""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .docs import DOCS, TOPICS, get_doc

# 创建 MCP 服务实例
mcp = Server("dtflow")


@mcp.list_tools()
async def list_tools() -> list[Tool]:
    """列出可用的工具"""
    return [
        Tool(
            name="dt_usage",
            description="查询 Datatron 的用法文档。Datatron 是一个专业的数据格式转换工具，用于机器学习训练数据的格式转换（SFT、RLHF等）。可查询的主题包括: overview(概述), basic_usage(基本用法), presets(预设模板), cli(命令行), storage(存储格式), chain_api(链式API)",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": f"要查询的主题。可选值: {', '.join(TOPICS)}",
                        "enum": TOPICS,
                    }
                },
                "required": ["topic"],
            },
        ),
        Tool(
            name="dt_list_topics",
            description="列出所有可用的 Datatron 文档主题",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="dt_quick_start",
            description="获取 Datatron 快速入门指南，包含最常用的用法示例",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@mcp.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """处理工具调用"""
    if name == "dt_usage":
        topic = arguments.get("topic", "overview")
        content = get_doc(topic)
        return [TextContent(type="text", text=content)]

    elif name == "dt_list_topics":
        topics_info = """# Datatron 文档主题

可用主题列表:

| 主题 | 描述 |
|------|------|
| overview | 项目概述和快速开始 |
| basic_usage | 基本操作（加载、转换、筛选） |
| presets | 预设模板（OpenAI Chat、Alpaca、ShareGPT 等） |
| cli | 命令行工具使用 |
| storage | 存储格式支持（JSONL、CSV、Parquet 等） |
| chain_api | 链式 API 设计 |

使用 `dt_usage` 工具并传入主题名称即可查看详细文档。
"""
        return [TextContent(type="text", text=topics_info)]

    elif name == "dt_quick_start":
        quick_start = """# Datatron 快速入门

## 安装
```bash
pip install dtflow
```

## 最常用的用法

### 1. Python API
```python
from dtflow import DataTransformer

# 加载数据
dt = DataTransformer.load("data.jsonl")

# 查看字段和统计
print(dt.fields())   # ['a', 'q', ...]
print(dt.stats())    # {'total': 1000, ...}

# 转换格式（lambda 支持属性访问）
result = dt.to(lambda x: {
    "instruction": x.q,
    "output": x.a
})

# 链式调用
dt.filter(lambda x: len(x.q) > 10) \\
  .sample(100) \\
  .transform(lambda x: {"q": x.q, "a": x.a}) \\
  .save("output.jsonl")
```

### 2. CLI 命令
```bash
# 使用预设转换
dt transform data.jsonl --preset=openai_chat
dt transform data.jsonl --preset=alpaca

# 数据采样
dt sample data.jsonl --num=10
```

### 3. 可用预设
- `openai_chat`: OpenAI Chat 格式
- `alpaca`: Alpaca 指令格式
- `sharegpt`: ShareGPT 多轮对话
- `dpo_pair`: DPO 偏好对格式
- `simple_qa`: 简单问答格式

更多详情请使用 `dt_usage` 查询具体主题。
"""
        return [TextContent(type="text", text=quick_start)]

    else:
        return [TextContent(type="text", text=f"未知工具: {name}")]


async def run_server():
    """运行 MCP 服务"""
    async with stdio_server() as (read_stream, write_stream):
        await mcp.run(read_stream, write_stream, mcp.create_initialization_options())


def main():
    """入口函数"""
    import asyncio

    asyncio.run(run_server())


if __name__ == "__main__":
    main()
