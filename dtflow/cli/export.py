"""
CLI 训练框架导出命令
"""

from pathlib import Path
from typing import Optional

from ..core import DataTransformer
from ..framework import check_compatibility, detect_format, export_for
from .common import _check_file_format, _require_file_exists
from .output import die, die_io_error, emit_action, log


def export(
    filename: str,
    framework: str,
    output: Optional[str] = None,
    name: Optional[str] = None,
    check: bool = False,
    dry_run: bool = False,
) -> None:
    """
    导出数据到训练框架 (LLaMA-Factory, ms-swift, Axolotl)。

    Args:
        filename: 输入文件路径
        framework: 目标框架 (llama-factory, swift, axolotl)
        output: 输出目录（默认 {stem}_{framework}/）
        name: 数据集名称（默认 custom_dataset）
        check: 仅检查兼容性，不导出 (等价于 --dry-run)
        dry_run: 同 --check

    Examples:
        dt export data.jsonl --framework=llama-factory
        dt export data.jsonl --framework=swift -o dataset/
        dt export data.jsonl --framework=axolotl --check
    """
    filepath = Path(filename)

    _require_file_exists(filepath)
    _check_file_format(filepath)

    # 加载数据
    log(f"[bold]📊 加载数据:[/bold] {filepath}")
    try:
        dt = DataTransformer.load(str(filepath))
    except Exception as e:
        die_io_error(e, operation="读取", path=str(filepath))

    data = dt.data
    total = len(data)
    log(f"   共 {total} 条数据")

    # 检测格式
    fmt = detect_format(data)
    log(f"[bold]📋 检测到格式:[/bold] {fmt}")

    # 兼容性检查
    result = check_compatibility(data, framework)
    log(str(result))

    # --check 或 --dry-run 都视为预演
    is_dry_run = check or dry_run

    # 确定输出目录 (所有分支都需要)
    if output is None:
        fw_short = framework.lower().replace("-", "_")
        output = str(filepath.parent / f"{filepath.stem}_{fw_short}")
    dataset_name = name or "custom_dataset"

    stats = {
        "framework": framework,
        "detected_format": str(fmt),
        "input_rows": total,
        "compatible": bool(getattr(result, "valid", True)),
        "dataset_name": dataset_name,
    }

    if is_dry_run:
        emit_action(
            "export",
            input_files=[str(filepath)],
            output=output,
            stats=stats,
            dry_run=True,
        )
        return

    if not result.valid:
        die(
            "incompatible_data",
            "兼容性检查未通过，跳过导出",
            suggestion="使用 --check 查看具体不兼容点, 或先用 clean/transform 修正数据",
            exit_code=2,
            context={"framework": framework},
        )

    # 执行导出
    log(f"[bold]📦 导出到 {framework}...[/bold]")
    try:
        export_for(data, framework, output, dataset_name=dataset_name)
    except (PermissionError, FileExistsError, IsADirectoryError, FileNotFoundError) as e:
        die_io_error(e, operation="导出", path=output)
    except Exception as e:
        die(
            "export_failed",
            f"导出失败: {e}",
            suggestion="查看 framework 模块的支持格式 / 确认输出目录可写",
            exit_code=1,
        )

    emit_action(
        "export",
        input_files=[str(filepath)],
        output=output,
        stats=stats,
    )
