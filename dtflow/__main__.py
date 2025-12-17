"""
Datatron CLI entry point.

Usage:
    python -m datatron <command> [options]
    dt <command> [options]

Commands:
    transform  转换数据格式（核心命令）
    sample     从数据文件中采样
    head       显示文件的前 N 条数据
    tail       显示文件的后 N 条数据
    stats      显示数据文件的统计信息
    dedupe     数据去重
    concat     拼接多个数据文件
    clean      数据清洗
    mcp        MCP 服务管理（install/uninstall/status）
"""
import fire

from .cli import clean as _clean, concat as _concat, dedupe as _dedupe, head as _head, sample as _sample, stats as _stats, tail as _tail, transform as _transform
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
        by: str = None,
        uniform: bool = False,
    ):
        """
        从数据文件中采样指定数量的数据。

        Args:
            filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
            num: 采样数量，默认 10
                - num > 0: 采样指定数量
                - num = 0: 采样所有数据
                - num < 0: Python 切片风格（如 -1 表示最后 1 条，-10 表示最后 10 条）
            sample_type: 采样方式，可选 random/head/tail，默认 head
            output: 输出文件路径，不指定则打印到控制台
            seed: 随机种子（仅在 sample_type=random 时有效）
            by: 分层采样字段名，按该字段的值分组采样
            uniform: 均匀采样模式（需配合 --by 使用），各组采样相同数量

        Examples:
            dt sample data.jsonl 5
            dt sample data.csv 100 --sample_type=head
            dt sample data.xlsx 50 --output=sampled.jsonl
            dt sample data.jsonl 0   # 采样所有数据
            dt sample data.jsonl -10 # 最后 10 条数据
            dt sample data.jsonl 1000 --by=category           # 按比例分层采样
            dt sample data.jsonl 1000 --by=category --uniform # 均匀分层采样
        """
        _sample(filename, num, sample_type, output, seed, by, uniform)

    @staticmethod
    def head(
        filename: str,
        num: int = 10,
        output: str = None,
    ):
        """
        显示文件的前 N 条数据（dt sample --sample_type=head 的快捷方式）。

        Args:
            filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
            num: 显示数量，默认 10
                - num > 0: 显示指定数量
                - num = 0: 显示所有数据
                - num < 0: Python 切片风格（如 -10 表示最后 10 条）
            output: 输出文件路径，不指定则打印到控制台

        Examples:
            dt head data.jsonl          # 显示前 10 条
            dt head data.jsonl 20       # 显示前 20 条
            dt head data.csv 0          # 显示所有数据
            dt head data.xlsx --output=head.jsonl
        """
        _head(filename, num, output)

    @staticmethod
    def tail(
        filename: str,
        num: int = 10,
        output: str = None,
    ):
        """
        显示文件的后 N 条数据（dt sample --sample_type=tail 的快捷方式）。

        Args:
            filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
            num: 显示数量，默认 10
                - num > 0: 显示指定数量
                - num = 0: 显示所有数据
                - num < 0: Python 切片风格（如 -10 表示最后 10 条）
            output: 输出文件路径，不指定则打印到控制台

        Examples:
            dt tail data.jsonl          # 显示后 10 条
            dt tail data.jsonl 20       # 显示后 20 条
            dt tail data.csv 0          # 显示所有数据
            dt tail data.xlsx --output=tail.jsonl
        """
        _tail(filename, num, output)

    @staticmethod
    def dedupe(
        filename: str,
        key: str = None,
        similar: float = None,
        output: str = None,
    ):
        """
        数据去重。

        支持两种模式：
        1. 精确去重（默认）：完全相同的数据才去重
        2. 相似度去重：使用 MinHash+LSH 算法，相似度超过阈值则去重

        Args:
            filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
            key: 去重依据字段，多个字段用逗号分隔。不指定则全量去重
            similar: 相似度阈值（0-1），指定后启用相似度去重模式
            output: 输出文件路径，不指定则覆盖原文件

        Examples:
            dt dedupe data.jsonl                            # 全量精确去重
            dt dedupe data.jsonl --key=text                 # 按字段精确去重
            dt dedupe data.jsonl --key=text --similar=0.8   # 相似度去重
            dt dedupe data.jsonl --output=clean.jsonl       # 指定输出文件
        """
        _dedupe(filename, key, similar, output)

    @staticmethod
    def concat(
        *files: str,
        output: str = None,
        strict: bool = False,
    ):
        """
        拼接多个数据文件。

        Args:
            *files: 输入文件路径列表，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
            output: 输出文件路径，必须指定
            strict: 严格模式，字段必须完全一致，否则报错

        Examples:
            dt concat a.jsonl b.jsonl -o merged.jsonl
            dt concat data1.csv data2.csv data3.csv -o all.jsonl
            dt concat a.jsonl b.jsonl --strict -o merged.jsonl
        """
        _concat(*files, output=output, strict=strict)

    @staticmethod
    def stats(
        filename: str,
        top: int = 10,
    ):
        """
        显示数据文件的统计信息（类似 pandas df.info() + df.describe()）。

        Args:
            filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
            top: 显示频率最高的前 N 个值，默认 10

        Examples:
            dt stats data.jsonl
            dt stats data.csv --top=5
        """
        _stats(filename, top)

    @staticmethod
    def clean(
        filename: str,
        drop_empty: str = None,
        min_len: str = None,
        max_len: str = None,
        keep: str = None,
        drop: str = None,
        strip: bool = False,
        output: str = None,
    ):
        """
        数据清洗。

        Args:
            filename: 输入文件路径，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
            drop_empty: 删除空值记录（不带值删除任意空，指定字段用逗号分隔）
            min_len: 最小长度过滤，格式 "字段:长度"（如 text:10）
            max_len: 最大长度过滤，格式 "字段:长度"（如 text:1000）
            keep: 只保留指定字段（逗号分隔）
            drop: 删除指定字段（逗号分隔）
            strip: 去除所有字符串字段的首尾空白
            output: 输出文件路径，不指定则覆盖原文件

        Examples:
            dt clean data.jsonl --drop-empty                    # 删除任意空值记录
            dt clean data.jsonl --drop-empty=text,answer        # 删除指定字段为空的记录
            dt clean data.jsonl --min-len=text:10               # text 字段最少 10 字符
            dt clean data.jsonl --keep=question,answer          # 只保留这些字段
            dt clean data.jsonl --strip                         # 去除字符串首尾空白
            dt clean data.jsonl --drop-empty --strip -o out.jsonl
        """
        _clean(filename, drop_empty, min_len, max_len, keep, drop, strip, output)


def main():
    fire.Fire(Cli)


if __name__ == "__main__":
    main()
