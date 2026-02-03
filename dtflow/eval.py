"""
评估指标计算模块

提供分类任务的指标计算和评估报告导出：
- MetricsCalculator: 计算 accuracy/precision/recall/F1/混淆矩阵
- export_eval_report: 生成 metrics.md + result.jsonl + bad_case.jsonl

依赖: scikit-learn, pandas
安装: pip install dtflow[eval]
"""

import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pandas import DataFrame


def _check_eval_deps():
    """检查 eval 依赖是否已安装"""
    try:
        import pandas  # noqa: F401
        import sklearn  # noqa: F401
    except ImportError as e:
        missing = str(e).split("'")[1] if "'" in str(e) else str(e)
        raise ImportError(
            f"eval 功能需要额外依赖: {missing}\n" f"请运行: pip install dtflow[eval]"
        ) from e


class MetricsCalculator:
    """分类指标计算器

    基于 sklearn 计算 accuracy/precision/recall/F1/混淆矩阵/分类报告。

    Args:
        df: 包含预测列和标签列的 DataFrame
        pred_col: 预测值列名
        label_col: 标签值列名
        include_macro_micro_avg: 是否在报告中包含 macro/micro 平均
        remove_matrix_zero_row: 是否移除混淆矩阵中 support=0 的行
    """

    def __init__(
        self,
        df: "DataFrame",
        pred_col: str = "predict",
        label_col: str = "label",
        include_macro_micro_avg: bool = False,
        remove_matrix_zero_row: bool = False,
    ):
        _check_eval_deps()
        self.df = df
        self.y_pred = df[pred_col]
        self.y_true = df[label_col]
        self.all_labels = sorted(set(self.y_true.unique()).union(set(self.y_pred.unique())))
        self.needed_labels = None
        self.remove_matrix_zero_row = remove_matrix_zero_row
        self.include_macro_micro_avg = include_macro_micro_avg
        self.metrics = self._calculate_metrics()

    def _calculate_metrics(self):
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            confusion_matrix,
            precision_score,
            recall_score,
        )

        accuracy = accuracy_score(self.y_true, self.y_pred)
        precision = precision_score(
            self.y_true, self.y_pred, labels=self.all_labels, average="weighted", zero_division=0
        )
        recall = recall_score(
            self.y_true, self.y_pred, labels=self.all_labels, average="weighted", zero_division=0
        )
        conf_matrix = confusion_matrix(self.y_true, self.y_pred, labels=self.all_labels)
        report = classification_report(
            self.y_true, self.y_pred, labels=self.all_labels, output_dict=True, zero_division=0
        )

        # 默认只保留加权平均
        if not self.include_macro_micro_avg:
            report = {
                label: metrics
                for label, metrics in report.items()
                if label in self.all_labels or label == "weighted avg"
            }

        # 去除 support=0 的类别
        report = {label: metrics for label, metrics in report.items() if metrics["support"] > 0}

        self.needed_labels = [label for label in report.keys() if label in self.all_labels]

        # 可选移除混淆矩阵中不需要的行
        needed_idx_list = [self.all_labels.index(label) for label in self.needed_labels]
        if self.remove_matrix_zero_row:
            conf_matrix = conf_matrix[needed_idx_list]

        return {
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "confusion_matrix": conf_matrix,
            "classification_report": report,
        }

    def get_metrics(self):
        return self.metrics

    def format_classification_report_as_markdown(self):
        """将分类报告格式化为 Markdown 表格"""
        report = self.metrics["classification_report"]
        header = "| Label | Precision | Recall | F1-score | Support |\n"
        separator = "|-------|-----------|--------|----------|---------|\n"
        rows = []
        for label, metrics in report.items():
            if isinstance(metrics, dict):
                rows.append(
                    f"| {label} | {metrics['precision']:.2f} | {metrics['recall']:.2f} "
                    f"| {metrics['f1-score']:.2f} | {metrics['support']:.0f} |"
                )
        return header + separator + "\n".join(rows)

    def _clean_label_for_markdown(self, label, max_length=20):
        """清理标签文本，使其适合 Markdown 表格显示"""
        label = str(label).replace("\n", " ")
        label = label.replace("|", "\\|")
        label = label.replace("-", "\\-")
        label = label.replace("<", "&lt;")
        label = label.replace(">", "&gt;")
        if len(label) > max_length:
            label = label[:max_length] + "..."
        label = label.strip()
        if not label:
            label = "(empty)"
        return label

    def format_confusion_matrix_as_markdown(self, max_label_length=20):
        """将混淆矩阵格式化为 Markdown 表格"""
        matrix = self.metrics["confusion_matrix"]

        if self.remove_matrix_zero_row:
            labels = self.needed_labels
        else:
            labels = self.all_labels

        processed_labels = [self._clean_label_for_markdown(lb, max_label_length) for lb in labels]

        header = "| 真实值/预测值 | " + " | ".join(processed_labels) + " |\n"
        separator_parts = [":---:"] * (len(processed_labels) + 1)
        separator = "| " + " | ".join(separator_parts) + " |\n"

        rows = []
        for i, row in enumerate(matrix):
            row_label = self._clean_label_for_markdown(labels[i], max_label_length)
            formatted_row = [f"{num:,}" for num in row]
            rows.append(f"| {row_label} | " + " | ".join(formatted_row) + " |")

        return header + separator + "\n".join(rows)


