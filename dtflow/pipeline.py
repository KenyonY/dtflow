"""
Pipeline 配置模块

支持将数据处理流程导出为 YAML 配置，实现可复现的数据处理。
"""

import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from .core import DataTransformer
from .presets import PRESETS, get_preset
from .storage.io import load_data

# ============ Pipeline 配置格式 ============

PIPELINE_VERSION = "1.0"


def _load_yaml(filepath: str) -> Dict[str, Any]:
    """加载 YAML 配置文件"""
    try:
        import yaml
    except ImportError:
        raise ImportError("需要安装 PyYAML: pip install pyyaml") from None

    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_yaml(data: Dict[str, Any], filepath: str) -> None:
    """保存 YAML 配置文件"""
    try:
        import yaml
    except ImportError:
        raise ImportError("需要安装 PyYAML: pip install pyyaml") from None

    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


# ============ 步骤执行器 ============


def _execute_filter(dt: DataTransformer, step: Dict[str, Any]) -> DataTransformer:
    """
    执行 filter 步骤: ``expr`` 为 Python 表达式, 当前行为 x (与 CLI --where 同一套语法)。

        - type: filter
          expr: "x.score > 0.5 and len(x.text) > 10"
    """
    from .expr import compile_where

    expr = step.get("expr")
    if not expr:
        raise ValueError("filter 步骤需要指定 expr")
    return dt.filter(compile_where(expr), raw=True)


def _execute_transform(dt: DataTransformer, step: Dict[str, Any]) -> DataTransformer:
    """执行 transform 步骤"""
    preset = step.get("preset")
    params = step.get("params", {})

    if not preset:
        raise ValueError("transform 步骤需要指定 preset")

    if preset not in PRESETS:
        available = ", ".join(PRESETS.keys())
        raise ValueError(f"未知预设: {preset}。可用预设: {available}")

    transform_func = get_preset(preset, **params)
    return dt.transform(transform_func)


def _execute_dedupe(dt: DataTransformer, step: Dict[str, Any]) -> DataTransformer:
    """执行 dedupe 步骤"""
    key = step.get("key")
    similar = step.get("similar")

    if similar is not None:
        if not key:
            raise ValueError("相似度去重需要指定 key")
        return dt.dedupe_similar(key, threshold=similar)

    # 精确去重
    if key:
        # 支持逗号分隔的多字段
        if isinstance(key, str) and "," in key:
            key = [k.strip() for k in key.split(",")]
    return dt.dedupe(key)


def _execute_sample(dt: DataTransformer, step: Dict[str, Any]) -> DataTransformer:
    """执行 sample 步骤"""
    num = step.get("num", 10)
    seed = step.get("seed")
    return dt.sample(num, seed=seed)


def _execute_head(dt: DataTransformer, step: Dict[str, Any]) -> DataTransformer:
    """执行 head 步骤"""
    num = step.get("num", 10)
    return dt.head(num)


def _execute_tail(dt: DataTransformer, step: Dict[str, Any]) -> DataTransformer:
    """执行 tail 步骤"""
    num = step.get("num", 10)
    return dt.tail(num)


def _execute_shuffle(dt: DataTransformer, step: Dict[str, Any]) -> DataTransformer:
    """执行 shuffle 步骤"""
    seed = step.get("seed")
    return dt.shuffle(seed=seed)


def _execute_split(dt: DataTransformer, step: Dict[str, Any]) -> DataTransformer:
    """
    执行 split 步骤。

    注意：split 会产生两个输出，这里只返回第一个（train），
    第二个（test）会在 run_pipeline 中特殊处理。
    """
    ratio = step.get("ratio", 0.8)
    seed = step.get("seed")
    train, _ = dt.split(ratio=ratio, seed=seed)
    return train


# 步骤执行器映射
STEP_EXECUTORS = {
    "filter": _execute_filter,
    "transform": _execute_transform,
    "dedupe": _execute_dedupe,
    "sample": _execute_sample,
    "head": _execute_head,
    "tail": _execute_tail,
    "shuffle": _execute_shuffle,
    "split": _execute_split,
}


# ============ Pipeline 执行器 ============


def run_pipeline(
    config_path: str,
    input_file: Optional[str] = None,
    output_file: Optional[str] = None,
    verbose: bool = True,
) -> DataTransformer:
    """
    执行 Pipeline 配置文件。

    Args:
        config_path: YAML 配置文件路径
        input_file: 输入文件路径（覆盖配置中的 input）
        output_file: 输出文件路径（覆盖配置中的 output）
        verbose: 是否打印执行过程

    Returns:
        处理后的 DataTransformer

    Examples:
        >>> run_pipeline("pipeline.yaml")
        >>> run_pipeline("pipeline.yaml", input_file="new_data.jsonl")
    """
    # 加载配置
    config = _load_yaml(config_path)

    # 验证版本
    version = config.get("version", "1.0")
    if version != PIPELINE_VERSION:
        if verbose:
            print(f"⚠ 配置版本 {version} 与当前版本 {PIPELINE_VERSION} 不一致")

    # 设置全局随机种子
    seed = config.get("seed")
    if seed is not None:
        random.seed(seed)
        if verbose:
            print(f"🎲 设置随机种子: {seed}")

    # 确定输入文件
    input_path = input_file or config.get("input")
    if not input_path:
        raise ValueError("未指定输入文件，请在配置中设置 input 或使用 --input 参数")

    # 加载数据
    if verbose:
        print(f"📂 加载数据: {input_path}")
    dt = DataTransformer.load(input_path)
    if verbose:
        print(f"   共 {len(dt)} 条数据")

    # 执行步骤
    steps = config.get("steps", [])
    for i, step in enumerate(steps, 1):
        step_type = step.get("type")
        if not step_type:
            raise ValueError(f"步骤 {i} 未指定 type")

        if step_type not in STEP_EXECUTORS:
            available = ", ".join(STEP_EXECUTORS.keys())
            raise ValueError(f"未知步骤类型: {step_type}。可用类型: {available}")

        if verbose:
            step_desc = _format_step_description(step)
            print(f"🔄 步骤 {i}: {step_desc}")

        before_count = len(dt)
        dt = STEP_EXECUTORS[step_type](dt, step)
        after_count = len(dt)

        if verbose and before_count != after_count:
            print(f"   {before_count} → {after_count} 条")

    # 保存结果
    output_path = output_file or config.get("output")
    if output_path:
        if verbose:
            print(f"💾 保存结果: {output_path}")
        dt.save(output_path)
        if verbose:
            print(f"\n✅ 完成! 共 {len(dt)} 条数据")

    return dt


