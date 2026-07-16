"""dt view TUI 交互测试 (Textual headless pilot)。"""

import pytest

from dtflow.cli.view.app import ViewApp
from dtflow.cli.view.source import RowSource


class _ListSource(RowSource):
    """内存列表数据源, 用于测试窗口逻辑 (无需真实文件)。"""

    def __init__(self, rows):
        self._rows = rows
        self.total = len(rows)

    def window(self, offset, size):
        return self._rows[max(0, offset) : offset + size]


def _make_app(rows, cap=20000, offset=0, fmt="openai_chat"):
    src = _ListSource(rows)
    return ViewApp(src, src.window(offset, cap), offset, cap, fmt, "t.jsonl")


def _chat_rows(n=30):
    return [
        {
            "messages": [
                {"role": "user", "content": f"q{i}"},
                {"role": "assistant", "content": "a" * (i % 5)},
            ],
            "source": "a" if i % 2 else "b",
        }
        for i in range(n)
    ]


def _chat_app(n=30):
    return _make_app(_chat_rows(n))


@pytest.mark.asyncio
async def test_vim_navigation():
    app = _chat_app(5)
    async with app.run_test() as pilot:
        t = app.query_one("#table")
        await pilot.press("j")
        await pilot.pause()
        assert t.cursor_row == 1
        await pilot.press("k")
        await pilot.pause()
        assert t.cursor_row == 0


@pytest.mark.asyncio
async def test_sort_by_column_name():
    app = _chat_app(5)  # chars = i%5 → 0..4
    async with app.run_test():
        app._apply_sort("chars")  # 升序
        assert app.view_indices[-1] == 4
        app._apply_sort("-chars")  # 反向
        assert app.view_indices[0] == 4
        app._apply_sort("nope")  # 无此列, 不改动不崩溃
        assert app.view_indices[0] == 4


@pytest.mark.asyncio
async def test_resize_step_5pct_and_bounds():
    app = _chat_app(3)
    async with app.run_test() as pilot:
        assert app._split == 13  # 默认表格 65%
        await pilot.press("plus")
        assert app._split == 14  # +5%
        for _ in range(20):
            await pilot.press("plus")
        assert app._split == 16  # 上限 80%
        for _ in range(30):
            await pilot.press("minus")
        assert app._split == 4  # 下限 20%


@pytest.mark.asyncio
async def test_half_scroll_clamps():
    app = _chat_app(30)
    async with app.run_test(size=(80, 24)) as pilot:
        t = app.query_one("#table")
        await pilot.press("d")
        await pilot.pause()
        assert t.cursor_row > 0
        for _ in range(20):
            await pilot.press("d")
        assert t.cursor_row == 29  # 不越界
        for _ in range(20):
            await pilot.press("u")
        assert t.cursor_row == 0


@pytest.mark.asyncio
async def test_search_and_filter_and_reset():
    app = _chat_app(4)
    async with app.run_test() as pilot:
        app._apply_search("q2")
        assert app.view_indices == [2]
        app.action_reset()
        assert app.view_indices == [0, 1, 2, 3]
        app._apply_filter("source=a")
        assert app.view_indices == [1, 3]  # 奇数 idx source=a
        app._apply_filter("bad@@expr")  # 非法表达式不崩溃
        app.action_reset()
        assert len(app.view_indices) == 4
        await pilot.pause()  # flush 详情渲染的延迟回调, 避免 teardown 竞态


@pytest.mark.asyncio
async def test_column_picker_hides_table_and_detail():
    from dtflow.cli.view import render as R
    from dtflow.cli.view.app import ColumnPicker

    rows = [
        {"messages": [{"role": "user", "content": "hi"}], "source": "m", "difficulty": 3}
        for _ in range(3)
    ]
    app = _make_app(rows)
    async with app.run_test() as pilot:
        table = app.query_one("#table")
        assert "source" in app._visible_columns()
        # 折叠 source/difficulty
        app._hidden = {"source", "difficulty"}
        app._rebuild_columns()
        await pilot.pause()
        vis = app._visible_columns()
        assert "source" not in vis and "difficulty" not in vis
        assert len(table.columns) == len(vis)
        # 详情也不含被折叠字段
        import io

        from rich.console import Console

        buf = io.StringIO()
        Console(file=buf, width=60).print(
            R.render_detail(rows[0], "openai_chat", hidden=app._hidden)
        )
        assert "source" not in buf.getvalue() and "difficulty" not in buf.getvalue()

        # picker: 全不选 + 应用 → 至少保留第一列
        app.action_columns()
        await pilot.pause()
        assert isinstance(app.screen, ColumnPicker)
        await pilot.press("n")
        await pilot.press("enter")
        await pilot.pause()
        assert app._visible_columns() == ["#"]


