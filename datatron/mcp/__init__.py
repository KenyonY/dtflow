"""DataTransformer MCP (Model Context Protocol) 服务

提供 DataTransformer 的用法查询功能，供 AI 模型调用。

使用方式:
    # 安装 MCP 服务到 Claude Code
    dt mcp install

    # 运行 MCP 服务（通常由 Claude 自动调用）
    dt-mcp
"""

from .server import main, mcp

__all__ = ["main", "mcp"]
