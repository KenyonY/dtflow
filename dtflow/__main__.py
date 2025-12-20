"""
Datatron CLI entry point.

Usage:
    python -m dtflow <command> [options]
    dt <command> [options]

Commands:
    transform    转换数据格式（核心命令）
    run          执行 Pipeline 配置文件
    sample       从数据文件中采样
    head         显示文件的前 N 条数据
    tail         显示文件的后 N 条数据
    stats        显示数据文件的统计信息
    token-stats  Token 统计
    diff         数据集对比
    dedupe       数据去重
    concat       拼接多个数据文件
    clean        数据清洗
    history      显示数据血缘历史
    mcp          MCP 服务管理（install/uninstall/status）

日志查看工具 (tl):
    dtflow 内置了 toolong 日志查看器，安装后可直接使用 tl 命令：

    tl app.log              查看日志文件（交互式 TUI）
    tl app.log error.log    同时查看多个日志
    tl --tail app.log       实时跟踪模式（类似 tail -f）
    tl *.log                通配符匹配多个文件

    快捷键:
        /     搜索
        n/N   下一个/上一个匹配
        g/G   跳到开头/结尾
        f     过滤显示
        q     退出

    安装: pip install dtflow[logs] 或 pip install dtflow[full]
"""
import fire

from .cli.commands import (
    sample,
    head,
    tail,
    transform,
    dedupe,
    concat,
    stats,
    clean,
    run,
    token_stats,
    diff,
    history,
)
from .mcp.cli import MCPCommands


def logs():
    """
    日志查看工具使用说明。

    dtflow 内置了 toolong 日志查看器，安装后可直接使用 tl 命令：

    基本用法:
        tl app.log              查看日志文件（交互式 TUI）
        tl app.log error.log    同时查看多个日志
        tl --tail app.log       实时跟踪模式（类似 tail -f）
        tl *.log                通配符匹配多个文件

    快捷键:
        /     搜索
        n/N   下一个/上一个匹配
        g/G   跳到开头/结尾
        f     过滤显示
        q     退出

    安装:
        pip install dtflow[logs]   # 仅安装日志工具
        pip install dtflow[full]   # 安装全部可选依赖
    """
    print(logs.__doc__)


class Cli:
    """Datatron CLI - 数据转换工具命令行接口"""

    # 直接引用 commands.py 中的函数，无需重复定义参数
    sample = staticmethod(sample)
    head = staticmethod(head)
    tail = staticmethod(tail)
    transform = staticmethod(transform)
    dedupe = staticmethod(dedupe)
    concat = staticmethod(concat)
    stats = staticmethod(stats)
    clean = staticmethod(clean)
    run = staticmethod(run)
    token_stats = staticmethod(token_stats)
    diff = staticmethod(diff)
    history = staticmethod(history)
    logs = staticmethod(logs)

    def __init__(self):
        self.mcp = MCPCommands()


def main():
    import os
    import sys

    # less 分页器配置（仅 Unix-like 系统）
    # -R 保留颜色，-X 退出后内容保留在屏幕，-F 内容少时直接输出
    if sys.platform != 'win32':
        os.environ['PAGER'] = 'less -RXF'

    fire.Fire(Cli)


if __name__ == "__main__":
    main()
