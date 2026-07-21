"""
dt view 的 Textual TUI: 表格 + 详情 master-detail 联动浏览器。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Set

import orjson
from rich.markup import escape
from rich.rule import Rule
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.geometry import Size
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, SelectionList, Static
from textual.widgets.selection_list import Selection

from . import render


def _fmt_num(x: float) -> str:
    """整数去掉小数点, 其余保留 2 位, 让快照数字紧凑。"""
    if x == int(x):
        return str(int(x))
    return f"{x:.2f}"


def _compile_atom(expr: str, fmt: str):
    """编译单个条件 ``字段 运算符 值`` → predicate(row)->bool。

    字段直接用表格里看到的列名 (turns/roles/chars/source 等):
    - 若是**派生列** (计算列, 无字段路径, 如 chars/turns) → 按该列表格显示值比较;
    - 否则当**真实字段路径**交给 _parse_where (标量列名 source, 或深层 messages.#>=2)。
    """
    import operator

    from ..sample import _parse_where

    ops = [
        (">=", operator.ge),
        ("<=", operator.le),
        ("!=", operator.ne),
        ("==", operator.eq),
        (">", operator.gt),
        ("<", operator.lt),
        ("=", operator.eq),
    ]
    field = op = value = None
    for token, _op in ops:
        if token in expr:
            field, _, value = expr.partition(token)
            op = _op
            break
    field_s = (field or "").strip()
    if field_s not in render.derived_columns(fmt):
        return _parse_where(expr)  # 标量列名 / 深层字段路径, 走原生解析

    col = field_s
    value = (value or "").strip()
    try:
        cmp_value = float(value)
        numeric = True
    except ValueError:
        cmp_value = value
        numeric = False

    def predicate(row) -> bool:
        if not isinstance(row, dict):
            return False
        cell = render.row_cells(0, row, fmt, [col])[0]
        if cell == "":
            return False
        if numeric:
            try:
                return op(float(cell), cmp_value)
            except (ValueError, TypeError):
                return False
        return op(str(cell), str(cmp_value))

    return predicate


def _compile_where(expr: str, fmt: str):
    """把筛选表达式编译成 predicate(row)->bool, 支持 ``and``/``or`` 多条件组合。

    用带空格的 `` and `` / `` or `` 分隔 (避免误伤值内子串如 source==android);
    ``and`` 优先级高于 ``or`` (标准语义, 不支持括号)。每个子条件形如 ``列名 运算符 值``,
    列名取表头所见 —— 这样 ``turns>=6 and chars<2000`` 这类多列筛选直接可写。
    """
    import re

    or_groups = []
    for or_part in re.split(r"\s+or\s+", expr, flags=re.IGNORECASE):
        ands = [
            _compile_atom(a.strip(), fmt)
            for a in re.split(r"\s+and\s+", or_part, flags=re.IGNORECASE)
        ]
        or_groups.append(ands)

    def predicate(row) -> bool:
        return any(all(p(row) for p in ands) for ands in or_groups)

    return predicate


class FastDataTable(DataTable):
    """定宽列 + 定高行专用: 跳过 textual 对每个 cell 的 measure。

    dt view 首屏/翻页的主瓶颈: textual 的 _update_dimensions 会对每个新增 cell
    调 measure() 更新 column.content_width (2万行 x 列 = 十几万次)。但定宽列的
    render_width 恒为 width, content_width 从不被 get_render_width 读取——这些
    measure 是纯浪费 (占首屏耗时的 2/3)。这里只保留刷新 virtual_size 的部分。

    前提 (dt view 始终满足): 所有列显式定宽 (_add_columns 传 width), 行默认
    height=1 非 auto_height。若引入 auto_width 列或 auto_height 行, 需回退父类实现。
    """

    def _update_dimensions(self, new_rows) -> None:
        for row_key in new_rows:
            row = self.rows.get(row_key)
            if row is not None and row.label is not None:
                self._labelled_row_exists = True
        self._line_cache.clear()
        self._styles_cache.clear()
        data_cells_width = sum(c.get_render_width(self) for c in self.columns.values())
        header_height = self.header_height if self.show_header else 0
        self.virtual_size = Size(
            data_cells_width + self._row_label_column_width,
            self._total_row_height + header_height,
        )


_HELP = """[b]dt view 快捷键[/b]

  ↑/↓  j/k     选行 (详情联动)
  PgUp/PgDn    整页      d/u (或 Ctrl+d/u)  半屏
  g/G          首/末行   Tab  切换焦点 (滚动长对话)
  ] / [        下/上一窗口 (大文件翻页)   :  跳到行号 (-1 为末行)
  n / N        详情下/上一字段 (精确定位, 底部字段也可达; 亦可鼠标点击选中)
  y            复制当前样本 JSON 到剪贴板
  v            多选样本 (j/k 扩展选区), y 复制多条, Esc 取消
  s            排序 (输入列名, 加 - 反向, 仅当前窗口内)
  S            列快照 (某列的 n·min·max·mean·非空率, 当前浏览序列; 完整分布用 dt stats)
  /            全量搜索 (子串, 全字段, 扫描整个文件 → 命中子集)
  f            全量筛选 (扫全文件 → 命中子集): 列名取表头所见
                 单条件  列名 运算符 值   运算符: > >= < <= == != =
                 例: chars>2000 · turns>=6 · source==alpaca · messages.#>=2(深层字段)
                 多条件  and / or 组合   例: turns>=6 and chars<2000
  Esc          (扫描时) 取消扫描
  Enter        放大当前样本 (Esc 返回)
  z            切换 上下 / 左右 布局
  +/-          调整表格/详情两区大小
  c            选列 (勾选面板, 同时作用于表格和详情)
  r            清除筛选子集/排序, 回到全量浏览
  ?            帮助      q  退出
"""


class _FieldStatic(Static):
    """详情里的一个字段块。自己处理点击 (self 即被点字段, 无需坐标反查, 同 DataTable 选行)。"""

    def __init__(self, renderable, field_name: str):
        # 不设 id: remove_children 是异步卸载, 固定 id 会与新 mount 的 widget 撞 DuplicateIds
        super().__init__(renderable, classes="detail-field")
        self._field_name = field_name

    def on_click(self, event) -> None:
        self.app.select_detail_field(self)  # 通知 app 选中本字段
        event.stop()


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
            sl.add_option(Selection(Text(col), col, col not in self._hidden))
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
        Binding("S", "snapshot", "列快照"),
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
        # n/N: 详情内下/上一字段精确定位 (绕过滚动条像素限制, 底部字段也可达)
        Binding("n", "next_field", "下一字段", show=False),
        Binding("N", "prev_field", "上一字段", show=False),
        # 复制到剪贴板: y 复制当前样本 JSON; v 多选样本后 y 复制
        Binding("y", "yank", "复制", show=False),
        Binding("v", "visual", "多选", show=False),
    ]

    def __init__(
        self, source, window: List[Dict], win_offset: int, cap: int, fmt: str, filename: str
    ):
        super().__init__()
        self.source = source  # RowSource: 随机窗口访问, 内存 O(窗口)
        self.cap = cap  # 单窗口行数
        self.win_offset = win_offset  # 当前窗口在"当前浏览序列"中的起始位置 (0-based)
        self.all_rows = window  # 当前窗口已 parse 的行
        # 当前浏览序列: subset=None 时为原始文件连续窗口; 否则为全量筛选命中的全局行号子集。
        # _global_nos 与 all_rows 对齐, 记每行真实全局行号 (供 # 列/跳行两模式统一显示)。
        self._subset: Optional[List[int]] = None
        self._global_nos: List[int] = list(range(win_offset, win_offset + len(window)))
        self._filter_label: Optional[str] = None  # 状态栏显示的全量筛选说明
        self._scan_cancel: Optional[object] = None  # 扫描中的取消 Event (threading.Event)
        self._scan_msg: str = ""  # 扫描进度文案 (worker 线程回填, 状态栏展示)
        self.fmt = fmt
        self.filename = filename
        self.columns = render.build_columns(window, fmt)  # 列固定自首窗口 (数据集 schema 稳定)
        self._hidden: Set[str] = set()  # 被折叠的列名 (同时作用于表格和详情)
        self.view_indices: List[int] = list(range(len(window)))
        self._sort_label: Optional[str] = None  # 状态栏显示的排序说明
        self._prompt_mode: Optional[str] = None
        self._split = 13  # 表格占比 (总 20 份, 每份 5%), 默认表格 65% : 详情 35%
        # 详情每字段一个 Static widget (真实布局, 无测量误差); 锚点 {字段名: 起始行} 由布局算出
        self._field_widgets: List[Static] = []
        self._cur_anchors: Dict[str, int] = {}
        self._field_i = 0  # 当前字段索引 (滚动时同步顶部字段, n/N/点击 精确接管)
        self._nav_lock = False  # 导航/定位期间抑制 scroll_y watch 回退当前字段
        self._visual_anchor: Optional[int] = (
            None  # visual 多选起点 (view_indices 位置); None=非选择态
        )

    def _cells(self, idx: int, vis: List[str]) -> List[str]:
        """取窗口内第 idx 行的单元格, ``#`` 列显示真实全局行号 (两种浏览模式统一)。"""
        return render.row_cells(
            idx, self.all_rows[idx], self.fmt, vis, row_no=self._global_nos[idx]
        )

    def _seq_total(self) -> int:
        """当前浏览序列总长: 子集态为命中数, 否则为文件总行数。"""
        return len(self._subset) if self._subset is not None else self.source.total

    def compose(self) -> ComposeResult:
        with Vertical(id="main"):
            yield FastDataTable(id="table", cursor_type="row", zebra_stripes=True)
            yield VerticalScroll(id="detail")  # 每字段一个 Static, 动态挂载 (真实布局定位)
        yield Input(id="prompt")
        yield Static(id="status")

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        self._add_columns(table)
        self._populate()
        self._apply_split()
        # 详情滚动时同步当前字段并刷新状态栏 (拖动/翻页均触发)
        self.watch(self.query_one("#detail", VerticalScroll), "scroll_y", self._on_detail_scroll)
        table.focus()

    def _visible_columns(self) -> List[str]:
        return [c for c in self.columns if c not in self._hidden]

    def _add_columns(self, table: DataTable) -> None:
        """显式给每列宽度, 避免 DataTable 对全表自动测量 (大文件会两阶段闪烁 + 卡顿)。"""
        vis = self._visible_columns()
        for name, w in zip(vis, self._column_widths(vis)):
            table.add_column(Text(name), width=w)

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
                # # 列是全局行号, 最大值取当前窗口的真实全局行号 (子集态可能很大), 不靠采样——
                # 否则采样只看前 200 行, 宽度按 3 位数估算, 上万的行号会显示不下被截断。
                max_no = (max(self._global_nos) + 1) if self._global_nos else 1
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
            # 包成 Text 绕过 DataTable 的 markup 解析 (数据含 [/xxx] 会 MarkupError)
            table.add_row(*(Text(c) for c in self._cells(idx, vis)), key=str(pos))
        self._update_status()
        if self.view_indices:
            self._refresh_detail(0)

    def _field_names(self) -> List[str]:
        return [w._field_name for w in self._field_widgets]

    def _recompute_anchors(self) -> int:
        """从真实布局高度累加每字段起始行 (widget.size.height, 无测量误差)。返回总高度。"""
        detail = self.query_one("#detail", VerticalScroll)
        anchors: Dict[str, int] = {}
        y = 0
        for w in detail.children:
            name = getattr(w, "_field_name", None)
            if name is not None:
                anchors[name] = y
            y += w.size.height  # 含字段间分隔 widget 的高度
        self._cur_anchors = anchors
        return y

    def _top_field(self, anchors: Dict[str, int], y: int) -> Optional[str]:
        """滚动位置 y 之上最近的字段名 (顶部可见字段)。"""
        top = None
        for name, start in anchors.items():
            if start <= y:
                top = name
            else:
                break
        return top

    def _current_field(self) -> Optional[str]:
        """当前字段名 (由 _field_i 索引; 滚动同步顶部字段, n/N/点击 精确接管)。"""
        names = self._field_names()
        return names[self._field_i] if 0 <= self._field_i < len(names) else None

    def _on_detail_scroll(self) -> None:
        """详情滚动: 非导航态下把当前字段同步为顶部可见字段, 再刷新状态栏。"""
        if not self._nav_lock:
            try:
                detail = self.query_one("#detail", VerticalScroll)
            except NoMatches:
                return  # DOM 卸载中 (watch 在 teardown 后触发)
            top = self._top_field(self._cur_anchors, detail.scroll_offset.y)
            names = self._field_names()
            self._field_i = names.index(top) if top in names else 0
        self._update_status()

    def _refresh_detail(self, cursor_row: int) -> None:
        if not (0 <= cursor_row < len(self.view_indices)):
            return
        try:
            detail = self.query_one("#detail", VerticalScroll)
        except NoMatches:
            return  # DataTable 高亮事件可能在 teardown 后触发
        idx = self.view_indices[cursor_row]
        prev_field = self._current_field()  # 切样本前当前字段, 新样本对齐同名字段
        # 整个切样本+定位期间抑制 scroll 反查, 避免 mount/布局微调把当前字段冲成顶部字段
        self._nav_lock = True
        detail.remove_children()
        sections = render.render_detail_sections(self.all_rows[idx], self.fmt, hidden=self._hidden)
        self._field_widgets = []
        to_mount: List[Static] = []
        for i, (name, rend) in enumerate(sections):
            if i:
                to_mount.append(Static(Rule(style="dim"), classes="detail-sep"))
            w = _FieldStatic(rend, name)  # 字段块自处理点击
            self._field_widgets.append(w)
            to_mount.append(w)
        if to_mount:
            detail.mount(*to_mount)
        # 布局完成后 (widget.size 才确定): 算真实锚点 → 定位到绑定字段 → 刷新状态栏
        self.call_after_refresh(self._after_detail_render, prev_field)

    def _after_detail_render(self, prev_field: Optional[str]) -> None:
        if not self.is_running or not self.screen_stack:
            self._nav_lock = False  # 确保解锁, 否则后续滚动无响应
            return  # app/screen 卸载中 (call_after_refresh 在 teardown 后触发)
        total = self._recompute_anchors()
        if self._field_widgets and total == 0:
            # 新版 textual 中 mount 后一帧布局可能尚未完成 (size 全 0), 再等一帧重算
            self.call_after_refresh(self._after_detail_render, prev_field)
            return
        names = self._field_names()
        self._field_i = names.index(prev_field) if prev_field in names else 0
        self._scroll_to_field_i()
        self._update_status()
        # 定位稳定后一帧再解锁 (期间的布局微调 scroll 不冲当前字段)
        self.call_after_refresh(self._unlock_nav)

    def _scroll_to_field_i(self) -> None:
        """把当前字段 widget 顶部对齐视口顶 (底部字段自动 clamp 可见)。"""
        if not self._field_widgets:
            return
        detail = self.query_one("#detail", VerticalScroll)
        detail.scroll_to_widget(self._field_widgets[self._field_i], top=True, animate=False)

    def action_next_field(self) -> None:
        self._goto_field(self._field_i + 1)

    def action_prev_field(self) -> None:
        self._goto_field(self._field_i - 1)

    def _goto_field(self, i: int) -> None:
        """精确跳到第 i 个字段 (绕过滚动条像素限制, 底部字段 clamp 但可见)。"""
        if not self._field_widgets:
            return
        self._field_i = max(0, min(i, len(self._field_widgets) - 1))
        self._nav_lock = True  # 抑制本次滚动触发的反查回退当前字段
        self._scroll_to_field_i()
        self._update_status()
        self.call_after_refresh(self._unlock_nav)

    def _unlock_nav(self) -> None:
        self._nav_lock = False

    def select_detail_field(self, widget) -> None:
        """选中被点击的详情字段块 (由 _FieldStatic.on_click 调用)。"""
        if widget in self._field_widgets:
            self._field_i = self._field_widgets.index(widget)
            self._update_status()

    def _update_status(self) -> None:
        # scroll_y watch / call_after_refresh 可能在 DOM 卸载后触发, widget 不存在则跳过
        try:
            status = self.query_one("#status", Static)
        except NoMatches:
            return
        total = self.source.total
        win = len(self.all_rows)
        seq_total = self._seq_total()
        parts = [f"[b]{escape(self.filename)}[/b]", f"格式:{self.fmt}"]
        if self._scan_msg:  # 扫描进行中: 只显文件名 + 进度, 醒目
            parts.append(f"[reverse] {escape(self._scan_msg)} [/reverse]")
            status.update(Text.from_markup("  ·  ".join(parts)))
            return
        if self._visual_anchor is not None:  # 多选态: 醒目显示选区范围
            cur = self.query_one("#table", DataTable).cursor_row
            lo, hi = sorted((self._visual_anchor, cur))
            parts.append(
                f"[reverse] VISUAL {lo + 1}–{hi + 1} ({hi - lo + 1}条) y复制 Esc取消 [/reverse]"
            )
        if self._subset is not None:  # 全量筛选子集态: 命中数 + 占比
            pct = 100 * len(self._subset) / total if total else 0
            parts.append(
                f"[green]{escape(self._filter_label or '筛选')}: "
                f"命中 {len(self._subset)}/{total} ({pct:.1f}%)[/green]"
            )
        if seq_total > win:  # 多窗口: 显示当前序列内的窗口范围
            parts.append(f"窗口 [{self.win_offset + 1}–{self.win_offset + win}]/{seq_total}")
            parts.append("[dim]]/[ 翻窗口·: 跳行[/dim]")
        elif self._subset is None:
            parts.append(f"{total} 行")
        if self._sort_label:
            parts.append(f"排序:{escape(self._sort_label)}")
        # 详情当前字段 (滚动同步顶部字段, n/N 精确接管)
        cur_field = self._current_field()
        if cur_field:
            parts.append(f"[cyan]字段:{escape(cur_field)}[/cyan]")
        parts.append("[dim]? 帮助[/dim]")
        status.update(Text.from_markup("  ·  ".join(parts)))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._refresh_detail(event.cursor_row)
        if self._visual_anchor is not None:  # 多选态下移动光标, 实时更新选区范围
            self._update_status()

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
            self.notify(escape(f"无此列: {name} (可选: {', '.join(vis)})"), severity="error")
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
        self.notify(escape(f"按 {name} 排序{' (反向)' if desc else ''}"))
        self._populate()

    def action_reset(self) -> None:
        """清除全量筛选子集与排序, 回到文件开头的原始浏览。"""
        was_filtered = self._subset is not None
        self._subset = None
        self._filter_label = None
        self._sort_label = None
        self._load_window(0)
        self.notify("已重置" + (" (退出筛选子集)" if was_filtered else ""))

    # ------------------------------------------------------------------ #
    # 复制到剪贴板 (y 当前样本; v 多选后 y 复制多条; 走 OSC52, 支持 SSH)
    # ------------------------------------------------------------------ #
    def _clipboard_osc52(self, text: str) -> str:
        """构造 OSC52 序列; 在 tmux/screen 内包 DCS passthrough 直穿到外层终端。

        Textual 只发裸 OSC52, 会被 tmux 拦截; 这里检测复用环境做穿透包装
        (需 tmux ``set -g allow-passthrough on``), 让 Ghostty 等支持 OSC52 的终端收到。
        """
        import base64

        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        seq = f"\x1b]52;c;{b64}\a"
        if os.environ.get("TMUX"):  # tmux: \ePtmux;<每个 ESC 翻倍的原序列>\e\\
            return "\x1bPtmux;" + seq.replace("\x1b", "\x1b\x1b") + "\x1b\\"
        if os.environ.get("STY"):  # GNU screen: \eP<原序列>\e\\
            return "\x1bP" + seq + "\x1b\\"
        return seq

    def _copy_clipboard(self, text: str) -> None:
        """写系统剪贴板 (OSC52, 支持 SSH); tmux/screen 下自动 passthrough。"""
        driver = getattr(self, "_driver", None)
        if driver is not None:
            driver.write(self._clipboard_osc52(text))

    def _copy_samples(self, positions) -> None:
        """把 view_indices 中若干位置的样本按 NDJSON (每行一条) 复制到剪贴板。"""
        lines = [
            orjson.dumps(self.all_rows[self.view_indices[p]]).decode("utf-8")
            for p in positions
            if 0 <= p < len(self.view_indices)
        ]
        if not lines:
            return
        self._copy_clipboard("\n".join(lines))
        self.notify(f"已复制 {len(lines)} 条样本到剪贴板")

    def action_yank(self) -> None:
        table = self.query_one("#table", DataTable)
        if self._visual_anchor is not None:  # visual: 复制选区
            lo, hi = sorted((self._visual_anchor, table.cursor_row))
            self._copy_samples(range(lo, hi + 1))
            self._visual_anchor = None
        else:  # 普通: 复制当前样本
            self._copy_samples([table.cursor_row])
        self._update_status()

    def action_visual(self) -> None:
        table = self.query_one("#table", DataTable)
        if table.has_class("hidden"):  # 详情放大态不进多选
            return
        # 再按 v 取消; 否则以当前行为锚点进入多选
        self._visual_anchor = None if self._visual_anchor is not None else table.cursor_row
        self._update_status()

    # ------------------------------------------------------------------ #
    # 大文件窗口翻页 (偏移索引 → 任意位置秒开, 内存 O(窗口))
    # ------------------------------------------------------------------ #
    def _load_window(self, offset: int) -> None:
        """加载"当前浏览序列"中以位置 offset 为起点的窗口, 重置排序并重填表格。

        原始态: 位置即文件行号, 走 source.window 顺序读。
        子集态: 位置为子集内序号, 取 subset[offset:] 的全局行号经 rows_at 拉取。
        """
        seq_total = self._seq_total()
        offset = max(0, min(offset, seq_total - 1)) if seq_total else 0
        if self._subset is None:
            rows = self.source.window(offset, self.cap)
            nos = list(range(offset, offset + len(rows)))
        else:
            picked = self._subset[offset : offset + self.cap]
            rows = self.source.rows_at(picked)
            nos = picked
        if not rows:
            return
        self.win_offset = offset
        self.all_rows = rows
        self._global_nos = nos
        self.view_indices = list(range(len(rows)))
        self._sort_label = None
        self._populate()
        self.query_one("#table", DataTable).move_cursor(row=0)

    def action_next_window(self) -> None:
        nxt = self.win_offset + len(self.all_rows)
        if nxt >= self._seq_total():
            self.notify("已是最后一个窗口")
            return
        self._load_window(nxt)

    def action_prev_window(self) -> None:
        if self.win_offset == 0:
            self.notify("已是第一个窗口")
            return
        self._load_window(max(0, self.win_offset - self.cap))

    def action_jump(self) -> None:
        seq_total = self._seq_total()
        where = "子集内序号" if self._subset is not None else "行号"
        self._open_prompt("jump", f"跳到{where} (1-{seq_total}, 负数从末尾数):")

    def _apply_jump(self, text: str) -> None:
        """跳到当前浏览序列的第 n 个位置 (原始态=文件行号, 子集态=子集内序号)。"""
        try:
            n = int(text)
        except ValueError:
            self.notify(escape(f"无效行号: {text}"), severity="error")
            return
        seq_total = self._seq_total()
        if n < 0:  # 负数从末尾数: -1 = 最后一个
            n = seq_total + n + 1
        g = max(1, min(n, seq_total)) - 1  # 0-based 序列位置
        if self.win_offset <= g < self.win_offset + len(self.all_rows):
            local = g - self.win_offset  # 已在当前窗口: 仅移动光标
            if local in self.view_indices:
                self.query_one("#table", DataTable).move_cursor(row=self.view_indices.index(local))
            else:
                self.notify("该行不在当前筛选结果中")
        else:
            self._load_window(g)  # 跳出窗口: 以目标位置为窗口首行加载

    def action_zoom(self) -> None:
        self.query_one("#table", DataTable).add_class("hidden")
        self.query_one("#detail", VerticalScroll).add_class("zoomed").focus()

    def action_unzoom(self) -> None:
        if self._scan_cancel is not None:  # Esc 优先取消进行中的全量扫描
            self._scan_cancel.set()
            return
        if self._visual_anchor is not None:  # Esc 再取消多选
            self._visual_anchor = None
            self._update_status()
            return
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
        self._open_prompt("search", "全量搜索子串 (全字段, 扫描整个文件):")

    def action_filter(self) -> None:
        self._open_prompt(
            "filter",
            "全量筛选 列名(表头所见) 运算符 值; and/or 组合 (如 turns>=6 and chars<2000):",
        )

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
        if mode == "snapshot":  # 空回车用默认列, 故先于空值守卫分发
            self._apply_snapshot(text)
            return
        if not text:
            return
        if mode == "search":
            self._apply_search(text)
        elif mode == "filter":
            self._apply_filter(text)
        elif mode == "sort":
            self._apply_sort(text)
        elif mode == "snapshot":
            self._apply_snapshot(text)
        elif mode == "jump":
            self._apply_jump(text)

    def _apply_search(self, text: str) -> None:
        low = text.lower()
        vis = self._visible_columns()
        fmt = self.fmt

        def predicate(row: Dict) -> bool:
            return any(low in c.lower() for c in render.row_cells(0, row, fmt, vis))

        self._start_scan(predicate, f"搜索 '{text}'")

    def _apply_filter(self, expr: str) -> None:
        try:
            fn = _compile_where(expr, self.fmt)
        except ValueError as e:
            self.notify(escape(str(e)), severity="error")
            return
        self._start_scan(fn, f"筛选 '{expr}'")

    # ------------------------------------------------------------------ #
    # 全量筛选/搜索: worker 线程扫全文件, 命中的全局行号聚成可分页子集
    # ------------------------------------------------------------------ #
    def _start_scan(self, predicate, label: str) -> None:
        """启动全量扫描: 逐行 (iter_all 枚举号即全局行号) 应用 predicate, 收集命中行号。

        跑在 worker 线程避免阻塞 UI; 进度经 call_from_thread 回填状态栏; Esc 可取消。
        """
        import threading

        if self._scan_cancel is not None:  # 已有扫描在跑, 忽略
            return
        cancel = threading.Event()
        self._scan_cancel = cancel
        total = self.source.total
        self._set_scan_msg(f"扫描中 0/{total} (Esc 取消)")

        def worker() -> None:
            matches: List[int] = []
            for i, row in enumerate(self.source.iter_all()):
                if cancel.is_set():
                    self.call_from_thread(self._on_scan_done, None, label, True)
                    return
                try:
                    if predicate(row):
                        matches.append(i)
                except Exception:  # noqa: BLE001  单行畸形不该中断整轮扫描
                    pass
                if i % 5000 == 0:
                    self.call_from_thread(
                        self._set_scan_msg,
                        f"扫描中 {i + 1}/{total} · 命中 {len(matches)} (Esc 取消)",
                    )
            self.call_from_thread(self._on_scan_done, matches, label, False)

        self.run_worker(worker, thread=True, exclusive=True, group="scan")

    def _set_scan_msg(self, msg: str) -> None:
        self._scan_msg = msg
        self._update_status()

    def _on_scan_done(self, matches: Optional[List[int]], label: str, cancelled: bool) -> None:
        self._scan_cancel = None
        self._scan_msg = ""
        if cancelled:
            self.notify("已取消扫描")
            self._update_status()
            return
        if not matches:
            self.notify(escape(f"{label}: 无匹配, 保持原视图"))
            self._update_status()
            return
        self._subset = matches
        self._filter_label = label
        self._load_window(0)
        self.notify(escape(f"{label}: {len(matches)} 条命中 (全量)"))

    # ------------------------------------------------------------------ #
    # 列快照: 对当前浏览序列的某列给一行 n·min·max·mean·非空率 (即时决策用)
    # 完整分布 (直方图/分位数/value_counts) 归 dt stats, 此处刻意不做。
    # ------------------------------------------------------------------ #
    def _iter_sequence(self, cancel):
        """产出当前浏览序列的行: 子集态按 subset 分块 rows_at 拉取, 否则 iter_all 全量。"""
        if self._subset is None:
            yield from self.source.iter_all()
        else:
            for start in range(0, len(self._subset), 1000):
                if cancel.is_set():
                    return
                yield from self.source.rows_at(self._subset[start : start + 1000])

    def action_snapshot(self) -> None:
        default = next((c for c in self._visible_columns() if c not in ("#",)), "chars")
        self._open_prompt("snapshot", f"列快照 (列名, 默认 {default}; 完整分布用 dt stats):")

    def _apply_snapshot(self, col: str) -> None:
        import threading

        col = col.strip() or next((c for c in self._visible_columns() if c != "#"), "")
        if col not in self.columns:
            self.notify(
                escape(f"无此列: {col} (可选: {', '.join(self.columns)})"), severity="error"
            )
            return
        if self._scan_cancel is not None:
            return
        ci = self.columns.index(col)
        cols = self.columns
        fmt = self.fmt
        cancel = threading.Event()
        self._scan_cancel = cancel
        seq_total = self._seq_total()
        self._set_scan_msg(f"快照扫描中 0/{seq_total} (Esc 取消)")

        def worker() -> None:
            n = nonempty = nnum = 0
            vmin = vmax = vsum = None
            for row in self._iter_sequence(cancel):
                if cancel.is_set():
                    self.call_from_thread(self._on_snapshot_done, col, None, True)
                    return
                n += 1
                cell = render.row_cells(0, row, fmt, cols)[ci] if isinstance(row, dict) else ""
                if cell != "":
                    nonempty += 1
                try:
                    x = float(cell)
                except (ValueError, TypeError):
                    pass
                else:
                    nnum += 1
                    vsum = x if vsum is None else vsum + x
                    vmin = x if vmin is None else min(vmin, x)
                    vmax = x if vmax is None else max(vmax, x)
                if n % 5000 == 0:
                    self.call_from_thread(
                        self._set_scan_msg, f"快照扫描中 {n}/{seq_total} (Esc 取消)"
                    )
            stats = (n, nonempty, nnum, vmin, vmax, vsum)
            self.call_from_thread(self._on_snapshot_done, col, stats, False)

        self.run_worker(worker, thread=True, exclusive=True, group="scan")

    def _on_snapshot_done(self, col: str, stats, cancelled: bool) -> None:
        self._scan_cancel = None
        self._scan_msg = ""
        if cancelled:
            self.notify("已取消快照")
            self._update_status()
            return
        n, nonempty, nnum, vmin, vmax, vsum = stats
        scope = "子集" if self._subset is not None else "全量"
        rate = f"{100 * nonempty / n:.1f}%" if n else "-"
        if nnum:
            mean = vsum / nnum
            body = (
                f"{col} [{scope} n={n}]  min={_fmt_num(vmin)}  max={_fmt_num(vmax)}  "
                f"mean={_fmt_num(mean)}  非空 {rate}"
            )
        else:  # 非数值列: 无 min/max/mean, 引导去 dt stats 看分布
            body = f"{col} [{scope} n={n}]  非数值列, 非空 {rate} · 完整分布用 dt stats"
        self.notify(escape(body), timeout=8)
        self._update_status()
