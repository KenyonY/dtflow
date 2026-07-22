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
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text

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
def _scalar_fields(rows: List[Dict], skip: set, limit: Optional[int] = None) -> List[str]:
    """收集顶层标量字段作为额外列 (label/source/id 等元数据)。

    limit=None 表示不限 (generic/CSV: 字段本身就是数据, 全部展示; 列过多可用 c 折叠)。
    """
    fields: List[str] = []
    for row in rows[:50]:
        if not isinstance(row, dict):
            continue
        for k, v in row.items():
            if k in skip or k in fields:
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                fields.append(k)
    return fields if limit is None else fields[:limit]


# 各格式的"派生列"名 (计算列, 无对应字段路径; 与标量元数据列区分)。
# 筛选时: 派生列按表格显示值比较, 其余名字当真实字段路径解析。
_DERIVED_COLUMNS = {
    "openai_chat": ["turns", "roles", "first_user", "chars"],
    "sharegpt": ["turns", "roles", "first_user", "chars"],
    "dpo": ["prompt", "chosen_chars", "rejected_chars"],
    "alpaca": ["instruction", "has_input", "out_chars"],
}


def derived_columns(fmt: str) -> set:
    """该格式的派生列名集合 (计算列, 无字段路径)。供筛选区分列名 vs 字段路径。"""
    return set(_DERIVED_COLUMNS.get(fmt, ()))


def build_columns(rows: List[Dict], fmt: str) -> List[str]:
    """根据格式返回表格列名 (含派生列 + 标量元数据列)。"""
    # base = "#" + 派生列 (单一来源 _DERIVED_COLUMNS, 与筛选的 derived_columns 一致, 不漂移)
    base = ["#"] + _DERIVED_COLUMNS.get(fmt, [])
    if fmt in ("openai_chat", "sharegpt"):
        skip = {"messages", "conversations"}
        limit = 8  # 训练格式: 派生列已含主信息, 元数据列适度限量 (可 c 折叠增删)
    elif fmt == "dpo":
        skip = {"chosen", "rejected", "prompt"}
        limit = 8
    elif fmt == "alpaca":
        skip = {"instruction", "input", "output", "response"}
        limit = 8
    else:
        skip = set()
        limit = None  # generic/CSV: 字段即数据, 全部展示
    return base + _scalar_fields(rows, skip, limit)


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
    derived: Dict[str, Any] = {"#": str((idx if row_no is None else row_no) + 1)}

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


# --------------------------------------------------------------------------- #
# 详情渲染: 选中样本 → Rich renderable
# --------------------------------------------------------------------------- #
def _render_content(content: str) -> List[RenderableType]:
    """按 ``` 代码块切分, 代码高亮, 普通文本原样。"""
    out: List[RenderableType] = []
    last = 0
    for m in _CODE_FENCE.finditer(content):
        if m.start() > last:
            pre = content[last : m.start()].strip("\n")
            if pre:
                out.append(Text(pre))
        lang = m.group(1) or "text"
        code = m.group(2).rstrip("\n")
        out.append(Syntax(code, lang, theme="ansi_dark", word_wrap=True, padding=(0, 1)))
        last = m.end()
    tail = content[last:].strip("\n")
    if tail or not out:
        out.append(Text(tail))
    return out


def _render_conversation(turns: List[Tuple[str, str]]) -> RenderableType:
    parts: List[RenderableType] = []
    for role, content in turns:
        style = _ROLE_STYLE.get(role, "bold white")
        parts.append(Text(f"[{role}]", style=style))
        parts.extend(_render_content(content))
        parts.append(Text(""))
    return Group(*parts)


def render_detail_sections(
    row: Dict, fmt: str, hidden: Optional[set] = None
) -> List[Tuple[str, RenderableType]]:
    """把详情拆成 [(字段名, renderable)] 分段, 供锚点定位 (切样本保持字段位置)。

    分段名即"字段": generic 为每个顶层 key; dpo/alpaca 为段名; 对话为 对话 + 元数据。
    hidden: 被折叠的字段, 详情里也不显示。
    """
    hidden = hidden or set()

    if fmt in ("openai_chat", "sharegpt"):
        secs: List[Tuple[str, RenderableType]] = [
            ("对话", _render_conversation(_normalize_turns(row, fmt)))
        ]
        extra = {
            k: v
            for k, v in row.items()
            if k not in ("messages", "conversations") and k not in hidden
        }
        if extra:
            secs.append(("元数据", _render_generic(extra)))
        return secs

    if fmt == "dpo":
        secs = []
        if row.get("prompt") and "prompt" not in hidden:
            secs.append(
                (
                    "prompt",
                    Group(
                        Text("[prompt]", style="bold cyan"),
                        *_render_content(_as_text(row["prompt"])),
                    ),
                )
            )
        secs.append(
            (
                "chosen",
                Group(
                    Text("[chosen]", style="bold green"),
                    *_render_content(_as_text(row.get("chosen", ""))),
                ),
            )
        )
        secs.append(
            (
                "rejected",
                Group(
                    Text("[rejected]", style="bold red"),
                    *_render_content(_as_text(row.get("rejected", ""))),
                ),
            )
        )
        return secs

    if fmt == "alpaca":
        secs = []
        for key in ("instruction", "input"):
            if row.get(key) and key not in hidden:
                secs.append(
                    (
                        key,
                        Group(
                            Text(f"[{key}]", style="bold cyan"),
                            *_render_content(_as_text(row[key])),
                        ),
                    )
                )
        out = row.get("output") or row.get("response") or ""
        secs.append(
            ("output", Group(Text("[output]", style="bold green"), *_render_content(_as_text(out))))
        )
        return secs

    return [(k, _render_generic({k: v})) for k, v in row.items() if k not in hidden]


def render_detail(row: Dict, fmt: str, hidden: Optional[set] = None) -> RenderableType:
    """把选中样本渲染成 Rich 可绘制对象, 默认全展开, 无需逐层进入。

    由 render_detail_sections 拼成 (段间插 Rule), 与锚点测量同源, 保证滚动定位精确。
    """
    parts: List[RenderableType] = []
    for i, (_, rend) in enumerate(render_detail_sections(row, fmt, hidden)):
        if i:
            parts.append(Rule(style="dim"))
        parts.append(rend)
    return Group(*parts)


def _render_generic(row: Any) -> RenderableType:
    """通用 JSON: 复用现有树形格式化, 全展开。"""
    from ..common import _format_nested

    lines = _format_nested(row, max_len=2000)
    return Group(*[Text.from_markup(ln) for ln in lines])
