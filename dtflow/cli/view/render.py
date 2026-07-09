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
from typing import Any, Dict, List, Tuple

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


def _preview(text: str, n: int = 40) -> str:
    text = text.replace("\n", " ").strip()
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
def _scalar_fields(rows: List[Dict], skip: set) -> List[str]:
    """收集顶层标量字段作为额外列 (label/source/id 等元数据)。"""
    fields: List[str] = []
    for row in rows[:50]:
        if not isinstance(row, dict):
            continue
        for k, v in row.items():
            if k in skip or k in fields:
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                fields.append(k)
    return fields[:6]


def build_columns(rows: List[Dict], fmt: str) -> List[str]:
    """根据格式返回表格列名 (含派生列 + 标量元数据列)。"""
    if fmt in ("openai_chat", "sharegpt"):
        base = ["#", "turns", "roles", "first_user", "chars"]
        skip = {"messages", "conversations"}
    elif fmt == "dpo":
        base = ["#", "prompt", "chosen_chars", "rejected_chars"]
        skip = {"chosen", "rejected", "prompt"}
    elif fmt == "alpaca":
        base = ["#", "instruction", "has_input", "out_chars"]
        skip = {"instruction", "input", "output", "response"}
    else:
        base = ["#"]
        skip = set()
    return base + _scalar_fields(rows, skip)


def row_cells(idx: int, row: Dict, fmt: str, columns: List[str]) -> List[str]:
    """把一行数据转成表格单元格字符串列表 (与 columns 对齐)。"""
    derived: Dict[str, Any] = {"#": str(idx + 1)}

    if fmt in ("openai_chat", "sharegpt"):
        turns = _normalize_turns(row, fmt)
        first_user = next((c for r, c in turns if r in ("user", "human")), "")
        derived.update(
            turns=str(len(turns)),
            roles=_roles_sig(turns),
            first_user=_preview(first_user),
            chars=str(sum(len(c) for _, c in turns)),
        )
    elif fmt == "dpo":
        derived.update(
            prompt=_preview(_as_text(row.get("prompt", ""))),
            chosen_chars=str(len(_as_text(row.get("chosen", "")))),
            rejected_chars=str(len(_as_text(row.get("rejected", "")))),
        )
    elif fmt == "alpaca":
        derived.update(
            instruction=_preview(_as_text(row.get("instruction", ""))),
            has_input="✓" if row.get("input") else "",
            out_chars=str(len(_as_text(row.get("output") or row.get("response") or ""))),
        )

    cells = []
    for col in columns:
        if col in derived:
            cells.append(derived[col])
        else:
            v = row.get(col) if isinstance(row, dict) else None
            cells.append("" if v is None else _preview(str(v), 30))
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


def render_detail(row: Dict, fmt: str) -> RenderableType:
    """把选中样本渲染成 Rich 可绘制对象, 默认全展开, 无需逐层进入。"""
    if fmt in ("openai_chat", "sharegpt"):
        turns = _normalize_turns(row, fmt)
        parts: List[RenderableType] = [_render_conversation(turns)]
        extra = {k: v for k, v in row.items() if k not in ("messages", "conversations")}
        if extra:
            parts.append(Rule(style="dim"))
            parts.append(_render_generic(extra))
        return Group(*parts)

    if fmt == "dpo":
        parts = []
        if row.get("prompt"):
            parts.append(Text("[prompt]", style="bold cyan"))
            parts.extend(_render_content(_as_text(row["prompt"])))
            parts.append(Rule(style="dim"))
        parts.append(Text("[chosen]", style="bold green"))
        parts.extend(_render_content(_as_text(row.get("chosen", ""))))
        parts.append(Rule(style="dim"))
        parts.append(Text("[rejected]", style="bold red"))
        parts.extend(_render_content(_as_text(row.get("rejected", ""))))
        return Group(*parts)

    if fmt == "alpaca":
        parts = []
        for label, key in (("instruction", "instruction"), ("input", "input")):
            if row.get(key):
                parts.append(Text(f"[{label}]", style="bold cyan"))
                parts.extend(_render_content(_as_text(row[key])))
        out = row.get("output") or row.get("response") or ""
        parts.append(Text("[output]", style="bold green"))
        parts.extend(_render_content(_as_text(out)))
        return Group(*parts)

    return _render_generic(row)


def _render_generic(row: Any) -> RenderableType:
    """通用 JSON: 复用现有树形格式化, 全展开。"""
    from ..common import _format_nested

    lines = _format_nested(row, max_len=2000)
    return Group(*[Text.from_markup(ln) for ln in lines])
