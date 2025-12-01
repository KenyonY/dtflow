"""
Base formatter class for format conversion.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseFormatter(ABC):
    """Base class for all format converters."""

    @abstractmethod
    def format(self, item: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Convert a single item to the target format.

        Args:
            item: Input data item
            **kwargs: Additional formatting options

        Returns:
            Formatted item
        """
        pass

    @abstractmethod
    def parse(self, item: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Parse a single item from the target format back to generic format.

        Args:
            item: Item in target format
            **kwargs: Additional parsing options

        Returns:
            Generic format item
        """
        pass

    def format_batch(self, items: List[Dict[str, Any]], **kwargs) -> List[Dict[str, Any]]:
        """
        Convert a batch of items to the target format.

        Args:
            items: List of input data items
            **kwargs: Additional formatting options

        Returns:
            List of formatted items
        """
        return [self.format(item, **kwargs) for item in items]

    def parse_batch(self, items: List[Dict[str, Any]], **kwargs) -> List[Dict[str, Any]]:
        """
        Parse a batch of items from the target format.

        Args:
            items: List of items in target format
            **kwargs: Additional parsing options

        Returns:
            List of generic format items
        """
        return [self.parse(item, **kwargs) for item in items]
