"""
dt view 的 Textual TUI: 表格 + 详情 master-detail 联动浏览器。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, SelectionList, Static
from textual.widgets.selection_list import Selection

from . import render

_HELP = """[b]dt view 快捷键[/b]

  ↑/↓  j/k     选行 (详情联动)
  PgUp/PgDn    整页      d/u (或 Ctrl+d/u)  半屏
  g/G          首/末行   Tab  切换焦点 (滚动长对话)
  ] / [        下/上一窗口 (大文件翻页)   :  跳到行号
  s            排序 (输入列名, 加 - 反向)
  /            搜索 (子串, 全字段, 仅当前窗口)
  f            筛选 (where 表达式, 如 messages.#>=2, 仅当前窗口)
  Enter        放大当前样本 (Esc 返回)
  z            切换 上下 / 左右 布局
  +/-          调整表格/详情两区大小
  c            选列 (勾选面板, 同时作用于表格和详情)
  r            清除筛选/排序
  ?            帮助      q  退出
"""


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,q,question_mark", "dismiss", "关闭")]

    def compose(self) -> ComposeResult:
        yield Static(Text.from_markup(_HELP), id="help-box")


class ColumnPicker(ModalScreen):
    """列显示勾选面板: 空格切换, Enter/Esc 应用并关闭。返回可见列名集合。"""

    # priority=True: 抢在 SelectionList 之前处理, 否则 enter 会被它消费而无法关闭
    BINDINGS = [
        Binding("enter,escape,c", "close", "应用", priority=True),
        Binding("a", "all", "全选"),
        Binding("n", "none", "全不选"),
    ]

    def __init__(self, columns: List[str], hidden: Set[str]):
        super().__init__()
        self._columns = columns
        self._hidden = hidden

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield Static("[b]选择要显示的列[/b]", id="picker-title")
            yield SelectionList(id="cols")
            yield Static(
                "[dim]空格 勾选/取消 · a 全选 · n 全不选 · Enter/Esc 应用[/dim]",
                id="picker-hint",
            )

    def on_mount(self) -> None:
        sl = self.query_one(SelectionList)
        for col in self._columns:
            sl.add_option(Selection(col, col, col not in self._hidden))
        sl.focus()

    def action_all(self) -> None:
        self.query_one(SelectionList).select_all()

    def action_none(self) -> None:
        self.query_one(SelectionList).deselect_all()

    def action_close(self) -> None:
        self.dismiss(set(self.query_one(SelectionList).selected))


class ViewApp(App):
    CSS = """
    Screen { layers: base; }
    #main { height: 1fr; }
    #main.horizontal { layout: horizontal; }
    #table { height: 2fr; border: round $primary; }
    #main.horizontal #table { width: 1fr; height: 1fr; }
    #detail { height: 3fr; border: round $secondary; padding: 0 1; }
    #main.horizontal #detail { width: 1fr; height: 1fr; }
    #detail.zoomed { height: 1fr; }
    #table.hidden { display: none; }
    #prompt { dock: bottom; display: none; }
    #prompt.active { display: block; }
    #status { dock: bottom; height: 1; background: $panel; color: $text-muted; padding: 0 1; }
    #help-box { padding: 1 2; border: round $primary; background: $surface; width: auto; }
    ColumnPicker { align: center middle; }
    #picker-box { width: 56; height: auto; max-height: 85%; border: round $primary;
                  background: $surface; padding: 1 2; }
    #picker-title { text-align: center; width: 1fr; margin-bottom: 1; }
    #picker-box #cols { width: 1fr; height: auto; max-height: 20; background: $surface; }
    #picker-hint { text-align: center; width: 1fr; margin-top: 1; }
    """

    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("question_mark", "help", "帮助"),
        Binding("slash", "search", "搜索"),
        Binding("f", "filter", "筛选"),
        Binding("s", "sort", "排序"),
        Binding("z", "toggle_layout", "布局"),
        Binding("r", "reset", "重置"),
        Binding("enter", "zoom", "放大"),
        Binding("escape", "unzoom", "返回", show=False),
        Binding("g", "top", "首行", show=False),
        Binding("G", "bottom", "末行", show=False),
        # DataTable 内置只认箭头键, 这里补 vim 键 (与帮助屏承诺一致)
        Binding("j", "cursor_down", "下移", show=False),
        Binding("k", "cursor_up", "上移", show=False),
        # h/l 与左右方向键一致: 水平滚动表格 (列超宽时可见右侧列)
        Binding("h", "scroll_left", "左滚", show=False),
        Binding("l", "scroll_right", "右滚", show=False),
        # 调整表格/详情两区大小 (竖排调高度, 横排调宽度)
        Binding("plus", "grow_table", "表格+", show=False),
        Binding("equals_sign", "grow_table", "表格+", show=False),
        Binding("minus", "shrink_table", "表格-", show=False),
        # 半屏滚动: d/u 单键 (ctrl+d/u 同义, 照顾 vim 习惯); PgUp/PgDn 整页
        Binding("d", "half_down", "半屏下", show=False),
        Binding("u", "half_up", "半屏上", show=False),
        Binding("ctrl+d", "half_down", "半屏下", show=False),
        Binding("ctrl+u", "half_up", "半屏上", show=False),
        # 列显示选择器: c 打开勾选面板 (同时作用于表格列和详情字段)
        Binding("c", "columns", "选列", show=False),
        # 大文件窗口翻页: ] 下一窗口, [ 上一窗口, : 跳到指定行号
        Binding("right_square_bracket", "next_window", "下一窗口", show=False),
        Binding("left_square_bracket", "prev_window", "上一窗口", show=False),
        Binding("colon", "jump", "跳行", show=False),
    ]

    def __init__(
        self, source, window: List[Dict], win_offset: int, cap: int, fmt: str, filename: str
    ):
        super().__init__()
        self.source = source  # RowSource: 随机窗口访问, 内存 O(窗口)
        self.cap = cap  # 单窗口行数
        self.win_offset = win_offset  # 当前窗口在全局的起始行 (0-based)
        self.all_rows = window  # 当前窗口已 parse 的行
        self.fmt = fmt
        self.filename = filename
        self.columns = render.build_columns(window, fmt)  # 列固定自首窗口 (数据集 schema 稳定)
        self._hidden: Set[str] = set()  # 被折叠的列名 (同时作用于表格和详情)
        self.view_indices: List[int] = list(range(len(window)))
        self._sort_label: Optional[str] = None  # 状态栏显示的排序说明
        self._prompt_mode: Optional[str] = None
        self._split = 13  # 表格占比 (总 20 份, 每份 5%), 默认表格 65% : 详情 35%

    def _cells(self, idx: int, vis: List[str]) -> List[str]:
        """取窗口内第 idx 行的单元格, ``#`` 列显示全局行号。"""
        return render.row_cells(
            idx, self.all_rows[idx], self.fmt, vis, row_no=self.win_offset + idx
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="main"):
            yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="detail"):
                yield Static(id="detail-body")
        yield Input(id="prompt")
        yield Static(id="status")

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        self._add_columns(table)
        self._populate()
        self._apply_split()
        table.focus()

    def _visible_columns(self) -> List[str]:
        return [c for c in self.columns if c not in self._hidden]

    def _add_columns(self, table: DataTable) -> None:
        """显式给每列宽度, 避免 DataTable 对全表自动测量 (大文件会两阶段闪烁 + 卡顿)。"""
        vis = self._visible_columns()
        for name, w in zip(vis, self._column_widths(vis)):
            table.add_column(name, width=w)

    def _column_widths(self, vis: List[str]) -> List[int]:
        """自适应列宽: 采样估算每列自然宽, 再按可用屏宽做 max-min 公平分配。

        - 自然宽 = max(表头, 采样单元格显示宽), 上限 CAP
        - 若自然宽总和 <= 预算: 直接用 (无需压缩)
        - 否则: 窄列拿满自然宽, 宽文本列平分剩余预算 (谁也不独占)
        性能 O(采样行 x 列数), 采样封顶 200 行。
        """
        from rich.cells import cell_len

        CAP = 80
        sample = [self._cells(idx, vis) for idx in self.view_indices[:200]]
        naturals = []
        for ci, name in enumerate(vis):
            if name == "#":
                # # 列是全局行号, 最大值可预测 (窗口末行), 不靠采样——否则采样只看前 200 行,
                # 宽度按 3 位数估算, 窗口内上万的行号会显示不下被截断。
                max_no = self.win_offset + len(self.all_rows)
                naturals.append(max(cell_len(name), len(str(max_no))))
                continue
            w = cell_len(name)
            for cells in sample:
                w = max(w, cell_len(cells[ci]))
            naturals.append(min(max(w, 1), CAP))

        # 预算 = 屏宽 - 表格边框(2) - 竖直滚动条(2) - 每列内边距(2×列数)
        # 漏掉滚动条会让列宽总和正好等于内容区, 竖条再占 2 列 → 触发横向滚动条(溢出一点点)
        avail = self.size.width or 120
        budget = avail - 4 - 2 * len(vis)
        if budget <= 0 or sum(naturals) <= budget:
            return naturals

        # 被压的宽列至少留 MIN_COL_W, 否则只剩省略号无信息量; 但天然更窄的列不硬撑 (取其自然宽)。
        MIN_COL_W = 8
        widths = [0] * len(vis)
        remaining, nrem = budget, len(vis)
        for i in sorted(range(len(vis)), key=lambda i: naturals[i]):
            share = remaining // nrem
            floor = min(MIN_COL_W, naturals[i])
            widths[i] = naturals[i] if naturals[i] <= share else max(share, floor)
            remaining -= widths[i]
            nrem -= 1
        return widths

    def _apply_split(self) -> None:
        """按 self._split 设置两区大小 (竖排改高度, 横排改宽度)。"""
        main = self.query_one("#main", Vertical)
        table = self.query_one("#table", DataTable)
        detail = self.query_one("#detail", VerticalScroll)
        t, d = self._split, 20 - self._split
        if main.has_class("horizontal"):
            table.styles.width, table.styles.height = f"{t}fr", "1fr"
            detail.styles.width, detail.styles.height = f"{d}fr", "1fr"
        else:
            table.styles.height, table.styles.width = f"{t}fr", "1fr"
            detail.styles.height, detail.styles.width = f"{d}fr", "1fr"

    def action_grow_table(self) -> None:
        self._split = min(16, self._split + 1)  # 上限表格 80%
        self._apply_split()

    def action_shrink_table(self) -> None:
        self._split = max(4, self._split - 1)  # 下限表格 20%
        self._apply_split()

    # ------------------------------------------------------------------ #
    # 表格填充 / 详情刷新
    # ------------------------------------------------------------------ #
    def _populate(self) -> None:
        table = self.query_one("#table", DataTable)
        table.clear()
        vis = self._visible_columns()
        for pos, idx in enumerate(self.view_indices):
            table.add_row(*self._cells(idx, vis), key=str(pos))
        self._update_status()
        if self.view_indices:
            self._refresh_detail(0)

    def _refresh_detail(self, cursor_row: int) -> None:
        if not (0 <= cursor_row < len(self.view_indices)):
            return
        idx = self.view_indices[cursor_row]
        body = self.query_one("#detail-body", Static)
        body.update(render.render_detail(self.all_rows[idx], self.fmt, hidden=self._hidden))
        self.query_one("#detail", VerticalScroll).scroll_home(animate=False)

    def _update_status(self) -> None:
        total = self.source.total
        win = len(self.all_rows)
        shown = len(self.view_indices)
        parts = [f"[b]{self.filename}[/b]", f"格式:{self.fmt}"]
        if total > win:  # 多窗口: 显示全局窗口范围
            parts.append(f"窗口 [{self.win_offset + 1}–{self.win_offset + win}]/{total}")
            parts.append("[dim]]/[ 翻窗口·: 跳行[/dim]")
        else:
            parts.append(f"{total} 行")
        if shown != win:  # 筛选/搜索子集 (窗口内)
            parts.append(f"[yellow]{shown} 条匹配(仅本窗口)[/yellow]")
        if self._sort_label:
            parts.append(f"排序:{self._sort_label}")
        parts.append("[dim]? 帮助[/dim]")
        self.query_one("#status", Static).update(Text.from_markup("  ·  ".join(parts)))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._refresh_detail(event.cursor_row)

    # ------------------------------------------------------------------ #
    # 动作
    # ------------------------------------------------------------------ #
    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def _table_action(self, name: str) -> None:
        """把 vim 键转调到 DataTable 的光标动作 (仅当详情未放大时)。"""
        table = self.query_one("#table", DataTable)
        if not table.has_class("hidden"):
            getattr(table, f"action_{name}")()

    def action_cursor_down(self) -> None:
        self._table_action("cursor_down")

    def action_cursor_up(self) -> None:
        self._table_action("cursor_up")

    def action_scroll_left(self) -> None:
        self._table_action("scroll_left")

    def action_scroll_right(self) -> None:
        self._table_action("scroll_right")

    def _half_scroll(self, direction: int) -> None:
        """半屏滚动: 详情放大时滚详情, 否则按半屏移动表格光标。"""
        table = self.query_one("#table", DataTable)
        if table.has_class("hidden"):
            d = self.query_one("#detail", VerticalScroll)
            d.scroll_relative(y=direction * max(1, d.size.height // 2), animate=False)
            return
        half = max(1, table.size.height // 2)
        target = table.cursor_row + direction * half
        target = max(0, min(len(self.view_indices) - 1, target))
        table.move_cursor(row=target)

    def action_half_down(self) -> None:
        self._half_scroll(1)

    def action_half_up(self) -> None:
        self._half_scroll(-1)

    def action_top(self) -> None:
        self.query_one("#table", DataTable).move_cursor(row=0)

    def action_bottom(self) -> None:
        self.query_one("#table", DataTable).move_cursor(row=len(self.view_indices) - 1)

    def action_sort(self) -> None:
        self._open_prompt("sort", "排序列名 (加 - 反向, 如 -chars):")

    def _apply_sort(self, text: str) -> None:
        desc = text.startswith("-")
        name = text.lstrip("-").strip()
        vis = self._visible_columns()
        if name not in vis:
            self.notify(f"无此列: {name} (可选: {', '.join(vis)})", severity="error")
            return
        col = vis.index(name)

        def keyfn(idx: int):
            v = self._cells(idx, vis)[col]
            try:
                return (0, float(v))
            except (ValueError, TypeError):
                return (1, str(v))

        self.view_indices.sort(key=keyfn, reverse=desc)
        self._sort_label = f"{name}{'↓' if desc else '↑'}"
        self.notify(f"按 {name} 排序{' (反向)' if desc else ''}")
        self._populate()

    def action_reset(self) -> None:
        self.view_indices = list(range(len(self.all_rows)))
        self._sort_label = None
        self._populate()
        self.notify("已重置")

    # ------------------------------------------------------------------ #
    # 大文件窗口翻页 (偏移索引 → 任意位置秒开, 内存 O(窗口))
    # ------------------------------------------------------------------ #
    def _load_window(self, offset: int) -> None:
        """加载以全局行 offset 为起点的新窗口, 重置筛选/排序并重填表格。"""
        offset = max(0, min(offset, self.source.total - 1))
        rows = self.source.window(offset, self.cap)
        if not rows:
            return
        self.win_offset = offset
        self.all_rows = rows
        self.view_indices = list(range(len(rows)))
        self._sort_label = None
        self._populate()
        self.query_one("#table", DataTable).move_cursor(row=0)

    def action_next_window(self) -> None:
        nxt = self.win_offset + len(self.all_rows)
        if nxt >= self.source.total:
            self.notify("已是最后一个窗口")
            return
        self._load_window(nxt)

    def action_prev_window(self) -> None:
        if self.win_offset == 0:
            self.notify("已是第一个窗口")
            return
        self._load_window(max(0, self.win_offset - self.cap))

    def action_jump(self) -> None:
        self._open_prompt("jump", f"跳到行号 (1-{self.source.total}):")

    def _apply_jump(self, text: str) -> None:
        try:
            n = int(text)
        except ValueError:
            self.notify(f"无效行号: {text}", severity="error")
            return
        g = max(1, min(n, self.source.total)) - 1  # 0-based 全局行
        if self.win_offset <= g < self.win_offset + len(self.all_rows):
            local = g - self.win_offset  # 已在当前窗口: 仅移动光标
            if local in self.view_indices:
                self.query_one("#table", DataTable).move_cursor(row=self.view_indices.index(local))
            else:
                self.notify("该行不在当前筛选结果中")
        else:
            self._load_window(g)  # 跳出窗口: 以目标行为窗口首行加载

    def action_zoom(self) -> None:
        self.query_one("#table", DataTable).add_class("hidden")
        self.query_one("#detail", VerticalScroll).add_class("zoomed").focus()

    def action_unzoom(self) -> None:
        self.query_one("#table", DataTable).remove_class("hidden")
        self.query_one("#detail", VerticalScroll).remove_class("zoomed")
        self.query_one("#table", DataTable).focus()

    def action_toggle_layout(self) -> None:
        self.query_one("#main", Vertical).toggle_class("horizontal")
        self._apply_split()

    def action_columns(self) -> None:
        """打开列勾选面板, 应用后同步表格列与详情字段。"""

        def apply(visible: Optional[Set[str]]) -> None:
            if visible is None:
                return
            hidden = set(self.columns) - visible
            if len(hidden) == len(self.columns):  # 不允许全隐藏, 至少留第一列
                hidden.discard(self.columns[0])
            self._hidden = hidden
            self._rebuild_columns()

        self.push_screen(ColumnPicker(self.columns, self._hidden), apply)

    def _rebuild_columns(self) -> None:
        """列可见集变化后重建表头并重填。"""
        table = self.query_one("#table", DataTable)
        table.clear(columns=True)
        self._add_columns(table)
        self._populate()

    def action_search(self) -> None:
        self._open_prompt("search", "搜索子串 (全字段):")

    def action_filter(self) -> None:
        self._open_prompt("filter", "where 表达式 (如 messages.#>=2):")

    def _open_prompt(self, mode: str, placeholder: str) -> None:
        self._prompt_mode = mode
        prompt = self.query_one("#prompt", Input)
        prompt.placeholder = placeholder
        prompt.value = ""
        prompt.add_class("active")
        prompt.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        mode, text = self._prompt_mode, event.value.strip()
        prompt = self.query_one("#prompt", Input)
        prompt.remove_class("active")
        self._prompt_mode = None
        self.query_one("#table", DataTable).focus()
        if not text:
            return
        if mode == "search":
            self._apply_search(text)
        elif mode == "filter":
            self._apply_filter(text)
        elif mode == "sort":
            self._apply_sort(text)
        elif mode == "jump":
            self._apply_jump(text)

    def _apply_search(self, text: str) -> None:
        low = text.lower()

        vis = self._visible_columns()

        def match(idx: int) -> bool:
            return any(low in c.lower() for c in self._cells(idx, vis))

        self.view_indices = [i for i in range(len(self.all_rows)) if match(i)]
        self._populate()
        self.notify(f"搜索 '{text}': {len(self.view_indices)} 条 (仅本窗口)")

    def _apply_filter(self, expr: str) -> None:
        from ..sample import _parse_where

        try:
            fn = _parse_where(expr)
        except ValueError as e:
            self.notify(str(e), severity="error")
            return
        self.view_indices = [
            i for i, r in enumerate(self.all_rows) if isinstance(r, dict) and fn(r)
        ]
        self._populate()
        self.notify(f"筛选 '{expr}': {len(self.view_indices)} 条 (仅本窗口)")
