"""
Token 统计模块

提供 token 计数和基于 token 长度的过滤功能。
支持 OpenAI (tiktoken) 和开源模型 (transformers) 两种后端。
"""

from typing import Any, Callable, Dict, List, Optional, Union

from .utils.field_path import get_field_with_spec

# 延迟导入，避免未安装时报错
_tokenizer_cache = {}

# 默认编码器（使用 tiktoken 的 cl100k_base，速度快且依赖轻）
DEFAULT_MODEL = "cl100k_base"

# 模型别名映射：简短名称 -> HuggingFace 模型路径
MODEL_ALIASES = {
    # Qwen 系列
    "qwen2.5": "Qwen/Qwen2.5-7B",
    "qwen2.5-0.5b": "Qwen/Qwen2.5-0.5B",
    "qwen2.5-1.5b": "Qwen/Qwen2.5-1.5B",
    "qwen2.5-3b": "Qwen/Qwen2.5-3B",
    "qwen2.5-7b": "Qwen/Qwen2.5-7B",
    "qwen2.5-14b": "Qwen/Qwen2.5-14B",
    "qwen2.5-32b": "Qwen/Qwen2.5-32B",
    "qwen2.5-72b": "Qwen/Qwen2.5-72B",
    "qwen3": "Qwen/Qwen3-8B",
    "qwen3-0.6b": "Qwen/Qwen3-0.6B",
    "qwen3-1.7b": "Qwen/Qwen3-1.7B",
    "qwen3-4b": "Qwen/Qwen3-4B",
    "qwen3-8b": "Qwen/Qwen3-8B",
    "qwen3-14b": "Qwen/Qwen3-14B",
    "qwen3-32b": "Qwen/Qwen3-32B",
    "qwen3-30b-a3b": "Qwen/Qwen3-30B-A3B",
    "qwen3-235b-a22b": "Qwen/Qwen3-235B-A22B",
    "qwen2": "Qwen/Qwen2-7B",
    "qwen2-0.5b": "Qwen/Qwen2-0.5B",
    "qwen2-1.5b": "Qwen/Qwen2-1.5B",
    "qwen2-7b": "Qwen/Qwen2-7B",
    "qwen2-72b": "Qwen/Qwen2-72B",
    # Llama 系列
    "llama3": "meta-llama/Llama-3.1-8B",
    "llama3.1": "meta-llama/Llama-3.1-8B",
    "llama3.1-8b": "meta-llama/Llama-3.1-8B",
    "llama3.1-70b": "meta-llama/Llama-3.1-70B",
    "llama3.2": "meta-llama/Llama-3.2-3B",
    "llama3.2-1b": "meta-llama/Llama-3.2-1B",
    "llama3.2-3b": "meta-llama/Llama-3.2-3B",
    "llama3.3": "meta-llama/Llama-3.3-70B-Instruct",
    "llama3.3-70b": "meta-llama/Llama-3.3-70B-Instruct",
    # Mistral 系列
    "mistral": "mistralai/Mistral-7B-v0.3",
    "mistral-7b": "mistralai/Mistral-7B-v0.3",
    "mixtral": "mistralai/Mixtral-8x7B-v0.1",
    "mixtral-8x7b": "mistralai/Mixtral-8x7B-v0.1",
    # DeepSeek 系列
    "deepseek": "deepseek-ai/DeepSeek-V3",
    "deepseek-v3": "deepseek-ai/DeepSeek-V3",
    "deepseek-v2": "deepseek-ai/DeepSeek-V2",
    "deepseek-coder": "deepseek-ai/deepseek-coder-6.7b-base",
    # Yi 系列
    "yi": "01-ai/Yi-1.5-9B",
    "yi-1.5": "01-ai/Yi-1.5-9B",
    "yi-1.5-6b": "01-ai/Yi-1.5-6B",
    "yi-1.5-9b": "01-ai/Yi-1.5-9B",
    "yi-1.5-34b": "01-ai/Yi-1.5-34B",
    # InternLM 系列
    "internlm": "internlm/internlm2_5-7b",
    "internlm2.5": "internlm/internlm2_5-7b",
    "internlm2.5-7b": "internlm/internlm2_5-7b",
    "internlm2.5-20b": "internlm/internlm2_5-20b",
    # GLM 系列
    "glm4": "THUDM/glm-4-9b",
    "glm4-9b": "THUDM/glm-4-9b",
    # Baichuan 系列
    "baichuan2": "baichuan-inc/Baichuan2-13B-Base",
    "baichuan2-7b": "baichuan-inc/Baichuan2-7B-Base",
    "baichuan2-13b": "baichuan-inc/Baichuan2-13B-Base",
}

