"""
格式转换器模块

提供与 HuggingFace datasets 等常用格式的互转功能。
"""
from typing import List, Dict, Any, Optional, Union, Callable


def to_hf_dataset(data: List[Dict[str, Any]]):
    """
    转换为 HuggingFace Dataset。

    Args:
        data: 数据列表

    Returns:
        datasets.Dataset 对象

    Examples:
        >>> ds = to_hf_dataset(dt.data)
        >>> ds.push_to_hub("my-dataset")
    """
    try:
        from datasets import Dataset
    except ImportError:
        raise ImportError("需要安装 datasets: pip install datasets")

    return Dataset.from_list(data)


def from_hf_dataset(dataset, split: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    从 HuggingFace Dataset 转换。

    Args:
        dataset: Dataset/DatasetDict 对象或数据集名称
        split: 数据集分割（如 "train", "test"）

    Returns:
        数据列表

    Examples:
        >>> data = from_hf_dataset("tatsu-lab/alpaca")
        >>> data = from_hf_dataset(my_dataset, split="train")
    """
    try:
        from datasets import load_dataset, Dataset, DatasetDict
    except ImportError:
        raise ImportError("需要安装 datasets: pip install datasets")

    # 如果是字符串，加载数据集
    if isinstance(dataset, str):
        dataset = load_dataset(dataset, split=split)

    # 处理 DatasetDict
    if hasattr(dataset, 'keys'):  # DatasetDict
        if split:
            dataset = dataset[split]
        else:
            # 默认取第一个 split
            first_key = list(dataset.keys())[0]
            dataset = dataset[first_key]

    return list(dataset)


def to_hf_chat_format(
    messages_field: str = "messages",
    add_generation_prompt: bool = False,
) -> Callable:
    """
    转换为 HuggingFace chat 模板格式。

    输出格式与 tokenizer.apply_chat_template() 兼容。

    Args:
        messages_field: messages 字段名
        add_generation_prompt: 是否添加生成提示

    Returns:
        转换函数

    Examples:
        >>> dt.transform(to_hf_chat_format())
    """
    def transform(item) -> dict:
        messages = item.get(messages_field, []) if hasattr(item, 'get') else item[messages_field]
        result = {"messages": messages}
        if add_generation_prompt:
            result["add_generation_prompt"] = True
        return result

    return transform


def from_openai_batch(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    从 OpenAI Batch API 结果转换。

    Args:
        data: OpenAI batch 输出数据

    Returns:
        简化后的数据列表

    Examples:
        >>> results = from_openai_batch(batch_output)
    """
    results = []
    for item in data:
        if item.get("response", {}).get("status_code") == 200:
            body = item["response"]["body"]
            results.append({
                "custom_id": item.get("custom_id"),
                "content": body["choices"][0]["message"]["content"],
                "model": body.get("model"),
                "usage": body.get("usage"),
            })
    return results


def to_openai_batch(
    messages_field: str = "messages",
    model: str = "gpt-4o-mini",
    custom_id_field: Optional[str] = None,
) -> Callable:
    """
    转换为 OpenAI Batch API 输入格式。

    Args:
        messages_field: messages 字段名
        model: 模型名称
        custom_id_field: 自定义 ID 字段，None 则自动生成

    Returns:
        转换函数

    Examples:
        >>> batch_input = dt.to(to_openai_batch(model="gpt-4o"))
    """
    def transform(item, idx=[0]) -> dict:
        messages = item.get(messages_field, []) if hasattr(item, 'get') else item[messages_field]

        if custom_id_field:
            custom_id = item.get(custom_id_field) if hasattr(item, 'get') else item[custom_id_field]
        else:
            custom_id = f"request-{idx[0]}"
            idx[0] += 1

        return {
            "custom_id": str(custom_id),
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": model,
                "messages": messages,
            }
        }

    return transform


def to_llama_factory(
    instruction_field: str = "instruction",
    input_field: str = "input",
    output_field: str = "output",
    system_field: Optional[str] = None,
    history_field: Optional[str] = None,
) -> Callable:
    """
    转换为 LLaMA-Factory 训练格式。

    输出格式:
    {
        "instruction": "...",
        "input": "...",
        "output": "...",
        "system": "...",      # 可选
        "history": [...]      # 可选
    }

    Args:
        instruction_field: 指令字段
        input_field: 输入字段
        output_field: 输出字段
        system_field: 系统提示字段
        history_field: 历史对话字段

    Returns:
        转换函数
    """
    def transform(item) -> dict:
        get = lambda f: (item.get(f, "") if hasattr(item, 'get') else item.get(f, ""))

        result = {
            "instruction": get(instruction_field),
            "input": get(input_field),
            "output": get(output_field),
        }

        if system_field:
            system = get(system_field)
            if system:
                result["system"] = system

        if history_field:
            history = get(history_field)
            if history:
                result["history"] = history

        return result

    return transform


def to_axolotl(
    conversations_field: str = "conversations",
    from_key: str = "from",
    value_key: str = "value",
) -> Callable:
    """
    转换为 Axolotl 训练格式（ShareGPT 风格）。

    输出格式:
    {
        "conversations": [
            {"from": "human", "value": "..."},
            {"from": "gpt", "value": "..."}
        ]
    }

    Args:
        conversations_field: 对话字段名
        from_key: 角色键名
        value_key: 内容键名

    Returns:
        转换函数
    """
    def transform(item) -> dict:
        conversations = item.get(conversations_field, []) if hasattr(item, 'get') else item.get(conversations_field, [])

        # 如果已经是正确格式，直接返回
        if conversations and isinstance(conversations[0], dict):
            if from_key in conversations[0] and value_key in conversations[0]:
                return {"conversations": conversations}

        # 尝试从 messages 格式转换
        messages = item.get("messages", []) if hasattr(item, 'get') else item.get("messages", [])
        if messages:
            role_map = {"user": "human", "assistant": "gpt", "system": "system"}
            conversations = [
                {from_key: role_map.get(m.get("role", ""), m.get("role", "")), value_key: m.get("content", "")}
                for m in messages
            ]

        return {"conversations": conversations}

    return transform


def messages_to_text(
    messages_field: str = "messages",
    output_field: str = "text",
    template: str = "chatml",
) -> Callable:
    """
    将 messages 格式转换为纯文本。

    Args:
        messages_field: messages 字段名
        output_field: 输出字段名
        template: 模板类型
            - "chatml": <|im_start|>role\ncontent<|im_end|>
            - "llama2": [INST] ... [/INST]
            - "simple": Role: content

    Returns:
        转换函数

    Examples:
        >>> dt.transform(messages_to_text(template="chatml"))
    """
    templates = {
        "chatml": lambda role, content: f"<|im_start|>{role}\n{content}<|im_end|>",
        "llama2": lambda role, content: f"[INST] {content} [/INST]" if role == "user" else content,
        "simple": lambda role, content: f"{role.title()}: {content}",
    }

    if template not in templates:
        raise ValueError(f"不支持的模板: {template}，可选: {list(templates.keys())}")

    fmt = templates[template]

    def transform(item) -> dict:
        result = item.to_dict() if hasattr(item, 'to_dict') else dict(item)
        messages = item.get(messages_field, []) if hasattr(item, 'get') else item[messages_field]

        parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            parts.append(fmt(role, content))

        result[output_field] = "\n".join(parts)
        return result

    return transform
