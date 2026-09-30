"""
CLI IO 操作相关命令 (concat, diff)
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import orjson
from rich.markup import escape

from ..i18n import t
from ..storage.io import save_data
from ..utils.field_path import get_field_with_spec
from .common import _check_file_format, _require_file_exists
from .output import (
    die,
    die_io_error,
    die_usage,
    emit_action,
    emit_json,
    is_stdout_tty,
    log,
    log_panel,
    resolve_format,
)


def concat(
    *files: str,
    output: Optional[str] = None,
    strict: bool = False,
    dry_run: bool = False,
) -> None:
    """
    拼接多个数据文件（流式处理，内存占用 O(1)）。

    Args:
        *files: 输入文件路径列表 (至多一个 - 表示 stdin)，支持 csv/excel/jsonl/json/parquet/arrow/feather
        output: 输出文件路径; 不指定则写 stdout
        strict: 严格模式，字段必须完全一致，否则报错
        dry_run: 预演模式，仅分析字段和计算条数，不实际写出文件

    Examples:
        dt concat a.jsonl b.jsonl -o merged.jsonl
        dt concat data1.csv data2.csv data3.csv -o all.jsonl
        dt concat a.jsonl b.jsonl --strict -o merged.jsonl
        dt concat a.jsonl b.jsonl --dry-run -o merged.jsonl
        dt filter a.jsonl "x.ok" | dt concat - b.jsonl | dt head -
    """
    from ..streaming import StreamingTransformer
    from .common import _get_file_row_count
    from .pipe import input_label, is_stdin, open_input, write_output

    if len(files) < 2:
        die_usage(
            t("At least two input files are required", "至少需要两个输入文件"),
            suggestion="dt concat a.jsonl b.jsonl -o merged.jsonl",
        )
    if sum(is_stdin(f) for f in files) > 1:
        die_usage(t("stdin (-) may appear only once", "stdin (-) 只能出现一次"))

    # 验证文件 (stdin 跳过)
    file_paths: List[Path] = []
    for f in files:
        if is_stdin(f):
            continue
        filepath = Path(f).resolve()  # 使用绝对路径进行比较
        _require_file_exists(filepath)
        _check_file_format(filepath)
        file_paths.append(filepath)

    # 输出文件与某个输入相同 → 让 save_rows 走临时文件
    output_path = Path(output).resolve() if output else None
    reads_output = output_path is not None and output_path in file_paths
    if reads_output and not dry_run:
        log(
            t(
                "[yellow]⚠ Output is also an input; writing via a temp file[/yellow]",
                "[yellow]⚠ 检测到输出文件与输入文件相同，将使用临时文件[/yellow]",
            )
        )

    # 流式分析字段（只读取每个文件的第一行; stdin 不可预读, 跳过）
    log(t("[bold]📊 Fields per file:[/bold]", "[bold]📊 文件字段分析:[/bold]"))
    file_fields: List[tuple] = []  # [(filepath, fields)]
    for filepath in file_paths:
        try:
            first_row = open_input(str(filepath)).head(1).collect()
            fields = set(first_row[0].keys()) if first_row else set()
        except Exception as e:
            die_io_error(e, operation=t("Read", "读取"), path=str(filepath))
        if not fields:
            log(
                t(
                    f"[yellow]Warning: file is empty - {filepath}[/yellow]",
                    f"[yellow]警告: 文件为空 - {filepath}[/yellow]",
                )
            )
        file_fields.append((filepath, fields))
        fields_str = ", ".join(sorted(fields)) if fields else t("(empty)", "(空)")
        log(f"   {filepath.name}: {escape(fields_str)}")  # 字段名来自用户数据

    # 分析字段差异
    all_fields: set = set()
    common_fields: Optional[set] = None
    for _, fields in file_fields:
        all_fields.update(fields)
        common_fields = fields.copy() if common_fields is None else common_fields & fields
    common_fields = common_fields or set()
    diff_fields = all_fields - common_fields

    if diff_fields:
        if strict:
            die(
                "schema_mismatch",
                t("Strict mode: fields differ across files", "严格模式: 字段不一致"),
                suggestion=t(
                    "Drop --strict or align the fields first", "去掉 --strict 或预先统一字段"
                ),
                exit_code=2,
                context={
                    "common_fields": sorted(common_fields),
                    "diff_fields": sorted(diff_fields),
                },
            )
        log(
            t(
                f"[yellow]⚠ Fields only in some files: {escape(', '.join(sorted(diff_fields)))}[/yellow]",
                f"[yellow]⚠ 字段差异: {escape(', '.join(sorted(diff_fields)))} 仅在部分文件中存在[/yellow]",
            )
        )

    # 计算总行数（供 dry-run / 摘要使用; stdin 未知计 0）
    per_file_counts = [_get_file_row_count(p) or 0 for p in file_paths]
    total_count = sum(per_file_counts)
    stats = {
        "input_files": len(files),
        "input_rows": total_count,
        "output_rows": total_count,
        "per_file_rows": per_file_counts,
        "common_fields": sorted(common_fields),
        "diff_fields": sorted(diff_fields),
    }

    if dry_run:
        emit_action(
            "concat",
            input_files=[input_label(f) for f in files],
            output=str(output_path) if output_path else None,
            stats=stats,
            dry_run=True,
        )
        return

    log(t("[bold]🔄 Concatenating (streaming)...[/bold]", "[bold]🔄 流式拼接...[/bold]"))

    def generator():
        for f in files:
            yield from open_input(f)

    # source_path 标成输出文件本身, save_rows 据此走"临时文件 + 原子替换"
    st = StreamingTransformer(generator(), str(output_path) if reads_output else None, total=None)
    write_output(st, output, action="concat", inputs=list(files), stats=stats)


def diff(
    file1: str,
    file2: str,
    key: Optional[str] = None,
    output: Optional[str] = None,
    format: Optional[str] = None,
) -> None:
    """
    对比两个数据集的差异。

    Args:
        file1: 第一个文件路径
        file2: 第二个文件路径
        key: 用于匹配的键字段，支持嵌套路径语法（可选）
        output: 差异报告输出路径（可选）
        format: 输出格式 (json|ndjson|table) - 默认非 TTY json，TTY table

    Examples:
        dt diff v1/train.jsonl v2/train.jsonl
        dt diff a.jsonl b.jsonl --key=id
        dt diff a.jsonl b.jsonl --key=meta.uuid   # 按嵌套字段匹配
        dt diff a.jsonl b.jsonl --output=diff_report.json
        dt --format=json diff a.jsonl b.jsonl     # 强制 JSON 到 stdout
    """
    from .common import field_path_arg
    from .pipe import input_label, is_stdin, load_rows

    field_path_arg(key, "--key")
    if is_stdin(file1) and is_stdin(file2):
        die_usage(t("stdin (-) may appear only once", "stdin (-) 只能出现一次"))
    path1 = Path(input_label(file1))
    path2 = Path(input_label(file2))

    # 加载数据
    log(t("[bold]📊 Loading data...[/bold]", "[bold]📊 加载数据...[/bold]"))
    data1 = load_rows(file1)
    data2 = load_rows(file2)

    log(
        t(
            f"   File 1: {path1.name} ({len(data1)} rows)",
            f"   文件1: {path1.name} ({len(data1)} 条)",
        )
    )
    log(
        t(
            f"   File 2: {path2.name} ({len(data2)} rows)",
            f"   文件2: {path2.name} ({len(data2)} 条)",
        )
    )

    # 计算差异
    log(t("[bold]🔍 Computing diff...[/bold]", "[bold]🔍 计算差异...[/bold]"))
    diff_result = _compute_diff(data1, data2, key)

    # 输出：TTY table / 非 TTY JSON
    fmt = resolve_format(format, default_for_tty="table")
    if fmt == "table" and is_stdout_tty():
        _print_diff_report(diff_result, path1.name, path2.name)
    else:
        emit_json(diff_result)

    # 保存报告
    if output:
        log(t(f"[dim]💾 Saving report: {output}[/dim]", f"[dim]💾 保存报告: {output}[/dim]"))
        try:
            save_data([diff_result], output)
        except Exception as e:
            die_io_error(e, operation=t("Save report", "保存报告"), path=str(output))


def _compute_diff(
    data1: List[Dict],
    data2: List[Dict],
    key: Optional[str] = None,
) -> Dict[str, Any]:
    """计算两个数据集的差异"""
    result = {
        "summary": {
            "file1_count": len(data1),
            "file2_count": len(data2),
            "added": 0,
            "removed": 0,
            "modified": 0,
            "unchanged": 0,
        },
        "field_changes": {},
        "details": {
            "added": [],
            "removed": [],
            "modified": [],
        },
    }

    if key:
        # 基于 key 的精确匹配（支持嵌套路径）
        dict1 = {
            get_field_with_spec(item, key): item
            for item in data1
            if get_field_with_spec(item, key) is not None
        }
        dict2 = {
            get_field_with_spec(item, key): item
            for item in data2
            if get_field_with_spec(item, key) is not None
        }

        keys1 = set(dict1.keys())
        keys2 = set(dict2.keys())

        # 新增
        added_keys = keys2 - keys1
        result["summary"]["added"] = len(added_keys)
        result["details"]["added"] = [dict2[k] for k in list(added_keys)[:10]]  # 最多显示 10 条

        # 删除
        removed_keys = keys1 - keys2
        result["summary"]["removed"] = len(removed_keys)
        result["details"]["removed"] = [dict1[k] for k in list(removed_keys)[:10]]

        # 修改/未变
        common_keys = keys1 & keys2
        for k in common_keys:
            if dict1[k] == dict2[k]:
                result["summary"]["unchanged"] += 1
            else:
                result["summary"]["modified"] += 1
                if len(result["details"]["modified"]) < 10:
                    result["details"]["modified"].append(
                        {
                            "key": k,
                            "before": dict1[k],
                            "after": dict2[k],
                        }
                    )
    else:
        # 基于哈希的比较
        def _hash_item(item):
            return orjson.dumps(item, option=orjson.OPT_SORT_KEYS)

        set1 = {_hash_item(item) for item in data1}
        set2 = {_hash_item(item) for item in data2}

        added = set2 - set1
        removed = set1 - set2
        unchanged = set1 & set2

        result["summary"]["added"] = len(added)
        result["summary"]["removed"] = len(removed)
        result["summary"]["unchanged"] = len(unchanged)

        # 详情
        result["details"]["added"] = [orjson.loads(h) for h in list(added)[:10]]
        result["details"]["removed"] = [orjson.loads(h) for h in list(removed)[:10]]

    # 字段变化分析
    fields1 = set()
    fields2 = set()
    for item in data1[:1000]:  # 采样分析
        fields1.update(item.keys())
    for item in data2[:1000]:
        fields2.update(item.keys())

    result["field_changes"] = {
        "added_fields": sorted(fields2 - fields1),
        "removed_fields": sorted(fields1 - fields2),
        "common_fields": sorted(fields1 & fields2),
    }

    return result


def _print_diff_report(diff_result: Dict[str, Any], name1: str, name2: str) -> None:
    """把差异报告渲染到 stderr（TTY 模式，人类友好的 Panel/table）。"""
    summary = diff_result["summary"]
    field_changes = diff_result["field_changes"]

    overview = t(
        f"[bold]{name1}:[/bold] {summary['file1_count']:,} rows\n"
        f"[bold]{name2}:[/bold] {summary['file2_count']:,} rows\n"
        f"\n"
        f"[green]+ Added:[/green] {summary['added']:,}\n"
        f"[red]- Removed:[/red] {summary['removed']:,}\n"
        f"[yellow]~ Modified:[/yellow] {summary['modified']:,}\n"
        f"[dim]= Unchanged:[/dim] {summary['unchanged']:,}",
        f"[bold]{name1}:[/bold] {summary['file1_count']:,} 条\n"
        f"[bold]{name2}:[/bold] {summary['file2_count']:,} 条\n"
        f"\n"
        f"[green]+ 新增:[/green] {summary['added']:,} 条\n"
        f"[red]- 删除:[/red] {summary['removed']:,} 条\n"
        f"[yellow]~ 修改:[/yellow] {summary['modified']:,} 条\n"
        f"[dim]= 未变:[/dim] {summary['unchanged']:,} 条",
    )
    log_panel(overview, title=t("📊 Diff summary", "📊 差异概览"))

    # 字段变化
    if field_changes["added_fields"] or field_changes["removed_fields"]:
        log(t("[bold]📋 Field changes:[/bold]", "[bold]📋 字段变化:[/bold]"))
        if field_changes["added_fields"]:
            added = escape(", ".join(field_changes["added_fields"]))
            log(
                t(
                    f"  [green]+ Added fields:[/green] {added}",
                    f"  [green]+ 新增字段:[/green] {added}",
                )
            )
        if field_changes["removed_fields"]:
            removed = escape(", ".join(field_changes["removed_fields"]))
            log(
                t(
                    f"  [red]- Removed fields:[/red] {removed}",
                    f"  [red]- 删除字段:[/red] {removed}",
                )
            )