@pytest.mark.asyncio
async def test_detail_scroll_keeps_field_across_samples():
    # 列多时切样本, 详情应停在同一"字段"(绑定字段而非绝对像素Y)
    rows = [{f"f{i:02d}": f"v{s}-{i}" for i in range(20)} for s in range(3)]
    rows[1]["f00"] = "\n".join(f"tall{k}" for k in range(10))  # 让 f00 变高, 使绝对Y错位
    app = _make_app(rows, fmt="generic")
    async with app.run_test(size=(80, 12)) as pilot:
        detail = app.query_one("#detail")
        await pilot.pause()
        # 锚点测量与 Textual 实际渲染高度一致
        assert app._cur_anchors["f19"] + 1 == detail.virtual_size.height
        # 滚到字段 f12
        detail.scroll_to(y=app._cur_anchors["f12"], animate=False)
        await pilot.pause()
        assert app._top_field(app._cur_anchors, detail.scroll_offset.y) == "f12"
        y0 = app._cur_anchors["f12"]
        # 切下一样本: f00 变高 → 同名字段绝对Y改变, 但应仍停在 f12
        app.query_one("#table").move_cursor(row=1)
        await pilot.pause()
        await pilot.pause()
        assert app._cur_anchors["f12"] != y0  # 绝对Y确实变了
        assert app._top_field(app._cur_anchors, detail.scroll_offset.y) == "f12"


@pytest.mark.asyncio
async def test_detail_field_stable_at_bottom_across_samples():
    # 滚到底切样本, 当前字段应保持不变 (字段绑定), 不再因"底部保持"逐样本乱跳
    rows = [{f"f{i:02d}": f"v{s}-{i}" for i in range(20)} for s in range(3)]
    rows[1]["f00"] = "\n".join(f"tall{k}" for k in range(15))  # 各样本高度不同
    app = _make_app(rows, fmt="generic")
    async with app.run_test(size=(80, 12)) as pilot:
        detail = app.query_one("#detail")
        await pilot.pause()
        detail.scroll_end(animate=False)
        await pilot.pause()
        field = app._current_field()  # 滚到底时的顶部可见字段
        assert field is not None
        for r in (1, 2):
            app.query_one("#table").move_cursor(row=r)
            await pilot.pause()
            await pilot.pause()
            assert app._current_field() == field  # 绑定同名字段, 稳定


@pytest.mark.asyncio
async def test_status_shows_current_field_on_scroll():
    import re

    from textual.widgets import Static

    rows = [{f"f{i:02d}": f"v-{i}" for i in range(20)}]
    app = _make_app(rows, fmt="generic")
    async with app.run_test(size=(80, 12)) as pilot:
        detail = app.query_one("#detail")
        await pilot.pause()

        def status_field():
            m = re.search(r"字段:(\S+)", str(app.query_one("#status", Static).renderable))
            return m.group(1) if m else None

        assert status_field() == "f00"  # 首屏顶部字段
        detail.scroll_to(y=app._cur_anchors["f12"], animate=False)
        await pilot.pause()
        assert status_field() == "f12"  # 滚动后随之更新


@pytest.mark.asyncio
async def test_field_nav_reaches_scroll_unreachable_bottom_fields():
    import re

    from textual.widgets import Static

    # 高 viewport + 内容略超 → max_scroll 小, 底部字段挤在末屏, 滚动到不了顶部
    rows = [{f"f{i:02d}": f"v-{i}" for i in range(20)}]
    app = _make_app(rows, fmt="generic")
    async with app.run_test(size=(80, 30)) as pilot:
        detail = app.query_one("#detail")
        await pilot.pause()

        def sf():
            m = re.search(r"字段:(\S+)", str(app.query_one("#status", Static).renderable))
            return m.group(1) if m else None

        # 靠滚动到底也无法让 f19 成为顶部字段
        detail.scroll_end(animate=False)
        await pilot.pause()
        assert app._top_field(app._cur_anchors, detail.scroll_offset.y) != "f19"
        # n 逐字段能精确到达 f19 (绕过滚动像素限制)
        app._goto_field(0)
        await pilot.pause()
        for _ in range(19):
            app.action_next_field()
        await pilot.pause()
        assert sf() == "f19"
        # N 回退一个字段
        app.action_prev_field()
        await pilot.pause()
        assert sf() == "f18"


