"""
CLI IO 操作相关命令 (concat, diff)
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import orjson
from rich.markup import escape

from ..storage.io import load_data, save_data
from ..streaming import load_stream
from ..utils.field_path import get_field_with_spec
from .common import _check_file_format, _is_streaming_supported, _require_file_exists
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
        *files: 输入文件路径列表，支持 csv/excel/jsonl/json/parquet/arrow/feather 格式
        output: 输出文件路径，必须指定
        strict: 严格模式，字段必须完全一致，否则报错
        dry_run: 预演模式，仅分析字段和计算条数，不实际写出文件

    Examples:
        dt concat a.jsonl b.jsonl -o merged.jsonl
        dt concat data1.csv data2.csv data3.csv -o all.jsonl
        dt concat a.jsonl b.jsonl --strict -o merged.jsonl
        dt concat a.jsonl b.jsonl --dry-run -o merged.jsonl
    """
    if len(files) < 2:
        die_usage(
            "至少需要两个输入文件",
            suggestion="dt concat a.jsonl b.jsonl -o merged.jsonl",
        )

    if not output:
        die_usage(
            "必须指定输出文件",
            suggestion="加上 -o/--output 指定输出路径，例如 -o merged.jsonl",
        )

    # 验证所有文件
    file_paths = []
    for f in files:
        filepath = Path(f).resolve()  # 使用绝对路径进行比较
        _require_file_exists(filepath)
        _check_file_format(filepath)
        file_paths.append(filepath)

    # 检查输出文件是否与输入文件冲突
    output_path = Path(output).resolve()
    use_temp_file = output_path in file_paths
    if use_temp_file and not dry_run:
        log("[yellow]⚠ 检测到输出文件与输入文件相同，将使用临时文件[/yellow]")

    # 流式分析字段（只读取每个文件的第一行）
    log("[bold]📊 文件字段分析:[/bold]")
    file_fields: List[tuple] = []  # [(filepath, fields)]

    for filepath in file_paths:
        try:
            # 只读取第一行来获取字段（根据格式选择加载方式）
            if _is_streaming_supported(filepath):
                first_row = load_stream(str(filepath)).head(1).collect()
            else:
                # 非流式格式（如 .json, .xlsx）使用全量加载
                data = load_data(str(filepath))
                first_row = data[:1] if data else []
            if not first_row:
                log(f"[yellow]警告: 文件为空 - {filepath}[/yellow]")
                fields = set()
            else:
                fields = set(first_row[0].keys())
        except Exception as e:
            die_io_error(e, operation="读取", path=str(filepath))

        file_fields.append((filepath, fields))
        fields_str = ", ".join(sorted(fields)) if fields else "(空)"
        log(f"   {filepath.name}: {escape(fields_str)}")  # 字段名来自用户数据

    # 分析字段差异
    all_fields: set = set()
    common_fields: Optional[set] = None
    for _, fields in file_fields:
        all_fields.update(fields)
        if common_fields is None:
            common_fields = fields.copy()
        else:
            common_fields &= fields

    common_fields = common_fields or set()
    diff_fields = all_fields - common_fields

    if diff_fields:
        if strict:
            die(
                "schema_mismatch",
                "严格模式: 字段不一致",
                suggestion="去掉 --strict 或预先统一字段",
                exit_code=2,
                context={
                    "common_fields": sorted(common_fields),
                    "diff_fields": sorted(diff_fields),
                },
            )
        else:
            log(
                f"[yellow]⚠ 字段差异: {escape(', '.join(sorted(diff_fields)))} 仅在部分文件中存在[/yellow]"
            )

    # 计算总行数（供 dry-run / 摘要使用）
    total_count = 0
    per_file_counts: List[int] = []
    log("[bold]📏 计算行数...[/bold]")
    for filepath in file_paths:
        try:
            from .common import _get_file_row_count

            cnt = _get_file_row_count(filepath) or 0
            per_file_counts.append(cnt)
            total_count += cnt
        except Exception:
            per_file_counts.append(0)

    stats = {
        "input_files": len(file_paths),
        "input_rows": total_count,
        "output_rows": total_count,
        "per_file_rows": per_file_counts,
        "common_fields": sorted(common_fields),
        "diff_fields": sorted(diff_fields),
    }

    if dry_run:
        emit_action(
            "concat",
            input_files=[str(p) for p in file_paths],
            output=str(output_path),
            stats=stats,
            dry_run=True,
        )
        return

    # 流式拼接
    log("[bold]🔄 流式拼接...[/bold]")

    # 如果输出文件与输入文件冲突，使用临时文件（在输出文件同一目录下）
    if use_temp_file:
        output_dir = output_path.parent
        temp_fd, temp_path = tempfile.mkstemp(
            suffix=output_path.suffix,
            prefix=".tmp_",
            dir=output_dir,
        )
        os.close(temp_fd)
        actual_output = temp_path
        log(f"💾 写入临时文件: {temp_path}")
    else:
        actual_output = output
        log(f"💾 保存结果: {output}")

    try:
        real_count = _concat_streaming(file_paths, actual_output)

        # 如果使用了临时文件，重命名为目标文件
        if use_temp_file:
            shutil.move(temp_path, output)
            log(f"💾 移动到目标文件: {output}")
    except Exception as e:
        # 清理临时文件
        if use_temp_file and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass
        die_io_error(e, operation="拼接", path=str(output))

    stats["output_rows"] = real_count
    emit_action(
        "concat",
        input_files=[str(p) for p in file_paths],
        output=str(output_path),
        stats=stats,
    )


