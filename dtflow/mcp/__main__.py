"""Datatron MCP 服务入口

使用方式:
    python -m dtflow.mcp
"""

if __name__ == "__main__":
    try:
        from .server import main
        main()
    except ImportError as e:
        import sys
        print(f"错误: MCP 功能需要安装 mcp 依赖", file=sys.stderr)
        print(f"请运行: pip install dtflow[mcp]", file=sys.stderr)
        print(f"\n原始错误: {e}", file=sys.stderr)
        sys.exit(1)
