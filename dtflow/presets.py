"""
预设转换模板: 训练格式之间的互转, 可直接用于 dt.to(preset=...) / dt.transform(preset=...) / CLI --preset。

每个预设先认输入的形态再转换 (messages / sharegpt conversations / alpaca / dpo / q-a),
显式传入的字段名优先; 认不出的行抛 ValueError (调用方按 on_error 跳过并汇总),
不会静默产出 content 为空的样本。
"""

import json
from typing import Any, Callable, Dict, List, Optional

from dtflow.utils.helpers import get_field_value


def _row(item: Any) -> Dict[str, Any]:
    """DictWrapper / dict → 原始 dict"""
    if isinstance(item, dict):
        return item
    if hasattr(item, "to_dict"):
        return item.to_dict()
    return dict(item)


_SHAREGPT_TO_ROLE = {
    "human": "user",
    "user": "user",
    "gpt": "assistant",
    "assistant": "assistant",
    "system": "system",
}
_ROLE_TO_SHAREGPT = {"user": "human", "assistant": "gpt", "system": "system", "tool": "observation"}


def _parse_function_call(value: Any) -> tuple:
    """function_call 的 value (JSON 字符串或 dict) → (name, arguments 字符串)"""
    try:
        spec = json.loads(value) if isinstance(value, str) else value
        name = spec.get("name", "")
        args = spec.get("arguments", {})
        arguments = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
        return name, arguments
    except (ValueError, AttributeError):
        return "", str(value)


def _sharegpt_to_messages(convs: List[Dict]) -> List[Dict]:
    """sharegpt conversations → OpenAI messages。

    连续的 function_call 合并成一条带多个 tool_calls 的 assistant 消息 (紧跟在 gpt 文本后面时
    直接挂到那条消息上); observation 按先进先出配给尚未回复的 call —— 并行工具调用不丢、不错配。
    """
    out: List[Dict] = []
    pending: List[str] = []  # 已发出、还没收到 observation 的 call id
    for i, c in enumerate(convs):
        src, value = c.get("from", ""), c.get("value", "")
        if src == "function_call":
            call_id = f"call_{i}"
            name, arguments = _parse_function_call(value)
            call = {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
            if out and out[-1].get("role") == "assistant" and not pending:
                out[-1].setdefault("tool_calls", []).append(call)  # 文本 + 调用同一条
            elif out and out[-1].get("role") == "assistant" and out[-1].get("tool_calls"):
                out[-1]["tool_calls"].append(call)  # 并行调用
            else:
                out.append({"role": "assistant", "content": "", "tool_calls": [call]})
            pending.append(call_id)
        elif src == "observation":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": pending.pop(0) if pending else "",
                    "content": value,
                }
            )
        else:
            out.append({"role": _SHAREGPT_TO_ROLE.get(src, src), "content": value})
    return out


def _messages_to_sharegpt(
    messages: List[Dict], mapping: Optional[Dict[str, str]] = None
) -> List[Dict]:
    """OpenAI messages → sharegpt。assistant 的文本与每个 tool_call 各占一条, 一个都不丢。"""
    mapping = mapping or _ROLE_TO_SHAREGPT
    out: List[Dict] = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content")
        calls = m.get("tool_calls") or []
        if role == "assistant" and calls:
            if content:
                out.append({"from": mapping.get("assistant", "gpt"), "value": content})
            for call in calls:
                fn = call.get("function", {})
                args = fn.get("arguments", "")
                try:
                    args = json.loads(args) if isinstance(args, str) else args
                except ValueError:
                    pass
                out.append(
                    {
                        "from": "function_call",
                        "value": json.dumps(
                            {"name": fn.get("name", ""), "arguments": args}, ensure_ascii=False
                        ),
                    }
                )
        else:
            out.append(
                {"from": mapping.get(role, role), "value": content if content is not None else ""}
            )
    return out


def _text_of(value: Any) -> Any:
    """HF 风格 DPO 的 chosen/rejected 可以是消息列表: 取最后一条的 content"""
    if isinstance(value, list) and value and isinstance(value[-1], dict) and "content" in value[-1]:
        return value[-1]["content"]
    return value


def _pair(row: Dict, user_field: str, assistant_field: str, explicit: bool) -> Optional[tuple]:
    """从 alpaca / dpo / q-a 形态取出 (user, assistant) 文本; 认不出返回 None。"""
    if explicit:
        u, a = get_field_value(row, user_field), get_field_value(row, assistant_field)
        if u and a:
            return u, a
    if row.get("instruction") and row.get("output"):  # alpaca
        u = row["instruction"]
        if row.get("input"):
            u = f"{u}\n\n{row['input']}"
        return u, row["output"]
    if row.get("prompt") and row.get("chosen"):  # dpo → 取 chosen
        return _text_of(row["prompt"]), _text_of(row["chosen"])
    u, a = get_field_value(row, user_field), get_field_value(row, assistant_field)
    if u and a:
        return u, a
    for uf, af in (("question", "answer"), ("query", "response")):
        if row.get(uf) and row.get(af):
            return row[uf], row[af]
    return None