# OpenAI 模型（使用 tiktoken）
OPENAI_MODELS = {
    "gpt-4",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-3.5-turbo",
    "gpt-4-turbo",
    "o1",
    "o1-mini",
    "o1-preview",
    "o3",
    "o3-mini",
}

# tiktoken 编码器名称
TIKTOKEN_ENCODINGS = {"cl100k_base", "p50k_base", "p50k_edit", "r50k_base", "o200k_base"}


def resolve_model(model: str) -> str:
    """
    解析模型名称，将别名转换为完整的 HuggingFace 路径。

    Args:
        model: 模型名称或别名

    Returns:
        完整的模型路径
    """
    return MODEL_ALIASES.get(model.lower(), model)


def _get_tiktoken_encoder(model: str):
    """获取 tiktoken 编码器（带缓存）"""
    if model not in _tokenizer_cache:
        try:
            import tiktoken

            # 直接使用编码器名称 (cl100k_base 等) 或通过模型名获取
            if model in TIKTOKEN_ENCODINGS:
                _tokenizer_cache[model] = tiktoken.get_encoding(model)
            else:
                _tokenizer_cache[model] = tiktoken.encoding_for_model(model)
        except ImportError:
            raise ImportError("需要安装 tiktoken: pip install tiktoken")
    return _tokenizer_cache[model]


def _get_hf_tokenizer(model: str):
    """
    获取 HuggingFace tokenizer（带缓存，支持别名解析）。

    优先使用 tokenizers 库（Rust 实现，轻量快速），失败时 fallback 到 transformers。
    """
    resolved = resolve_model(model)
    if resolved not in _tokenizer_cache:
        # 优先使用 tokenizers 库（更轻量）
        try:
            from huggingface_hub import hf_hub_download
            from tokenizers import Tokenizer

            tokenizer_path = hf_hub_download(repo_id=resolved, filename="tokenizer.json")
            _tokenizer_cache[resolved] = ("tokenizers", Tokenizer.from_file(tokenizer_path))
        except Exception:
            # Fallback 到 transformers（某些模型可能没有 tokenizer.json）
            try:
                from transformers import AutoTokenizer

                tokenizer = AutoTokenizer.from_pretrained(resolved, trust_remote_code=True)
                _tokenizer_cache[resolved] = ("transformers", tokenizer)
            except ImportError:
                raise ImportError(
                    "需要安装 tokenizers 或 transformers:\n"
                    "  pip install tokenizers huggingface_hub  (推荐，更轻量)\n"
                    "  pip install transformers"
                )
    return _tokenizer_cache[resolved]


def _encode_tokens(tokenizer_info, text: str) -> int:
    """编码文本，返回 token 数量"""
    backend, tokenizer = tokenizer_info
    if backend == "tokenizers":
        return len(tokenizer.encode(text).ids)
    else:
        return len(tokenizer.encode(text))


def count_tokens(
    text: str,
    model: str = DEFAULT_MODEL,
    backend: Optional[str] = None,
) -> int:
    """
    计算文本的 token 数量。

    Args:
        text: 输入文本
        model: 模型名称或别名，如 "qwen2.5", "gpt-4", "llama3" 等
        backend: 后端选择，None 则自动检测
            - "tiktoken": OpenAI tiktoken（快速，支持 GPT 系列）
            - "transformers": HuggingFace transformers（支持开源模型）

    Returns:
        token 数量
    """
    if not text:
        return 0

    _backend = backend or _auto_backend(model)

    if _backend == "tiktoken":
        encoder = _get_tiktoken_encoder(model)
        return len(encoder.encode(text))
    elif _backend == "transformers":
        tokenizer_info = _get_hf_tokenizer(model)
        return _encode_tokens(tokenizer_info, text)
    else:
        raise ValueError(f"不支持的 backend: {_backend}")


def token_counter(
    fields: Union[str, List[str]],
    model: str = DEFAULT_MODEL,
    backend: Optional[str] = None,
    output_field: str = "token_count",
) -> Callable:
    """
    创建 token 计数转换函数。

    Args:
        fields: 要统计的字段（单个或多个），支持嵌套路径语法
            - 简单字段: "text"
            - 嵌套字段: "meta.content", "data.text"
            - 索引: "messages[0].content", "messages[-1].content"
        model: 模型名称或别名，如 "qwen2.5", "gpt-4", "llama3" 等
        backend: 后端选择，None 则自动检测
        output_field: 输出字段名

    Returns:
        转换函数，用于 dt.transform()

    Examples:
        >>> dt.transform(token_counter("text"))
        >>> dt.transform(token_counter(["question", "answer"], model="qwen3"))
        >>> dt.transform(token_counter("messages[-1].content"))  # 最后一条消息
    """
    if isinstance(fields, str):
        fields = [fields]

    def transform(item) -> dict:
        result = item.to_dict() if hasattr(item, "to_dict") else dict(item)
        total = 0
        for field in fields:
            value = get_field_with_spec(item, field, default="")
            if value:
                total += count_tokens(str(value), model=model, backend=backend)
        result[output_field] = total
        return result

    return transform