def export_eval_report(
    df: "DataFrame",
    pred_col: str,
    label_col: str,
    record_folder: str = "record",
    input_name: Optional[str] = None,
):
    """生成评估报告并保存到指定目录

    输出文件：
    - metrics.md: 指标概览 + 分类报告 + 混淆矩阵
    - result.jsonl: 完整预测结果
    - bad_case.jsonl: 预测错误样本

    Args:
        df: 包含预测和标签的 DataFrame
        pred_col: 预测值列名
        label_col: 标签值列名
        record_folder: 输出根目录
        input_name: 输入文件名（用于子目录命名）
    """
    from rich.console import Console
    from rich.markdown import Markdown

    calculator = MetricsCalculator(df, pred_col=pred_col, label_col=label_col)
    metrics = calculator.get_metrics()

    # 用 Rich Table 构建指标概览（替代 tabulate）
    from rich.table import Table

    overview_table = Table(title="指标概览", show_header=True)
    overview_table.add_column("Accuracy", justify="center")
    overview_table.add_column("Precision", justify="center")
    overview_table.add_column("Recall", justify="center")
    overview_table.add_row(
        f"{metrics['accuracy']:.4f}",
        f"{metrics['precision']:.4f}",
        f"{metrics['recall']:.4f}",
    )

    # 构建 Markdown 报告内容
    md = (
        f"\n\n### 指标概览\n\n"
        f"| Accuracy | Precision | Recall |\n"
        f"|----------|-----------|--------|\n"
        f"| {metrics['accuracy']:.4f} | {metrics['precision']:.4f} | {metrics['recall']:.4f} |"
    )
    metrics_md = calculator.format_classification_report_as_markdown()
    confusion_md = calculator.format_confusion_matrix_as_markdown()
    md += f"\n\n### Classification Report\n{metrics_md}\n" f"\n### Confusion Matrix\n{confusion_md}"

    # 创建输出目录（带序号和时间戳）
    now = datetime.now().strftime("%Y%m%d-%H-%M-%S")
    record_path = Path(record_folder)
    if input_name:
        record_path = record_path / input_name

    if record_path.exists():
        existing = [d.name for d in record_path.iterdir() if d.is_dir()]
        max_idx = 0
        for name in existing:
            parts = name.split("-", 1)
            if parts[0].isdigit():
                max_idx = max(max_idx, int(parts[0]))
        idx = max_idx + 1
    else:
        idx = 1

    record_path = record_path / f"{idx}-{now}"
    record_path.mkdir(parents=True, exist_ok=True)

    # 终端输出
    console = Console()
    console.print(overview_table)
    console.print(Markdown(md))

    # 保存文件
    with open(os.path.join(record_path, "metrics.md"), "w", encoding="utf-8") as f:
        f.write(md)

    bad_case_df = df[df[pred_col] != df[label_col]]

    # 保存 JSONL
    df.to_json(
        os.path.join(record_path, "result.jsonl"),
        orient="records",
        lines=True,
        force_ascii=False,
    )
    bad_case_df.to_json(
        os.path.join(record_path, "bad_case.jsonl"),
        orient="records",
        lines=True,
        force_ascii=False,
    )

    # 尝试保存 CSV
    try:
        df.to_csv(os.path.join(record_path, "result.csv"), index=False)
        bad_case_df.to_csv(os.path.join(record_path, "bad_case.csv"), index=False)
    except Exception:
        pass

    console.print(f"\n[green]报告已保存到: {record_path}[/green]")
    console.print(f"[dim]  - metrics.md ({len(df)} 条数据, {len(bad_case_df)} 条错误)[/dim]")

    return record_path
