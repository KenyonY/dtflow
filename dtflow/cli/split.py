"""
CLI 数据集切分命令
"""

from pathlib import Path
from typing import Optional

from rich.markup import escape

from ..i18n import t
from ..ops import parse_ratio, split_names, split_rows
from ..storage.io import save_data
from .output import die_io_error, die_usage, emit_action, log


def split(
    filename: str,
    ratio: str = "0.8",
    seed: Optional[int] = None,
    output: Optional[str] = None,
    dry_run: bool = False,
    name: Optional[str] = None,
) -> None:
    """
    分割数据集为 train/test (或 train/val/test)。

    Args:
        filename: 输入文件路径 (- 为 stdin, 此时必须给 -o 目录和 --name 前缀)
        ratio: 分割比例，如 "0.8" 或 "0.7,0.15,0.15"
        seed: 随机种子
        output: 输出目录（默认同目录）
        dry_run: 预演模式，仅计算各切分行数但不写入文件
        name: 输出文件名前缀 (默认取输入文件名); 输出为 <name>_train.jsonl 等

    Examples:
        dt split data.jsonl --ratio=0.8
        dt split data.jsonl --ratio=0.7,0.15,0.15 --seed=42
        dt split data.jsonl --ratio=0.8 --dry-run
    """
    from .pipe import input_label, is_stdin, load_rows

    filepath = Path(filename)
    if output == "-":
        die_usage(
            t(
                "split writes multiple files; -o must be a directory, not -",
                "split 输出多个文件, -o 必须是目录, 不能是 -",
            )
        )
    if is_stdin(filename) and not (output and name):
        die_usage(
            t(
                "stdin input requires an output directory and a file name prefix",
                "stdin 输入需要指定输出目录和文件名前缀",
            ),
            suggestion="-o DIR --name STEM",
        )

    # 解析比例
    try:
        ratios = parse_ratio(ratio)
    except ValueError as e:
        die_usage(
            str(e),
            suggestion=t(
                "Example: --ratio=0.8 (two-way) or --ratio=0.7,0.15,0.15 (three-way)",
                "示例: --ratio=0.8 (二分) 或 --ratio=0.7,0.15,0.15 (三分)",
            ),
        )
    names = split_names(len(ratios))

    # 加载数据
    log(
        t(
            f"[bold]📊 Loading:[/bold] {input_label(filename)}",
            f"[bold]📊 加载数据:[/bold] {input_label(filename)}",
        )
    )
    rows = load_rows(filename)
    total = len(rows)
    log(t(f"   {total} records", f"   共 {total} 条数据"))
    if seed is not None:
        log(t(f"🎲 Random seed: {seed}", f"🎲 随机种子: {seed}"))
    parts = split_rows(rows, ratios, seed)

    # 确定输出目录
    if output:
        output_dir = Path(output)
        if not dry_run:
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                die_io_error(
                    e, operation=t("Create output directory", "创建输出目录"), path=str(output_dir)
                )
    else:
        output_dir = filepath.parent

    # 收集 split 信息
    stem = name or filepath.stem
    ext = ".jsonl" if is_stdin(filename) else filepath.suffix

    ratio_text = " / ".join(f"{r:.0%}" for r in ratios)
    log(t(f"[bold]🔀 Split ratio:[/bold] {ratio_text}", f"[bold]🔀 切分比例:[/bold] {ratio_text}"))
    split_info = []
    for i, (part_name, part) in enumerate(zip(names, parts, strict=False)):
        output_path = output_dir / f"{stem}_{part_name}{ext}"
        split_info.append(
            {
                "name": part_name,
                "rows": len(part),
                "ratio": ratios[i],
                "path": str(output_path),
            }
        )

    stats = {
        "input_rows": total,
        "ratios": ratios,
        "splits": split_info,
        "seed": seed,
    }

    if dry_run:
        emit_action(
            "split",
            input_files=[input_label(filename)],
            output=str(output_dir),
            stats=stats,
            dry_run=True,
        )
        return

    # 保存各部分
    for info, part in zip(split_info, parts, strict=False):
        try:
            save_data(part, info["path"])
        except Exception as e:
            die_io_error(e, operation=t("Save", "保存"), path=str(info["path"]))
        log(
            t(
                f"   {escape(info['name'])}: {info['rows']} rows "
                f"({info['ratio'] * 100:.1f}%) -> {info['path']}",
                f"   {escape(info['name'])}: {info['rows']} 条 "
                f"({info['ratio'] * 100:.1f}%) -> {info['path']}",
            )
        )

    emit_action(
        "split",
        input_files=[input_label(filename)],
        output=str(output_dir),
        stats=stats,
    )
