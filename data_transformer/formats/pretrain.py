"""
Pre-training format converter.
"""
from typing import Dict, Any, List
from .base import BaseFormatter


class PretrainFormatter(BaseFormatter):
    """
    Formatter for pre-training format.

    Standard pre-training format is simple text:
    {
        "text": "..."
    }

    Or with metadata:
    {
        "text": "...",
        "meta": {
            "source": "...",
            "quality_score": 0.95
        }
    }
    """

    def format(self, item: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Convert item to pre-training format.

        Args:
            item: Input data item
            **kwargs: Additional options like 'join_char', 'include_meta'

        Returns:
            Item in pre-training format
        """
        join_char = kwargs.get('join_char', '\n\n')
        include_meta = kwargs.get('include_meta', True)

        # If already in simple text format, return as is
        if 'text' in item and len(item) == 1:
            return item

        result = {"text": ""}
        text_parts = []

        # Extract text from various formats
        if 'text' in item:
            text_parts.append(item['text'])

        elif 'messages' in item:
            # Convert conversation to continuous text
            for msg in item['messages']:
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                if role == 'system':
                    text_parts.append(f"System: {content}")
                elif role == 'user':
                    text_parts.append(f"User: {content}")
                elif role == 'assistant':
                    text_parts.append(f"Assistant: {content}")
                else:
                    text_parts.append(content)

        elif 'instruction' in item:
            # Convert instruction format to text
            if item['instruction']:
                text_parts.append(f"Instruction: {item['instruction']}")
            if item.get('input'):
                text_parts.append(f"Input: {item['input']}")
            if item.get('output'):
                text_parts.append(f"Output: {item['output']}")

        elif 'prompt' in item and 'response' in item:
            # Convert prompt-response to text
            text_parts.append(f"Prompt: {item['prompt']}")
            text_parts.append(f"Response: {item['response']}")

        elif 'question' in item and 'answer' in item:
            # Convert Q&A to text
            text_parts.append(f"Question: {item['question']}")
            text_parts.append(f"Answer: {item['answer']}")

        elif 'content' in item:
            text_parts.append(item['content'])

        else:
            # Try to concatenate all string values
            for key, value in item.items():
                if isinstance(value, str) and value:
                    text_parts.append(f"{key.capitalize()}: {value}")

        result['text'] = join_char.join(text_parts)

        # Include metadata if requested
        if include_meta:
            meta = {}

            # Standard metadata fields
            meta_fields = ['source', 'url', 'timestamp', 'author', 'title',
                          'quality_score', 'language', 'domain']

            for field in meta_fields:
                if field in item:
                    meta[field] = item[field]

            # Add any other non-text fields as metadata
            for key, value in item.items():
                if key not in ['text', 'messages', 'instruction', 'input', 'output',
                              'prompt', 'response', 'question', 'answer', 'content'] \
                   and key not in meta_fields:
                    meta[key] = value

            if meta:
                result['meta'] = meta

        return result

    def parse(self, item: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Parse item from pre-training format to generic format.

        Args:
            item: Item in pre-training format

        Returns:
            Generic format item
        """
        # Pre-training format is already quite generic
        # Just ensure it has the expected structure
        result = {}

        if 'text' in item:
            result['text'] = item['text']

        if 'meta' in item:
            # Flatten metadata into main dict
            result.update(item['meta'])

        # Preserve other fields
        for key, value in item.items():
            if key not in ['text', 'meta']:
                result[key] = value

        return result
