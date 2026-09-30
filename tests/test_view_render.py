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
    tail_cells = dict(
        zip(cols, R.row_cells(0, rows[0], "openai_chat", cols, row_no=-3), strict=False)
    )
    assert tail_cells["#"] == "-3"  # 懒索引尾窗先显示相对行号
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


def test_columns_scan_whole_window_and_include_container_fields():
    rows = [{"early": i} for i in range(60)]
    rows[50].update(late={"nested": 1}, tags=["a", "b"])
    cols = R.build_columns(rows, "generic")
    assert cols == ["#", "early", "late", "tags"]


def test_training_format_keeps_full_catalog_with_compact_default():
    # 训练格式完整收录元数据, 但默认只显示前 8 个；其余可从 c 面板启用。
    row = {"messages": [{"role": "user", "content": "x"}], **{f"m{i}": i for i in range(20)}}
    cols = R.build_columns([row], "openai_chat")
    extra = [c for c in cols if c.startswith("m")]
    visible = R.default_visible_columns(cols, "openai_chat")
    assert len(extra) == 20
    assert [c for c in visible if c.startswith("m")] == [f"m{i}" for i in range(8)]


def test_derived_and_diagnostic_columns_are_not_hidden_or_duplicated():
    row = {
        "messages": [],
        "turns": "real-field-collision",
        **{f"m{i}": i for i in range(8)},
        "_parse_error": "bad",
        "_raw_line": "{broken",
    }
    cols = R.build_columns([row], "openai_chat")
    visible = R.default_visible_columns(cols, "openai_chat")
    assert cols.count("turns") == 1
    assert "_parse_error" in visible and "_raw_line" in visible


def test_roles_sig_truncates():
    turns = [R.Turn("user", "")] * 8
    assert R._roles_sig(turns).endswith("…")


def _agent_row():
    return {
        "messages": [
            {"role": "user", "content": "北京天气"},
            {
                "role": "assistant",
                "content": None,
                "reasoning_content": "先查工具",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city": "北京"}'},
                    },
                    {"id": "call_2", "function": {"name": "search", "arguments": "{bad"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": '{"temp": 22}'},
            {"role": "assistant", "content": "22 度"},
        ]
    }


def test_tool_calls_derived_columns():
    # content=null 的调用消息不再算成 "None"; calls 列列出调用过的函数; 工具返回记 t
    row = _agent_row()
    cols = R.build_columns([row], "openai_chat")
    cells = dict(zip(cols, R.row_cells(0, row, "openai_chat", cols), strict=False))
    assert cells["roles"] == "u→a→t→a"
    assert cells["calls"] == "get_weather,search"
    assert cells["turns"] == "4"
    # chars = 正文 + 思维链 + 函数名 + 参数, 不含 "None"
    expected = (
        len("北京天气")
        + len("先查工具")
        + len("get_weather")
        + len('{"city": "北京"}')
        + len("search")
        + len("{bad")
        + len('{"temp": 22}')
        + len("22 度")
    )
    assert cells["chars"] == str(expected)
    assert "calls" in R.derived_columns("openai_chat")  # 筛选 calls~=get_weather 走派生列


def test_tool_calls_render_detail():
    from rich.console import Console

    row = _agent_row()
    out = Console(width=60)
    with out.capture() as cap:
        out.print(R.render_detail(row, "openai_chat"))
    text = cap.get()
    assert "None" not in text  # 回归: content=null 曾显示为 None
    assert "assistant  → get_weather, search" in text  # 徽章 + 调用的函数名
    assert "(reasoning)" in text and "先查工具" in text
    assert "⚙ get_weather" in text and "call_1" in text
    assert '"city": "北京"' in text  # 合法参数格式化展示
    assert "⚠ arguments 不是合法 JSON" in text  # 坏参数标出来
    assert "tool  ← call_1" in text
    # 纯文本与渲染同源: 函数名/参数可被 * 命中定位
    secs = R.render_detail_sections(row, "openai_chat", split_turns=True)
    assert "get_weather" in secs[1][2] and "{bad" in secs[1][2]
    assert secs[2][2].startswith("[tool ← call_1]")


def test_sharegpt_function_call_and_observation():
    row = {
        "conversations": [
            {"from": "human", "value": "查天气"},
            {
                "from": "function_call",
                "value": '{"name": "get_weather", "arguments": {"city": "上海"}}',
            },
            {"from": "observation", "value": '{"temp": 25}'},
            {"from": "gpt", "value": "25 度"},
        ]
    }
    cols = R.build_columns([row], "sharegpt")
    cells = dict(zip(cols, R.row_cells(0, row, "sharegpt", cols), strict=False))
    assert cells["roles"] == "u→a→t→a"  # 与 openai_chat 一致: 发起调用是 a, 返回是 t
    assert cells["calls"] == "get_weather"
    from rich.console import Console

    out = Console(width=60)
    with out.capture() as cap:
        out.print(R.render_detail(row, "sharegpt"))
    assert "function_call  → get_weather" in cap.get() and '"city": "上海"' in cap.get()


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
    assert " user " in text and " assistant " in text  # 角色徽章
    assert "─" not in text  # 段间 Rule: 只有一段, 不该出现


def test_row_cells_preview_limits():
    # 表格预览上限: 长文本列 160 字, 普通列 120 字; preview=False 不截断
    row = {"messages": [{"role": "user", "content": "x" * 500}], "note": "y" * 500}
    first_user, note = R.row_cells(0, row, "openai_chat", ["first_user", "note"])
    assert first_user == "x" * 160 + "…"
    assert note == "y" * 120 + "…"
    full = R.row_cells(0, row, "openai_chat", ["first_user", "note"], preview=False)
    assert full == ["x" * 500, "y" * 500]


def test_calls_column_does_not_shadow_top_level_tools_field():
    # 顶层 tools 是工具定义的标准字段 (OpenAI/LLaMA-Factory), 派生列不能撞名把它挤掉
    row = {
        "messages": [{"role": "user", "content": "x"}],
        "tools": [{"type": "function", "function": {"name": "get_weather"}}],
    }
    cols = R.build_columns([row], "openai_chat")
    assert "tools" in cols and "calls" in cols
    cells = dict(zip(cols, R.row_cells(0, row, "openai_chat", cols), strict=False))
    assert cells["calls"] == "" and "get_weather" in cells["tools"]


def test_bad_tool_call_entries_are_flagged():
    from rich.console import Console

    def rendered(row, fmt="openai_chat"):
        out = Console(width=60)
        with out.capture() as cap:
            out.print(R.render_detail(row, fmt))
        return cap.get()

    # sharegpt function_call 不是合法 JSON / 没有 name: 不能悄悄当普通文本, 要标红且进 calls
    for value, warn in (
        ("{name: get_weather", "⚠ arguments 不是合法 JSON"),
        ('{"foo": 1}', "⚠ 缺少函数名"),
    ):
        row = {"conversations": [{"from": "function_call", "value": value}]}
        cols = R.build_columns([row], "sharegpt")
        cells = dict(zip(cols, R.row_cells(0, row, "sharegpt", cols), strict=False))
        assert cells["calls"] == "?"
        text = rendered(row, "sharegpt")
        assert warn in text and "⚙ ?" in text

    # arguments/name 为 null: 不显示成 null/None, 标红
    row = {
        "messages": [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "function": {"name": None, "arguments": None}}],
            }
        ]
    }
    text = rendered(row)
    assert "⚙ ?" in text and "⚠ arguments 不是合法 JSON" in text
    assert "None" not in text and "null" not in text