def _format_step_description(step: Dict[str, Any]) -> str:
    """格式化步骤描述"""
    step_type = step.get("type", "")

    if step_type == "filter":
        return f"filter ({step.get('expr')})"
    elif step_type == "transform":
        preset = step.get("preset", "")
        return f"transform ({preset})"
    elif step_type == "dedupe":
        key = step.get("key", "全量")
        similar = step.get("similar")
        if similar:
            return f"dedupe ({key}, 相似度={similar})"
        return f"dedupe ({key})"
    elif step_type == "sample":
        num = step.get("num", 10)
        return f"sample ({num})"
    elif step_type in ("head", "tail"):
        num = step.get("num", 10)
        return f"{step_type} ({num})"
    elif step_type == "shuffle":
        return "shuffle"
    elif step_type == "split":
        ratio = step.get("ratio", 0.8)
        return f"split (ratio={ratio})"
    else:
        return step_type


# ============ Pipeline 模板生成 ============


def generate_pipeline_template(
    input_file: str,
    output_file: str = "pipeline.yaml",
    preset: Optional[str] = None,
) -> str:
    """
    生成 Pipeline 配置模板。

    Args:
        input_file: 输入文件路径
        output_file: 配置文件输出路径

    Returns:
        生成的配置文件路径
    """
    # 分析输入数据
    data = load_data(input_file)
    if not data:
        raise ValueError("输入文件为空")

    sample = data[0]
    fields = list(sample.keys())

    # 构建配置
    config = {
        "version": PIPELINE_VERSION,
        "seed": 42,
        "input": input_file,
        "output": Path(input_file).stem + "_output.jsonl",
        "steps": [],
    }

    # 添加示例步骤
    if preset:
        config["steps"].append(
            {
                "type": "transform",
                "preset": preset,
            }
        )
    else:
        # 根据字段推断可能的步骤
        config["steps"].append(
            {
                "type": "filter",
                "expr": f"len(x.{fields[0]}) > 0",
            }
        )

        # 如果有 messages 或 q/a 字段，添加 transform 步骤
        if "messages" in fields:
            pass  # 已经是 messages 格式
        elif "q" in fields and "a" in fields:
            config["steps"].append(
                {
                    "type": "transform",
                    "preset": "openai_chat",
                    "params": {"user_field": "q", "assistant_field": "a"},
                }
            )
        elif "instruction" in fields and "output" in fields:
            config["steps"].append(
                {
                    "type": "transform",
                    "preset": "alpaca",
                }
            )

        # 添加去重步骤
        config["steps"].append(
            {
                "type": "dedupe",
                "key": fields[0] if fields else None,
            }
        )

    # 保存配置
    _save_yaml(config, output_file)

    return output_file


def validate_pipeline(config_path: str) -> List[str]:
    """
    验证 Pipeline 配置文件。

    Args:
        config_path: 配置文件路径

    Returns:
        错误列表，空列表表示验证通过
    """
    errors = []

    try:
        config = _load_yaml(config_path)
    except Exception as e:
        return [f"无法解析配置文件: {e}"]

    # 检查必需字段
    if "steps" not in config:
        errors.append("缺少 steps 字段")

    # 检查步骤
    steps = config.get("steps", [])
    for i, step in enumerate(steps, 1):
        if "type" not in step:
            errors.append(f"步骤 {i} 缺少 type 字段")
            continue

        step_type = step["type"]
        if step_type not in STEP_EXECUTORS:
            available = ", ".join(STEP_EXECUTORS.keys())
            errors.append(f"步骤 {i}: 未知类型 '{step_type}'，可用: {available}")

        # 特定步骤的验证
        if step_type == "transform" and "preset" not in step:
            errors.append(f"步骤 {i}: transform 需要指定 preset")

        if step_type == "filter":
            expr = step.get("expr")
            if not expr:
                errors.append(f"步骤 {i}: filter 需要指定 expr (Python 表达式, 当前行为 x)")
            else:
                from .expr import ExprSyntaxError, check_syntax

                try:
                    check_syntax(str(expr))
                except ExprSyntaxError as e:
                    errors.append(f"步骤 {i}: filter expr {e}")

    return errors
