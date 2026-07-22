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
    cells = dict(zip(cols, R.row_cells(0, rows[0], "openai_chat", cols), strict=False))
    assert cells["#"] == "1"  # 1-based
    assert cells["turns"] == "3"
    assert cells["roles"] == "sys→u→a"
    assert cells["first_user"] == "写快排"
    assert cells["chars"] == str(len("sys") + len("写快排") + len("好的"))
    assert cells["source"] == "math"


def test_generic_shows_all_columns():
    # generic/CSV: 不限列数, 十几个字段都要出现 (曾被硬编码截断到 6)
    row = {f"col{i}": i for i in range(14)}
    cols = R.build_columns([row], "generic")
    assert cols[0] == "#"
    assert len([c for c in cols if c.startswith("col")]) == 14


def test_training_format_caps_extra_scalar_columns():
    # 训练格式: 派生列已含主信息, 额外标量元数据列限量
    row = {"messages": [{"role": "user", "content": "x"}], **{f"m{i}": i for i in range(20)}}
    cols = R.build_columns([row], "openai_chat")
    extra = [c for c in cols if c.startswith("m")]
    assert len(extra) == 8


def test_roles_sig_truncates():
    turns = [("user", "")] * 8
    assert R._roles_sig(turns).endswith("…")


def test_multimodal_content_flattened():
    row = {"messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]}
    cells = dict(
        zip(
            R.build_columns([row], "openai_chat"),
            R.row_cells(0, row, "openai_chat", R.build_columns([row], "openai_chat")),
            strict=False,
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


def test_markup_like_content_escaped():
    # 数据含 [/quote] 等伪 markup 不应抛 MarkupError, 且原文保留 (回归: dt view 崩溃)
    from rich.console import Console
    from rich.text import Text

    from dtflow.cli.common import _format_nested, _format_value

    payload = "=/article/ [url=/article/][/quote][/url] 文本 [b]x[/b]"
    lines = _format_nested({"k[/dim]": payload, "msgs": [{"role": "user", "content": payload}]})
    plain = "\n".join(Text.from_markup(ln).plain for ln in lines)  # 不抛 MarkupError
    assert "[/quote]" in plain and "k[/dim]" in plain

    assert "[/quote]" in Text.from_markup(_format_value(payload)).plain

    c = Console(width=60, file=open("/dev/null", "w"))
    c.print(R.render_detail({"field": payload}, "generic"))


def test_split_turns_makes_each_message_a_section():
    # 对话按条分段: n/N 因此能逐条消息走 (整段"对话"作为一个字段等于没有粒度)
    row = {
        "messages": [
            {"role": "user", "content": "写快排"},
            {"role": "assistant", "content": "好的"},
        ],
        "source": "math",
    }
    secs = R.render_detail_sections(row, "openai_chat", split_turns=True)
    names = [n for n, _r, _p in secs]
    assert names == ["msg0", "msg1", "元数据"]
    # 段名不含 role: 切样本靠段名对齐位置, 而不同样本同位置的角色未必相同
    assert "user" not in names[0]
    plains = [p for _n, _r, p in secs]
    assert "写快排" in plains[0] and "[user]" in plains[0]
    assert "好的" in plains[1]
    assert "math" in plains[2]


def test_split_turns_off_keeps_single_conversation_section():
    # 默认不拆: dt head/sample 的静态打印走 render_detail, 不该被拆成一堆分隔块
    row = {"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]}
    secs = R.render_detail_sections(row, "openai_chat")
    assert [n for n, _r, _p in secs] == ["对话"]


def test_highlight_marks_matches_in_detail():
    import re

    from rich.console import Console

    pat = re.compile(re.escape("退款"), re.IGNORECASE)
    row = {"messages": [{"role": "user", "content": "我要退款请处理"}]}
    secs = R.render_detail_sections(row, "openai_chat", split_turns=True, highlight=pat)
    out = Console(width=60, force_terminal=True, color_system="truecolor")
    with out.capture() as cap:
        out.print(secs[0][1])
    assert "\x1b[" in cap.get()  # 命中处带样式转义

    # 无 highlight 时同一段不该有高亮 span
    plain_secs = R.render_detail_sections(row, "openai_chat", split_turns=True)
    hl = [s for s in _iter_texts(plain_secs[0][1]) if s.spans]
    assert not any(R.HIGHLIGHT_STYLE in str(sp.style) for t in hl for sp in t.spans)


def _iter_texts(renderable):
    """从 Group 里递归掏出所有 Text (测试辅助)。"""
    from rich.console import Group
    from rich.text import Text

    if isinstance(renderable, Text):
        yield renderable
    elif isinstance(renderable, Group):
        for r in renderable.renderables:
            yield from _iter_texts(r)


def test_highlight_applies_to_generic_and_dpo():
    import re

    pat = re.compile("KEY")
    dpo = R.render_detail_sections({"chosen": "aKEYb", "rejected": "c"}, "dpo", highlight=pat)
    spans = [sp for t in _iter_texts(dpo[0][1]) for sp in t.spans]
    assert any(R.HIGHLIGHT_STYLE in str(sp.style) for sp in spans)
    gen = R.render_detail_sections({"f": "xKEYy"}, "generic", highlight=pat)
    spans = [sp for t in _iter_texts(gen[0][1]) for sp in t.spans]
    assert any(R.HIGHLIGHT_STYLE in str(sp.style) for sp in spans)


def test_render_detail_output_unchanged_for_head():
    # dt head/sample 复用 render_detail: 对话仍是一整块, 没有逐条消息的分隔线
    from rich.console import Console

    row = {"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]}
    out = Console(width=40)
    with out.capture() as cap:
        out.print(R.render_detail(row, "openai_chat"))
    text = cap.get()
    assert "[user]" in text and "[assistant]" in text
    assert "─" not in text  # 段间 Rule: 只有一段, 不该出现
