"""dt view TUI 交互测试 (Textual headless pilot)。"""

import pytest

from dtflow.cli.view.app import ViewApp


def _chat_app(n=30):
    rows = [
        {
            "messages": [
                {"role": "user", "content": f"q{i}"},
                {"role": "assistant", "content": "a" * (i % 5)},
            ],
            "source": "a" if i % 2 else "b",
        }
        for i in range(n)
    ]
    return ViewApp(rows, "openai_chat", "t.jsonl", False)


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
        c0 = t.cursor_column
        await pilot.press("l")
        await pilot.pause()
        assert t.cursor_column == c0 + 1


@pytest.mark.asyncio
async def test_sort_toggle_on_current_column():
    app = _chat_app(5)
    async with app.run_test() as pilot:
        chars_col = app.columns.index("chars")
        for _ in range(chars_col):
            await pilot.press("l")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        assert app.view_indices[-1] == 4  # 升序: chars 最大在末
        await pilot.press("s")
        await pilot.pause()
        assert app.view_indices[0] == 4  # 降序


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
async def test_zoom_guards_table_navigation():
    app = _chat_app(5)
    async with app.run_test() as pilot:
        t = app.query_one("#table")
        app.action_zoom()
        await pilot.press("j")
        await pilot.pause()
        assert t.cursor_row == 0  # 放大态下 j 不移动表格
        app.action_unzoom()