def _concat_streaming(file_paths: List[Path], output: str) -> int:
    """流式拼接多个文件"""
    from ..streaming import (
        StreamingTransformer,
        _stream_arrow,
        _stream_csv,
        _stream_jsonl,
        _stream_parquet,
    )

    def generator():
        for filepath in file_paths:
            ext = filepath.suffix.lower()
            if ext == ".jsonl":
                yield from _stream_jsonl(str(filepath))
            elif ext == ".csv":
                yield from _stream_csv(str(filepath))
            elif ext == ".parquet":
                yield from _stream_parquet(str(filepath))
            elif ext in (".arrow", ".feather"):
                yield from _stream_arrow(str(filepath))
            elif ext in (".json",):
                # JSON 需要全量加载
                data = load_data(str(filepath))
                yield from data
            elif ext in (".xlsx", ".xls"):
                # Excel 需要全量加载
                data = load_data(str(filepath))
                yield from data
            else:
                yield from _stream_jsonl(str(filepath))

    st = StreamingTransformer(generator())
    return st.save(output, show_progress=True)


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
    path1 = Path(file1)
    path2 = Path(file2)

    # 验证文件
    _require_file_exists(path1)
    _check_file_format(path1)
    _require_file_exists(path2)
    _check_file_format(path2)

    # 加载数据
    log("[bold]📊 加载数据...[/bold]")
    try:
        data1 = load_data(str(path1))
        data2 = load_data(str(path2))
    except Exception as e:
        die_io_error(e, operation="读取")

    log(f"   文件1: {path1.name} ({len(data1)} 条)")
    log(f"   文件2: {path2.name} ({len(data2)} 条)")

    # 计算差异
    log("[bold]🔍 计算差异...[/bold]")
    diff_result = _compute_diff(data1, data2, key)

    # 输出：TTY table / 非 TTY JSON
    fmt = resolve_format(format, default_for_tty="table")
    if fmt == "table" and is_stdout_tty():
        _print_diff_report(diff_result, path1.name, path2.name)
    else:
        emit_json(diff_result)

    # 保存报告
    if output:
        log(f"[dim]💾 保存报告: {output}[/dim]")
        try:
            save_data([diff_result], output)
        except Exception as e:
            die_io_error(e, operation="保存报告", path=str(output))


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

    overview = (
        f"[bold]{name1}:[/bold] {summary['file1_count']:,} 条\n"
        f"[bold]{name2}:[/bold] {summary['file2_count']:,} 条\n"
        f"\n"
        f"[green]+ 新增:[/green] {summary['added']:,} 条\n"
        f"[red]- 删除:[/red] {summary['removed']:,} 条\n"
        f"[yellow]~ 修改:[/yellow] {summary['modified']:,} 条\n"
        f"[dim]= 未变:[/dim] {summary['unchanged']:,} 条"
    )
    log_panel(overview, title="📊 差异概览")

    # 字段变化
    if field_changes["added_fields"] or field_changes["removed_fields"]:
        log("[bold]📋 字段变化:[/bold]")
        if field_changes["added_fields"]:
            log(f"  [green]+ 新增字段:[/green] {escape(', '.join(field_changes['added_fields']))}")
        if field_changes["removed_fields"]:
            log(f"  [red]- 删除字段:[/red] {escape(', '.join(field_changes['removed_fields']))}")
