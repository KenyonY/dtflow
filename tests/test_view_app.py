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

    def iter_all(self, progress_cb=None):
        yield from self._rows
        if progress_cb is not None:
            progress_cb(self.total)

    def rows_at(self, indices):
        return [self._rows[i] for i in indices if 0 <= i < self.total]


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


def _rendered_row(app, row_index):
    """表格某行渲染时的单元格 (行里只存字符串, 样式在渲染时才套上)。"""
    return app.query_one("#table")._get_row_renderables(row_index).cells


def _chat_app(n=30):
    return _make_app(_chat_rows(n))


@pytest.mark.asyncio
async def test_index_column_frozen():
    # # 索引列冻结: 水平滚动查看右侧列时始终可见, 且列重建后仍保持
    app = _chat_app(5)
    async with app.run_test() as pilot:
        t = app.query_one("#table")
        assert t.fixed_columns == 1
        app._rebuild_columns()  # 选列/折叠触发的重建不应丢失冻结
        await pilot.pause()
        assert t.fixed_columns == 1


@pytest.mark.asyncio
async def test_value_filter_select_subset():
    # Excel 式列值勾选: 扫 source 列唯一值 → 只留勾选的值 → 子集 (全局行号)
    from dtflow.cli.view.app import ValueFilterScreen

    app = _chat_app(30)  # source = "a"(奇数idx) / "b"(偶数idx)
    async with app.run_test() as pilot:
        app._start_value_scan("source")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, ValueFilterScreen)
        # 面板列出两个唯一值 a/b
        sl = app.screen.query_one("SelectionList")
        assert sl.option_count == 2
        # 只保留 "a" (取消勾选 b): 应用后异步重算子集
        app.screen.dismiss({"a"})
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == list(range(1, 30, 2))  # 奇数 idx = source a
        assert app._col_value_filters == {"source": {"a"}}
        assert "source" in (app._filter_label or "")


@pytest.mark.asyncio
async def test_value_filter_opens_on_header_click():
    # 点列头 → 弹出该列的值勾选面板 (Excel AutoFilter 触发, cursor_type=row 下也生效)
    from dtflow.cli.view.app import ValueFilterScreen

    app = _chat_app(10)
    async with app.run_test(size=(120, 30)) as pilot:
        t = app.query_one("#table")
        vis = app._visible_columns()
        widths = app._column_widths(vis)
        ci = vis.index("source")
        x = sum(widths[j] + 2 * t.cell_padding for j in range(ci)) + t.cell_padding
        await pilot.click("#table", offset=(x + 1, 1))  # +1/+1 越过表格边框, y=1 表头行
        await pilot.pause(0.3)  # 单击延后 0.15s 开面板 (给双击重命名让路)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, ValueFilterScreen)
        assert app.screen._col == "source"


@pytest.mark.asyncio
async def test_value_filter_high_cardinality_caps_render_only():
    # 高基数列照样弹面板: 列表只渲染前 _MAX_SHOW 项, 但搜索/全选作用于全量值
    from dtflow.cli.view.app import ValueFilterScreen

    rows = [{"messages": [{"role": "user", "content": f"u{i}"}], "id": i} for i in range(50)]
    app = _make_app(rows)
    async with app.run_test() as pilot:
        ValueFilterScreen._MAX_SHOW = 10  # 压低渲染上限触发截断
        try:
            app._start_value_scan("id")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert isinstance(app.screen, ValueFilterScreen)  # 不再拒绝
            sl = app.screen.query_one("SelectionList")
            assert sl.option_count == 10  # 仅渲染前 10 项
            assert app.screen._checked == set()  # 默认全不选
            # 搜索在全量值上过滤: "4" 命中 4/14/24/34/40-49 共 14 个 (含未渲染的低频值)
            app.screen.query_one("#vf-search").value = "4"
            await pilot.pause()
            app.screen.action_close()  # 打字 → Enter: 只保留匹配项
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._subset == [i for i in range(50) if "4" in str(i)]
        finally:
            ValueFilterScreen._MAX_SHOW = 1000


@pytest.mark.asyncio
async def test_value_filter_stacks_with_expr():
    # 表达式约束 + 列值约束叠加: 先 f 筛, 再值筛选, 子集为二者交集
    app = _chat_app(30)
    async with app.run_test() as pilot:
        app._apply_filter("turns(x)>=2")  # 全部 30 条 (每条 2 turns)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app._subset) == 30
        app._start_value_scan("source")
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.screen.dismiss({"b"})  # 偶数 idx
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == list(range(0, 30, 2))
        assert app._wheres and app._col_value_filters == {"source": {"b"}}


@pytest.mark.asyncio
async def test_value_apply_skips_second_scan():
    # 点列头扫一遍值就够了: 勾选确定时直接用扫出来的 值→行号表 拼子集, 不再扫第二遍文件
    from dtflow.cli.view import scan

    app = _chat_app(30)
    async with app.run_test() as pilot:
        app._start_value_scan("source")
        await app.workers.wait_for_complete()
        await pilot.pause()
        calls = []
        orig = scan.scan_rows
        scan.scan_rows = lambda *a, **k: calls.append(1) or orig(*a, **k)
        try:
            app.screen.dismiss({"b"})
            await app.workers.wait_for_complete()
            await pilot.pause()
        finally:
            scan.scan_rows = orig
        assert calls == []  # 一次都没重扫
        assert app._subset == list(range(0, 30, 2))
        assert app._col_value_filters == {"source": {"b"}}


@pytest.mark.asyncio
async def test_refined_subset_equals_full_rescan():
    # 叠加条件走"只扫旧子集"这条路, 结果必须与全量重扫逐位相同
    from dtflow.cli.view import scan

    app = _chat_app(30)
    async with app.run_test() as pilot:
        app._apply_filter("x.source=='a'")  # 奇数 idx, 15 条 = 全量的一半
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._applied_spec is not None
        app._apply_filter("chars(x)>=2")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == scan.scan_rows(app.source, app._applied_spec)
        assert app._subset  # 非空, 否则这条用例是空跑


@pytest.mark.asyncio
async def test_value_filter_mouse_buttons():
    # 全鼠标流程: 点列头呼出 → 点"全不选" → 勾一个 → 点"应用" 按钮 (无需回键盘)
    from dtflow.cli.view.app import ValueFilterScreen

    app = _chat_app(30)  # source a(奇)/b(偶)
    async with app.run_test(size=(120, 30)) as pilot:
        app._start_value_scan("source")
        await app.workers.wait_for_complete()
        await pilot.pause()
        from textual.widgets import Button

        # 四个按钮必须都落在面板框内 (否则被裁看不见, 回归 0.6.10 取消按钮消失的 bug)
        box = app.screen.query_one("#vf-box").region
        for b in app.screen.query(Button):
            assert b.region.x >= box.x and b.region.right <= box.right, f"{b.label} 被裁"
        sl = app.screen.query_one("SelectionList")
        # 点"全选"再点"全不选"按钮 → 清空勾选
        await pilot.click("#vf-all")
        await pilot.pause()
        assert set(sl.selected) == {"a", "b"}
        await pilot.click("#vf-none")
        await pilot.pause()
        assert set(sl.selected) == set()
        # 只勾 a, 点"应用"按钮
        sl.select("a")
        await pilot.pause()
        await pilot.click("#vf-apply")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not isinstance(app.screen, ValueFilterScreen)  # 面板已关
        assert app._subset == list(range(1, 30, 2))  # 仅 source a
        assert app._col_value_filters == {"source": {"a"}}


@pytest.mark.asyncio
async def test_value_filter_cancel_button():
    # 点"取消"按钮 → 关闭且不筛选
    from dtflow.cli.view.app import ValueFilterScreen

    app = _chat_app(10)
    async with app.run_test(size=(120, 30)) as pilot:
        app._start_value_scan("source")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.click("#vf-cancel")
        await pilot.pause()
        assert not isinstance(app.screen, ValueFilterScreen)
        assert app._subset is None and app._col_value_filters == {}


@pytest.mark.asyncio
async def test_value_filter_click_outside_cancels():
    # 点面板内不关闭; 修改选择后点模态背景则按“取消”关闭, 不应用临时选择
    from dtflow.cli.view.app import ValueFilterScreen

    app = _chat_app(10)
    async with app.run_test(size=(120, 30)) as pilot:
        app._start_value_scan("source")
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ValueFilterScreen)

        await pilot.click("#vf-none")
        await pilot.click("#picker-title")
        await pilot.pause()
        assert app.screen is screen  # 卡片内点击仍由原控件正常处理

        box = screen.query_one("#vf-box").region
        outside = next(
            point
            for point in ((0, 0), (app.size.width - 1, app.size.height - 1))
            if point not in box
        )
        await pilot.click(offset=outside)
        await pilot.pause()
        assert app.screen is not screen
        assert app._subset is None and app._col_value_filters == {}


@pytest.mark.asyncio
async def test_value_filter_readd_excluded_value():
    # 关键: 筛掉一个值后再次打开该列, 面板列出全量唯一值(含被去掉的), 可重新勾回
    app = _chat_app(30)
    async with app.run_test() as pilot:
        # 第一次: 只留 a
        app._start_value_scan("source")
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.screen.dismiss({"a"})
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == list(range(1, 30, 2))
        # 列头带 ▾ 标记
        t = app.query_one("#table")
        src_i = app._visible_columns().index("source")
        assert "▾" in str(list(t.columns.values())[src_i].label)
        # 再次打开: 面板仍列出 a、b 两个值 (b 虽被筛掉也在), 回显勾选=仅 a
        app._start_value_scan("source")
        await app.workers.wait_for_complete()
        await pilot.pause()
        sl = app.screen.query_one("SelectionList")
        assert sl.option_count == 2  # a、b 都在, b 可加回
        assert set(sl.selected) == {"a"}  # 回显上次保留集
        # 把 a、b 都勾上 (加回 b) → 全选 = 清除该列筛选 → 回全量
        app.screen.dismiss({"a", "b"})
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset is None
        assert app._col_value_filters == {}
        # ▾ 标记消失
        assert "▾" not in str(list(t.columns.values())[src_i].label)


@pytest.mark.asyncio
async def test_filter_zero_hits_clears_view():
    # 0 命中: 子集空, 视图清空且不崩; reset 恢复全量
    app = _chat_app(20)
    async with app.run_test() as pilot:
        app._apply_filter("x.source=='zzz'")  # 无匹配
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == []
        assert len(app.all_rows) == 0
        assert app.query_one("#table").row_count == 0
        app.action_reset()
        await pilot.pause()
        assert app._subset is None and len(app.all_rows) == 20


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


def _chars(i: int) -> int:
    """_chat_rows 第 i 行的 chars 派生列值 (user 'q{i}' + assistant 'a'*(i%5))。"""
    return len(f"q{i}") + i % 5


@pytest.mark.asyncio
async def test_sort_is_full_scan_and_survives_paging():
    # 排序是全量的: 扫全文件 → 排好序的全局行号序列即浏览序列, 翻窗口不失效
    app = _make_app(_chat_rows(30), cap=10)  # 30 行分 3 个窗口
    async with app.run_test() as pilot:
        app._apply_sort("-chars")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app._subset) == 30  # 排序只重排, 不筛掉任何行
        vals = [_chars(i) for i in app._subset]
        assert vals == sorted(vals, reverse=True)  # 整体有序, 而不只是首窗口内有序
        assert app._sort_label == "chars↓"
        assert app._filter_label is None  # 无筛选 → 状态栏不报"命中 30/30"
        # 翻到第二个窗口: 排序仍在 (旧的"仅当前窗口内排序"翻页即丢)
        app.action_next_window()
        await pilot.pause()
        assert app._sort_label == "chars↓"
        assert app._global_nos == app._subset[10:20]


@pytest.mark.asyncio
async def test_sort_ascending_and_bad_column():
    app = _make_app(_chat_rows(12))
    async with app.run_test() as pilot:
        app._apply_sort("chars")  # 升序
        await app.workers.wait_for_complete()
        await pilot.pause()
        vals = [_chars(i) for i in app._subset]
        assert vals == sorted(vals)
        app._apply_sort("nope")  # 无此列: 不改排序、不启动扫描、不崩
        await pilot.pause()
        assert app._sort_spec == ("chars", False)


@pytest.mark.asyncio
async def test_sort_stacks_with_filter():
    # 排序与筛选共用一条管线: 先筛后排, 两者同时生效
    app = _make_app(_chat_rows(30))
    async with app.run_test() as pilot:
        app._apply_filter("x.source=='a'")  # 奇数 idx
        await app.workers.wait_for_complete()
        await pilot.pause()
        app._apply_sort("-chars")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert all(i % 2 == 1 for i in app._subset)  # 筛选仍在
        vals = [_chars(i) for i in app._subset]
        assert vals == sorted(vals, reverse=True)  # 排序也在
        app.action_reset()
        await pilot.pause()
        assert app._subset is None and app._sort_spec is None


@pytest.mark.asyncio
async def test_resize_step_5pct_and_bounds():
    app = _chat_app(3)
    async with app.run_test() as pilot:
        assert app._split == 65  # 默认表格 65%
        await pilot.press("plus")
        assert app._split == 70  # +5%
        for _ in range(20):
            await pilot.press("plus")
        assert app._split == 80  # 上限 80%
        for _ in range(30):
            await pilot.press("minus")
        assert app._split == 20  # 下限 20%


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
    # 全量搜索/筛选: 扫全文件 (worker 线程) → 命中全局行号聚成 _subset, r 清除回到全量
    app = _chat_app(4)
    async with app.run_test() as pilot:
        app._apply_search("q2")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == [2]  # 全局命中子集
        app.action_reset()
        await pilot.pause()
        assert app._subset is None  # 退出子集, 回到全量
        app._apply_filter("x.source=='a'")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == [1, 3]  # 奇数 idx source=a
        app._apply_filter("bad@@expr")  # 非法表达式不崩溃, 不启动扫描
        await pilot.pause()
        assert app._subset == [1, 3]  # 保持上次子集
        app.action_reset()
        await pilot.pause()
        assert app._subset is None
        assert len(app.all_rows) == 4


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

        # picker: 未手动选过列 → 默认只勾行号列 #; 空勾选应用 → 提示并留在面板
        app.action_columns()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ColumnPicker)
        assert set(screen.query_one("SelectionList").selected) == {"#"}
        await pilot.press("n")
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is screen
        # 勾 # + source 应用 → 之后再打开回显当前可见列
        screen.query_one("SelectionList").select("#")
        screen.query_one("SelectionList").select("source")
        await pilot.press("enter")
        await pilot.pause()
        assert app._visible_columns() == ["#", "source"]
        app.action_columns()
        await pilot.pause()
        assert set(app.screen.query_one("SelectionList").selected) == {"#", "source"}
        await pilot.press("escape")
        await pilot.pause()

        # 鼠标按钮: 全选按钮 + 应用按钮 → 恢复全部列
        app.action_columns()
        await pilot.pause()
        await pilot.click("#cp-all")
        await pilot.pause()
        await pilot.click("#cp-apply")
        await pilot.pause()
        assert set(app._visible_columns()) == set(app.columns)
        # 取消按钮不改变现状
        app.action_columns()
        await pilot.pause()
        await pilot.press("n")  # 试图全不选
        await pilot.click("#cp-cancel")  # 但取消
        await pilot.pause()
        assert set(app._visible_columns()) == set(app.columns)  # 未变


@pytest.mark.asyncio
async def test_detail_scroll_keeps_field_across_samples():
    # 列多时切样本, 详情应停在同一"字段"(绑定字段而非绝对像素Y)
    rows = [{f"f{i:02d}": f"v{s}-{i}" for i in range(20)} for s in range(3)]
    rows[1]["f00"] = "\n".join(f"tall{k}" for k in range(10))  # 让 f00 变高, 使绝对Y错位
    app = _make_app(rows, fmt="generic")
    async with app.run_test(size=(80, 12)) as pilot:
        detail = app.query_one("#detail")
        await pilot.pause()
        # 锚点测量与 Textual 实际渲染高度一致 (末字段 = 顶边分隔线 1 行 + 内容 1 行)
        last = app._field_widgets[-1]
        assert last.outer_size.height == 2
        assert app._cur_anchors["f19"] + last.outer_size.height == detail.virtual_size.height
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
    rows = [{f"f{i:02d}": f"v-{i}" for i in range(20)}]
    app = _make_app(rows, fmt="generic")
    async with app.run_test(size=(80, 12)) as pilot:
        detail = app.query_one("#detail")
        await pilot.pause()

        def status_field():  # 当前字段挂在详情边框右下角
            return detail.border_subtitle

        assert status_field() == "f00"  # 首屏顶部字段
        detail.scroll_to(y=app._cur_anchors["f12"], animate=False)
        await pilot.pause()
        assert status_field() == "f12"  # 滚动后随之更新


