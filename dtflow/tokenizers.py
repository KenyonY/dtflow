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


def _auto_backend(model: str) -> str:
    """自动检测 tokenizer backend"""
    # 本地路径或包含 / 的模型 ID 使用 transformers
    if "/" in model or model.startswith(("/", "~", ".")):
        return "transformers"
    # OpenAI 模型使用 tiktoken
    openai_models = {"gpt-4", "gpt-4o", "gpt-3.5-turbo", "gpt-4-turbo", "o1", "o1-mini"}
    if model in openai_models or model.startswith(("gpt-", "o1")):
        return "tiktoken"
    # 默认尝试 transformers
    return "transformers"


def _count_messages_tokens(
    messages: List[Dict[str, Any]],
    model: str,
    backend: str,
) -> Dict[str, int]:
    """统计 messages 中各角色的 token 数"""
    role_tokens = {"user": 0, "assistant": 0, "system": 0, "other": 0}
    turn_tokens = []

    for msg in messages:
        role = msg.get("role", "other")
        content = msg.get("content", "")
        if not content:
            continue

        tokens = count_tokens(str(content), model=model, backend=backend)

        if role in role_tokens:
            role_tokens[role] += tokens
        else:
            role_tokens["other"] += tokens

        turn_tokens.append(tokens)

    total = sum(role_tokens.values())
    return {
        "total": total,
        "user": role_tokens["user"],
        "assistant": role_tokens["assistant"],
        "system": role_tokens["system"],
        "turns": len(turn_tokens),
        "avg_turn": total // len(turn_tokens) if turn_tokens else 0,
        "max_turn": max(turn_tokens) if turn_tokens else 0,
    }


def messages_token_counter(
    messages_field: str = "messages",
    model: str = "gpt-4",
    backend: Optional[str] = None,
    output_field: str = "token_stats",
    detailed: bool = False,
) -> Callable:
    """
    创建 messages token 计数转换函数。

    Args:
        messages_field: messages 字段名
        model: 模型名称或本地路径
            - OpenAI 模型: "gpt-4", "gpt-4o" 等（使用 tiktoken）
            - HuggingFace 模型: "Qwen/Qwen2-7B" 等
            - 本地路径: "/path/to/model"
        backend: 强制指定后端，None 则自动检测
        output_field: 输出字段名
        detailed: True 则输出详细统计，False 只输出 total

    Returns:
        转换函数，用于 dt.transform()

    Examples:
        >>> # 使用 tiktoken (OpenAI 模型)
        >>> dt.transform(messages_token_counter(model="gpt-4"))

        >>> # 使用本地 Qwen 模型
        >>> dt.transform(messages_token_counter(model="/home/models/Qwen2-7B"))

        >>> # 详细统计
        >>> dt.transform(messages_token_counter(detailed=True))
        # 输出: {"token_stats": {"total": 500, "user": 200, "assistant": 300, ...}}
    """
    _backend = backend or _auto_backend(model)

    def transform(item) -> dict:
        result = item.to_dict() if hasattr(item, "to_dict") else dict(item)
        messages = item.get(messages_field, []) if hasattr(item, "get") else item.get(messages_field, [])

        if not messages:
            result[output_field] = 0 if not detailed else {"total": 0}
            return result

        stats = _count_messages_tokens(messages, model=model, backend=_backend)

        if detailed:
            result[output_field] = stats
        else:
            result[output_field] = stats["total"]

        return result

    return transform


def messages_token_filter(
    messages_field: str = "messages",
    min_tokens: Optional[int] = None,
    max_tokens: Optional[int] = None,
    min_turns: Optional[int] = None,
    max_turns: Optional[int] = None,
    model: str = "gpt-4",
    backend: Optional[str] = None,
) -> Callable:
    """
    创建基于 messages token 的过滤函数。

    Args:
        messages_field: messages 字段名
        min_tokens: 最小总 token 数
        max_tokens: 最大总 token 数
        min_turns: 最小对话轮数
        max_turns: 最大对话轮数
        model: 模型名称或路径
        backend: 后端，None 则自动检测

    Returns:
        过滤函数，用于 dt.filter()

    Examples:
        >>> dt.filter(messages_token_filter(min_tokens=100, max_tokens=2048))
        >>> dt.filter(messages_token_filter(min_turns=2, max_turns=10))
    """
    _backend = backend or _auto_backend(model)

    def filter_func(item) -> bool:
        messages = item.get(messages_field, []) if hasattr(item, "get") else item.get(messages_field, [])

        if not messages:
            return False

        stats = _count_messages_tokens(messages, model=model, backend=_backend)

        if min_tokens is not None and stats["total"] < min_tokens:
            return False
        if max_tokens is not None and stats["total"] > max_tokens:
            return False
        if min_turns is not None and stats["turns"] < min_turns:
            return False
        if max_turns is not None and stats["turns"] > max_turns:
            return False

        return True

    return filter_func


def messages_token_stats(
    data: List[Dict[str, Any]],
    messages_field: str = "messages",
    model: str = "gpt-4",
    backend: Optional[str] = None,
) -> Dict[str, Any]:
    """
    统计数据集中 messages 的 token 信息。

    Args:
        data: 数据列表
        messages_field: messages 字段名
        model: 模型名称或路径
        backend: 后端，None 则自动检测

    Returns:
        统计信息字典

    Examples:
        >>> stats = messages_token_stats(dt.data, model="gpt-4")
        >>> print(stats)
        {
            "count": 1000,
            "total_tokens": 500000,
            "user_tokens": 200000,
            "assistant_tokens": 290000,
            "system_tokens": 10000,
            "avg_tokens": 500,
            "max_tokens": 2048,
            "min_tokens": 50,
            "avg_turns": 4,
        }
    """
    _backend = backend or _auto_backend(model)

    if not data:
        return {"count": 0, "total_tokens": 0}

    all_stats = []
    for item in data:
        messages = item.get(messages_field, [])
        if messages:
            all_stats.append(_count_messages_tokens(messages, model=model, backend=_backend))

    if not all_stats:
        return {"count": 0, "total_tokens": 0}

    totals = [s["total"] for s in all_stats]
    return {
        "count": len(all_stats),
        "total_tokens": sum(totals),
        "user_tokens": sum(s["user"] for s in all_stats),
        "assistant_tokens": sum(s["assistant"] for s in all_stats),
        "system_tokens": sum(s["system"] for s in all_stats),
        "avg_tokens": sum(totals) // len(totals),
        "max_tokens": max(totals),
        "min_tokens": min(totals),
        "median_tokens": sorted(totals)[len(totals) // 2],
        "avg_turns": sum(s["turns"] for s in all_stats) // len(all_stats),
    }