def token_filter(
    fields: Union[str, List[str]],
    min_tokens: Optional[int] = None,
    max_tokens: Optional[int] = None,
    model: str = DEFAULT_MODEL,
    backend: Optional[str] = None,
) -> Callable:
    """
    创建基于 token 长度的过滤函数。

    Args:
        fields: 要统计的字段（单个或多个），支持嵌套路径语法
            - 简单字段: "text"
            - 嵌套字段: "meta.content", "data.text"
            - 索引: "messages[0].content", "messages[-1].content"
        min_tokens: 最小 token 数（包含）
        max_tokens: 最大 token 数（包含）
        model: 模型名称
        backend: tiktoken 或 transformers

    Returns:
        过滤函数，用于 dt.filter()

    Examples:
        >>> dt.filter(token_filter("text", min_tokens=10, max_tokens=512))
        >>> dt.filter(token_filter(["q", "a"], max_tokens=2048))
        >>> dt.filter(token_filter("messages[-1].content", max_tokens=1024))
    """
    if isinstance(fields, str):
        fields = [fields]

    def filter_func(item) -> bool:
        total = 0
        for field in fields:
            value = get_field_with_spec(item, field, default="")
            if value:
                total += count_tokens(str(value), model=model, backend=backend)

        if min_tokens is not None and total < min_tokens:
            return False
        if max_tokens is not None and total > max_tokens:
            return False
        return True

    return filter_func


def _percentile(sorted_data: List[int], p: float) -> int:
    """计算百分位数"""
    n = len(sorted_data)
    if n == 0:
        return 0
    idx = (n - 1) * p / 100
    lower = int(idx)
    upper = min(lower + 1, n - 1)
    weight = idx - lower
    return int(sorted_data[lower] * (1 - weight) + sorted_data[upper] * weight)


def _std(counts: List[int], avg: float) -> float:
    """计算标准差"""
    if len(counts) < 2:
        return 0.0
    variance = sum((x - avg) ** 2 for x in counts) / len(counts)
    return variance**0.5


