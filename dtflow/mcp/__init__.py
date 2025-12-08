"""DataTransformer MCP (Model Context Protocol) 服务

提供 DataTransformer 的用法查询功能，供 AI 模型调用。

使用方式:
    # 安装 MCP 服务到 Claude Code
    dt mcp install

    # 运行 MCP 服务（通常由 Claude 自动调用）
    dt-mcp

注意: MCP 功能需要安装 mcp 依赖: pip install dtflow[mcp]
"""

__all__ = ["main", "mcp"]


def __getattr__(name):
    """延迟导入 server 模块，避免在未安装 mcp 依赖时报错"""
    if name in ("main", "mcp"):
        try:
            from .server import main, mcp
            return main if name == "main" else mcp
        except ImportError as e:
            raise ImportError(
                f"MCP 功能需要安装 mcp 依赖: pip install dtflow[mcp]\n原始错误: {e}"
            ) from e
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
