"""
Input/Output utilities for saving and loading data.
"""
from typing import List, Dict, Any, Optional
import json
import os
from pathlib import Path


def save_data(data: List[Dict[str, Any]],
              filepath: str,
              file_format: Optional[str] = None) -> None:
    """
    Save data to file.

    Args:
        data: List of data items to save
        filepath: Path to save file
        file_format: File format (auto-detected from extension if None)
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Auto-detect format from extension
    if file_format is None:
        file_format = _detect_format(filepath)

    if file_format == 'jsonl':
        _save_jsonl(data, filepath)
    elif file_format == 'json':
        _save_json(data, filepath)
    elif file_format == 'csv':
        _save_csv(data, filepath)
    elif file_format == 'parquet':
        _save_parquet(data, filepath)
    elif file_format == 'arrow':
        _save_arrow(data, filepath)
    elif file_format == 'excel':
        _save_excel(data, filepath)
    elif file_format == 'flaxkv':
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

    # Auto-detect format from extension
    if file_format is None:
        file_format = _detect_format(filepath)

    if file_format == 'jsonl':
        return _load_jsonl(filepath)
    elif file_format == 'json':
        return _load_json(filepath)
    elif file_format == 'csv':
        return _load_csv(filepath)
    elif file_format == 'parquet':
        return _load_parquet(filepath)
    elif file_format == 'arrow':
        return _load_arrow(filepath)
    elif file_format == 'excel':
        return _load_excel(filepath)
    elif file_format == 'flaxkv':
        return _load_flaxkv(filepath)
    else:
        raise ValueError(f"Unknown file format: {file_format}")


def _detect_format(filepath: Path) -> str:
    """Detect file format from extension."""
    ext = filepath.suffix.lower()
    if ext == '.jsonl':
        return 'jsonl'
    elif ext == '.json':
        return 'json'
    elif ext == '.csv':
        return 'csv'
    elif ext == '.parquet':
        return 'parquet'
    elif ext in ('.arrow', '.feather'):
        return 'arrow'
    elif ext in ('.xlsx', '.xls'):
        return 'excel'
    elif ext == '.flaxkv' or ext == '':
        # For FlaxKV, filepath is typically a directory
        return 'flaxkv'
    else:
        # Default to JSONL
        return 'jsonl'


# ============ JSONL Format ============

def _save_jsonl(data: List[Dict[str, Any]], filepath: Path) -> None:
    """Save data in JSONL format."""
    with open(filepath, 'w', encoding='utf-8') as f:
        for item in data:
            json_line = json.dumps(item, ensure_ascii=False)
            f.write(json_line + '\n')


def _load_jsonl(filepath: Path) -> List[Dict[str, Any]]:
    """Load data from JSONL format."""
    data = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    return data


# ============ JSON Format ============

def _save_json(data: List[Dict[str, Any]], filepath: Path) -> None:
    """Save data in JSON format."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_json(filepath: Path) -> List[Dict[str, Any]]:
    """Load data from JSON format."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Ensure data is a list
    if not isinstance(data, list):
        data = [data]

    return data


# ============ CSV Format ============

def _save_csv(data: List[Dict[str, Any]], filepath: Path) -> None:
    """Save data in CSV format."""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for CSV support. Install with: pip install pandas")

    df = pd.DataFrame(data)
    df.to_csv(filepath, index=False, encoding='utf-8')


def _load_csv(filepath: Path) -> List[Dict[str, Any]]:
    """Load data from CSV format."""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for CSV support. Install with: pip install pandas")

    df = pd.read_csv(filepath, encoding='utf-8')
    return df.to_dict('records')


# ============ Excel Format ============

def _save_excel(data: List[Dict[str, Any]], filepath: Path) -> None:
    """Save data in Excel format."""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas and openpyxl are required for Excel support. Install with: pip install pandas openpyxl")

    df = pd.DataFrame(data)
    df.to_excel(filepath, index=False)


def _load_excel(filepath: Path) -> List[Dict[str, Any]]:
    """Load data from Excel format."""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas and openpyxl are required for Excel support. Install with: pip install pandas openpyxl")

    df = pd.read_excel(filepath)
    return df.to_dict('records')


# ============ Parquet Format ============

def _save_parquet(data: List[Dict[str, Any]], filepath: Path) -> None:
    """Save data in Parquet format."""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for Parquet support. Install with: pip install pandas pyarrow")

    df = pd.DataFrame(data)
    df.to_parquet(filepath, index=False, engine='pyarrow')


def _load_parquet(filepath: Path) -> List[Dict[str, Any]]:
    """Load data from Parquet format."""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for Parquet support. Install with: pip install pandas pyarrow")

    df = pd.read_parquet(filepath, engine='pyarrow')
    return df.to_dict('records')


# ============ Arrow Format ============

def _save_arrow(data: List[Dict[str, Any]], filepath: Path) -> None:
    """Save data in Arrow IPC format (also known as Feather v2).

    Note: Complex nested structures (like list of dicts) are serialized as JSON strings.
    """
    try:
        import pyarrow as pa
        import pyarrow.feather as feather
    except ImportError:
        raise ImportError("pyarrow is required for Arrow support. Install with: pip install pyarrow")

    # Serialize complex fields to JSON strings for Arrow compatibility
    serialized_data = []
    for item in data:
        new_item = {}
        for k, v in item.items():
            if isinstance(v, (list, dict)):
                new_item[k] = json.dumps(v, ensure_ascii=False)
            else:
                new_item[k] = v
        serialized_data.append(new_item)

    table = pa.Table.from_pylist(serialized_data)

    # Use Feather format (simpler and more portable)
    feather.write_feather(table, filepath)


def _load_arrow(filepath: Path) -> List[Dict[str, Any]]:
    """Load data from Arrow IPC format (also known as Feather v2).

    Note: JSON-serialized fields are automatically deserialized.
    """
    try:
        import pyarrow.feather as feather
    except ImportError:
        raise ImportError("pyarrow is required for Arrow support. Install with: pip install pyarrow")

    table = feather.read_table(filepath)
    data = table.to_pylist()

    # Deserialize JSON strings back to complex objects
    result = []
    for item in data:
        new_item = {}
        for k, v in item.items():
            if isinstance(v, str) and v.startswith(('[', '{')):
                try:
                    new_item[k] = json.loads(v)
                except json.JSONDecodeError:
                    new_item[k] = v
            else:
                new_item[k] = v
        result.append(new_item)

    return result


# ============ Additional Utilities ============

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
        num: Number of items to sample.
            - num > 0: sample specified number of items
            - num = 0: sample all data
            - num < 0: Python slice style (e.g., -1 means last 1, -10 means last 10)
        sample_type: Sampling method - "random", "head", or "tail"
        seed: Random seed for reproducibility (only for random sampling)

    Returns:
        Sampled data list

    Examples:
        >>> data = [{"id": i} for i in range(100)]
        >>> sample_data(data, num=5, sample_type="head")
        [{'id': 0}, {'id': 1}, {'id': 2}, {'id': 3}, {'id': 4}]
        >>> sample_data(data, num=3, sample_type="tail")
        [{'id': 97}, {'id': 98}, {'id': 99}]
        >>> len(sample_data(data, num=0))  # 0 means all
        100
        >>> sample_data(data, num=-1, sample_type="head")  # last 1 item
        [{'id': 99}]
        >>> sample_data(data, num=-3, sample_type="tail")  # last 3 items
        [{'id': 97}, {'id': 98}, {'id': 99}]
    """
    import random as rand_module

    if not data:
        return []

    total = len(data)

    # Determine actual number to sample
    if num == 0:
        # 0 means sample all data
        actual_num = total
    elif num < 0:
        # Negative number: Python slice style (e.g., -1 means 1 item, -10 means 10 items)
        actual_num = min(abs(num), total)
    else:
        # Positive number: normal sampling
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
    Sample data from a file with streaming support for large files.

    对于 head/tail 采样，支持流式读取，不需要加载整个文件到内存。
    对于 random 采样，JSONL 使用蓄水池采样算法，其他格式需要加载全部数据。

    Args:
        filepath: Input file path (supports csv, xlsx, jsonl, json, parquet, arrow, feather)
        num: Number of items to sample
        sample_type: Sampling method - "random", "head", or "tail"
        seed: Random seed for reproducibility (only for random sampling)
        output: Output file path (optional, if provided, saves sampled data)

    Returns:
        Sampled data list

    Examples:
        >>> sampled = sample_file("data.jsonl", num=100, sample_type="random")
        >>> sample_file("data.csv", num=50, output="sampled.jsonl")
    """
    filepath = Path(filepath)
    file_format = _detect_format(filepath)

    # 尝试使用流式采样
    sampled = _stream_sample(filepath, file_format, num, sample_type, seed)

    # Save if output specified
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
    """
    流式采样实现。

    支持的流式优化：
    - head: jsonl, csv, parquet, arrow, excel
    - tail: jsonl（反向读取）
    - random: jsonl（蓄水池采样）

    num == 0 表示采样所有数据，回退到全量加载。
    num < 0 表示 Python 切片风格，回退到全量加载。
    """
    # num == 0 表示采样所有数据，num < 0 表示切片风格，都需要全量加载
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

    # random 采样优化（仅 JSONL，使用蓄水池采样）
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
    """CSV 流式读取前 N 行"""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for CSV support. Install with: pip install pandas")

    df = pd.read_csv(filepath, encoding="utf-8", nrows=num)
    return df.to_dict("records")


def _stream_head_parquet(filepath: Path, num: int) -> List[Dict[str, Any]]:
    """Parquet 真流式读取前 N 行（使用 iter_batches 避免全量加载）"""
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise ImportError("pyarrow is required for Parquet support. Install with: pip install pyarrow")

    parquet_file = pq.ParquetFile(filepath)
    result = []

    # 使用 iter_batches 真正流式读取，只读取需要的数据
    for batch in parquet_file.iter_batches(batch_size=min(num, 10000)):
        batch_data = batch.to_pylist()
        result.extend(batch_data)
        if len(result) >= num:
            break

    return result[:num]


def _stream_head_arrow(filepath: Path, num: int) -> List[Dict[str, Any]]:
    """Arrow/Feather 流式读取前 N 行"""
    try:
        import pyarrow.feather as feather
    except ImportError:
        raise ImportError("pyarrow is required for Arrow support. Install with: pip install pyarrow")

    table = feather.read_table(filepath)
    sliced = table.slice(0, min(num, table.num_rows))
    return _deserialize_arrow_data(sliced.to_pylist())


def _deserialize_arrow_data(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """反序列化 Arrow 数据中的 JSON 字符串字段"""
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


def _stream_head_excel(filepath: Path, num: int) -> List[Dict[str, Any]]:
    """Excel 流式读取前 N 行"""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas and openpyxl are required for Excel support")

    df = pd.read_excel(filepath, nrows=num)
    return df.to_dict("records")


def append_to_file(data: List[Dict[str, Any]],
                   filepath: str,
                   file_format: str = 'jsonl') -> None:
    """
    Append data to an existing file.

    Args:
        data: List of data items to append
        filepath: Path to file
        file_format: File format (only 'jsonl' supported for append)
    """
    filepath = Path(filepath)

    if file_format != 'jsonl':
        raise ValueError("Only JSONL format supports appending")

    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, 'a', encoding='utf-8') as f:
        for item in data:
            json_line = json.dumps(item, ensure_ascii=False)
            f.write(json_line + '\n')


def count_lines(filepath: str) -> int:
    """
    Count number of lines in a JSONL file without loading all data.

    Args:
        filepath: Path to JSONL file

    Returns:
        Number of lines
    """
    count = 0
    with open(filepath, 'r', encoding='utf-8') as f:
        for _ in f:
            count += 1
    return count


def stream_jsonl(filepath: str, chunk_size: int = 1000):
    """
    Stream JSONL file in chunks.

    Args:
        filepath: Path to JSONL file
        chunk_size: Number of items per chunk

    Yields:
        Chunks of data items
    """
    chunk = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                chunk.append(json.loads(line))
                if len(chunk) >= chunk_size:
                    yield chunk
                    chunk = []

        if chunk:
            yield chunk


# ============ JSONL 流式采样优化 ============


def _stream_tail_jsonl(filepath: Path, num: int) -> List[Dict[str, Any]]:
    """
    JSONL 反向读取后 N 行（避免全量加载）。

    使用双端队列保持最后 N 行，内存占用 O(num) 而非 O(total)。
    """
    from collections import deque

    # 使用 deque 的 maxlen 自动保持最后 N 个元素
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
    """
    JSONL 蓄水池采样（Reservoir Sampling）。

    单次遍历文件，内存占用 O(num)，适合超大文件随机采样。
    算法保证每条数据被选中的概率相等。
    """
    import random

    if seed is not None:
        random.seed(seed)

    reservoir = []  # 蓄水池

    with open(filepath, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue

            item = json.loads(line)

            if len(reservoir) < num:
                # 蓄水池未满，直接加入
                reservoir.append(item)
            else:
                # 蓄水池已满，以 num/(i+1) 的概率替换
                j = random.randint(0, i)
                if j < num:
                    reservoir[j] = item

    return reservoir


# ============ FlaxKV Format ============

def _save_flaxkv(data: List[Dict[str, Any]], filepath: Path) -> None:
    """
    Save data in FlaxKV format.

    Args:
        data: List of data items to save
        filepath: Path to FlaxKV database (directory)
    """
    from flaxkv2 import FlaxKV

    # Use the directory name as the database name
    db_name = filepath.stem if filepath.stem else "data"
    db_path = filepath.parent

    # Create FlaxKV database
    with FlaxKV(db_name, str(db_path)) as db:
        # Store metadata
        db["_metadata"] = {
            "total": len(data),
            "format": "flaxkv"
        }

        # Store each item with index as key
        for i, item in enumerate(data):
            db[f"item:{i}"] = item


def _load_flaxkv(filepath: Path) -> List[Dict[str, Any]]:
    """
    Load data from FlaxKV format.

    Args:
        filepath: Path to FlaxKV database (directory)

    Returns:
        List of data items
    """
    from flaxkv2 import FlaxKV

    # Use the directory name as the database name
    db_name = filepath.stem if filepath.stem else "data"
    db_path = filepath.parent

    # Open FlaxKV database
    with FlaxKV(db_name, str(db_path)) as db:
        # Collect all items
        items = []
        for key in sorted(db.keys()):
            if key.startswith("item:"):
                items.append(db[key])

        return items
