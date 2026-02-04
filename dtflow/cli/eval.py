"""
CLI eval 命令实现

对模型输出进行解析 + 指标计算，支持两阶段解析和管道式提取。
"""

import json
import re
from pathlib import Path
from typing import Optional

from rich.console import Console

from ..storage.io import load_data
from ..utils.field_path import get_field
from ..utils.text_parser import extract_code_snippets, parse_generic_tags, strip_think_tags

console = Console()

# 自动检测 label 的候选字段名
LABEL_CANDIDATES = ["label", "labels", "content_label", "target", "ground_truth", "answer"]


def eval(
    result_file: str,
    source: Optional[str] = None,
    response_col: str = "content",
    label_col: Optional[str] = None,
    extract: str = "direct",
    sep: Optional[str] = None,
    mapping: Optional[str] = None,
    output_dir: str = "record",
):
    """对模型输出 .jsonl 文件进行解析和指标计算

    两阶段解析流程：
      阶段1（自动）：去除 <think>...</think>，提取 ```...``` 代码块
      阶段2（--extract 指定）：管道式提取

    Args:
        result_file: 模型输出的 .jsonl 文件路径
        source: 原始输入文件，按行号对齐合并（当 result_file 不含 label 时使用）
        response_col: 模型响应所在字段名（支持嵌套路径，如 api_output.content）
        label_col: 标签字段名（不指定时自动检测，支持嵌套路径）
        extract: 管道式提取规则，算子间用 " | " 分隔
        sep: 配合 index 算子使用的分隔符
        mapping: 值映射，格式 "k1:v1,k2:v2"
        output_dir: 指标报告输出目录
    """
    import pandas as pd

    from ..eval import export_eval_report

    # --- 加载数据 ---
    data = load_data(result_file)
    df = pd.DataFrame(data)
    console.print(f"[cyan]加载 {result_file}，共 {len(df)} 条[/cyan]")

    # 合并 source 文件
    if source:
        source_data = load_data(source)
        source_df = pd.DataFrame(source_data)
        if len(source_df) != len(df):
            console.print(f"[red]行数不一致: result={len(df)}, source={len(source_df)}[/red]")
            return
        for col in source_df.columns:
            if col not in df.columns:
                df[col] = source_df[col].values
        console.print(f"[dim]已合并 source 文件: {source}[/dim]")

    # --- 解析 response_col（支持嵌套）---
    response_col_resolved = _resolve_nested_col(df, response_col)
    if response_col_resolved is None:
        console.print(f"[red]响应列 '{response_col}' 不存在。可用列: {list(df.columns)}[/red]")
        return

    # --- 自动检测 label_col ---
    if label_col is None:
        label_col = _auto_detect_label_col(df)
        if label_col is None:
            console.print(
                f"[red]未找到标签列，请通过 --label-col 指定。可用列: {list(df.columns)}[/red]"
            )
            return

    # 解析 label_col（支持嵌套）
    label_col_resolved = _resolve_nested_col(df, label_col)
    if label_col_resolved is None:
        console.print(f"[red]标签列 '{label_col}' 不存在。可用列: {list(df.columns)}[/red]")
        return

    console.print(
        f"[dim]response_col={response_col_resolved}, "
        f"label_col={label_col_resolved}, extract={extract}[/dim]"
    )

    # --- 阶段1+2：解析 ---
    ops = _parse_pipeline(extract)
    pred_col = "__pred__"
    df[pred_col] = df[response_col_resolved].apply(
        lambda x: _run_pipeline(_stage1_clean(x), ops, sep)
    )

    # --- mapping 阶段 ---
    if mapping:
        m = _parse_mapping(mapping)
        priority = {}
        for i, v in enumerate(m.values()):
            priority[v] = i

        def map_value(x):
            if isinstance(x, list):
                mapped = [m.get(v, v) for v in x]
                return max(mapped, key=lambda v: priority.get(v, -1))
            return m.get(x, x) if isinstance(x, str) else m.get(str(x), x)

        df[pred_col] = df[pred_col].apply(map_value)
        df[label_col_resolved] = df[label_col_resolved].apply(map_value)

    # 统一转字符串
    df[pred_col] = df[pred_col].apply(
        lambda x: str(x).strip() if not isinstance(x, str) else x.strip()
    )
    df[label_col_resolved] = df[label_col_resolved].apply(
        lambda x: str(x).strip() if not isinstance(x, str) else x.strip()
    )

    # --- 调用 export_eval_report ---
    console.print("\n[bold green]评估结果[/bold green]")
    input_name = Path(result_file).stem
    export_eval_report(
        df,
        pred_col=pred_col,
        label_col=label_col_resolved,
        record_folder=output_dir,
        input_name=input_name,
    )


