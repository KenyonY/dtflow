"""
CLI 数据血缘追踪命令
"""

from pathlib import Path
from typing import Optional

from ..lineage import format_lineage_report, get_lineage_chain, has_lineage
from .output import die, emit_json, is_stdout_tty, log, resolve_format


def history(
    filename: str,
    json: bool = False,
    format: Optional[str] = None,
) -> None:
    """
    显示数据文件的血缘历史。

    Args:
        filename: 数据文件路径
        json: 以 JSON 格式输出 (保留向后兼容, 等价于 --format=json)
        format: 输出格式 (json|ndjson|table)

    Examples:
        dt history data.jsonl
        dt history data.jsonl --json
        dt --format=json history data.jsonl
    """
    filepath = Path(filename)

    if not filepath.exists():
        from .output import die_file_not_found

        die_file_not_found(str(filepath))

    if not has_lineage(str(filepath)):
        die(
            "no_lineage",
            f"文件 {filename} 没有血缘记录",
            suggestion=(
                "加载时使用 DataTransformer.load(..., track_lineage=True)，"
                "保存时使用 .save(..., lineage=True)"
            ),
            exit_code=3,
        )

    # 向后兼容: --json 等价 --format=json
    fmt = resolve_format(format, default_for_tty="table")
    if json:
        fmt = "json"

    chain = get_lineage_chain(str(filepath))
    records = [record.to_dict() for record in chain]

    if fmt == "ndjson":
        from .output import emit_ndjson

        emit_ndjson(records)
        return

    if fmt == "json" or not is_stdout_tty():
        emit_json(records)
        return

    # TTY table: 直接打印人类可读报告到 stdout
    # (report 本身已经是格式化文本, 不走 log 以便用户可重定向查看)
    report = format_lineage_report(str(filepath))
    log(report)
