"""
Datatron CLI entry point.

Usage:
    python -m datatron <command> [options]
    dt <command> [options]

Commands:
    transform  转换数据格式（核心命令）
    sample     从数据文件中采样
    mcp        MCP 服务管理（install/uninstall/status）
"""
import fire

from .cli import sample as _sample, transform as _transform
from .mcp.cli import MCPCommands


class Cli:
    """Datatron CLI - 数据转换工具命令行接口"""

    def __init__(self):
        self.mcp = MCPCommands()

    @staticmethod
    def transform(
        filename: str,
        num: int = None,
        preset: str = None,
        config: str = None,
        output: str = None,
    ):
        """
        转换数据格式。

        两种使用方式：
        1. 配置文件模式（默认）：自动生成配置文件，编辑后再次运行
        2. 预设模式：使用 --preset 直接转换

        Args:
            filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
            num: 只转换前 N 条数据（可选）
            preset: 使用预设模板（openai_chat, alpaca, sharegpt, dpo_pair, simple_qa）
            config: 配置文件路径（可选，默认 .dt/<filename>.py）
            output: 输出文件路径

        Examples:
            dt transform data.jsonl                        # 首次生成配置
            dt transform data.jsonl 10                     # 只转换前 10 条
            dt transform data.jsonl --preset=openai_chat   # 使用预设
            dt transform data.jsonl 100 --preset=alpaca    # 预设 + 限制数量
        """
        _transform(filename, num, preset, config, output)

    @staticmethod
    def sample(
        filename: str,
        num: int = 10,
        sample_type: str = "head",
        output: str = None,
        seed: int = None,
    ):
        """
        从数据文件中采样指定数量的数据。

        Args:
            filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
            num: 采样数量，默认 10
            sample_type: 采样方式，可选 random/head/tail，默认 random
            output: 输出文件路径，不指定则打印到控制台
            seed: 随机种子（仅在 sample_type=random 时有效）

        Examples:
            dt sample data.jsonl 5
            dt sample data.csv 100 --sample_type=head
            dt sample data.xlsx 50 --output=sampled.jsonl
        """
        _sample(filename, num, sample_type, output, seed)


def main():
    fire.Fire(Cli)


if __name__ == "__main__":
    main()
