"""
SFT (Supervised Fine-Tuning) format converter.
"""
from typing import Dict, Any, List, Optional
from .base import BaseFormatter


class SFTFormatter(BaseFormatter):
    """
    Formatter for SFT (Supervised Fine-Tuning) format.

    Standard SFT format:
    {
        "messages": [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."}
        ]
    }

    Or simple format:
    {
        "instruction": "...",
        "input": "...",
        "output": "..."
    }
    """

    def format(self, item: Dict[str, Any], style: str = 'messages', **kwargs) -> Dict[str, Any]:
        """
        Convert item to SFT format.

        Args:
            item: Input data item
            style: Output style ('messages' or 'simple')
            **kwargs: Additional options like 'system_prompt'

        Returns:
            Item in SFT format
        """
        if style == 'messages':
            return self._format_messages(item, **kwargs)
        elif style == 'simple':
            return self._format_simple(item, **kwargs)
        else:
            raise ValueError(f"Unknown SFT style: {style}")

    def _format_messages(self, item: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Format to messages-style SFT."""
        # If already in messages format, return as is
        if 'messages' in item:
            return item

        messages = []

        # Add system message if provided
        system_prompt = kwargs.get('system_prompt', item.get('system', ''))
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Handle various input formats
        if 'instruction' in item:
            # Instruction-based format
            user_content = item['instruction']
            if 'input' in item and item['input']:
                user_content += f"\n\nInput: {item['input']}"
            messages.append({"role": "user", "content": user_content})

            if 'output' in item:
                messages.append({"role": "assistant", "content": item['output']})

        elif 'prompt' in item and 'response' in item:
            # Prompt-response format
            messages.append({"role": "user", "content": item['prompt']})
            messages.append({"role": "assistant", "content": item['response']})

        elif 'question' in item and 'answer' in item:
            # Q&A format
            messages.append({"role": "user", "content": item['question']})
            messages.append({"role": "assistant", "content": item['answer']})

        elif 'conversations' in item:
            # Multi-turn conversation
            for turn in item['conversations']:
                messages.append({
                    "role": turn.get('from', turn.get('role', 'user')),
                    "content": turn.get('value', turn.get('content', ''))
                })

        else:
            # Try to extract any text-like fields
            text_fields = ['text', 'content', 'data']
            for field in text_fields:
                if field in item:
                    messages.append({"role": "user", "content": item[field]})
                    break

        result = {"messages": messages}

        # Preserve any additional metadata
        for key, value in item.items():
            if key not in ['messages', 'instruction', 'input', 'output', 'prompt', 'response',
                          'question', 'answer', 'conversations', 'system']:
                result[key] = value

        return result

    def _format_simple(self, item: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Format to simple instruction-style SFT."""
        # If already in simple format, return as is
        if 'instruction' in item and 'output' in item:
            return item

        result = {
            "instruction": "",
            "input": "",
            "output": ""
        }

        if 'messages' in item:
            # Convert from messages format
            messages = item['messages']
            for msg in messages:
                role = msg.get('role', '')
                content = msg.get('content', '')

                if role == 'system':
                    result['instruction'] = content
                elif role == 'user':
                    if not result['instruction']:
                        result['instruction'] = content
                    else:
                        result['input'] = content
                elif role == 'assistant':
                    result['output'] = content

        elif 'prompt' in item and 'response' in item:
            result['instruction'] = item['prompt']
            result['output'] = item['response']

        elif 'question' in item and 'answer' in item:
            result['instruction'] = item['question']
            result['output'] = item['answer']

        else:
            # Copy matching fields
            if 'instruction' in item:
                result['instruction'] = item['instruction']
            if 'input' in item:
                result['input'] = item['input']
            if 'output' in item:
                result['output'] = item['output']

        # Preserve metadata
        for key, value in item.items():
            if key not in ['messages', 'instruction', 'input', 'output', 'prompt',
                          'response', 'question', 'answer', 'system']:
                result[key] = value

        return result

    def parse(self, item: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Parse item from SFT format to generic format.

        Args:
            item: Item in SFT format

        Returns:
            Generic format item
        """
        # Just return as is, since SFT format is our base generic format
        return item
