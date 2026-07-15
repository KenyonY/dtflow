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
    async with app.run_test():
        app._apply_search("q2")
        assert app.view_indices == [2]
        app.action_reset()
        assert app.view_indices == [0, 1, 2, 3]
        app._apply_filter("source=a")
        assert app.view_indices == [1, 3]  # 奇数 idx source=a
        app._apply_filter("bad@@expr")  # 非法表达式不崩溃
        app.action_reset()
        assert len(app.view_indices) == 4


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
        # 越界与非法输入不崩溃
        app._apply_jump("9999")
        await pilot.pause()
        app._apply_jump("abc")
        await pilot.pause()
