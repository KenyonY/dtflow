"""
CLI Pipeline 执行命令
"""

from pathlib import Path
from typing import Optional

from ..pipeline import run_pipeline, validate_pipeline


def run(
    config: str,
    input: Optional[str] = None,
    output: Optional[str] = None,
) -> None:
    """
    执行 Pipeline 配置文件。

    Args:
        config: Pipeline YAML 配置文件路径
        input: 输入文件路径（覆盖配置中的 input）
        output: 输出文件路径（覆盖配置中的 output）

    Examples:
        dt run pipeline.yaml
        dt run pipeline.yaml --input=new_data.jsonl
        dt run pipeline.yaml --input=data.jsonl --output=result.jsonl
    """
    config_path = Path(config)

    if not config_path.exists():
        print(f"错误: 配置文件不存在 - {config}")
        return

    if config_path.suffix.lower() not in (".yaml", ".yml"):
        print(f"错误: 配置文件必须是 YAML 格式 (.yaml 或 .yml)")
        return

    # 验证配置
    errors = validate_pipeline(config)
    if errors:
        print("❌ 配置文件验证失败:")
        for err in errors:
            print(f"   - {err}")
        return

    # 执行 pipeline
    try:
        run_pipeline(config, input_file=input, output_file=output, verbose=True)
    except Exception as e:
        print(f"错误: {e}")
        import traceback

        traceback.print_exc()