# ============ 内部工具函数 ============


def _resolve_nested_col(df, col_name: str) -> Optional[str]:
    """解析嵌套字段路径，将其展开为 DataFrame 的新列

    使用 dtflow 的 get_field() 支持完整的嵌套路径语法。

    Returns:
        解析后的列名，或 None（如果字段不存在）
    """
    # 简单情况：直接列名存在
    if col_name in df.columns:
        return col_name

    # 尝试嵌套路径
    if "." not in col_name and "[" not in col_name:
        return None

    # 用 get_field 从第一个非空行试探
    sample_row = None
    for _, row in df.iterrows():
        row_dict = row.to_dict()
        val = get_field(row_dict, col_name)
        if val is not None:
            sample_row = row_dict
            break

    if sample_row is None:
        return None

    # 展开嵌套字段到新列
    resolved_name = col_name.replace(".", "__").replace("[", "_").replace("]", "")
    df[resolved_name] = df.apply(lambda row: get_field(row.to_dict(), col_name), axis=1)
    return resolved_name


def _auto_detect_label_col(df) -> Optional[str]:
    """自动检测 label 列"""
    # 优先在顶层列中查找
    for c in LABEL_CANDIDATES:
        if c in df.columns:
            return c

    # 搜索 dict 类型列的嵌套 key
    for col in df.columns:
        non_null = df[col].dropna()
        if non_null.empty:
            continue
        sample = non_null.iloc[0]
        if isinstance(sample, dict):
            for c in LABEL_CANDIDATES:
                if c in sample:
                    return f"{col}.{c}"

    return None


def _stage1_clean(text) -> str:
    """阶段1：自动清洗（去思考链 + 提取代码块）"""
    if not isinstance(text, str):
        return str(text) if text is not None else ""
    text = strip_think_tags(text)
    snippets = extract_code_snippets(text)
    if snippets:
        return snippets[-1]["code"]
    return text.strip()


def _parse_pipeline(extract_str: str) -> list:
    """解析管道表达式，按 ' | ' 分割"""
    return [op.strip() for op in extract_str.split(" | ") if op.strip()]


def _apply_op(text: str, op: str, sep: Optional[str] = None) -> str:
    """对单个字符串执行单个算子"""
    if op == "direct":
        return text
    elif op.startswith("tag:"):
        tag_name = op[4:]
        tags = parse_generic_tags(text)
        return tags.get(tag_name, text)
    elif op.startswith("json_key:"):
        key = op[9:]
        try:
            obj = json.loads(text)
        except Exception:
            return text
        if isinstance(obj, dict):
            return str(obj.get(key, text))
        return text
    elif op.startswith("index:"):
        idx = int(op[6:])
        delimiter = sep if sep else ","
        parts = text.split(delimiter)
        if 0 <= idx < len(parts):
            return parts[idx].strip()
        return text
    elif op.startswith("line:"):
        n = int(op[5:])
        text_lines = [line.strip() for line in text.splitlines() if line.strip()]
        if text_lines and -len(text_lines) <= n < len(text_lines):
            return text_lines[n]
        return text
    elif op.startswith("regex:"):
        pattern = op[6:]
        m = re.search(pattern, text)
        if m:
            return m.group(1) if m.lastindex else m.group(0)
        return text
    else:
        console.print(f"[yellow]未知算子: {op}，跳过[/yellow]")
        return text


def _run_pipeline(text: str, ops: list, sep: Optional[str] = None):
    """执行管道，处理 lines 展开"""
    if "lines" in ops:
        pos = ops.index("lines")
        # lines 之前的算子先执行
        for op in ops[:pos]:
            text = _apply_op(text, op, sep)
        # 展开为多行
        items = [line.strip() for line in text.splitlines() if line.strip()]
        # 每行独立走后续管道
        rest_ops = ops[pos + 1 :]
        results = []
        for item in items:
            for op in rest_ops:
                item = _apply_op(item, op, sep)
            results.append(item)
        if not results:
            return text
        return results if len(results) > 1 else results[0]
    else:
        for op in ops:
            text = _apply_op(text, op, sep)
        return text


def _parse_mapping(mapping_str: str) -> dict:
    """解析 'k1:v1,k2:v2' 格式的映射"""
    m = {}
    for pair in mapping_str.split(","):
        pair = pair.strip()
        if ":" in pair:
            k, v = pair.split(":", 1)
            m[k.strip()] = v.strip()
    return m
