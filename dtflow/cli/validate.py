"""
CLI Schema 验证命令
"""

from pathlib import Path
from typing import Optional

from ..schema import (
    alpaca_schema,
    dpo_schema,
    openai_chat_schema,
    sharegpt_schema,
)
from ..storage.io import load_data, save_data
from .common import _check_file_format

# 预设 Schema 映射
PRESET_SCHEMAS = {
    "openai_chat": openai_chat_schema,
    "openai-chat": openai_chat_schema,
    "chat": openai_chat_schema,
    "alpaca": alpaca_schema,
    "dpo": dpo_schema,
    "dpo_pair": dpo_schema,
    "sharegpt": sharegpt_schema,
}


def validate(
    filename: str,
    preset: Optional[str] = None,
    output: Optional[str] = None,
    filter_invalid: bool = False,
    max_errors: int = 20,
    verbose: bool = False,
    workers: Optional[int] = None,
) -> None:
    """
    使用 Schema 验证数据文件。

    Args:
        filename: 输入文件路径
        preset: 预设 Schema 名称 (openai_chat, alpaca, dpo, sharegpt)
        output: 输出文件路径（保存有效数据）
        filter_invalid: 过滤无效数据并保存
        max_errors: 最多显示的错误数量
        verbose: 显示详细信息
        workers: 并行进程数，None 自动检测，1 禁用并行

    Examples:
        dt validate data.jsonl --preset=openai_chat
        dt validate data.jsonl --preset=alpaca -o valid.jsonl
        dt validate data.jsonl --preset=chat --filter
        dt validate data.jsonl --preset=chat --workers=4
    """
    filepath = Path(filename)

    if not filepath.exists():
        print(f"错误: 文件不存在 - {filename}")
        return

    if not _check_file_format(filepath):
        return

    # 确定 Schema
    if preset is None:
        # 列出可用的预设
        print("请指定预设 Schema (--preset):")
        print()
        for name in ["openai_chat", "alpaca", "dpo", "sharegpt"]:
            print(f"  --preset={name}")
        print()
        print("示例:")
        print(f"  dt validate {filename} --preset=openai_chat")
        return

    preset_lower = preset.lower().replace("-", "_")
    if preset_lower not in PRESET_SCHEMAS:
        print(f"错误: 未知的预设 Schema '{preset}'")
        print(f"可用预设: {', '.join(['openai_chat', 'alpaca', 'dpo', 'sharegpt'])}")
        return

    schema = PRESET_SCHEMAS[preset_lower]()

    # 加载数据
    try:
        data = load_data(str(filepath))
    except Exception as e:
        print(f"错误: 无法读取文件 - {e}")
        return

    if not data:
        print("文件为空")
        return

    total = len(data)
    print(f"验证文件: {filepath.name}")
    print(f"预设 Schema: {preset}")
    print(f"总记录数: {total}")
    print()

    # 验证（使用并行或串行）
    use_parallel = workers != 1 and total >= 1000

    if use_parallel:
        # 使用进度条（如果有 rich）
        try:
            from rich.progress import (
                BarColumn,
                Progress,
                SpinnerColumn,
                TaskProgressColumn,
                TextColumn,
            )

            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]验证数据"),
                BarColumn(),
                TaskProgressColumn(),
            ) as progress:
                task = progress.add_task("", total=total)

                def update_progress(current: int, total_count: int):
                    progress.update(task, completed=current)

                valid_data, invalid_results = schema.validate_parallel(
                    data, workers=workers, progress_callback=update_progress
                )
        except ImportError:
            print("🔍 验证数据...")
            valid_data, invalid_results = schema.validate_parallel(data, workers=workers)

        invalid_count = len(invalid_results)
        error_samples = invalid_results[:max_errors]
    else:
        # 串行验证
        valid_data = []
        invalid_count = 0
        error_samples = []

        for i, item in enumerate(data):
            result = schema.validate(item)
            if result.valid:
                valid_data.append(item)
            else:
                invalid_count += 1
                if len(error_samples) < max_errors:
                    error_samples.append((i, result))

    valid_count = len(valid_data)
    valid_ratio = valid_count / total * 100 if total > 0 else 0

    # 输出结果
    if invalid_count == 0:
        print(f"✅ 全部通过! {valid_count}/{total} 条记录有效 (100%)")
    else:
        print(f"⚠️ 验证结果: {valid_count}/{total} 条有效 ({valid_ratio:.1f}%)")
        print(f"   无效记录: {invalid_count} 条")
        print()

        # 显示错误示例
        print(f"错误示例 (最多显示 {max_errors} 条):")
        print("-" * 60)

        for idx, result in error_samples:
            print(f"[第 {idx} 行]")
            for err in result.errors[:3]:  # 每条记录最多显示 3 个错误
                print(f"  - {err}")
            if len(result.errors) > 3:
                print(f"  ... 还有 {len(result.errors) - 3} 个错误")
            print()

    # 保存有效数据
    if output or filter_invalid:
        output_path = output or str(filepath).replace(filepath.suffix, f"_valid{filepath.suffix}")
        save_data(valid_data, output_path)
        print(f"✅ 有效数据已保存: {output_path} ({valid_count} 条)")

    # 详细模式：显示 Schema 定义
    if verbose:
        print()
        print("Schema 定义:")
        print("-" * 40)
        print(schema)
