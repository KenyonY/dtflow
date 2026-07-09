"""
dt view 的 Textual TUI: 表格 + 详情 master-detail 联动浏览器。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static

from . import render

_HELP = """[b]dt view 快捷键[/b]

  ↑/↓  j/k     选行 (详情联动)
  PgUp/PgDn    整页      d/u (或 Ctrl+d/u)  半屏
  g/G          首/末行   Tab  切换焦点 (滚动长对话)
  ←/→  h/l     滚动列
  s            按当前列排序 (再按反向)
  /            搜索 (子串, 全字段)
  f            筛选 (where 表达式, 如 messages.#>=2)
  Enter        放大当前样本 (Esc 返回)
  z            切换 上下 / 左右 布局
  +/-          调整表格/详情两区大小
  r            清除筛选/排序
  ?            帮助      q  退出
"""


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,q,question_mark", "dismiss", "关闭")]

    def compose(self) -> ComposeResult:
        yield Static(Text.from_markup(_HELP), id="help-box")


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
        Binding("h", "cursor_left", "左列", show=False),
        Binding("l", "cursor_right", "右列", show=False),
        # 调整表格/详情两区大小 (竖排调高度, 横排调宽度)
        Binding("plus", "grow_table", "表格+", show=False),
        Binding("equals_sign", "grow_table", "表格+", show=False),
        Binding("minus", "shrink_table", "表格-", show=False),
        # 半屏滚动: d/u 单键 (ctrl+d/u 同义, 照顾 vim 习惯); PgUp/PgDn 整页
        Binding("d", "half_down", "半屏下", show=False),
        Binding("u", "half_up", "半屏上", show=False),
        Binding("ctrl+d", "half_down", "半屏下", show=False),
        Binding("ctrl+u", "half_up", "半屏上", show=False),
    ]

    def __init__(self, rows: List[Dict], fmt: str, filename: str, truncated: bool):
        super().__init__()
        self.all_rows = rows
        self.fmt = fmt
        self.filename = filename
        self.truncated = truncated
        self.columns = render.build_columns(rows, fmt)
        self.view_indices: List[int] = list(range(len(rows)))
        self._sort_col: Optional[int] = None
        self._sort_desc = False
        self._prompt_mode: Optional[str] = None
        self._split = 13  # 表格占比 (总 20 份, 每份 5%), 默认表格 65% : 详情 35%

    def compose(self) -> ComposeResult:
        with Vertical(id="main"):
            yield DataTable(id="table", cursor_type="cell", zebra_stripes=True)
            with VerticalScroll(id="detail"):
                yield Static(id="detail-body")
        yield Input(id="prompt")
        yield Static(id="status")

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.add_columns(*self.columns)
        self._populate()
        self._apply_split()
        table.focus()

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
        for pos, idx in enumerate(self.view_indices):
            cells = render.row_cells(idx, self.all_rows[idx], self.fmt, self.columns)
            table.add_row(*cells, key=str(pos))
        self._update_status()
        if self.view_indices:
            self._refresh_detail(0)

    def _refresh_detail(self, cursor_row: int) -> None:
        if not (0 <= cursor_row < len(self.view_indices)):
            return
        idx = self.view_indices[cursor_row]
        body = self.query_one("#detail-body", Static)
        body.update(render.render_detail(self.all_rows[idx], self.fmt))
        self.query_one("#detail", VerticalScroll).scroll_home(animate=False)

    def _update_status(self) -> None:
        total = len(self.all_rows)
        shown = len(self.view_indices)
        parts = [f"[b]{self.filename}[/b]", f"格式:{self.fmt}", f"{shown}/{total} 行"]
        if self.truncated:
            parts.append(f"[yellow]已截断前 {total} 行[/yellow]")
        if self._sort_col is not None:
            arrow = "↓" if self._sort_desc else "↑"
            parts.append(f"排序:{self.columns[self._sort_col]}{arrow}")
        parts.append("[dim]? 帮助[/dim]")
        self.query_one("#status", Static).update(Text.from_markup("  ·  ".join(parts)))

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        self._refresh_detail(event.coordinate.row)

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

    def action_cursor_left(self) -> None:
        self._table_action("cursor_left")

    def action_cursor_right(self) -> None:
        self._table_action("cursor_right")

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
        table = self.query_one("#table", DataTable)
        col = table.cursor_column
        if self._sort_col == col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col, self._sort_desc = col, False
        name = self.columns[col]

        def keyfn(idx: int):
            cells = render.row_cells(idx, self.all_rows[idx], self.fmt, self.columns)
            v = cells[col]
            try:
                return (0, float(v))
            except (ValueError, TypeError):
                return (1, str(v))

        self.view_indices.sort(key=keyfn, reverse=self._sort_desc)
        self.notify(f"按 {name} 排序")
        self._populate()
        # _populate 重建后光标归零, 移回排序列以便再按 s 切换升降序
        table.move_cursor(row=0, column=col)

    def action_reset(self) -> None:
        self.view_indices = list(range(len(self.all_rows)))
        self._sort_col = None
        self._sort_desc = False
        self._populate()
        self.notify("已重置")

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

    def _apply_search(self, text: str) -> None:
        low = text.lower()

        def match(idx: int) -> bool:
            cells = render.row_cells(idx, self.all_rows[idx], self.fmt, self.columns)
            return any(low in c.lower() for c in cells)

        self.view_indices = [i for i in range(len(self.all_rows)) if match(i)]
        self._populate()
        self.notify(f"搜索 '{text}': {len(self.view_indices)} 条")

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
        self.notify(f"筛选 '{expr}': {len(self.view_indices)} 条")