@pytest.mark.asyncio
async def test_field_nav_reaches_scroll_unreachable_bottom_fields():
    # 高 viewport + 内容略超 → max_scroll 小, 底部字段挤在末屏, 滚动到不了顶部
    rows = [{f"f{i:02d}": f"v-{i}" for i in range(20)}]
    app = _make_app(rows, fmt="generic")
    async with app.run_test(size=(80, 30)) as pilot:
        detail = app.query_one("#detail")
        await pilot.pause()

        def sf():
            return detail.border_subtitle

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

        # 字段块无 id (见 _FieldStatic), 按 widget 屏幕区域坐标真实点击
        def _click_field(i):
            w = app._field_widgets[i]
            return pilot.click(offset=(w.region.x + 1, w.region.y))

        await _click_field(1)  # 真实点击第 2 个字段块
        await pilot.pause()
        assert app._current_field() == "f01"
        await _click_field(2)
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

    from dtflow.utils import clipboard

    b64 = base64.b64encode("hi".encode()).decode()
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("STY", raising=False)
    assert clipboard.osc52("hi") == f"\x1b]52;c;{b64}\a"
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,123,0")
    assert clipboard.osc52("hi") == f"\x1bPtmux;\x1b\x1b]52;c;{b64}\a\x1b\\"
    monkeypatch.delenv("TMUX")
    monkeypatch.setenv("STY", "12345.pts-0")
    assert clipboard.osc52("hi") == f"\x1bP\x1b]52;c;{b64}\a\x1b\\"


@pytest.mark.asyncio
async def test_enter_key_zooms_from_table():
    # 焦点在表格时按 Enter 要能放大 (DataTable 自带的 enter→select_cursor 不能把键吃掉), Esc 还原
    app = _chat_app(5)
    async with app.run_test() as pilot:
        detail = app.query_one("#detail")
        await pilot.press("enter")
        await pilot.pause()
        assert detail.has_class("zoomed")
        assert app.query_one("#table").has_class("hidden")
        await pilot.press("escape")
        await pilot.pause()
        assert not detail.has_class("zoomed")
        assert app.query_one("#table").has_focus


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
async def test_window_paging_incrementally_discovers_columns():
    rows = [{"first": 1}, {"late": {"nested": True}}]
    app = _make_app(rows, cap=1, fmt="generic")
    async with app.run_test() as pilot:
        table = app.query_one("#table")
        assert app.columns == ["#", "first"]
        app.action_next_window()
        await pilot.pause()
        assert app.columns == ["#", "first", "late"]
        assert app._visible_columns() == app.columns
        assert len(table.columns) == len(app.columns)
        cells = dict(zip(app.columns, app._cells(0, app.columns), strict=False))
        assert "nested" in cells["late"]


def test_training_overflow_is_available_without_hiding_detail():
    row = {"messages": [], **{f"m{i}": i for i in range(10)}}
    app = _make_app([row])
    assert "m9" in app.columns
    assert "m9" not in app._visible_columns()
    assert "m9" in app._auto_hidden
    assert "m9" not in app._hidden  # 自动收起只管表格, 详情仍完整


@pytest.mark.asyncio
async def test_column_picker_can_reveal_auto_hidden_metadata():
    from dtflow.cli.view.app import ColumnPicker

    row = {"messages": [], **{f"m{i}": i for i in range(10)}}
    app = _make_app([row])
    async with app.run_test() as pilot:
        app.action_columns()
        await pilot.pause()
        assert isinstance(app.screen, ColumnPicker)
        picker = app.screen.query_one("SelectionList")
        assert "m9" not in picker.selected
        picker.select("m9")
        app.screen.action_close()
        await pilot.pause()
        assert "m9" in app._visible_columns()
        assert not app._auto_hidden


def test_custom_column_selection_hides_later_discoveries():
    app = _make_app([{"a": 1}], cap=1, fmt="generic")
    app._columns_customized = True
    assert app._merge_columns([{"late": 2}])
    assert "late" in app.columns and "late" in app._hidden
    assert "late" not in app._visible_columns()


@pytest.mark.asyncio
async def test_hash_column_width_fits_max_global_row_no():
    # # 列宽须容纳窗口最大行号, 不能靠采样前 200 行 (否则上万行号被截)
    app = _make_app(_chat_rows(20000), cap=20000)
    async with app.run_test(size=(120, 30)):
        vis = app._visible_columns()
        hash_w = app._column_widths(vis)[vis.index("#")]
        assert hash_w >= len("20000")  # 末行号 5 位
    # 大 offset: 全局行号可达 7 位 (# 列宽取 _global_nos 最大值)
    app2 = _make_app(_chat_rows(1000), cap=20000)
    app2._global_nos = list(range(980000, 980000 + 1000))
    async with app2.run_test(size=(120, 30)):
        vis = app2._visible_columns()
        hash_w = app2._column_widths(vis)[vis.index("#")]
        assert hash_w >= len(str(980000 + 1000))


@pytest.mark.asyncio
@pytest.mark.parametrize("last_no", [1_000_000, 10_000_000, 100_000_000, -100_000_000])
async def test_row_numbers_keep_all_digits_when_columns_are_compressed(last_no):
    rows = [{f"c{i}": "x" * 30 for i in range(12)} for _ in range(3)]
    app = _make_app(rows, fmt="generic")
    app._global_nos = (
        [last_no - 3, last_no - 2, last_no - 1]
        if last_no > 0
        else [last_no, last_no + 1, last_no + 2]
    )
    async with app.run_test(size=(40, 20)) as pilot:
        table = app.query_one("#table")
        column = table.ordered_columns[app._visible_columns().index("#")]
        assert column.width >= len(str(last_no))
        await pilot.resize_terminal(30, 20)
        assert table.ordered_columns[app._visible_columns().index("#")].width >= len(str(last_no))


@pytest.mark.asyncio
async def test_compressed_col_min_width_and_narrow_exempt():
    # 一个天然仅 2 宽的列 + 一堆宽列 → 触发压缩
    long_header = "moderately_long_header"
    rows = [
        {"nw": "ab", long_header: "x" * 30, **{f"c{i}": "x" * 30 for i in range(20)}}
        for _ in range(5)
    ]
    app = _make_app(rows, fmt="generic")
    async with app.run_test(size=(120, 30)):
        vis = app._visible_columns()
        w = dict(zip(vis, app._column_widths(vis), strict=False))
        # 被压的宽文本列下限 8 (不再是 4)
        assert min(w[c] for c in vis if c.startswith("c")) >= 8
        # 天然窄列不被硬撑到 8, 保持自然宽 (2 字列名 + 1 格给表头分隔线)
        assert w["nw"] == 3
        # 长列名在压缩时仍完整显示，不再按统一下限 8 截断
        assert w[long_header] >= len(long_header)


@pytest.mark.asyncio
async def test_vim_horizontal_scroll_moves_four_cells():
    rows = [{f"column_{i}": "x" * 30 for i in range(20)}]
    app = _make_app(rows, fmt="generic")
    async with app.run_test(size=(60, 20)) as pilot:
        table = app.query_one("#table")
        assert table.max_scroll_x >= 4
        await pilot.press("l")
        assert table.scroll_target_x == 4
        await pilot.press("h")
        assert table.scroll_target_x == 0


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
        # 全量搜索伪 markup 子串也不崩 (3 行都含 payload → 命中 3)
        app._apply_search("[/quote]")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert t.row_count == 3


def test_compile_where_derived_vs_field_path():
    # 派生列对应行函数 (chars(x)/turns(x), 原始 int); 其余字段走 x.
    from dtflow.cli.view.scan import compile_where as _compile_where

    row = {
        "messages": [
            {"role": "user", "content": "x" * 3000},
            {"role": "assistant", "content": "y"},
        ],
        "source": "alpaca",
    }
    assert _compile_where("chars(x)>2000")(row) is True  # chars=3001
    assert _compile_where("chars(x)<2000")(row) is False
    assert _compile_where("turns(x)>=2")(row) is True
    assert _compile_where("x.source=='alpaca'")(row) is True
    assert _compile_where("x.source=='other'")(row) is False
    assert _compile_where("len(x.messages)>=2")(row) is True
    assert _compile_where("x.messages[-1].role=='assistant'")(row) is True
    # 缺字段 / 非 dict 行: 不命中而不是炸
    assert _compile_where("x.nope>1")(row) is False
    assert _compile_where("turns(x)>=2")("not a row") is False
    # 语法错误在编译期就抛 ValueError (TUI 靠它提示)
    with pytest.raises(ValueError):
        _compile_where("chars(x) >")


def test_compile_where_and_or_parens():
    from dtflow.cli.view.scan import compile_where as _compile_where

    def mk(nchars, src):
        return {
            "messages": [
                {"role": "user", "content": "x" * nchars},
                {"role": "assistant", "content": ""},
            ],
            "source": src,
        }

    long_a, short_a, long_b = mk(3000, "alpaca"), mk(10, "alpaca"), mk(3000, "android")
    p_and = _compile_where("chars(x)>2000 and x.source=='alpaca'")
    assert (p_and(long_a), p_and(short_a), p_and(long_b)) == (True, False, False)
    p_or = _compile_where("chars(x)>2000 or x.source=='alpaca'")
    assert (p_or(short_a), p_or(long_b)) == (True, True)
    p_mix = _compile_where("(chars(x)<100 or chars(x)>2000) and x.source=='alpaca'")
    assert (p_mix(short_a), p_mix(long_a), p_mix(long_b)) == (True, True, False)


@pytest.mark.asyncio
async def test_global_filter_by_derived_column():
    # 全量按派生列 chars 筛选 (直接用列名): content 长度递增, 只留长样本
    rows = [
        {
            "messages": [
                {"role": "user", "content": "x" * (i * 100)},
                {"role": "assistant", "content": "a"},
            ]
        }
        for i in range(20)
    ]
    app = _make_app(rows, cap=50)
    async with app.run_test() as pilot:
        app._apply_filter("chars(x)>1000")  # chars = i*100 + 1, 见下方 expected
        await app.workers.wait_for_complete()
        await pilot.pause()
        expected = [i for i in range(20) if i * 100 + 1 > 1000]
        assert app._subset == expected


@pytest.mark.asyncio
async def test_global_filter_builds_subset_across_windows():
    # 50 行 cap=20: 全量筛选 source=a (奇数 idx, 25 命中) → 子集跨多窗口, 可分页
    app = _make_app(_chat_rows(50), cap=20)
    async with app.run_test() as pilot:
        app._apply_filter("x.source=='a'")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == list(range(1, 50, 2))  # [1,3,...,49] 共 25
        assert app._seq_total() == 25
        assert app.win_offset == 0
        assert len(app.all_rows) == 20  # 子集首窗口 20 条
        # 首行是全局第 2 行 (idx=1 → 显示行号 2)
        assert app._cells(0, app._visible_columns())[0] == "2"
        # 翻子集下一窗口: 剩 5 条
        app.action_next_window()
        await pilot.pause()
        assert app.win_offset == 20
        assert len(app.all_rows) == 5
        assert app._cells(0, app._visible_columns())[0] == "42"  # subset[20]=41 → 行号 42
        # r 清除子集回到全量
        app.action_reset()
        await pilot.pause()
        assert app._subset is None
        assert app._cells(0, app._visible_columns())[0] == "1"


@pytest.mark.asyncio
async def test_snapshot_numeric_full_and_subset(monkeypatch):
    # 列快照: 全量态 scope=全量; 筛选后 scope=子集, 仅统计命中行。预期从数据实算, 不硬编码。
    from dtflow.cli.view import render as R

    rows = _chat_rows(30)
    chars = [int(R.row_cells(0, r, "openai_chat", ["chars"])[0]) for r in rows]
    app = _make_app(rows)
    msgs = []
    monkeypatch.setattr(type(app), "notify", lambda self, m, **k: msgs.append(str(m)))
    async with app.run_test() as pilot:
        app._apply_snapshot("chars")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert f"全量 n={len(chars)}" in msgs[-1]
        assert f"min={min(chars)}" in msgs[-1] and f"max={max(chars)}" in msgs[-1]
        # 非数值列: 给非空率 + 引导 dt stats
        app._apply_snapshot("roles")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "非数值列" in msgs[-1] and "dt stats" in msgs[-1]
        # 先全量筛选出子集 (source=a → 奇数 idx), 再快照 chars → scope=子集, 仅统计命中行
        app._apply_filter("x.source=='a'")
        await app.workers.wait_for_complete()
        await pilot.pause()
        sub = [c for i, c in enumerate(chars) if i % 2]  # 奇数 idx 的 chars
        app._apply_snapshot("chars")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert f"子集 n={len(sub)}" in msgs[-1] and f"min={min(sub)}" in msgs[-1]


@pytest.mark.asyncio
async def test_rapid_refresh_no_duplicate_ids():
    """同一帧内连续刷新详情不崩 DuplicateIds (issue #1).

    remove_children 是异步卸载, 新旧字段 widget 会短暂共存;
    字段块若带固定 id 会在 mount 时撞 DuplicateIds。
    """
    app = _chat_app(5)
    async with app.run_test() as pilot:
        await pilot.pause()
        # 不 await 布局, 模拟启动时 on_mount 刷新与首个 RowHighlighted 事件背靠背触发
        app._refresh_detail(1)
        app._refresh_detail(2)
        await pilot.pause()
        assert app._field_names()  # 详情正常渲染


# --------------------------------------------------------------------------- #
# 包含筛选: 派生列 first_user 在表达式里是全文 (不是表格里截断的预览)
# --------------------------------------------------------------------------- #
def test_derived_text_column_is_full_text_in_expr():
    from dtflow.cli.view.scan import compile_where as _compile_where

    row = {
        "messages": [
            {"role": "user", "content": "x" * 200 + "尾部关键词"},
            {"role": "assistant", "content": "ok"},
        ],
        "source": "alpaca_zh",
    }
    assert _compile_where("'尾部关键词' in first_user(x)")(row)  # 预览截断外
    assert not _compile_where("'不存在的词' in first_user(x)")(row)
    assert _compile_where("'alpaca' in x.source")(row)
    assert _compile_where("'ok' in x.messages[-1].content")(row)
    assert _compile_where("turns(x)==2 and '尾部' in first_user(x)")(row)
    assert not _compile_where("turns(x)==3 and '尾部' in first_user(x)")(row)
    assert _compile_where("x.source.endswith('zh')")(row)


@pytest.mark.asyncio
async def test_search_matches_beyond_preview_truncation():
    # / 全量搜索也搜全文: 200 字后的词在表格里看不见, 但必须能被搜到
    rows = [{"messages": [{"role": "user", "content": "y" * 200 + f"标记{i}"}]} for i in range(5)]
    app = _make_app(rows)
    async with app.run_test() as pilot:
        app._apply_search("标记3")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == [3]


# --------------------------------------------------------------------------- #
# 值面板搜索框: 上千唯一值时靠打字定位, "全选"= 只保留匹配项
# --------------------------------------------------------------------------- #
def _tag_app(n=30):
    """tag 列取 5 个值: alpaca_zh / alpaca_en / sharegpt / dolly / other。"""
    tags = ["alpaca_zh", "alpaca_en", "sharegpt", "dolly", "other"]
    rows = [
        {"messages": [{"role": "user", "content": f"q{i}"}], "tag": tags[i % 5]} for i in range(n)
    ]
    return _make_app(rows)


@pytest.mark.asyncio
async def test_value_filter_search_box_filters_options():
    app = _tag_app(30)
    async with app.run_test(size=(120, 30)) as pilot:
        app._start_value_scan("tag")
        await app.workers.wait_for_complete()
        await pilot.pause()
        sl = app.screen.query_one("SelectionList")
        assert sl.option_count == 5
        # 输入子串 → 列表只剩匹配项 (大小写不敏感)
        app.screen.query_one("#vf-search").value = "ALPACA"
        await pilot.pause()
        assert sl.option_count == 2
        shown = {sl.get_option_at_index(i).value for i in range(sl.option_count)}
        assert shown == {"alpaca_zh", "alpaca_en"}
        # 清空搜索词 → 恢复全部
        app.screen.query_one("#vf-search").value = ""
        await pilot.pause()
        assert sl.option_count == 5


@pytest.mark.asyncio
async def test_value_filter_search_then_apply_keeps_only_matches():
    # 用户诉求"某列包含某子串": 打字 → 应用, 两步拿到子集 (无需先全不选再全选)
    app = _tag_app(30)
    async with app.run_test(size=(120, 30)) as pilot:
        app._start_value_scan("tag")
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.screen.query_one("#vf-search").value = "alpaca"
        await pilot.pause()
        await pilot.click("#vf-apply")  # 有搜索词: 应用 = 只保留 勾选∩匹配
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._col_value_filters == {"tag": {"alpaca_zh", "alpaca_en"}}
        assert app._subset == [i for i in range(30) if i % 5 in (0, 1)]


