"""
Core DataTransformer class for flexible data manipulation and format conversion.
"""
from typing import List, Dict, Any, Optional, Callable, Union
from copy import deepcopy
import json
from .formats.sft import SFTFormatter
from .formats.rlhf import RLHFFormatter
from .formats.pretrain import PretrainFormatter
from .utils.similarity import calculate_similarity
from .utils.display import display_data
from .storage.io import save_data, load_data


class DataTransformer:
    """
    A flexible data transformation tool that acts as a bridge between different ML training formats.

    Supports:
    - Multiple format conversions (SFT, RLHF, Pretrain)
    - Data manipulation (add, modify, delete)
    - Data inspection (count, similarity, display)
    - Save/Load functionality
    """

    def __init__(self, data: Optional[List[Dict[str, Any]]] = None):
        """
        Initialize DataTransformer with optional data.

        Args:
            data: List of dictionaries representing the dataset
        """
        self._data = data if data is not None else []
        self._formatters = {
            'sft': SFTFormatter(),
            'rlhf': RLHFFormatter(),
            'pretrain': PretrainFormatter()
        }

    @property
    def data(self) -> List[Dict[str, Any]]:
        """Get the current data."""
        return self._data

    def __len__(self) -> int:
        """Return the number of items in the dataset."""
        return len(self._data)

    def __getitem__(self, idx: Union[int, slice]) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """Get item(s) by index or slice."""
        return self._data[idx]

    def __repr__(self) -> str:
        """String representation of the DataTransformer."""
        return f"DataTransformer(samples={len(self._data)})"

    # ============ Data Manipulation Methods ============

    def add(self, item: Union[Dict[str, Any], List[Dict[str, Any]]]) -> 'DataTransformer':
        """
        Add one or more items to the dataset.

        Args:
            item: A single dictionary or list of dictionaries to add

        Returns:
            Self for method chaining
        """
        if isinstance(item, dict):
            self._data.append(deepcopy(item))
        elif isinstance(item, list):
            self._data.extend(deepcopy(item))
        else:
            raise TypeError("Item must be a dictionary or list of dictionaries")
        return self

    def modify(self,
               index: Optional[int] = None,
               condition: Optional[Callable[[Dict[str, Any]], bool]] = None,
               updates: Optional[Dict[str, Any]] = None,
               transform: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None) -> 'DataTransformer':
        """
        Modify item(s) in the dataset.

        Args:
            index: Index of item to modify (if specified, modifies single item)
            condition: Function that returns True for items to modify
            updates: Dictionary of key-value pairs to update
            transform: Function to transform the entire item

        Returns:
            Self for method chaining

        Examples:
            # Modify by index
            dt.modify(index=0, updates={'label': 'positive'})

            # Modify by condition
            dt.modify(condition=lambda x: x['score'] > 0.5, updates={'label': 'high'})

            # Modify with transform function
            dt.modify(condition=lambda x: 'text' in x,
                     transform=lambda x: {**x, 'text': x['text'].upper()})
        """
        if index is not None:
            if index < 0 or index >= len(self._data):
                raise IndexError(f"Index {index} out of range")

            if transform:
                self._data[index] = transform(deepcopy(self._data[index]))
            elif updates:
                self._data[index].update(updates)

        elif condition:
            for i, item in enumerate(self._data):
                if condition(item):
                    if transform:
                        self._data[i] = transform(deepcopy(item))
                    elif updates:
                        self._data[i].update(updates)
        else:
            raise ValueError("Must specify either 'index' or 'condition'")

        return self

    def delete(self,
               index: Optional[int] = None,
               condition: Optional[Callable[[Dict[str, Any]], bool]] = None) -> 'DataTransformer':
        """
        Delete item(s) from the dataset.

        Args:
            index: Index of item to delete
            condition: Function that returns True for items to delete

        Returns:
            Self for method chaining

        Examples:
            # Delete by index
            dt.delete(index=0)

            # Delete by condition
            dt.delete(condition=lambda x: x['score'] < 0.3)
        """
        if index is not None:
            if index < 0 or index >= len(self._data):
                raise IndexError(f"Index {index} out of range")
            del self._data[index]

        elif condition:
            self._data = [item for item in self._data if not condition(item)]

        else:
            raise ValueError("Must specify either 'index' or 'condition'")

        return self

    def filter(self, condition: Callable[[Dict[str, Any]], bool]) -> 'DataTransformer':
        """
        Filter dataset keeping only items that match the condition.

        Args:
            condition: Function that returns True for items to keep

        Returns:
            Self for method chaining
        """
        self._data = [item for item in self._data if condition(item)]
        return self

    def map(self, transform: Callable[[Dict[str, Any]], Dict[str, Any]]) -> 'DataTransformer':
        """
        Apply a transformation to all items in the dataset.

        Args:
            transform: Function to transform each item

        Returns:
            Self for method chaining
        """
        self._data = [transform(deepcopy(item)) for item in self._data]
        return self

    # ============ Data Inspection Methods ============

    def count(self, condition: Optional[Callable[[Dict[str, Any]], bool]] = None) -> int:
        """
        Count items in the dataset, optionally with a condition.

        Args:
            condition: Optional function that returns True for items to count

        Returns:
            Number of items (matching condition if provided)

        Examples:
            # Count all items
            total = dt.count()

            # Count items with condition
            positive = dt.count(lambda x: x['label'] == 'positive')
        """
        if condition is None:
            return len(self._data)
        return sum(1 for item in self._data if condition(item))

    def similarity(self,
                   index1: int,
                   index2: int,
                   method: str = 'cosine',
                   text_field: str = 'text') -> float:
        """
        Calculate similarity between two items in the dataset.

        Args:
            index1: Index of first item
            index2: Index of second item
            method: Similarity method ('cosine', 'jaccard', 'edit_distance')
            text_field: Field name containing text to compare

        Returns:
            Similarity score (higher means more similar)
        """
        if index1 < 0 or index1 >= len(self._data):
            raise IndexError(f"Index {index1} out of range")
        if index2 < 0 or index2 >= len(self._data):
            raise IndexError(f"Index {index2} out of range")

        text1 = str(self._data[index1].get(text_field, ''))
        text2 = str(self._data[index2].get(text_field, ''))

        return calculate_similarity(text1, text2, method=method)

    def find_similar(self,
                     reference: Union[int, str],
                     top_k: int = 5,
                     method: str = 'cosine',
                     text_field: str = 'text') -> List[tuple]:
        """
        Find most similar items to a reference.

        Args:
            reference: Index of reference item or text string
            top_k: Number of similar items to return
            method: Similarity method
            text_field: Field name containing text to compare

        Returns:
            List of (index, similarity_score) tuples
        """
        if isinstance(reference, int):
            if reference < 0 or reference >= len(self._data):
                raise IndexError(f"Index {reference} out of range")
            ref_text = str(self._data[reference].get(text_field, ''))
        else:
            ref_text = reference

        similarities = []
        for i, item in enumerate(self._data):
            if isinstance(reference, int) and i == reference:
                continue
            text = str(item.get(text_field, ''))
            sim = calculate_similarity(ref_text, text, method=method)
            similarities.append((i, sim))

        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]

    def display(self,
                n: int = 5,
                fields: Optional[List[str]] = None,
                start: int = 0,
                format_type: Optional[str] = None) -> None:
        """
        Display data in a readable format.

        Args:
            n: Number of items to display
            fields: Specific fields to display (None = all fields)
            start: Starting index
            format_type: Optional format to convert to before display ('sft', 'rlhf', 'pretrain')
        """
        data_to_display = self._data[start:start + n]

        if format_type and format_type in self._formatters:
            formatter = self._formatters[format_type]
            data_to_display = [formatter.format(item) for item in data_to_display]

        display_data(data_to_display, fields=fields, start_index=start)

    def stats(self) -> Dict[str, Any]:
        """
        Get statistics about the dataset.

        Returns:
            Dictionary containing dataset statistics
        """
        if not self._data:
            return {"total": 0, "fields": []}

        all_keys = set()
        for item in self._data:
            all_keys.update(item.keys())

        field_stats = {}
        for key in all_keys:
            values = [item.get(key) for item in self._data if key in item]
            field_stats[key] = {
                "count": len(values),
                "missing": len(self._data) - len(values),
                "type": type(values[0]).__name__ if values else "unknown"
            }

        return {
            "total": len(self._data),
            "fields": list(all_keys),
            "field_stats": field_stats
        }

    # ============ Format Conversion Methods ============

    def to_sft(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Convert data to SFT (Supervised Fine-Tuning) format.

        Returns:
            List of dictionaries in SFT format
        """
        return self._formatters['sft'].format_batch(self._data, **kwargs)

    def to_rlhf(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Convert data to RLHF (Reinforcement Learning from Human Feedback) format.

        Returns:
            List of dictionaries in RLHF format
        """
        return self._formatters['rlhf'].format_batch(self._data, **kwargs)

    def to_pretrain(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Convert data to pre-training format.

        Returns:
            List of dictionaries in pre-training format
        """
        return self._formatters['pretrain'].format_batch(self._data, **kwargs)

    def from_format(self, data: List[Dict[str, Any]], format_type: str) -> 'DataTransformer':
        """
        Load data from a specific format.

        Args:
            data: Data in the specified format
            format_type: Format type ('sft', 'rlhf', 'pretrain')

        Returns:
            Self for method chaining
        """
        if format_type not in self._formatters:
            raise ValueError(f"Unknown format: {format_type}")

        self._data = self._formatters[format_type].parse_batch(data)
        return self

    # ============ Save/Load Methods ============

    def save(self,
             filepath: str,
             format_type: Optional[str] = None,
             file_format: str = 'jsonl') -> None:
        """
        Save data to file.

        Args:
            filepath: Path to save file
            format_type: Optional format to convert to before saving ('sft', 'rlhf', 'pretrain')
            file_format: File format ('jsonl', 'json', 'csv', 'parquet')
        """
        data_to_save = self._data

        if format_type and format_type in self._formatters:
            data_to_save = self._formatters[format_type].format_batch(data_to_save)

        save_data(data_to_save, filepath, file_format=file_format)

    @classmethod
    def load(cls,
             filepath: str,
             file_format: Optional[str] = None,
             source_format: Optional[str] = None) -> 'DataTransformer':
        """
        Load data from file.

        Args:
            filepath: Path to load file
            file_format: File format ('jsonl', 'json', 'csv', 'parquet'), auto-detected if None
            source_format: If data is in a specific format, parse it ('sft', 'rlhf', 'pretrain')

        Returns:
            New DataTransformer instance with loaded data
        """
        data = load_data(filepath, file_format=file_format)

        instance = cls(data)

        if source_format and source_format in instance._formatters:
            instance._data = instance._formatters[source_format].parse_batch(data)

        return instance

    # ============ Utility Methods ============

    def copy(self) -> 'DataTransformer':
        """Create a deep copy of the DataTransformer."""
        return DataTransformer(deepcopy(self._data))

    def clear(self) -> 'DataTransformer':
        """Clear all data."""
        self._data = []
        return self

    def shuffle(self, seed: Optional[int] = None) -> 'DataTransformer':
        """
        Randomly shuffle the dataset.

        Args:
            seed: Random seed for reproducibility

        Returns:
            Self for method chaining
        """
        import random
        if seed is not None:
            random.seed(seed)
        random.shuffle(self._data)
        return self

    def split(self, ratio: float = 0.8, shuffle: bool = True, seed: Optional[int] = None) -> tuple:
        """
        Split dataset into two parts.

        Args:
            ratio: Ratio for first split (e.g., 0.8 for 80/20 split)
            shuffle: Whether to shuffle before splitting
            seed: Random seed if shuffling

        Returns:
            Tuple of two DataTransformer instances
        """
        data = deepcopy(self._data)

        if shuffle:
            import random
            if seed is not None:
                random.seed(seed)
            random.shuffle(data)

        split_idx = int(len(data) * ratio)
        return DataTransformer(data[:split_idx]), DataTransformer(data[split_idx:])
