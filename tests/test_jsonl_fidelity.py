"""JSONL 预览/采样必须原样返回记录: 每行结构不同是 JSONL 的常态, 不能被按列统一 schema。"""

import orjson
import pytest

from dtflow.storage.io import sample_file

ROWS = [
    # 纯文本 content 与多模态 list content 混在同一列
    {"id": 1, "messages": [{"role": "user", "content": "hi"}]},
    {"id": 2, "messages": [{"role": "user", "content": [{"type": "text", "text": "看"}]}]},
    # 只有这一行的消息带 tool_calls, 其余行不该被补上 "tool_calls": null
    {"id": 3, "messages": [{"role": "assistant", "content": None, "tool_calls": [{"id": "c"}]}]},
    # 数据里真的 null 要保留
    {"id": 4, "extra": None, "messages": []},
]


@pytest.fixture
def path(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_bytes(b"\n".join(orjson.dumps(r) for r in ROWS) + b"\n")
    return p


@pytest.mark.parametrize("sample_type", ["head", "tail", "random"])
def test_records_round_trip_unchanged(path, sample_type):
    got = sample_file(str(path), num=len(ROWS), sample_type=sample_type, seed=0)
    assert sorted(got, key=lambda r: r["id"]) == ROWS


def test_tail_takes_last_lines(path):
    assert [r["id"] for r in sample_file(str(path), num=2, sample_type="tail")] == [3, 4]