@pytest.mark.asyncio
async def test_value_filter_search_check_one_then_apply():
    # 有搜索词时勾一个匹配项再应用 → 只保留勾选的匹配项 (视野外勾选不算数)
    app = _tag_app(30)
    async with app.run_test(size=(120, 30)) as pilot:
        app._start_value_scan("tag")
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.screen.action_all()  # 视野外也有勾选: dolly 等不应混进结果
        app.screen.query_one("#vf-search").value = "alpaca"
        await pilot.pause()
        await pilot.click("#vf-none")
        await pilot.pause()
        app.screen.query_one("SelectionList").select("alpaca_zh")
        await pilot.pause()
        await pilot.click("#vf-apply")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._col_value_filters == {"tag": {"alpaca_zh"}}


@pytest.mark.asyncio
async def test_value_filter_selection_survives_search_change():
    # 勾选状态的真值是 _checked, 不是列表: 被搜索词过滤掉的项不能丢勾选
    app = _tag_app(30)
    async with app.run_test(size=(120, 30)) as pilot:
        app._start_value_scan("tag")
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen, sl = app.screen, app.screen.query_one("SelectionList")
        await pilot.click("#vf-none")  # 从空集开始
        await pilot.pause()
        # 搜 dolly 勾上
        screen.query_one("#vf-search").value = "dolly"
        await pilot.pause()
        sl.select("dolly")
        await pilot.pause()
        # 换搜索词: dolly 不在列表里了, 但勾选必须还在
        screen.query_one("#vf-search").value = "sharegpt"
        await pilot.pause()
        assert screen._checked == {"dolly"}
        sl.select("sharegpt")
        await pilot.pause()
        # 跨搜索累积后, 清空搜索词回到全量视野再应用 (带词应用只保留匹配项)
        screen.query_one("#vf-search").value = ""
        await pilot.pause()
        await pilot.click("#vf-apply")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._col_value_filters == {"tag": {"dolly", "sharegpt"}}


@pytest.mark.asyncio
async def test_value_filter_search_deselect_only_matches():
    # 有搜索词时 "全不选" 只取消匹配项, 不碰其他勾选
    app = _tag_app(30)
    async with app.run_test(size=(120, 30)) as pilot:
        app._start_value_scan("tag")
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen = app.screen
        screen.action_all()
        screen.query_one("#vf-search").value = "alpaca"
        await pilot.pause()
        await pilot.click("#vf-none")  # 只去掉 alpaca_*
        await pilot.pause()
        assert screen._checked == {"sharegpt", "dolly", "other"}


@pytest.mark.asyncio
async def test_value_filter_default_unchecked_and_empty_apply_stays_open():
    # 未筛过的列默认全不选; 空勾选直接应用 → 提示并留在面板 (关掉会丢刚扫完的值表)
    from dtflow.cli.view.app import ValueFilterScreen

    app = _tag_app(30)
    async with app.run_test(size=(120, 30)) as pilot:
        app._start_value_scan("tag")
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen = app.screen
        assert set(screen.query_one("SelectionList").selected) == set()
        await pilot.click("#vf-apply")
        await pilot.pause()
        assert app.screen is screen and isinstance(screen, ValueFilterScreen)
        # 搜索词 0 命中时应用同样留在面板
        screen.query_one("#vf-search").value = "zzz"
        await pilot.pause()
        await pilot.click("#vf-apply")
        await pilot.pause()
        assert app.screen is screen
        assert app._subset is None and app._col_value_filters == {}


def _assert_panel_fits(screen, box_id, size):
    """面板整体在屏内, 且可见按钮不越出面板 (溢出时最先被裁的就是按钮行)。"""
    from textual.widgets import Button

    box = screen.query_one(box_id).region
    assert box.bottom <= size[1] and box.right <= size[0], f"{box_id} 溢出屏幕 {box}"
    for b in screen.query(Button):
        if not b.display:  # 窄屏下 全选/全不选 会被主动隐藏, 键盘 a/n 仍可用
            continue
        assert b.region.bottom <= box.bottom, f"{b.label} 纵向被裁"
        assert b.region.right <= box.right, f"{b.label} 横向被裁"


# 支持区间的下沿 (屏高 11 / 屏宽 40) 也要覆盖: 边界只测通过侧等于没测边界
@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(110, 40), (100, 24), (100, 16), (80, 14), (80, 12), (40, 24)])
async def test_panels_fit_screen_on_short_terminals(size):
    app = _tag_app(40)
    async with app.run_test(size=size) as pilot:
        app._start_value_scan("tag")
        await app.workers.wait_for_complete()
        await pilot.pause()
        _assert_panel_fits(app.screen, "#vf-box", size)
        app.screen.dismiss(None)
        await pilot.pause()
        app.action_columns()  # 列选择面板同样的结构, 同样不能裁
        await pilot.pause()
        _assert_panel_fits(app.screen, "#picker-box", size)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(120, 40), (120, 30), (100, 24), (80, 14)])
async def test_help_screen_fits_and_scrolls(size):
    """帮助文本只会越加越长: 超屏时必须可滚动, 不能把末尾几行连边框一起裁掉。"""
    from textual.containers import VerticalScroll

    app = _chat_app(5)
    async with app.run_test(size=size) as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        box = app.screen.query_one("#help-box", VerticalScroll)
        assert box.region.bottom <= size[1] and box.region.right <= size[0]
        # 装不下时靠滚动而非裁剪; 30 行终端已经装不下当前帮助
        if size[1] < 34:
            assert box.max_scroll_y > 0


def test_expr_contains_is_case_sensitive_unless_lowered():
    """表达式 in 是精确子串; 要不分大小写显式 .lower() (与 / 搜索的不分大小写不同, 文档注明)。"""
    from dtflow.cli.view.scan import compile_where as _compile_where

    row = {"messages": [{"role": "user", "content": "A" * 100 + "TAIL_Key"}], "source": "Alpaca_ZH"}
    assert _compile_where("'TAIL_Key' in first_user(x)")(row)
    assert not _compile_where("'tail_key' in first_user(x)")(row)
    assert _compile_where("'tail_key' in first_user(x).lower()")(row)
    assert _compile_where("'alpaca' in x.source.lower()")(row)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(120, 30), (40, 24)])
async def test_both_pickers_hint_mentions_keys(size):
    """两个勾选面板的提示必须讲按键: 窄屏下 全选/全不选 按钮会被隐藏, 只讲按钮等于没讲。"""
    from textual.widgets import Static

    from dtflow.cli.view.app import _PICK_HINT

    assert "a/n" in _PICK_HINT
    app = _tag_app(30)
    async with app.run_test(size=size) as pilot:
        app.action_columns()  # 列选择面板
        await pilot.pause()
        assert _PICK_HINT in str(app.screen.query_one("#picker-hint", Static).render())
        app.screen.dismiss(None)
        await pilot.pause()
        app._start_value_scan("tag")  # 值筛选面板: 无搜索词时同一句
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert _PICK_HINT in str(app.screen.query_one("#picker-hint", Static).render())
        app.screen.query_one("#vf-search").value = "alpaca"  # 有搜索词时改讲应用的新语义
        await pilot.pause()
        assert "应用" in str(app.screen.query_one("#picker-hint", Static).render())


# ---------------------------------------------------------------------- #
# 约束叠加: 搜索与 where 各占独立槽位, 多条 where 之间是 AND
# ---------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_multiple_filters_stack_with_and():
    # 连按两次 f 追加条件而非覆盖; 需要括号语义时就靠"拆成多条"表达
    app = _make_app(_chat_rows(30))
    async with app.run_test() as pilot:
        app._apply_filter("x.source=='a'")  # 奇数 idx
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == list(range(1, 30, 2))
        app._apply_filter("chars(x)>=6")  # 再叠一条
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app._wheres) == 2
        assert app._subset == [i for i in range(1, 30, 2) if _chars(i) >= 6]


@pytest.mark.asyncio
async def test_search_and_filter_do_not_overwrite_each_other():
    """回归: 搜索与 f 曾共用一个槽位, 先 f 再 / 会静默丢掉 f 的条件 (README 却说可叠加)。"""
    app = _make_app(_chat_rows(30))
    async with app.run_test() as pilot:
        app._apply_filter("x.source=='a'")  # 奇数 idx
        await app.workers.wait_for_complete()
        await pilot.pause()
        app._apply_search("q1")  # 含 q1 的: 1, 10-19
        await app.workers.wait_for_complete()
        await pilot.pause()
        expected = [i for i in range(30) if i % 2 == 1 and "q1" in f"q{i}"]
        assert app._subset == expected  # 两个约束同时生效
        assert app._wheres and app._search_re is not None


@pytest.mark.asyncio
async def test_search_regex_prefix_and_bad_regex():
    app = _make_app(_chat_rows(20))
    async with app.run_test() as pilot:
        app._apply_search(r"re:q1\d")  # q10..q19
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == list(range(10, 20))
        app._apply_search("re:[")  # 非法正则: 提示但不崩、不改子集
        await pilot.pause()
        assert app._subset == list(range(10, 20))


@pytest.mark.asyncio
async def test_search_highlights_cells_and_detail():
    from dtflow.cli.view.render import HIGHLIGHT_STYLE

    app = _make_app(_chat_rows(6))
    async with app.run_test() as pilot:
        app._apply_search("q3")
        await app.workers.wait_for_complete()
        await pilot.pause()
        # 表格单元格: first_user 列命中处带黄底
        cell = _rendered_row(app, 0)[app._visible_columns().index("first_user")]
        assert any(HIGHLIGHT_STYLE in str(sp.style) for sp in cell.spans)


@pytest.mark.asyncio
async def test_next_match_jumps_to_matching_message():
    # 长对话里 * 直奔命中那条消息 (n/N 是逐条走, * 只在含命中的段间跳)
    rows = [
        {
            "messages": [
                {"role": "user", "content": "开头"},
                {"role": "assistant", "content": "中间"},
                {"role": "user", "content": "关键词在这"},
            ]
        }
    ]
    app = _make_app(rows)
    async with app.run_test() as pilot:
        app._apply_search("关键词")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._field_i == 0
        app.action_next_match()
        await pilot.pause()
        assert app._field_i == 2  # msg2
        app.action_next_match()  # 绕一圈回到唯一命中
        await pilot.pause()
        assert app._field_i == 2


@pytest.mark.asyncio
async def test_next_match_without_search_is_noop():
    app = _chat_app(5)
    async with app.run_test() as pilot:
        app.action_next_match()  # 未搜索: 提示而已, 不崩
        await pilot.pause()
        assert app._field_i == 0


# ---------------------------------------------------------------------- #
# 导出: 筛出来的子集必须能落盘 (剪贴板 OSC52 装不下几千条)
# ---------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_export_subset_to_jsonl_with_lineage(tmp_path):
    import orjson

    app = _make_app(_chat_rows(30))
    app.filepath = str(tmp_path / "src.jsonl")
    out = tmp_path / "out.jsonl"
    async with app.run_test() as pilot:
        app._apply_filter("x.source=='a'")  # 奇数 idx, 15 条
        await app.workers.wait_for_complete()
        await pilot.pause()
        app._apply_export(str(out))
        await app.workers.wait_for_complete()
        await pilot.pause()
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 15
        assert [orjson.loads(x)["source"] for x in lines] == ["a"] * 15
        # 血缘 sidecar: 条件与可复现命令都记下了
        rec = orjson.loads((tmp_path / "out.jsonl.lineage.json").read_bytes())
        params = rec["operations"][0]["params"]
        assert params["where"] == ["x.source=='a'"]
        assert "--where" in params["command"]
        assert rec["operations"][0]["output_count"] == 15


@pytest.mark.asyncio
async def test_export_visual_selection(tmp_path):
    out = tmp_path / "sel.jsonl"
    app = _make_app(_chat_rows(10))
    async with app.run_test() as pilot:
        app._visual_anchor = 2
        app.query_one("#table").move_cursor(row=5)
        await pilot.pause()
        assert app._export_scope() == ("selection", 4)
        app._apply_export(str(out))
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(out.read_text().strip().split("\n")) == 4


@pytest.mark.asyncio
async def test_export_refuses_to_overwrite(tmp_path):
    out = tmp_path / "exists.jsonl"
    out.write_text("keep\n")
    app = _chat_app(5)
    async with app.run_test() as pilot:
        app._apply_export(str(out))
        await pilot.pause()
        assert out.read_text() == "keep\n"  # 原文件没被动


@pytest.mark.asyncio
async def test_export_non_jsonl_format(tmp_path):
    out = tmp_path / "out.json"
    app = _make_app(_chat_rows(6))
    async with app.run_test() as pilot:
        app._apply_export(str(out))
        await app.workers.wait_for_complete()
        await pilot.pause()
        import orjson

        assert len(orjson.loads(out.read_bytes())) == 6


# ---------------------------------------------------------------------- #
# 可复现命令 + 启动参数 (同一件事: C 生成的命令必须能被 dt view 吃回去)
# ---------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_build_command_translates_all_constraints():
    app = _make_app(_chat_rows(30))
    app.filepath = "data.jsonl"
    async with app.run_test() as pilot:
        app._apply_filter("turns(x)>=2")
        await app.workers.wait_for_complete()
        app._search_text, app._search_re = "报错", __import__("re").compile("报错")
        app._col_value_filters = {"source": {"a", "b"}}
        app._sort_spec = ("chars", True)
        await pilot.pause()
        cmd, skipped = app._build_command()
        assert not skipped
        # 单列多值 → 一条 where 内 in (...); 多条 where 之间 AND
        # 值经 shlex.quote, 含 > 或空格的会带引号 —— 粘回终端才不会被 shell 当重定向
        assert "--where='turns(x)>=2'" in cmd
        assert (
            "--where='str(x.get('\"'\"'source'\"'\"')) in ('\"'\"'a'\"'\"', '\"'\"'b'\"'\"',)'"
            in cmd
        )
        assert "--search='报错'" in cmd and "--sort=-chars" in cmd
        # 翻译出的表达式本身必须可编译 (吃回去不报错)
        from dtflow.cli.view.scan import compile_where as _cw

        pred = _cw(app._value_filter_expr("source", {"a", "b"}))
        assert pred({"source": "a"}) and not pred({"source": "c"})


@pytest.mark.asyncio
async def test_bare_derived_name_is_rejected_with_hint():
    """老语法 turns>=2 (裸派生列名) 编译期报错并提示 turns(x), 条件不入栈。"""
    app = _make_app(_chat_rows(5))
    async with app.run_test() as pilot:
        notes = []
        app.notify = lambda msg, **kw: notes.append((msg, kw.get("severity")))
        app._apply_filter("turns>=2")
        await pilot.pause()
        assert app._wheres == []
        assert notes and notes[0][1] == "error" and "turns(x)" in notes[0][0]


@pytest.mark.asyncio
async def test_build_pipeline_command_translates_to_dt_filter_and_sort():
    """P: 同一套条件写成 dt filter … | dt sort …, 且翻译出的表达式能被 dt filter 编译。"""
    import shlex

    from dtflow.expr import compile_where as _plain

    app = _make_app(_chat_rows(30))
    app.filepath = "data.jsonl"
    async with app.run_test() as pilot:
        assert app._build_pipeline_command()[0] is None  # 没有任何条件: 无可翻译
        app._apply_filter("turns(x)>=2")
        await app.workers.wait_for_complete()
        app._search_text, app._search_re = "报错", __import__("re").compile("报错")
        app._col_value_filters = {"source": {"a", "b"}}
        app._sort_spec = ("chars", True)
        await pilot.pause()
        cmd, skipped = app._build_pipeline_command()
        assert not skipped
        head, tail = cmd.split(" | ")
        assert head.startswith("dt filter data.jsonl ")
        expr = shlex.split(head)[3]
        assert expr == (
            "(turns(x)>=2) and (str(x.get('source')) in ('a', 'b',)) and (search(x, '报错'))"
        )
        assert tail == "dt sort - --by 'chars(x)' --desc"
        pred = _plain(expr)
        row = {
            "messages": [
                {"role": "user", "content": "报错了"},
                {"role": "assistant", "content": "ok"},
            ],
            "source": "a",
        }
        assert pred(row) and not pred({**row, "source": "c"})
        # 只排序: dt sort 直接吃文件; 按行号排序没有表达式
        app._wheres, app._search_text, app._col_value_filters = [], None, {}
        app._sort_spec = ("id", False)
        assert app._build_pipeline_command() == (
            "dt sort data.jsonl --by 'x.get('\"'\"'id'\"'\"')'",
            [],
        )
        app._sort_spec = ("#", False)
        cmd, skipped = app._build_pipeline_command()
        assert cmd is None and skipped
    # stdin 模式没有可复现的输入
    app.filepath = None
    assert app._build_pipeline_command()[0] is None


