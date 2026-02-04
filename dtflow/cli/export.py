"""
CLI 训练框架导出命令
"""

from pathlib import Path
from typing import Optional

from ..core import DataTransformer
from ..framework import check_compatibility, detect_format, export_for
from .common import _check_file_format


def export(
    filename: str,
    framework: str,
    output: Optional[str] = None,
    name: Optional[str] = None,
    check: bool = False,
) -> None:
    """
    导出数据到训练框架 (LLaMA-Factory, ms-swift, Axolotl)。

    Args:
        filename: 输入文件路径
        framework: 目标框架 (llama-factory, swift, axolotl)
        output: 输出目录（默认 {stem}_{framework}/）
        name: 数据集名称（默认 custom_dataset）
        check: 仅检查兼容性，不导出
    """
    filepath = Path(filename)

    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
        return

    # 加载数据
    print(f"📊 加载数据: {filepath}")
    try:
        dt = DataTransformer.load(str(filepath))
    except Exception as e:
        print(f"错误: 无法读取文件 - {e}")
        return

    data = dt.data
    total = len(data)
    print(f"   共 {total} 条数据")

    # 检测格式
    fmt = detect_format(data)
    print(f"📋 检测到格式: {fmt}")

    # 兼容性检查
    result = check_compatibility(data, framework)
    print(f"\n{result}")

    if check:
        return

    if not result.valid:
        print("\n❌ 兼容性检查未通过，跳过导出")
        return

    # 确定输出目录
    if output is None:
        fw_short = framework.lower().replace("-", "_")
        output = str(filepath.parent / f"{filepath.stem}_{fw_short}")

    dataset_name = name or "custom_dataset"

    # 执行导出
    print(f"\n📦 导出到 {framework}...")
    try:
        export_for(data, framework, output, dataset_name=dataset_name)
    except Exception as e:
        print(f"错误: 导出失败 - {e}")
        return

    print(f"\n✅ 导出完成! 文件保存在: {output}")
