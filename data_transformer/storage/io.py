"""
Input/Output utilities for saving and loading data.
"""
from typing import List, Dict, Any, Optional
import json
import os
from pathlib import Path


def save_data(data: List[Dict[str, Any]],
              filepath: str,
              file_format: str = 'jsonl') -> None:
    """
    Save data to file.

    Args:
        data: List of data items to save
        filepath: Path to save file
        file_format: File format ('jsonl', 'json', 'csv', 'parquet', 'flaxkv')
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    if file_format == 'jsonl':
        _save_jsonl(data, filepath)
    elif file_format == 'json':
        _save_json(data, filepath)
    elif file_format == 'csv':
        _save_csv(data, filepath)
    elif file_format == 'parquet':
        _save_parquet(data, filepath)
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


# ============ Additional Utilities ============

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