def test_value_filter_expr_by_column_type():
    # 值筛选比的是单元格字符串: 数值派生列比数, has_input 比真值, 真实字段按 str() 比, 空值单独表达
    app = _chat_app(3)
    from dtflow.cli.view.scan import compile_where as _cw

    assert app._value_filter_expr("turns", {"2", "3"}) == "turns(x) in (2, 3,)"
    assert (
        app._value_filter_expr("calls", {"get_weather", ""}) == "calls(x) in ('', 'get_weather',)"
    )
    e = app._value_filter_expr("id", {"5", ""})
    p = _cw(e)
    assert p({"id": 5}) and p({"id": None}) and p({}) and not p({"id": 6})
    app.fmt = "alpaca"
    assert app._value_filter_expr("has_input", {"✓"}) == "bool(x.get('input'))"
    assert app._value_filter_expr("has_input", {""}) == "not bool(x.get('input'))"
    assert (
        app._value_filter_expr("out_chars", {"3"})
        == "len(x.get('output') or x.get('response') or '') in (3,)"
    )
    # 翻译出的表达式必须能被 dt filter 吃 (与 view 同一套语言)
    from dtflow.expr import compile_where as _plain

    assert _plain(app._value_filter_expr("out_chars", {"3"}))({"output": "abc"})
    assert not _plain(app._value_filter_expr("has_input", {""}))({"input": "x"})


@pytest.mark.asyncio
async def test_build_command_skips_unsafe_values():
    # 值被截断 (含 …) → 原值已不可知, 如实说明而不是生成错命令; 含引号/运算符的值 repr 能表达
    app = _chat_app(5)
    app.filepath = "d.jsonl"
    async with app.run_test():
        app._col_value_filters = {"source": {"abc…"}}
        cmd, skipped = app._build_command()
        assert "source" not in cmd and skipped
        app._col_value_filters = {"source": {"a=b 'q'"}}
        cmd, skipped = app._build_command()
        assert not skipped and "--where" in cmd


@pytest.mark.asyncio
async def test_build_command_none_for_stdin():
    app = _chat_app(5)  # filepath 为 None = 管道模式
    async with app.run_test():
        cmd, skipped = app._build_command()
        assert cmd is None and skipped


@pytest.mark.asyncio
async def test_startup_constraints_apply():
    # --where/--search/--sort 走的是和 TUI 内完全相同的扫描管线
    rows = _chat_rows(30)
    src = _ListSource(rows)
    app = ViewApp(
        src,
        src.window(0, 20000),
        0,
        20000,
        "openai_chat",
        "t.jsonl",
        where=["x.source=='a'"],
        sort="-chars",
    )
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert all(i % 2 == 1 for i in app._subset)
        vals = [_chars(i) for i in app._subset]
        assert vals == sorted(vals, reverse=True)
        assert app._sort_label == "chars↓"


@pytest.mark.asyncio
async def test_startup_bad_where_does_not_crash():
    rows = _chat_rows(10)
    src = _ListSource(rows)
    app = ViewApp(src, src.window(0, 100), 0, 100, "openai_chat", "t.jsonl", where=["bad@@expr"])
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._wheres == []  # 非法条件不入约束


@pytest.mark.asyncio
async def test_search_covers_whole_record_not_just_columns():
    """/ 必须搜整条记录: 表格列只有派生摘要 (first_user = 第一条用户消息),
    只搜列会把 assistant 回复和后续轮次整个漏掉 —— 而那正是最常要找的地方。"""
    rows = [
        {
            "messages": [
                {"role": "user", "content": "开头"},
                {"role": "assistant", "content": "藏在回复里的词"},
            ]
        },
        {"messages": [{"role": "user", "content": "无关"}]},
    ]
    app = _make_app(rows)
    async with app.run_test() as pilot:
        app._apply_search("藏在回复里")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == [0]


@pytest.mark.asyncio
async def test_search_scope_independent_of_hidden_columns():
    # 折叠一列不该悄悄改变搜索范围
    app = _make_app(_chat_rows(10))
    async with app.run_test() as pilot:
        app._hidden = {"source"}
        app._apply_search("q7")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == [7]


@pytest.mark.asyncio
async def test_navigation_survives_late_render_callback():
    """回归: 详情渲染的收尾回调比按键晚一帧, 曾把刚按下的 * / n 静默撤销回原字段。"""
    rows = [
        {
            "messages": [
                {"role": "user", "content": "开头"},
                {"role": "assistant", "content": "命中在这"},
            ]
        }
    ]
    app = _make_app(rows)
    async with app.run_test() as pilot:
        app._apply_search("命中")
        await app.workers.wait_for_complete()
        await pilot.pause()  # 只等一帧: 渲染回调可能还在队列里
        app.action_next_match()
        await pilot.pause()
        await pilot.pause()  # 迟到的回调在这里落地, 不该覆盖上面的跳转
        assert app._current_field() == "msg1"


# ---------------------------------------------------------------------- #
# 扫描进行中的一致性: 屏幕 / 约束模型 / C 命令 / 血缘 四者必须描述同一个视图
# ---------------------------------------------------------------------- #
class _SlowSource(RowSource):
    """每行 sleep 一下, 制造"扫描进行中"的时间窗 (真实大文件就是这个体感)。"""

    def __init__(self, rows, delay=0.002):
        self._rows, self.total, self._d = rows, len(rows), delay

    def window(self, offset, size):
        return self._rows[max(0, offset) : offset + size]

    def iter_all(self, progress_cb=None):
        import time

        for r in self._rows:
            time.sleep(self._d)
            yield r

    def rows_at(self, indices):
        return [self._rows[i] for i in indices if 0 <= i < self.total]


def _slow_app(n=300):
    rows = [{"messages": [{"role": "user", "content": f"q{i}"}], "id": i} for i in range(n)]
    src = _SlowSource(rows)
    return ViewApp(src, src.window(0, n), 0, n, "openai_chat", "t.jsonl", filepath="t.jsonl")


@pytest.mark.asyncio
async def test_filter_during_scan_is_refused_not_half_applied():
    """回归: 扫描中改约束曾"先改状态, 再静默 return" —— 屏幕停在旧子集, 而 C 命令和
    导出血缘却在描述新条件, 复现出来的行数与屏幕对不上。宁可拒绝, 不可半改。"""
    app = _slow_app()
    async with app.run_test() as pilot:
        app._apply_filter("x.id<100")
        await pilot.pause()
        assert app._scan_cancel is not None  # 扫描确实在跑
        app._apply_filter("x.id<5")  # 扫描中的第二条: 应被拒绝
        assert app._wheres == ["x.id<100"]
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app._subset) == 100
        cmd, _ = app._build_command()
        assert "id<5" not in cmd  # 命令不描述未生效的条件


@pytest.mark.asyncio
async def test_sort_during_scan_is_refused():
    app = _slow_app()
    async with app.run_test() as pilot:
        app._apply_filter("x.id<100")
        await pilot.pause()
        app._apply_sort("-id")
        assert app._sort_spec is None  # 状态栏不会声称"已排序"而顺序纹丝不动
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._sort_label is None


@pytest.mark.asyncio
async def test_reset_during_scan_is_not_revived_by_late_result():
    """r 在扫描中必须有效 (它正是"不想等了"的出口), 且迟到的结果不得把筛选复活。"""
    app = _slow_app()
    async with app.run_test() as pilot:
        app._apply_filter("x.id<100")
        await pilot.pause()
        app.action_reset()
        await app.workers.wait_for_complete()
        for _ in range(5):
            await pilot.pause()  # 让迟到的完成回调有机会落地
        assert app._subset is None and app._filter_label is None and app._wheres == []
        assert app._scan_cancel is None  # 槽位已释放, 不会把后续操作卡死
        app._apply_filter("x.id<7")  # 重置后仍可正常使用
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == list(range(7))


@pytest.mark.asyncio
async def test_sort_by_index_column():
    """回归: 按 # 排序曾被接受、扫全文件、报告成功, 实际全部同键 → 顺序纹丝不动。
    # 是"第几行"这一事实, 不在行数据里, 排序键必须用扫描时的全局行号。"""
    app = _make_app(_chat_rows(30))
    async with app.run_test() as pilot:
        app._apply_sort("-#")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == list(range(29, -1, -1))
        app._apply_sort("#")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == list(range(30))


# ---------------------------------------------------------------------- #
# 约束的提交时机: 改约束只是提案, 扫描结果落地才算数 —— 取消/失败必须退回原状
# ---------------------------------------------------------------------- #
async def _cancel_scan(app, pilot, keys):
    """按 keys 发起一次全量扫描, 确认它在跑, 然后按 Esc 取消并等落定。"""
    for k in keys:
        await pilot.press(k)
    await pilot.pause()
    assert app._scan_cancel is not None, "扫描应在进行中"
    await pilot.press("escape")
    await app.workers.wait_for_complete()
    for _ in range(4):
        await pilot.pause()


@pytest.mark.asyncio
async def test_cancelled_filter_leaves_no_trace(tmp_path):
    """回归: Esc 取消扫描曾只停 worker 不退条件 —— 屏幕是全量, 约束模型里却留着被取消的
    条件, 于是 C 命令和导出血缘都在描述另一个视图。取消就该是"什么都没发生"。"""
    app = _slow_app()
    async with app.run_test() as pilot:
        await _cancel_scan(app, pilot, ["f", *"x.id<100", "enter"])
        assert app._wheres == [] and app._subset is None
        cmd, _ = app._build_command()
        assert "x.id<100" not in cmd
        out = tmp_path / "o.jsonl"
        app._apply_export(str(out))
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(out.read_text().strip().split("\n")) == 300  # 导出的是屏幕上的全量
        import orjson

        rec = orjson.loads((tmp_path / "o.jsonl.lineage.json").read_bytes())
        assert rec["operations"][0]["params"]["where"] == []  # 血缘不记未生效的条件


@pytest.mark.asyncio
async def test_cancelled_sort_does_not_claim_sorted():
    app = _slow_app()
    async with app.run_test() as pilot:
        await _cancel_scan(app, pilot, ["s", *"-id", "enter"])
        assert app._sort_spec is None and app._sort_label is None


@pytest.mark.asyncio
async def test_cancelled_condition_is_not_silently_revived():
    """取消掉的条件不得在下一次操作时被静默 AND 进去。"""
    app = _slow_app()
    async with app.run_test() as pilot:
        await _cancel_scan(app, pilot, ["f", *"x.id<100", "enter"])
        for k in ["f", *"x.id>=200", "enter"]:
            await pilot.press(k)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._wheres == ["x.id>=200"]
        assert len(app._subset) == 100  # 200..299, 而非 id<100 and id>=200 的 0 命中


@pytest.mark.asyncio
async def test_malformed_line_is_browsable_not_fatal(tmp_path):
    """坏行不再打断任何环节: 能打开、能筛、能被搜出来 —— 它成了一条看得见的占位行。"""
    from dtflow.cli.view.source import PARSE_ERROR_FIELD, open_source

    p = tmp_path / "bad.jsonl"
    p.write_bytes(
        b"{ this is not json\n"  # 首行就坏, 以前连界面都进不去
        b'{"messages":[{"role":"user","content":"a"}],"id":1}\n'
        b'{"messages":[{"role":"user","content":"b"}],"id":2}\n'
    )
    src = open_source(p)
    app = ViewApp(src, src.window(0, 3), 0, 3, "openai_chat", "bad.jsonl", filepath=str(p))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#table").row_count == 3  # 坏行占一行, 行号不错位
        assert PARSE_ERROR_FIELD in app._visible_columns()  # 坏在哪看得见
        app._apply_filter("x.id>=1")  # 扫描不再崩, 也不回滚
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.is_running and app._subset == [1, 2]
        app.action_reset()
        await pilot.pause()
        app._apply_search("not json")  # 反过来: 用搜索把坏行定位出来
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == [0]


@pytest.mark.asyncio
async def test_scan_worker_error_is_reported_not_fatal():
    """worker 里逃逸的异常必须变成提示 + 回滚, 而不是被 Textual 当致命错误整个退出。

    坏行已在数据源层化解, 这里守的是其余任何意外 (磁盘错误、源实现有 bug 等)。
    """

    class _BoomSource(RowSource):
        total = 5

        def window(self, offset, size):
            return [{"messages": [{"role": "user", "content": "x"}], "id": i} for i in range(5)]

        def iter_all(self, progress_cb=None):
            yield {"id": 0}
            raise OSError("源炸了")

        def rows_at(self, indices):
            return []

    src = _BoomSource()
    app = ViewApp(src, src.window(0, 5), 0, 5, "openai_chat", "t.jsonl", filepath="t.jsonl")
    async with app.run_test() as pilot:
        app._apply_filter("x.id>=0")
        await app.workers.wait_for_complete()
        for _ in range(4):
            await pilot.pause()
        assert app.is_running  # 没被打死
        assert app._scan_cancel is None  # 槽位没泄漏
        assert app._wheres == [] and app._subset is None  # 失败 → 回滚


@pytest.mark.asyncio
async def test_field_navigation_reaches_last_field_without_stutter():
    """回归: 跳到末尾字段时滚动被 max_scroll_y 夹住, 该段并没真对齐到视口顶, 于是滚动
    反查算出的"顶部可见字段"仍是前一段, 把刚跳过去的字段拽了回来 —— n 走到末尾会原地
    停一次, 状态栏字段名跟着抖。到底之后不反查即可, 那里本来就区分不了末尾几段。"""
    rows = [
        {
            "messages": [
                {
                    "role": "user" if i % 2 == 0 else "assistant",
                    "content": f"第{i}段 " + "内容" * 30,
                }
                for i in range(7)
            ],
            "source": "x",
        }
    ]
    app = _make_app(rows)
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()
        names = app._field_names()
        assert len(names) == 8  # msg0..msg6 + 元数据

        seen = []
        for _ in range(len(names) - 1):
            await pilot.press("n")
            await pilot.pause()
            await pilot.pause()  # 让迟到的 scroll watch 落地
            seen.append(app._current_field())
        assert seen == names[1:]  # 逐条推进, 不原地停

        back = []
        for _ in range(len(names) - 1):
            await pilot.press("N")
            await pilot.pause()
            await pilot.pause()
            back.append(app._current_field())
        assert back == names[-2::-1]

        # 但用户真的滚动时, 字段指示仍须跟着走 (别为了修抖动把同步整个关掉)
        detail = app.query_one("#detail")
        detail.scroll_to(y=0, animate=False)
        await pilot.pause()
        await pilot.pause()
        assert app._current_field() == names[0]


@pytest.mark.asyncio
async def test_next_match_reaches_last_field():
    # * 跳到落在末尾的命中同样不能被拽回来
    rows = [
        {
            "messages": [{"role": "user", "content": f"第{i}段 " + "内容" * 30} for i in range(6)]
            + [{"role": "assistant", "content": "命中关键词在最后"}]
        }
    ]
    app = _make_app(rows)
    async with app.run_test(size=(100, 24)) as pilot:
        app._apply_search("命中关键词")
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.action_next_match()
        await pilot.pause()
        await pilot.pause()
        assert app._current_field() == "msg6"


def test_detail_panel_never_truncates_long_content():
    # * 详情面板的职责是完整展示 — 超长字段不得出现 <<<N行>>>/<<<N字符>>> 占位符
    from dtflow.cli.view.render import _render_generic

    long_multiline = ("段落内容 " * 400) + "\n\n" + "x" * 3000
    row = {
        "reply": long_multiline,
        "messages": [{"role": "user", "content": "q" * 5000}],
    }
    _, plain = _render_generic(row)
    assert "<<<" not in plain
    assert "x" * 3000 in plain
    assert "q" * 5000 in plain  # messages 分支同样不截断


# ---------------------------------------------------------------------- #
# 快速尾窗 / follow: 按需历史索引、暂停与增量约束
# ---------------------------------------------------------------------- #
def _file_app(path, cap=3, follow=False):
    from dtflow.cli.view.source import open_source

    src = open_source(path, tail_size=cap, follow=follow)
    rows = src.window(0, cap)
    return ViewApp(
        src,
        rows,
        0,
        cap,
        "generic",
        path.name,
        filepath=str(path),
        follow=follow,
        start_at_end=True,
    )


@pytest.mark.asyncio
async def test_static_tail_starts_relative_and_indexes_when_paging_back(tmp_path):
    p = tmp_path / "tail.jsonl"
    p.write_text("".join(f'{{"i":{i}}}\n' for i in range(10)))
    app = _file_app(p)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert [row["i"] for row in app.all_rows] == [7, 8, 9]
        assert app._global_nos == [-3, -2, -1]
        assert app.query_one("#table").cursor_row == 2

        app.action_prev_window()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.source.fully_indexed and app.source.total == 10
        assert [row["i"] for row in app.all_rows] == [4, 5, 6]
        assert app._global_nos == [4, 5, 6]


@pytest.mark.asyncio
async def test_static_tail_export_does_not_claim_tail_size_is_full_history(tmp_path):
    p = tmp_path / "tail.jsonl"
    p.write_text("".join(f'{{"i":{i}}}\n' for i in range(10)))
    app = _file_app(p)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._export_scope() == ("all", -1)


def _head_app(tmp_path, **kwargs):
    from dtflow.cli.view.source import open_source

    p = tmp_path / "head.jsonl"
    p.write_text("".join(f'{{"i":{i}}}\n' for i in range(10)))
    src = open_source(p, initial_size=3)
    return ViewApp(src, src.window(0, 3), 0, 3, "generic", p.name, **kwargs)


