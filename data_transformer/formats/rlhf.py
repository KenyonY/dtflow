"""
RLHF (Reinforcement Learning from Human Feedback) format converter.
这里更应该叫DPO
"""
from typing import Dict, Any, List
from .base import BaseFormatter


class RLHFFormatter(BaseFormatter):
    """
    Formatter for RLHF format.

    Standard RLHF format includes:
    {
        "prompt": "...",
        "chosen": "...",
        "rejected": "...",
        "score_chosen": 1.0,
        "score_rejected": 0.0
    }

    Or preference pair format:
    {
        "query": "...",
        "responses": [
            {"text": "...", "score": 1.0, "rank": 1},
            {"text": "...", "score": 0.5, "rank": 2}
        ]
    }
    """

    def format(self, item: Dict[str, Any], style: str = 'pair', **kwargs) -> Dict[str, Any]:
        """
        Convert item to RLHF format.

        Args:
            item: Input data item
            style: Output style ('pair' or 'ranked')
            **kwargs: Additional options

        Returns:
            Item in RLHF format
        """
        if style == 'pair':
            return self._format_pair(item, **kwargs)
        elif style == 'ranked':
            return self._format_ranked(item, **kwargs)
        else:
            raise ValueError(f"Unknown RLHF style: {style}")

    def _format_pair(self, item: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Format to preference pair style."""
        # If already in pair format, return as is
        if 'prompt' in item and 'chosen' in item and 'rejected' in item:
            return item

        result = {
            "prompt": "",
            "chosen": "",
            "rejected": ""
        }

        # Extract prompt
        if 'prompt' in item:
            result['prompt'] = item['prompt']
        elif 'query' in item:
            result['prompt'] = item['query']
        elif 'question' in item:
            result['prompt'] = item['question']
        elif 'instruction' in item:
            prompt = item['instruction']
            if 'input' in item and item['input']:
                prompt += f"\n\n{item['input']}"
            result['prompt'] = prompt
        elif 'messages' in item:
            # Extract user messages as prompt
            user_messages = [msg['content'] for msg in item['messages']
                           if msg.get('role') == 'user']
            result['prompt'] = '\n'.join(user_messages) if user_messages else ''

        # Extract chosen and rejected responses
        if 'chosen' in item:
            result['chosen'] = item['chosen']
        elif 'responses' in item and isinstance(item['responses'], list):
            # Sort by score or rank
            responses = sorted(item['responses'],
                             key=lambda x: x.get('score', x.get('rank', 0)),
                             reverse=True)
            if len(responses) >= 2:
                result['chosen'] = responses[0].get('text', str(responses[0]))
                result['rejected'] = responses[-1].get('text', str(responses[-1]))
            elif len(responses) == 1:
                result['chosen'] = responses[0].get('text', str(responses[0]))

        if 'rejected' in item:
            result['rejected'] = item['rejected']

        # Add scores if available
        if 'score_chosen' in item:
            result['score_chosen'] = item['score_chosen']
        if 'score_rejected' in item:
            result['score_rejected'] = item['score_rejected']

        # Preserve metadata
        for key, value in item.items():
            if key not in ['prompt', 'chosen', 'rejected', 'query', 'question',
                          'instruction', 'input', 'messages', 'responses',
                          'score_chosen', 'score_rejected']:
                result[key] = value

        return result

    def _format_ranked(self, item: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Format to ranked responses style."""
        # If already in ranked format, return as is
        if 'query' in item and 'responses' in item:
            return item

        result = {
            "query": "",
            "responses": []
        }

        # Extract query
        if 'query' in item:
            result['query'] = item['query']
        elif 'prompt' in item:
            result['query'] = item['prompt']
        elif 'question' in item:
            result['query'] = item['question']
        elif 'instruction' in item:
            query = item['instruction']
            if 'input' in item and item['input']:
                query += f"\n\n{item['input']}"
            result['query'] = query

        # Extract responses
        if 'responses' in item:
            result['responses'] = item['responses']
        elif 'chosen' in item and 'rejected' in item:
            result['responses'] = [
                {
                    "text": item['chosen'],
                    "score": item.get('score_chosen', 1.0),
                    "rank": 1
                },
                {
                    "text": item['rejected'],
                    "score": item.get('score_rejected', 0.0),
                    "rank": 2
                }
            ]
        elif 'output' in item:
            result['responses'] = [
                {
                    "text": item['output'],
                    "score": item.get('score', 1.0),
                    "rank": 1
                }
            ]

        # Preserve metadata
        for key, value in item.items():
            if key not in ['query', 'prompt', 'question', 'instruction', 'input',
                          'responses', 'chosen', 'rejected', 'output',
                          'score_chosen', 'score_rejected', 'score']:
                result[key] = value

        return result

    def parse(self, item: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Parse item from RLHF format to generic format.

        Args:
            item: Item in RLHF format

        Returns:
            Generic format item
        """
        # Convert to a standard prompt-response format
        result = {}

        if 'prompt' in item:
            result['prompt'] = item['prompt']
        elif 'query' in item:
            result['prompt'] = item['query']

        if 'chosen' in item:
            result['response'] = item['chosen']
            result['response_rejected'] = item.get('rejected', '')

        if 'responses' in item and isinstance(item['responses'], list):
            result['responses'] = item['responses']

        # Preserve other fields
        for key, value in item.items():
            if key not in ['prompt', 'query', 'chosen', 'rejected', 'responses']:
                result[key] = value

        return result
