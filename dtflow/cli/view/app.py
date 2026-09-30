"""
dt view 的 Textual TUI: 表格 + 详情 master-detail 联动浏览器。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Pattern, Set, Tuple

import orjson
from rich.cells import cell_len
from rich.console import RenderableType
from rich.markup import escape
from rich.padding import Padding
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.errors import NoWidget
from textual.geometry import Offset, Region, Size
from textual.message import Message
from textual.screen import ModalScreen
from textual.selection import Selection as TextSelection  # 与勾选面板的 Selection 同名
from textual.strip import Strip
from textual.widgets import Button, DataTable, Input, SelectionList, Static
from textual.widgets._data_table import RowRenderables
from textual.widgets.selection_list import Selection
from textual.worker import WorkerState

from ...expr import rename_fields
from ...i18n import t
from ...ops import _rename_item
from ...rowfn import _normalize_turns
from ...utils import clipboard
from . import image, render, scan
from .pipe import dt_error, error_message, run_pipe, shell_form
from .scan import ScanSpec, compile_search
from .source import _MemorySource


def _fmt_num(x: float) -> str:
    """整数去掉小数点, 其余保留 2 位, 让快照数字紧凑。"""
    if x == int(x):
        return str(int(x))
    return f"{x:.2f}"


def _pad_right(text: Text) -> Padding:
    return Padding(text, (0, 1, 0, 0))


class FastDataTable(DataTable):
    """定宽列 + 定高行专用: 跳过 textual 对每个 cell 的 measure。

    dt view 首屏/翻页的主瓶颈: textual 的 _update_dimensions 会对每个新增 cell
    调 measure() 更新 column.content_width (2万行 x 列 = 十几万次)。但定宽列的
    render_width 恒为 width, content_width 从不被 get_render_width 读取——这些
    measure 是纯浪费 (占首屏耗时的 2/3)。这里只保留刷新 virtual_size 的部分。

    前提 (dt view 始终满足): 所有列显式定宽 (_add_columns 传 width), 行默认
    height=1 非 auto_height。若引入 auto_width 列或 auto_height 行, 需回退父类实现。
    """

    # 每列一个 单元格字符串 → renderable (对齐/着色/截断/高亮), 由 app 填表时给定。
    # 行里只存字符串, 渲染某行时才套格式 (_compute_row_renderables): DataTable 只画可见的
    # 几十行, 填表时给 10k 行逐格造 Text/Padding 是白花 (还拖慢 GC)。
    cell_formatters: List[Callable[[str], RenderableType]] = []

    # DataTable 自带 enter→select_cursor, 焦点在表格时会先于 App 层的 enter→zoom 吃掉按键;
    # 在这里同键覆盖, 直接转给 app 的放大动作 (弹窗/输入框里的 Enter 焦点不在表格, 不受影响)。
    BINDINGS = [Binding("enter", "app.zoom", t("Zoom", "放大"))]

    def _compute_row_renderables(self, row_index: int) -> RowRenderables:
        if row_index < 0:  # 表头
            return super()._compute_row_renderables(row_index)
        cells = self.get_row_at(row_index)
        return RowRenderables(
            None, [f(c) for f, c in zip(self.cell_formatters, cells, strict=True)]
        )

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

    # -------------------------------------------------------------- #
    # 拖拽列宽 (Excel 式): 按住表头的列分隔线左右拖, 双击恢复自适应
    # -------------------------------------------------------------- #
    MIN_DRAG_W = 3  # 拖到底也留 3 格内容, 否则列头彻底消失就没法再拖回来

    class ColumnResized(Message):
        """拖拽结束 (width=新内容宽) 或双击分隔线 (width=None 表示恢复自适应)。"""

        def __init__(self, index: int, width: Optional[int]) -> None:
            super().__init__()
            self.index, self.width = index, width

    # 表头上常驻的列分隔线: 不画出来用户根本看不到"有条线可以拖"; 鼠标压上去换成粗体高亮,
    # 这是终端里唯一能表达"此处可拖"的手段 (改不了鼠标指针形状)。
    DIVIDER, DIVIDER_HOT = "│", "┃"

    class CellClicked(Message):
        """单击数据单元格; app 按列名决定是否响应 (点 imgs 列开图片弹窗)。"""

        def __init__(self, row: int, column: int) -> None:
            super().__init__()
            self.row, self.column = row, column

    class HeaderDoubleClicked(Message):
        """双击列头文字 (不是分隔线) → 重命名该列。"""

        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    class EdgeHover(Message):
        """鼠标进入/离开分隔线判定区, 供状态栏出提示。"""

        def __init__(self, active: bool) -> None:
            super().__init__()
            self.active = active

    _drag_col: Optional[int] = None  # 正在拖的列下标
    _drag_x0: int = 0  # 按下时的屏幕 x, 拖动量按它算
    _drag_w0: int = 0  # 按下时的列宽
    _drag_guard: bool = False  # 刚拖完: 吞掉紧随其后的 Click, 免得顺手选中行/开筛选面板
    _hover_edge: Optional[int] = None  # 鼠标所在 (或正在拖) 的分隔线, 画成高亮

    def _divider_cells(self) -> List[Tuple[int, int]]:
        """[(分隔线的屏幕 x, 归属列下标)]。末列右缘也画: 列没铺满时它在表格中间, 铺满时也得能拖窄。"""
        out: List[Tuple[int, int]] = []
        cols = self.ordered_columns
        fixed = self._row_label_column_width + sum(
            c.get_render_width(self) for c in cols[: self.fixed_columns]
        )
        edge = self._row_label_column_width
        for i, col in enumerate(cols):
            edge += col.get_render_width(self)
            x = edge - 1  # 本列右内边距那一格: 必为空白, 画线不遮字
            if i >= self.fixed_columns:
                x -= int(self.scroll_x)
                if x < fixed:  # 被固定列盖住了
                    continue
            if 0 <= x < self.size.width:
                out.append((x, i))
        return out

    def render_line(self, y: int) -> Strip:
        """在表头行叠画列分隔线。只改那几格, 其余片段连样式原样保留。"""
        strip = super().render_line(y)
        if not self.show_header or y >= self.header_height:
            return strip
        cells = self._divider_cells()
        if not cells:
            return strip
        length = strip.cell_length
        cuts = [c for x, _ in cells for c in (x, x + 1)] + [length]
        pieces = strip.divide(cuts)
        segments: List[Segment] = []
        for k, piece in enumerate(pieces):
            if k % 2 == 0:  # 偶数段是原内容, 奇数段才是被切出来的那一格分隔线
                segments.extend(piece)
                continue
            hot = cells[k // 2][1] == self._hover_edge
            base = next((seg.style for seg in piece if seg.style), Style())
            segments.append(
                Segment(
                    self.DIVIDER_HOT if hot else self.DIVIDER,
                    base + (Style(bold=True, reverse=True) if hot else Style(bold=False, dim=True)),
                )
            )
        return Strip(segments, length)

    def _set_hover_edge(self, i: Optional[int]) -> None:
        if i == self._hover_edge:
            return
        was = self._hover_edge is not None
        self._hover_edge = i
        self.refresh()
        if (i is not None) != was:
            self.post_message(self.EdgeHover(i is not None))

    def _edge_at(self, event: events.MouseEvent) -> Optional[int]:
        """鼠标落在表头某列右分隔线上 (2 格判定区) 时返回该列下标, 否则 None。

        判定区取的是"本列右内边距 + 下列左内边距"这两格, 都不含文字, 不会误伤点列头筛选。
        """
        if not self.show_header:
            return None
        y = event.y - self.gutter.top
        if not 0 <= y < self.header_height:
            return None
        x = event.x - self.gutter.left
        # 固定列不随横向滚动, 超出固定区的部分才加 scroll_x
        fixed = self._row_label_column_width + sum(
            c.get_render_width(self) for c in self.ordered_columns[: self.fixed_columns]
        )
        if x >= fixed:
            x += int(self.scroll_x)
        edge = self._row_label_column_width
        for i, col in enumerate(self.ordered_columns):
            edge += col.get_render_width(self)
            if edge - 1 <= x <= edge:
                return i
        return None

    def set_column_width(self, index: int, width: int) -> None:
        """就地改列宽并重绘。绕开 clear+重填 (2 万行重填在拖动中根本跟不上帧)。"""
        col = self.ordered_columns[index]
        if col.width == width:
            return
        col.width = width
        self._clear_caches()
        self._update_count += 1  # 行渲染缓存以它为 key, 不 +1 会拿到旧宽度的缓存行
        self._update_dimensions(())
        self.refresh()

    def _on_mouse_down(self, event: events.MouseDown) -> None:
        i = self._edge_at(event)
        if i is None:
            return
        self._drag_col, self._drag_x0 = i, event.screen_x
        self._drag_w0 = self.ordered_columns[i].width
        self._set_hover_edge(i)  # 拖动全程保持高亮 (鼠标此时未必还压在线上)
        self.capture_mouse()  # 拖出表格范围也继续收事件
        event.stop()
        event.prevent_default()

    def _on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag_col is None:
            self._set_hover_edge(self._edge_at(event))
            return  # 其余交给 DataTable 自己的 hover 处理
        self.set_column_width(
            self._drag_col, max(self.MIN_DRAG_W, self._drag_w0 + event.screen_x - self._drag_x0)
        )
        event.stop()
        event.prevent_default()

    def _on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag_col is None:
            return
        i, self._drag_col = self._drag_col, None
        self.release_mouse()
        self._set_hover_edge(self._edge_at(event))
        self._drag_guard = True  # 无论有没有真拖动, 这次 Click 都得吞掉
        width = self.ordered_columns[i].width
        if width != self._drag_w0:  # 只按了一下没拖: 不该把这列就此钉死成手动宽
            self.post_message(self.ColumnResized(i, width))
        event.stop()
        event.prevent_default()

    def cancel_drag(self) -> None:
        """作废进行中的列宽拖拽 (弹窗抢走鼠标时用)。

        退回按下前的宽度, 也不发 ColumnResized: 这次拖拽没走完, 鼠标停在哪纯属偶然,
        那个宽度既不该被记成手动列宽, 也不该留在屏幕上 —— 留着的话它会一直显示到
        下一次 _rebuild_columns (改筛选/选列/翻窗口), 再毫无来由地弹回去。
        """
        if self._drag_col is None:
            return
        self.set_column_width(self._drag_col, self._drag_w0)
        self._drag_col = None
        self.release_mouse()
        self._set_hover_edge(None)

    def _on_leave(self, event: events.Leave) -> None:
        self._set_hover_edge(None)

    def _on_click(self, event: events.Click) -> None:
        # 双击列头文字 → 重命名。拦下第二击, 原生 _on_click 就不会再发一次 HeaderSelected
        # (第一击已经发过, app 侧用 0.15s 定时器延后开值面板, 收到本消息就取消它)。
        meta = event.style.meta
        if (
            event.chain >= 2
            and not self._drag_guard
            and self.show_header
            and meta.get("row") == -1
            and "column" in meta
            and self._edge_at(event) is None
        ):
            self.post_message(self.HeaderDoubleClicked(meta["column"]))
            event.stop()
            event.prevent_default()
            return
        # guard 只在刚拖/刚按过分隔线时为真, 所以双击分隔线必定命中这里
        if not self._drag_guard:
            if event.chain == 1 and meta.get("row", -1) >= 0 and "column" in meta:
                # 不拦截: 原生 _on_click 照常移光标, app 只是额外收到"点了哪一格"
                self.post_message(self.CellClicked(meta["row"], meta["column"]))
            return
        self._drag_guard = False
        if event.chain >= 2:
            i = self._edge_at(event)
            if i is not None:
                self.post_message(self.ColumnResized(i, None))
        event.stop()
        event.prevent_default()


_HELP = t(
    """[b]dt view keys[/b]

  ↑/↓  j/k     select row (detail follows)
  PgUp/PgDn    full page     d/u (or Ctrl+d/u)  half page
  g/G          first/last row   Tab  switch focus (to scroll long conversations)
  ←/→          scroll sideways   h/l scroll 4 chars sideways
  ] / [        next/prev window (paging big files)   :  jump to row (-1 = last)
                 paging back from a tail window or full-file ops build the history index
                 on demand; in follow mode moving up pauses, G resumes tailing
  n / N        next/prev field in detail (conversations go per message: msg0/msg1…;
                 clicking a field selects it too)
  *            jump to the next search hit in detail (hits are highlighted in yellow)
  y            copy the current sample's JSON to the clipboard
  i            view the sample's images full-size (←/→ switch, Esc closes); clicking the
                 imgs cell or a 🖼 line in detail opens it too
  mouse drag   drag with the left button in detail to select text (what you see is what
                 you get, even across soft wraps), then Ctrl+c to copy; more clicks select
                 more: double = word (ids/values; - and _ count as word chars) · triple =
                 line · 4x = field block · 5x = whole detail; Esc or a click clears it
                 copies via OSC52 + local wl-copy/xclip/xsel (works over SSH/tmux too)
  v            multi-select samples (j/k extends), y copies them all, Esc cancels
  w            export the current browse sequence (or selection) to a file; format follows
                 the extension. .jsonl streams, so 100k+ rows use no memory; lineage is
                 written too, so dt history shows the source and conditions
  C            copy a dt view command that reproduces this view (with filter/search/sort)
  P            copy the processing-chain form: dt filter FILE '…' | dt sort - --by '…'
                 (same conditions; append -o FILE or more pipes to process the subset)
  |            run a shell pipe over the WHOLE file and browse its output, e.g.
                 dt filter - "turns(x)>=6" | dt sort - --by "chars(x)" --desc | dt head - 200
                 NDJSON in and out (dt, jq, grep … all work); every run starts from the
                 original file and replaces the previous result; r returns to the file;
                 C / P / w carry the pipe (dt view --pipe '…' restores it)
  s            full sort (enter a column name, prefix - to reverse; scans the whole file,
                 holds across windows)
  S            column snapshot (n·min·max·mean·non-empty rate of a column over the current
                 sequence; full distribution: dt stats)
  /            full search (every value of each record, incl. assistant replies;
                 case-insensitive, re: prefix for regex)
                 → hit subset + yellow highlights in table/detail; * hops between hits
  f            full filter (scans the whole file → hit subset): Python expr, row is x
                 same language as dt filter: derived columns are row functions
                       chars(x)>2000 · turns(x)>=6 · 'refund' in first_user(x)
                       search(x, 'refund') (whole record, like /) · 'get_weather' in calls(x)
                 other fields via x.: x.source=='alpaca' · len(x.messages)>=2
                       x.messages[-1].role=='assistant'
                       any('error' in m.content for m in x.messages)   (whole chat)
                 and/or/not/parentheses: turns(x)>=6 and (chars(x)<2000 or x.source=='a')
                 press f again to stack more conditions (combined with and)
  F / header   value filter (Excel-style): lists the column's unique values + counts,
                 check the ones to keep → subset
                 the search box on top narrows candidates by substring; with a query,
                 Apply keeps only the checked matches
                 click outside or Esc cancels; filtered headers show ▾; reopen to add
                 removed values back
  Esc          cancel a running scan
  Enter        zoom into the current sample (Esc to return)
  dbl-click hdr  rename the column: shows at once, the file is untouched until you quit,
                 then q asks save (dt clean --rename, lineage recorded) / discard;
                 f/s/S/F/| then take the new name (x.new_name)
  drag hdr │   resize columns (Excel-style): the │ right of each header is the divider;
                 hover turns it ┃, drag left/right to resize, double-click to auto-fit;
                 widths stick to the column name across windows and filters
  z            toggle side-by-side / stacked layout (default side-by-side)
  +/-          resize the table/detail split (5% per step)
  drag split   the border between table and detail (two rows, or two columns side-by-side)
                 is the split: it lights up on hover, drag it anywhere; double-click
                 restores the default 65:35
  c            choose columns (checkbox panel, applies to both table and detail)
  r            clear all filters/search/sort and browse the full file again (also scrolls
                 back to the left; after | it also leaves the pipe result)
               after a filter/search the horizontal position stays; if the current sample
               still matches, the cursor stays on it
  ?            help      q  quit""",
    """[b]dt view 快捷键[/b]

  ↑/↓  j/k     选行 (详情联动)
  PgUp/PgDn    整页      d/u (或 Ctrl+d/u)  半屏
  g/G          首/末行   Tab  切换焦点 (滚动长对话)
  ←/→          水平滚动   h/l 水平滚动 4 字符
  ] / [        下/上一窗口 (大文件翻页)   :  跳到行号 (-1 为末行)
                 尾窗首次前翻/全量操作会按需建历史索引；follow 中上移暂停，G 恢复追尾
  n / N        详情下/上一字段 (对话按条走: msg0/msg1…; 亦可鼠标点击选中)
  *            跳到详情中下一处搜索命中 (命中处画黄底)
  y            复制当前样本 JSON 到剪贴板
  i            大图查看当前样本的图片 (←/→ 切换, Esc 关闭); 点 imgs 单元格或详情里的
                 🖼 行也能打开
  鼠标拖选     详情区按住左键拖选文本 (所见即所选, 自动换行处不错位), 再按 Ctrl+c 复制;
                 连击逐级放大: 双击取词 (id/字段值, 连字符下划线算词内) · 三击整行 ·
                 四击整个字段块 · 五击整屏详情; Esc 或点一下清除选区
                 复制走 OSC52 + 本地 wl-copy/xclip/xsel 双通道 (SSH/tmux 下也进本机剪贴板)
  v            多选样本 (j/k 扩展选区), y 复制多条, Esc 取消
  w            导出当前浏览序列 (或多选选区) 到文件, 按扩展名定格式
                 .jsonl 流式写, 几十万行不占内存; 同时写血缘, dt history 可查来源与条件
  C            复制"复现当前视图"的 dt view 命令到剪贴板 (筛选/搜索/排序全带上)
  P            复制"处理链"形式: dt filter FILE '…' | dt sort - --by '…'
                 (同一套条件; 接 -o FILE 或继续管道即可处理这个子集)
  |            对**整个文件**跑一段 shell 管道, 浏览它的输出, 如
                 dt filter - "turns(x)>=6" | dt sort - --by "chars(x)" --desc | dt head - 200
                 进出都是 NDJSON (dt、jq、grep 都行); 每次都从原文件重跑并替换上一次的结果;
                 r 回到原文件; C / P / w 都会带上管道 (dt view --pipe '…' 可还原)
  s            全量排序 (输入列名, 加 - 反向; 扫全文件, 跨窗口有效)
  S            列快照 (某列的 n·min·max·mean·非空率, 当前浏览序列; 完整分布用 dt stats)
  /            全量搜索 (整条记录的每个值, 含 assistant 回复; 不分大小写, re: 前缀走正则)
                 → 命中子集 + 表格/详情里黄底高亮, 再用 * 逐个跳过去
  f            全量筛选 (扫全文件 → 命中子集): 表达式即 Python, 当前行叫 x
                 与 dt filter 同一套语言: 派生列是行函数
                       chars(x)>2000 · turns(x)>=6 · '退款' in first_user(x)
                       search(x, '退款') (搜整条记录, 同 /) · 'get_weather' in calls(x)
                 其余字段走 x.: x.source=='alpaca' · len(x.messages)>=2
                       x.messages[-1].role=='assistant'
                       any('报错' in m.content for m in x.messages)   (搜整段对话)
                 and/or/not/括号随意: turns(x)>=6 and (chars(x)<2000 or x.source=='a')
                 可反复按 f 叠加多条 (多条之间是 and)
  F / 点列头   列值勾选筛选 (Excel 式): 列出该列唯一值+频次, 勾选保留哪些 → 子集
                 顶部搜索框按子串过滤候选值; 有搜索词时应用 = 只保留勾选的匹配项
                 点面板外或按 Esc 取消; 被筛的列头带 ▾ 标记; 再次打开可加回已去掉的值
  Esc          (扫描时) 取消扫描
  Enter        放大当前样本 (Esc 返回)
  双击列头     重命名该列: 界面立即改, 文件退出前不动; q 时询问 保存 (等价 dt clean
                 --rename, 记血缘) / 丢弃; 之后 f/s/S/F/| 都按新名写 (x.新名)
  拖表头的 │   改列宽 (Excel 式): 表头每列右侧那道 │ 即分隔线, 鼠标压上去变 ┃
                 按住左右拖即改宽, 双击恢复自适应; 列宽记在列名上, 翻窗口/改筛选后仍在
  z            切换 左右 / 上下 布局 (默认左右)
  +/-          调整表格/详情两区大小 (每档 5%)
  拖两区分界   表格与详情之间那两行(横排时是两列)边框即分界, 鼠标压上去边框变亮,
                 按住拖到哪分界就到哪; 双击恢复默认 65:35
  c            选列 (勾选面板, 同时作用于表格和详情)
  r            清除全部筛选/搜索/排序, 回到全量浏览 (横向也回最左; | 之后也退出管道结果)
               筛选/搜索应用后横向位置保持不动; 原来那条样本还在命中里就继续停在它上面
  ?            帮助      q  退出

  搜索/筛选/排序都是全量的 (扫整个文件, 非仅当前窗口), 且可叠加;
  启动即带条件: dt view f.jsonl --where=... --search=... --sort=-chars
""",
)


# 双击取词的分段: 词 (\w 已含中文与下划线, 再带上 uuid/命名里的 -) / 空白 / 符号, 三类各自成段
_TOKEN_RE = re.compile(r"[\w-]+|\s+|[^\w\s-]+")


def _token_span(line: str, x: int) -> Tuple[int, int]:
    """命中 x 的那一段同类字符 [起, 止); 落在行尾之外就退化成一个字符。"""
    for m in _TOKEN_RE.finditer(line):
        if m.start() <= x < m.end():
            return m.start(), m.end()
    return x, x + 1


def _style_chars(strip: Strip, start: int, end: int, style: Style) -> Strip:
    """给 strip 的 [start, end) 字符区间叠加样式。

    按字符切而不是按 cell (Strip.divide) 切: 选区坐标来自 apply_offsets, 那是字符索引空间,
    宽字符 (中文) 下两者对不上, 按 cell 切会把选区高亮整体错位。
    """
    segments: List[Segment] = []
    x = 0
    for text, seg_style, control in strip:
        n = len(text)
        lo, hi = max(start - x, 0), min(end - x, n)
        x += n
        if lo >= hi:  # 整段在选区外
            segments.append(Segment(text, seg_style, control))
            continue
        if lo:
            segments.append(Segment(text[:lo], seg_style, control))
        segments.append(Segment(text[lo:hi], (seg_style + style) if seg_style else style, control))
        if hi < n:
            segments.append(Segment(text[hi:], seg_style, control))
    return Strip(segments, strip.cell_length)


class _FieldStatic(Static):
    """详情里的一个字段块。自己处理点击 (self 即被点字段, 无需坐标反查, 同 DataTable 选行),
    并支持鼠标拖选取词。

    拖选: textual 靠渲染 segment 上的 meta["offset"] 把屏幕坐标反查成内容坐标, 而字段渲染的是
    rich Group (角色标题 + 正文 + 搜索高亮), 这类 renderable 不带 offset —— 选区退化成"整块",
    且默认 get_selection 只认 Text/Content, 取不出文本 (即 textual 原生拖选在这里是死的)。
    这里把坐标空间直接定义为"渲染后的行/列": render_line 给每个 segment 打上 (字符索引, 行号),
    get_selection 按同一套渲染行文本切片 —— 所见即所选, 自动换行/缩进也不会错位。
    """

    def __init__(self, renderable, field_name: str):
        # 不设 id: remove_children 是异步卸载, 固定 id 会与新 mount 的 widget 撞 DuplicateIds
        super().__init__(renderable, classes="detail-field")
        self._field_name = field_name

    async def _on_click(self, event: events.Click) -> None:
        """点击选中本字段 (self 即被点字段, 无需坐标反查), 连击则分级放大选区:
        2 词 · 3 整行 · 4 整个字段块 · 5 整屏详情。

        覆写掉 textual 默认的 2=整块 / 3=整屏: 那个跨度对着数据看时太粗 —— 最常要复制的是
        一个 id、一个字段值, 那是"词"这一级, 一路加击才逐步放大。

        写成私有 handler 而不是 on_click: textual 每个类只取一个点击 handler, 私有优先,
        两个都定义的话公有那个根本不会被调用; 而 MRO 上每个类各取一个, 所以还得
        prevent_default 掐掉 Widget._on_click, 否则它的 2=整块/3=整屏会盖在这上面。
        """
        event.prevent_default()
        self.app.select_detail_field(self)  # 通知 app 选中本字段
        chain = event.chain
        if chain >= 5:
            self.select_container.text_select_all()
        elif chain == 4:
            self.text_select_all()
        elif chain == 1:
            k = self._image_line_at(event)
            if k is not None:
                self.app.open_detail_image(self._field_name, k)
        elif chain in (2, 3):
            offset = self._click_offset(event)
            if offset is not None:
                lines = self._plain_lines()
                line = lines[offset.y] if offset.y < len(lines) else ""
                lo, hi = (0, len(line)) if chain == 3 else _token_span(line, offset.x)
                span = TextSelection(Offset(lo, offset.y), Offset(hi, offset.y))
                self.screen.selections = {self: span}
        event.stop()
        await self.broker_event("click", event)

    def _image_line_at(self, event: events.Click) -> Optional[int]:
        """点在第 k 个 🖼 行上则返回 k (本字段内序号), 否则 None。拖选结束时的那次
        click 不算 —— 用户是在选路径文本, 不是要看图。"""
        sel = self.screen.selections.get(self)
        if sel is not None and sel.start != sel.end:
            return None
        offset = self._click_offset(event)
        if offset is None:
            return None
        lines = [ln.lstrip() for ln in self._plain_lines()]
        if offset.y >= len(lines) or not lines[offset.y].startswith(render.IMAGE_LINE_PREFIX):
            return None
        return sum(ln.startswith(render.IMAGE_LINE_PREFIX) for ln in lines[: offset.y])

    def _click_offset(self, event: events.Click) -> Optional[Offset]:
        """点击位置的内容坐标 (字符索引, 渲染行); 借 compositor 换算, 与拖选同一套坐标。"""
        widget, offset = self.screen.get_widget_and_offset_at(event.screen_x, event.screen_y)
        return offset if widget is self else None

    # -------------------------------------------------------------- #
    # 鼠标拖选 (选区靠 Ctrl+c 复制, 见 ViewApp.action_copy_selection)
    # -------------------------------------------------------------- #
    def _plain_lines(self) -> List[str]:
        """渲染行的纯文本; 行尾补白不是内容, 去掉免得复制出一串空格。"""
        base = super().render_line  # 绕开本类的 offset/高亮加工, 拿原始渲染行
        return [base(y).text.rstrip() for y in range(self.size.height)]

    def get_selection(self, selection) -> Optional[Tuple[str, str]]:
        return selection.extract("\n".join(self._plain_lines())), "\n"

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        if not strip:
            # 空行 (段落之间的空白) 渲染成 0 个 segment, 没有 segment 就没地方挂 offset,
            # textual 反查不到内容坐标就把这一端退化成"整块全选" —— 拖到一个空行, 选中的
            # 却是整个字段。补一个空格撑住这行的落点。
            strip = Strip([Segment(" ")], 1)
        selection = self.text_selection
        span = None if selection is None else selection.get_span(y)
        if span is not None:
            start, end = span
            if end == -1:
                end = len(strip.text)
            # 只叠背景: screen--selection 的前景是"完全透明"(意为不改前景), 扁平成 rich style
            # 时会被解析成与背景同色, 整段叠上去等于把文字涂没了。textual 自己走 Visual 那条
            # 路会保留原前景, 这里对齐它。
            selection_bg = self.screen.get_component_rich_style("screen--selection").bgcolor
            strip = _style_chars(strip, start, end, Style(bgcolor=selection_bg))
        # offset 必须最后打, 且打在最终的 segment 划分上: 高亮会把一个 segment 切成三段,
        # 沿用切之前的 offset 会让后两段都自称从原 segment 起点开始 —— 拖动中 textual 每次
        # 反查坐标都读这些 meta, 于是越拖越偏 (高亮从鼠标位置一路涂到行首)。
        return strip.apply_offsets(0, y)  # 打 offset: 屏幕坐标→字符索引


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
_PICK_HINT = t(
    "Space: toggle · a/n: all/none · or click below",
    "空格 勾选/取消 · a/n 全选/全不选 · 亦可点下方按钮",
)

# 面板中列表之外的固定行数 (边框2 + 内边距2 + 标题1 + 提示1&margin1 + 按钮1&margin1)
_PICKER_CHROME = 10
_VF_CHROME = _PICKER_CHROME + 2  # 值面板多一行搜索框 + 其 margin


class HelpScreen(ModalScreen):
    """帮助。放在 VerticalScroll 里: 帮助文本只会越加越长, 而终端高度是给定的,
    定高 Static 一旦超屏就把末尾几行连边框一起静默裁掉 (最先没的正是 q 退出那行)。"""

    BINDINGS = [Binding("escape,q,question_mark", "dismiss", t("Close", "关闭"))]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box"):
            yield Static(Text.from_markup(_HELP))

    def on_mount(self) -> None:
        self.query_one("#help-box", VerticalScroll).focus()  # 矮终端下可用 ↑↓ 滚动


class ImageScreen(ModalScreen):
    """一条样本里的图片逐张大图显示: ←/→ 切换, Esc/q/i 关闭 (弹窗占满全屏, 没有"框外")。

    放弹窗而不是详情里: 弹窗能用满整屏分辨率, 也不牵动详情的分批挂载与锚点定位。
    读图 (可能要下载) 在线程 worker 里, 结果按代次作废, 快速翻页不会串图。
    图由 textual-image 画 (kitty 图形协议 / sixel / 半块字符, 启动时探测终端决定)。
    """

    BINDINGS = [
        Binding("escape,q,i", "dismiss", t("Close", "关闭")),
        Binding("left,h", "go(-1)", t("Prev", "上一张")),
        Binding("right,l", "go(1)", t("Next", "下一张")),
    ]

    def __init__(self, items: List[Tuple[str, str]], start: int, root: str):
        super().__init__()
        self._items = items  # [(出处如 msg0 user, 引用)]
        self._i = start
        self._root = root
        self._gen = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="img-box"):
            yield Static(id="img-title")
            yield Vertical(id="img-view")
            yield Static(
                t("←/→ switch · Esc close", "←/→ 切换 · Esc 关闭"), id="img-hint", markup=False
            )

    def on_mount(self) -> None:
        self._show()

    def dismiss(self, result=None):
        # 关闭的各条路 (Esc/q/i) 都走这里; 卸载时子 widget 已先没了, 等不到那会儿
        self._release()
        return super().dismiss(result)

    def action_go(self, step: int) -> None:
        self._i = (self._i + step) % len(self._items)
        self._show()

    def _title(self, extra: str) -> Text:
        where, ref = self._items[self._i]
        title = Text(f"{self._i + 1}/{len(self._items)} · {where} · ", style="bold")
        title.append(render.image_label(ref))
        if extra:
            title.append(f" · {extra}", style="dim")
        return title

    def _release(self) -> None:
        """让 textual-image 把图从终端里删掉: kitty 协议传过去的图不随界面重绘消失。"""
        for w in self.query("#img-view .img"):
            w.image = None

    def _clear(self) -> None:
        self._release()
        self.query_one("#img-view", Vertical).remove_children()

    def _show(self) -> None:
        self._gen += 1
        gen, (_, ref) = self._gen, self._items[self._i]
        self.query_one("#img-title", Static).update(self._title(t("loading…", "加载中…")))
        self._clear()

        def load() -> None:
            try:
                got = image.load(ref, self._root)
            except image.ImageError as e:
                self.app.call_from_thread(self._loaded, gen, None, str(e))
            else:
                self.app.call_from_thread(self._loaded, gen, got, "")

        self.run_worker(load, thread=True, exclusive=True, group="image")

    def _loaded(self, gen: int, got, error: str) -> None:
        if gen != self._gen or not self.is_attached:
            return  # 已翻到别的图 / 已关闭
        view = self.query_one("#img-view", Vertical)
        if got is None:
            self.query_one("#img-title", Static).update(self._title(""))
            view.mount(Static(Text(f"⚠ {error}", style="bold red"), classes="img-msg"))
            return
        self.query_one("#img-title", Static).update(self._title(got.describe()))
        # 终端图形能力只能在 Textual 接管 stdin 前探测 (_run_tui 里按格式做了);
        # 没探测过就 import 会在运行中抢读 stdin, 所以此处只认已加载的模块
        widgets = sys.modules.get("textual_image.widget")
        if widgets is None:
            view.mount(
                Static(
                    t(
                        "No preview: the terminal graphics probe runs at startup only when the "
                        "first window has images, and it did not run or failed",
                        "无法预览: 终端图形探测只在首窗口有图时于启动时进行, 这次没有进行或失败了",
                    ),
                    classes="img-msg",
                )
            )
            return
        view.mount(widgets.Image(got.image, classes="img"))


class ColumnPicker(ModalScreen):
    """列显示勾选面板: 空格切换, Enter 应用 / Esc 取消。返回可见列名集合。

    checked 为打开时的勾选集: 未手动选过列时只勾行号列 #, 选过则回显当前可见列。
    勾选为空时提示并留在面板, 不返回空集。"""

    # priority=True: 抢在 SelectionList 之前处理, 否则 enter 会被它消费而无法关闭
    BINDINGS = [
        Binding("enter,c", "close", t("Apply", "应用"), priority=True),
        Binding("escape", "cancel", t("Cancel", "取消"), priority=True),
        Binding("a", "all", t("All", "全选")),
        Binding("n", "none", t("None", "全不选")),
    ]

    def __init__(
        self, columns: List[str], checked: Set[str], labels: Optional[Dict[str, str]] = None
    ):
        super().__init__()
        self._columns = columns
        self._checked = checked
        self._labels = labels or {}  # 原始列名 → 显示名 (重命名后); 值仍用原始名

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield Static(t("[b]Columns to show[/b]", "[b]选择要显示的列[/b]"), id="picker-title")
            yield SelectionList(id="cols")
            yield Static(f"[dim]{_PICK_HINT}[/dim]", id="picker-hint")
            with Horizontal(classes="panel-btns"):
                yield Button(t("All", "全选"), id="cp-all")
                yield Button(t("None", "全不选"), id="cp-none")
                yield Button(t("Apply", "应用"), id="cp-apply", variant="primary")
                yield Button(t("Cancel", "取消"), id="cp-cancel")

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
            sl.add_option(Selection(Text(self._labels.get(col, col)), col, col in self._checked))
        _fit_panel(self, sl, _PICKER_CHROME, hard_max=20)
        sl.focus()

    def action_all(self) -> None:
        self.query_one(SelectionList).select_all()

    def action_none(self) -> None:
        self.query_one(SelectionList).deselect_all()

    def action_close(self) -> None:
        selected = set(self.query_one(SelectionList).selected)
        if not selected:
            self.notify(t("Select at least one column", "至少选一列"))
            return
        self.dismiss(selected)

    def action_cancel(self) -> None:
        self.dismiss(None)


class HeaderEditScreen(ModalScreen):
    """列头原地改名: 一个输入框盖在被双击的列头格上, 背景不压暗。Enter 提交, Esc/点别处取消。"""

    BINDINGS = [Binding("escape", "cancel", t("Cancel", "取消"), show=False)]

    def __init__(
        self,
        value: str,
        cell: Region,
        text_x: int,
        right_aligned: bool,
        padding: int = 1,
        right: Optional[int] = None,
    ):
        super().__init__()
        self._value = value
        self._cell = cell  # 列头格的屏幕区域 (含左右 padding; 末格是列分隔线 │)
        self._text_x = text_x  # 列头文字起点: 输入文字从这里开始, 看起来是列头本身变成可编辑
        self._right_aligned = right_aligned  # 数值列: 变长时先向左长 (与右对齐的列头一致)
        self._padding = padding
        self._right = right  # 表格内容区右缘: 加宽时不越过它压到详情区

    def compose(self) -> ComposeResult:
        yield Input(value=self._value, id="hdr-edit")

    def on_mount(self) -> None:
        inp = self.query_one("#hdr-edit", Input)
        inp.styles.padding = (0, 0, 0, self._padding)  # 右侧不留 padding: 光标占列头右边距那一格
        self._fit(self._value)
        inp.focus()
        inp.action_end()

    def _fit(self, text: str) -> None:
        """框 = [x, 右缘): 左 padding 后接文字, 文字 + 行尾光标要放得下。

        默认右缘止于列分隔线之前 (分隔线仍可见), 文字起点对齐列头文字。装不下时:
        数值列先把左缘往左推到格子左边 (右对齐列变长本就向左长), 仍不够再向右越过
        分隔线加宽; 文本列直接向右加宽。都不越过表格右缘, 再长就在框内横向滚动。
        """
        limit = self._right if self._right is not None else self.app.size.width
        need = cell_len(text) + 1  # 文字 + 行尾光标
        p = self._padding
        x, right = self._text_x - p, self._cell.right - 1
        if right - (x + p) < need and self._right_aligned:
            x = max(self._cell.x, right - p - need)
        if right - (x + p) < need:
            right = min(limit, x + p + need)
        inp = self.query_one("#hdr-edit", Input)
        inp.styles.offset = (x, self._cell.y)
        inp.styles.width = max(1, right - x)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._fit(event.value)  # 边打边长, 不把开头滚出框外

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_click(self, event: events.Click) -> None:
        if event.screen_offset not in self.query_one("#hdr-edit", Input).region:
            self.dismiss(None)
            event.stop()


def _append_lineage(path: str, op_type: str, params: Dict, count: int) -> None:
    """原地写回的血缘: 文件已有血缘则在其记录上追加操作 (来源链不断), 否则新建一条指向自身。"""
    import orjson as _orjson

    from ...lineage import LineageTracker, _get_lineage_path, load_lineage

    existing = load_lineage(path)
    if existing is None:
        LineageTracker(path).record(
            op_type, params=params, input_count=count, output_count=count
        ).save(path, count)
        return
    existing.add_operation(op_type, params=params, input_count=count, output_count=count)
    existing.metadata["output_path"] = str(path)
    existing.metadata["output_count"] = count
    with open(_get_lineage_path(path), "wb") as f:
        f.write(_orjson.dumps(existing.to_dict(), option=_orjson.OPT_INDENT_2))


class SaveScreen(ModalScreen):
    """退出时的待保存询问: 写回原文件 / 丢弃 / 取消。返回 "write" | "discard" | None。"""

    BINDINGS = [
        Binding("escape", "cancel", t("Cancel", "取消"), priority=True),
        Binding("s", "write", t("Save", "保存"), priority=True),
        Binding("d", "discard", t("Discard", "丢弃"), priority=True),
    ]

    def __init__(self, summary: str, command: Optional[str], can_write: bool, why_not: str = ""):
        super().__init__()
        self._summary, self._command, self._can_write, self._why_not = (
            summary,
            command,
            can_write,
            why_not,
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="save-box"):
            yield Static(t("[b]Unsaved column renames[/b]", "[b]未保存的列重命名[/b]"))
            yield Static(escape(self._summary))
            if self._command:
                yield Static(f"[dim]= {escape(self._command)}[/dim]")
            if not self._can_write:
                yield Static(f"[yellow]{escape(self._why_not)}[/yellow]")
            with Horizontal(classes="panel-btns"):
                if self._can_write:
                    yield Button(t("Save (s)", "保存 (s)"), id="sv-write", variant="primary")
                yield Button(t("Discard (d)", "丢弃 (d)"), id="sv-discard")
                yield Button(t("Cancel (Esc)", "取消 (Esc)"), id="sv-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        {
            "sv-write": self.action_write,
            "sv-discard": self.action_discard,
            "sv-cancel": self.action_cancel,
        }[event.button.id]()

    def action_write(self) -> None:
        if self._can_write:
            self.dismiss("write")

    def action_discard(self) -> None:
        self.dismiss("discard")

    def action_cancel(self) -> None:
        self.dismiss(None)


class ValueFilterScreen(ModalScreen):
    """Excel 式列值勾选筛选: 列出某列唯一值(带频次), 勾选要保留的值。

    - 顶部搜索框实时按子串过滤候选值 (大小写不敏感), 唯一值成百上千时靠它定位。
    - 有搜索词时应用 = 只保留 勾选∩匹配 (Excel 语义: 所见即所得); 匹配项一个没勾时
      = 保留全部匹配项, 于是"某列包含某子串"= 打字 → Enter, 两步完成。
    - 有搜索词时 全选=勾上匹配项(不动视野外勾选) / 全不选=只取消匹配项 —— 因此
      跨搜索词可累积勾选 (搜A全选→搜B全选→清空搜索词→应用 = A∪B)。
    - prior 非 None 时回显上次保留集 (故可把去掉的值重新勾回); 否则默认全不选。
    - anchor 非 None 时面板贴着被点列头下方弹出 (右溢出自动左移), 否则居中。
    - Enter 应用返回勾选集合, Esc 或点击面板外返回 None (取消)。

    勾选状态的真值是 ``self._checked``, 不是 SelectionList —— 列表随搜索词重建,
    被过滤掉的项不在列表里, 只能靠 _checked 记住。

    高基数列: 列表只渲染前 _MAX_SHOW 项 (按频次降序) 防 UI 卡死, 但搜索/应用/
    全选/全不选作用于全量匹配项 —— "打字 → Enter" 对未显示的值同样生效。
    """

    _BOX_W = 56
    _MAX_SHOW = 1000  # 列表最多渲染的候选值数; 超出部分靠搜索框缩小范围后可见

    BINDINGS = [
        Binding("enter", "close", t("Apply", "应用"), priority=True),
        Binding("escape", "cancel", t("Cancel", "取消"), priority=True),
        Binding("down", "focus_list", t("To list", "进入列表"), show=False),
        Binding("a", "all", t("All", "全选")),
        Binding("n", "none", t("None", "全不选")),
    ]

    def __init__(
        self,
        col: str,
        items: List,
        total: int,
        prior=None,
        anchor=None,
        label: str = "",
        header: Optional[Region] = None,
    ):
        super().__init__()
        self._col = col
        self._label = label or col  # 标题给人看: 列改名后显示新名, 约束仍按原名
        self._header = header  # 被点列头格的屏幕区域: 落在这里的第二击 = 双击 → 转重命名
        self._items = items  # [(value, count), ...] 按频次降序
        self._total = total
        self._prior = prior  # 上次保留值集 (None=未筛→默认全不选)
        self._anchor = anchor  # (x, y) 列头下方; None=居中
        self._checked: Set[str] = set() if prior is None else {v for v, _ in items if v in prior}
        self._query = ""
        self._shown: List[str] = []  # 当前列表实际渲染的值 (≤_MAX_SHOW), _sync 的作用域

    def compose(self) -> ComposeResult:
        with Vertical(id="vf-box"):
            yield Static(id="picker-title")
            yield Input(
                placeholder=t("Type to filter values…", "输入子串过滤候选值…"), id="vf-search"
            )
            yield SelectionList(id="cols")
            yield Static(id="picker-hint")
            with Horizontal(classes="panel-btns"):  # 鼠标可点: 全流程无需回键盘
                yield Button(t("All", "全选"), id="vf-all")
                yield Button(t("None", "全不选"), id="vf-none")
                yield Button(t("Apply", "应用"), id="vf-apply", variant="primary")
                yield Button(t("Cancel", "取消"), id="vf-cancel")

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
        below = None
        if self._anchor is not None:
            # 列头下方放得下 (列表至少 3 行) 就压缩列表贴在下方, 不上移盖住列头行
            below = self.app.size.height - self._anchor[1] - _VF_CHROME
        hard_max = min(14, below) if below is not None and below >= 3 else 14
        list_h = _fit_panel(self, self.query_one(SelectionList), _VF_CHROME, hard_max=hard_max)
        if self._anchor is not None:  # 贴列头下方弹出; 溢出则左移/上移, 保证整块可见
            x, y = self._anchor
            x = max(0, min(x, self.app.size.width - self._BOX_W))
            y = min(y, max(0, self.app.size.height - (list_h + _VF_CHROME)))
            box = self.query_one("#vf-box", Vertical)
            self.styles.align = ("left", "top")
            box.styles.offset = (x, y)

    def on_click(self, event: events.Click) -> None:
        """点击值筛选卡片外的模态背景时按“取消”语义关闭。

        单击列头开本面板只延后 0.15s, 人手双击常慢于这个间隔, 第二击就落到了本面板上:
        它落在同一列头格里且 textual 判为连击 (0.5s 内同位置) 时, 按双击处理 → 交回 app 改名。
        这个判断先于"点在面板内": 极矮的终端里面板只能上移盖住列头行, 双击仍要能改名。
        """
        if event.chain >= 2 and self._header is not None and event.screen_offset in self._header:
            self.dismiss("rename")
        elif event.screen_offset in self.query_one("#vf-box", Vertical).region:
            return
        else:
            self.dismiss(None)
        event.stop()

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
            label = val if val != "" else t("(empty)", "(空)")
            if len(label) > 46:
                label = label[:45] + "…"
            sl.add_option(Selection(Text(f"{label}  ({cnt})"), val, val in self._checked))
        scope = (
            t(f"{len(matched)}/{self._total} match", f"匹配 {len(matched)}/{self._total}")
            if self._query
            else t(f"{self._total} values", f"{self._total} 个值")
        )
        if len(matched) > len(shown):
            scope += t(f", showing first {len(shown)}", f", 仅显示前 {len(shown)}")
        self.query_one("#picker-title", Static).update(
            Text.from_markup(
                t(
                    f"[b]Filter {escape(self._label)}[/b] [dim]({scope})[/dim]",
                    f"[b]按 {escape(self._label)} 值筛选[/b] [dim]({scope})[/dim]",
                )
            )
        )
        if self._query:
            hint = t(
                "Apply keeps checked matches · ↓ then Space checks",
                "应用 = 只保留勾选的匹配项 · ↓ 进列表空格勾选",
            )
        elif len(matched) > len(shown):
            hint = t(
                "Too many; type to narrow · Apply keeps matches",
                "候选过多, 输入子串缩小范围 · 应用 = 只保留匹配项",
            )
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
        """应用。有搜索词时只保留 勾选∩匹配 (所见即所得); 匹配项一个没勾则取全部匹配项 ——
        默认全不选下 "打字 → Enter" 即等于按包含子串筛选, 不必再点全选。
        结果为空时留在面板提示: 关掉会丢掉刚扫完的值表, 大文件重扫代价高。"""
        self._sync()
        selected = set(self._checked)
        if self._query:
            matched = {v for v, _ in self._matched()}
            selected = (selected & matched) or matched
        if not selected:
            self.notify(t("Select at least one value", "至少选一个值"))
            return
        self.dismiss(selected)

    def action_cancel(self) -> None:
        self.dismiss(None)


# 导出范围 (稳定键, 写进血缘) → 界面文案
_SCOPE_LABELS = {
    "selection": t("selection", "选区"),
    "filtered": t("filtered subset", "筛选子集"),
    "all": t("all", "全部"),
    "all_unknown": t(
        "all (index built on demand, row count TBD)", "全部（将按需补全索引，行数待定）"
    ),
}


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
    /* Border titles carry identity (file · format, position, sample, field): readable, not border-tinted */
    #table, #detail {
        border-title-color: $text; border-title-style: bold;
        border-subtitle-color: $text-muted;
    }
    /* Scrollbars recede: the default black track and blue thumb outshine the data */
    #table, #detail {
        scrollbar-background: $surface; scrollbar-background-hover: $surface;
        scrollbar-background-active: $surface; scrollbar-corner-color: $surface;
        scrollbar-color: $panel-lighten-2; scrollbar-color-hover: $panel-lighten-3;
        scrollbar-color-active: $primary;
    }
    /* Field separator as a border, not a widget of its own: halves the widget count on long chats */
    .detail-field { border-top: solid $foreground 20%; }
    .detail-field:first-child { border-top: none; }
    /* Mouse over the split line: light up the border along it to show it can be dragged */
    #table.split-hot { border: round $accent; }
    #detail.split-hot { border: round $accent; }
    #table.hidden { display: none; }
    #prompt { dock: bottom; display: none; }
    #prompt.active { display: block; }
    #statusbar { dock: bottom; height: 1; background: $panel; color: $text-muted; padding: 0 1; }
    #status { width: 1fr; height: 1; }
    #hint { width: auto; height: 1; padding-left: 2; }
    /* Fixed width: width:auto collapses on VerticalScroll (scroll containers don't size to content).
       98 = longest help line + padding + border; max-* 100% scrolls instead of clipping on small terminals */
    #help-box { padding: 1 2; border: round $primary; background: $surface;
                width: 98; max-width: 100%; height: auto; max-height: 100%; }
    #help-box Static { width: auto; }
    ImageScreen { align: center middle; }
    #img-box { width: 100%; height: 100%; border: round $primary; background: $surface;
               padding: 0 1; }
    #img-title { height: auto; }
    #img-view { height: 1fr; align: center middle; }
    #img-view .img { width: auto; height: auto; }
    #img-view .img-msg { width: auto; }
    #img-hint { height: 1; color: $text-muted; text-align: center; width: 1fr; }
    ColumnPicker { align: center middle; }
    #picker-box { width: 56; max-width: 100%; height: auto; max-height: 100%;
              border: round $primary;
                  background: $surface; padding: 1 2; }
    #picker-title { text-align: center; width: 1fr; margin-bottom: 1; }
    #picker-box #cols { width: 1fr; height: auto; max-height: 20; background: $surface; }
    #picker-hint { text-align: center; width: 1fr; margin-top: 1; }
    SaveScreen { align: center middle; }
    #save-box { width: 72; max-width: 100%; height: auto; max-height: 100%;
                border: round $warning; background: $surface; padding: 1 2; }
    #save-box Static { width: 1fr; }
    HeaderEditScreen { background: transparent; align: left top; }
    #hdr-edit { border: none; height: 1; padding: 0; background: $boost; text-style: bold; }
    ValueFilterScreen { align: center middle; }
    #vf-box { width: 56; max-width: 100%; height: auto; max-height: 100%;
              border: round $primary;
              background: $surface; padding: 1 2; }
    #vf-box #cols { width: 1fr; height: auto; max-height: 14; background: $surface; }
    /* Compact search box: drop the 2 rows of Input's default border so the panel stays on screen */
    #vf-search { border: none; height: 1; padding: 0; margin-bottom: 1;
                 background: $boost; width: 1fr; }
    /* Compact one-line buttons: drop Button's default border / height:3 / min-width:16 */
    .panel-btns { width: 1fr; height: auto; align: center middle; margin-top: 1; }
    .panel-btns Button {
        height: 1; min-width: 0; border: none; padding: 0 1; margin: 0 1; color: $text;
    }
    .panel-btns Button.-primary { background: $primary; }
    """

    BINDINGS = [
        Binding("q", "quit", t("Quit", "退出")),
        Binding("question_mark", "help", t("Help", "帮助")),
        Binding("slash", "search", t("Search", "搜索")),
        Binding("f", "filter", t("Filter", "筛选")),
        Binding("F", "value_filter", t("Value filter", "值筛选")),
        Binding("s", "sort", t("Sort", "排序")),
        Binding("S", "snapshot", t("Snapshot", "列快照")),
        Binding("z", "toggle_layout", t("Layout", "布局")),
        Binding("r", "reset", t("Reset", "重置")),
        Binding("enter", "zoom", t("Zoom", "放大")),
        Binding("escape", "unzoom", t("Back", "返回"), show=False),
        Binding("g", "top", t("Top", "首行"), show=False),
        Binding("G", "bottom", t("Bottom", "末行"), show=False),
        # DataTable 内置只认箭头键, 这里补 vim 键 (与帮助屏承诺一致)
        Binding("j", "cursor_down", t("Down", "下移"), show=False),
        Binding("k", "cursor_up", t("Up", "上移"), show=False),
        # h/l 每次水平滚动 4 字符，方向键保留 Textual 默认的单字符跨度。
        Binding("h", "scroll_left", t("Scroll left", "左滚"), show=False),
        Binding("l", "scroll_right", t("Scroll right", "右滚"), show=False),
        # 调整表格/详情两区大小 (竖排调高度, 横排调宽度)
        Binding("plus", "grow_table", t("Table+", "表格+"), show=False),
        Binding("equals_sign", "grow_table", t("Table+", "表格+"), show=False),
        Binding("minus", "shrink_table", t("Table-", "表格-"), show=False),
        # 半屏滚动: d/u 单键 (ctrl+d/u 同义, 照顾 vim 习惯); PgUp/PgDn 整页
        Binding("d", "half_down", t("Half page down", "半屏下"), show=False),
        Binding("u", "half_up", t("Half page up", "半屏上"), show=False),
        Binding("ctrl+d", "half_down", t("Half page down", "半屏下"), show=False),
        Binding("ctrl+u", "half_up", t("Half page up", "半屏上"), show=False),
        # 列显示选择器: c 打开勾选面板 (同时作用于表格列和详情字段)
        Binding("c", "columns", t("Columns", "选列"), show=False),
        # 大文件窗口翻页: ] 下一窗口, [ 上一窗口, : 跳到指定行号
        Binding("right_square_bracket", "next_window", t("Next window", "下一窗口"), show=False),
        Binding("left_square_bracket", "prev_window", t("Prev window", "上一窗口"), show=False),
        Binding("colon", "jump", t("Jump to row", "跳行"), show=False),
        # n/N: 详情内下/上一字段精确定位 (绕过滚动条像素限制, 底部字段也可达)
        Binding("n", "next_field", t("Next field", "下一字段"), show=False),
        Binding("N", "prev_field", t("Prev field", "上一字段"), show=False),
        # *: 只在含搜索命中的字段间跳 (n/N 的过滤版, 长对话里直奔命中那条消息)
        Binding("asterisk", "next_match", t("Next hit", "下一命中"), show=False),
        # 复制到剪贴板: y 复制当前样本 JSON; v 多选样本后 y 复制
        Binding(
            "ctrl+c", "copy_selection", t("Copy selection", "复制选区"), show=False, priority=True
        ),
        Binding("y", "yank", t("Copy", "复制"), show=False),
        Binding("i", "images", t("Images", "看图"), show=False),
        Binding("v", "visual", t("Multi-select", "多选"), show=False),
        # 落地: w 导出当前子集到文件, C 复制可复现当前视图的命令
        Binding("w", "export", t("Export", "导出"), show=False),
        Binding("C", "copy_command", t("Copy command", "复制命令"), show=False),
        Binding("P", "copy_pipeline", t("Copy pipeline", "复制处理链"), show=False),
        # |: 在 view 里跑一段 shell 管道 (dt … | dt …), 结果替换浏览数据
        Binding("vertical_line", "pipe", t("Pipe", "管道"), show=False),
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
        follow: bool = False,
        start_at_end: bool = False,
        pipe: Optional[str] = None,
        format_hint: Optional[str] = None,
        image_root: str = ".",
    ):
        super().__init__()
        self._image_root = image_root  # 图片相对路径的基准目录 (--image-root, 默认数据文件所在目录)
        self.source = source  # RowSource: 随机窗口访问, 内存 O(窗口)
        # | 管道: 结果替换 source; 原文件留着给 r 回退和下一次管道 (输入永远是原文件)
        self._origin_source = source
        self._origin_fmt = fmt
        self._format_hint = format_hint  # 用户 --format 强制的格式, 换数据后仍尊重
        self._pipe: Optional[str] = None  # 当前生效的管道原句, None = 在看原文件
        self._init_pipe = pipe
        self._after_worker: Optional[Tuple[object, Callable[[], None]]] = None
        self.cap = cap  # 单窗口行数
        self.win_offset = win_offset  # 当前窗口在"当前浏览序列"中的起始位置 (0-based)
        self.all_rows = window  # 当前窗口已 parse 的行
        # 当前浏览序列: subset=None 时为"原始文件顺序"; 否则为一串全局行号 —— 筛选命中集,
        # 且当有排序时按排序键重排过 (排序与筛选共用同一条管线, 语义一致且跨窗口有效)。
        # _global_nos 与 all_rows 对齐, 记每行真实全局行号 (供 # 列/跳行两模式统一显示)。
        self._subset: Optional[List[int]] = None
        self._global_nos: List[int] = self.source.row_numbers(win_offset, len(window))
        self._filter_label: Optional[str] = None  # 状态栏显示的全量筛选说明
        # 统一约束模型: 子集 = 全文件中满足 (搜索 且 每条 where 且 每列值约束) 的行, 再按排序键排。
        # 三类约束分开存而不是塞进一个槽: 各自可独立增删/回显, 且能逐条翻译成 --where 复现。
        self._col_value_filters: Dict[str, set] = {}  # 列 → 保留值集 (故某列可反复调整/加回)
        self._wheres: List[str] = []  # where 表达式原文, 多条 AND (谓词由 spec 现编, 不另存)
        self._search_text: Optional[str] = None  # 原始搜索词 (含 re: 前缀), 供复现命令
        self._search_re: Optional[Pattern] = None  # 编译后的 pattern: 既筛选也用于高亮
        self._sort_spec: Optional[Tuple[str, bool]] = None  # (列名, 是否降序)
        # 已落地的约束 spec + 由它编译的谓词: 前者用于判断新约束是不是"收紧"(可只扫子集),
        # 后者供 follow 增量行复用 (不必每行重编译)
        self._applied_spec: Optional[ScanSpec] = None
        self._row_ok: Optional[Callable] = None
        self._scan_cancel: Optional[object] = None  # 扫描中的取消 Event (threading.Event)
        self._scan_gen = 0  # 扫描代次: 迟到的结果靠它作废 (详见 _scan_superseded)
        self._scan_rollback = None  # 本次扫描发起前的约束快照 (取消/失败时退回)
        self._scan_msg: str = ""  # 扫描进度文案 (worker 线程回填, 状态栏展示)
        self._index_navigation = False
        self.fmt = fmt
        self.filename = filename
        self.filepath = filepath  # 真实路径 (复现命令/血缘用); stdin 模式为 None
        self._follow = follow
        self._follow_pinned = follow
        self._start_at_end = start_at_end
        self._follow_polling = False
        self._follow_moving = start_at_end
        self._follow_pending = 0
        self._follow_partial = False
        self._follow_missing = False
        self._follow_generation = getattr(source, "generation", 0)
        self._follow_sort_snapshot = False
        self._format_auto_empty = not window and fmt == "generic"
        self._init_where = list(where or [])  # 启动参数, on_mount 后统一走一次扫描
        self._init_search = search
        self._init_sort = sort
        # 列目录按已加载窗口增量取并集: JSONL 不为 schema 额外 parse 全文件, 但当前窗口内
        # 任何行的字段都不会再因“只看前 50 行”而消失。训练格式的额外元数据先自动收起,
        # 仍完整保留在 c 面板；自动收起不影响详情, 用户主动隐藏才同时作用于表格和详情。
        self.columns = render.build_columns(window, fmt)
        default_visible = set(render.default_visible_columns(self.columns, fmt))
        self._auto_hidden: Set[str] = set(self.columns) - default_visible
        self._hidden: Set[str] = set()
        self._columns_customized = False
        self.view_indices: List[int] = list(range(len(window)))
        self._row_keys: List[str] = []
        self._row_key_seq = 0
        self._field_texts: List[str] = []  # 详情各字段的纯文本, 供 * 找命中
        self._prompt_mode: Optional[str] = None
        self._split = 65  # 表格占比 (%), 默认 65:35; 键盘 +/- 走 5% 档, 鼠标拖分界是连续的
        self._split_drag = False  # 正在拖两区分界
        self._split_hint = False  # 鼠标压在分界上: 状态栏说明这条线能拖
        # 详情每字段一个 Static widget (真实布局, 无测量误差); 锚点 {字段名: 起始行} 由布局算出。
        # _fields 是当前样本的全部字段, _field_widgets 是已挂上的前缀 (长样本分批挂, 见
        # _refresh_detail); 字段序号 _field_i 始终按 _fields 算。
        self._fields: List[Tuple[str, RenderableType]] = []
        self._field_widgets: List[Static] = []
        self._mount_gen = 0  # 分批挂载代次: 换样本即作废上一样本还没挂完的批次
        self._cur_anchors: Dict[str, int] = {}
        self._field_i = 0  # 当前字段索引 (滚动时同步顶部字段, n/N/点击 精确接管)
        # 详情渲染代次: 渲染收尾回调比按键晚一帧, 靠它判断"这次回调是否已被取代"
        self._detail_gen = 0
        # 光标高亮代次: 按键排队 (长按 j) 时只渲染最后一次高亮的样本, 中间的全跳过
        self._highlight_gen = 0
        self._nav_lock = False  # 导航/定位期间抑制 scroll_y watch 回退当前字段
        self._visual_anchor: Optional[int] = (
            None  # visual 多选起点 (view_indices 位置); None=非选择态
        )
        # 用户拖出来的列宽 {列名: 内容宽}: 只认名字, 所以换窗口/改可见列/改格式后依然保留
        self._manual_widths: Dict[str, int] = {}
        self._numeric_cols: Set[str] = set()  # 右对齐的数值列, 随列重建重算
        self._edge_hint = False  # 鼠标压在列分隔线上: 状态栏说明这条线能干什么
        # 列重命名 {原始列名: 新名}: 只改显示, 文件到退出时按用户选择才写回 (见 action_quit)
        self._renames: Dict[str, str] = {}
        self._value_scan_gen = -1  # 单击列头起的值扫描代次: 双击到来时只取消它, 不误伤别的扫描
        self._header_timer = None  # 单击列头延后 0.15s 开值面板, 双击到来则取消

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
        return f"{self._shown(name)}{'↓' if desc else '↑'}"

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
        self.notify(
            t(
                "A scan is running; press Esc to cancel it before changing conditions",
                "扫描进行中, 先按 Esc 取消再改条件",
            ),
            severity="warning",
        )
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
        self._index_navigation = False

    def _run_scan(self, body: Callable, gen: int):
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

        return self.run_worker(guarded, thread=True, exclusive=True, group="scan")

    def _on_scan_crashed(self, msg: str, gen: int) -> None:
        if self._scan_superseded(gen):
            return
        self._end_scan()
        self._rollback_constraints()  # 这次改动没生效, 约束退回改之前
        if self._sort_spec is None:
            self._follow_sort_snapshot = False
        self.notify(
            escape(t(f"Scan failed: {msg}", f"扫描失败: {msg}")), severity="error", timeout=10
        )
        self._update_status()

    # ------------------------------------------------------------------ #
    # 约束的"提交时机": 改约束只是提案, 扫描结果落地才算数
    # ------------------------------------------------------------------ #
    def _constraints_snapshot(self):
        """当前约束集的快照 (深到能独立回滚)。"""
        return (
            self._search_text,
            self._search_re,
            list(self._wheres),
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
            self._wheres,
            self._col_value_filters,
            self._sort_spec,
        ) = self._scan_rollback
        self._scan_rollback = None

    def _has_filters(self) -> bool:
        """是否存在"筛掉行"的约束 (排序不算 —— 它只重排, 不改变行集)。"""
        return bool(self._search_text or self._wheres or self._col_value_filters)

    def _spec(self) -> ScanSpec:
        """当前约束的不可变快照。扫描、跨进程传递、"是否收紧"的比较都以它为准。"""
        return scan.make_spec(
            self.fmt, self._search_text, self._wheres, self._col_value_filters, self._sort_spec
        )

    def _commit_spec(self, spec: ScanSpec) -> None:
        """扫描结果落地时记下这一版约束 (供下次判断收紧) 并编译好谓词 (供 follow 增量行)。"""
        self._applied_spec = spec
        self._row_ok = scan.build_row_ok(spec)

    def compose(self) -> ComposeResult:
        # 默认左右布局 (horizontal): 表格在左、详情在右。z 切回上下。
        with Vertical(id="main", classes="horizontal"):
            # fixed_columns=1: 冻结 # 索引列, 列多水平滚动时始终可见 (# 恒为第一列, 不可隐藏)
            yield FastDataTable(id="table", cursor_type="row", zebra_stripes=True, fixed_columns=1)
            yield VerticalScroll(id="detail")  # 每字段一个 Static, 动态挂载 (真实布局定位)
        yield Input(id="prompt")
        # 状态栏两段: 左边会变的状态 (窄屏被截的是它的右端), 右边常驻按键提示
        with Horizontal(id="statusbar"):
            yield Static(id="status")
            yield Static(id="hint")

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        self._add_columns(table)
        self._populate()
        if self._start_at_end and self.view_indices:
            table.move_cursor(row=len(self.view_indices) - 1)
            self.call_after_refresh(self._unlock_follow_move)
        self._apply_split()
        # 详情滚动时同步当前字段并刷新状态栏 (拖动/翻页均触发)
        self.watch(self.query_one("#detail", VerticalScroll), "scroll_y", self._on_detail_scroll)
        table.focus()
        if self._init_pipe:
            # 管道先跑, where/search/sort 作用在它的结果上 (在 _on_pipe_done 里接着调)
            self._apply_pipe(self._init_pipe, after=self._apply_initial_constraints)
        else:
            self._apply_initial_constraints()
        if self._follow:
            self.set_interval(0.5, self._poll_follow)

    def _apply_initial_constraints(self) -> None:
        """把 --where/--search/--sort 装进约束模型, 再走一次和 TUI 内完全相同的扫描。

        刻意复用同一条管线 (而不是启动时另写一套筛选): 命令行进来的条件和手按 f/s 得到的
        子集必然一致, 也免得两处语义漂移。
        """
        empty = self._constraints_snapshot()
        for expr in self._init_where:
            try:
                scan.compile_where(expr)  # 只为校验: 谓词由 spec 现编
                self._wheres.append(expr)
            except ValueError as e:
                self.notify(escape(f"--where {expr}: {e}"), severity="error")
        if self._init_search:
            try:
                self._search_re = compile_search(self._init_search)
                self._search_text = self._init_search
            except re.error as e:
                self.notify(
                    escape(
                        t(
                            f"--search {self._init_search}: invalid regex ({e})",
                            f"--search {self._init_search}: 正则无效 ({e})",
                        )
                    ),
                    severity="error",
                )
        if self._init_sort:
            self._set_sort_spec(self._init_sort)
        if self._has_filters() or self._sort_spec is not None:
            # 快照是"空约束": 首屏扫描按 Esc 取消 = 放弃命令行给的条件, 直接看全量
            self._recompute_subset(empty)

    def _visible_columns(self) -> List[str]:
        hidden = self._hidden | self._auto_hidden
        return [c for c in self.columns if c not in hidden]

    def _merge_columns(self, rows: List[Dict]) -> bool:
        """把新窗口字段并入稳定列目录；返回是否发现新列。"""
        known = set(self.columns)
        added = [c for c in render.build_columns(rows, self.fmt) if c not in known]
        if not added:
            return False
        self.columns.extend(added)
        if self._columns_customized:
            # 用户已经明确选过列，此后新发现字段先放进 c 面板，不能擅自打乱其布局。
            self._hidden.update(added)
        else:
            visible = set(render.default_visible_columns(self.columns, self.fmt))
            self._auto_hidden = set(self.columns) - visible
        return True

    def _header_plain(self, name: str) -> str:
        """列头纯文本 (含值筛选标记), 用于列宽估算。"""
        shown = self._shown(name)
        return f"{shown} ▾" if name in self._col_value_filters else shown

    def _header_label(self, name: str) -> RenderableType:
        """列头显示: 被值筛选的列加黄色漏斗 ▾ 标记, 一眼可辨; 对齐方式随该列单元格。"""
        label = self._shown(name)
        if name in self._col_value_filters:
            label += " ▾"
        style = "bold yellow" if name in self._col_value_filters else ""
        if self._right_aligned(name):  # 与单元格同样右侧留一格 (列宽里表头已含这一格)
            return _pad_right(Text(label, style=style, justify="right"))
        return Text(label, style=style)

    def _right_aligned(self, name: str) -> bool:
        return name == "#" or name in self._numeric_cols

    # ------------------------------------------------------------------ #
    # 列重命名: 界面即时, 文件退出时写回
    # ------------------------------------------------------------------ #
    def _active_renames(self) -> Dict[str, str]:
        """当前数据源上生效的改名。改名是原文件之上的一层"看法"; 管道态看的是管道结果,
        它的列名已经是新名 (喂进管道的就是改过名的行), 不再叠一层。"""
        return {} if self._pipe is not None else self._renames

    def _shown(self, col: str) -> str:
        """列的显示名 (重命名后)。约束/血缘用磁盘原名存, 人看到和敲的都是它。"""
        return self._active_renames().get(col, col)

    def _original(self, shown: str) -> str:
        """显示名 → 原始列名 (提示框里用户敲的是看到的名字)。"""
        for col, new in self._active_renames().items():
            if new == shown:
                return col
        return shown

    def _to_disk_expr(self, expr: str) -> str:
        """按新名写的条件 → 磁盘原名 (存储/扫描/C/P/血缘都对磁盘文件成立)。"""
        renames = self._active_renames()
        return rename_fields(expr, {new: old for old, new in renames.items()}) if renames else expr

    def _to_shown_expr(self, expr: str) -> str:
        """存储的条件 → 显示给人看的新名写法。"""
        renames = self._active_renames()
        return rename_fields(expr, renames) if renames else expr

    def _shown_columns(self) -> str:
        return ", ".join(self._shown(c) for c in self.columns)

    def _apply_renames(self, row: Dict) -> Dict:
        """显示用的改名: 不做冲突检查 (校验在输入时按列目录做, 写回时按每一行做), 渲染绝不抛错。"""
        renames = self._active_renames()
        if not renames or not isinstance(row, dict):
            return row
        return {renames.get(k, k): v for k, v in row.items()}

    def _pipe_blocks_rename(self) -> bool:
        if self._pipe is None:
            return False
        self.notify(
            t(
                "Renaming applies to the file; leave the pipe first (r)",
                "改名作用于原文件; 先按 r 退出管道",
            ),
            severity="error",
        )
        return True

    def _rename_column(self, col: str, new: str) -> None:
        """把原始列 col 显示为 new。校验在此刻报错, 不留到保存。"""
        if self._pipe_blocks_rename():
            return
        new = new.strip()
        derived = render.derived_columns(self.fmt)
        if col == "#" or col in derived or col not in self.columns:
            self.notify(
                escape(
                    t(f"{col} is not a data field, can't rename", f"{col} 不是数据字段, 不能重命名")
                ),
                severity="error",
            )
            return
        if not new or new == self._shown(col):
            return
        taken = {self._shown(c) for c in self.columns if c != col}
        if new in taken or new in derived or new == "#":
            self.notify(
                escape(t(f"{new} already exists, pick another name", f"{new} 已存在, 换个名字")),
                severity="error",
            )
            return
        if new == col:
            self._renames.pop(col, None)
        else:
            self._renames[col] = new
        if self._filter_label:  # 状态栏的条件说明也换成新名
            self._filter_label = self._constraint_label()
        self._rebuild_columns()
        self._refresh_detail(self.query_one("#table", DataTable).cursor_row)
        self._update_status()
        self.notify(escape(t(f"{col} → {new} (q to save)", f"{col} → {new} (q 时保存)")))

    def _rename_summary(self) -> str:
        return ", ".join(f"{k} → {v}" for k, v in self._renames.items())

    def _rename_command(self) -> Optional[str]:
        """等价的 CLI 命令, 给血缘和保存对话框; stdin 模式没有文件, 返回 None。"""
        if not self.filepath or not self._renames:
            return None
        import shlex

        pairs = ",".join(f"{k}:{v}" for k, v in self._renames.items())
        return f"dt clean {shlex.quote(self.filepath)} --rename {shlex.quote(pairs)} -i"

    def _write_back(self) -> bool:
        """把重命名应用到原文件: 流式重写到同目录临时文件再原子替换, 并记血缘。成功返回 True。"""
        import os
        import shutil
        import tempfile

        from ...ops import clean_rows
        from ...streaming import open_stream

        real = os.path.realpath(self.filepath)  # 符号链接: 改真实文件, 不把链接替换成普通文件
        out = Path(real)
        renames = dict(self._renames)
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix="".join(out.suffixes), prefix=".tmp_", dir=out.parent)
            os.close(fd)
            # clean_rows 的 --rename 同款: 目标名已是某行的字段 (列目录只认已加载窗口) 即报错中止
            st = clean_rows(open_stream(real), rename_map=renames)
            n = st.save(tmp, show_progress=False)
            shutil.copymode(real, tmp)  # mkstemp 建的是 0600, 保留原文件权限
            os.replace(tmp, real)
            tmp = None
        except Exception as e:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
            self.notify(escape(t(f"Save failed: {e}", f"保存失败: {e}")), severity="error")
            return False
        try:
            _append_lineage(
                real,
                "view_rename",
                {
                    "renames": renames,
                    "command": self._rename_command(),
                    "source_snapshot": self.source.snapshot_info(),
                },
                n,
            )
        except Exception:
            pass  # 文件已写好; 血缘只是附带记录, 不因它失败而回滚
        self._renames.clear()
        return True

    def action_quit(self) -> None:
        """q: 没有待保存的重命名直接退出; 有则问 写回 / 丢弃 / 取消。"""
        if not self._renames:
            self.exit()
            return
        can_write = self.filepath is not None and not self._follow and self._pipe is None
        if can_write:
            why_not = ""
        elif self._pipe is not None:
            why_not = t(
                "a pipe result can't be written back to the source file; press r first, or w to export",
                "管道结果不能保存回原文件; 先按 r 回到原文件, 或用 w 导出",
            )
        else:
            why_not = t(
                "stdin / follow mode can't save; use w to export with the new names",
                "stdin / follow 模式不能保存回原文件; 用 w 导出即得到新列名",
            )

        def done(choice: Optional[str]) -> None:
            if choice == "discard":
                self.exit()
            elif choice == "write" and self._write_back():
                self.exit()

        self.push_screen(
            SaveScreen(self._rename_summary(), self._rename_command(), can_write, why_not), done
        )

    def _add_columns(self, table: DataTable) -> None:
        """显式给每列宽度, 避免 DataTable 对全表自动测量 (大文件会两阶段闪烁 + 卡顿)。"""
        vis = self._visible_columns()
        self._numeric_cols = self._detect_numeric(vis)
        for name, w in zip(vis, self._column_widths(vis), strict=False):
            table.add_column(self._header_label(name), width=w)

    _NUMBER = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?")

    def _detect_numeric(self, vis: List[str]) -> Set[str]:
        """采样判定数值列 (非空采样值全是数字), 这些列右对齐, 位数一眼可比。"""
        sample = [self._cells(idx, vis) for idx in self.view_indices[:200]]
        out = set()
        for ci, name in enumerate(vis):
            vals = [cells[ci] for cells in sample if cells[ci]]
            if vals and all(self._NUMBER.fullmatch(v) for v in vals):
                out.add(name)
        return out

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
        header_widths = []
        for ci, name in enumerate(vis):
            # +1: 给表头右边的列分隔线留一格, 否则列名恰好占满时会被挤成 "turns│ roles"
            header_w = cell_len(self._header_plain(name)) + 1
            header_widths.append(header_w)
            pad = 1 if self._right_aligned(name) else 0  # 右对齐列末尾留一格, 见 _cell_formatters
            if name == "#":
                # # 列是全局行号, 最大值取当前窗口的真实全局行号 (子集态可能很大), 不靠采样——
                # 否则采样只看前 200 行, 宽度按 3 位数估算, 上万的行号会显示不下被截断。
                labels = [str(n if n < 0 else n + 1) for n in self._global_nos] or ["1"]
                naturals.append(max(header_w, max(map(len, labels)) + pad))
                continue
            w = header_w  # 含 ▾ 标记宽度, 避免标记被截
            for cells in sample:
                w = max(w, cell_len(cells[ci]) + pad)
            naturals.append(min(max(w, 1), CAP))

        # 用户拖过的列: 宽度即用户意图, 既不按自然宽估也不参与后面的压缩
        for i, name in enumerate(vis):
            if name in self._manual_widths:
                naturals[i] = self._manual_widths[name]

        # 预算 = 屏宽 - 表格边框(2) - 竖直滚动条(2) - 每列内边距(2×列数)
        # 漏掉滚动条会让列宽总和正好等于内容区, 竖条再占 2 列 → 触发横向滚动条(溢出一点点)
        avail = self.size.width or 120
        budget = avail - 4 - 2 * len(vis)
        if budget <= 0 or sum(naturals) <= budget:
            return naturals

        # 被压的宽列至少留 MIN_COL_W；列名更长时则保住完整列头。
        # 天然更窄的列不硬撑，仍取其自然宽。
        MIN_COL_W = 8
        widths = [0] * len(vis)
        remaining, nrem = budget, len(vis)
        for i in sorted(range(len(vis)), key=lambda i: naturals[i]):
            share = remaining // nrem
            # 行号必须完整显示；空间不足时允许横向滚动，不截断数字或负号。
            floor = (
                naturals[i]
                if vis[i] == "#" or vis[i] in self._manual_widths
                else min(naturals[i], max(MIN_COL_W, header_widths[i]))
            )
            widths[i] = naturals[i] if naturals[i] <= share else max(share, floor)
            remaining -= widths[i]
            nrem -= 1
        return widths

    def _apply_split(self) -> None:
        """按 self._split 设置两区大小 (竖排改高度, 横排改宽度)。"""
        main = self.query_one("#main", Vertical)
        table = self.query_one("#table", DataTable)
        detail = self.query_one("#detail", VerticalScroll)
        t, d = self._split, 100 - self._split
        if main.has_class("horizontal"):
            table.styles.width, table.styles.height = f"{t}fr", "1fr"
            detail.styles.width, detail.styles.height = f"{d}fr", "1fr"
        else:
            table.styles.height, table.styles.width = f"{t}fr", "1fr"
            detail.styles.height, detail.styles.width = f"{d}fr", "1fr"

    def action_grow_table(self) -> None:
        self._set_split(self._split + 5)

    def action_shrink_table(self) -> None:
        self._set_split(self._split - 5)

    # ------------------------------------------------------------------ #
    # 拖两区分界调大小 (同列宽拖拽: 能看见的边界就该能直接拖)
    # ------------------------------------------------------------------ #
    SPLIT_MIN, SPLIT_MAX = 20, 80  # 表格占比上下限 (%): 两边都至少留得下几行/几列
    SPLIT_DEFAULT = 65

    def _set_split(self, split: int) -> None:
        split = max(self.SPLIT_MIN, min(self.SPLIT_MAX, split))
        if split != self._split:
            self._split = split
            self._apply_split()

    def _on_split_edge(self, x: int, y: int) -> bool:
        """屏幕坐标是否压在两区分界上 —— 且这一格此刻确实归两区所有。

        分界不是一条线而是两格: 表格那圈边框的下(右)缘 + 详情那圈边框的上(左)缘,
        两格都算, 手感与拖列宽的 2 格判定区一致。

        光按坐标判定不够: 分界拖拽挂在 app 上, 而弹窗(选列/值筛选/帮助)里的鼠标事件
        照样冒泡到 app —— 面板正好盖在分界上时, 点面板里的选项会被当成"按住分界",
        app 还会 capture_mouse, 于是随后的 Click 全被吞掉, 那一行选项永远点不中。
        所以先做一次命中测试: 问一句当前这一屏的这一格归谁, 不是两区本身就不算分界
        (弹窗那一屏、模态背景都算不是)。
        """
        if self.query_one("#table", DataTable).has_class("hidden"):
            return False  # 详情放大态只有一个区, 没有分界
        table = self.query_one("#table", DataTable)
        detail = self.query_one("#detail", VerticalScroll)
        t, d = table.region, detail.region
        if self.query_one("#main", Vertical).has_class("horizontal"):
            on_band = t.right - 1 <= x <= d.x and t.y <= y < t.bottom
        else:
            on_band = t.bottom - 1 <= y <= d.y and t.x <= x < t.right
        if not on_band:
            return False
        try:
            hit, _ = self.screen.get_widget_at(x, y)
        except NoWidget:
            return False
        return hit is table or hit is detail

    def _set_split_hint(self, active: bool) -> None:
        if active == self._split_hint:
            return
        self._split_hint = active
        for wid in ("#table", "#detail"):
            self.query_one(wid).set_class(active, "split-hot")
        self._update_status()

    def _drag_split_to(self, x: int, y: int) -> None:
        """把分界拖到鼠标所在处 —— 按格算而不是按 5% 档, 否则拖起来一跳一跳。"""
        main = self.query_one("#main", Vertical)
        region = main.region
        if main.has_class("horizontal"):
            frac = (x - region.x + 1) / max(1, region.width)
        else:
            frac = (y - region.y + 1) / max(1, region.height)
        self._set_split(round(frac * 100))

    def push_screen(self, *args, **kwargs):
        """弹窗压上来之前, 把主屏拖到一半的鼠标状态机就地作废。

        弹窗接管鼠标后主屏再也收不到 MouseUp, 拖拽既不会自己结束也停不下来 ——
        分界会在面板底下被继续拖走; 列宽那边更糟, capture 一直挂着, 面板关掉后
        只要动一下鼠标列宽就跟着跑。弹窗不总是手按出来的 (值扫描完自动弹), 拖到
        一半被打断是真会发生的。顺带熄掉"分界可拖"的边框高亮: 它只由鼠标移动
        开关, 弹窗之后不会再有 MouseMove 来关它。
        """
        if self._split_drag:
            self._split_drag = False
            self.screen.release_mouse()
        self.query_one("#table", FastDataTable).cancel_drag()
        self._set_split_hint(False)
        return super().push_screen(*args, **kwargs)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if not self._on_split_edge(event.screen_x, event.screen_y):
            return
        self._split_drag = True
        # 边框属于详情容器 (allow_select), 不清掉选择状态会顺手拖出一片选区, 松手还自动复制
        self.screen.clear_selection()
        self.screen.capture_mouse()  # 拖到两区之外也继续收事件
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._split_drag:
            self._set_split_hint(self._on_split_edge(event.screen_x, event.screen_y))
            return
        self._drag_split_to(event.screen_x, event.screen_y)
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._split_drag:
            return
        self._split_drag = False
        self.screen.release_mouse()
        self._set_split_hint(self._on_split_edge(event.screen_x, event.screen_y))
        event.stop()

    # ------------------------------------------------------------------ #
    # 表格填充 / 详情刷新
    # ------------------------------------------------------------------ #
    def _cell_formatters(self, vis: List[str]) -> List[Callable[[str], RenderableType]]:
        """每列一个 单元格字符串 → renderable 的函数, 交给 FastDataTable 在渲染可见行时套用。

        一律包成 Text 绕过 DataTable 的 markup 解析 (数据含 [/xxx] 会 MarkupError); 列宽装不下
        以 … 收尾; 行号列暗色、数值列右对齐、roles 按角色着色; 有搜索时命中处画上黄底 ——
        只画数据列: 行号、轮数/字数、roles 签名这些是算出来的, 搜数字时画上去全是假命中。
        """
        derived = render.derived_columns(self.fmt)
        # 算出来的列: 按当前格式判断 (generic 里叫 chars 的就是数据列, 照画命中)
        computed = {"#"} | (derived & (render.NUMERIC_DERIVED | {"roles", "has_input"}))
        return [self._cell_formatter(name, name in derived, name in computed) for name in vis]

    def _cell_formatter(
        self, name: str, is_derived: bool, is_computed: bool
    ) -> Callable[[str], RenderableType]:
        hl = None if is_computed else self._search_re
        if name == "roles" and is_derived:
            return render.roles_text
        if not self._right_aligned(name):
            return lambda s: render._hl(Text(s, no_wrap=True, overflow="ellipsis"), hl)
        style = "dim" if name == "#" else ""

        def right(s: str) -> Padding:
            # 右侧留一格: 贴着列边的数字会和表头的列分隔线 │ 粘成一团。不能用尾随空格 ——
            # rich 右对齐时先 rstrip, 空格会被吃掉
            text = Text(s, style=style, no_wrap=True, overflow="ellipsis", justify="right")
            return _pad_right(render._hl(text, hl))

        return right

    def _populate(self) -> None:
        table = self.query_one("#table", DataTable)
        scroll_x = table.scroll_x  # clear() 顺手把横向滚动清零, 重填完要放回去
        table.clear()
        self._row_keys = []
        vis = self._visible_columns()
        table.cell_formatters = self._cell_formatters(vis)
        for idx in self.view_indices:
            key = f"r{self._row_key_seq}"
            self._row_key_seq += 1
            self._row_keys.append(key)
            table.add_row(*self._cells(idx, vis), key=key)
        if self.view_indices:
            self._refresh_detail(0)
        else:  # 空视图 (0 命中): 清详情, 免残留上个样本
            try:
                detail = self.query_one("#detail", VerticalScroll)
                detail.remove_children()
                detail.border_title = None
            except NoMatches:
                pass
            self._fields = []
            self._field_widgets = []
            self._field_texts = []
            self._cur_anchors = {}
            self._mount_gen += 1
        self._update_status()  # 放在清详情之后: 边框副标题的当前字段要读到清空后的状态
        self._restore_scroll_x(table, scroll_x)

    def _field_names(self) -> List[str]:
        return [name for name, _ in self._fields]

    def _recompute_anchors(self) -> int:
        """从真实布局高度累加每字段起始行 (widget.outer_size, 无测量误差)。返回总高度。"""
        anchors: Dict[str, int] = {}
        y = 0
        for w in self._field_widgets:
            anchors[w._field_name] = y
            y += w.outer_size.height  # size 只是内容区, outer_size 才含顶边分隔线
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
        if not detail.is_attached:
            return  # 帧后回调落在退出过程中: DOM 还在但已卸载, mount 会抛 MountError
        idx = self.view_indices[cursor_row]
        detail.border_title = self._detail_title(idx)
        prev_field = self._current_field()  # 切样本前当前字段, 新样本对齐同名字段
        # 整个切样本+定位期间抑制 scroll 反查, 避免 mount/布局微调把当前字段冲成顶部字段
        self._nav_lock = True
        detail.remove_children()
        # split_turns: 对话拆成 msg0/msg1…, n/N 因此变成逐条消息导航 (长对话里整段"对话"
        # 作为一个字段等于没有粒度); highlight 让搜索命中在正文里直接可见。
        sections = render.render_detail_sections(
            self._apply_renames(self.all_rows[idx]),
            self.fmt,
            hidden={self._shown(c) for c in self._hidden},
            split_turns=True,
            highlight=self._search_re,
            # 代码/JSON 块底色随主题取, 比详情底 ($background) 亮一档, 与正文分开
            code_bg=self.get_css_variables()["surface-lighten-1"],
        )
        self._fields = [(name, rend) for name, rend, _ in sections]
        self._field_texts = [plain for _, _, plain in sections]
        self._field_widgets = []
        # 分批挂载: Textual 布局要给每个字段折行求高, 耗时与样本总长成正比 (几百条消息的
        # agent 轨迹要一秒)。首批只挂够填满两屏的字段, 余下在帧后逐批追加 (_mount_more),
        # 期间照常响应按键; 跳到还没挂的字段时由 _scroll_to_field_i 当场补挂。
        self._mount_gen += 1
        self._mount_upto(self._batch_end(0, self._first_batch_chars()))
        # 布局完成后 (widget.size 才确定): 算真实锚点 → 定位到绑定字段 → 刷新状态栏
        self._detail_gen += 1
        self.call_after_refresh(self._after_detail_render, prev_field, self._detail_gen)

    def _detail_title(self, idx: int) -> Text:
        """详情边框标题: 行号 (与表格 # 列同一口径), 对话再加轮数与字数。"""
        (no,) = self._cells(idx, ["#"])
        derived = render.derived_values(self.all_rows[idx], self.fmt)
        if "turns" not in derived:
            return Text(f"#{no}")
        turns, chars = derived["turns"], derived["chars"]
        return Text(
            t(f"#{no} · {turns} turns · {chars:,} chars", f"#{no} · {turns} 轮 · {chars:,} 字")
        )

    def _first_batch_chars(self) -> int:
        """首批字符预算: 约两屏 (按终端尺寸粗估, 足够盖住详情视口)。"""
        return max(4000, self.size.width * self.size.height * 2)

    _MORE_BATCH_CHARS = 20000  # 后续每批字符预算: 布局约几十毫秒, 批间让出给按键

    def _batch_end(self, start: int, budget: int) -> int:
        """从 start 起按纯文本长度累加到 budget, 返回批次终点 (至少含一个字段)。"""
        end, used = start, 0
        while end < len(self._fields) and (end == start or used < budget):
            used += len(self._field_texts[end])
            end += 1
        return end

    def _mount_upto(self, n: int) -> bool:
        """挂上前 n 个字段 (已挂的跳过)。返回是否新挂了 widget。"""
        start = len(self._field_widgets)
        if n <= start:
            return False
        new = [_FieldStatic(rend, name) for name, rend in self._fields[start:n]]
        self._field_widgets.extend(new)
        self.query_one("#detail", VerticalScroll).mount(*new)
        return True

    def _mount_more(self, gen: int) -> None:
        """帧后追加下一批字段, 布局完成后再接着挂, 直到挂完或样本已换。"""
        if gen != self._mount_gen or not self.is_running:
            return
        try:
            detail = self.query_one("#detail", VerticalScroll)
        except NoMatches:
            return
        if not detail.is_attached:
            return
        start = len(self._field_widgets)
        if start >= len(self._fields):
            return
        self._mount_upto(self._batch_end(start, self._MORE_BATCH_CHARS))
        self.call_after_refresh(self._after_mount_more, gen)

    def _after_mount_more(self, gen: int) -> None:
        if gen != self._mount_gen or not self.is_running:
            return
        if self._field_widgets and self._field_widgets[-1].size.height == 0:
            self.call_after_refresh(self._after_mount_more, gen)  # 布局还没轮到, 再等一帧
            return
        self._recompute_anchors()
        self._mount_more(gen)

    def _refresh_detail_latest(self, gen: int) -> None:
        if gen != self._highlight_gen:
            return
        try:
            row = self.query_one("#table", DataTable).cursor_row
        except NoMatches:
            return  # 帧后回调可能落在 teardown 之后
        self._refresh_detail(row)

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
        self.call_after_refresh(self._mount_more, self._mount_gen)

    def _scroll_to_field_i(self, tries: int = 3) -> None:
        """把当前字段 widget 顶部对齐视口顶 (底部字段自动 clamp 可见)。

        目标字段还没挂 (分批挂载) 就当场挂到它为止, 等它布局出高度再滚 —— 没布局的
        widget 区域为空, 这时滚过去会落到顶部。
        """
        target = self._field_i
        if not 0 <= target < len(self._fields):
            return  # 等布局期间样本已换 (字段变少)
        if self._mount_upto(target + 1) or (
            tries > 0 and self._field_widgets[target].size.height == 0
        ):
            self._nav_lock = True
            self.call_after_refresh(self._scroll_to_field_i, tries - 1)
            return
        self._recompute_anchors()
        detail = self.query_one("#detail", VerticalScroll)
        detail.scroll_to_widget(self._field_widgets[target], top=True, animate=False)
        self.call_after_refresh(self._unlock_nav)

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
            self.notify(
                t("Search with / first, then * jumps to hits", "先用 / 搜索, 再用 * 跳命中")
            )
            return
        n = len(self._field_texts)
        for step in range(1, n + 1):  # 从当前字段之后找起, 绕一圈回到自己
            i = (self._field_i + step) % n
            if self._search_re.search(self._field_texts[i]):
                self._goto_field(i)
                return
        self.notify(t("No hits in this sample's detail", "本样本详情内无命中"))

    def _goto_field(self, i: int) -> None:
        """精确跳到第 i 个字段 (绕过滚动条像素限制, 底部字段 clamp 但可见)。

        推进 _detail_gen: 用户显式导航后, 上一次渲染排队中的"对齐回原字段"作废。
        """
        if not self._fields:
            return
        self._detail_gen += 1
        self._field_i = max(0, min(i, len(self._fields) - 1))
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
        self._sync_titles()
        total = self.source.total
        win = len(self.all_rows)
        seq_total = self._seq_total()
        # 文件名/格式/光标位置/当前字段在两区边框上 (_sync_titles), 状态栏只放会变的状态
        parts: List[str] = []
        if self._scan_msg:  # 扫描进行中: 只显进度, 醒目
            status.update(Text.from_markup(f"[reverse] {escape(self._scan_msg)} [/reverse]"))
            self.query_one("#hint", Static).update(Text())
            return
        # 压在可拖的线上时, 那条更贴当下的提示排最前, 右侧常驻提示让位
        contextual = self._edge_hint or self._split_hint
        if self._edge_hint:  # 光是高亮那条线还不够, 直说一句它能拖
            hint = t(
                "[reverse] drag to resize column · double-click to auto-fit [/reverse]",
                "[reverse] 拖动调列宽 · 双击恢复自适应 [/reverse]",
            )
        elif self._split_hint:
            hint = t(
                "[reverse] drag to resize panes · double-click to reset · z flips layout"
                " [/reverse]",
                "[reverse] 拖动调两区大小 · 双击恢复默认 · z 换上下/左右 [/reverse]",
            )
        else:
            hint = t("[dim]z layout · ? help[/dim]", "[dim]z 布局 · ? 帮助[/dim]")
        if self._renames:
            n = len(self._renames)
            parts.append(
                t(
                    f"[yellow]renamed ×{n} · q to save[/yellow]",
                    f"[yellow]已改名 ×{n} · q 时保存[/yellow]",
                ),
            )
        if self._follow:
            if self._follow_missing:
                parts.append(
                    t(
                        "[yellow]path missing, waiting for the rotated file[/yellow]",
                        "[yellow]路径暂时不存在，等待轮转新文件[/yellow]",
                    )
                )
            elif self._follow_sort_snapshot:
                parts.append(
                    t(
                        "[yellow]sorted snapshot (r resets to live)[/yellow]",
                        "[yellow]排序快照（r 重置后回到实时）[/yellow]",
                    )
                )
            elif self._follow_pinned:
                parts.append(t("[green]following live[/green]", "[green]实时追尾[/green]"))
            else:
                pending = (
                    t(f" · +{self._follow_pending} new", f" · +{self._follow_pending} 新行")
                    if self._follow_pending
                    else ""
                )
                parts.append(
                    t(
                        f"[yellow]paused{pending} (G for latest)[/yellow]",
                        f"[yellow]已暂停界面{pending}（G 回到最新）[/yellow]",
                    )
                )
            if self._follow_partial:
                parts.append(t("[dim]last line being written[/dim]", "[dim]尾行写入中[/dim]"))
        if self.source.has_unindexed_history:
            parts.append(
                t(f"tail window {win} rows (history not indexed)", f"尾窗 {win} 行（历史未索引）")
            )
        elif self.source.has_unindexed_tail and not self.source.total_known:
            parts.append(
                t(
                    f"window [{self.win_offset + 1}–{self.win_offset + win}] / total unknown",
                    f"窗口 [{self.win_offset + 1}–{self.win_offset + win}] / 总行数待定",
                )
            )
            parts.append(
                t("[dim]]/[ page windows·G to end[/dim]", "[dim]]/[ 按需翻窗口·G 到末尾[/dim]")
            )
        if self._visual_anchor is not None:  # 多选态: 醒目显示选区范围
            cur = self.query_one("#table", DataTable).cursor_row
            lo, hi = sorted((self._visual_anchor, cur))
            parts.append(
                t(
                    f"[reverse] VISUAL {lo + 1}–{hi + 1} ({hi - lo + 1}) y copy Esc cancel"
                    " [/reverse]",
                    f"[reverse] VISUAL {lo + 1}–{hi + 1} ({hi - lo + 1}条) y复制 Esc取消 [/reverse]",
                )
            )
        # 子集态但无筛选约束 = 纯排序: 行集没变, 报"命中 N/N (100%)"是误导
        if self._subset is not None and self._filter_label:
            pct = 100 * len(self._subset) / total if total else 0
            parts.append(
                t(
                    f"[green]{escape(self._filter_label)}: "
                    f"{len(self._subset)}/{total} hits ({pct:.1f}%)[/green]",
                    f"[green]{escape(self._filter_label)}: "
                    f"命中 {len(self._subset)}/{total} ({pct:.1f}%)[/green]",
                )
            )
            parts.append(t("[dim]r clears filters[/dim]", "[dim]r 清筛选[/dim]"))
        if seq_total > win and self.source.total_known:  # 多窗口
            parts.append(
                t(
                    f"window [{self.win_offset + 1}–{self.win_offset + win}]/{seq_total}",
                    f"窗口 [{self.win_offset + 1}–{self.win_offset + win}]/{seq_total}",
                )
            )
            parts.append(t("[dim]]/[ page windows·: jump[/dim]", "[dim]]/[ 翻窗口·: 跳行[/dim]"))
        if self._sort_label:
            parts.append(t(f"sort:{escape(self._sort_label)}", f"排序:{escape(self._sort_label)}"))
        if contextual:
            parts.insert(0, hint)
        status.update(Text.from_markup("  ·  ".join(parts)))
        self.query_one("#hint", Static).update(Text() if contextual else Text.from_markup(hint))

    def _sync_titles(self) -> None:
        """两区边框标题: 表格 左上 文件·格式 / 右下 光标位置; 详情 右下 当前字段。

        这些是"身份"信息, 挂在所属区域的边框上, 状态栏就只剩会变的状态。
        """
        try:
            table = self.query_one("#table", DataTable)
            detail = self.query_one("#detail", VerticalScroll)
        except NoMatches:
            return
        title = f"{self.filename} · {self.fmt}"
        if self._pipe is not None:
            short = self._pipe if len(self._pipe) <= 48 else self._pipe[:47] + "…"
            title = f"{self.filename} | {short} · {self.fmt}"
        table.border_title = Text(title)
        if self.view_indices:
            pos = self.win_offset + table.cursor_row + 1
            total = f"{self._seq_total():,}" if self.source.total_known else "?"
            table.border_subtitle = Text(f"{pos:,} / {total}")
        else:
            table.border_subtitle = None
        field = self._current_field()  # 滚动同步顶部字段, n/N 精确接管
        detail.border_subtitle = Text(field) if field else None

    def _unlock_follow_move(self) -> None:
        self._follow_moving = False

    def _poll_follow(self) -> None:
        """在 worker 中轮询文件，避免大批追加阻塞 Textual 事件循环。"""
        if not self._follow or self._follow_polling or self._scan_cancel is not None:
            return
        self._follow_polling = True

        def worker() -> None:
            try:
                update = self.source.poll()
            except Exception as e:  # noqa: BLE001
                self.call_from_thread(self._on_follow_error, f"{type(e).__name__}: {e}")
                return
            self.call_from_thread(self._on_follow_update, update)

        self.run_worker(worker, thread=True, exclusive=True, group="follow")

    def _on_follow_error(self, message: str) -> None:
        self._follow_polling = False
        self.notify(
            escape(t(f"Follow read failed: {message}", f"追尾读取失败: {message}")),
            severity="error",
            timeout=10,
        )

    def _row_matches_constraints(self, row) -> bool:
        """follow 新行是否落进当前子集。谓词取已落地那版 (轮询与扫描互斥, 二者一致)。"""
        if self._row_ok is None:
            return isinstance(row, dict)
        return self._row_ok(row)

    def _on_follow_update(self, update) -> None:
        self._follow_polling = False
        self._follow_partial = update.pending
        refresh_rotation_subset = False
        if update.kind == "missing":
            self._follow_missing = True
            self._update_status()
            return
        if update.kind == "restored":
            self._follow_missing = False
            self.notify(t("Log path is back", "日志路径已恢复"))
        if update.kind == "rotation":
            self._follow_missing = False
            self._follow_generation = update.generation
            self._subset = None
            self._follow_sort_snapshot = self._sort_spec is not None
            refresh_rotation_subset = self._has_filters() and self._sort_spec is None
            self.notify(
                t(
                    "Log rotated; now following the new file, the old tail will phase out",
                    "检测到日志轮转，已跟随新文件；旧尾窗将逐步淘汰",
                ),
                timeout=8,
            )

        if not update.rows:
            self._update_status()
            if refresh_rotation_subset:
                self._recompute_subset(preserve_window=True)
            return

        pairs = list(zip(update.rows, update.row_numbers, strict=False))
        if self._has_filters():
            pairs = [(row, no) for row, no in pairs if self._row_matches_constraints(row)]

        if (
            self._subset is not None
            and self.source.fully_indexed
            and not self._follow_sort_snapshot
        ):
            self._subset.extend(no for _, no in pairs if no >= 0)

        if not self._follow_pinned or self._follow_sort_snapshot:
            self._follow_pending += update.added
            self._update_status()
            if refresh_rotation_subset:
                self._recompute_subset(preserve_window=True)
            return

        self._append_follow_rows([row for row, _ in pairs], [no for _, no in pairs])
        if refresh_rotation_subset:
            self._recompute_subset(preserve_window=True)

    def _append_follow_rows(self, rows: List[Dict], numbers: List[int]) -> None:
        """把一批新行追加到尾窗；无新列时不重建整张表。"""
        if not rows:
            self._update_status()
            return
        self._follow_moving = True
        format_changed = self._format_auto_empty
        if format_changed:
            detected = render.detect_format(rows)
            self.fmt = detected
            self._format_auto_empty = False
            self.columns = render.build_columns(rows, detected)
            visible = set(render.default_visible_columns(self.columns, detected))
            self._auto_hidden = set(self.columns) - visible

        self.all_rows.extend(rows)
        self._global_nos.extend(numbers)
        overflow = max(0, len(self.all_rows) - self.cap)
        if overflow:
            del self.all_rows[:overflow]
            del self._global_nos[:overflow]
        self.view_indices = list(range(len(self.all_rows)))
        self.win_offset = max(0, self._seq_total() - len(self.all_rows))
        self._follow_pending = 0

        if format_changed or self._merge_columns(rows) or self._row_number_width_changed():
            self._rebuild_columns()
        else:
            table = self.query_one("#table", DataTable)
            for key in self._row_keys[:overflow]:
                table.remove_row(key)
            if overflow:
                del self._row_keys[:overflow]
            vis = self._visible_columns()
            first = len(self.all_rows) - len(rows)
            for idx in range(max(0, first), len(self.all_rows)):
                key = f"r{self._row_key_seq}"
                self._row_key_seq += 1
                self._row_keys.append(key)
                table.add_row(*self._cells(idx, vis), key=key)
            self._update_status()

        self.query_one("#table", DataTable).move_cursor(row=len(self.view_indices) - 1)
        self.call_after_refresh(self._unlock_follow_move)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        # 详情渲染挪到下一帧: 长对话一次渲染几百毫秒, 长按 j 时按键排队, 逐个同步渲染会
        # 让光标卡在后面慢慢追。这里只记代次, 帧后回调发现已被更新的高亮取代就不画。
        self._highlight_gen += 1
        self.call_after_refresh(self._refresh_detail_latest, self._highlight_gen)
        self._sync_titles()  # 光标位置即时跟上, 不等详情
        if (
            self._follow
            and self._follow_pinned
            and not self._follow_moving
            and event.cursor_row < len(self.view_indices) - 1
        ):
            self._follow_pinned = False
            self._update_status()
        if self._visual_anchor is not None:  # 多选态下移动光标, 实时更新选区范围
            self._update_status()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """点列头 → 打开该列的值勾选筛选 (Excel AutoFilter)。

        延后 0.15s: 同一位置的双击是重命名, 第二击到来时取消定时器。小文件的值扫描是瞬间的,
        不延后的话面板已经弹出, 第二击落在面板上, 双击永远到不了表格。
        """
        vis = self._visible_columns()
        if not 0 <= event.column_index < len(vis):
            return
        col = vis[event.column_index]
        if self._header_timer is not None:
            self._header_timer.stop()
        self._header_timer = self.set_timer(0.15, lambda: self._header_click_fire(col))

    def _header_click_fire(self, col: str) -> None:
        self._header_timer = None
        self._start_value_scan(col)

    def on_fast_data_table_header_double_clicked(
        self, msg: FastDataTable.HeaderDoubleClicked
    ) -> None:
        """双击列头文字 → 在列头格上原地改名。"""
        if self._header_timer is not None:
            self._header_timer.stop()
            self._header_timer = None
        if self._scan_cancel is not None and self._scan_gen == self._value_scan_gen:
            # 第一击起的值扫描 (大文件时还在跑) 作废, 否则它算完会把值面板压到编辑框上
            self._scan_cancel.set()
            self._scan_gen += 1
            self._end_scan()
            self._update_status()
        vis = self._visible_columns()
        if 0 <= msg.index < len(vis):
            self._begin_rename(vis[msg.index])

    def _begin_rename(self, col: str) -> None:
        if self._pipe_blocks_rename():
            return
        if col == "#" or col in render.derived_columns(self.fmt):
            self.notify(
                escape(
                    t(f"{col} is not a data field, can't rename", f"{col} 不是数据字段, 不能重命名")
                ),
                severity="error",
            )
            return
        table = self.query_one("#table", DataTable)
        try:
            ci = self._visible_columns().index(col)
        except ValueError:
            return
        # 列被右缘截断或藏在冻结的 # 列后面时, 先整列滚进视野, 否则框只剩几格、盖到邻列
        fixed = table._get_fixed_offset()
        region = table._get_column_region(ci)
        before = table.scroll_offset
        table.scroll_to_region(
            Region(region.x, int(table.scroll_y), region.width, 1),
            animate=False,
            spacing=fixed,
            force=True,
            immediate=True,
        )
        if table.scroll_offset == before:
            self._open_header_edit(col)
        else:  # 等这一帧按新滚动位置重绘后再按屏幕坐标开框
            self.call_after_refresh(self._open_header_edit, col)

    def _open_header_edit(self, col: str) -> None:
        cell = self._header_cell(col)
        if cell is None:
            return
        table = self.query_one("#table", DataTable)
        p = table.cell_padding
        if self._right_aligned(col):  # 列头右对齐, 右侧还多留一格 (见 _header_label)
            text_x = cell.right - p - 1 - cell_len(self._header_plain(col))
        else:
            text_x = cell.x + p
        text_x = max(cell.x + p, text_x)

        def done(value: Optional[str]) -> None:
            if value is not None:
                self._rename_column(col, value)

        self.push_screen(
            HeaderEditScreen(
                self._shown(col),
                cell,
                text_x,
                self._right_aligned(col),
                p,
                table.content_region.right,
            ),
            done,
        )

    # ------------------------------------------------------------------ #
    # 动作
    # ------------------------------------------------------------------ #
    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def _table_action(self, name: str, repeat: int = 1) -> None:
        """把 vim 键转调到 DataTable 的光标动作 (仅当详情未放大时)。"""
        table = self.query_one("#table", DataTable)
        if not table.has_class("hidden"):
            action = getattr(table, f"action_{name}")
            for _ in range(repeat):
                action()

    def action_cursor_down(self) -> None:
        self._table_action("cursor_down")

    def action_cursor_up(self) -> None:
        self._table_action("cursor_up")

    def action_scroll_left(self) -> None:
        self._table_action("scroll_left", repeat=4)

    def action_scroll_right(self) -> None:
        self._table_action("scroll_right", repeat=4)

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
        self._supersede_index_navigation()
        if self._follow:
            self._follow_pinned = False
        if self.source.has_unindexed_history:
            self._start_history_index(lambda: self._load_window(0))
            return
        self._load_window(0)

    def action_bottom(self) -> None:
        self._supersede_index_navigation()
        if self._follow and not self._follow_sort_snapshot:
            self._follow_pinned = True
            self._follow_pending = 0
            self._load_follow_latest()
            return
        if self.source.has_unindexed_tail and (
            not self.source.total_known
            or not self.source.window_is_indexed(max(0, self.source.total - self.cap), self.cap)
        ):
            self._start_history_index(self.action_bottom, tail=True)
            return
        end = max(0, self._seq_total() - self.cap)
        self._load_window(end)
        if self.view_indices:
            self.query_one("#table", DataTable).move_cursor(row=len(self.view_indices) - 1)

    def _supersede_index_navigation(self) -> None:
        """新的导航意图取代尚未完成的跳转；不打断搜索/筛选等全量操作。"""
        if self._index_navigation and self._scan_cancel is not None:
            self._scan_cancel.set()
            self._scan_gen += 1
            self._end_scan()

    def _start_history_index(
        self, after: Callable[[], None], count: Optional[int] = None, tail: bool = False
    ) -> None:
        """在 worker 中补全索引；count 指定正向浏览所需的最少行数。"""
        if self.source.fully_indexed:
            after()
            return
        if self._busy():
            return
        cancel, gen = self._begin_scan()
        self._index_navigation = True
        self._set_scan_msg(
            t("Counting rows and reading the tail (Esc cancels)", "统计总行数并读取尾窗 (Esc 取消)")
            if tail
            else t("Indexing rows: 0 (Esc cancels)", "读取行索引 0 行 (Esc 取消)")
        )

        def progress(n: int) -> None:
            def update() -> None:
                if not self._scan_superseded(gen):
                    self._set_scan_msg(
                        t(f"Indexing rows: {n} (Esc cancels)", f"读取行索引 {n} 行 (Esc 取消)")
                    )

            self.call_from_thread(update)

        def worker():
            if tail:
                ok = self.source.ensure_tail(
                    count if count is not None else self.cap, cancel=cancel
                )
            elif count is None:
                ok = self.source.ensure_index(progress_cb=progress, cancel=cancel)
            else:
                ok = self.source.ensure_window(
                    max(0, count - self.cap), self.cap, progress_cb=progress, cancel=cancel
                )
            return self._on_history_index_done, (ok, gen, after)

        self._run_scan(worker, gen)

    def _on_history_index_done(self, ok: bool, gen: int, after: Callable[[], None]) -> None:
        if self._scan_superseded(gen):
            return
        self._end_scan()
        if not ok:
            self.notify(t("Row indexing cancelled", "已取消行索引"))
            self._update_status()
            return
        after()
        self._update_status()

    def _load_follow_latest(self) -> None:
        if self._subset is not None and self.source.fully_indexed:
            self._load_window(max(0, len(self._subset) - self.cap))
        else:
            start = max(0, self.source.total - self.cap)
            rows = self.source.window(start, self.cap)
            nos = self.source.row_numbers(start, len(rows))
            if self._has_filters():
                pairs = [
                    (row, no)
                    for row, no in zip(rows, nos, strict=False)
                    if self._row_matches_constraints(row)
                ]
                rows = [row for row, _ in pairs]
                nos = [no for _, no in pairs]
            self.win_offset = start
            self.all_rows = rows
            self._global_nos = nos
            self.view_indices = list(range(len(rows)))
            if self._merge_columns(rows) or self._row_number_width_changed():
                self._rebuild_columns()
            else:
                self._populate()
        if self.view_indices:
            self._follow_moving = True
            self.query_one("#table", DataTable).move_cursor(row=len(self.view_indices) - 1)
            self.call_after_refresh(self._unlock_follow_move)
        self._update_status()

    def _rebase_tail_after_index(self) -> None:
        """懒索引完成后，把尾窗的相对行号切换为绝对行号。"""
        if (
            self._start_at_end
            and self.source.fully_indexed
            and self._subset is None
            and any(no < 0 for no in self._global_nos)
        ):
            self._load_window(max(0, self.source.total - self.cap))
            if self.view_indices:
                self.query_one("#table", DataTable).move_cursor(row=len(self.view_indices) - 1)

    def action_sort(self) -> None:
        self._open_prompt(
            "sort",
            t(
                "Sort by column (prefix - to reverse, e.g. -chars; scans the whole file):",
                "全量排序列名 (加 - 反向, 如 -chars; 扫全文件):",
            ),
        )

    def _set_sort_spec(self, text: str) -> bool:
        """校验并记下排序列; 列名非法返回 False。"""
        desc = text.startswith("-")
        name = self._original(text.lstrip("-").strip())
        if name not in self.columns:
            self.notify(
                escape(
                    t(
                        f"No such column: {name} (available: {self._shown_columns()})",
                        f"无此列: {name} (可选: {self._shown_columns()})",
                    )
                ),
                severity="error",
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
            if self._follow:
                self._follow_pinned = False
                self._follow_sort_snapshot = True
            self._recompute_subset(snap)

    def action_reset(self) -> None:
        """清除所有约束 (搜索/where/列值/排序), 回到文件开头的原始顺序浏览。

        r 在扫描进行中也必须有效 —— 它正是"我不想等了"的出口。所以这里不 _busy() 拦,
        而是叫停 worker 并推进代次, 让那次扫描的结果作废 (否则迟到的结果会把刚清掉的
        筛选原样复活)。
        """
        was_filtered = self._subset is not None
        was_piped = self._pipe is not None
        if self._scan_cancel is not None:
            self._scan_cancel.set()  # 通知 worker 收摊
        self._scan_gen += 1  # 它的结果就此作废
        self._end_scan()
        if was_piped:  # 管道态的 r = 回到原文件 (约束一并清空)
            self._replace_source(self._origin_source, None, self._origin_fmt)
            self.notify(t("Reset (left the pipe)", "已重置 (退出管道)"))
            return
        self._clear_constraints()
        if self._follow:
            self._follow_pinned = True
            self._follow_pending = 0
            self._load_follow_latest()
            self._rebuild_columns()  # 清列头 ▾ 标记 + 清单元格高亮
        else:
            self._load_window(0, rebuild_columns=True)
        table = self.query_one("#table", DataTable)
        table.scroll_x = table.scroll_target_x = 0  # r 是"回到起点", 横向也一并回最左
        self.notify(
            t("Reset", "已重置")
            + (t(" (left the filtered subset)", " (退出筛选子集)") if was_filtered else "")
        )

    # ------------------------------------------------------------------ #
    # 复制到剪贴板 (Ctrl+c 鼠标选区; y 当前样本; v 多选后 y 复制多条)
    # ------------------------------------------------------------------ #
    def _copy_clipboard(self, text: str) -> Optional[str]:
        """写系统剪贴板, 两条通道都发: OSC52 (本机/SSH 都行, 终端需支持, tmux/screen 自动
        passthrough) + 本地工具 (wl-copy/xclip/xsel, 覆盖吞掉 OSC52 的终端)。

        返回本地通道用了哪个工具, 没有则 None (只靠 OSC52)。
        """
        driver = getattr(self, "_driver", None)
        if driver is not None:
            driver.write(clipboard.osc52(text))
        return clipboard.copy_external(text)

    def copy_to_clipboard(self, text: str) -> None:
        """覆盖 textual 的实现 (它只发裸 OSC52, tmux 下被吞), 统一走上面那条双通道。"""
        self._clipboard = text
        self._copy_clipboard(text)

    def action_copy_selection(self) -> None:
        """Ctrl+c: 把鼠标选中的文本复制走。

        选中不自动复制 —— 拖选也是"看"的手段 (对照两处字段、量一段长度都会顺手拖),
        自动复制会把剪贴板搅成拖动记录。

        没有屏幕选区时分两种去处:
        - 焦点在输入框且框里有选中 (搜索词、筛选表达式) —— 抛 SkipAction 交回 Input 自己的
          复制。SkipAction 对同一 node 上被顶掉的绑定无效, 但 Input 是另一个 node, 接得住。
        - 否则自己答复一句: ctrl+c 在 app 上只存得下一条绑定, 我们这条顶掉了 textual 自带的
          help_quit ("按 q 退出"的提示), 静默会让反射性按 ctrl+c 想退出的人以为卡死。
        """
        text = self.screen.get_selected_text()
        if not text:
            focused = self.focused
            if isinstance(focused, Input) and focused.selected_text:
                raise SkipAction()
            self.notify(
                t(
                    "Nothing selected: drag over text in detail, then Ctrl+c to copy · q quits",
                    "没有选中内容: 详情区拖选文本后再按 Ctrl+c 复制 · 退出按 q",
                )
            )
            return
        used = self._copy_clipboard(text)
        self.screen.clear_selection()
        self.notify(
            t(
                f"Copied {len(text)} selected chars ({used or 'OSC52'})",
                f"已复制选中的 {len(text)} 字符 ({used or 'OSC52'})",
            )
        )

    def on_click(self, event: events.Click) -> None:
        """双击两区分界: 回默认比例 (同双击列分隔线恢复自适应)。"""
        if event.chain >= 2 and self._on_split_edge(event.screen_x, event.screen_y):
            self._set_split(self.SPLIT_DEFAULT)
            event.stop()

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
        self.notify(
            t(
                f"Copied {len(lines)} sample(s) to the clipboard",
                f"已复制 {len(lines)} 条样本到剪贴板",
            )
        )

    # ------------------------------------------------------------------ #
    # 图片弹窗 (i 键 / 点 imgs 单元格 / 点详情 🖼 行)
    # ------------------------------------------------------------------ #
    def action_images(self) -> None:
        self.open_images(self.query_one("#table", DataTable).cursor_row)

    def open_detail_image(self, field: str, k: int) -> None:
        """详情里点了字段 field (msgN) 的第 k 个 🖼 行: 从那张图开始看。"""
        self.open_images(self.query_one("#table", DataTable).cursor_row, field, k)

    def open_images(self, cursor_row: int, field: Optional[str] = None, k: int = 0) -> None:
        """打开 cursor_row 处样本的图片弹窗; 全样本的图按消息顺序排, 可 ←/→ 翻。"""
        if not 0 <= cursor_row < len(self.view_indices):
            return
        row = self._apply_renames(self.all_rows[self.view_indices[cursor_row]])
        items: List[Tuple[str, str]] = []
        start = 0
        for i, turn in enumerate(_normalize_turns(row)):
            if f"msg{i}" == field:
                start = len(items) + k
            items.extend((f"msg{i} {turn.role}", ref) for ref in turn.images)
        if not items:
            self.notify(t("No images in this sample", "这条样本没有图片"))
            return
        self.push_screen(ImageScreen(items, min(start, len(items) - 1), self._image_root))

    def on_fast_data_table_cell_clicked(self, msg: FastDataTable.CellClicked) -> None:
        vis = self._visible_columns()
        if 0 <= msg.column < len(vis) and vis[msg.column] == "imgs":
            self.open_images(msg.row)

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
    # 值不能安全塞进 where 表达式的情形: 含 … (表格预览截断过, 原值已不可知)。
    # 其余 (引号/运算符/空值) 都由 repr 与 _value_filter_expr 妥善表达。
    _UNSAFE_VALUE = re.compile("…")

    def _value_filter_expr(self, col: str, kept: set) -> str:
        """列值勾选 → 等价的 where 表达式 (值筛选比的是表格单元格字符串, 翻译要按列的类型)。

        派生列翻译成 render.DERIVED_EXPR 里的取值表达式 (对话列即行函数 turns(x)…),
        于是这条 where 同时能喂给 dt view 与 dt filter。
        """
        vals = sorted(kept)
        if col in render.derived_columns(self.fmt):
            get = render.DERIVED_EXPR[col]
            if col in render.NUMERIC_DERIVED:
                return f"{get} in ({', '.join(vals)},)"
            if col == "has_input":
                want = {v == "✓" for v in vals}
                return get if want == {True} else f"not {get}" if want == {False} else "True"
            return f"{get} in ({', '.join(map(repr, vals))},)"
        parts = []
        nonempty = [v for v in vals if v != ""]
        if nonempty:
            parts.append(f"str(x.get({col!r})) in ({', '.join(map(repr, nonempty))},)")
        if "" in vals:
            parts.append(f"x.get({col!r}) in (None, '')")
        return " or ".join(parts)

    def _stdin_unreproducible(self) -> List[str]:
        return [
            t(
                "Piped input (dt view -) can't be reproduced; export the result with w",
                "管道输入 (dt view -) 无法复现, 请用 w 导出结果文件",
            )
        ]

    def _collect_wheres(self) -> Tuple[List[str], List[str]]:
        """(全部 where 条件 = 手输的 + 列值勾选翻译出的, 无法表达的说明)。"""
        skipped: List[str] = []
        wheres = list(self._wheres)
        for col, kept in self._col_value_filters.items():
            bad = [v for v in kept if self._UNSAFE_VALUE.search(v)]
            if bad:
                skipped.append(
                    t(
                        f"{len(bad)} value(s) of {self._shown(col)} are truncated"
                        " and can't go into a command",
                        f"{self._shown(col)} 的 {len(bad)} 个值含特殊字符/被截断, 无法写进命令",
                    )
                )
                continue
            # 多列值筛选之间是 AND, 各写一条 --where; 单列内多值是 in (...)
            wheres.append(self._value_filter_expr(col, kept))
        return wheres, skipped

    def _rename_pairs(self) -> str:
        import shlex

        return shlex.quote(",".join(f"{k}:{v}" for k, v in self._renames.items()))

    def _view_pipe(self) -> Optional[str]:
        """C 里的 --pipe: 管道当初喂的是改过名的行, 复现时前面接上同样的改名。"""
        if self._pipe is None or not self._renames:
            return self._pipe
        return f"dt clean - --rename {self._rename_pairs()} | {self._pipe}"

    def _shell_pipe(self) -> Optional[str]:
        """P/血缘里对源文件重跑管道的 shell 命令 (含改名段)。"""
        if self._pipe is None or not self.filepath:
            return None
        if not self._renames:
            return shell_form(self._pipe, self.filepath)
        import shlex

        head = f"dt clean {shlex.quote(self.filepath)} --rename {self._rename_pairs()}"
        return f"{head} | {self._pipe}"

    def _build_command(self) -> Tuple[Optional[str], List[str]]:
        """(可复现当前视图的 dt view 命令, 无法表达的部分说明)。"""
        import shlex

        if not self.filepath:  # stdin 模式: 源数据是管道, 没有可复现的输入
            return None, self._stdin_unreproducible()

        wheres, skipped = self._collect_wheres()
        if self._follow:
            skipped.insert(
                0,
                t(
                    "follow mode reproduces the conditions, not a fixed byte snapshot",
                    "实时模式只复现观察条件，不固定历史字节快照",
                ),
            )

        parts = ["dt", "view", shlex.quote(self.filepath)]
        if self._start_at_end:
            parts.append(str(-self.cap))
        if self._follow:
            parts.append("--follow")
        if self._pipe is not None:
            parts.append(f"--pipe={shlex.quote(self._view_pipe())}")
        elif self._renames:
            skipped.append(
                t(
                    "column renames (dt view has no option for them; P includes them)",
                    "列改名 (dt view 没有对应选项; P 的处理链里有)",
                )
            )
        for w in wheres:
            parts.append(f"--where={shlex.quote(w)}")
        if self._search_text:
            parts.append(f"--search={shlex.quote(self._search_text)}")
        if self._sort_spec:
            name, desc = self._sort_spec
            parts.append(f"--sort={shlex.quote(('-' if desc else '') + name)}")
        return " ".join(parts), skipped

    def _sort_key_expr(self, col: str) -> Optional[str]:
        """排序列名 → dt sort --by 的表达式; ``#`` (行号) 没有对应表达式。"""
        if col == "#":
            return None
        if col in render.derived_columns(self.fmt):
            return render.DERIVED_EXPR[col]
        return f"x.get({col!r})"

    def _build_pipeline_command(self) -> Tuple[Optional[str], List[str]]:
        """(把当前约束写成处理链 ``dt filter … | dt sort …``, 无法表达的部分说明)。

        与 C 的区别: C 复现"看", P 复现"处理" —— 同一套条件喂给 dt filter, 后面接 -o 或
        更多管道就能对这个子集做事。这正是 view 与 CLI 共用一种表达式语言的意义。
        """
        import shlex

        if not self.filepath:
            return None, self._stdin_unreproducible()

        wheres, skipped = self._collect_wheres()
        if self._search_text:
            wheres.append(f"search(x, {self._search_text!r})")
        stages: List[str] = []
        src = shlex.quote(self.filepath)
        if self._pipe is not None:  # 先是管道本身 (对源文件重跑), 再接当前约束
            stages.append(self._shell_pipe())
        if wheres:
            expr = " and ".join(f"({w})" for w in wheres) if len(wheres) > 1 else wheres[0]
            stages.append(f"dt filter {'-' if stages else src} {shlex.quote(expr)}")
        if self._sort_spec:
            name, desc = self._sort_spec
            key = self._sort_key_expr(name)
            if key is None:
                skipped.append(
                    t("sorting by row number # has no expression", "按行号 # 排序没有对应表达式")
                )
            else:
                head = "dt sort - " if stages else f"dt sort {src} "
                stages.append(head + f"--by {shlex.quote(key)}" + (" --desc" if desc else ""))
        if self._pipe is None and self._renames:  # 条件按原名筛完, 末段改名 = 输出与所见一致
            head = "dt clean - " if stages else f"dt clean {src} "
            stages.append(head + f"--rename {self._rename_pairs()}")
        if not stages:
            return None, [
                t("no filter/search/sort to translate", "当前没有筛选/搜索/排序条件可翻译")
            ]
        return " | ".join(stages), skipped

    def _notify_copied(self, cmd: Optional[str], skipped: List[str]) -> None:
        if cmd is None:
            self.notify(escape(skipped[0]), severity="warning")
            return
        self._copy_clipboard(cmd)
        msg = t(f"Copied command: {cmd}", f"已复制命令: {cmd}")
        if skipped:
            msg += (
                t("\nNot included: ", "\n未纳入: ")
                + "; ".join(skipped)
                + t(
                    " (full conditions are in an exported file's lineage)",
                    " (完整条件见导出文件的血缘记录)",
                )
            )
        self.notify(escape(msg), timeout=10, severity="warning" if skipped else "information")

    def action_copy_command(self) -> None:
        self._notify_copied(*self._build_command())

    def action_copy_pipeline(self) -> None:
        self._notify_copied(*self._build_pipeline_command())

    # ------------------------------------------------------------------ #
    # 导出: 把当前浏览序列 (或多选选区) 落盘。剪贴板走 OSC52 有长度上限, 几千条根本装不下,
    # 所以"筛出来的子集"必须能写成文件, 否则 view 里的筛选结果出不去。
    # ------------------------------------------------------------------ #
    def _export_scope(self) -> Tuple[str, int]:
        """(范围: selection|filtered|all, 行数; -1=行数待定): 多选态导出选区, 否则导出当前浏览序列。

        范围是稳定键 (写进血缘记录), 界面文案由 _SCOPE_LABELS 在显示时给出。
        """
        if self._visual_anchor is not None:
            lo, hi = sorted((self._visual_anchor, self.query_one("#table", DataTable).cursor_row))
            return "selection", hi - lo + 1
        if not self.source.total_known:
            return "all", -1
        return ("filtered" if self._filter_label else "all"), self._seq_total()

    def action_export(self) -> None:
        scope, n = self._export_scope()
        if n == 0:
            self.notify(t("No rows to export", "没有可导出的行"))
            return
        if n < 0:
            scope, count = "all_unknown", ""
        else:
            count = t(f" ({n} rows)", f" {n} 行")
        scope = _SCOPE_LABELS[scope]
        self._open_prompt(
            "export",
            t(
                f"Export {scope}{count} to (format by extension, e.g. out.jsonl):",
                f"导出{scope}{count}到 (按扩展名定格式, 如 out.jsonl):",
            ),
        )

    def _apply_export(self, path_str: str) -> None:
        from pathlib import Path

        if self._busy():
            return
        out = Path(path_str).expanduser()
        if out.exists():  # 不静默覆盖: 导出目标多半是新文件, 覆盖了没法撤
            self.notify(
                escape(t(f"Already exists, pick another name: {out}", f"已存在, 换个名字: {out}")),
                severity="error",
            )
            return
        if not out.parent.exists():
            self.notify(
                escape(t(f"No such directory: {out.parent}", f"目录不存在: {out.parent}")),
                severity="error",
            )
            return

        scope, n = self._export_scope()
        if self._visual_anchor is not None:
            lo, hi = sorted((self._visual_anchor, self.query_one("#table", DataTable).cursor_row))
            picked = [self.all_rows[self.view_indices[p]] for p in range(lo, hi + 1)]
            rows_iter: Callable = lambda cancel: iter(picked)  # noqa: E731
        else:
            rows_iter = self._iter_sequence
        streaming = out.suffix.lower() in (".jsonl", ".ndjson")
        if not streaming and (n < 0 or n > 200_000):
            self.notify(
                escape(
                    t(
                        f"{out.suffix} loads everything into memory after indexing",
                        f"{out.suffix} 需在索引后全量载入内存",
                    )
                    + (t(f" ({n} rows)", f" ({n} 行)") if n >= 0 else "")
                    + t("; consider exporting .jsonl", ", 建议导出 .jsonl")
                ),
                severity="warning",
            )

        cancel, gen = self._begin_scan()
        self._set_scan_msg(t("Preparing export (Esc cancels)", "准备导出 (Esc 取消)"))

        def worker():
            # 导出的失败 (磁盘满/权限/格式后端缺失) 有自己的文案, 不并进 _on_scan_crashed
            try:
                if self._visual_anchor is None and not self._prepare_full_scan(cancel):
                    return self._on_export_done, (out, None, None, gen)
                total = self._export_scope()[1]
                self.call_from_thread(
                    self._set_scan_msg,
                    t(f"Exporting 0/{total} (Esc cancels)", f"导出中 0/{total} (Esc 取消)"),
                )
                written = self._write_export(out, rows_iter, cancel, total, streaming)
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
                    f.write(orjson.dumps(self._apply_renames(row)))
                    f.write(b"\n")
                    n += 1
                    if n % 5000 == 0:
                        self.call_from_thread(
                            self._set_scan_msg,
                            t(
                                f"Exporting {n}/{total} (Esc cancels)",
                                f"导出中 {n}/{total} (Esc 取消)",
                            ),
                        )
            if cancel.is_set():
                out.unlink(missing_ok=True)  # 半截文件比没有更坏, 直接删掉
                return None
            return n

        data = []
        for row in rows_iter(cancel):
            if cancel.is_set():
                return None
            data.append(self._apply_renames(row))
            n += 1
            if n % 5000 == 0:
                self.call_from_thread(
                    self._set_scan_msg,
                    t(f"Collecting {n}/{total} (Esc cancels)", f"收集中 {n}/{total} (Esc 取消)"),
                )
        from ...storage.io import save_data

        self.call_from_thread(
            self._set_scan_msg,
            t(f"Writing {out.suffix} ({n} rows)…", f"写入 {out.suffix} ({n} 行)…"),
        )
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
            "where": list(self._wheres),
            "value_filters": {c: sorted(v) for c, v in self._col_value_filters.items()},
            "sort": self._sort_label,
            "scope": self._export_scope()[0],
            "command": cmd,
            "pipeline_command": self._build_pipeline_command()[0],
            "source_snapshot": self._origin_source.snapshot_info(),
        }
        if self._pipe is not None:
            params["pipe"] = self._pipe
            params["pipe_rows"] = self.source.total
            if self.filepath:
                params["pipe_command"] = self._shell_pipe()
        if skipped:
            params["command_incomplete"] = skipped
        if self._renames:
            params["renames"] = dict(self._renames)
        tracker = LineageTracker(self.filepath)
        tracker.record(
            "view_export",
            params=params,
            input_count=self._origin_source.total,
            output_count=written,
        )
        return tracker.save(str(out), written)

    def _on_export_done(self, out, written: Optional[int], error: Optional[str], gen: int) -> None:
        if self._scan_superseded(gen):
            return  # 期间已被 r 重置或新扫描取代
        self._end_scan()
        self._rebase_tail_after_index()
        self._update_status()
        if error is not None:
            self.notify(
                escape(t(f"Export failed: {error}", f"导出失败: {error}")),
                severity="error",
                timeout=10,
            )
            return
        if written is None:
            self.notify(t("Export cancelled", "已取消导出"))
            return
        try:
            lineage_path = self._save_lineage(out, written)
            extra = t(
                f"\nLineage: {lineage_path} (see dt history {out})",
                f"\n血缘: {lineage_path} (dt history {out} 可查)",
            )
        except Exception as e:  # noqa: BLE001  血缘是附加信息, 写不成不该让导出显示为失败
            extra = t(f"\n(lineage not written: {e})", f"\n(血缘未写成: {e})")
        self.notify(
            escape(
                t(f"Exported {written} rows → {out}{extra}", f"已导出 {written} 行 → {out}{extra}")
            ),
            timeout=10,
        )

    # ------------------------------------------------------------------ #
    # |: 在 view 里跑一段 shell 管道, 结果替换浏览数据。输入永远是原文件的全部行
    # (不是当前子集), 每次都从原文件重跑; r 回到原文件。这是 P 的反方向: P 把 view 的
    # 条件交给 CLI, | 把 CLI 的结果拿回 view, 两边都在同一个界面里闭环。
    # ------------------------------------------------------------------ #
    _PIPE_PLACEHOLDER = t(
        "shell pipe over the whole file, NDJSON in/out, e.g. "
        'dt filter - "turns(x)>=6" | dt sort - --by "chars(x)" --desc',
        "对全文件跑 shell 管道 (进出都是 NDJSON), 如 "
        'dt filter - "turns(x)>=6" | dt sort - --by "chars(x)" --desc',
    )

    def action_pipe(self) -> None:
        if self._follow:
            self.notify(
                t("follow mode can't run a pipe", "实时追尾模式不能跑管道"), severity="warning"
            )
            return
        if self._busy():
            return
        self._open_prompt("pipe", self._PIPE_PLACEHOLDER, value=self._pipe or "")

    def _apply_pipe(self, text: str, after: Optional[Callable[[], None]] = None) -> None:
        """对原文件跑 text 这条管道; 完成后 after() (启动参数的 where/search/sort 靠它排在管道后)。"""
        text = text.strip()
        if not text or self._busy():
            return
        cancel, gen = self._begin_scan()
        self._set_scan_msg(t(f"pipe: {text} (Esc cancels)", f"管道: {text} (Esc 取消)"))

        def progress(n: int) -> None:
            self.call_from_thread(
                self._set_scan_msg,
                t(f"pipe: fed {n} rows (Esc cancels)", f"管道: 已喂入 {n} 行 (Esc 取消)"),
            )

        def worker():
            try:
                if not self._prepare_full_scan(cancel, source=self._origin_source):
                    return self._on_pipe_done, (text, None, None, gen)
                rows = self._origin_source.iter_all()
                if self._renames:  # 用户照着看到的列名写管道; 窗口外的冲突行在这里报错
                    renames = dict(self._renames)
                    rows = (_rename_item(r, renames) if isinstance(r, dict) else r for r in rows)
                result = run_pipe(text, rows, cancel, progress)
            except Exception as e:  # noqa: BLE001  如 sh 不存在: 变提示, 不是崩溃
                return self._on_pipe_done, (text, None, f"{type(e).__name__}: {e}", gen)
            return self._on_pipe_done, (text, result, None, gen)

        w = self._run_scan(worker, gen)
        if after is not None:
            # after 会起新的 exclusive worker; 必须等这个 worker 真正结束 (StateChanged),
            # 在它的回调里直接起会把它自己判成被取消
            self._after_worker = (w, after)

    def on_worker_state_changed(self, event) -> None:
        pending = self._after_worker
        if pending is None or event.worker is not pending[0]:
            return
        if event.state in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            self._after_worker = None
            pending[1]()

    def _on_pipe_done(self, text: str, result, error: Optional[str], gen: int) -> None:
        if self._scan_superseded(gen):
            return
        self._end_scan()
        self._update_status()
        if result is None or (error is None and result.rows is None):
            # 取消先于成败: kill 掉的子进程返回码也非 0, 但那不是失败
            self.notify(t("pipe cancelled", "已取消管道"))
            return
        failed = error is not None or result.returncode != 0 or dt_error(result.stderr_tail)
        if failed:
            msg = error if error is not None else error_message(result.stderr_tail)
            self.notify(
                escape(t(f"pipe failed: {msg}", f"管道失败: {msg}")),
                severity="error",
                timeout=10,
            )
            return
        rows = result.rows
        self._replace_source(_MemorySource(rows), text)
        n = len(rows)
        if n == 0:
            msg = t("pipe: 0 rows (r returns to the file)", "管道: 0 行 (r 回到原文件)")
            sev = "warning"
        else:
            msg = t(f"pipe: {n} rows", f"管道: {n} 行")
            sev = "information"
            if n > 200_000:
                msg += t(
                    " (held in memory; consider filter/head before sort)",
                    " (全在内存里; 大结果建议先 filter/head 再 sort)",
                )
                sev = "warning"
        # dt 在 stderr 上的汇总 (如 "N 行求值失败") 值得看一眼: 附在通知里
        summary = "\n".join(ln for ln in result.stderr_tail.strip().splitlines()[-2:] if ln.strip())
        if summary:
            msg += "\n" + summary
        self.notify(escape(msg), severity=sev, timeout=10)

    def _scope_word(self) -> str:
        """扫描范围的说法: 管道态扫的是管道结果, 不是原文件。"""
        if self._pipe is not None:
            return t("pipe result", "管道结果")
        return t("full file", "全量")

    def _clear_constraints(self) -> None:
        """清空全部约束状态 (搜索/where/列值/排序/子集), 不动数据源与窗口。"""
        self._scan_rollback = None
        self._applied_spec = None
        self._row_ok = None
        self._col_value_filters = {}
        self._wheres = []
        self._search_text = None
        self._search_re = None
        self._sort_spec = None
        self._subset = None
        self._filter_label = None
        self._follow_sort_snapshot = False
        self._visual_anchor = None

    def _replace_source(self, source, pipe_text: Optional[str], fmt: Optional[str] = None) -> None:
        """换数据源并整体重建: 约束清空、格式重检、列目录重建、回到第一窗口。

        列的手动宽度按列名保留 (换回原文件时列还在); 隐藏列与自定义列集清掉, 因为它们
        描述的是上一份数据的列目录。
        """
        self.source = source
        self._pipe = pipe_text
        self._clear_constraints()
        window = source.window(0, self.cap)
        self.fmt = fmt or self._format_hint or render.detect_format(window)
        self._format_auto_empty = not window and self.fmt == "generic"
        self.columns = render.build_columns(window, self.fmt)
        default_visible = set(render.default_visible_columns(self.columns, self.fmt))
        self._auto_hidden = set(self.columns) - default_visible
        self._hidden = set()
        self._columns_customized = False
        if not window:  # _load_window 遇空窗口直接返回, 空结果要自己清屏
            self.win_offset = 0
            self.all_rows = []
            self._global_nos = []
            self.view_indices = []
            self._rebuild_columns()
        else:
            self._load_window(0, rebuild_columns=True)
        table = self.query_one("#table", DataTable)
        table.scroll_x = table.scroll_target_x = 0
        self._update_status()

    # ------------------------------------------------------------------ #
    # 大文件窗口翻页 (偏移索引 → 任意位置秒开, 内存 O(窗口))
    # ------------------------------------------------------------------ #
    def _load_window(self, offset: int, rebuild_columns: bool = False) -> None:
        """加载"当前浏览序列"中以位置 offset 为起点的窗口, 重置排序并重填表格。

        原始态: 位置即文件行号, 走 source.window 顺序读。
        子集态: 位置为子集内序号, 取 subset[offset:] 的全局行号经 rows_at 拉取。
        rebuild_columns: 调用方还要清/改列头 (筛选的 ▾ 标记、命中高亮) 时置位 —— 让列头
        与行在同一趟里重建。否则填完一遍表再 _rebuild_columns() 又清空重填, 一万行的窗口
        白白多花一倍时间。
        """
        if self._follow and self._follow_sort_snapshot and self._subset is None:
            # 轮转后旧排序快照的全局索引已经不再指向当前文件；当前可见窗口仍安全，
            # 但不能拿旧索引去读取新 inode。r 会显式回到新文件的实时顺序。
            self.notify(
                t(
                    "Log rotated; the sorted snapshot is limited to this window. r returns to live",
                    "日志已轮转，排序快照只能查看当前窗口；按 r 回到实时",
                ),
                severity="warning",
            )
            return
        if not self.source.window_is_indexed(offset, self.cap):
            self._start_history_index(
                lambda: self._load_window(offset), count=max(0, offset) + self.cap
            )
            return
        seq_total = self._seq_total()
        if self._subset is not None and seq_total == 0:  # 空子集: 清空视图 (0 命中)
            self.win_offset = 0
            self.all_rows = []
            self._global_nos = []
            self.view_indices = []
            self._populate()
            return
        offset = max(0, min(offset, seq_total - 1)) if seq_total else 0
        try:
            if self._subset is None:
                rows = self.source.window(offset, self.cap)
                nos = self.source.row_numbers(offset, len(rows))
            else:
                picked = self._subset[offset : offset + self.cap]
                rows = self.source.rows_at(picked)
                nos = picked
        except OSError as e:
            self.notify(
                escape(
                    t(
                        f"File changed; this snapshot can no longer be read: {e}",
                        f"文件已变化，当前快照无法继续读取: {e}",
                    )
                ),
                severity="error",
                timeout=10,
            )
            return
        if not rows:
            return
        self.win_offset = offset
        self.all_rows = rows
        self._global_nos = nos
        self.view_indices = list(range(len(rows)))
        # _merge_columns 有副作用 (并入新列), 不能被 rebuild_columns 短路掉
        columns_changed = self._merge_columns(rows) or self._row_number_width_changed()
        if rebuild_columns or columns_changed:
            self._rebuild_columns()
        else:
            self._populate()
        self.query_one("#table", DataTable).move_cursor(row=0)

    def action_next_window(self) -> None:
        self._supersede_index_navigation()
        nxt = self.win_offset + len(self.all_rows)
        if self.source.has_unindexed_tail:
            self._start_history_index(lambda: self._show_next_window(nxt), count=nxt + self.cap)
            return
        self._show_next_window(nxt)

    def _show_next_window(self, nxt: int) -> None:
        if nxt >= self._seq_total():
            self.notify(t("Already at the last window", "已是最后一个窗口"))
            return
        self._load_window(nxt)

    def action_prev_window(self) -> None:
        self._supersede_index_navigation()
        if self.win_offset == 0:
            if self.source.has_unindexed_history:
                self._follow_pinned = False

                def load_previous_tail() -> None:
                    self._load_window(max(0, self.source.total - 2 * self.cap))

                self._start_history_index(load_previous_tail)
                return
            self.notify(t("Already at the first window", "已是第一个窗口"))
            return
        if self._follow:
            self._follow_pinned = False
        self._load_window(max(0, self.win_offset - self.cap))

    def action_jump(self) -> None:
        where = (
            t("position in subset", "子集内序号") if self._subset is not None else t("row", "行号")
        )
        if self.source.has_unindexed_history:
            hint = t(
                "negative counts from the tail end; positive builds the history index",
                "负数从尾窗末尾数，正数会按需建历史索引",
            )
        elif self.source.has_unindexed_tail:
            hint = t(
                "positive reads on demand; negative counts rows, then from the end",
                "正数按需读取，负数快速计数后从末尾数",
            )
        else:
            hint = t(
                f"1-{self._seq_total()}, negative counts from the end",
                f"1-{self._seq_total()}, 负数从末尾数",
            )
        self._open_prompt("jump", t(f"Jump to {where} ({hint}):", f"跳到{where} ({hint}):"))

    def _apply_jump(self, text: str) -> None:
        """跳到当前浏览序列的第 n 个位置 (原始态=文件行号, 子集态=子集内序号)。"""
        try:
            n = int(text)
        except ValueError:
            self.notify(
                escape(t(f"Invalid row number: {text}", f"无效行号: {text}")), severity="error"
            )
            return
        self._supersede_index_navigation()
        if self.source.has_unindexed_tail and n < 0:
            self._start_history_index(
                lambda: self._jump_indexed(n), count=max(self.cap, -n), tail=True
            )
            return
        if self.source.has_unindexed_tail and n > self.source.total:
            self._start_history_index(lambda: self._jump_indexed(n), count=n + self.cap - 1)
            return
        if self.source.has_unindexed_history and n > 0:
            self._follow_pinned = False
            self._start_history_index(lambda: self._jump_indexed(n))
            return
        if self.source.has_unindexed_history and n < -self.source.total:
            self._follow_pinned = False
            self._start_history_index(lambda: self._jump_indexed(n))
            return
        self._jump_indexed(n)

    def _jump_indexed(self, n: int) -> None:
        """对已知序列执行跳转；尾窗内负数也可直接走这里。"""
        seq_total = self._seq_total()
        if n < 0:  # 负数从末尾数: -1 = 最后一个
            n = seq_total + n + 1
        g = max(1, min(n, seq_total)) - 1  # 0-based 序列位置
        if self.win_offset <= g < self.win_offset + len(self.all_rows):
            local = g - self.win_offset  # 已在当前窗口: 仅移动光标
            if local in self.view_indices:
                self.query_one("#table", DataTable).move_cursor(row=self.view_indices.index(local))
            else:
                self.notify(
                    t("That row is not in the current filter result", "该行不在当前筛选结果中")
                )
        else:
            self._load_window(g)  # 跳出窗口: 以目标位置为窗口首行加载

    def action_zoom(self) -> None:
        self.query_one("#table", DataTable).add_class("hidden")
        self.query_one("#detail", VerticalScroll).add_class("zoomed").focus()

    def action_unzoom(self) -> None:
        prompt = self.query_one("#prompt", Input)
        if prompt.has_class("active"):  # Esc 先关掉正在输入的提示框
            prompt.remove_class("active")
            self._prompt_mode = None
            self.query_one("#table", DataTable).focus()
            return
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
            self._hidden = set(self.columns) - visible
            self._auto_hidden.clear()
            self._columns_customized = True
            self._rebuild_columns()

        checked = set(self._visible_columns()) if self._columns_customized else {"#"}
        labels = {c: self._shown(c) for c in self.columns}
        self.push_screen(ColumnPicker(self.columns, checked, labels), apply)

    def _row_number_width_changed(self) -> bool:
        """窗口行号位数增加时扩列，避免沿用首屏宽度截断绝对行号。"""
        if not self._global_nos:
            return False
        vis = self._visible_columns()
        if "#" not in vis or "#" in self._manual_widths:
            return False
        width = max(
            len(str(n if n < 0 else n + 1)) for n in (min(self._global_nos), max(self._global_nos))
        )
        return self.query_one("#table", DataTable).ordered_columns[vis.index("#")].width < width

    def on_fast_data_table_edge_hover(self, msg: FastDataTable.EdgeHover) -> None:
        self._edge_hint = msg.active
        self._update_status()

    def on_fast_data_table_column_resized(self, msg: FastDataTable.ColumnResized) -> None:
        """记住拖出来的列宽 (width=None 为双击分隔线, 该列恢复自适应并重排全表)。"""
        vis = self._visible_columns()
        if not 0 <= msg.index < len(vis):
            return
        name = vis[msg.index]
        if msg.width is not None:
            self._manual_widths[name] = msg.width
            return
        self._manual_widths.pop(name, None)
        # 让出去的空间要还给别的列, 所以整表重算一遍宽度 (不重填行, 帧内就能改完)
        table = self.query_one("#table", FastDataTable)
        for i, w in enumerate(self._column_widths(vis)):
            table.set_column_width(i, w)
        self.notify(t(f"{name}: width back to auto-fit", f"{name} 列宽已恢复自适应"))

    def _rebuild_columns(self) -> None:
        """列可见集变化后重建表头并重填。"""
        table = self.query_one("#table", DataTable)
        scroll_x = table.scroll_x
        table.clear(columns=True)
        self._add_columns(table)
        self._populate()
        self._restore_scroll_x(table, scroll_x)

    def _restore_scroll_x(self, table: DataTable, scroll_x: float) -> None:
        """把横向滚动放回原处。

        筛选/翻窗口都要重填表格, 而 DataTable.clear() 会把 scroll_x 清零 —— 右边那几列
        看得好好的, 一应用筛选就被弹回最左, 还得重新滚过去。列变窄/变少时由 scroll_x 的
        validate 夹到新的 max_scroll_x, 不会滚出界。
        """
        if not scroll_x:
            return
        table.scroll_x = scroll_x
        table.scroll_target_x = table.scroll_x

    def action_search(self) -> None:
        self._open_prompt(
            "search",
            t(
                "Search all records (whole record, case-insensitive; re: prefix for regex):",
                "全量搜索 (整条记录, 不分大小写; re: 前缀走正则):",
            ),
        )

    def action_filter(self) -> None:
        self._open_prompt(
            "filter",
            t(
                "Filter (Python, row is x; same as dt filter) "
                "e.g. turns(x)>=6 and 'refund' in first_user(x) · x.source=='a':",
                "全量筛选 (Python 表达式, 当前行 x; 与 dt filter 同一套) "
                "如 turns(x)>=6 and '退款' in first_user(x) · x.source=='a':",
            ),
        )

    def action_value_filter(self) -> None:
        self._open_prompt(
            "value_filter",
            t(
                "Filter by column values: enter a column name (or click its header):",
                "按列值勾选筛选: 输入列名 (亦可直接点表头):",
            ),
        )

    def _open_prompt(self, mode: str, placeholder: str, value: str = "") -> None:
        self._prompt_mode = mode
        prompt = self.query_one("#prompt", Input)
        prompt.placeholder = placeholder
        prompt.value = value
        prompt.add_class("active")
        prompt.focus()
        if value:
            prompt.action_end()  # 预填时光标放末尾, 直接接着改

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
            self._start_value_scan(self._original(text))
        elif mode == "jump":
            self._apply_jump(text)
        elif mode == "export":
            self._apply_export(text)
        elif mode == "pipe":
            self._apply_pipe(text)

    def _apply_search(self, text: str) -> None:
        if self._busy():
            return
        snap = self._constraints_snapshot()  # 扫描被取消/失败时退回这里
        try:
            self._search_re = compile_search(text)
        except re.error as e:
            self.notify(escape(t(f"Invalid regex: {e}", f"正则无效: {e}")), severity="error")
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
        expr = self._to_disk_expr(expr)  # 按看到的列名写; 存磁盘原名, 之后再改名也不失效
        try:
            scan.compile_where(expr)  # 只为校验: 谓词由 spec 现编
        except ValueError as e:
            self.notify(escape(str(e)), severity="error")
            return
        self._wheres.append(expr)
        self._recompute_subset(snap)

    # ------------------------------------------------------------------ #
    # 统一约束重算: 子集 = 全文件中满足 (搜索 且 每条 where 且 每列值约束) 的行, 再按排序键排
    # worker 线程扫全文件, 进度回填状态栏, Esc 可取消
    # ------------------------------------------------------------------ #
    def _constraint_label(self) -> str:
        """状态栏/血缘里的约束说明。"""
        parts = []
        if self._search_text:
            parts.append(t(f"search '{self._search_text}'", f"搜索'{self._search_text}'"))
        wheres = [self._to_shown_expr(e) for e in self._wheres]
        parts += [t(f"where '{e}'", f"筛选'{e}'") for e in wheres]
        parts += [
            t(f"{self._shown(c)}∈{len(v)} values", f"{self._shown(c)}∈{len(v)}值")
            for c, v in self._col_value_filters.items()
        ]
        return " · ".join(parts)

    def _recompute_subset(self, rollback=None, preserve_window: bool = False) -> None:
        """按当前所有约束重算子集并按排序键排序; 什么都没有则回全量顺序浏览。

        调用方须已通过 _busy() 确认没有扫描在跑 —— 那道闸在"改约束之前", 这里再挡就晚了
        (状态已经改过, 屏幕却停在旧子集)。
        rollback: 改约束之前的快照; 扫描被取消或失败时退回它 (见 _rollback_constraints)。
        """
        spec = self._spec()
        label = self._constraint_label()
        # 排序也算"需要扫描"的理由: 无筛选但要排序时, 子集 = 全部行号按键重排
        if not spec.has_filters and spec.sort_col is None:
            self._subset = None
            self._filter_label = None
            self._applied_spec = None
            self._row_ok = None
            if self._follow:
                self._follow_pinned = True
                self._follow_sort_snapshot = False
                self._load_follow_latest()
                self._rebuild_columns()  # 清列头标记
            else:
                self._load_window(0, rebuild_columns=True)
            return

        self._start_subset_scan(spec, label, rollback, preserve_window=preserve_window)

    def _start_subset_scan(
        self, spec: ScanSpec, label: str, rollback=None, preserve_window: bool = False
    ) -> None:
        """扫出满足 spec 的行号。新约束只是把旧约束收紧时, 只扫现有子集, 不重读文件。"""
        cancel, gen = self._begin_scan()
        self._scan_rollback = rollback
        base = scan.refine_base(self._applied_spec, spec, self._subset, self.source.total)
        self._set_scan_msg(
            t("Preparing to narrow the subset (Esc cancels)", "准备收紧子集 (Esc 取消)")
            if base is not None
            else t("Preparing full scan (Esc cancels)", "准备全量扫描 (Esc 取消)")
        )

        def progress(done: int, total: int) -> None:
            if not self._scan_superseded(gen):
                self.call_from_thread(
                    self._set_scan_msg,
                    t(
                        f"Scanning {done}/{total} (Esc cancels)",
                        f"扫描中 {done}/{total} (Esc 取消)",
                    ),
                )

        def worker():
            cancelled = (None, spec, label, True, gen, preserve_window)
            if base is None:
                if not self._prepare_full_scan(cancel):
                    return self._on_subset_scan_done, cancelled
                matches = scan.scan_rows(self.source, spec, progress=progress, cancel=cancel)
            else:
                matches = scan.refine_rows(
                    self.source, base, spec, progress=progress, cancel=cancel
                )
            if matches is None:
                return self._on_subset_scan_done, cancelled
            return self._on_subset_scan_done, (matches, spec, label, False, gen, preserve_window)

        self._run_scan(worker, gen)

    def _set_scan_msg(self, msg: str) -> None:
        self._scan_msg = msg
        self._update_status()

    def _prepare_full_scan(
        self, cancel, label: str = t("Indexing rows:", "补全行索引"), source=None
    ) -> bool:
        """全量操作的统一高水位入口；首窗和尾窗源均在此补全索引。

        source: 管道对原文件跑, 而 self.source 此时可能已是上一次的管道结果。
        """
        source = self.source if source is None else source
        if source.fully_indexed:
            return True

        self.call_from_thread(
            self._set_scan_msg, t(f"{label} 0 (Esc cancels)", f"{label} 0 行 (Esc 取消)")
        )

        def progress(n: int) -> None:
            self.call_from_thread(
                self._set_scan_msg, t(f"{label} {n} (Esc cancels)", f"{label} {n} 行 (Esc 取消)")
            )

        return source.ensure_index(progress_cb=progress, cancel=cancel)

    def _on_subset_scan_done(
        self,
        matches,
        spec: ScanSpec,
        label: str,
        cancelled: bool,
        gen: int,
        preserve_window: bool = False,
    ) -> None:
        if self._scan_superseded(gen):
            return  # 期间已被 r 重置或新扫描取代: 丢弃, 否则会把清掉的筛选复活
        self._end_scan()
        if cancelled:
            self._rollback_constraints()  # 取消 = 什么都没发生, 条件不生效
            if self._sort_spec is None:
                self._follow_sort_snapshot = False
            self.notify(t("Scan cancelled (conditions not applied)", "已取消扫描 (条件未生效)"))
            self._rebuild_columns()  # 值筛选的 ▾ 标记随之回退
            return
        self._scan_rollback = None  # 结果落地: 约束就此提交
        if preserve_window:
            # 轮转时旧尾窗仍留在屏幕上；新代次的筛选索引只接管之后的导航与增量行。
            self._subset = matches
            self._filter_label = label or None
            self._commit_spec(spec)
            self.win_offset = max(0, len(matches) - len(self.all_rows))
            self._update_status()
            self.notify(
                escape(
                    t(
                        f"Filter index refreshed after log rotation"
                        f" ({len(matches)} hits in the new file)",
                        f"日志轮转后已刷新筛选索引（当前文件命中 {len(matches)} 行）",
                    )
                )
            )
            return
        self._commit_subset(matches, label, spec)
        if not label:  # 纯排序 (无筛选): 行集没变, 说排序而不是"命中"
            self.notify(
                escape(
                    t(
                        f"Sorted all by {self._sort_label} ({len(matches)} rows)",
                        f"已按 {self._sort_label} 全量排序 ({len(matches)} 行)",
                    )
                )
            )
        elif matches:
            self.notify(
                escape(
                    t(
                        f"{label}: {len(matches)} hits ({self._scope_word()}) · r clears filters",
                        f"{label}: {len(matches)} 命中 ({self._scope_word()}) · r 清筛选",
                    )
                )
            )
        else:
            self.notify(
                escape(
                    t(
                        f"{label}: 0 hits (r resets; or click a header/F to loosen that column)",
                        f"{label}: 0 命中 (r 重置, 或点列头/F 放宽该列)",
                    )
                )
            )

    def _commit_subset(self, matches: List[int], label: str, spec: ScanSpec) -> None:
        """子集落地: 记下这一版约束, 定位到窗口并刷新列头标记。"""
        keep = self._cursor_global_no()  # 筛选前正看着的那条样本
        self._subset = matches  # 可能为空 (0 命中)
        self._filter_label = label or None
        self._commit_spec(spec)
        start = 0
        if self._follow and self._sort_spec is None:
            start = max(0, len(matches) - self.cap)
        self._load_window(start, rebuild_columns=True)  # 列头标记 (▾) 与命中高亮同趟重建
        if self._follow and self._sort_spec is None and self.view_indices:
            self._follow_moving = True
            self.query_one("#table", DataTable).move_cursor(row=len(self.view_indices) - 1)
            self.call_after_refresh(self._unlock_follow_move)
        else:
            self._restore_cursor(keep)

    def _cursor_global_no(self) -> Optional[int]:
        """光标所在样本的全局行号 (跨筛选/翻窗口唯一)。"""
        table = self.query_one("#table", DataTable)
        row = table.cursor_row
        if not self.view_indices or not 0 <= row < len(self.view_indices):
            return None
        return self._global_nos[self.view_indices[row]]

    def _restore_cursor(self, global_no: Optional[int]) -> None:
        """筛完把光标放回原来那条样本 —— 它常常就是你按 f 的原因 (照着它找同类)。

        它要是被筛掉了, 或落在别的窗口, 就留在首行: 从头看命中结果同样是常态, 为跟一条
        样本去跨窗口跳转反而喧宾夺主。
        """
        if global_no is None:
            return
        try:
            local = self._global_nos.index(global_no)
        except ValueError:
            return
        if local in self.view_indices:
            self.query_one("#table", DataTable).move_cursor(row=self.view_indices.index(local))

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
        col = col.strip()
        if col == "#":
            self.notify(t("The row-number column can't be value-filtered", "行号列不支持值筛选"))
            return
        if col not in self.columns:
            self.notify(
                escape(
                    t(
                        f"No such column: {col} (available: {self._shown_columns()})",
                        f"无此列: {col} (可选: {self._shown_columns()})",
                    )
                ),
                severity="error",
            )
            return
        if self._busy():
            return
        # 关键: 算该列候选值时应用"除本列外"的其他约束 → 本列自己筛掉的值仍在列表里, 可加回
        spec = self._spec().without_column(col)
        cancel, gen = self._begin_scan()
        self._value_scan_gen = gen
        self._set_scan_msg(
            t(f"Preparing to scan {col} values (Esc cancels)", f"准备扫描 {col} 值 (Esc 取消)")
        )

        def progress(done: int, total: int) -> None:
            if not self._scan_superseded(gen):
                self.call_from_thread(
                    self._set_scan_msg,
                    t(
                        f"Scanning {col} values {done}/{total} (Esc cancels)",
                        f"扫描 {col} 值 {done}/{total} (Esc 取消)",
                    ),
                )

        def worker():
            if not self._prepare_full_scan(cancel):
                return self._on_value_scan_done, (col, spec, None, gen)
            value_rows = scan.scan_values(self.source, col, spec, progress=progress, cancel=cancel)
            return self._on_value_scan_done, (col, spec, value_rows, gen)

        self._run_scan(worker, gen)

    def _on_value_scan_done(self, col: str, spec: ScanSpec, value_rows, gen: int) -> None:
        if self._scan_superseded(gen):
            return  # 期间已被 r 重置或新扫描取代
        self._end_scan()
        self._rebase_tail_after_index()
        self._update_status()
        if value_rows is None:
            self.notify(t("Scan cancelled", "已取消扫描"))
            return
        # 值 → 行号表随闭包留给 apply: 勾完 (其他约束没变且未排序) 直接拼子集, 免二次全扫
        items = sorted(value_rows.items(), key=lambda kv: -len(kv[1]))  # [(值, 频次)] 频次降序
        items = [(v, len(rows)) for v, rows in items]
        total = len(items)
        prior = self._col_value_filters.get(col)  # 上次保留集 (None=该列未筛→默认全不选)

        def apply(selected) -> None:
            if selected is None:  # Esc 取消
                return
            if selected == "rename":  # 第二击落在面板外的列头格上 = 双击
                self._begin_rename(col)
                return
            if self._busy():
                return
            snap = self._constraints_snapshot()
            if len(selected) == total:  # 全选 = 清除该列筛选 (Excel 语义)
                self._col_value_filters.pop(col, None)
                picked = value_rows.keys()
            else:
                self._col_value_filters[col] = selected
                picked = selected
            if self._apply_value_rows(col, spec, value_rows, picked):
                return
            self._recompute_subset(snap)

        cell = self._header_cell(col)
        anchor = (cell.x, cell.bottom) if cell is not None else None
        self.push_screen(
            ValueFilterScreen(
                col, items, total, prior, anchor, label=self._shown(col), header=cell
            ),
            apply,
        )

    def _apply_value_rows(self, col: str, spec: ScanSpec, value_rows, picked) -> bool:
        """用刚扫出来的 值→行号表 直接拼出子集; 前提不成立时返回 False 交给全量重算。

        成立条件: 其他约束与扫这张表时一模一样 (否则表已过期), 且没有排序 (排序键不在表里)。
        """
        new_spec = self._spec()
        if (
            not new_spec.has_filters
            or new_spec.sort_col is not None
            or new_spec.without_column(col) != spec
        ):
            return False
        matches = scan.merge_value_rows(value_rows, picked)
        self._commit_subset(matches, self._constraint_label(), new_spec)
        label = self._filter_label or ""
        self.notify(
            escape(
                t(
                    f"{label}: {len(matches)} hits ({self._scope_word()}) · r clears filters",
                    f"{label}: {len(matches)} 命中 ({self._scope_word()}) · r 清筛选",
                )
            )
        )
        return True

    def _header_cell(self, col: str) -> Optional[Region]:
        """列头格的屏幕区域 (含左右 padding): 值面板贴它下方弹出, 改名框盖在它上面; 拿不到则 None。"""
        try:
            table = self.query_one("#table", DataTable)
            vis = self._visible_columns()
            ci = vis.index(col)
            region = table._get_column_region(ci)  # x/width 已含左右 padding
            x = table.content_region.x + region.x - table.scroll_offset.x
            if ci >= table.fixed_columns:  # 横向滚动时冻结列 (#) 始终在最左, 别盖到它
                fixed_w = sum(table._get_column_region(j).width for j in range(table.fixed_columns))
                x = max(x, table.content_region.x + fixed_w)
            return Region(x, table.content_region.y, region.width, 1)
        except Exception:  # noqa: BLE001  定位失败退回居中, 不影响功能
            return None

    def action_snapshot(self) -> None:
        default = next((c for c in self._visible_columns() if c not in ("#",)), "chars")
        self._open_prompt(
            "snapshot",
            t(
                f"Column snapshot (column name, default {default}; full distribution: dt stats):",
                f"列快照 (列名, 默认 {default}; 完整分布用 dt stats):",
            ),
        )

    def _apply_snapshot(self, col: str) -> None:
        col = self._original(col.strip()) or next(
            (c for c in self._visible_columns() if c != "#"), ""
        )
        if col not in self.columns:
            self.notify(
                escape(
                    t(
                        f"No such column: {col} (available: {self._shown_columns()})",
                        f"无此列: {col} (可选: {self._shown_columns()})",
                    )
                ),
                severity="error",
            )
            return
        if self._busy():
            return
        ci = self.columns.index(col)
        cols = self.columns
        fmt = self.fmt
        cancel, gen = self._begin_scan()
        self._set_scan_msg(t("Preparing snapshot scan (Esc cancels)", "准备快照扫描 (Esc 取消)"))

        def worker():
            if not self._prepare_full_scan(cancel):
                return self._on_snapshot_done, (col, None, True, gen)
            seq_total = self._seq_total()
            self.call_from_thread(
                self._set_scan_msg,
                t(
                    f"Snapshot scan 0/{seq_total} (Esc cancels)",
                    f"快照扫描中 0/{seq_total} (Esc 取消)",
                ),
            )
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
                        self._set_scan_msg,
                        t(
                            f"Snapshot scan {n}/{seq_total} (Esc cancels)",
                            f"快照扫描中 {n}/{seq_total} (Esc 取消)",
                        ),
                    )
            stats = (n, nonempty, nnum, vmin, vmax, vsum)
            return self._on_snapshot_done, (col, stats, False, gen)

        self._run_scan(worker, gen)

    def _on_snapshot_done(self, col: str, stats, cancelled: bool, gen: int) -> None:
        if self._scan_superseded(gen):
            return  # 期间已被 r 重置或新扫描取代
        self._end_scan()
        self._rebase_tail_after_index()
        if cancelled:
            self.notify(t("Snapshot cancelled", "已取消快照"))
            self._update_status()
            return
        n, nonempty, nnum, vmin, vmax, vsum = stats
        col = self._shown(col)
        scope = t("subset", "子集") if self._subset is not None else t("all", "全量")
        rate = f"{100 * nonempty / n:.1f}%" if n else "-"
        if nnum:
            mean = vsum / nnum
            body = (
                f"{col} [{scope} n={n}]  min={_fmt_num(vmin)}  max={_fmt_num(vmax)}  "
                f"mean={_fmt_num(mean)}  " + t(f"non-empty {rate}", f"非空 {rate}")
            )
        else:  # 非数值列: 无 min/max/mean, 引导去 dt stats 看分布
            body = t(
                f"{col} [{scope} n={n}]  non-numeric, non-empty {rate}"
                " · full distribution: dt stats",
                f"{col} [{scope} n={n}]  非数值列, 非空 {rate} · 完整分布用 dt stats",
            )
        self.notify(escape(body), timeout=8)
        self._update_status()