@pytest.mark.asyncio
async def test_head_paging_extends_index_and_preserves_absolute_rows(tmp_path):
    app = _head_app(tmp_path)
    async with app.run_test() as pilot:
        assert app.source.total == 3 and not app.source.fully_indexed
        assert "总行数待定" in str(app.query_one("#status").render())
        await pilot.press("j", "]")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.source.total == 6 and not app.source.fully_indexed
        assert app._global_nos == [3, 4, 5]
        await pilot.press("[")
        assert app._global_nos == [0, 1, 2]
        assert app.source.total == 6
        for _ in range(3):
            await pilot.press("]")
            await app.workers.wait_for_complete()
            await pilot.pause()
        assert app.source.total == 10 and app.source.fully_indexed
        assert app._global_nos == [9]
        await pilot.press("]")
        assert app._global_nos == [9]


@pytest.mark.asyncio
@pytest.mark.parametrize("target,expected", [(5, [4, 5, 6]), (-1, [9]), (100, [9])])
async def test_head_jump_reads_needed_rows_or_real_end(tmp_path, target, expected):
    app = _head_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press(":", *str(target), "enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._global_nos == expected
        assert app.source.fully_indexed == (target == 100)


@pytest.mark.asyncio
async def test_head_bottom_counts_without_full_index_and_top_returns_to_start(tmp_path):
    app = _head_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("G")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._global_nos == [7, 8, 9]
        assert app.query_one("#table").cursor_row == 2
        assert app.source.total == 10 and app.source.total_known
        assert app.query_one("#table").ordered_columns[0].width >= 2
        assert not app.source.fully_indexed and len(app.source._offsets) == 3
        await pilot.press("g")
        assert app._global_nos == [0, 1, 2]


@pytest.mark.asyncio
async def test_g_then_previous_tail_window_and_export_keep_full_semantics(tmp_path):
    import orjson

    app = _head_app(tmp_path)
    out = tmp_path / "after-g.jsonl"
    async with app.run_test() as pilot:
        await pilot.press("G")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._global_nos == [7, 8, 9]
        assert "总行数待定" not in str(app.query_one("#status").render())
        assert app._export_scope() == ("all", 10)

        await pilot.press("[")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._global_nos == [4, 5, 6]
        assert not app.source.fully_indexed
        assert len(app.source._offsets) == 3
        await pilot.press("]")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._global_nos == [7, 8, 9]

        app._apply_export(str(out))
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.source.fully_indexed
        assert [orjson.loads(line) for line in out.read_bytes().splitlines()] == [
            {"i": i} for i in range(10)
        ]
        assert app._global_nos == [7, 8, 9]


@pytest.mark.asyncio
async def test_g_then_filter_sort_and_reset_cover_whole_file(tmp_path):
    app = _head_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("G")
        await app.workers.wait_for_complete()
        app._apply_filter("x.i<8")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == list(range(8)) and app.source.fully_indexed
        app._apply_sort("-i")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._subset == list(range(7, -1, -1))
        await pilot.press("G")
        assert app._global_nos == [2, 1, 0]  # 子集末尾，不是原文件末尾
        await pilot.press("r")
        assert app._global_nos == [0, 1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["escape", "g", "r"])
async def test_cancel_or_new_navigation_does_not_resurrect_pending_g(tmp_path, monkeypatch, key):
    import threading

    app = _head_app(tmp_path)
    entered = threading.Event()

    def delayed_count(*args, cancel=None, **kwargs):
        entered.set()
        assert cancel.wait(5)
        return None

    monkeypatch.setattr("dtflow.utils.jsonl.count_jsonl_rows", delayed_count)
    async with app.run_test() as pilot:
        await pilot.press("G")
        await pilot.pause()
        assert entered.is_set()
        await pilot.press(key)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._scan_cancel is None
        assert app._global_nos == [0, 1, 2]
        assert not app.source.total_known


@pytest.mark.asyncio
async def test_head_initial_search_and_sort_cover_rows_outside_first_window(tmp_path):
    app = _head_app(tmp_path, where=["x.i>=6"], sort="-i")
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.source.fully_indexed
        assert app._subset == [9, 8, 7, 6]
        assert app._global_nos == [9, 8, 7]
        await pilot.press("r")
        assert app._global_nos == [0, 1, 2]


@pytest.mark.asyncio
async def test_head_export_includes_whole_file(tmp_path):
    import orjson

    app = _head_app(tmp_path)
    out = tmp_path / "export.jsonl"
    async with app.run_test() as pilot:
        assert app._export_scope()[1] == -1
        app._apply_export(str(out))
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert [orjson.loads(line) for line in out.read_bytes().splitlines()] == [
            {"i": i} for i in range(10)
        ]
        assert app._global_nos == [0, 1, 2]


@pytest.mark.asyncio
async def test_head_cancel_index_keeps_window_and_allows_retry(tmp_path, monkeypatch):
    import threading

    app = _head_app(tmp_path)
    entered = threading.Event()
    ensure = app.source.ensure_rows

    def wait_for_cancel(count, progress_cb=None, cancel=None):
        entered.set()
        assert cancel.wait(5)
        return False

    monkeypatch.setattr(app.source, "ensure_rows", wait_for_cancel)
    async with app.run_test() as pilot:
        await pilot.press("]")
        await pilot.pause()
        assert entered.is_set()
        await pilot.press("escape")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._scan_cancel is None
        assert app._global_nos == [0, 1, 2] and app.source.total == 3
        monkeypatch.setattr(app.source, "ensure_rows", ensure)
        await pilot.press("]")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._global_nos == [3, 4, 5]


@pytest.mark.asyncio
async def test_follow_appends_at_bottom_pauses_on_navigation_and_g_resumes(tmp_path):
    p = tmp_path / "live.jsonl"
    p.write_text("".join(f'{{"i":{i}}}\n' for i in range(5)))
    app = _file_app(p, follow=True)

    async with app.run_test() as pilot:
        await pilot.pause()
        with p.open("a") as f:
            f.write('{"i":5}\n')
        app._on_follow_update(app.source.poll())
        await pilot.pause()
        assert [row["i"] for row in app.all_rows] == [3, 4, 5]
        assert app.query_one("#table").cursor_row == 2

        await pilot.press("k")
        await pilot.pause()
        assert app._follow_pinned is False
        with p.open("a") as f:
            f.write('{"i":6}\n')
        app._on_follow_update(app.source.poll())
        assert [row["i"] for row in app.all_rows] == [3, 4, 5]
        assert app._follow_pending == 1

        await pilot.press("G")
        await pilot.pause()
        assert app._follow_pinned is True and app._follow_pending == 0
        assert [row["i"] for row in app.all_rows] == [4, 5, 6]


@pytest.mark.asyncio
async def test_follow_filter_scans_history_then_applies_to_new_rows(tmp_path):
    p = tmp_path / "live.jsonl"
    p.write_text("".join(f'{{"id":{i}}}\n' for i in range(10)))
    app = _file_app(p, follow=True)

    async with app.run_test() as pilot:
        app._apply_filter("x.id>=5")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.source.fully_indexed
        assert app._subset == [5, 6, 7, 8, 9]
        assert [row["id"] for row in app.all_rows] == [7, 8, 9]

        with p.open("a") as f:
            f.write('{"id":10}\n{"id":1}\n')
        app._on_follow_update(app.source.poll())
        await pilot.pause()
        assert app._subset == [5, 6, 7, 8, 9, 10]
        assert [row["id"] for row in app.all_rows] == [8, 9, 10]


@pytest.mark.asyncio
async def test_follow_expands_absolute_row_numbers_after_counting_history(tmp_path):
    p = tmp_path / "live.jsonl"
    p.write_text("".join(f'{{"id":{i}}}\n' for i in range(9)))
    app = _file_app(p, follow=True)
    async with app.run_test() as pilot:
        app._apply_filter("x.id>=0")
        await app.workers.wait_for_complete()
        await pilot.pause()
        with p.open("a") as f:
            f.write('{"id":9}\n')
        app._on_follow_update(app.source.poll())
        await pilot.pause()
        assert app._global_nos[-1] == 9
        assert app.query_one("#table").ordered_columns[0].width >= 2


@pytest.mark.asyncio
async def test_follow_rotation_keeps_visible_tail_until_new_rows_evict_it(tmp_path):
    import os

    p = tmp_path / "live.jsonl"
    p.write_text("".join(f'{{"old":{i}}}\n' for i in range(3)))
    app = _file_app(p, follow=True)

    async with app.run_test() as pilot:
        replacement = tmp_path / "new.jsonl"
        replacement.write_text('{"new":1}\n')
        os.replace(replacement, p)
        app._on_follow_update(app.source.poll())
        await pilot.pause()

        assert app._follow_generation == 1
        assert app.all_rows[0] == {"old": 1}
        assert app.all_rows[-1] == {"new": 1}
        assert len(app.all_rows) == 3


@pytest.mark.asyncio
async def test_follow_rotation_refreshes_filter_index_without_dropping_visible_tail(tmp_path):
    import os

    p = tmp_path / "live.jsonl"
    p.write_text("".join(f'{{"id":{i}}}\n' for i in range(6)))
    app = _file_app(p, follow=True)

    async with app.run_test() as pilot:
        app._apply_filter("x.id>=3")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert [row["id"] for row in app.all_rows] == [3, 4, 5]

        replacement = tmp_path / "new.jsonl"
        replacement.write_text("".join(f'{{"id":{i}}}\n' for i in range(4)))
        os.replace(replacement, p)
        app._on_follow_update(app.source.poll())
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert app._subset == [3]
        assert [row["id"] for row in app.all_rows] == [4, 5, 3]

        await pilot.press("G")
        await pilot.pause()
        assert [row["id"] for row in app.all_rows] == [3]


@pytest.mark.asyncio
async def test_follow_rotation_does_not_read_new_file_through_old_sort_indices(tmp_path):
    import os

    p = tmp_path / "live.jsonl"
    p.write_text("".join(f'{{"id":{i}}}\n' for i in range(5)))
    app = _file_app(p, follow=True)

    async with app.run_test() as pilot:
        app._apply_sort("-id")
        await app.workers.wait_for_complete()
        await pilot.pause()
        before = list(app.all_rows)

        replacement = tmp_path / "new.jsonl"
        replacement.write_text('{"id":100}\n')
        os.replace(replacement, p)
        app._on_follow_update(app.source.poll())
        await pilot.pause()
        assert app._follow_sort_snapshot and app._subset is None

        await pilot.press("G")
        await pilot.pause()
        assert app.all_rows == before

        await pilot.press("r")
        await pilot.pause()
        assert app.all_rows == [{"id": 100}]


def _divider_x(app, col_index: int) -> int:
    """第 col_index 列右分隔线的屏幕 x (含表格边框偏移, 未横向滚动时)。"""
    t = app.query_one("#table")
    return (
        t.gutter.left + sum(c.get_render_width(t) for c in t.ordered_columns[: col_index + 1]) - 1
    )


def _drag(t, x0: int, x1: int, y: int):
    """构造一次拖动中的 MouseMove (按住左键从 x0 移到 x1)。"""
    from textual import events

    return events.MouseMove(
        widget=t,
        x=x1,
        y=y,
        delta_x=x1 - x0,
        delta_y=0,
        button=1,
        shift=False,
        meta=False,
        ctrl=False,
        screen_x=x1,
        screen_y=y,
        style=None,
    )


@pytest.mark.asyncio
async def test_column_drag_resize():
    # 拖表头分隔线改列宽: 实时生效, 松手后记在列名上, 重建列表头也不丢
    app = _chat_app(10)
    async with app.run_test(size=(120, 30)) as pilot:
        t = app.query_one("#table")
        vis = app._visible_columns()
        ci = vis.index("turns")
        x, y = _divider_x(app, ci), t.gutter.top
        w0 = t.ordered_columns[ci].width

        await pilot.mouse_down(t, offset=(x, y))
        t.post_message(_drag(t, x, x + 9, y))
        await pilot.pause()
        assert t.ordered_columns[ci].width == w0 + 9  # 拖动中即时改宽, 不等松手

        await pilot.mouse_up(t, offset=(x + 9, y))
        await pilot.pause()
        assert app._manual_widths == {"turns": w0 + 9}

        app._rebuild_columns()
        await pilot.pause()
        assert t.ordered_columns[vis.index("turns")].width == w0 + 9


@pytest.mark.asyncio
async def test_column_drag_min_width_and_click_does_not_open_filter():
    # 拖到底留最小宽度; 只点分隔线(不拖)既不弹值筛选面板, 也不把该列钉成手动宽
    from dtflow.cli.view.app import FastDataTable, ValueFilterScreen

    app = _chat_app(10)
    async with app.run_test(size=(120, 30)) as pilot:
        t = app.query_one("#table")
        ci = app._visible_columns().index("first_user")
        x, y = _divider_x(app, ci), t.gutter.top

        await pilot.mouse_down(t, offset=(x, y))
        t.post_message(_drag(t, x, x - 500, y))
        await pilot.pause()
        await pilot.mouse_up(t, offset=(0, y))
        await pilot.pause()
        assert t.ordered_columns[ci].width == FastDataTable.MIN_DRAG_W

        await pilot.click(t, offset=(_divider_x(app, ci), y))
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not isinstance(app.screen, ValueFilterScreen)
        assert set(app._manual_widths) == {"first_user"}  # 单击没有新增手动列


@pytest.mark.asyncio
async def test_column_double_click_divider_restores_auto_width():
    # 双击分隔线 → 该列恢复自适应, 让出的宽度回流给其它列
    app = _chat_app(10)
    async with app.run_test(size=(120, 30)) as pilot:
        t = app.query_one("#table")
        vis = app._visible_columns()
        ci = vis.index("turns")
        auto = app._column_widths(vis)[ci]
        x, y = _divider_x(app, ci), t.gutter.top

        await pilot.mouse_down(t, offset=(x, y))
        t.post_message(_drag(t, x, x + 20, y))
        await pilot.pause()
        await pilot.mouse_up(t, offset=(x + 20, y))
        await pilot.pause()
        assert "turns" in app._manual_widths

        await pilot.click(t, offset=(_divider_x(app, ci), y), times=2)
        await pilot.pause()
        assert app._manual_widths == {}
        assert t.ordered_columns[ci].width == auto


@pytest.mark.asyncio
async def test_manual_width_survives_narrow_budget():
    # 手动宽度不参与"挤不下就压缩"的公平分配, 其它列让路 (溢出则横向滚动)
    app = _chat_app(10)
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        vis = app._visible_columns()
        app._manual_widths["first_user"] = 40
        assert app._column_widths(vis)[vis.index("first_user")] == 40


@pytest.mark.asyncio
async def test_header_shows_dividers_and_highlights_on_hover():
    # 分隔线常驻表头 (看得见才知道有得拖), 鼠标压上去换粗体符号 + 状态栏出提示
    from dtflow.cli.view.app import FastDataTable

    app = _chat_app(10)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        t = app.query_one("#table")
        vis = app._visible_columns()
        header = t.render_line(0).text
        assert header.count(FastDataTable.DIVIDER) == len(vis)  # 末列右缘也画, 否则末列没法拖
        assert FastDataTable.DIVIDER_HOT not in header
        assert t.render_line(1).text.count(FastDataTable.DIVIDER) == 0  # 数据行保持干净

        ci = vis.index("turns")
        await pilot.hover(t, offset=(_divider_x(app, ci), t.gutter.top))
        await pilot.pause()
        assert t._hover_edge == ci and app._edge_hint
        assert t.render_line(0).text.count(FastDataTable.DIVIDER_HOT) == 1

        await pilot.hover(t, offset=(_divider_x(app, ci) + 4, t.gutter.top))
        await pilot.pause()
        assert t._hover_edge is None and not app._edge_hint
        assert FastDataTable.DIVIDER_HOT not in t.render_line(0).text


@pytest.mark.asyncio
async def test_divider_position_follows_horizontal_scroll():
    # 横向滚动后分隔线仍画在真实列边界上, 固定的 # 列不跟着滚
    from dtflow.cli.view.app import FastDataTable

    app = _chat_app(10)
    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        t = app.query_one("#table")
        app._manual_widths["turns"] = 50  # 撑到溢出屏幕, 逼出横向滚动
        app._rebuild_columns()
        await pilot.pause()
        t.scroll_x = 20
        await pilot.pause()
        xs = [x for x, _ in t._divider_cells()]
        fixed = t.ordered_columns[0].get_render_width(t)
        assert xs[0] == fixed - 1  # # 列是固定列, 边界不随 scroll_x 移动
        assert all(0 <= x < t.size.width for x in xs)
        line = t.render_line(0).text
        for x in xs:
            assert line[x] == FastDataTable.DIVIDER


# ---------------------------------------------------------------------- #
# 详情区鼠标拖选
# ---------------------------------------------------------------------- #
def _mouse(app, cls, x, y):
    kwargs = {
        "x": x,
        "y": y,
        "delta_x": 0,
        "delta_y": 0,
        "button": 1,
        "shift": False,
        "meta": False,
        "ctrl": False,
        "screen_x": x,
        "screen_y": y,
        "style": None,
    }
    return cls(app.screen, **kwargs)


async def _drag_select(pilot, app, x1, y1, x2, y2, steps=6):
    """按下 → 逐格移动 → 松开 (pilot 没有拖拽 API, 按它内部的方式直接投事件)。

    中间要走多步: 真实拖动每格都发一次 MouseMove, 而 textual 每次都按"当前这一帧渲染出来的
    segment"反查坐标 —— 只投一次 move 的话, 一切与"渲染结果被选区改变"相关的错位都测不出来。
    """
    from textual.events import MouseDown, MouseMove, MouseUp

    moves = [
        (MouseMove, x1 + round((x2 - x1) * i / steps), y1 + round((y2 - y1) * i / steps))
        for i in range(1, steps + 1)
    ]
    for cls, x, y in [(MouseDown, x1, y1), *moves, (MouseUp, x2, y2)]:
        app.screen._forward_event(_mouse(app, cls, x, y))
        await pilot.pause()


def _first_field(app):
    from dtflow.cli.view.app import _FieldStatic

    return next(c for c in app.query_one("#detail").children if isinstance(c, _FieldStatic))


@pytest.mark.asyncio
async def test_detail_drag_select_highlights_what_ctrl_c_copies():
    # 详情区拖选: 选到的文本 == 屏幕上高亮的文本 (中文宽字符不错位), Ctrl+c 才进剪贴板
    from rich.cells import cell_len

    rows = [{"messages": [{"role": "user", "content": "abcdefghij 中文字符测试 klmnopqr"}]}]
    app = _make_app(rows)
    copied = []
    app._copy_clipboard = lambda text: copied.append(text)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        f = _first_field(app)
        lines = f._plain_lines()
        y = next(i for i, ln in enumerate(lines) if "abcdefghij" in ln)
        line = lines[y]
        x1 = f.content_region.x + cell_len(line[:3])
        x2 = f.content_region.x + cell_len(line[:16])  # 落在中文中间
        await _drag_select(pilot, app, x1, f.content_region.y + y, x2, f.content_region.y + y)

        selected = app.screen.get_selected_text()
        assert selected.startswith("defghij 中文字符测")
        assert copied == []  # 选中不自动复制
        # 高亮的正是待复制的那段
        sel_bg = app.screen.get_component_rich_style("screen--selection").bgcolor
        strip = f.render_line(y)
        highlighted = "".join(s.text for s in strip if s.style and s.style.bgcolor == sel_bg)
        assert highlighted == selected

        await pilot.press("ctrl+c")
        await pilot.pause()
        assert copied == [selected]
        assert app.screen.get_selected_text() is None  # 复制后清除选区, 高亮不残留


@pytest.mark.asyncio
async def test_detail_drag_select_spans_fields():
    # 跨字段拖选: 起点字段的尾部 + 中间字段整块 + 终点字段的头部
    app = _chat_app(3)
    copied = []
    app._copy_clipboard = lambda text: copied.append(text)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        fields = [
            c for c in app.query_one("#detail").children if type(c).__name__ == "_FieldStatic"
        ]
        first, last = fields[0], fields[-1]
        await _drag_select(
            pilot,
            app,
            first.content_region.x + 1,
            first.content_region.y,
            last.content_region.x + 3,
            last.content_region.y,
        )
        selected = app.screen.get_selected_text()
        assert "\n" in selected  # 跨行跨字段
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert copied == [selected]


@pytest.mark.asyncio
async def test_detail_drag_select_after_scroll():
    # 详情滚动后拖选: 高亮的仍是屏幕上那段 (坐标按可见行算, 不被滚动偏移带歪), Ctrl+c 拿到同一段
    long_text = "\n".join(f"line{i:03d} content" for i in range(60))
    rows = [{"messages": [{"role": "user", "content": long_text}]}]
    app = _make_app(rows)
    copied = []
    app._copy_clipboard = lambda text: copied.append(text)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#detail")
        detail.scroll_to(y=20, animate=False)
        await pilot.pause()
        f = _first_field(app)
        y = detail.content_region.y + 1  # 屏幕坐标: 详情区顶部往下一行
        await _drag_select(
            pilot, app, detail.content_region.x + 2, y, detail.content_region.x + 9, y
        )

        selected = app.screen.get_selected_text()
        sel_bg = app.screen.get_component_rich_style("screen--selection").bgcolor
        row = y - f.content_region.y  # 该屏幕行在字段内的行号
        highlighted = "".join(
            seg.text for seg in f.render_line(row) if seg.style and seg.style.bgcolor == sel_bg
        )
        assert highlighted == selected

        await pilot.press("ctrl+c")
        await pilot.pause()
        assert copied == [selected]


@pytest.mark.asyncio
async def test_ctrl_c_without_selection_copies_nothing_and_answers():
    # 没有选区时 Ctrl+c 不写剪贴板, 但必须给回应 —— 我们这条绑定顶掉了 textual 的
    # "按 q 退出"提示, 静默会让反射性按 ctrl+c 想退出的人以为卡死
    app = _chat_app(3)
    copied = []
    app._copy_clipboard = lambda text: copied.append(text)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert copied == []
        assert app.is_running  # 不退出
        msgs = [n.message for n in app._notifications]
        assert msgs and "q" in msgs[-1]  # 复制怎么用 + 怎么退出


@pytest.mark.asyncio
async def test_multi_click_selection_levels():
    # 连击分级放大: 2 词 · 3 整行 · 4 整个字段块 · 5 整屏详情
    # (textual 默认只有 2=整块/3=整屏, 对着数据看太粗 —— 最常复制的是一个 id/一个值)
    from rich.cells import cell_len

    line = "id=8f3a-42b1 请看 order_no 12345 这段中文内容，还有标点。"
    app = _make_app(
        [
            {
                "messages": [
                    {"role": "user", "content": line},
                    {"role": "assistant", "content": "回答"},
                ]
            }
        ]
    )
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.press("z")  # 切回上下: 详情占满宽度, 长行不折行
        await pilot.pause()
        f = _first_field(app)
        assert f._plain_lines()[1] == line

        async def click_at(word, times):
            x = cell_len(line[: line.index(word) + 1])  # 落在词里面
            app.screen.clear_selection()
            await pilot.click(f, offset=(x, 1), times=times)
            await pilot.pause()
            return app.screen.get_selected_text()

        assert await click_at("8f3a-42b1", 2) == "8f3a-42b1"  # 连字符算词的一部分 (uuid)
        assert await click_at("order_no", 2) == "order_no"  # 下划线同理
        assert await click_at("这段中文内容", 2) == "这段中文内容"  # 中文按标点/空格断词
        assert await click_at("12345", 2) == "12345"

        assert await click_at("order_no", 3) == line  # 整行 (自动换行后的渲染行)
        block = await click_at("order_no", 4)  # 整个字段块: 徽章标题行 + 正文
        assert block.startswith(" user ") and block.endswith(f"\n{line}")
        assert " assistant " in await click_at("order_no", 5)  # 整屏详情


@pytest.mark.asyncio
async def test_double_click_word_then_ctrl_c_copies_it():
    # 双击取词 -> Ctrl+c: 最常用的一条路 (复制一个 id / 一个字段值)
    app = _make_app([{"messages": [{"role": "user", "content": "trace_id abc123 done"}]}])
    copied = []
    app._copy_clipboard = lambda text: copied.append(text)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        f = _first_field(app)
        await pilot.click(f, offset=(f._plain_lines()[1].index("abc123") + 1, 1), times=2)
        await pilot.pause()
        assert copied == []  # 双击只选中
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert copied == ["abc123"]


@pytest.mark.asyncio
async def test_unrelated_drag_leaves_clipboard_alone():
    # 拖列宽/拖滚动条这类与选择无关的拖拽不碰剪贴板 (选区还在, 但没人按 Ctrl+c)
    rows = [{"messages": [{"role": "user", "content": "\n".join(f"line{i}" for i in range(80))}]}]
    app = _make_app(rows)
    copied = []
    app._copy_clipboard = lambda text: copied.append(text)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        f = _first_field(app)
        y = f.content_region.y + 1
        await _drag_select(pilot, app, f.content_region.x + 1, y, f.content_region.x + 5, y)
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert len(copied) == 1

        detail = app.query_one("#detail")
        assert detail.scrollbars_enabled[0]  # 真有滚动条
        sb = detail.vertical_scrollbar
        await _drag_select(pilot, app, sb.region.x, sb.region.y + 1, sb.region.x, sb.region.y + 8)

        t = app.query_one("#table")
        ci = app._visible_columns().index("turns")
        x = _divider_x(app, ci) + t.content_region.x
        await _drag_select(pilot, app, x, t.content_region.y, x + 6, t.content_region.y)
        assert len(copied) == 1  # 剪贴板没被这些拖拽动过


# ---------------------------------------------------------------------- #
# 拖两区分界调大小
# ---------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_split_drag_resizes_panes():
    # 竖排: 按住分界往下拖, 表格变高; 拖动是按格连续的, 不是 5% 一档
    app = _chat_app(30)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("z")  # 默认左右, 切回上下
        await pilot.pause()
        table = app.query_one("#table")
        edge_y = table.region.bottom - 1
        assert app._on_split_edge(table.region.x + 5, edge_y)  # 表格下边框
        assert app._on_split_edge(table.region.x + 5, edge_y + 1)  # 详情上边框
        assert not app._on_split_edge(table.region.x + 5, edge_y - 1)

        h0 = table.region.height  # region 是实时的, 先取值再拖
        await _drag_select(pilot, app, table.region.x + 5, edge_y, table.region.x + 5, edge_y + 3)
        assert app._split not in (65, 70)  # 落在格上, 不对齐 5% 档
        assert table.region.height > h0


@pytest.mark.asyncio
async def test_split_drag_clamps_and_ignores_zoom():
    # 拖过头被夹在 20~80; 详情放大态没有分界
    app = _chat_app(30)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("z")  # 默认左右, 切回上下
        await pilot.pause()
        table = app.query_one("#table")
        main = app.query_one("#main")
        x = table.region.x + 5
        await _drag_select(pilot, app, x, table.region.bottom - 1, x, main.region.bottom - 1)
        assert app._split == app.SPLIT_MAX
        edge = app.query_one("#table").region.bottom - 1
        await _drag_select(pilot, app, x, edge, x, main.region.y)
        assert app._split == app.SPLIT_MIN

        app.action_zoom()  # 放大态只剩详情一个区
        await pilot.pause()
        assert not app._on_split_edge(x, app.query_one("#detail").region.y)


@pytest.mark.asyncio
async def test_split_drag_horizontal_layout():
    # 横排 (默认布局) 时分界是竖的两列, 左右拖改宽度
    app = _chat_app(30)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = app.query_one("#table")
        edge_x = table.region.right - 1
        w0 = table.region.width
        assert app._on_split_edge(edge_x, table.region.y + 3)
        await _drag_select(pilot, app, edge_x, table.region.y + 3, edge_x - 20, table.region.y + 3)
        assert table.region.width < w0


@pytest.mark.asyncio
async def test_split_drag_does_not_select_or_copy():
    # 分界压在详情容器的边框上, 拖它不该顺手拖出一片选区
    app = _chat_app(30)
    copied = []
    app._copy_clipboard = lambda text: copied.append(text)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("z")  # 默认左右, 切回上下
        await pilot.pause()
        table = app.query_one("#table")
        x, edge_y = table.region.x + 5, table.region.bottom - 1
        await _drag_select(pilot, app, x, edge_y, x, edge_y + 4)
        assert app.screen.get_selected_text() is None
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert copied == []


@pytest.mark.asyncio
async def test_split_double_click_restores_default():
    # 双击分界回默认 65:35 (同双击列分隔线恢复自适应)
    app = _chat_app(30)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("z")  # 默认左右, 切回上下
        app._set_split(30)
        await pilot.pause()
        table = app.query_one("#table")
        await pilot.click(table, offset=(5, table.region.height - 1), times=2)
        await pilot.pause()
        assert app._split == app.SPLIT_DEFAULT


async def _real_click(pilot, app, x, y):
    """真实终端的一次点击: 走 App.on_event (Click 由 app 自己合成), 且 down 与 up 之间
    隔着一次事件循环 —— pilot.click 直接投给 screen, 复现不出"按下时 app 抢走鼠标、
    随后的 Click 被捕获者吞掉"这条时序。"""
    from textual.events import MouseDown, MouseUp

    for cls in (MouseDown, MouseUp):
        await app.on_event(_mouse(app, cls, x, y))
        await pilot.pause()


@pytest.mark.asyncio
async def test_panel_click_beats_split_drag():
    # 面板盖在两区分界上时, 点面板里的选项就是选项 —— 不能被分界拖拽抢走
    from textual.widgets import SelectionList

    app = _chat_app(30)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        edge_x = app.query_one("#table").region.right - 1  # 默认左右排, 分界是竖的
        assert app._on_split_edge(edge_x, 10)
        await pilot.press("c")
        await pilot.pause()
        sl = app.screen.query_one(SelectionList)
        box = sl.content_region
        assert box.x <= edge_x < box.right  # 选项行确实横跨分界
        assert not app._on_split_edge(edge_x, box.y)  # 这一格此刻归面板

        before = set(sl.selected)
        split0 = app._split
        await _real_click(pilot, app, edge_x, box.y + 1)
        assert set(app.screen.query_one(SelectionList).selected) != before
        assert app._split == split0 and not app._split_drag


@pytest.mark.asyncio
async def test_value_filter_click_beats_split_drag():
    # 值筛选面板同理 (它贴着列头弹出, 更容易压在分界上)
    from textual.widgets import SelectionList

    rows = [
        {"messages": [{"role": "user", "content": "q"}], "source": f"s{i % 7}"} for i in range(30)
    ]
    app = _make_app(rows)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_value_filter()
        await pilot.pause()
        await pilot.press("s", "o", "u", "r", "c", "e", "enter")
        await pilot.pause()
        sl = app.screen.query_one(SelectionList)
        box = sl.content_region
        edge_x = app.query_one("#table").region.right - 1
        assert box.x <= edge_x < box.right
        before = set(sl.selected)
        await _real_click(pilot, app, edge_x, box.y)
        assert set(app.screen.query_one(SelectionList).selected) != before
        assert not app._split_drag


@pytest.mark.asyncio
async def test_panel_backdrop_does_not_drag_split():
    # 面板外的模态背景也不是分界: 那一格归弹窗, 拖不动两区
    app = _chat_app(30)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        edge_x = app.query_one("#table").region.right - 1
        await pilot.press("c")
        await pilot.pause()
        assert not app._on_split_edge(edge_x, 1)  # 顶部那行是模态背景, 不在面板框里
        split0 = app._split
        await _drag_select(pilot, app, edge_x, 1, edge_x - 20, 1)
        assert app._split == split0


@pytest.mark.asyncio
async def test_panel_aborts_split_drag_in_progress():
    # 拖分界拖到一半弹窗压上来 (值扫描完成会自动弹): 这次拖拽就此作废, 不能在面板底下继续
    from textual.events import MouseDown, MouseMove

    app = _chat_app(30)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        edge_x = app.query_one("#table").region.right - 1
        await app.on_event(_mouse(app, MouseDown, edge_x, 10))
        await pilot.pause()
        assert app._split_drag
        split0 = app._split

        await pilot.press("c")  # 面板压上来
        await pilot.pause()
        assert not app._split_drag and app.mouse_captured is None
        await app.on_event(_mouse(app, MouseMove, edge_x - 20, 10))
        await pilot.pause()
        assert app._split == split0


@pytest.mark.asyncio
async def test_panel_aborts_column_drag_in_progress():
    # 列宽拖到一半弹窗压上来: 面板关掉后不能留下"鼠标一动列宽就跟着跑"的幽灵拖拽
    from textual.events import MouseDown, MouseMove

    app = _chat_app(30)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        t = app.query_one("#table")
        x = t.region.x + t.gutter.left + t._divider_cells()[0][0]
        y = t.region.y + t.gutter.top
        w0 = t.ordered_columns[0].width
        await app.on_event(_mouse(app, MouseDown, x, y))
        await pilot.pause()
        assert t._drag_col is not None
        await app.on_event(_mouse(app, MouseMove, x + 16, y))
        await pilot.pause()
        assert t.ordered_columns[0].width > w0  # 确实拖宽了

        await pilot.press("c")
        await pilot.pause()
        assert t._drag_col is None and app.mouse_captured is None
        assert t.ordered_columns[0].width == w0  # 当场退回, 不留个待回弹的半截宽
        await pilot.press("escape")
        await pilot.pause()
        await app.on_event(_mouse(app, MouseMove, x + 16, y))
        await pilot.pause()
        assert t.ordered_columns[0].width == w0
        assert not app._manual_widths


@pytest.mark.asyncio
async def test_split_hint_clears_when_panel_opens():
    # 鼠标停在分界上时开面板: "可拖"高亮得熄掉, 否则指着一条此刻拖不动的线
    from textual.events import MouseMove

    app = _chat_app(30)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        edge_x = app.query_one("#table").region.right - 1
        await app.on_event(_mouse(app, MouseMove, edge_x, 10))
        await pilot.pause()
        assert app._split_hint and app.query_one("#table").has_class("split-hot")
        await pilot.press("c")
        await pilot.pause()
        assert not app._split_hint and not app.query_one("#table").has_class("split-hot")


@pytest.mark.asyncio
async def test_ctrl_c_in_input_copies_input_selection():
    # 焦点在搜索/筛选输入框且框里有选中时, Ctrl+c 归 Input 自己的复制, 别被 app 这条绑定吃掉
    app = _chat_app(3)
    copied = []
    app._copy_clipboard = lambda text: copied.append(text)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("slash")  # 打开搜索 prompt
        await pilot.pause()
        prompt = app.query_one("#prompt")
        prompt.value = "abc"
        prompt.action_home()
        prompt.action_cursor_right(select=True)
        prompt.action_cursor_right(select=True)
        await pilot.pause()
        assert prompt.selected_text == "ab"

        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.clipboard == "ab"  # Input.action_copy 走的是 app.copy_to_clipboard
        assert not [n for n in app._notifications if "没有选中内容" in n.message]


@pytest.mark.asyncio
async def test_ctrl_c_in_value_filter_search_copies_selection():
    # 值筛选面板的搜索框同理 (它也是 Input, 只是在模态屏里)
    app = _chat_app(6)
    app._copy_clipboard = lambda text: None  # 别在测试里真写系统剪贴板
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._start_value_scan("source")
        await app.workers.wait_for_complete()
        await pilot.pause()
        box = app.screen.query_one("#vf-search")
        box.value = "xy"
        box.action_home()
        box.action_cursor_right(select=True)
        await pilot.pause()
        assert box.selected_text == "x"

        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.clipboard == "x"
        assert not [n for n in app._notifications if "没有选中内容" in n.message]


@pytest.mark.asyncio
async def test_selection_highlight_keeps_text_readable():
    # 选区高亮只改背景: screen--selection 的前景是"完全透明", 扁平成 rich style 后与背景同色,
    # 整段叠上去会把文字涂没 (选中即看不见内容)
    app = _make_app([{"messages": [{"role": "user", "content": "彩色文本 abcdef"}]}])
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        f = _first_field(app)
        before = [(seg.text, seg.style.color) for seg in f.render_line(0)]
        f.text_select_all()
        await pilot.pause()
        after = [(seg.text, seg.style.color) for seg in f.render_line(0)]
        assert [c for _, c in after] == [c for _, c in before]  # 前景原样
        sel_bg = app.screen.get_component_rich_style("screen--selection").bgcolor
        assert all(seg.style.bgcolor == sel_bg for seg in f.render_line(0) if seg.text)
        assert all(seg.style.color != sel_bg for seg in f.render_line(0) if seg.text.strip())


@pytest.mark.asyncio
async def test_drag_onto_blank_line_stays_within_drag():
    # 空行渲染成 0 个 segment, 没地方挂 offset —— 不补落点的话 textual 反查失败,
    # 会把这一端退化成"整块全选": 只拖了两行, 却选中整个字段
    rows = [{"messages": [{"role": "assistant", "content": "第一行\n\n第三行\n第四行\n第五行"}]}]
    app = _make_app(rows)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        f = _first_field(app)
        lines = f._plain_lines()
        i = lines.index("第一行")
        assert lines[i + 1] == ""  # 下一行确实是空行
        y = f.content_region.y + i
        await _drag_select(pilot, app, f.content_region.x + 2, y, f.content_region.x + 2, y + 1)
        selected = app.screen.get_selected_text()
        assert "第三行" not in selected and "第五行" not in selected
        assert selected == "一行"  # 起点落在"第"之后, 终点是空行 —— 就这么多


@pytest.mark.asyncio
async def test_drag_select_tracks_mouse_across_steps():
    # 真实拖动是一连串 MouseMove, textual 每次都按"当前帧渲染出的 segment"反查坐标:
    # 高亮会把 segment 切成三段, 若沿用切之前的 offset, 后两段都自称从原 segment 起点开始,
    # 选区就会越拖越短 (用户看到的"高亮从鼠标位置一路涂到行首")
    from rich.cells import cell_len

    text = "abcdefghijklmnopqrstuvwxyz0123456789"
    app = _make_app([{"messages": [{"role": "user", "content": text}]}])
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        f = _first_field(app)
        y = f.content_region.y + 1
        base = f.content_region.x
        sel_bg = app.screen.get_component_rich_style("screen--selection").bgcolor

        for x1, x2 in ((2, 20), (25, 8)):  # 正向 / 反向拖
            app.screen.clear_selection()
            await pilot.pause()
            await _drag_select(pilot, app, base + x1, y, base + x2, y, steps=10)

            strip = app.screen._compositor.render_strips()[y]
            cells, start, end = 0, None, None
            for seg in strip:  # 屏幕上真正被涂上选区底色的 cell 区间
                if seg.style and seg.style.bgcolor == sel_bg:
                    start = cells if start is None else start
                    end = cells + cell_len(seg.text)
                cells += cell_len(seg.text)
            lo, hi = min(x1, x2), max(x1, x2) + 1  # 终点那格也算进选区
            assert (start - base, end - base) == (lo, hi)
            assert app.screen.get_selected_text() == text[lo:hi]


@pytest.mark.asyncio
async def test_status_state_left_hints_right():
    # 状态栏: 左边会变的状态, 右边常驻 z / ? 提示 (窄屏被截的是状态的右端, 提示始终在)
    app = _chat_app(5)
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        status, hint = app.query_one("#status"), app.query_one("#hint")
        assert hint.render_line(0).text.strip() == "z 布局 · ? 帮助"
        assert hint.region.right == status.region.right + hint.region.width  # 贴在右端
        assert app.filename not in status.render_line(0).text  # 文件名在表格边框标题上

        await pilot.resize_terminal(30, 20)
        await pilot.pause()
        assert hint.render_line(0).text.strip() == "z 布局 · ? 帮助"

        app._set_split_hint(True)  # 压在两区分界上: 让位给更贴当下的那条提示
        await pilot.pause()
        assert "拖动调两区大小" in status.render_line(0).text
        assert hint.render_line(0).text.strip() == ""


@pytest.mark.asyncio
async def test_border_titles_carry_file_position_and_sample():
    # 文件·格式 / 光标位置 / 样本摘要 / 当前字段 挂在两区边框上, 随光标即时更新
    app = _chat_app(5)
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        table, detail = app.query_one("#table"), app.query_one("#detail")
        assert table.border_title == f"{app.filename} · openai_chat"
        assert table.border_subtitle == "1 / 5"
        assert detail.border_title.startswith("#1 · ")
        assert detail.border_subtitle == "msg0"
        await pilot.press("j", "j")
        await pilot.pause()
        assert table.border_subtitle == "3 / 5"
        assert detail.border_title.startswith("#3 · ")


# ---------------------------------------------------------------------- #
# 筛选前后的视图位置
# ---------------------------------------------------------------------- #
async def _wide_app(pilot, app):
    """把某列撑到溢出屏幕, 逼出横向滚动。"""
    app._manual_widths["first_user"] = 120
    app._rebuild_columns()
    await pilot.pause()
    t = app.query_one("#table")
    assert t.max_scroll_x > 40
    return t


@pytest.mark.asyncio
async def test_filter_keeps_horizontal_scroll_and_cursor():
    # 筛选要重填表格, 而 DataTable.clear() 会把横向滚动清零 —— 右边那几列看得好好的,
    # 一应用筛选就被弹回最左。光标则跟住原来那条样本 (它常常就是按 f 的原因)
    app = _chat_app(40)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        t = await _wide_app(pilot, app)
        t.move_cursor(row=7)
        t.scroll_x = 40
        await pilot.pause()
        keep = app._cursor_global_no()

        app._apply_filter("x.source=='a'")  # 奇数 idx 命中
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert t.scroll_x == 40
        assert app._cursor_global_no() == keep  # 还停在原来那条上 (行号变了, 样本没变)

        # 值筛选走的是另一条路径, 同样保持
        t.scroll_x = 30
        await pilot.pause()
        app._start_value_scan("source")
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.screen.dismiss({"a"})
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert t.scroll_x == 30


@pytest.mark.asyncio
async def test_filtered_out_sample_falls_back_to_first_row():
    # 原来那条被筛掉了就留在首行 (为跟一条样本跨窗口跳转反而喧宾夺主), 横向仍保持
    app = _chat_app(40)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        t = await _wide_app(pilot, app)
        t.move_cursor(row=2)  # source == "b" (偶数 idx)
        t.scroll_x = 35
        await pilot.pause()

        app._apply_filter("x.source=='a'")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert t.cursor_row == 0
        assert t.scroll_x == 35


@pytest.mark.asyncio
async def test_reset_returns_to_leftmost():
    # r 是"回到全量浏览的起点", 横向也一并回最左
    app = _chat_app(40)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        t = await _wide_app(pilot, app)
        t.scroll_x = 50
        await pilot.pause()
        app.action_reset()
        await pilot.pause()
        assert t.scroll_x == 0 and t.cursor_row == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("width", [120, 61])  # 列没铺满 (末列右缘在表格中间) / 恰好铺满到右缘
async def test_last_column_divider_drawn_and_draggable(width):
    # 末列右缘同样画分隔线并可拖, 否则最右一列没法调宽
    from dtflow.cli.view.app import FastDataTable

    app = _chat_app(10)
    async with app.run_test(size=(width, 30)) as pilot:
        await pilot.pause()
        await pilot.press("z")  # 切回上下: 表格占满终端宽度, width 参数才是表格宽度
        await pilot.pause()
        t = app.query_one("#table")
        last = len(t.ordered_columns) - 1
        cells = t._divider_cells()
        assert cells[-1][1] == last
        x_local = cells[-1][0]
        assert t.render_line(0).text[x_local] == FastDataTable.DIVIDER

        x, y = _divider_x(app, last), t.gutter.top
        assert x == x_local + t.gutter.left
        w0 = t.ordered_columns[last].width
        await pilot.mouse_down(t, offset=(x, y))
        t.post_message(_drag(t, x, x - 2, y))
        await pilot.pause()
        await pilot.mouse_up(t, offset=(x - 2, y))
        await pilot.pause()
        assert t.ordered_columns[last].width == w0 - 2
        assert app._manual_widths[app._visible_columns()[last]] == w0 - 2


# --------------------------------------------------------------------------- #
# 列重命名: 双击列头 → 界面即时改, 文件退出时写回
# --------------------------------------------------------------------------- #
def _header_x(app, col: str) -> int:
    t = app.query_one("#table")
    vis = app._visible_columns()
    widths = app._column_widths(vis)
    ci = vis.index(col)
    return sum(widths[j] + 2 * t.cell_padding for j in range(ci)) + t.cell_padding + 1


@pytest.mark.asyncio
async def test_rename_column_updates_header_detail_and_picker():
    from dtflow.cli.view.app import ColumnPicker

    app = _chat_app(5)
    async with app.run_test(size=(120, 30)) as pilot:
        t = app.query_one("#table")
        vis = app._visible_columns()
        app._rename_column("source", "src")
        await pilot.pause()
        assert app._renames == {"source": "src"}
        assert str(t.ordered_columns[vis.index("source")].label) == "src"
        await pilot.pause()
        # 详情里的元数据用新名 (对话格式的元数据段是键值文本)
        meta = "\n".join(app._field_texts)
        assert "src" in meta and "source" not in meta
        # 选列面板显示新名, 值仍是原始名
        app.action_columns()
        await pilot.pause()
        assert isinstance(app.screen, ColumnPicker)
        sl = app.screen.query_one("SelectionList")
        labels = [str(sl.get_option_at_index(i).prompt) for i in range(sl.option_count)]
        assert "src" in labels and "source" not in labels
        app.screen.action_cancel()
        await pilot.pause()
        # 链式改名与改回原名
        app._rename_column("source", "origin")
        assert app._renames == {"source": "origin"}
        app._rename_column("source", "source")
        assert app._renames == {}


@pytest.mark.asyncio
async def test_rename_rejects_invalid():
    app = _chat_app(5)
    async with app.run_test(size=(120, 30)):
        for col, new in [
            ("turns", "x"),
            ("#", "x"),
            ("nope", "x"),
            ("source", "id" if "id" in app.columns else "turns"),
            ("source", "turns"),
            ("source", "#"),
            ("source", ""),
        ]:
            app._rename_column(col, new)
            assert app._renames == {}, (col, new)


@pytest.mark.asyncio
async def test_header_double_click_opens_rename_prompt_single_click_delays_value_filter():
    from dtflow.cli.view.app import ValueFilterScreen

    app = _chat_app(10)
    async with app.run_test(size=(120, 30)) as pilot:
        x = _header_x(app, "source")
        await pilot.click("#table", offset=(x, 1), times=2)
        await pilot.pause()
        prompt = app.query_one("#prompt")
        assert prompt.has_class("active") and app._prompt_mode == "rename"
        assert app._rename_target == "source" and prompt.value == "source"
        await pilot.pause(0.4)  # 定时器已被取消, 值面板不会再弹
        assert not isinstance(app.screen, ValueFilterScreen)
        prompt.value = "src"
        await pilot.press("enter")
        await pilot.pause()
        assert app._renames == {"source": "src"}
        # 单击: 0.15s 后才开值面板
        await pilot.click("#table", offset=(_header_x(app, "source"), 1))
        await pilot.pause(0.02)
        assert not isinstance(app.screen, ValueFilterScreen)
        await pilot.pause(0.4)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, ValueFilterScreen)
        assert app.screen._col == "source"  # 约束用原始名


