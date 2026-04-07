"""
CLI 数据集切分命令
"""

from pathlib import Path
from typing import List, Optional

from ..core import DataTransformer
from ..storage.io import save_data
from .common import _check_file_format, _require_file_exists
from .output import die_io_error, die_usage, emit_action, log


def _parse_ratio(ratio_str: str) -> List[float]:
    """
    解析比例参数。

    - "0.8" -> [0.8, 0.2]（二分）
    - "0.8,0.1,0.1" -> [0.8, 0.1, 0.1]（三分）
    """
    parts = [float(x.strip()) for x in ratio_str.split(",")]

    if len(parts) == 1:
        if not (0 < parts[0] < 1):
            raise ValueError(f"比例必须在 0-1 之间: {parts[0]}")
        parts.append(round(1 - parts[0], 10))

    total = sum(parts)
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"比例之和必须为 1.0，当前为 {total}")

    if any(p <= 0 for p in parts):
        raise ValueError("每个比例都必须大于 0")

    return parts


# 切分名称：二分用 train/test，三分及以上用 train/val/test/part4/part5...
_SPLIT_NAMES_2 = ["train", "test"]
_SPLIT_NAMES_3 = ["train", "val", "test"]


def _get_split_names(count: int) -> List[str]:
    """根据切分数量获取名称"""
    if count == 2:
        return _SPLIT_NAMES_2
    elif count == 3:
        return _SPLIT_NAMES_3
    else:
        names = ["train", "val", "test"]
        for i in range(3, count):
            names.append(f"part{i + 1}")
        return names


def split(
    filename: str,
    ratio: str = "0.8",
    seed: Optional[int] = None,
    output: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """
    分割数据集为 train/test (或 train/val/test)。

    Args:
        filename: 输入文件路径
        ratio: 分割比例，如 "0.8" 或 "0.7,0.15,0.15"
        seed: 随机种子
        output: 输出目录（默认同目录）
        dry_run: 预演模式，仅计算各切分行数但不写入文件

    Examples:
        dt split data.jsonl --ratio=0.8
        dt split data.jsonl --ratio=0.7,0.15,0.15 --seed=42
        dt split data.jsonl --ratio=0.8 --dry-run
    """
    filepath = Path(filename)

    _require_file_exists(filepath)
    _check_file_format(filepath)

    # 解析比例
    try:
        ratios = _parse_ratio(ratio)
    except ValueError as e:
        die_usage(
            str(e),
            suggestion="示例: --ratio=0.8 (二分) 或 --ratio=0.7,0.15,0.15 (三分)",
        )

    split_names = _get_split_names(len(ratios))

    # 加载数据
    log(f"[bold]📊 加载数据:[/bold] {filepath}")
    try:
        dt = DataTransformer.load(str(filepath))
    except Exception as e:
        die_io_error(e, operation="读取", path=str(filepath))

    total = len(dt)
    log(f"   共 {total} 条数据")

    # 打乱
    shuffled = dt.shuffle(seed)
    if seed is not None:
        log(f"🎲 随机种子: {seed}")

    # 计算切分点
    data = shuffled.data
    split_indices = []
    acc = 0
    for r in ratios[:-1]:
        acc += int(total * r)
        split_indices.append(acc)

    # 切分数据
    parts = []
    prev = 0
    for idx in split_indices:
        parts.append(data[prev:idx])
        prev = idx
    parts.append(data[prev:])

    # 确定输出目录
    if output:
        output_dir = Path(output)
        if not dry_run:
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                die_io_error(e, operation="创建输出目录", path=str(output_dir))
    else:
        output_dir = filepath.parent

    # 收集 split 信息
    stem = filepath.stem
    ext = filepath.suffix

    log(f"[bold]🔀 切分比例:[/bold] {' / '.join(f'{r:.0%}' for r in ratios)}")
    split_info = []
    for i, (name, part) in enumerate(zip(split_names, parts)):
        output_path = output_dir / f"{stem}_{name}{ext}"
        split_info.append(
            {
                "name": name,
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
            input_files=[str(filepath)],
            output=str(output_dir),
            stats=stats,
            dry_run=True,
        )
        return

    # 保存各部分
    for info, part in zip(split_info, parts):
        try:
            save_data(part, info["path"])
        except Exception as e:
            die_io_error(e, operation="保存", path=str(info["path"]))
        log(f"   {info['name']}: {info['rows']} 条 ({info['ratio'] * 100:.1f}%) -> {info['path']}")

    emit_action(
        "split",
        input_files=[str(filepath)],
        output=str(output_dir),
        stats=stats,
    )
