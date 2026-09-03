"""
dt view 的数据模型与渲染层

职责:
- 格式检测 (openai_chat / sharegpt / dpo / alpaca / generic)
- 派生列 (把嵌套结构降维成可扫视的摘要列)
- 详情渲染 (把选中样本按格式渲染成 Rich 可绘制对象)

与 Textual 无关, 纯数据 → Rich renderable, 便于单测。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Pattern, Tuple

from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text

# 搜索命中的高亮样式 (表格单元格与详情共用; 黄底黑字在明暗主题下都醒目)
HIGHLIGHT_STYLE = "black on yellow"

# role → 颜色 (对话气泡上色)
_ROLE_STYLE = {
    "system": "dim magenta",
    "user": "bold cyan",
    "human": "bold cyan",
    "assistant": "bold green",
    "gpt": "bold green",
    "tool": "yellow",
    "function": "yellow",
}

_CODE_FENCE = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)


# --------------------------------------------------------------------------- #
# 格式检测
# --------------------------------------------------------------------------- #
def detect_format(rows: List[Dict]) -> str:
    """采样首行判断数据格式。返回 openai_chat/sharegpt/dpo/alpaca/generic。"""
    for row in rows[:20]:
        if not isinstance(row, dict):
            return "generic"
        if isinstance(row.get("messages"), list):
            return "openai_chat"
        if isinstance(row.get("conversations"), list):
            return "sharegpt"
        if "chosen" in row and "rejected" in row:
            return "dpo"
        if "instruction" in row and ("output" in row or "response" in row):
            return "alpaca"
    return "generic"


def _normalize_turns(row: Dict, fmt: str) -> List[Tuple[str, str]]:
    """统一抽取 (role, content) 列表, 供表格摘要和详情渲染共用。"""
    if fmt == "openai_chat":
        msgs = row.get("messages") or []
        return [(str(m.get("role", "")), _as_text(m.get("content", ""))) for m in msgs]
    if fmt == "sharegpt":
        msgs = row.get("conversations") or []
        return [(str(m.get("from", "")), _as_text(m.get("value", ""))) for m in msgs]
    return []


def _as_text(v: Any) -> str:
    """content 可能是 str, 也可能是多模态 list, 统一成字符串。"""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        parts = []
        for seg in v:
            if isinstance(seg, dict):
                parts.append(seg.get("text") or seg.get("type") or "")
            else:
                parts.append(str(seg))
        return " ".join(p for p in parts if p)
    return str(v)


def _preview(text: str, n: Optional[int] = 40) -> str:
    """压平成单行; n=None 表示不截断 (搜索/包含筛选用全文, 不能只看可见前缀)。"""
    text = text.replace("\n", " ").strip()
    if n is None:
        return text
    return text[:n] + "…" if len(text) > n else text


def _roles_sig(turns: List[Tuple[str, str]]) -> str:
    """角色序列签名, 如 u→a→u; 长了截断。"""
    abbr = {"system": "sys", "user": "u", "human": "u", "assistant": "a", "gpt": "a"}
    seq = [abbr.get(r, r[:3]) for r, _ in turns]
    if len(seq) > 5:
        seq = seq[:4] + ["…"]
    return "→".join(seq)


# --------------------------------------------------------------------------- #
# 派生列: 定义列 + 逐行取值
# --------------------------------------------------------------------------- #
def _top_level_fields(rows: List[Dict], skip: set, reserved: set) -> List[str]:
    """收集当前窗口里出现过的顶层字段, 保持首次出现顺序。

    对象/数组字段同样是 JSON 的真实列: 表格给紧凑预览, 完整内容交给详情。这里只跳过
    已由派生列代替的训练主体字段, 不再用值类型或固定采样行数静默裁掉 schema。
    """
    fields: List[str] = []
    seen = set(reserved)
    for row in rows:
        if not isinstance(row, dict):
            continue
        for k in row:
            if k in skip or k in seen:
                continue
            fields.append(k)
            seen.add(k)
    return fields


# 各格式的"派生列"名 (计算列, 无对应字段路径; 与标量元数据列区分)。
# 筛选时: 派生列按表格显示值比较, 其余名字当真实字段路径解析。
_DERIVED_COLUMNS = {
    "openai_chat": ["turns", "roles", "first_user", "chars"],
    "sharegpt": ["turns", "roles", "first_user", "chars"],
    "dpo": ["prompt", "chosen_chars", "rejected_chars"],
    "alpaca": ["instruction", "has_input", "out_chars"],
}

_TRAINING_FORMATS = frozenset(_DERIVED_COLUMNS)
_TRAINING_META_LIMIT = 8
_DIAGNOSTIC_COLUMNS = ("_parse_error", "_raw_line")


def derived_columns(fmt: str) -> set:
    """该格式的派生列名集合 (计算列, 无字段路径)。供筛选区分列名 vs 字段路径。"""
    return set(_DERIVED_COLUMNS.get(fmt, ()))


def build_columns(rows: List[Dict], fmt: str) -> List[str]:
    """返回当前窗口发现的完整列目录 (派生列 + 顶层元数据列)。"""
    # base = "#" + 派生列 (单一来源 _DERIVED_COLUMNS, 与筛选的 derived_columns 一致, 不漂移)
    base = ["#"] + _DERIVED_COLUMNS.get(fmt, [])
    if fmt in ("openai_chat", "sharegpt"):
        skip = {"messages", "conversations"}
    elif fmt == "dpo":
        skip = {"chosen", "rejected", "prompt"}
    elif fmt == "alpaca":
        skip = {"instruction", "input", "output", "response"}
    else:
        skip = set()
    return base + _top_level_fields(rows, skip, set(base))


def default_visible_columns(columns: List[str], fmt: str) -> List[str]:
    """给完整列目录套默认可见策略。

    generic/CSV 默认展示全部；训练格式已有派生摘要，先展示 8 个元数据，其余留在 ``c``
    列面板。坏行诊断列无论出现多晚都默认可见，避免“坏在哪”再次被紧凑策略藏掉。
    """
    if fmt not in _TRAINING_FORMATS:
        return list(columns)

    base = ["#"] + _DERIVED_COLUMNS[fmt]
    metadata = [c for c in columns if c not in base]
    visible = base + metadata[:_TRAINING_META_LIMIT]
    for col in _DIAGNOSTIC_COLUMNS:
        if col in columns and col not in visible:
            visible.append(col)
    return visible


def row_cells(
    idx: int,
    row: Dict,
    fmt: str,
    columns: List[str],
    row_no: Optional[int] = None,
    preview: bool = True,
) -> List[str]:
    """把一行数据转成表格单元格字符串列表 (与 columns 对齐)。

    row_no: 用于 ``#`` 列显示的行号 (0-based); None 时用 idx (窗口化后应传全局行号)。
    preview: False 时文本列不截断 —— 搜索/包含筛选须匹配全文, 否则长内容里靠后的
             关键词会被"只搜可见前缀"静默漏掉。表格显示/值勾选仍用 True。
    """
    n_long = 80 if preview else None  # 长文本列 (first_user/prompt/instruction)
    n_meta = 60 if preview else None  # 普通标量列
    display_no = idx + 1 if row_no is None else (row_no if row_no < 0 else row_no + 1)
    derived: Dict[str, Any] = {"#": str(display_no)}

    if fmt in ("openai_chat", "sharegpt"):
        turns = _normalize_turns(row, fmt)
        first_user = next((c for r, c in turns if r in ("user", "human")), "")
        derived.update(
            turns=str(len(turns)),
            roles=_roles_sig(turns),
            first_user=_preview(first_user, n_long),
            chars=str(sum(len(c) for _, c in turns)),
        )
    elif fmt == "dpo":
        derived.update(
            prompt=_preview(_as_text(row.get("prompt", "")), n_long),
            chosen_chars=str(len(_as_text(row.get("chosen", "")))),
            rejected_chars=str(len(_as_text(row.get("rejected", "")))),
        )
    elif fmt == "alpaca":
        derived.update(
            instruction=_preview(_as_text(row.get("instruction", "")), n_long),
            has_input="✓" if row.get("input") else "",
            out_chars=str(len(_as_text(row.get("output") or row.get("response") or ""))),
        )

    cells = []
    for col in columns:
        if col in derived:
            cells.append(derived[col])
        else:
            v = row.get(col) if isinstance(row, dict) else None
            cells.append("" if v is None else _preview(str(v), n_meta))
    return cells


def row_text(row: Any) -> str:
    """把一行里所有标量值拼成可搜索的纯文本 (只取值, 不含键名)。

    ``/`` 问的是"这条样本里有没有这个词", 所以必须看整条记录: 表格列只是派生摘要
    (first_user 只是第一条用户消息), 靠列搜会把 assistant 回复、后续轮次整个漏掉 ——
    而那恰恰是最常要找的地方。不含键名, 免得搜 "content" 命中每一行。
    """
    out: List[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        elif v is not None:
            out.append(str(v))

    walk(row)
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# 详情渲染: 选中样本 → Rich renderable
# --------------------------------------------------------------------------- #
def _hl(text: Text, highlight: Optional[Pattern]) -> Text:
    """给 Text 里所有命中处叠加高亮样式 (原地改, 返回自身便于内联)。"""
    if highlight is not None:
        text.highlight_regex(highlight, style=HIGHLIGHT_STYLE)
    return text


def _render_content(content: str, highlight: Optional[Pattern] = None) -> List[RenderableType]:
    """按 ``` 代码块切分, 代码高亮, 普通文本原样。

    highlight: 搜索命中的正则, 命中处叠加黄底。代码块 (Syntax) 不叠加 —— Syntax 自带
    词法着色, rich 不支持在其上再加 span; 代码里的命中靠上下文文本段定位。
    """
    out: List[RenderableType] = []
    last = 0
    for m in _CODE_FENCE.finditer(content):
        if m.start() > last:
            pre = content[last : m.start()].strip("\n")
            if pre:
                out.append(_hl(Text(pre), highlight))
        lang = m.group(1) or "text"
        code = m.group(2).rstrip("\n")
        out.append(Syntax(code, lang, theme="ansi_dark", word_wrap=True, padding=(0, 1)))
        last = m.end()
    tail = content[last:].strip("\n")
    if tail or not out:
        out.append(_hl(Text(tail), highlight))
    return out


def _render_turn(role: str, content: str, highlight: Optional[Pattern] = None) -> RenderableType:
    """单条消息: [role] 标题行 + 正文。"""
    style = _ROLE_STYLE.get(role, "bold white")
    return Group(Text(f"[{role}]", style=style), *_render_content(content, highlight))


def _render_conversation(
    turns: List[Tuple[str, str]], highlight: Optional[Pattern] = None
) -> RenderableType:
    parts: List[RenderableType] = []
    for role, content in turns:
        parts.append(_render_turn(role, content, highlight))
        parts.append(Text(""))
    return Group(*parts)


def _labeled(label: str, style: str, text: str, highlight: Optional[Pattern]):
    """``[label]`` 标题行 + 正文, 并返回配套纯文本 (供命中查找)。"""
    return (
        Group(Text(f"[{label}]", style=style), *_render_content(text, highlight)),
        f"[{label}]\n{text}",
    )


def render_detail_sections(
    row: Dict,
    fmt: str,
    hidden: Optional[set] = None,
    split_turns: bool = False,
    highlight: Optional[Pattern] = None,
) -> List[Tuple[str, RenderableType, str]]:
    """把详情拆成 [(字段名, renderable, 纯文本)] 分段, 供锚点定位与命中查找。

    分段名即"字段": generic 为每个顶层 key; dpo/alpaca 为段名; 对话为 对话 + 元数据。
    纯文本与 renderable 同源, 用来判断"这一段里有没有搜索命中"(``*`` 跳转)。

    hidden: 被折叠的字段, 详情里也不显示。
    split_turns: 对话格式下每条消息独立成段 (段名 ``msg0``/``msg1``…), 使 n/N 变成
        逐条消息导航。段名刻意不含 role —— 切样本时靠段名对齐位置, 而不同样本同一位置
        的角色未必相同, 名字带 role 会对不齐。role 仍显示在段内容的 ``[user]`` 标题行。
        默认 False: dt head/sample 的静态打印走 render_detail, 不该被拆成一堆分隔块。
    highlight: 搜索命中的正则, 命中处叠加黄底。
    """
    hidden = hidden or set()

    if fmt in ("openai_chat", "sharegpt"):
        turns = _normalize_turns(row, fmt)
        secs: List[Tuple[str, RenderableType, str]] = []
        if split_turns:
            for i, (role, content) in enumerate(turns):
                secs.append(
                    (f"msg{i}", _render_turn(role, content, highlight), f"[{role}]\n{content}")
                )
        else:
            plain = "\n".join(f"[{r}]\n{c}" for r, c in turns)
            secs.append(("对话", _render_conversation(turns, highlight), plain))
        extra = {
            k: v
            for k, v in row.items()
            if k not in ("messages", "conversations") and k not in hidden
        }
        if extra:
            secs.append(("元数据", *_render_generic(extra, highlight)))
        return secs

    if fmt == "dpo":
        secs = []
        if row.get("prompt") and "prompt" not in hidden:
            secs.append(
                ("prompt", *_labeled("prompt", "bold cyan", _as_text(row["prompt"]), highlight))
            )
        secs.append(
            (
                "chosen",
                *_labeled("chosen", "bold green", _as_text(row.get("chosen", "")), highlight),
            )
        )
        secs.append(
            (
                "rejected",
                *_labeled("rejected", "bold red", _as_text(row.get("rejected", "")), highlight),
            )
        )
        return secs

    if fmt == "alpaca":
        secs = []
        for key in ("instruction", "input"):
            if row.get(key) and key not in hidden:
                secs.append((key, *_labeled(key, "bold cyan", _as_text(row[key]), highlight)))
        out = row.get("output") or row.get("response") or ""
        secs.append(("output", *_labeled("output", "bold green", _as_text(out), highlight)))
        return secs

    return [(k, *_render_generic({k: v}, highlight)) for k, v in row.items() if k not in hidden]


def render_detail(row: Dict, fmt: str, hidden: Optional[set] = None) -> RenderableType:
    """把选中样本渲染成 Rich 可绘制对象, 默认全展开, 无需逐层进入。

    由 render_detail_sections 拼成 (段间插 Rule)。对话不拆条 (split_turns 默认 False),
    与 dt head/sample 的既有输出保持一致。
    """
    parts: List[RenderableType] = []
    for i, (_, rend, _plain) in enumerate(render_detail_sections(row, fmt, hidden)):
        if i:
            parts.append(Rule(style="dim"))
        parts.append(rend)
    return Group(*parts)


def _render_generic(row: Any, highlight: Optional[Pattern] = None) -> Tuple[RenderableType, str]:
    """通用 JSON: 复用现有树形格式化, 全展开。返回 (renderable, 纯文本)。"""
    from ..common import _format_nested

    # 详情面板可滚动, 完整展示是它的职责 — 不截断 (截断只属于 head/sample 等预览场景)
    texts = [_hl(Text.from_markup(ln), highlight) for ln in _format_nested(row, max_len=None)]
    return Group(*texts), "\n".join(t.plain for t in texts)