@pytest.mark.asyncio
async def test_double_click_derived_header_does_not_rename():
    app = _chat_app(5)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.click("#table", offset=(_header_x(app, "turns"), 1), times=2)
        await pilot.pause()
        assert not app.query_one("#prompt").has_class("active")


@pytest.mark.asyncio
async def test_escape_closes_prompt():
    app = _chat_app(5)
    async with app.run_test() as pilot:
        await pilot.press("slash")
        assert app.query_one("#prompt").has_class("active")
        await pilot.press("escape")
        await pilot.pause()
        assert not app.query_one("#prompt").has_class("active") and app._prompt_mode is None


@pytest.mark.asyncio
async def test_quit_asks_only_when_renamed():
    from dtflow.cli.view.app import SaveScreen

    app = _chat_app(5)
    async with app.run_test() as pilot:
        app._rename_column("source", "src")
        await pilot.press("q")
        await pilot.pause()
        assert isinstance(app.screen, SaveScreen)
        assert not app._exit
        # stdin/内存源没有文件: 没有写回按钮
        assert not app.screen.query("#sv-write")
        app.screen.action_cancel()
        await pilot.pause()
        assert not app._exit and app._renames == {"source": "src"}
        await pilot.press("q")
        await pilot.pause()
        app.screen.action_discard()
        await pilot.pause()
        assert app._exit
    app2 = _chat_app(5)
    async with app2.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()
        assert app2._exit


