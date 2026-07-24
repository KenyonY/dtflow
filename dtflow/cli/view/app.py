"""
dt view 的 Textual TUI: 表格 + 详情 master-detail 联动浏览器。
"""

from __future__ import annotations

import os
import re
from typing import Callable, Dict, List, Optional, Pattern, Set, Tuple

import orjson
from rich.markup import escape
from rich.rule import Rule
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.geometry import Size
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, SelectionList, Static
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
    - 若是**派生列** (计算列, 无字段路径, 如 chars/turns/first_user) → 按该列的值比较;
      ``~=`` (包含) 匹配未截断的完整文本, 不是表格里那 80 字的预览。
    - 否则当**真实字段路径**交给 _parse_where (标量列名 source, 或深层 messages.#>=2)。
    """
    import operator

    from ..sample import _parse_where

    ops = [
        (">=", operator.ge),
        ("<=", operator.le),
        ("!=", operator.ne),
        # 包含; 必须排在 "=" 之前。不区分大小写, 与 _parse_where、/ 搜索、值面板搜索框一致
        ("~=", lambda cell, v: v.lower() in cell.lower()),
        ("==", operator.eq),
        (">", operator.gt),
        ("<", operator.lt),
        ("=", operator.eq),
    ]
    field = op = value = None
    token = ""
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
    if token == "~=":  # 包含永远是字符串语义, 不能把 "2000" 当数字比
        numeric, cmp_value = False, value
    else:
        try:
            cmp_value = float(value)
            numeric = True
        except ValueError:
            cmp_value = value
            numeric = False
    # 包含筛选要看全文 (预览只有 80 字, 截断会静默漏掉靠后的关键词)
    preview = token != "~="

    def predicate(row) -> bool:
        if not isinstance(row, dict):
            return False
        cell = render.row_cells(0, row, fmt, [col], preview=preview)[0]
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

    不支持括号是刻意的: 需要 ``(a or b) and (c or d)`` 时改用多条 where
    (TUI 内连按两次 f, 命令行传两个 --where), 多条之间是 AND。
    """
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


def compile_search(text: str) -> Pattern:
    """搜索词 → 正则。默认按字面子串 (转义), ``re:`` 前缀走正则; 一律不分大小写。

    编译出的 pattern 同时用于两处, 必须同源: 筛选出命中子集, 以及给命中处画黄底。
    非法正则原样抛 re.error, 由调用方提示用户。
    """
    if text.startswith("re:"):
        return re.compile(text[3:], re.IGNORECASE)
    return re.compile(re.escape(text), re.IGNORECASE)


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
  n / N        详情下/上一字段 (对话按条走: msg0/msg1…; 亦可鼠标点击选中)
  *            跳到详情中下一处搜索命中 (命中处画黄底)
  y            复制当前样本 JSON 到剪贴板
  v            多选样本 (j/k 扩展选区), y 复制多条, Esc 取消
  w            导出当前浏览序列 (或多选选区) 到文件, 按扩展名定格式
                 .jsonl 流式写, 几十万行不占内存; 同时写血缘, dt history 可查来源与条件
  C            复制"复现当前视图"的 dt view 命令到剪贴板 (筛选/搜索/排序全带上)
  s            全量排序 (输入列名, 加 - 反向; 扫全文件, 跨窗口有效)
  S            列快照 (某列的 n·min·max·mean·非空率, 当前浏览序列; 完整分布用 dt stats)
  /            全量搜索 (整条记录的每个值, 含 assistant 回复; 不分大小写, re: 前缀走正则)
                 → 命中子集 + 表格/详情里黄底高亮, 再用 * 逐个跳过去
  f            全量筛选 (扫全文件 → 命中子集): 列名取表头所见
                 单条件  列名 运算符 值   运算符: > >= < <= == != = ~=(包含,不分大小写)
                 例: chars>2000 · turns>=6 · source==alpaca · messages.#>=2(深层字段)
                 包含: first_user~=退款 · source~=alpaca · messages[0].content~=报错
                       messages[*].content:join~=词  (搜整段对话, :join 不可省)
                 多条件  and / or 组合   例: turns>=6 and chars<2000
                 可反复按 f 叠加多条 (多条之间是 and; 需要括号语义就拆成多条)
  F / 点列头   列值勾选筛选 (Excel 式): 列出该列唯一值+频次, 勾选保留哪些 → 子集
                 顶部搜索框按子串过滤候选值; 有搜索词时应用 = 只保留勾选的匹配项
                 被筛的列头带 ▾ 标记; 再次打开可加回之前去掉的值 (全选=清除该列筛选)
  Esc          (扫描时) 取消扫描
  Enter        放大当前样本 (Esc 返回)
  z            切换 上下 / 左右 布局
  +/-          调整表格/详情两区大小
  c            选列 (勾选面板, 同时作用于表格和详情)
  r            清除全部筛选/搜索/排序, 回到全量浏览
  ?            帮助      q  退出

  搜索/筛选/排序都是全量的 (扫整个文件, 非仅当前窗口), 且可叠加;
  启动即带条件: dt view f.jsonl --where=... --search=... --sort=-chars
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


def _fit_panel(screen, sl: SelectionList, chrome: int, hard_max: int) -> int:
    """把勾选面板压进当前终端尺寸; 返回列表最终高度。

    面板是 height:auto, 列表却有固定 max-height —— 内容总高一旦超过屏幕,
    超出部分被静默裁剪, 最先没的就是排在最后的按钮行 (矮终端上按钮凭空消失)。
    这里反过来算: 列表能占的 = 屏高 - 固定装饰(chrome, 含边框/标题/提示/按钮行) - 1。

    装不下时按"可推断的先牺牲"排序: 列表压到 3 行 → 去掉提示行(换 2 行) → 窄屏去掉
    全选/全不选按钮(键盘 a/n 仍可用), 始终保住应用/取消。屏高 11 行 / 屏宽 40 列以下
    仍会裁 —— 那种尺寸下 dt view 主界面本身就没法用了, 不做适配。

    对面板的约定 (新加勾选面板时照做, 否则降级不会生效): 提示行 id 为 ``picker-hint``,
    次要按钮 id 以 ``-all`` / ``-none`` 结尾 (如 ``cp-all``/``vf-none``)。
    """
    size = screen.app.size
    avail = size.height - chrome - 1
    if avail < 3:
        screen.query_one("#picker-hint", Static).display = False
        avail += 2
    list_h = max(1, min(hard_max, avail))
    sl.styles.max_height = list_h
    if size.width < 50:  # 4 个按钮横排需要 ~38 列内容宽, 窄屏只留最关键的两个
        for btn in screen.query(Button):
            if str(btn.id).endswith(("-all", "-none")):
                btn.display = False
    return list_h


# 勾选面板的默认提示。讲按键而不只是按钮名: 窄屏下 _fit_panel 会隐藏 全选/全不选
# 两个按钮, 只讲按钮等于没讲。两个面板共用同一句, 免得改一处漏一处。
_PICK_HINT = "空格 勾选/取消 · a/n 全选/全不选 · 亦可点下方按钮"

# 面板中列表之外的固定行数 (边框2 + 内边距2 + 标题1 + 提示1&margin1 + 按钮1&margin1)
_PICKER_CHROME = 10
_VF_CHROME = _PICKER_CHROME + 2  # 值面板多一行搜索框 + 其 margin


class HelpScreen(ModalScreen):
    """帮助。放在 VerticalScroll 里: 帮助文本只会越加越长, 而终端高度是给定的,
    定高 Static 一旦超屏就把末尾几行连边框一起静默裁掉 (最先没的正是 q 退出那行)。"""

    BINDINGS = [Binding("escape,q,question_mark", "dismiss", "关闭")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box"):
            yield Static(Text.from_markup(_HELP))

    def on_mount(self) -> None:
        self.query_one("#help-box", VerticalScroll).focus()  # 矮终端下可用 ↑↓ 滚动


class ColumnPicker(ModalScreen):
    """列显示勾选面板: 空格切换, Enter/Esc 应用并关闭。返回可见列名集合。"""

    # priority=True: 抢在 SelectionList 之前处理, 否则 enter 会被它消费而无法关闭
    BINDINGS = [
        Binding("enter,c", "close", "应用", priority=True),
        Binding("escape", "cancel", "取消", priority=True),
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
            yield Static(f"[dim]{_PICK_HINT}[/dim]", id="picker-hint")
            with Horizontal(classes="panel-btns"):
                yield Button("全选", id="cp-all")
                yield Button("全不选", id="cp-none")
                yield Button("应用", id="cp-apply", variant="primary")
                yield Button("取消", id="cp-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        {
            "cp-all": self.action_all,
            "cp-none": self.action_none,
            "cp-apply": self.action_close,
            "cp-cancel": self.action_cancel,
        }[event.button.id]()

    def on_mount(self) -> None:
        sl = self.query_one(SelectionList)
        for col in self._columns:
            sl.add_option(Selection(Text(col), col, col not in self._hidden))
        _fit_panel(self, sl, _PICKER_CHROME, hard_max=20)
        sl.focus()

    def action_all(self) -> None:
        self.query_one(SelectionList).select_all()

    def action_none(self) -> None:
        self.query_one(SelectionList).deselect_all()

    def action_close(self) -> None:
        self.dismiss(set(self.query_one(SelectionList).selected))

    def action_cancel(self) -> None:
        self.dismiss(None)


class ValueFilterScreen(ModalScreen):
    """Excel 式列值勾选筛选: 列出某列唯一值(带频次), 勾选要保留的值。

    - 顶部搜索框实时按子串过滤候选值 (大小写不敏感), 唯一值成百上千时靠它定位。
    - 有搜索词时应用 = 只保留 勾选∩匹配 (Excel 语义: 所见即所得),
      于是"某列包含某子串"= 打字 → Enter, 两步完成。
    - 有搜索词时 全选=勾上匹配项(不动视野外勾选) / 全不选=只取消匹配项 —— 因此
      跨搜索词可累积勾选 (搜A全选→搜B全选→清空搜索词→应用 = A∪B)。
    - prior 非 None 时回显上次保留集 (故可把去掉的值重新勾回); 否则默认全选。
    - anchor 非 None 时面板贴着被点列头下方弹出 (右溢出自动左移), 否则居中。
    - Enter 应用返回勾选集合, Esc 返回 None (取消)。

    勾选状态的真值是 ``self._checked``, 不是 SelectionList —— 列表随搜索词重建,
    被过滤掉的项不在列表里, 只能靠 _checked 记住。

    高基数列: 列表只渲染前 _MAX_SHOW 项 (按频次降序) 防 UI 卡死, 但搜索/应用/
    全选/全不选作用于全量匹配项 —— "打字 → Enter" 对未显示的值同样生效。
    """

    _BOX_W = 56
    _MAX_SHOW = 1000  # 列表最多渲染的候选值数; 超出部分靠搜索框缩小范围后可见

    BINDINGS = [
        Binding("enter", "close", "应用", priority=True),
        Binding("escape", "cancel", "取消", priority=True),
        Binding("down", "focus_list", "进入列表", show=False),
        Binding("a", "all", "全选"),
        Binding("n", "none", "全不选"),
    ]

    def __init__(self, col: str, items: List, total: int, prior=None, anchor=None):
        super().__init__()
        self._col = col
        self._items = items  # [(value, count), ...] 按频次降序
        self._total = total
        self._prior = prior  # 上次保留值集 (None=未筛→默认全选)
        self._anchor = anchor  # (x, y) 列头下方; None=居中
        self._checked: Set[str] = (
            {v for v, _ in items} if prior is None else {v for v, _ in items if v in prior}
        )
        self._query = ""
        self._shown: List[str] = []  # 当前列表实际渲染的值 (≤_MAX_SHOW), _sync 的作用域

    def compose(self) -> ComposeResult:
        with Vertical(id="vf-box"):
            yield Static(id="picker-title")
            yield Input(placeholder="输入子串过滤候选值…", id="vf-search")
            yield SelectionList(id="cols")
            yield Static(id="picker-hint")
            with Horizontal(classes="panel-btns"):  # 鼠标可点: 全流程无需回键盘
                yield Button("全选", id="vf-all")
                yield Button("全不选", id="vf-none")
                yield Button("应用", id="vf-apply", variant="primary")
                yield Button("取消", id="vf-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        {
            "vf-all": self.action_all,
            "vf-none": self.action_none,
            "vf-apply": self.action_close,
            "vf-cancel": self.action_cancel,
        }[event.button.id]()

    def on_mount(self) -> None:
        self._rebuild()
        self.query_one("#vf-search", Input).focus()  # 打开即可打字过滤; ↓ 进列表勾选
        list_h = _fit_panel(self, self.query_one(SelectionList), _VF_CHROME, hard_max=14)
        if self._anchor is not None:  # 贴列头下方弹出; 右/下溢出则左移上移, 保证整块可见
            x, y = self._anchor
            x = max(0, min(x, self.app.size.width - self._BOX_W))
            y = min(y, max(0, self.app.size.height - (list_h + _VF_CHROME)))
            box = self.query_one("#vf-box", Vertical)
            self.styles.align = ("left", "top")
            box.styles.offset = (x, y)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._sync()  # 先把当前列表的勾选并回 _checked, 再按新词重建
        self._query = event.value.strip().lower()
        self._rebuild()

    # -------------------------------------------------------------- #
    def _matched(self) -> List:
        """当前搜索词命中的候选值 [(值, 频次)]; 空词=全部。"""
        if not self._query:
            return self._items
        return [(v, c) for v, c in self._items if self._query in v.lower()]

    def _sync(self) -> None:
        """把列表里(即当前显示项)的勾选状态并回 _checked; 未显示的项保持原状。"""
        try:
            sl = self.query_one(SelectionList)
        except NoMatches:
            return
        selected = set(sl.selected)
        for val in self._shown:
            if val in selected:
                self._checked.add(val)
            else:
                self._checked.discard(val)

    def _rebuild(self) -> None:
        sl = self.query_one(SelectionList)
        sl.clear_options()
        matched = self._matched()
        shown = matched[: self._MAX_SHOW]
        self._shown = [v for v, _ in shown]  # _sync 只并回显示过的项
        for val, cnt in shown:
            label = val if val != "" else "(空)"
            if len(label) > 46:
                label = label[:45] + "…"
            sl.add_option(Selection(Text(f"{label}  ({cnt})"), val, val in self._checked))
        scope = f"匹配 {len(matched)}/{self._total}" if self._query else f"{self._total} 个值"
        if len(matched) > len(shown):
            scope += f", 仅显示前 {len(shown)}"
        self.query_one("#picker-title", Static).update(
            Text.from_markup(f"[b]按 {escape(self._col)} 值筛选[/b] [dim]({scope})[/dim]")
        )
        if self._query:
            hint = "应用 = 只保留勾选的匹配项 · ↓ 进列表空格勾选"
        elif len(matched) > len(shown):
            hint = "候选过多, 输入子串缩小范围 · 应用 = 只保留匹配项"
        else:
            hint = _PICK_HINT
        self.query_one("#picker-hint", Static).update(Text.from_markup(f"[dim]{hint}[/dim]"))

    # -------------------------------------------------------------- #
    def action_focus_list(self) -> None:
        self.query_one(SelectionList).focus()

    def action_all(self) -> None:
        """无搜索词: 全选。有搜索词: 勾上匹配项 (视野外的勾选不动, 可跨搜索词累积)。"""
        if self._query:
            self._checked |= {v for v, _ in self._matched()}
        else:
            self._checked = {v for v, _ in self._items}
        self._rebuild()

    def action_none(self) -> None:
        """无搜索词: 全不选。有搜索词: 只取消匹配项。"""
        if self._query:
            self._checked -= {v for v, _ in self._matched()}
        else:
            self._checked = set()
        self._rebuild()

    def action_close(self) -> None:
        """应用。有搜索词时只保留 勾选∩匹配 (所见即所得) —— 默认全选下
        "打字 → Enter" 即等于按包含子串筛选, 不必先全不选再全选。"""
        self._sync()
        selected = set(self._checked)
        if self._query:
            selected &= {v for v, _ in self._matched()}
        self.dismiss(selected)

    def action_cancel(self) -> None:
        self.dismiss(None)


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
    /* 宽度写死: VerticalScroll 的 width:auto 会塌缩 (滚动容器不按内容测宽),
       98 = 帮助最长行 + 内边距 + 边框; max-* 100% 保证窄/矮终端下改为滚动而非被裁 */
    #help-box { padding: 1 2; border: round $primary; background: $surface;
                width: 98; max-width: 100%; height: auto; max-height: 100%; }
    #help-box Static { width: auto; }
    ColumnPicker { align: center middle; }
    #picker-box { width: 56; max-width: 100%; height: auto; max-height: 100%;
              border: round $primary;
                  background: $surface; padding: 1 2; }
    #picker-title { text-align: center; width: 1fr; margin-bottom: 1; }
    #picker-box #cols { width: 1fr; height: auto; max-height: 20; background: $surface; }
    #picker-hint { text-align: center; width: 1fr; margin-top: 1; }
    ValueFilterScreen { align: center middle; }
    #vf-box { width: 56; max-width: 100%; height: auto; max-height: 100%;
              border: round $primary;
              background: $surface; padding: 1 2; }
    #vf-box #cols { width: 1fr; height: auto; max-height: 14; background: $surface; }
    /* 紧凑搜索框: 去掉 Input 默认 border 占的 2 行, 面板不至于顶到屏幕外 */
    #vf-search { border: none; height: 1; padding: 0; margin-bottom: 1;
                 background: $boost; width: 1fr; }
    /* 紧凑单行按钮 (去掉 Button 默认的边框/height:3/min-width:16, 不再又大又丑) */
    .panel-btns { width: 1fr; height: auto; align: center middle; margin-top: 1; }
    .panel-btns Button {
        height: 1; min-width: 0; border: none; padding: 0 1; margin: 0 1; color: $text;
    }
    .panel-btns Button.-primary { background: $primary; }
    """

    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("question_mark", "help", "帮助"),
        Binding("slash", "search", "搜索"),
        Binding("f", "filter", "筛选"),
        Binding("F", "value_filter", "值筛选"),
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
        # *: 只在含搜索命中的字段间跳 (n/N 的过滤版, 长对话里直奔命中那条消息)
        Binding("asterisk", "next_match", "下一命中", show=False),
        # 复制到剪贴板: y 复制当前样本 JSON; v 多选样本后 y 复制
        Binding("y", "yank", "复制", show=False),
        Binding("v", "visual", "多选", show=False),
        # 落地: w 导出当前子集到文件, C 复制可复现当前视图的命令
        Binding("w", "export", "导出", show=False),
        Binding("C", "copy_command", "复制命令", show=False),
    ]

    def __init__(
        self,
        source,
        window: List[Dict],
        win_offset: int,
        cap: int,
        fmt: str,
        filename: str,
        where: Optional[List[str]] = None,
        search: Optional[str] = None,
        sort: Optional[str] = None,
        filepath: Optional[str] = None,
    ):
        super().__init__()
        self.source = source  # RowSource: 随机窗口访问, 内存 O(窗口)
        self.cap = cap  # 单窗口行数
        self.win_offset = win_offset  # 当前窗口在"当前浏览序列"中的起始位置 (0-based)
        self.all_rows = window  # 当前窗口已 parse 的行
        # 当前浏览序列: subset=None 时为"原始文件顺序"; 否则为一串全局行号 —— 筛选命中集,
        # 且当有排序时按排序键重排过 (排序与筛选共用同一条管线, 语义一致且跨窗口有效)。
        # _global_nos 与 all_rows 对齐, 记每行真实全局行号 (供 # 列/跳行两模式统一显示)。
        self._subset: Optional[List[int]] = None
        self._global_nos: List[int] = list(range(win_offset, win_offset + len(window)))
        self._filter_label: Optional[str] = None  # 状态栏显示的全量筛选说明
        # 统一约束模型: 子集 = 全文件中满足 (搜索 且 每条 where 且 每列值约束) 的行, 再按排序键排。
        # 三类约束分开存而不是塞进一个槽: 各自可独立增删/回显, 且能逐条翻译成 --where 复现。
        self._col_value_filters: Dict[str, set] = {}  # 列 → 保留值集 (故某列可反复调整/加回)
        self._where_specs: List[Tuple[str, Callable]] = []  # [(原始表达式, predicate)], 多条 AND
        self._search_text: Optional[str] = None  # 原始搜索词 (含 re: 前缀), 供复现命令
        self._search_re: Optional[Pattern] = None  # 编译后的 pattern: 既筛选也用于高亮
        self._sort_spec: Optional[Tuple[str, bool]] = None  # (列名, 是否降序)
        self._scan_cancel: Optional[object] = None  # 扫描中的取消 Event (threading.Event)
        self._scan_gen = 0  # 扫描代次: 迟到的结果靠它作废 (详见 _scan_superseded)
        self._scan_rollback = None  # 本次扫描发起前的约束快照 (取消/失败时退回)
        self._scan_msg: str = ""  # 扫描进度文案 (worker 线程回填, 状态栏展示)
        self.fmt = fmt
        self.filename = filename
        self.filepath = filepath  # 真实路径 (复现命令/血缘用); stdin 模式为 None
        self._init_where = list(where or [])  # 启动参数, on_mount 后统一走一次扫描
        self._init_search = search
        self._init_sort = sort
        self.columns = render.build_columns(window, fmt)  # 列固定自首窗口 (数据集 schema 稳定)
        self._hidden: Set[str] = set()  # 被折叠的列名 (同时作用于表格和详情)
        self.view_indices: List[int] = list(range(len(window)))
        self._field_texts: List[str] = []  # 详情各字段的纯文本, 供 * 找命中
        self._prompt_mode: Optional[str] = None
        self._split = 13  # 表格占比 (总 20 份, 每份 5%), 默认表格 65% : 详情 35%
        # 详情每字段一个 Static widget (真实布局, 无测量误差); 锚点 {字段名: 起始行} 由布局算出
        self._field_widgets: List[Static] = []
        self._cur_anchors: Dict[str, int] = {}
        self._field_i = 0  # 当前字段索引 (滚动时同步顶部字段, n/N/点击 精确接管)
        # 详情渲染代次: 渲染收尾回调比按键晚一帧, 靠它判断"这次回调是否已被取代"
        self._detail_gen = 0
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

    @property
    def _sort_label(self) -> Optional[str]:
        """状态栏的排序说明; 由 _sort_spec 派生, 不单独存 (存两份必然漂移)。"""
        if self._sort_spec is None:
            return None
        name, desc = self._sort_spec
        return f"{name}{'↓' if desc else '↑'}"

    # ------------------------------------------------------------------ #
    # 扫描的统一出入口。四种全量扫描 (筛选/值/快照/导出) 共用一个 worker 槽位
    # (run_worker exclusive, group="scan"), 所以"谁在跑"和"结果还算不算数"必须统一管。
    # ------------------------------------------------------------------ #
    def _busy(self) -> bool:
        """扫描进行中则拒绝并说明。

        关键: 调用方必须在**改约束之前**问这一句。此前是先改状态再让 _recompute_subset
        静默 return —— 于是屏幕上是旧子集、约束模型里是新条件, C 复制出的命令和导出的
        血缘都在描述一个屏幕上并不存在的视图。宁可拒绝, 不可半改。
        """
        if self._scan_cancel is None:
            return False
        self.notify("扫描进行中, 先按 Esc 取消再改条件", severity="warning")
        return True

    def _begin_scan(self):
        """占用扫描槽位, 返回 (取消 Event, 代次)。代次用于作废迟到的结果。"""
        import threading

        cancel = threading.Event()
        self._scan_cancel = cancel
        self._scan_gen += 1
        return cancel, self._scan_gen

    def _scan_superseded(self, gen: int) -> bool:
        """这次扫描的结果是否已作废 (期间被 r 重置, 或被更新的扫描取代)。

        没有这道闸: 扫描中按 r, 迟到的结果会把已经清掉的筛选原样复活。
        """
        return gen != self._scan_gen

    def _end_scan(self) -> None:
        self._scan_cancel = None
        self._scan_msg = ""

    def _run_scan(self, body: Callable, gen: int) -> None:
        """起扫描 worker: body 只负责算, 算完把 (回调, 参数) 交回来, 由这里投递。

        兜底的意义: 数据源迭代自己会抛 (JSONL 夹一条坏行 → JSONDecodeError), 裸 worker
        抛出去会被 Textual 当致命错误整个退出 —— 一条坏行不该让人连文件都看不成。

        投递刻意放在 try 之外: 它执行的是 UI 回调, 那里面抛的是程序 bug, 不是扫描失败。
        包进来会把 bug 报成"扫描失败"、连带回滚掉已经提交的约束, 还丢掉原始 traceback。
        """

        def guarded() -> None:
            try:
                delivery = body()
            except Exception as e:  # noqa: BLE001  扫描本身失败 → 变成提示而不是退出
                self.call_from_thread(self._on_scan_crashed, f"{type(e).__name__}: {e}", gen)
                return
            if delivery is not None:  # body 中途取消可返回 None
                callback, args = delivery
                self.call_from_thread(callback, *args)

        self.run_worker(guarded, thread=True, exclusive=True, group="scan")

    def _on_scan_crashed(self, msg: str, gen: int) -> None:
        if self._scan_superseded(gen):
            return
        self._end_scan()
        self._rollback_constraints()  # 这次改动没生效, 约束退回改之前
        self.notify(escape(f"扫描失败: {msg}"), severity="error", timeout=10)
        self._update_status()

    # ------------------------------------------------------------------ #
    # 约束的"提交时机": 改约束只是提案, 扫描结果落地才算数
    # ------------------------------------------------------------------ #
    def _constraints_snapshot(self):
        """当前约束集的快照 (深到能独立回滚)。"""
        return (
            self._search_text,
            self._search_re,
            list(self._where_specs),
            {c: set(v) for c, v in self._col_value_filters.items()},
            self._sort_spec,
        )

    def _rollback_constraints(self) -> None:
        """把约束退回本次扫描发起之前。

        没有这一步, "按 Esc 取消扫描"就会留下半改状态: 屏幕还是旧子集, 约束模型里却已
        装着取消掉的条件 —— C 复制出的命令、导出的血缘都在描述另一个视图, 而且下次再加
        条件时它会被静默 AND 进去。取消就该是"什么都没发生"。
        """
        if self._scan_rollback is None:
            return
        (
            self._search_text,
            self._search_re,
            self._where_specs,
            self._col_value_filters,
            self._sort_spec,
        ) = self._scan_rollback
        self._scan_rollback = None

    def _has_filters(self) -> bool:
        """是否存在"筛掉行"的约束 (排序不算 —— 它只重排, 不改变行集)。"""
        return bool(self._search_re or self._where_specs or self._col_value_filters)

    def _filter_pred(self) -> Optional[Callable]:
        """搜索 + 各条 where 合成的单个 predicate; 都没有则 None。

        值约束不并进来: 值面板算候选值时要排除"本列"的约束, 那里只能用这个部分谓词。
        """
        pat, wheres = self._search_re, [p for _, p in self._where_specs]

        def matches_search(row) -> bool:
            # 搜整条记录而非表格列: 列只是派生摘要, 搜不到 assistant 回复和后续轮次。
            # 也因此与隐藏列无关 —— 折叠一列不该悄悄改变搜索范围。
            return bool(pat.search(render.row_text(row)))

        if pat is None and not wheres:
            return None
        if pat is None:
            return lambda row: all(w(row) for w in wheres)
        if not wheres:
            return matches_search
        return lambda row: matches_search(row) and all(w(row) for w in wheres)

    def compose(self) -> ComposeResult:
        with Vertical(id="main"):
            # fixed_columns=1: 冻结 # 索引列, 列多水平滚动时始终可见 (# 恒为第一列, 不可隐藏)
            yield FastDataTable(id="table", cursor_type="row", zebra_stripes=True, fixed_columns=1)
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
        self._apply_initial_constraints()

    def _apply_initial_constraints(self) -> None:
        """把 --where/--search/--sort 装进约束模型, 再走一次和 TUI 内完全相同的扫描。

        刻意复用同一条管线 (而不是启动时另写一套筛选): 命令行进来的条件和手按 f/s 得到的
        子集必然一致, 也免得两处语义漂移。
        """
        empty = self._constraints_snapshot()
        for expr in self._init_where:
            try:
                self._where_specs.append((expr, _compile_where(expr, self.fmt)))
            except ValueError as e:
                self.notify(escape(f"--where {expr}: {e}"), severity="error")
        if self._init_search:
            try:
                self._search_re = compile_search(self._init_search)
                self._search_text = self._init_search
            except re.error as e:
                self.notify(
                    escape(f"--search {self._init_search}: 正则无效 ({e})"), severity="error"
                )
        if self._init_sort:
            self._set_sort_spec(self._init_sort)
        if self._has_filters() or self._sort_spec is not None:
            # 快照是"空约束": 首屏扫描按 Esc 取消 = 放弃命令行给的条件, 直接看全量
            self._recompute_subset(empty)

    def _visible_columns(self) -> List[str]:
        return [c for c in self.columns if c not in self._hidden]

    def _header_plain(self, name: str) -> str:
        """列头纯文本 (含值筛选标记), 用于列宽估算。"""
        return f"{name} ▾" if name in self._col_value_filters else name

    def _header_label(self, name: str) -> Text:
        """列头显示: 被值筛选的列加黄色漏斗 ▾ 标记, 一眼可辨。"""
        if name in self._col_value_filters:
            return Text(f"{name} ▾", style="bold yellow")
        return Text(name)

    def _add_columns(self, table: DataTable) -> None:
        """显式给每列宽度, 避免 DataTable 对全表自动测量 (大文件会两阶段闪烁 + 卡顿)。"""
        vis = self._visible_columns()
        for name, w in zip(vis, self._column_widths(vis), strict=False):
            table.add_column(self._header_label(name), width=w)

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
            w = cell_len(self._header_plain(name))  # 含 ▾ 标记宽度, 避免标记被截
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
    def _cell_text(self, s: str) -> Text:
        """单元格 → Text。包成 Text 绕过 DataTable 的 markup 解析 (数据含 [/xxx] 会
        MarkupError); 有搜索时顺带把命中处画上黄底。"""
        return render._hl(Text(s), self._search_re)

    def _populate(self) -> None:
        table = self.query_one("#table", DataTable)
        table.clear()
        vis = self._visible_columns()
        for pos, idx in enumerate(self.view_indices):
            table.add_row(*(self._cell_text(c) for c in self._cells(idx, vis)), key=str(pos))
        self._update_status()
        if self.view_indices:
            self._refresh_detail(0)
        else:  # 空视图 (0 命中): 清详情, 免残留上个样本
            try:
                self.query_one("#detail", VerticalScroll).remove_children()
            except NoMatches:
                pass
            self._field_widgets = []
            self._field_texts = []
            self._cur_anchors = {}

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
        """详情滚动: 非导航态下把当前字段同步为顶部可见字段, 再刷新状态栏。

        已经滚到底时不反查: 那里"顶部可见字段"根本区分不了末尾几段 —— 跳到最后一段时
        滚动被 max_scroll_y 夹住, 该段并没有真对齐到视口顶, 顶部仍是前一段, 反查就会
        把刚跳过去的字段拽回来 (n 走到末尾会原地停一次)。到底之后保留显式导航的结果。
        """
        if not self._nav_lock:
            try:
                detail = self.query_one("#detail", VerticalScroll)
            except NoMatches:
                return  # DOM 卸载中 (watch 在 teardown 后触发)
            y = detail.scroll_offset.y
            if y < detail.max_scroll_y:  # 不在底部: 顶部可见字段是可靠的
                top = self._top_field(self._cur_anchors, y)
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
        # split_turns: 对话拆成 msg0/msg1…, n/N 因此变成逐条消息导航 (长对话里整段"对话"
        # 作为一个字段等于没有粒度); highlight 让搜索命中在正文里直接可见。
        sections = render.render_detail_sections(
            self.all_rows[idx],
            self.fmt,
            hidden=self._hidden,
            split_turns=True,
            highlight=self._search_re,
        )
        self._field_widgets = []
        self._field_texts = []
        to_mount: List[Static] = []
        for i, (name, rend, plain) in enumerate(sections):
            if i:
                to_mount.append(Static(Rule(style="dim"), classes="detail-sep"))
            w = _FieldStatic(rend, name)  # 字段块自处理点击
            self._field_widgets.append(w)
            self._field_texts.append(plain)
            to_mount.append(w)
        if to_mount:
            detail.mount(*to_mount)
        # 布局完成后 (widget.size 才确定): 算真实锚点 → 定位到绑定字段 → 刷新状态栏
        self._detail_gen += 1
        self.call_after_refresh(self._after_detail_render, prev_field, self._detail_gen)

    def _after_detail_render(self, prev_field: Optional[str], gen: int) -> None:
        if not self.is_running or not self.screen_stack:
            self._nav_lock = False  # 确保解锁, 否则后续滚动无响应
            return  # app/screen 卸载中 (call_after_refresh 在 teardown 后触发)
        total = self._recompute_anchors()  # 锚点无论如何都要更新: 滚动反查靠它
        if self._field_widgets and total == 0:
            # 新版 textual 中 mount 后一帧布局可能尚未完成 (size 全 0), 再等一帧重算
            self.call_after_refresh(self._after_detail_render, prev_field, gen)
            return
        # 本次回调已被更新的渲染或用户导航取代 → 只更锚点, 不再把当前字段拽回对齐位置。
        # 否则 "扫描刚完成就按 * / n" 会被这个迟到的回调静默撤销 (回调比按键晚一帧)。
        if gen == self._detail_gen:
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

    def action_next_match(self) -> None:
        """跳到详情中下一个含搜索命中的字段 (到末尾回绕)。

        只定位到"哪个字段", 不定位到字段内第几行 —— 换行后的视觉行号没法从纯文本推算,
        要精确得钻 textual 的渲染行缓存。对话已按条拆段, 配合黄底高亮, 这个粒度够用。
        """
        if self._search_re is None:
            self.notify("先用 / 搜索, 再用 * 跳命中")
            return
        n = len(self._field_texts)
        for step in range(1, n + 1):  # 从当前字段之后找起, 绕一圈回到自己
            i = (self._field_i + step) % n
            if self._search_re.search(self._field_texts[i]):
                self._goto_field(i)
                return
        self.notify("本样本详情内无命中")

    def _goto_field(self, i: int) -> None:
        """精确跳到第 i 个字段 (绕过滚动条像素限制, 底部字段 clamp 但可见)。

        推进 _detail_gen: 用户显式导航后, 上一次渲染排队中的"对齐回原字段"作废。
        """
        if not self._field_widgets:
            return
        self._detail_gen += 1
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
            self._detail_gen += 1  # 同 _goto_field: 点击是显式导航, 不该被迟到的对齐撤销
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
        # 子集态但无筛选约束 = 纯排序: 行集没变, 报"命中 N/N (100%)"是误导
        if self._subset is not None and self._filter_label:
            pct = 100 * len(self._subset) / total if total else 0
            parts.append(
                f"[green]{escape(self._filter_label)}: "
                f"命中 {len(self._subset)}/{total} ({pct:.1f}%)[/green]"
            )
        if seq_total > win:  # 多窗口: 显示当前序列内的窗口范围
            parts.append(f"窗口 [{self.win_offset + 1}–{self.win_offset + win}]/{seq_total}")
            parts.append("[dim]]/[ 翻窗口·: 跳行[/dim]")
        elif not self._filter_label:
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

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """点列头 → 打开该列的值勾选筛选 (Excel AutoFilter)。"""
        vis = self._visible_columns()
        if 0 <= event.column_index < len(vis):
            self._start_value_scan(vis[event.column_index])

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
        self._open_prompt("sort", "全量排序列名 (加 - 反向, 如 -chars; 扫全文件):")

    def _set_sort_spec(self, text: str) -> bool:
        """校验并记下排序列; 列名非法返回 False。"""
        desc = text.startswith("-")
        name = text.lstrip("-").strip()
        if name not in self.columns:
            self.notify(
                escape(f"无此列: {name} (可选: {', '.join(self.columns)})"), severity="error"
            )
            return False
        self._sort_spec = (name, desc)
        return True

    def _apply_sort(self, text: str) -> None:
        """排序 = 重排整个浏览序列, 不是只排当前窗口。

        走和筛选同一条扫描管线: 扫全文件算排序键 → 排好的全局行号序列即新的浏览序列。
        代价是一次全量扫描 (有进度、可 Esc 取消), 换来的是"全文件最长的 20 条"这类
        问题真的能回答, 且翻窗口不失效 —— 旧的窗口内排序做不到, 语义还和 f// 不一致。
        """
        if self._busy():
            return
        snap = self._constraints_snapshot()
        if self._set_sort_spec(text):
            self._recompute_subset(snap)

    def _sort_keyfn(self) -> Optional[Callable]:
        """按排序列取键 ``keyfn(全局行号, 行)``: 数值优先 (0, float), 非数值退化为 (1, str)。

        分层元组保证数值行整体排在字符串行之前, 不会 float 与 str 相比报错。
        ``#`` 列必须用传进来的全局行号: 它是"第几行"这一事实, 不在行数据里
        (row_cells 拿到的 # 恒为占位值), 按它排会全部同键 → 扫了一遍却纹丝不动。
        """
        if self._sort_spec is None:
            return None
        col = self._sort_spec[0]
        fmt = self.fmt

        def keyfn(idx: int, row):
            if col == "#":
                return (0, float(idx), "")
            v = render.row_cells(0, row, fmt, [col])[0] if isinstance(row, dict) else ""
            try:
                return (0, float(v), "")
            except (ValueError, TypeError):
                return (1, 0.0, str(v))

        return keyfn

    def action_reset(self) -> None:
        """清除所有约束 (搜索/where/列值/排序), 回到文件开头的原始顺序浏览。

        r 在扫描进行中也必须有效 —— 它正是"我不想等了"的出口。所以这里不 _busy() 拦,
        而是叫停 worker 并推进代次, 让那次扫描的结果作废 (否则迟到的结果会把刚清掉的
        筛选原样复活)。
        """
        was_filtered = self._subset is not None
        if self._scan_cancel is not None:
            self._scan_cancel.set()  # 通知 worker 收摊
        self._scan_gen += 1  # 它的结果就此作废
        self._end_scan()
        self._scan_rollback = None  # 已经清空到底, 无需回滚
        self._col_value_filters = {}
        self._where_specs = []
        self._search_text = None
        self._search_re = None
        self._sort_spec = None
        self._subset = None
        self._filter_label = None
        self._load_window(0)
        self._rebuild_columns()  # 清列头 ▾ 标记 + 清单元格高亮
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
    # 复现当前视图的命令: 把约束翻译回 dt view 的命令行参数
    # ------------------------------------------------------------------ #
    # 值不能安全塞进 where 表达式的情形: 空值; 含运算符字符 (会被重新切成别的条件);
    # 含 and/or 分隔词 (会被拆成多个条件); 含 … (表格预览截断过, 原值已不可知)。
    _UNSAFE_VALUE = re.compile(r"^\s*$|[=<>!~…]|\s(and|or)\s", re.IGNORECASE)

    def _build_command(self) -> Tuple[Optional[str], List[str]]:
        """(可复现当前视图的 dt view 命令, 无法表达的部分说明)。"""
        import shlex

        if not self.filepath:  # stdin 模式: 源数据是管道, 没有可复现的输入
            return None, ["管道输入 (dt view -) 无法复现, 请用 w 导出结果文件"]

        skipped: List[str] = []
        wheres = [e for e, _ in self._where_specs]
        for col, kept in self._col_value_filters.items():
            bad = [v for v in kept if self._UNSAFE_VALUE.search(v)]
            if bad:
                skipped.append(f"{col} 的 {len(bad)} 个值含特殊字符/被截断, 无法写进命令")
                continue
            # 多列值筛选之间是 AND, 各写一条 --where; 单列内多值是 OR, 写在一条里 ——
            # where 表达式没有括号, 靠"多条 --where 之间 AND"来表达这层嵌套
            wheres.append(" or ".join(f"{col}=={v}" for v in sorted(kept)))

        parts = ["dt", "view", shlex.quote(self.filepath)]
        for w in wheres:
            parts.append(f"--where={shlex.quote(w)}")
        if self._search_text:
            parts.append(f"--search={shlex.quote(self._search_text)}")
        if self._sort_spec:
            name, desc = self._sort_spec
            parts.append(f"--sort={shlex.quote(('-' if desc else '') + name)}")
        return " ".join(parts), skipped

    def action_copy_command(self) -> None:
        cmd, skipped = self._build_command()
        if cmd is None:
            self.notify(escape(skipped[0]), severity="warning")
            return
        self._copy_clipboard(cmd)
        msg = f"已复制命令: {cmd}"
        if skipped:
            msg += "\n未纳入: " + "; ".join(skipped) + " (完整条件见导出文件的血缘记录)"
        self.notify(escape(msg), timeout=10, severity="warning" if skipped else "information")

    # ------------------------------------------------------------------ #
    # 导出: 把当前浏览序列 (或多选选区) 落盘。剪贴板走 OSC52 有长度上限, 几千条根本装不下,
    # 所以"筛出来的子集"必须能写成文件, 否则 view 里的筛选结果出不去。
    # ------------------------------------------------------------------ #
    def _export_scope(self) -> Tuple[str, int]:
        """(范围说明, 行数): 多选态导出选区, 否则导出整个当前浏览序列。"""
        if self._visual_anchor is not None:
            lo, hi = sorted((self._visual_anchor, self.query_one("#table", DataTable).cursor_row))
            return "选区", hi - lo + 1
        return ("筛选子集" if self._filter_label else "全部"), self._seq_total()

    def action_export(self) -> None:
        scope, n = self._export_scope()
        if n <= 0:
            self.notify("没有可导出的行")
            return
        self._open_prompt("export", f"导出{scope} {n} 行到 (按扩展名定格式, 如 out.jsonl):")

    def _apply_export(self, path_str: str) -> None:
        from pathlib import Path

        if self._busy():
            return
        out = Path(path_str).expanduser()
        if out.exists():  # 不静默覆盖: 导出目标多半是新文件, 覆盖了没法撤
            self.notify(escape(f"已存在, 换个名字: {out}"), severity="error")
            return
        if not out.parent.exists():
            self.notify(escape(f"目录不存在: {out.parent}"), severity="error")
            return

        scope, n = self._export_scope()
        if self._visual_anchor is not None:
            lo, hi = sorted((self._visual_anchor, self.query_one("#table", DataTable).cursor_row))
            picked = [self.all_rows[self.view_indices[p]] for p in range(lo, hi + 1)]
            rows_iter: Callable = lambda cancel: iter(picked)  # noqa: E731
        else:
            rows_iter = self._iter_sequence
        streaming = out.suffix.lower() in (".jsonl", ".ndjson")
        if not streaming and n > 200_000:
            self.notify(
                escape(f"{out.suffix} 需全量载入内存 ({n} 行), 建议导出 .jsonl"), severity="warning"
            )

        cancel, gen = self._begin_scan()
        self._set_scan_msg(f"导出中 0/{n} (Esc 取消)")

        def worker():
            # 导出的失败 (磁盘满/权限/格式后端缺失) 有自己的文案, 不并进 _on_scan_crashed
            try:
                written = self._write_export(out, rows_iter, cancel, n, streaming)
            except Exception as e:  # noqa: BLE001
                return self._on_export_done, (out, None, str(e), gen)
            return self._on_export_done, (out, written, None, gen)

        self._run_scan(worker, gen)

    def _write_export(self, out, rows_iter, cancel, total: int, streaming: bool) -> Optional[int]:
        """写文件, 返回行数; 被取消返回 None。

        .jsonl 逐行写 (内存 O(1), 几十万行的子集也扛得住); 其余格式没有流式写入口,
        只能物化后交给 save_data 按扩展名分派。
        """
        n = 0
        if streaming:
            with open(out, "wb") as f:
                for row in rows_iter(cancel):
                    if cancel.is_set():
                        break
                    f.write(orjson.dumps(row))
                    f.write(b"\n")
                    n += 1
                    if n % 5000 == 0:
                        self.call_from_thread(self._set_scan_msg, f"导出中 {n}/{total} (Esc 取消)")
            if cancel.is_set():
                out.unlink(missing_ok=True)  # 半截文件比没有更坏, 直接删掉
                return None
            return n

        data = []
        for row in rows_iter(cancel):
            if cancel.is_set():
                return None
            data.append(row)
            n += 1
            if n % 5000 == 0:
                self.call_from_thread(self._set_scan_msg, f"收集中 {n}/{total} (Esc 取消)")
        from ...storage.io import save_data

        self.call_from_thread(self._set_scan_msg, f"写入 {out.suffix} ({n} 行)…")
        save_data(data, str(out))
        return n

    def _save_lineage(self, out, written: int) -> Optional[str]:
        """给导出文件写血缘 sidecar: 来源文件 + 本次全部筛选/排序条件 + 可复现命令。

        这才是"可复现"的落点 —— 命令行能表达的条件写进 command, 表达不了的 (含特殊字符的
        值集等) 也在 params 里如实记着, dt history <out> 能看到完整来龙去脉。
        """
        from ...lineage import LineageTracker

        cmd, skipped = self._build_command()
        params = {
            "format": self.fmt,
            "search": self._search_text,
            "where": [e for e, _ in self._where_specs],
            "value_filters": {c: sorted(v) for c, v in self._col_value_filters.items()},
            "sort": self._sort_label,
            "scope": self._export_scope()[0],
            "command": cmd,
        }
        if skipped:
            params["command_incomplete"] = skipped
        tracker = LineageTracker(self.filepath)
        tracker.record(
            "view_export", params=params, input_count=self.source.total, output_count=written
        )
        return tracker.save(str(out), written)

    def _on_export_done(self, out, written: Optional[int], error: Optional[str], gen: int) -> None:
        if self._scan_superseded(gen):
            return  # 期间已被 r 重置或新扫描取代
        self._end_scan()
        self._update_status()
        if error is not None:
            self.notify(escape(f"导出失败: {error}"), severity="error", timeout=10)
            return
        if written is None:
            self.notify("已取消导出")
            return
        try:
            lineage_path = self._save_lineage(out, written)
            extra = f"\n血缘: {lineage_path} (dt history {out} 可查)"
        except Exception as e:  # noqa: BLE001  血缘是附加信息, 写不成不该让导出显示为失败
            extra = f"\n(血缘未写成: {e})"
        self.notify(escape(f"已导出 {written} 行 → {out}{extra}"), timeout=10)

    # ------------------------------------------------------------------ #
    # 大文件窗口翻页 (偏移索引 → 任意位置秒开, 内存 O(窗口))
    # ------------------------------------------------------------------ #
    def _load_window(self, offset: int) -> None:
        """加载"当前浏览序列"中以位置 offset 为起点的窗口, 重置排序并重填表格。

        原始态: 位置即文件行号, 走 source.window 顺序读。
        子集态: 位置为子集内序号, 取 subset[offset:] 的全局行号经 rows_at 拉取。
        """
        seq_total = self._seq_total()
        if self._subset is not None and seq_total == 0:  # 空子集: 清空视图 (0 命中)
            self.win_offset = 0
            self.all_rows = []
            self._global_nos = []
            self.view_indices = []
            self._populate()
            return
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
        self._open_prompt("search", "全量搜索 (整条记录, 不分大小写; re: 前缀走正则):")

    def action_filter(self) -> None:
        self._open_prompt(
            "filter",
            "全量筛选 列名 运算符 值 (~= 为包含); and/or 组合 "
            "(如 turns>=6 and first_user~=退款):",
        )

    def action_value_filter(self) -> None:
        self._open_prompt("value_filter", "按列值勾选筛选: 输入列名 (亦可直接点表头):")

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
        elif mode == "value_filter":
            self._start_value_scan(text)
        elif mode == "jump":
            self._apply_jump(text)
        elif mode == "export":
            self._apply_export(text)

    def _apply_search(self, text: str) -> None:
        if self._busy():
            return
        snap = self._constraints_snapshot()  # 扫描被取消/失败时退回这里
        try:
            self._search_re = compile_search(text)
        except re.error as e:
            self.notify(escape(f"正则无效: {e}"), severity="error")
            return
        self._search_text = text
        self._recompute_subset(snap)

    def _apply_filter(self, expr: str) -> None:
        """追加一条 where (不是覆盖上一条)。

        多条之间是 AND, 与命令行可重复的 --where 同义 —— 于是"再加一个条件"不必把整个
        表达式重敲一遍, 也让无括号的表达式语法能表达 (a or b) and (c or d)。要改条件用 r 重置。
        """
        if self._busy():
            return
        snap = self._constraints_snapshot()
        try:
            fn = _compile_where(expr, self.fmt)
        except ValueError as e:
            self.notify(escape(str(e)), severity="error")
            return
        self._where_specs.append((expr, fn))
        self._recompute_subset(snap)

    # ------------------------------------------------------------------ #
    # 统一约束重算: 子集 = 全文件中满足 (搜索 且 每条 where 且 每列值约束) 的行, 再按排序键排
    # worker 线程扫全文件, 进度回填状态栏, Esc 可取消
    # ------------------------------------------------------------------ #
    def _constraint_label(self) -> str:
        """状态栏/血缘里的约束说明。"""
        parts = []
        if self._search_text:
            parts.append(f"搜索'{self._search_text}'")
        parts += [f"筛选'{e}'" for e, _ in self._where_specs]
        parts += [f"{c}∈{len(v)}值" for c, v in self._col_value_filters.items()]
        return " · ".join(parts)

    def _recompute_subset(self, rollback=None) -> None:
        """按当前所有约束重算子集并按排序键排序; 什么都没有则回全量顺序浏览。

        调用方须已通过 _busy() 确认没有扫描在跑 —— 那道闸在"改约束之前", 这里再挡就晚了
        (状态已经改过, 屏幕却停在旧子集)。
        rollback: 改约束之前的快照; 扫描被取消或失败时退回它 (见 _rollback_constraints)。
        """
        pred = self._filter_pred()
        colf = {c: set(v) for c, v in self._col_value_filters.items()}
        fmt = self.fmt
        label = self._constraint_label()
        # 排序也算"需要扫描"的理由: 无筛选但要排序时, 子集 = 全部行号按键重排
        if pred is None and not colf and self._sort_spec is None:
            self._subset = None
            self._filter_label = None
            self._load_window(0)
            self._rebuild_columns()  # 清列头标记
            return

        def row_ok(row) -> bool:
            if not isinstance(row, dict):
                return False
            if pred is not None and not pred(row):
                return False
            for c, kept in colf.items():
                if render.row_cells(0, row, fmt, [c])[0] not in kept:
                    return False
            return True

        self._start_subset_scan(row_ok, label, rollback)

    def _start_subset_scan(self, row_ok, label: str, rollback=None) -> None:
        cancel, gen = self._begin_scan()
        self._scan_rollback = rollback
        total = self.source.total
        keyfn = self._sort_keyfn()
        desc = bool(self._sort_spec and self._sort_spec[1])
        self._set_scan_msg(f"扫描中 0/{total} (Esc 取消)")

        def worker():
            matches: List[int] = []
            keys: List = []
            for i, row in enumerate(self.source.iter_all()):
                if cancel.is_set():
                    return self._on_subset_scan_done, (None, label, True, gen)
                try:
                    if row_ok(row):
                        matches.append(i)
                        if keyfn is not None:
                            keys.append(keyfn(i, row))  # i 是全局行号, # 列排序靠它
                except Exception:  # noqa: BLE001  单行畸形不该中断整轮扫描
                    pass
                if i % 5000 == 0:
                    self.call_from_thread(
                        self._set_scan_msg,
                        f"扫描中 {i + 1}/{total} · 命中 {len(matches)} (Esc 取消)",
                    )
            if keyfn is not None:
                # sort 是稳定的 → 键相同的行保持原文件顺序, 结果可复现
                order = sorted(range(len(matches)), key=lambda j: keys[j], reverse=desc)
                matches = [matches[j] for j in order]
            return self._on_subset_scan_done, (matches, label, False, gen)

        self._run_scan(worker, gen)

    def _set_scan_msg(self, msg: str) -> None:
        self._scan_msg = msg
        self._update_status()

    def _on_subset_scan_done(self, matches, label: str, cancelled: bool, gen: int) -> None:
        if self._scan_superseded(gen):
            return  # 期间已被 r 重置或新扫描取代: 丢弃, 否则会把清掉的筛选复活
        self._end_scan()
        if cancelled:
            self._rollback_constraints()  # 取消 = 什么都没发生, 条件不生效
            self.notify("已取消扫描 (条件未生效)")
            self._rebuild_columns()  # 值筛选的 ▾ 标记随之回退
            return
        self._scan_rollback = None  # 结果落地: 约束就此提交
        self._subset = matches  # 可能为空 (0 命中)
        self._filter_label = label or None
        self._load_window(0)
        self._rebuild_columns()  # 刷新列头标记 (值筛选列加 ▾) + 单元格高亮
        if not label:  # 纯排序 (无筛选): 行集没变, 说排序而不是"命中"
            self.notify(escape(f"已按 {self._sort_label} 全量排序 ({len(matches)} 行)"))
        elif matches:
            self.notify(escape(f"{label}: {len(matches)} 命中 (全量)"))
        else:
            self.notify(escape(f"{label}: 0 命中 (r 重置, 或点列头/F 放宽该列)"))

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

    def _iter_sequence_indexed(self, cancel):
        """同 _iter_sequence, 但产出 (全局行号, 行): 原始态枚举号即全局行号, 子集态取 subset 值。"""
        if self._subset is None:
            for i, row in enumerate(self.source.iter_all()):
                yield i, row
        else:
            for start in range(0, len(self._subset), 1000):
                if cancel.is_set():
                    return
                chunk = self._subset[start : start + 1000]
                for gidx, row in zip(chunk, self.source.rows_at(chunk), strict=False):
                    yield gidx, row

    # ------------------------------------------------------------------ #
    # 列值勾选筛选 (Excel AutoFilter): 列出该列"在其他约束下"的全量唯一值 → 勾选 → 该列值约束
    # 列出全量值 (而非当前子集) + 回显上次勾选 → 可反复调整/把去掉的加回
    # ------------------------------------------------------------------ #
    # 唯一值再多也不拒绝筛选 (候选值已截断 ≤80 字符, 内存有界); 渲染开销由
    # ValueFilterScreen._MAX_SHOW 兜底 —— 只显示前 N 项, 搜索框仍在全量值上过滤。
    def _start_value_scan(self, col: str) -> None:
        from collections import Counter

        col = col.strip()
        if col == "#":
            self.notify("行号列不支持值筛选")
            return
        if col not in self.columns:
            self.notify(
                escape(f"无此列: {col} (可选: {', '.join(self.columns)})"), severity="error"
            )
            return
        if self._busy():
            return
        fmt = self.fmt
        expr = self._filter_pred()  # 搜索 + 各条 where
        # 关键: 算该列候选值时应用"除本列外"的其他约束 → 本列自己筛掉的值仍在列表里, 可加回
        other = {c: set(v) for c, v in self._col_value_filters.items() if c != col}
        cancel, gen = self._begin_scan()
        total = self.source.total
        self._set_scan_msg(f"扫描 {col} 值 0/{total} (Esc 取消)")

        def worker():
            counts: Counter = Counter()
            n = 0
            for row in self.source.iter_all():
                if cancel.is_set():
                    return self._on_value_scan_done, (col, None, "cancelled", gen)
                n += 1
                if n % 5000 == 0:
                    self.call_from_thread(
                        self._set_scan_msg, f"扫描 {col} 值 {n}/{total} (Esc 取消)"
                    )
                if not isinstance(row, dict):
                    continue
                if expr is not None and not expr(row):
                    continue
                if any(
                    render.row_cells(0, row, fmt, [c])[0] not in kept for c, kept in other.items()
                ):
                    continue
                counts[render.row_cells(0, row, fmt, [col])[0]] += 1
            return self._on_value_scan_done, (col, counts, "ok", gen)

        self._run_scan(worker, gen)

    def _on_value_scan_done(self, col, counts, status: str, gen: int) -> None:
        if self._scan_superseded(gen):
            return  # 期间已被 r 重置或新扫描取代
        self._end_scan()
        self._update_status()
        if status == "cancelled":
            self.notify("已取消扫描")
            return
        items = counts.most_common()  # [(值, 频次)] 按频次降序
        total = len(items)
        prior = self._col_value_filters.get(col)  # 上次保留集 (None=该列未筛→默认全选)

        def apply(selected) -> None:
            if selected is None:  # Esc 取消
                return
            if not selected:
                self.notify("至少选一个值")
                return
            if self._busy():
                return
            snap = self._constraints_snapshot()
            if len(selected) == total:  # 全选 = 清除该列筛选 (Excel 语义)
                self._col_value_filters.pop(col, None)
            else:
                self._col_value_filters[col] = selected
            self._recompute_subset(snap)

        anchor = self._column_anchor(col)
        self.push_screen(ValueFilterScreen(col, items, total, prior, anchor), apply)

    def _column_anchor(self, col: str):
        """被点列头正下方的屏幕坐标 (x, y), 供值面板贴着该列弹出; 拿不到则 None (居中)。"""
        try:
            table = self.query_one("#table", DataTable)
            vis = self._visible_columns()
            ci = vis.index(col)
            region = table._get_column_region(ci)
            x = table.content_region.x + region.x - table.scroll_offset.x
            y = table.content_region.y + (table.header_height if table.show_header else 0)
            return (max(0, x), y)
        except Exception:  # noqa: BLE001  定位失败退回居中, 不影响功能
            return None

    def action_snapshot(self) -> None:
        default = next((c for c in self._visible_columns() if c not in ("#",)), "chars")
        self._open_prompt("snapshot", f"列快照 (列名, 默认 {default}; 完整分布用 dt stats):")

    def _apply_snapshot(self, col: str) -> None:
        col = col.strip() or next((c for c in self._visible_columns() if c != "#"), "")
        if col not in self.columns:
            self.notify(
                escape(f"无此列: {col} (可选: {', '.join(self.columns)})"), severity="error"
            )
            return
        if self._busy():
            return
        ci = self.columns.index(col)
        cols = self.columns
        fmt = self.fmt
        cancel, gen = self._begin_scan()
        seq_total = self._seq_total()
        self._set_scan_msg(f"快照扫描中 0/{seq_total} (Esc 取消)")

        def worker():
            n = nonempty = nnum = 0
            vmin = vmax = vsum = None
            for row in self._iter_sequence(cancel):
                if cancel.is_set():
                    return self._on_snapshot_done, (col, None, True, gen)
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
            return self._on_snapshot_done, (col, stats, False, gen)

        self._run_scan(worker, gen)

    def _on_snapshot_done(self, col: str, stats, cancelled: bool, gen: int) -> None:
        if self._scan_superseded(gen):
            return  # 期间已被 r 重置或新扫描取代
        self._end_scan()
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
