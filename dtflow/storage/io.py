"""
Input/Output utilities for saving and loading data.

使用 Polars 作为主要 I/O 引擎，性能比 Pandas 快 3-5 倍。
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import polars as pl


def save_data(
    data: List[Dict[str, Any]], filepath: str, file_format: Optional[str] = None
) -> None:
    """
    Save data to file.

    Args:
        data: List of data items to save
        filepath: Path to save file
        file_format: File format (auto-detected from extension if None)
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    if file_format is None:
        file_format = _detect_format(filepath)

    if file_format == "jsonl":
        _save_jsonl(data, filepath)
    elif file_format == "json":
        _save_json(data, filepath)
    elif file_format == "csv":
        _save_csv(data, filepath)
    elif file_format == "parquet":
        _save_parquet(data, filepath)
    elif file_format == "arrow":
        _save_arrow(data, filepath)
    elif file_format == "excel":
        _save_excel(data, filepath)
    elif file_format == "flaxkv":
        _save_flaxkv(data, filepath)
    else:
        raise ValueError(f"Unknown file format: {file_format}")


def load_data(filepath: str, file_format: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Load data from file.

    Args:
        filepath: Path to load file
        file_format: File format (auto-detected from extension if None)

    Returns:
        List of data items
    """
    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    if file_format is None:
        file_format = _detect_format(filepath)

    if file_format == "jsonl":
        return _load_jsonl(filepath)
    elif file_format == "json":
        return _load_json(filepath)
    elif file_format == "csv":
        return _load_csv(filepath)
    elif file_format == "parquet":
        return _load_parquet(filepath)
    elif file_format == "arrow":
        return _load_arrow(filepath)
    elif file_format == "excel":
        return _load_excel(filepath)
    elif file_format == "flaxkv":
        return _load_flaxkv(filepath)
    else:
        raise ValueError(f"Unknown file format: {file_format}")


def _detect_format(filepath: Path) -> str:
    """Detect file format from extension."""
    ext = filepath.suffix.lower()
    if ext == ".jsonl":
        return "jsonl"
    elif ext == ".json":
        return "json"
    elif ext == ".csv":
        return "csv"
    elif ext == ".parquet":
        return "parquet"
    elif ext in (".arrow", ".feather"):
        return "arrow"
    elif ext in (".xlsx", ".xls"):
        return "excel"
    elif ext == ".flaxkv" or ext == "":
        return "flaxkv"
    else:
        return "jsonl"


# ============ JSONL Format ============
# JSONL 保持用原生 Python，因为需要处理复杂嵌套结构


def _save_jsonl(data: List[Dict[str, Any]], filepath: Path) -> None:
    """Save data in JSONL format."""
    with open(filepath, "w", encoding="utf-8") as f:
        for item in data:
            json_line = json.dumps(item, ensure_ascii=False)
            f.write(json_line + "\n")


def _load_jsonl(filepath: Path) -> List[Dict[str, Any]]:
    """Load data from JSONL format."""
    data = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    return data


# ============ JSON Format ============


def _save_json(data: List[Dict[str, Any]], filepath: Path) -> None:
    """Save data in JSON format."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_json(filepath: Path) -> List[Dict[str, Any]]:
    """Load data from JSON format."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        data = [data]

    return data


# ============ CSV Format (Polars) ============


def _save_csv(data: List[Dict[str, Any]], filepath: Path) -> None:
    """Save data in CSV format using Polars."""
    if not data:
        # 空数据，创建空文件
        filepath.touch()
        return

    # 序列化复杂字段为 JSON 字符串
    serialized = _serialize_complex_fields(data)
    df = pl.DataFrame(serialized)
    df.write_csv(filepath)


def _load_csv(filepath: Path) -> List[Dict[str, Any]]:
    """Load data from CSV format using Polars."""
    df = pl.read_csv(filepath)
    data = df.to_dicts()
    # 反序列化 JSON 字符串
    return _deserialize_complex_fields(data)


# ============ Parquet Format (Polars) ============


def _save_parquet(data: List[Dict[str, Any]], filepath: Path) -> None:
    """Save data in Parquet format using Polars."""
    if not data:
        # 空数据，创建空 parquet
        pl.DataFrame().write_parquet(filepath)
        return

    serialized = _serialize_complex_fields(data)
    df = pl.DataFrame(serialized)
    df.write_parquet(filepath)


def _load_parquet(filepath: Path) -> List[Dict[str, Any]]:
    """Load data from Parquet format using Polars."""
    df = pl.read_parquet(filepath)
    data = df.to_dicts()
    return _deserialize_complex_fields(data)


# ============ Arrow Format (Polars) ============


def _save_arrow(data: List[Dict[str, Any]], filepath: Path) -> None:
    """Save data in Arrow IPC format using Polars."""
    if not data:
        pl.DataFrame().write_ipc(filepath)
        return

    serialized = _serialize_complex_fields(data)
    df = pl.DataFrame(serialized)
    df.write_ipc(filepath)


def _load_arrow(filepath: Path) -> List[Dict[str, Any]]:
    """Load data from Arrow IPC format using Polars."""
    df = pl.read_ipc(filepath)
    data = df.to_dicts()
    return _deserialize_complex_fields(data)


# ============ Excel Format ============
# Excel 需要额外依赖，保持可选


def _save_excel(data: List[Dict[str, Any]], filepath: Path) -> None:
    """Save data in Excel format."""
    if not data:
        # 空数据
        try:
            import xlsxwriter
            workbook = xlsxwriter.Workbook(str(filepath))
            workbook.close()
        except ImportError:
            raise ImportError(
                "xlsxwriter is required for Excel write. Install with: pip install xlsxwriter"
            )
        return

    serialized = _serialize_complex_fields(data)
    df = pl.DataFrame(serialized)
    df.write_excel(filepath)


def _load_excel(filepath: Path) -> List[Dict[str, Any]]:
    """Load data from Excel format."""
    df = pl.read_excel(filepath)
    data = df.to_dicts()
    return _deserialize_complex_fields(data)


# ============ 复杂字段序列化 ============


def _serialize_complex_fields(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将复杂字段（list, dict）序列化为 JSON 字符串"""
    result = []
    for item in data:
        new_item = {}
        for k, v in item.items():
            if isinstance(v, (list, dict)):
                new_item[k] = json.dumps(v, ensure_ascii=False)
            else:
                new_item[k] = v
        result.append(new_item)
    return result


def _deserialize_complex_fields(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将 JSON 字符串反序列化为复杂字段"""
    result = []
    for item in data:
        new_item = {}
        for k, v in item.items():
            if isinstance(v, str) and v.startswith(("[", "{")):
                try:
                    new_item[k] = json.loads(v)
                except json.JSONDecodeError:
                    new_item[k] = v
            else:
                new_item[k] = v
        result.append(new_item)
    return result


# ============ Streaming Utilities ============


def sample_data(
    data: List[Dict[str, Any]],
    num: int = 10,
    sample_type: str = "head",
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Sample data from a list.

    Args:
        data: List of data items
        num: Number of items to sample
        sample_type: Sampling method - "random", "head", or "tail"
        seed: Random seed for reproducibility

    Returns:
        Sampled data list
    """
    import random as rand_module

    if not data:
        return []

    total = len(data)

    if num == 0:
        actual_num = total
    elif num < 0:
        actual_num = min(abs(num), total)
    else:
        actual_num = min(num, total)

    if sample_type == "head":
        return data[:actual_num]
    elif sample_type == "tail":
        return data[-actual_num:]
    else:  # random
        if seed is not None:
            rand_module.seed(seed)
        return rand_module.sample(data, actual_num)


def sample_file(
    filepath: str,
    num: int = 10,
    sample_type: str = "head",
    seed: Optional[int] = None,
    output: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Sample data from a file with streaming support.

    Args:
        filepath: Input file path
        num: Number of items to sample
        sample_type: Sampling method
        seed: Random seed
        output: Output file path

    Returns:
        Sampled data list
    """
    filepath = Path(filepath)
    file_format = _detect_format(filepath)

    sampled = _stream_sample(filepath, file_format, num, sample_type, seed)

    if output:
        save_data(sampled, output)

    return sampled


def _stream_sample(
    filepath: Path,
    file_format: str,
    num: int,
    sample_type: str,
    seed: Optional[int],
) -> List[Dict[str, Any]]:
    """流式采样实现"""
    if num <= 0:
        data = load_data(str(filepath))
        return sample_data(data, num=num, sample_type=sample_type, seed=seed)

    # head 采样优化
    if sample_type == "head":
        if file_format == "jsonl":
            return _stream_head_jsonl(filepath, num)
        elif file_format == "csv":
            return _stream_head_csv(filepath, num)
        elif file_format == "parquet":
            return _stream_head_parquet(filepath, num)
        elif file_format == "arrow":
            return _stream_head_arrow(filepath, num)
        elif file_format == "excel":
            return _stream_head_excel(filepath, num)

    # tail 采样优化（仅 JSONL）
    if sample_type == "tail" and file_format == "jsonl":
        return _stream_tail_jsonl(filepath, num)

    # random 采样优化（仅 JSONL）
    if sample_type == "random" and file_format == "jsonl":
        return _stream_random_jsonl(filepath, num, seed)

    # 其他情况回退到全量加载
    data = load_data(str(filepath))
    return sample_data(data, num=num, sample_type=sample_type, seed=seed)


def _stream_head_jsonl(filepath: Path, num: int) -> List[Dict[str, Any]]:
    """JSONL 流式读取前 N 行"""
    result = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                result.append(json.loads(line))
                if len(result) >= num:
                    break
    return result


def _stream_head_csv(filepath: Path, num: int) -> List[Dict[str, Any]]:
    """CSV 流式读取前 N 行（使用 Polars LazyFrame）"""
    df = pl.scan_csv(filepath).head(num).collect()
    return _deserialize_complex_fields(df.to_dicts())


def _stream_head_parquet(filepath: Path, num: int) -> List[Dict[str, Any]]:
    """Parquet 流式读取前 N 行（使用 Polars LazyFrame）"""
    df = pl.scan_parquet(filepath).head(num).collect()
    return _deserialize_complex_fields(df.to_dicts())


def _stream_head_arrow(filepath: Path, num: int) -> List[Dict[str, Any]]:
    """Arrow 流式读取前 N 行（使用 Polars LazyFrame）"""
    df = pl.scan_ipc(filepath).head(num).collect()
    return _deserialize_complex_fields(df.to_dicts())


def _stream_head_excel(filepath: Path, num: int) -> List[Dict[str, Any]]:
    """Excel 读取前 N 行"""
    # Excel 不支持 lazy scan，使用普通读取
    df = pl.read_excel(filepath).head(num)
    return _deserialize_complex_fields(df.to_dicts())


def _stream_tail_jsonl(filepath: Path, num: int) -> List[Dict[str, Any]]:
    """JSONL 反向读取后 N 行"""
    from collections import deque

    buffer = deque(maxlen=num)

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                buffer.append(json.loads(line))

    return list(buffer)


def _stream_random_jsonl(
    filepath: Path, num: int, seed: Optional[int] = None
) -> List[Dict[str, Any]]:
    """JSONL 蓄水池采样"""
    import random

    if seed is not None:
        random.seed(seed)

    reservoir = []

    with open(filepath, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue

            item = json.loads(line)

            if len(reservoir) < num:
                reservoir.append(item)
            else:
                j = random.randint(0, i)
                if j < num:
                    reservoir[j] = item

    return reservoir


# ============ Additional Utilities ============


def append_to_file(
    data: List[Dict[str, Any]], filepath: str, file_format: str = "jsonl"
) -> None:
    """Append data to an existing file (only JSONL supported)."""
    filepath = Path(filepath)

    if file_format != "jsonl":
        raise ValueError("Only JSONL format supports appending")

    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "a", encoding="utf-8") as f:
        for item in data:
            json_line = json.dumps(item, ensure_ascii=False)
            f.write(json_line + "\n")


def count_lines(filepath: str) -> int:
    """Count number of lines in a JSONL file."""
    count = 0
    with open(filepath, "r", encoding="utf-8") as f:
        for _ in f:
            count += 1
    return count


def stream_jsonl(filepath: str, chunk_size: int = 1000):
    """Stream JSONL file in chunks."""
    chunk = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunk.append(json.loads(line))
                if len(chunk) >= chunk_size:
                    yield chunk
                    chunk = []

        if chunk:
            yield chunk


# ============ FlaxKV Format ============


def _save_flaxkv(data: List[Dict[str, Any]], filepath: Path) -> None:
    """Save data in FlaxKV format."""
    from flaxkv2 import FlaxKV

    db_name = filepath.stem if filepath.stem else "data"
    db_path = filepath.parent

    with FlaxKV(db_name, str(db_path)) as db:
        db["_metadata"] = {"total": len(data), "format": "flaxkv"}

        for i, item in enumerate(data):
            db[f"item:{i}"] = item


def _load_flaxkv(filepath: Path) -> List[Dict[str, Any]]:
    """Load data from FlaxKV format."""
    from flaxkv2 import FlaxKV

    db_name = filepath.stem if filepath.stem else "data"
    db_path = filepath.parent

    with FlaxKV(db_name, str(db_path)) as db:
        items = []
        for key in sorted(db.keys()):
            if key.startswith("item:"):
                items.append(db[key])

        return items