@pytest.mark.asyncio
async def test_write_back_rewrites_file_and_lineage(tmp_path):
    import orjson

    from dtflow.cli.view.app import SaveScreen

    app = _head_app(tmp_path, filepath=str(tmp_path / "head.jsonl"))
    p = tmp_path / "head.jsonl"
    async with app.run_test() as pilot:
        app._rename_column("i", "idx")
        await pilot.pause()
        app.action_quit()
        await pilot.pause()
        assert isinstance(app.screen, SaveScreen)
        assert app.screen.query("#sv-write")
        app.screen.action_write()
        await pilot.pause()
        assert app._exit
    rows = [orjson.loads(line) for line in p.read_bytes().splitlines()]
    assert [list(r) for r in rows] == [["idx"]] * 10 and [r["idx"] for r in rows] == list(range(10))
    assert not list(tmp_path.glob(".tmp_*"))
    rec = orjson.loads((tmp_path / "head.jsonl.lineage.json").read_bytes())
    op = rec["operations"][-1]
    assert op["type"] == "view_rename" and op["params"]["renames"] == {"i": "idx"}
    assert (
        "--rename 'i:idx' -i" in op["params"]["command"]
        or "--rename i:idx -i" in op["params"]["command"]
    )


@pytest.mark.asyncio
async def test_follow_mode_cannot_write_back(tmp_path):
    from dtflow.cli.view.app import SaveScreen

    app = _head_app(tmp_path, filepath=str(tmp_path / "head.jsonl"), follow=True)
    async with app.run_test() as pilot:
        app._rename_column("i", "idx")
        app.action_quit()
        await pilot.pause()
        assert isinstance(app.screen, SaveScreen) and not app.screen.query("#sv-write")
        app.screen.action_discard()
        await pilot.pause()
    assert (tmp_path / "head.jsonl").read_text().startswith('{"i":0}')


