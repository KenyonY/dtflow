"""
预设转换模板

提供常用数据格式的转换函数，可直接用于 dt.to() 或 CLI --preset。
"""
from typing import Callable, Any


def openai_chat(
    user_field: str = "q",
    assistant_field: str = "a",
    system_prompt: str = None
) -> Callable:
    """
    OpenAI Chat 格式。

    输出格式:
    {
        "messages": [
            {"role": "system", "content": "..."},  # 可选
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."}
        ]
    }

    Args:
        user_field: 用户消息字段名
        assistant_field: 助手回复字段名
        system_prompt: 系统提示词（可选）
    """
    def transform(item: Any) -> dict:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        user_content = getattr(item, user_field, None) or item.get(user_field, "")
        assistant_content = getattr(item, assistant_field, None) or item.get(assistant_field, "")

        messages.append({"role": "user", "content": user_content})
        messages.append({"role": "assistant", "content": assistant_content})

        return {"messages": messages}

    return transform


def alpaca(
    instruction_field: str = "instruction",
    input_field: str = "input",
    output_field: str = "output"
) -> Callable:
    """
    Alpaca 格式。

    输出格式:
    {
        "instruction": "...",
        "input": "...",
        "output": "..."
    }
    """
    def transform(item: Any) -> dict:
        return {
            "instruction": getattr(item, instruction_field, None) or item.get(instruction_field, ""),
            "input": getattr(item, input_field, None) or item.get(input_field, ""),
            "output": getattr(item, output_field, None) or item.get(output_field, ""),
        }

    return transform


def sharegpt(
    conversations_field: str = "conversations",
    role_mapping: dict = None
) -> Callable:
    """
    ShareGPT 多轮对话格式。

    输出格式:
    {
        "conversations": [
            {"from": "human", "value": "..."},
            {"from": "gpt", "value": "..."}
        ]
    }
    """
    role_mapping = role_mapping or {"user": "human", "assistant": "gpt"}

    def transform(item: Any) -> dict:
        conversations = getattr(item, conversations_field, None) or item.get(conversations_field, [])

        # 如果已经是对话格式，直接返回
        if conversations:
            return {"conversations": conversations}

        # 尝试从 q/a 构建
        result = []
        for field, role in [("q", "human"), ("question", "human"), ("instruction", "human"),
                           ("a", "gpt"), ("answer", "gpt"), ("output", "gpt")]:
            value = getattr(item, field, None) or item.get(field, None)
            if value:
                result.append({"from": role, "value": value})

        return {"conversations": result}

    return transform


def dpo_pair(
    prompt_field: str = "prompt",
    chosen_field: str = "chosen",
    rejected_field: str = "rejected"
) -> Callable:
    """
    DPO 偏好对格式。

    输出格式:
    {
        "prompt": "...",
        "chosen": "...",
        "rejected": "..."
    }
    """
    def transform(item: Any) -> dict:
        return {
            "prompt": getattr(item, prompt_field, None) or item.get(prompt_field, ""),
            "chosen": getattr(item, chosen_field, None) or item.get(chosen_field, ""),
            "rejected": getattr(item, rejected_field, None) or item.get(rejected_field, ""),
        }

    return transform


def simple_qa(
    question_field: str = "q",
    answer_field: str = "a"
) -> Callable:
    """
    简单问答格式。

    输出格式:
    {
        "question": "...",
        "answer": "..."
    }
    """
    def transform(item: Any) -> dict:
        return {
            "question": getattr(item, question_field, None) or item.get(question_field, ""),
            "answer": getattr(item, answer_field, None) or item.get(answer_field, ""),
        }

    return transform


# 预设注册表
PRESETS = {
    "openai_chat": openai_chat,
    "alpaca": alpaca,
    "sharegpt": sharegpt,
    "dpo_pair": dpo_pair,
    "simple_qa": simple_qa,
}


def get_preset(name: str, **kwargs) -> Callable:
    """
    获取预设转换函数。

    Args:
        name: 预设名称
        **kwargs: 传递给预设函数的参数

    Returns:
        转换函数
    """
    if name not in PRESETS:
        available = ", ".join(PRESETS.keys())
        raise ValueError(f"未知预设: {name}。可用预设: {available}")

    return PRESETS[name](**kwargs)


def list_presets() -> list:
    """列出所有可用预设"""
    return list(PRESETS.keys())