def test_legacy_function_call_field_rendered():
    # 旧版 OpenAI: assistant 带 function_call 单个 dict, 与 tool_calls 同样渲染
    row = {
        "messages": [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": None,
                "function_call": {"name": "get_weather", "arguments": '{"city": "北京"}'},
            },
            {"role": "function", "name": "get_weather", "content": '{"temp": 1}'},
        ]
    }
    cols = R.build_columns([row], "openai_chat")
    cells = dict(zip(cols, R.row_cells(0, row, "openai_chat", cols), strict=False))
    assert cells["calls"] == "get_weather" and cells["roles"] == "u→a→t"
    secs = R.render_detail_sections(row, "openai_chat", split_turns=True)
    assert secs[1][2].startswith("[assistant → get_weather]")


def test_call_id_searchable_on_calling_turn():
    # 搜 call_1 时 * 既能跳到 tool 返回, 也能跳到发起调用的那条 (纯文本与渲染同源)
    secs = R.render_detail_sections(_agent_row(), "openai_chat", split_turns=True)
    assert "call_1" in secs[1][2] and "call_1" in secs[2][2]


def test_sharegpt_function_call_dict_without_name_not_misreported():
    # value 已是 dict (合法 JSON) 只是缺 name: 只报缺函数名, 不该误报"不是合法 JSON"
    row = {"conversations": [{"from": "function_call", "value": {"foo": 1}}]}
    from rich.console import Console

    out = Console(width=60)
    with out.capture() as cap:
        out.print(R.render_detail(row, "sharegpt"))
    text = cap.get()
    assert "⚠ 缺少函数名" in text and "⚠ arguments 不是合法 JSON" not in text
    assert '"foo": 1' in text  # 按 JSON 格式化, 不是 Python repr


def test_roles_text_colors_by_role():
    # roles 列与详情同色: 缩写按角色着色, 箭头暗色, 未知缩写原样
    from dtflow.cli.view.render import roles_text

    text = roles_text("sys→u→a→t→xyz")
    assert text.plain == "sys→u→a→t→xyz"
    styles = {text.plain[s.start : s.end]: str(s.style) for s in text.spans}
    assert styles["u"] == "cyan" and styles["a"] == "green" and styles["t"] == "yellow"
    assert styles["→"] == "dim"
    assert "xyz" not in styles


def test_code_block_background_only_when_given():
    # TUI 传 code_bg 时代码/JSON 块铺底与正文分开; dt head 打印不传, 不铺底 (终端底色未知)
    from rich.syntax import Syntax

    row = {"messages": [{"role": "assistant", "content": "看:\n```python\nx = 1\n```"}]}

    def syntaxes(**kw):
        (_, rend, _), *_ = R.render_detail_sections(row, "openai_chat", split_turns=True, **kw)
        return [r for r in rend.renderables if isinstance(r, Syntax)]

    [plain] = syntaxes()
    assert plain.background_color is None
    [shaded] = syntaxes(code_bg="#2D2D2D")
    assert shaded.background_color == "#2D2D2D"


def test_turn_title_badge_and_char_count():
    # 标题行: 反色徽章只罩角色名, 后接暗色字数 (无正文的纯调用消息不显示字数)
    from dtflow.rowfn import Turn

    title = R._turn_title(Turn(role="user", content="hello"), "bold cyan")
    assert title.plain == " user   5 字"
    assert str(title.spans[0].style) == "bold reverse cyan"
    assert title.plain[title.spans[0].start : title.spans[0].end] == " user "
    call = R._turn_title(Turn(role="assistant", content=""), "bold green")
    assert call.plain == " assistant "
