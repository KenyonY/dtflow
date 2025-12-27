"""
CLI 数据血缘追踪命令
"""

from pathlib import Path

import orjson

from ..lineage import format_lineage_report, get_lineage_chain, has_lineage


def history(
    filename: str,
    json: bool = False,
) -> None:
    """
    显示数据文件的血缘历史。

    Args:
        filename: 数据文件路径
        json: 以 JSON 格式输出

    Examples:
        dt history data.jsonl
        dt history data.jsonl --json
    """
    filepath = Path(filename)

    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not has_lineage(str(filepath)):
        print(f"文件 {filename} 没有血缘记录")
        print("\n提示: 使用 track_lineage=True 加载数据，并在保存时使用 lineage=True 来记录血缘")
        print("示例:")
        print("  dt = DataTransformer.load('data.jsonl', track_lineage=True)")
        print("  dt.filter(...).transform(...).save('output.jsonl', lineage=True)")
        return

    if json:
        # JSON 格式输出
        chain = get_lineage_chain(str(filepath))
        output = [record.to_dict() for record in chain]
        print(orjson.dumps(output, option=orjson.OPT_INDENT_2).decode("utf-8"))
    else:
        # 格式化报告
        report = format_lineage_report(str(filepath))
        print(report)