@pytest.mark.asyncio
async def test_click_detail_selects_field():
    # 真实点击详情字段块 → 该字段块自处理点击并选中 (无坐标换算/测量误差)
    rows = [{f"f{i:02d}": f"v-{i}" for i in range(20)}]
    app = _make_app(rows, fmt="generic")
    async with app.run_test(size=(80, 30)) as pilot:  # 详情区够大, 前几字段可见
        await pilot.pause()
        await pilot.click("#detail-field-1")  # 真实点击第 2 个字段块
        await pilot.pause()
        assert app._current_field() == "f01"
        await pilot.click("#detail-field-2")
        await pilot.pause()
        assert app._current_field() == "f02"


@pytest.mark.asyncio
async def test_yank_and_visual_copy(monkeypatch):
    # y 复制当前样本 JSON; v 多选后 y 复制多条 NDJSON (剪贴板内容正确性)
    import orjson

    from dtflow.cli.view.app import ViewApp

    captured = []
    # 捕获复制内容 (验证我们传的文本); OSC52 序列格式另由 test_clipboard_osc52_wrapping 覆盖
    monkeypatch.setattr(ViewApp, "_copy_clipboard", lambda self, text: captured.append(text))

    rows = [{"id": i, "text": f"样本{i}"} for i in range(6)]
    app = _make_app(rows, fmt="generic")
    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        t = app.query_one("#table")
        # y 复制当前样本 (第 0 行), 中文不转义
        await pilot.press("y")
        await pilot.pause()
        assert orjson.loads(captured[-1]) == rows[0]
        # v 多选 row2..row4, y 复制多条
        t.move_cursor(row=2)
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        assert app._visual_anchor == 2
        t.move_cursor(row=4)
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert [orjson.loads(x) for x in captured[-1].split("\n")] == rows[2:5]
        assert app._visual_anchor is None  # 复制后退出多选
        # v 再按 v 取消
        await pilot.press("v")
        await pilot.pause()
        assert app._visual_anchor is not None
        await pilot.press("v")
        await pilot.pause()
        assert app._visual_anchor is None


def test_clipboard_osc52_wrapping(monkeypatch):
    # OSC52 序列: 裸 / tmux passthrough / screen passthrough (tmux 下须穿透, 否则被拦)
    import base64

    app = _make_app([{"a": 1}], fmt="generic")
    b64 = base64.b64encode("hi".encode()).decode()
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("STY", raising=False)
    assert app._clipboard_osc52("hi") == f"\x1b]52;c;{b64}\a"
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,123,0")
    assert app._clipboard_osc52("hi") == f"\x1bPtmux;\x1b\x1b]52;c;{b64}\a\x1b\\"
    monkeypatch.delenv("TMUX")
    monkeypatch.setenv("STY", "12345.pts-0")
    assert app._clipboard_osc52("hi") == f"\x1bP\x1b]52;c;{b64}\a\x1b\\"


@pytest.mark.asyncio
async def test_zoom_guards_table_navigation():
    app = _chat_app(5)
    async with app.run_test() as pilot:
        t = app.query_one("#table")
        app.action_zoom()
        await pilot.press("j")
        await pilot.pause()
        assert t.cursor_row == 0  # 放大态下 j 不移动表格
        app.action_unzoom()


