"""
CLI Pipeline 执行命令 (dt run)
"""

from pathlib import Path
from typing import Optional

from ..i18n import t
from ..pipeline import TERMINAL_STEPS, _load_yaml, build_pipeline, run_pipeline, validate_pipeline
from .output import die, die_usage, emit_action, log


def run(
    config: str,
    input: Optional[str] = None,
    output: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """
    执行 Pipeline 配置文件。step 的 type 即 CLI 命令名, 参数即 CLI 选项名。

    Args:
        config: Pipeline YAML 配置文件路径
        input: 输入文件路径（覆盖配置中的 input; - 为 stdin）
        output: 输出文件路径（覆盖配置中的 output; 两者都没有则写 stdout）
        dry_run: 仅验证配置并打印执行计划，不真正执行

    Examples:
        dt run pipeline.yaml
        dt run pipeline.yaml --input=new_data.jsonl
        dt run pipeline.yaml --input=data.jsonl --output=result.jsonl
        cat data.jsonl | dt run pipeline.yaml -i - | dt head -
        dt run pipeline.yaml --dry-run          # 验证配置, 打印步骤链
    """
    from .pipe import input_label, write_output

    config_path = Path(config)
    if not config_path.exists():
        from .output import die_file_not_found

        die_file_not_found(str(config_path))
    if config_path.suffix.lower() not in (".yaml", ".yml"):
        die_usage(
            t(
                "Config file must be YAML (.yaml or .yml)",
                "配置文件必须是 YAML 格式 (.yaml 或 .yml)",
            ),
            suggestion=t(
                f"Use a .yaml/.yml suffix (got: {config_path.suffix})",
                f"请使用 .yaml/.yml 后缀, 当前: {config_path.suffix}",
            ),
        )

    errors = validate_pipeline(config)
    if errors:
        die(
            "pipeline_invalid",
            t("Pipeline config validation failed", "Pipeline 配置文件验证失败"),
            suggestion=t(
                "Fix the YAML config according to the errors below", "根据下方错误修正 YAML 配置"
            ),
            exit_code=2,
            context={"errors": errors},
        )

    cfg = _load_yaml(config)
    steps = cfg.get("steps") or []
    input_path = input or cfg.get("input")
    output_path = output or cfg.get("output")
    if output_path == "-":
        output_path = None

    if dry_run:
        planned = [{"step": s.get("type"), "config": s} for s in steps if isinstance(s, dict)]
        emit_action(
            "run",
            input_files=[str(config_path)],
            output=output_path,
            stats={
                "config": str(config_path),
                "input": input_path,
                "output": output_path,
                "step_count": len(planned),
            },
            dry_run=True,
            extra={"plan": planned},
        )
        return

    if not input_path:
        die_usage(
            t("No input file specified", "未指定输入文件"),
            suggestion=t(
                "Set input in the config or pass --input (- for stdin)",
                "在配置中设置 input 或使用 --input (- 为 stdin)",
            ),
        )

    terminal = bool(steps) and steps[-1].get("type") in TERMINAL_STEPS
    try:
        if terminal:
            if not output_path:
                die_usage(
                    t(
                        "A pipeline ending in split needs output "
                        "as the base for derived file names",
                        "以 split 结尾的 pipeline 需要 output 作为派生文件名的基准",
                    )
                )
            result = run_pipeline(
                config, input_file=input_path, output_file=output_path, verbose=False
            )
            for s in result["splits"]:
                log(
                    t(
                        f"   {s['name']}: {s['rows']} rows -> {s['path']}",
                        f"   {s['name']}: {s['rows']} 条 -> {s['path']}",
                    )
                )
            emit_action(
                "run",
                input_files=[input_label(input_path)],
                output=output_path,
                stats={"config": str(config_path), **result},
            )
            return
        st = build_pipeline(cfg, input_path, verbose=False)
    except ValueError as e:
        die(
            "pipeline_error",
            str(e),
            suggestion=t(
                "Check the pipeline step definitions and the input data format",
                "检查 pipeline 步骤定义和输入数据格式",
            ),
            exit_code=1,
        )
    write_output(
        st, output_path, action="run", inputs=[input_path], stats={"config": str(config_path)}
    )