@pytest.mark.asyncio
async def test_export_applies_renames(tmp_path):
    import orjson

    app = _make_app(_chat_rows(6))
    app.filepath = str(tmp_path / "src.jsonl")
    out = tmp_path / "out.jsonl"
    async with app.run_test() as pilot:
        app._rename_column("source", "src")
        app._apply_export(str(out))
        await app.workers.wait_for_complete()
        await pilot.pause()
    rows = [orjson.loads(x) for x in out.read_text().strip().split("\n")]
    assert len(rows) == 6 and all("src" in r and "source" not in r for r in rows)
    rec = orjson.loads((tmp_path / "out.jsonl.lineage.json").read_bytes())
    assert rec["operations"][0]["params"]["renames"] == {"source": "src"}


@pytest.mark.asyncio
async def test_write_back_readonly_dir_notifies_instead_of_crashing(tmp_path):
    """目标目录不可写: 提示错误, 不退出, 改名保留 (mkstemp 在 try 内)。"""
    import os

    from dtflow.cli.view.app import SaveScreen

    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions")
    d = tmp_path / "ro"
    d.mkdir()
    p = d / "head.jsonl"
    p.write_text("".join(f'{{"i":{i}}}\n' for i in range(10)))
    from dtflow.cli.view.source import open_source

    src = open_source(p, initial_size=3)
    app = ViewApp(src, src.window(0, 3), 0, 3, "generic", p.name, filepath=str(p))
    d.chmod(0o555)
    try:
        async with app.run_test() as pilot:
            app._rename_column("i", "idx")
            app.action_quit()
            await pilot.pause()
            assert isinstance(app.screen, SaveScreen)
            app.screen.action_write()
            await pilot.pause()
            assert not app._exit and app._renames == {"i": "idx"}
            await pilot.press("q")
            await pilot.pause()
            assert isinstance(app.screen, SaveScreen)
            app.screen.action_discard()
            await pilot.pause()
    finally:
        d.chmod(0o755)
    assert p.read_text().startswith('{"i":0}')


@pytest.mark.asyncio
async def test_write_back_appends_to_existing_lineage(tmp_path):
    """文件已有血缘 (来自 dt clean 等) 时写回追加操作, 不冲掉来源链。"""
    import orjson

    from dtflow.lineage import LineageTracker

    app = _head_app(tmp_path, filepath=str(tmp_path / "head.jsonl"))
    p = tmp_path / "head.jsonl"
    LineageTracker(str(tmp_path / "raw.jsonl")).record(
        "clean", params={"strip": True}, input_count=12, output_count=10
    ).save(str(p), 10)
    async with app.run_test() as pilot:
        app._rename_column("i", "idx")
        app.action_quit()
        await pilot.pause()
        app.screen.action_write()
        await pilot.pause()
        assert app._exit
    rec = orjson.loads((tmp_path / "head.jsonl.lineage.json").read_bytes())
    assert rec["source"]["path"].endswith("raw.jsonl")
    assert [op["type"] for op in rec["operations"]] == ["clean", "view_rename"]
    assert rec["metadata"]["output_count"] == 10


@pytest.mark.asyncio
async def test_write_back_refuses_collision_with_unseen_field(tmp_path):
    """目标列名只出现在窗口外的行里: 写回中止、原文件不动, 而不是静默覆盖那一行的字段。"""
    from dtflow.cli.view.source import open_source

    p = tmp_path / "head.jsonl"
    lines = [f'{{"i":{i}}}' for i in range(9)] + ['{"i":9,"idx":"keep"}']
    p.write_text("\n".join(lines) + "\n")
    before = p.read_bytes()
    src = open_source(p, initial_size=3)
    app = ViewApp(src, src.window(0, 3), 0, 3, "generic", p.name, filepath=str(p))
    async with app.run_test() as pilot:
        app._rename_column("i", "idx")  # 窗口里没有 idx, 校验放行
        app.action_quit()
        await pilot.pause()
        app.screen.action_write()
        await pilot.pause()
        assert not app._exit and app._renames == {"i": "idx"}
        await pilot.press("q")
        await pilot.pause()
        app.screen.action_discard()
        await pilot.pause()
    assert p.read_bytes() == before
    assert not list(tmp_path.glob(".tmp_*"))
    assert not (tmp_path / "head.jsonl.lineage.json").exists()


@pytest.mark.asyncio
async def test_value_filter_title_shows_renamed_column():
    from dtflow.cli.view.app import ValueFilterScreen

    app = _chat_app(10)
    async with app.run_test(size=(120, 30)) as pilot:
        app._rename_column("source", "src")
        app._start_value_scan("source")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, ValueFilterScreen)
        title = str(app.screen.query_one("#picker-title").render())
        assert "src" in title and app.screen._col == "source"
        await pilot.press("escape")


def _long_chat_rows():
    """第 0 行是几百条长消息的 agent 轨迹 (远超两屏, 触发分批挂载), 其后是短样本。"""
    long_msgs = [
        {"role": "user" if k % 2 == 0 else "assistant", "content": f"m{k} " + "x" * 400}
        for k in range(300)
    ]
    short = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]
    return [{"messages": long_msgs}] + [{"messages": short} for _ in range(5)]


async def _wait_all_mounted(pilot, app):
    for _ in range(400):
        if len(app._field_widgets) == len(app._fields):
            return
        await pilot.pause(0.01)
    raise AssertionError("detail fields never finished mounting")


@pytest.mark.asyncio
async def test_detail_mounts_long_sample_in_batches(monkeypatch):
    # 长样本首批只挂够两屏的字段, 余下由 _mount_more 帧后逐批补齐, 锚点最终覆盖全部字段
    monkeypatch.setattr(ViewApp, "_mount_more", lambda self, gen: None)  # 先冻住后台批次
    app = _make_app(_long_chat_rows())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert len(app._fields) == 300
        assert 0 < len(app._field_widgets) < 300
        monkeypatch.undo()  # 放开后台批次, 链式补齐
        app._mount_more(app._mount_gen)
        await _wait_all_mounted(pilot, app)
        await pilot.pause()
        assert list(app._cur_anchors) == app._field_names()


@pytest.mark.asyncio
async def test_goto_unmounted_field_mounts_and_scrolls(monkeypatch):
    # 跳到还没挂上的字段: 当场补挂到它为止, 布局后对齐到视口顶
    monkeypatch.setattr(ViewApp, "_mount_more", lambda self, gen: None)
    app = _make_app(_long_chat_rows())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        target = 150
        assert len(app._field_widgets) <= target
        app._goto_field(target)
        for _ in range(5):
            await pilot.pause()
        assert len(app._field_widgets) == target + 1
        name = app._field_names()[target]
        assert app._current_field() == name
        detail = app.query_one("#detail")
        assert app._top_field(app._cur_anchors, detail.scroll_offset.y) == name


@pytest.mark.asyncio
async def test_switching_sample_cancels_pending_batches(monkeypatch):
    # 长样本还没挂完就换到短样本: 旧代次的批次作废, 详情只剩短样本的字段
    mount_more = ViewApp._mount_more
    monkeypatch.setattr(ViewApp, "_mount_more", lambda self, gen: None)
    app = _make_app(_long_chat_rows())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        old_gen = app._mount_gen
        app.query_one("#table").move_cursor(row=1)
        for _ in range(3):
            await pilot.pause()
        mount_more(app, old_gen)  # 迟到的旧批次
        await pilot.pause()
        assert len(app._fields) == 2
        assert len(app._field_widgets) == 2
        assert len(app.query_one("#detail").children) == 2


@pytest.mark.asyncio
async def test_queued_cursor_moves_render_detail_once(monkeypatch):
    # 长按 j 时按键排队: 表格光标逐行走, 详情只按最后一行渲染一次
    from textual import events

    app = _chat_app(30)
    calls = []
    orig = ViewApp._refresh_detail
    monkeypatch.setattr(
        ViewApp, "_refresh_detail", lambda self, r: (calls.append(r), orig(self, r))
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        calls.clear()
        for _ in range(10):
            app.post_message(events.Key("j", "j"))
        for _ in range(10):
            await pilot.pause()
        assert app.query_one("#table").cursor_row == 10
        assert calls == [10]


@pytest.mark.asyncio
async def test_numeric_columns_right_aligned():
    # 采样全为数字的列右对齐 (列头同); 夹杂非数字的列保持左对齐
    rows = [{"n": i * 7, "score": 0.5 + i, "mixed": "x" if i == 3 else i} for i in range(10)]
    app = _make_app(rows, fmt="generic")
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        assert {"n", "score"} <= app._numeric_cols
        assert "mixed" not in app._numeric_cols
        vis = app._visible_columns()
        cells = _rendered_row(app, 0)
        assert cells[vis.index("n")].renderable.justify == "right"  # Padding 包着右对齐的 Text
        assert cells[vis.index("mixed")].justify != "right"


@pytest.mark.asyncio
async def test_empty_view_clears_detail_border_titles():
    # 筛选 0 命中: 详情清空, 边框标题/副标题都不能残留上个样本的行号与字段名
    app = _chat_app(5)
    async with app.run_test() as pilot:
        await pilot.pause()
        detail = app.query_one("#detail")
        assert detail.border_subtitle == "msg0"
        app._apply_filter("turns(x)>99")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.view_indices == []
        assert detail.border_title is None and detail.border_subtitle is None


@pytest.mark.asyncio
async def test_search_highlight_skips_generated_columns():
    # 搜数字时, 行号/轮数/字数/roles 这些算出来的列不画命中, 数据列照画
    import re

    from rich.padding import Padding

    rows = [{"messages": [{"role": "user", "content": "1"}], "score": 1} for _ in range(3)]
    app = _make_app(rows)
    async with app.run_test(size=(120, 20)) as pilot:
        await pilot.pause()
        app._search_re = re.compile("1")
        app._populate()
        await pilot.pause()
        vis = app._visible_columns()
        row = _rendered_row(app, 0)

        def spans(col):
            cell = row[vis.index(col)]
            text = cell.renderable if isinstance(cell, Padding) else cell
            return text.spans

        assert not spans("#") and not spans("turns") and not spans("chars")
        assert spans("first_user") and spans("score")


@pytest.mark.asyncio
async def test_search_highlights_data_columns_named_like_derived():
    # 派生列按当前格式判断: generic 数据里叫 chars / turns / has_input 的是真实数据, 照画命中
    import re

    from rich.padding import Padding

    rows = [{"id": i, "chars": 11, "turns": 1, "has_input": "a1"} for i in range(3)]
    app = _make_app(rows, fmt="generic")
    async with app.run_test(size=(120, 20)) as pilot:
        await pilot.pause()
        app._search_re = re.compile("1")
        app._populate()
        await pilot.pause()
        vis = app._visible_columns()
        row = _rendered_row(app, 0)
        for col in ("chars", "turns", "has_input"):
            cell = row[vis.index(col)]
            assert (cell.renderable if isinstance(cell, Padding) else cell).spans, col
        assert not row[vis.index("#")].renderable.spans  # 行号仍不画


# --------------------------------------------------------------------------- #
# |: 在 view 里跑 shell 管道, 结果替换浏览数据; r 回到原文件; C/P/w 带上管道
# --------------------------------------------------------------------------- #
async def _pipe(app, pilot, text):
    app._apply_pipe(text)
    await app.workers.wait_for_complete()
    await pilot.pause()


@pytest.mark.asyncio
async def test_pipe_replaces_source_and_reset_restores():
    rows = _chat_rows(30)
    app = _make_app(rows)
    origin = app.source
    async with app.run_test() as pilot:
        notes = []
        app.notify = lambda msg, **kw: notes.append(str(msg))
        await _pipe(app, pilot, 'dt select - "id=x.source,n=turns(x)" | dt sort - --by x.n --desc')
        assert app.source is not origin and app.source.total == 30
        assert app.fmt == "generic" and app.columns == ["#", "id", "n"]
        assert app._pipe.startswith("dt select")
        assert "| dt select" in str(app.query_one("#table").border_title)
        assert app.all_rows[0] == {"id": "b", "n": 2}
        assert any("30" in n for n in notes)
        # 管道结果上再筛选: 作用在结果而不是原文件
        app._apply_filter("x.id == 'a'")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._seq_total() == 15
        # r: 回到原文件, 格式/列/约束全部恢复
        await pilot.press("r")
        await pilot.pause()
        assert app.source is origin and app._pipe is None and app.fmt == "openai_chat"
        assert app.columns[:3] == ["#", "turns", "roles"] and app._subset is None
        assert app.source.total == 30 and len(app.all_rows) == 30


@pytest.mark.asyncio
async def test_pipe_failure_keeps_data_and_zero_rows_clears_view():
    app = _make_app(_chat_rows(10))
    origin = app.source
    async with app.run_test() as pilot:
        notes = []
        app.notify = lambda msg, **kw: notes.append((str(msg), kw.get("severity")))
        await _pipe(app, pilot, 'dt filter - "x.a >"')  # 语法错误 → dt 退出码 2
        assert app.source is origin and app._pipe is None
        assert notes[-1][1] == "error" and "x.a >" in notes[-1][0]
        await _pipe(app, pilot, 'dt filter - "False"')  # 0 行: 切到空结果并提示
        assert app.source is not origin and app.source.total == 0
        assert app.all_rows == [] and app.query_one("#table").row_count == 0
        assert notes[-1][1] == "warning" and "0" in notes[-1][0]
        await pilot.press("r")
        await pilot.pause()
        assert app.source is origin and len(app.all_rows) == 10


@pytest.mark.asyncio
async def test_pipe_always_reads_the_original_file():
    app = _make_app(_chat_rows(20))
    async with app.run_test() as pilot:
        await _pipe(app, pilot, "dt head - 5")
        assert app.source.total == 5
        await _pipe(app, pilot, "dt head - 7")  # 第二次仍从原文件 (20 行) 跑, 不是从 5 行
        assert app.source.total == 7


@pytest.mark.asyncio
async def test_pipe_rejected_in_follow_mode():
    src = _ListSource(_chat_rows(3))
    app = ViewApp(src, src.window(0, 3), 0, 3, "openai_chat", "t.jsonl", follow=True)
    async with app.run_test() as pilot:
        notes = []
        app.notify = lambda msg, **kw: notes.append(kw.get("severity"))
        await pilot.press("vertical_line")
        await pilot.pause()
        assert notes == ["warning"] and app._prompt_mode is None


@pytest.mark.asyncio
async def test_pipe_cancel_via_escape():
    app = _slow_app(3000)  # 喂入慢, 有足够的时间窗按 Esc
    origin = app.source
    async with app.run_test() as pilot:
        notes = []
        app.notify = lambda msg, **kw: notes.append(str(msg))
        app._apply_pipe("cat")
        await pilot.pause(0.1)
        assert app._scan_cancel is not None
        await pilot.press("escape")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.source is origin and app._pipe is None
        assert any("取消" in n for n in notes)


@pytest.mark.asyncio
async def test_build_command_and_pipeline_with_pipe(tmp_path):
    import orjson

    app = _make_app(_chat_rows(10))
    app.filepath = "data.jsonl"
    async with app.run_test() as pilot:
        await _pipe(app, pilot, 'dt select - "id=x.source,n=turns(x)"')
        app._apply_filter("x.n >= 2")
        await app.workers.wait_for_complete()
        await pilot.pause()
        app._sort_spec = ("n", True)
        cmd, _ = app._build_command()
        assert cmd == (
            "dt view data.jsonl --pipe='dt select - \"id=x.source,n=turns(x)\"'"
            " --where='x.n >= 2' --sort=-n"
        )
        pcmd, skipped = app._build_pipeline_command()
        assert not skipped
        assert pcmd == (
            "dt select data.jsonl \"id=x.source,n=turns(x)\" | dt filter - 'x.n >= 2'"
            " | dt sort - --by 'x.get('\"'\"'n'\"'\"')' --desc"
        )
        # w 导出: 血缘记下管道与对源文件重跑的命令
        app.filepath = str(tmp_path / "src.jsonl")
        out = tmp_path / "out.jsonl"
        app._apply_export(str(out))
        await app.workers.wait_for_complete()
        await pilot.pause()
        rec = orjson.loads((tmp_path / "out.jsonl.lineage.json").read_bytes())
        op = rec["operations"][0]
        assert op["params"]["pipe"].startswith("dt select") and op["params"]["pipe_rows"] == 10
        assert op["params"]["pipe_command"].startswith(f"dt select {tmp_path}/src.jsonl")
        assert op["input_count"] == 10 and op["output_count"] == 10
        # 管道态不能写回原文件
        app._renames = {"n": "turns_n"}
        assert app._pipe is not None


@pytest.mark.asyncio
async def test_init_pipe_then_initial_constraints():
    src = _ListSource(_chat_rows(20))
    app = ViewApp(
        src,
        src.window(0, 20),
        0,
        20,
        "openai_chat",
        "t.jsonl",
        where=["x.n >= 2"],
        sort="-n",
        pipe='dt select - "id=x.source,n=turns(x)"',
    )
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        await app.workers.wait_for_complete()  # 管道之后的约束扫描
        await pilot.pause()
        assert app._pipe is not None and app.fmt == "generic"
        assert app._wheres == ["x.n >= 2"] and app._sort_spec == ("n", True)
        assert app._seq_total() == 20