def _to_messages(item: Any, user_field: str, assistant_field: str, explicit: bool) -> List[Dict]:
    """任意已知形态 → messages 列表 (不含 system_prompt 注入)。"""
    row = _row(item)
    if explicit:
        pair = _pair(row, user_field, assistant_field, True)
        if pair:
            return [{"role": "user", "content": pair[0]}, {"role": "assistant", "content": pair[1]}]
    if isinstance(row.get("messages"), list) and row["messages"]:
        return [dict(m) for m in row["messages"]]
    if isinstance(row.get("conversations"), list) and row["conversations"]:
        return _sharegpt_to_messages(row["conversations"])
    prompt, chosen = row.get("prompt"), row.get("chosen")
    if (
        isinstance(prompt, list) and prompt and chosen
    ):  # HF 风格 dpo: prompt 是对话, chosen 是消息列表或文本
        tail = (
            [dict(m) for m in chosen]
            if isinstance(chosen, list)
            else [{"role": "assistant", "content": chosen}]
        )
        return [dict(m) for m in prompt] + tail
    pair = _pair(row, user_field, assistant_field, False)
    if pair:
        return [{"role": "user", "content": pair[0]}, {"role": "assistant", "content": pair[1]}]
    raise ValueError(
        f"无法识别输入格式 (需要 messages / conversations / instruction+output / prompt+chosen / "
        f"{user_field}+{assistant_field}), 字段: {sorted(row)[:8]}"
    )


def openai_chat(
    user_field: str = "q", assistant_field: str = "a", system_prompt: Optional[str] = None
) -> Callable:
    """
    → OpenAI Chat 格式 {"messages": [{"role", "content"}, ...]}。

    输入可以是: 已有 messages (原样) / sharegpt conversations (function_call → tool_calls) /
    alpaca instruction+input+output / dpo prompt+chosen / 单轮 q-a (字段名可指定)。

    Args:
        user_field: 单轮问答的用户字段名 (默认 q; 显式指定时优先于自动识别)
        assistant_field: 单轮问答的助手字段名 (默认 a)
        system_prompt: 注入的系统提示词 (可选; 已有 system 消息时不重复加)
    """
    explicit = (user_field, assistant_field) != ("q", "a")

    def transform(item: Any) -> dict:
        messages = _to_messages(item, user_field, assistant_field, explicit)
        if system_prompt and not (messages and messages[0].get("role") == "system"):
            messages = [{"role": "system", "content": system_prompt}] + messages
        return {"messages": messages}

    return transform


def _first(messages: List[Dict], role: str) -> str:
    for m in messages:
        if m.get("role") == role and m.get("content"):
            return m["content"]
    return ""


def alpaca(
    instruction_field: str = "instruction", input_field: str = "input", output_field: str = "output"
) -> Callable:
    """
    → Alpaca 格式 {"instruction", "input", "output"}。

    输入可以是 alpaca (字段名可指定) / messages / sharegpt / dpo / q-a: 多轮对话取第一轮 user→instruction、
    assistant→output。
    """

    def transform(item: Any) -> dict:
        row = _row(item)
        inst, out = get_field_value(row, instruction_field), get_field_value(row, output_field)
        if inst and out:
            return {"instruction": inst, "input": get_field_value(row, input_field), "output": out}
        messages = _to_messages(row, "q", "a", False)
        inst, out = _first(messages, "user"), _first(messages, "assistant")
        if not (inst and out):
            raise ValueError("样本里没有成对的 user / assistant 内容")
        return {"instruction": inst, "input": "", "output": out}

    return transform


def sharegpt(
    conversations_field: str = "conversations", role_mapping: Optional[dict] = None
) -> Callable:
    """
    → ShareGPT 格式 {"conversations": [{"from": "human"|"gpt", "value"}, ...]}。

    输入可以是 sharegpt (原样) / messages (tool_calls → function_call, tool → observation) /
    alpaca / dpo / q-a。role_mapping 可覆盖 messages role → from 的映射。
    """
    mapping = dict(_ROLE_TO_SHAREGPT)
    if role_mapping:
        mapping.update(role_mapping)

    def transform(item: Any) -> dict:
        row = _row(item)
        convs = get_field_value(row, conversations_field, [])
        if convs:
            return {"conversations": convs}
        messages = _to_messages(row, "q", "a", False)
        return {"conversations": _messages_to_sharegpt(messages, mapping)}

    return transform


def dpo_pair(
    prompt_field: str = "prompt", chosen_field: str = "chosen", rejected_field: str = "rejected"
) -> Callable:
    """→ DPO 偏好对 {"prompt", "chosen", "rejected"}。只按字段名取值 (不做形态识别), 三个字段缺一即报错。"""

    def transform(item: Any) -> dict:
        row = _row(item)
        out = {
            "prompt": get_field_value(row, prompt_field),
            "chosen": get_field_value(row, chosen_field),
            "rejected": get_field_value(row, rejected_field),
        }
        missing = [k for k, v in out.items() if not v]
        if missing:
            raise ValueError(f"缺少字段: {', '.join(missing)}")
        return out

    return transform


def simple_qa(question_field: str = "q", answer_field: str = "a") -> Callable:
    """→ {"question", "answer"}。输入可以是 q-a (字段名可指定) / messages / sharegpt / alpaca / dpo。"""
    explicit = (question_field, answer_field) != ("q", "a")

    def transform(item: Any) -> dict:
        messages = _to_messages(item, question_field, answer_field, explicit)
        q, a = _first(messages, "user"), _first(messages, "assistant")
        if not (q and a):
            raise ValueError("样本里没有成对的 user / assistant 内容")
        return {"question": q, "answer": a}

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
    """按名字取预设转换函数, kwargs 透传给预设。"""
    if name not in PRESETS:
        available = ", ".join(PRESETS.keys())
        raise ValueError(f"未知预设: {name}。可用预设: {available}")
    return PRESETS[name](**kwargs)


def list_presets() -> list:
    """列出所有可用预设"""
    return list(PRESETS.keys())
