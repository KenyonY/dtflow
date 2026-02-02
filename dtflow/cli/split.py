"""
CLI 数据集切分命令
"""

from pathlib import Path
from typing import List, Optional

from ..core import DataTransformer
from ..storage.io import save_data
from .common import _check_file_format


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
) -> None:
    """
    分割数据集为 train/test (或 train/val/test)。

    Args:
        filename: 输入文件路径
        ratio: 分割比例，如 "0.8" 或 "0.7,0.15,0.15"
        seed: 随机种子
        output: 输出目录（默认同目录）
    """
    filepath = Path(filename)

    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
        return

    # 解析比例
    try:
        ratios = _parse_ratio(ratio)
    except ValueError as e:
        print(f"错误: {e}")
        return

    split_names = _get_split_names(len(ratios))

    # 加载数据
    print(f"📊 加载数据: {filepath}")
    try:
        dt = DataTransformer.load(str(filepath))
    except Exception as e:
        print(f"错误: 无法读取文件 - {e}")
        return

    total = len(dt)
    print(f"   共 {total} 条数据")

    # 打乱
    shuffled = dt.shuffle(seed)
    if seed is not None:
        print(f"🎲 随机种子: {seed}")

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
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = filepath.parent

    # 保存各部分
    stem = filepath.stem
    ext = filepath.suffix

    print(f"\n🔀 切分比例: {' / '.join(f'{r:.0%}' for r in ratios)}")
    for i, (name, part) in enumerate(zip(split_names, parts)):
        output_path = output_dir / f"{stem}_{name}{ext}"
        save_data(part, str(output_path))
        pct = ratios[i] * 100
        print(f"   {name}: {len(part)} 条 ({pct:.1f}%) -> {output_path}")

    print(f"\n✅ 完成! 共切分为 {len(ratios)} 个部分")
