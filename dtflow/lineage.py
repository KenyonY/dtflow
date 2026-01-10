"""
数据血缘模块

记录数据处理的完整历史，支持数据溯源和版本对比。
"""

import hashlib
import os
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import orjson

# 血缘元数据版本
LINEAGE_VERSION = "1.0"

# 元数据文件后缀
LINEAGE_SUFFIX = ".lineage.json"


def _get_file_hash(filepath: str, sample_size: int = 10000) -> str:
    """
    计算文件内容哈希（采样方式，避免大文件性能问题）。

    Args:
        filepath: 文件路径
        sample_size: 采样字节数

    Returns:
        文件哈希值（前16位）
    """
    hasher = hashlib.sha256()
    file_size = os.path.getsize(filepath)

    with open(filepath, "rb") as f:
        # 读取文件头
        hasher.update(f.read(sample_size))

        # 如果文件较大，还要读取中间和尾部
        if file_size > sample_size * 3:
            f.seek(file_size // 2)
            hasher.update(f.read(sample_size))
            f.seek(-sample_size, 2)
            hasher.update(f.read(sample_size))

    return hasher.hexdigest()[:16]


def _get_lineage_path(data_path: str) -> str:
    """获取血缘元数据文件路径"""
    return str(data_path) + LINEAGE_SUFFIX


def _get_environment_info() -> Dict[str, str]:
    """获取运行环境信息"""
    return {
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "hostname": platform.node(),
        "user": os.environ.get("USER", os.environ.get("USERNAME", "unknown")),
    }


class LineageRecord:
    """血缘记录"""

    def __init__(
        self,
        source: Optional[str] = None,
        operations: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.version = LINEAGE_VERSION
        self.created_at = datetime.now().isoformat()
        self.source = source
        self.operations = operations or []
        self.metadata = metadata or {}
        self.environment = _get_environment_info()

    def add_operation(
        self,
        op_type: str,
        params: Optional[Dict[str, Any]] = None,
        input_count: Optional[int] = None,
        output_count: Optional[int] = None,
    ) -> "LineageRecord":
        """添加操作记录"""
        op = {
            "type": op_type,
            "timestamp": datetime.now().isoformat(),
        }
        if params:
            op["params"] = params
        if input_count is not None:
            op["input_count"] = input_count
        if output_count is not None:
            op["output_count"] = output_count

        self.operations.append(op)
        return self

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "version": self.version,
            "created_at": self.created_at,
            "source": self.source,
            "operations": self.operations,
            "metadata": self.metadata,
            "environment": self.environment,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LineageRecord":
        """从字典创建"""
        record = cls(
            source=data.get("source"),
            operations=data.get("operations", []),
            metadata=data.get("metadata", {}),
        )
        record.version = data.get("version", LINEAGE_VERSION)
        record.created_at = data.get("created_at", datetime.now().isoformat())
        record.environment = data.get("environment", {})
        return record


class LineageTracker:
    """
    血缘追踪器

    用于记录数据处理的完整历史。
    """

    def __init__(self, source_path: Optional[str] = None):
        """
        初始化追踪器。

        Args:
            source_path: 源数据文件路径
        """
        self.source_path = source_path
        self.source_lineage = None
        self.operations: List[Dict[str, Any]] = []

        # 如果源文件有血缘记录，加载它
        if source_path:
            self.source_lineage = load_lineage(source_path)

    def record(
        self,
        op_type: str,
        params: Optional[Dict[str, Any]] = None,
        input_count: Optional[int] = None,
        output_count: Optional[int] = None,
    ) -> "LineageTracker":
        """
        记录一次操作。

        Args:
            op_type: 操作类型 (filter, transform, dedupe, sample, etc.)
            params: 操作参数
            input_count: 输入数据量
            output_count: 输出数据量

        Returns:
            self，支持链式调用
        """
        op = {
            "type": op_type,
            "timestamp": datetime.now().isoformat(),
        }
        if params:
            # 清理参数，移除不可序列化的内容
            op["params"] = _sanitize_params(params)
        if input_count is not None:
            op["input_count"] = input_count
        if output_count is not None:
            op["output_count"] = output_count

        self.operations.append(op)
        return self

    def build_record(self, output_path: str, output_count: int) -> LineageRecord:
        """
        构建最终的血缘记录。

        Args:
            output_path: 输出文件路径
            output_count: 输出数据量

        Returns:
            LineageRecord 对象
        """
        # 构建来源信息
        source_info = None
        if self.source_path:
            source_info = {
                "path": str(self.source_path),
                "hash": (
                    _get_file_hash(self.source_path) if os.path.exists(self.source_path) else None
                ),
            }
            # 如果源文件有血缘，记录血缘链
            if self.source_lineage:
                source_info["lineage_ref"] = _get_lineage_path(self.source_path)

        record = LineageRecord(
            source=source_info,
            operations=self.operations,
            metadata={
                "output_path": str(output_path),
                "output_count": output_count,
            },
        )

        return record

    def save(self, output_path: str, output_count: int) -> str:
        """
        保存血缘记录到文件。

        Args:
            output_path: 输出数据文件路径
            output_count: 输出数据量

        Returns:
            血缘文件路径
        """
        record = self.build_record(output_path, output_count)
        lineage_path = _get_lineage_path(output_path)

        with open(lineage_path, "wb") as f:
            f.write(orjson.dumps(record.to_dict(), option=orjson.OPT_INDENT_2))

        return lineage_path

    def copy(self) -> "LineageTracker":
        """
        创建追踪器的深拷贝。

        用于 split() 等场景，确保子数据集有独立的血缘追踪。

        Returns:
            新的 LineageTracker 实例
        """
        import copy as copy_module

        new_tracker = LineageTracker.__new__(LineageTracker)
        new_tracker.source_path = self.source_path
        new_tracker.source_lineage = self.source_lineage  # LineageRecord 是不可变的，可共享
        new_tracker.operations = copy_module.deepcopy(self.operations)
        return new_tracker


def _sanitize_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    清理参数，移除不可序列化的内容。
    """
    result = {}
    for key, value in params.items():
        if callable(value):
            # 函数：只记录名称
            result[key] = f"<function:{getattr(value, '__name__', 'anonymous')}>"
        elif isinstance(value, (str, int, float, bool, type(None))):
            result[key] = value
        elif isinstance(value, (list, tuple)):
            result[key] = [_sanitize_value(v) for v in value]
        elif isinstance(value, dict):
            result[key] = _sanitize_params(value)
        else:
            result[key] = str(value)
    return result


def _sanitize_value(value: Any) -> Any:
    """清理单个值"""
    if callable(value):
        return f"<function:{getattr(value, '__name__', 'anonymous')}>"
    elif isinstance(value, (str, int, float, bool, type(None))):
        return value
    elif isinstance(value, dict):
        return _sanitize_params(value)
    else:
        return str(value)


# ============ 公共 API ============


def load_lineage(data_path: str) -> Optional[LineageRecord]:
    """
    加载数据文件的血缘记录。

    Args:
        data_path: 数据文件路径

    Returns:
        LineageRecord 或 None（如果没有血缘记录）
    """
    lineage_path = _get_lineage_path(data_path)
    if not os.path.exists(lineage_path):
        return None

    try:
        with open(lineage_path, "rb") as f:
            data = orjson.loads(f.read())
        return LineageRecord.from_dict(data)
    except (orjson.JSONDecodeError, IOError):
        return None


def get_lineage_chain(data_path: str, max_depth: int = 10) -> List[LineageRecord]:
    """
    获取完整的血缘链。

    Args:
        data_path: 数据文件路径
        max_depth: 最大追溯深度

    Returns:
        血缘记录列表，从最新到最旧
    """
    chain = []
    current_path = data_path
    visited = set()

    for _ in range(max_depth):
        if current_path in visited:
            break  # 避免循环引用
        visited.add(current_path)

        record = load_lineage(current_path)
        if not record:
            break

        chain.append(record)

        # 追溯到源文件
        if record.source and isinstance(record.source, dict):
            source_path = record.source.get("path")
            if source_path and os.path.exists(source_path):
                current_path = source_path
            else:
                break
        else:
            break

    return chain


def format_lineage_report(data_path: str) -> str:
    """
    格式化血缘报告。

    Args:
        data_path: 数据文件路径

    Returns:
        格式化的报告字符串
    """
    chain = get_lineage_chain(data_path)

    if not chain:
        return f"文件 {data_path} 没有血缘记录"

    lines = []
    lines.append(f"📊 数据血缘报告: {data_path}")
    lines.append("=" * 60)

    for i, record in enumerate(chain):
        prefix = "└─" if i == len(chain) - 1 else "├─"
        indent = "  " * i

        # 基本信息
        lines.append(f"{indent}{prefix} 版本 {i + 1}")
        lines.append(f"{indent}   创建时间: {record.created_at}")

        # 来源信息
        if record.source:
            if isinstance(record.source, dict):
                lines.append(f"{indent}   来源: {record.source.get('path', 'unknown')}")
                if record.source.get("hash"):
                    lines.append(f"{indent}   哈希: {record.source['hash']}")
            else:
                lines.append(f"{indent}   来源: {record.source}")

        # 操作列表
        if record.operations:
            lines.append(f"{indent}   操作链:")
            for j, op in enumerate(record.operations):
                op_prefix = "└─" if j == len(record.operations) - 1 else "├─"
                op_type = op.get("type", "unknown")
                input_count = op.get("input_count", "?")
                output_count = op.get("output_count", "?")
                lines.append(f"{indent}     {op_prefix} {op_type}: {input_count} → {output_count}")

                # 显示参数
                if op.get("params"):
                    for key, value in op["params"].items():
                        lines.append(f"{indent}        {key}: {value}")

        # 元数据
        if record.metadata:
            output_count = record.metadata.get("output_count")
            if output_count:
                lines.append(f"{indent}   输出数量: {output_count}")

        lines.append("")

    return "\n".join(lines)


def has_lineage(data_path: str) -> bool:
    """检查文件是否有血缘记录"""
    return os.path.exists(_get_lineage_path(data_path))


def delete_lineage(data_path: str) -> bool:
    """删除血缘记录"""
    lineage_path = _get_lineage_path(data_path)
    if os.path.exists(lineage_path):
        os.remove(lineage_path)
        return True
    return False
