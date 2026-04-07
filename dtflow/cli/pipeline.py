"""
CLI Pipeline 执行命令
"""

from pathlib import Path
from typing import Optional

from ..pipeline import run_pipeline, validate_pipeline
from .output import die, die_io_error, die_usage, emit_action


def run(
    config: str,
    input: Optional[str] = None,
    output: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """
    执行 Pipeline 配置文件。

    Args:
        config: Pipeline YAML 配置文件路径
        input: 输入文件路径（覆盖配置中的 input）
        output: 输出文件路径（覆盖配置中的 output）
        dry_run: 仅验证配置并打印执行计划，不真正执行

    Examples:
        dt run pipeline.yaml
        dt run pipeline.yaml --input=new_data.jsonl
        dt run pipeline.yaml --input=data.jsonl --output=result.jsonl
        dt run pipeline.yaml --dry-run          # 验证配置, 打印步骤链
    """
    config_path = Path(config)

    if not config_path.exists():
        from .output import die_file_not_found

        die_file_not_found(str(config_path))

    if config_path.suffix.lower() not in (".yaml", ".yml"):
        die_usage(
            "配置文件必须是 YAML 格式 (.yaml 或 .yml)",
            suggestion=f"请使用 .yaml/.yml 后缀, 当前: {config_path.suffix}",
        )

    # 验证配置
    errors = validate_pipeline(config)
    if errors:
        die(
            "pipeline_invalid",
            "Pipeline 配置文件验证失败",
            suggestion="根据下方错误修正 YAML 配置",
            exit_code=2,
            context={"errors": errors},
        )

    if dry_run:
        # 读取配置, 展示将要执行的步骤链
        try:
            import yaml

            with open(config, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception as e:
            die_io_error(e, operation="读取配置文件", path=str(config_path))

        steps = cfg.get("steps") or cfg.get("pipeline") or []
        planned = []
        for step in steps:
            if isinstance(step, dict):
                # 取 name/type 作为步骤标识
                label = (
                    step.get("name") or step.get("type") or step.get("op") or list(step.keys())[0]
                )
                planned.append({"step": label, "config": step})
            else:
                planned.append({"step": str(step)})

        stats = {
            "config": str(config_path),
            "input": input or cfg.get("input"),
            "output": output or cfg.get("output"),
            "step_count": len(planned),
        }
        emit_action(
            "run",
            input_files=[str(config_path)],
            output=output or cfg.get("output"),
            stats=stats,
            dry_run=True,
            extra={"plan": planned},
        )
        return

    # 执行 pipeline
    try:
        run_pipeline(config, input_file=input, output_file=output, verbose=True)
    except Exception as e:
        die(
            "pipeline_error",
            str(e),
            suggestion="检查 pipeline 步骤定义和输入数据格式",
            exit_code=1,
        )

    emit_action(
        "run",
        input_files=[str(config_path)],
        output=output,
        stats={"config": str(config_path)},
    )