@pytest.mark.asyncio
async def test_window_paging_and_global_row_number():
    # 50 行, 每窗口 20 行 → 3 个窗口 [0-20)[20-40)[40-50)
    app = _make_app(_chat_rows(50), cap=20)
    async with app.run_test() as pilot:
        t = app.query_one("#table")
        assert app.win_offset == 0
        # 首窗口第一行的 # 列 = 全局行号 1
        assert app._cells(0, app._visible_columns())[0] == "1"
        # 下一窗口
        app.action_next_window()
        await pilot.pause()
        assert app.win_offset == 20
        assert len(app.all_rows) == 20
        assert app._cells(0, app._visible_columns())[0] == "21"  # 全局行号
        assert t.cursor_row == 0
        # 最后一个窗口 (不足一窗)
        app.action_next_window()
        await pilot.pause()
        assert app.win_offset == 40
        assert len(app.all_rows) == 10
        # 再翻到底: 不动
        app.action_next_window()
        assert app.win_offset == 40
        # 往回翻
        app.action_prev_window()
        await pilot.pause()
        assert app.win_offset == 20


@pytest.mark.asyncio
async def test_hash_column_width_fits_max_global_row_no():
    # # 列宽须容纳窗口最大行号, 不能靠采样前 200 行 (否则上万行号被截)
    app = _make_app(_chat_rows(20000), cap=20000)
    async with app.run_test(size=(120, 30)):
        vis = app._visible_columns()
        hash_w = app._column_widths(vis)[vis.index("#")]
        assert hash_w >= len("20000")  # 末行号 5 位
    # 大 offset: 全局行号可达 7 位
    app2 = _make_app(_chat_rows(1000), cap=20000)
    app2.win_offset = 980000
    async with app2.run_test(size=(120, 30)):
        vis = app2._visible_columns()
        hash_w = app2._column_widths(vis)[vis.index("#")]
        assert hash_w >= len(str(980000 + 1000))


@pytest.mark.asyncio
async def test_compressed_col_min_width_and_narrow_exempt():
    # 一个天然仅 2 宽的列 + 一堆宽列 → 触发压缩
    rows = [{"nw": "ab", **{f"c{i}": "x" * 30 for i in range(20)}} for _ in range(5)]
    app = _make_app(rows, fmt="generic")
    async with app.run_test(size=(120, 30)):
        vis = app._visible_columns()
        w = dict(zip(vis, app._column_widths(vis)))
        # 被压的宽文本列下限 8 (不再是 4)
        assert min(w[c] for c in vis if c.startswith("c")) >= 8
        # 天然窄列不被硬撑到 8, 保持自然宽 2
        assert w["nw"] == 2


@pytest.mark.asyncio
async def test_jump_to_line_loads_right_window():
    app = _make_app(_chat_rows(50), cap=20)
    async with app.run_test() as pilot:
        t = app.query_one("#table")
        # 跳到全局第 35 行 → 落在窗口 [34, 54) 的首行
        app._apply_jump("35")
        await pilot.pause()
        assert app.win_offset == 34
        assert app._cells(0, app._visible_columns())[0] == "35"
        # 窗口内跳转只移动光标, 不换窗口
        app._apply_jump("40")
        await pilot.pause()
        assert app.win_offset == 34
        assert t.cursor_row == 5  # 40 - 35
        # 负数从末尾数: -1 = 最后一行 (第 50 行, 在当前窗口 [34,50) 内 → 仅移光标)
        app._apply_jump("-1")
        await pilot.pause()
        assert app.win_offset == 34
        assert t.cursor_row == 15  # 50 - 35
        # -50 = 倒数第 50 行 = 第 1 行 → 换窗口
        app._apply_jump("-50")
        await pilot.pause()
        assert app.win_offset == 0
        assert app._cells(0, app._visible_columns())[0] == "1"
        # 越界与非法输入不崩溃
        app._apply_jump("9999")
        await pilot.pause()
        app._apply_jump("abc")
        await pilot.pause()


@pytest.mark.asyncio
async def test_markup_like_content_does_not_crash():
    # 回归: 单元格/列名含 [/quote] 等伪 markup 时, DataTable 默认 formatter 会
    # Text.from_markup 抛 MarkupError; 现在统一包 Text 直传
    payload = "[url=/article/][/quote][/url] 引用文本 [b]x[/b]"
    rows = [
        {
            "messages": [
                {"role": "user", "content": payload},
                {"role": "assistant", "content": "ok"},
            ],
            "source[/dim]": payload,
        }
        for _ in range(3)
    ]
    app = _make_app(rows)
    async with app.run_test() as pilot:
        await pilot.pause()
        t = app.query_one("#table")
        assert t.row_count == 3
        # 搜索伪 markup 子串也不崩
        app._apply_search("[/quote]")
        await pilot.pause()
        assert t.row_count == 3
