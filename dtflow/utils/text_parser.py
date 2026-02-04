"""
文本清洗工具

提供 LLM 输出的常见清洗函数：
- strip_think_tags: 去除 <think>...</think> 思考链内容
- extract_code_snippets: 提取 ``` 代码块
- parse_generic_tags: 解析 <tag>content</tag> 格式标签
"""

import re
from typing import Dict, List


def strip_think_tags(text: str) -> str:
    """去除 <think>...</think> 包裹的内容

    Args:
        text: 输入文本

    Returns:
        去除思考链后的文本

    Examples:
        >>> strip_think_tags("<think>让我想想...</think>答案是42")
        '答案是42'
    """
    if not text:
        return text
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def extract_code_snippets(text: str, strict: bool = True) -> List[Dict[str, str]]:
    """提取 ``` 代码块

    Args:
        text: 输入文本
        strict: True 仅匹配 ```lang...``` 格式，False 额外匹配 {...} 格式

    Returns:
        代码片段列表，每项为 {"language": ..., "code": ...}

    Examples:
        >>> extract_code_snippets("```json\\n{\"a\": 1}\\n```")
        [{'language': 'json', 'code': '{"a": 1}'}]
    """
    pattern = r"```(\w+)?\s*([\s\S]*?)```"
    matches = re.findall(pattern, text)

    code_snippets = []
    for lang, code in matches:
        code_snippets.append(
            {
                "language": lang.strip() if lang else "unknown",
                "code": code.strip(),
            }
        )

    if not strict:
        # 移除已匹配的 ``` 块，在剩余文本中匹配 { ... }
        text = re.sub(pattern, "", text)
        brace_matches = re.findall(r"\{[\s\S]*?\}", text)
        for code in brace_matches:
            code_snippets.append(
                {
                    "language": "unknown",
                    "code": code.strip(),
                }
            )

    return code_snippets


def parse_generic_tags(text: str, strict: bool = False) -> Dict[str, str]:
    """解析 XML 风格标签

    支持两种模式：
    - strict=True: 仅匹配闭合标签 <label>content</label>
    - strict=False: 同时匹配开放式标签 <label>content，闭合标签优先

    Args:
        text: 输入文本
        strict: 是否严格模式

    Returns:
        {标签名: 内容} 字典

    Examples:
        >>> parse_generic_tags("<标签>内容</标签>")
        {'标签': '内容'}
        >>> parse_generic_tags("<a>hello<b>world", strict=False)
        {'a': 'hello', 'b': 'world'}
    """
    if not text:
        return {}

    result = {}

    if strict:
        pattern_closed = r"<([^>]+)>\s*(.*?)\s*</\1>"
        matches = re.findall(pattern_closed, text, re.DOTALL)
        for label, content in matches:
            result[label.strip()] = content.strip()
    else:
        remaining_text = str(text)

        # 1. 优先处理闭合标签
        def process_closed_tag(match_obj):
            label = match_obj.group(1).strip()
            content = match_obj.group(2).strip()
            result[label] = content
            return ""

        pattern_closed = r"<([^>]+)>\s*(.*?)\s*</\1>"
        remaining_text = re.sub(pattern_closed, process_closed_tag, remaining_text, flags=re.DOTALL)

        # 2. 在剩余文本中处理开放式标签
        pattern_open = r"<([^>]+)>\s*(.*?)(?=<[^>]+>|$)"
        matches_open = re.findall(pattern_open, remaining_text, re.DOTALL)
        for label, content in matches_open:
            label_stripped = label.strip()
            if label_stripped not in result:
                result[label_stripped] = content.strip()

    return result
