"""dt view 渲染层测试 (纯数据 → 派生列/详情, 不依赖 TTY)。"""

from dtflow.cli.view import render as R


def test_detect_format():
    assert R.detect_format([{"messages": [{"role": "user", "content": "hi"}]}]) == "openai_chat"
    assert R.detect_format([{"conversations": [{"from": "human", "value": "hi"}]}]) == "sharegpt"
    assert R.detect_format([{"prompt": "p", "chosen": "a", "rejected": "b"}]) == "dpo"
    assert R.detect_format([{"instruction": "i", "output": "o"}]) == "alpaca"
    assert R.detect_format([{"a": 1, "b": {"x": 2}}]) == "generic"


def test_columns_and_cells_chat():
    rows = [
        {
            "messages": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "写快排"},
                {"role": "assistant", "content": "好的"},
            ],
            "source": "math",
        }
    ]
    cols = R.build_columns(rows, "openai_chat")
    assert cols[:5] == ["#", "turns", "roles", "first_user", "chars"]
    assert "source" in cols  # 标量元数据列
    cells = dict(zip(cols, R.row_cells(0, rows[0], "openai_chat", cols)))
    assert cells["#"] == "1"  # 1-based
    assert cells["turns"] == "3"
    assert cells["roles"] == "sys→u→a"
    assert cells["first_user"] == "写快排"
    assert cells["chars"] == str(len("sys") + len("写快排") + len("好的"))
    assert cells["source"] == "math"


def test_roles_sig_truncates():
    turns = [("user", "")] * 8
    assert R._roles_sig(turns).endswith("…")


def test_multimodal_content_flattened():
    row = {"messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]}
    cells = dict(
        zip(
            R.build_columns([row], "openai_chat"),
            R.row_cells(0, row, "openai_chat", R.build_columns([row], "openai_chat")),
        )
    )
    assert cells["first_user"] == "hello"


def test_render_detail_smoke():
    # 各格式详情渲染都应返回可绘制对象, 不抛异常
    from rich.console import Console

    c = Console(width=60, file=open("/dev/null", "w"))
    c.print(
        R.render_detail(
            {"messages": [{"role": "user", "content": "```py\nx=1\n```"}]}, "openai_chat"
        )
    )
    c.print(R.render_detail({"prompt": "p", "chosen": "a", "rejected": "b"}, "dpo"))
    c.print(R.render_detail({"instruction": "i", "input": "x", "output": "o"}, "alpaca"))
    c.print(R.render_detail({"a": 1, "b": {"x": 2}}, "generic"))
