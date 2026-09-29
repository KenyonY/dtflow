"""预设按输入形态自动转换; schema 预设接受 OpenAI 工具调用形态。"""

import json

import pytest

from dtflow import DataTransformer, get_preset, openai_chat_schema, sharegpt_schema

QA = {"q": "hi", "a": "hello"}
ALPACA = {"instruction": "Translate", "input": "你好", "output": "hello"}
DPO = {"prompt": "p", "chosen": "good", "rejected": "bad"}
MSGS = {
    "messages": [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "a"},
    ]
}
SG = {"conversations": [{"from": "human", "value": "u"}, {"from": "gpt", "value": "a"}]}
SG_TOOL = {
    "conversations": [
        {"from": "human", "value": "weather?"},
        {
            "from": "function_call",
            "value": json.dumps({"name": "get_weather", "arguments": {"city": "Tokyo"}}),
        },
        {"from": "observation", "value": '{"temp": 27}'},
        {"from": "gpt", "value": "27°C"},
    ]
}
MSGS_TOOL = {
    "messages": [
        {"role": "user", "content": "weather?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "Tokyo"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"temp": 27}'},
        {"role": "assistant", "content": "27°C"},
    ]
}


class TestOpenAIChat:
    def test_from_every_shape(self):
        f = get_preset("openai_chat")
        assert f(QA)["messages"] == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        assert f(ALPACA)["messages"] == [
            {"role": "user", "content": "Translate\n\n你好"},
            {"role": "assistant", "content": "hello"},
        ]
        assert f(DPO)["messages"] == [
            {"role": "user", "content": "p"},
            {"role": "assistant", "content": "good"},
        ]
        assert f(MSGS)["messages"] == MSGS["messages"]
        assert f(SG)["messages"] == [
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
        ]

    def test_sharegpt_function_call_becomes_tool_calls(self):
        out = get_preset("openai_chat")(SG_TOOL)["messages"]
        assert (
            out[1]["role"] == "assistant"
            and out[1]["tool_calls"][0]["function"]["name"] == "get_weather"
        )
        assert json.loads(out[1]["tool_calls"][0]["function"]["arguments"]) == {"city": "Tokyo"}
        assert out[2]["role"] == "tool" and out[2]["tool_call_id"] == out[1]["tool_calls"][0]["id"]

    def test_explicit_fields_win_and_system_prompt(self):
        f = get_preset(
            "openai_chat", user_field="question", assistant_field="answer", system_prompt="S"
        )
        out = f(
            {"question": "q?", "answer": "a!", "messages": [{"role": "user", "content": "ignored"}]}
        )
        assert out["messages"] == [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "q?"},
            {"role": "assistant", "content": "a!"},
        ]
        assert (
            get_preset("openai_chat", system_prompt="S")(MSGS)["messages"][0]["content"] == "s"
        )  # 已有 system 不重复

    def test_unknown_shape_raises_instead_of_empty(self):
        with pytest.raises(ValueError, match="无法识别"):
            get_preset("openai_chat")({"text": "lonely"})
        dt = DataTransformer([QA, {"text": "lonely"}])
        assert len(dt.to(preset="openai_chat")) == 1  # 默认 skip + 汇总


class TestOtherPresets:
    def test_alpaca_from_messages_and_sharegpt(self):
        f = get_preset("alpaca")
        assert f(ALPACA) == ALPACA
        assert f(MSGS) == {"instruction": "u", "input": "", "output": "a"}
        assert f(SG) == {"instruction": "u", "input": "", "output": "a"}
        assert f(QA) == {"instruction": "hi", "input": "", "output": "hello"}

    def test_sharegpt_from_messages_with_tools(self):
        out = get_preset("sharegpt")(MSGS_TOOL)["conversations"]
        assert [c["from"] for c in out] == ["human", "function_call", "observation", "gpt"]
        assert json.loads(out[1]["value"]) == {
            "name": "get_weather",
            "arguments": {"city": "Tokyo"},
        }
        assert (
            get_preset("sharegpt", role_mapping={"user": "usr"})(QA)["conversations"][0]["from"]
            == "usr"
        )

    def test_simple_qa_and_dpo(self):
        assert get_preset("simple_qa")(MSGS) == {"question": "u", "answer": "a"}
        assert get_preset("simple_qa", question_field="instruction", answer_field="output")(
            ALPACA
        ) == {"question": "Translate", "answer": "hello"}
        assert get_preset("dpo_pair")(DPO) == DPO
        with pytest.raises(ValueError, match="rejected"):
            get_preset("dpo_pair")({"prompt": "p", "chosen": "c"})

    def test_to_and_transform_accept_preset_kwarg(self):
        dt = DataTransformer([ALPACA])
        assert dt.to(preset="openai_chat")[0]["messages"][1]["content"] == "hello"
        assert dt.transform(preset="simple_qa").data == [
            {"question": "Translate\n\n你好", "answer": "hello"}
        ]
        with pytest.raises(ValueError):
            dt.to(lambda x: x, preset="alpaca")
        with pytest.raises(ValueError):
            dt.to(lambda x: x, user_field="q")


class TestSchemasAcceptToolCalls:
    def test_openai_chat_schema(self):
        s = openai_chat_schema()
        assert s.validate(MSGS_TOOL).valid
        assert s.validate(MSGS).valid
        r = s.validate(
            {"messages": [{"role": "user", "content": "u"}, {"role": "assistant", "content": ""}]}
        )
        assert not r.valid and "content 为空" in r.errors[0].message
        r = s.validate({"messages": [{"role": "tool", "content": "x"}]})
        assert not r.valid and "tool_call_id" in r.errors[0].message
        assert not s.validate({"messages": [{"role": "robot", "content": "x"}]}).valid
        assert not openai_chat_schema(roles=["user", "assistant"]).validate(MSGS_TOOL).valid

    def test_sharegpt_schema(self):
        assert sharegpt_schema().validate(SG_TOOL).valid
        assert not sharegpt_schema(extra_roles=[]).validate(SG_TOOL).valid
