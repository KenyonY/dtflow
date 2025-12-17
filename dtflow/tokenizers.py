"""
Token 统计模块

提供 token 计数和基于 token 长度的过滤功能。
"""
from typing import Callable, Union, List, Dict, Any, Optional

# 延迟导入，避免未安装时报错
_tokenizer_cache = {}


def _get_tiktoken_encoder(model: str = "gpt-4"):
    """获取 tiktoken 编码器（带缓存）"""
    if model not in _tokenizer_cache:
        try:
            import tiktoken
            _tokenizer_cache[model] = tiktoken.encoding_for_model(model)
        except ImportError:
            raise ImportError("需要安装 tiktoken: pip install tiktoken")
    return _tokenizer_cache[model]


def _get_transformers_tokenizer(model: str):
    """获取 transformers tokenizer（带缓存）"""
    if model not in _tokenizer_cache:
        try:
            from transformers import AutoTokenizer
            _tokenizer_cache[model] = AutoTokenizer.from_pretrained(model)
        except ImportError:
            raise ImportError("需要安装 transformers: pip install transformers")
    return _tokenizer_cache[model]


def count_tokens(
    text: str,
    model: str = "gpt-4",
    backend: str = "tiktoken",
) -> int:
    """
    计算文本的 token 数量。

    Args:
        text: 输入文本
        model: 模型名称
        backend: 后端选择
            - "tiktoken": OpenAI tiktoken（快速，支持 GPT 系列）
            - "transformers": HuggingFace transformers（支持更多模型）

    Returns:
        token 数量
    """
    if not text:
        return 0

    if backend == "tiktoken":
        encoder = _get_tiktoken_encoder(model)
        return len(encoder.encode(text))
    elif backend == "transformers":
        tokenizer = _get_transformers_tokenizer(model)
        return len(tokenizer.encode(text))
    else:
        raise ValueError(f"不支持的 backend: {backend}")


def token_counter(
    fields: Union[str, List[str]],
    model: str = "gpt-4",
    backend: str = "tiktoken",
    output_field: str = "token_count",
) -> Callable:
    """
    创建 token 计数转换函数。

    Args:
        fields: 要统计的字段（单个或多个）
        model: 模型名称
        backend: tiktoken 或 transformers
        output_field: 输出字段名

    Returns:
        转换函数，用于 dt.transform()

    Examples:
        >>> dt.transform(token_counter("text"))
        >>> dt.transform(token_counter(["question", "answer"]))
    """
    if isinstance(fields, str):
        fields = [fields]

    def transform(item) -> dict:
        result = item.to_dict() if hasattr(item, 'to_dict') else dict(item)
        total = 0
        for field in fields:
            value = item.get(field, "") if hasattr(item, 'get') else item[field]
            if value:
                total += count_tokens(str(value), model=model, backend=backend)
        result[output_field] = total
        return result

    return transform


def token_filter(
    fields: Union[str, List[str]],
    min_tokens: Optional[int] = None,
    max_tokens: Optional[int] = None,
    model: str = "gpt-4",
    backend: str = "tiktoken",
) -> Callable:
    """
    创建基于 token 长度的过滤函数。

    Args:
        fields: 要统计的字段（单个或多个）
        min_tokens: 最小 token 数（包含）
        max_tokens: 最大 token 数（包含）
        model: 模型名称
        backend: tiktoken 或 transformers

    Returns:
        过滤函数，用于 dt.filter()

    Examples:
        >>> dt.filter(token_filter("text", min_tokens=10, max_tokens=512))
        >>> dt.filter(token_filter(["q", "a"], max_tokens=2048))
    """
    if isinstance(fields, str):
        fields = [fields]

    def filter_func(item) -> bool:
        total = 0
        for field in fields:
            value = item.get(field, "") if hasattr(item, 'get') else item[field]
            if value:
                total += count_tokens(str(value), model=model, backend=backend)

        if min_tokens is not None and total < min_tokens:
            return False
        if max_tokens is not None and total > max_tokens:
            return False
        return True

    return filter_func


def token_stats(
    data: List[Dict[str, Any]],
    fields: Union[str, List[str]],
    model: str = "gpt-4",
    backend: str = "tiktoken",
) -> Dict[str, Any]:
    """
    统计数据集的 token 信息。

    Args:
        data: 数据列表
        fields: 要统计的字段
        model: 模型名称
        backend: tiktoken 或 transformers

    Returns:
        统计信息字典
    """
    if isinstance(fields, str):
        fields = [fields]

    if not data:
        return {"total_tokens": 0, "count": 0}

    counts = []
    for item in data:
        total = 0
        for field in fields:
            value = item.get(field, "")
            if value:
                total += count_tokens(str(value), model=model, backend=backend)
        counts.append(total)

    return {
        "total_tokens": sum(counts),
        "count": len(counts),
        "avg_tokens": sum(counts) / len(counts),
        "min_tokens": min(counts),
        "max_tokens": max(counts),
        "median_tokens": sorted(counts)[len(counts) // 2],
    }