def token_stats(
    data: List[Dict[str, Any]],
    fields: Union[str, List[str]],
    model: str = DEFAULT_MODEL,
    backend: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """
    统计数据集的 token 信息。

    Args:
        data: 数据列表
        fields: 要统计的字段，支持嵌套路径语法（如 meta.text, messages[-1].content）
        model: 模型名称或别名，如 "qwen2.5", "gpt-4" 等
        backend: 后端选择，None 则自动检测
        progress_callback: 进度回调函数，接收 (current, total) 两个参数

    Returns:
        统计信息字典，包含:
        - total_tokens: 总 token 数
        - count: 样本数
        - avg_tokens: 平均 token 数
        - std_tokens: 标准差
        - min_tokens, max_tokens: 最小/最大值
        - median_tokens: 中位数 (p50)
        - p25, p75, p90, p95, p99: 百分位数
    """
    if isinstance(fields, str):
        fields = [fields]

    if not data:
        return {"total_tokens": 0, "count": 0}

    counts = []
    total_items = len(data)
    for i, item in enumerate(data):
        total = 0
        for field in fields:
            value = get_field_with_spec(item, field, default="")
            if value:
                total += count_tokens(str(value), model=model, backend=backend)
        counts.append(total)
        if progress_callback:
            progress_callback(i + 1, total_items)

    sorted_counts = sorted(counts)
    avg = sum(counts) / len(counts)

    return {
        "total_tokens": sum(counts),
        "count": len(counts),
        "avg_tokens": avg,
        "std_tokens": _std(counts, avg),
        "min_tokens": min(counts),
        "max_tokens": max(counts),
        "median_tokens": _percentile(sorted_counts, 50),
        "p25": _percentile(sorted_counts, 25),
        "p75": _percentile(sorted_counts, 75),
        "p90": _percentile(sorted_counts, 90),
        "p95": _percentile(sorted_counts, 95),
        "p99": _percentile(sorted_counts, 99),
    }


def _auto_backend(model: str) -> str:
    """
    自动检测 tokenizer backend。

    规则：
    1. tiktoken 编码器名称 (cl100k_base 等) -> tiktoken
    2. OpenAI 模型 (gpt-*, o1*, o3*) -> tiktoken
    3. 其他模型（包括别名和 HuggingFace 路径）-> transformers
    """
    model_lower = model.lower()

    # tiktoken 编码器名称
    if model_lower in TIKTOKEN_ENCODINGS:
        return "tiktoken"

    # OpenAI 模型使用 tiktoken
    if model_lower in OPENAI_MODELS or model_lower.startswith(("gpt-", "o1", "o3")):
        return "tiktoken"

    # 其他模型使用 transformers
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
    model: str = DEFAULT_MODEL,
    backend: Optional[str] = None,
    output_field: str = "token_stats",
    detailed: bool = False,
) -> Callable:
    """
    创建 messages token 计数转换函数。

    Args:
        messages_field: messages 字段名
        model: 模型名称或别名
            - 别名: "qwen2.5", "qwen3", "llama3", "deepseek" 等
            - OpenAI 模型: "gpt-4", "gpt-4o" 等（使用 tiktoken）
            - HuggingFace 模型: "Qwen/Qwen2.5-7B" 等
            - 本地路径: "/path/to/model"
        backend: 强制指定后端，None 则自动检测
        output_field: 输出字段名
        detailed: True 则输出详细统计，False 只输出 total

    Returns:
        转换函数，用于 dt.transform()

    Examples:
        >>> # 使用默认模型 (qwen2.5)
        >>> dt.transform(messages_token_counter())

        >>> # 使用 Qwen3
        >>> dt.transform(messages_token_counter(model="qwen3"))

        >>> # 使用 OpenAI 模型
        >>> dt.transform(messages_token_counter(model="gpt-4"))

        >>> # 详细统计
        >>> dt.transform(messages_token_counter(detailed=True))
        # 输出: {"token_stats": {"total": 500, "user": 200, "assistant": 300, ...}}
    """
    _backend = backend or _auto_backend(model)

    def transform(item) -> dict:
        result = item.to_dict() if hasattr(item, "to_dict") else dict(item)
        messages = (
            item.get(messages_field, []) if hasattr(item, "get") else item.get(messages_field, [])
        )

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
    model: str = DEFAULT_MODEL,
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
        model: 模型名称或别名
        backend: 后端，None 则自动检测

    Returns:
        过滤函数，用于 dt.filter()

    Examples:
        >>> dt.filter(messages_token_filter(min_tokens=100, max_tokens=2048))
        >>> dt.filter(messages_token_filter(min_turns=2, max_turns=10, model="qwen3"))
    """
    _backend = backend or _auto_backend(model)

    def filter_func(item) -> bool:
        messages = (
            item.get(messages_field, []) if hasattr(item, "get") else item.get(messages_field, [])
        )

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
    model: str = DEFAULT_MODEL,
    backend: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """
    统计数据集中 messages 的 token 信息。

    Args:
        data: 数据列表
        messages_field: messages 字段名，支持嵌套路径语法（如 conversation.messages）
        model: 模型名称或别名
        backend: 后端，None 则自动检测
        progress_callback: 进度回调函数，接收 (current, total) 两个参数

    Returns:
        统计信息字典，包含:
        - count: 样本数
        - total_tokens: 总 token 数
        - user_tokens, assistant_tokens, system_tokens: 各角色 token 数
        - avg_tokens, std_tokens: 平均值和标准差
        - min_tokens, max_tokens: 最小/最大值
        - median_tokens: 中位数
        - p25, p75, p90, p95, p99: 百分位数
        - avg_turns: 平均对话轮数
    """
    _backend = backend or _auto_backend(model)

    if not data:
        return {"count": 0, "total_tokens": 0}

    all_stats = []
    total_items = len(data)
    for i, item in enumerate(data):
        messages = get_field_with_spec(item, messages_field, default=[])
        if messages:
            all_stats.append(_count_messages_tokens(messages, model=model, backend=_backend))
        if progress_callback:
            progress_callback(i + 1, total_items)

    if not all_stats:
        return {"count": 0, "total_tokens": 0}

    totals = [s["total"] for s in all_stats]
    sorted_totals = sorted(totals)
    avg = sum(totals) / len(totals)

    return {
        "count": len(all_stats),
        "total_tokens": sum(totals),
        "user_tokens": sum(s["user"] for s in all_stats),
        "assistant_tokens": sum(s["assistant"] for s in all_stats),
        "system_tokens": sum(s["system"] for s in all_stats),
        "avg_tokens": int(avg),
        "std_tokens": _std(totals, avg),
        "min_tokens": min(totals),
        "max_tokens": max(totals),
        "median_tokens": _percentile(sorted_totals, 50),
        "p25": _percentile(sorted_totals, 25),
        "p75": _percentile(sorted_totals, 75),
        "p90": _percentile(sorted_totals, 90),
        "p95": _percentile(sorted_totals, 95),
        "p99": _percentile(sorted_totals, 99),
        "avg_turns": sum(s["turns"] for s in all_stats) // len(all_stats),
    }
