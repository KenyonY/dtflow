"""
dt view 的数据模型与渲染层

职责:
- 格式检测 (openai_chat / sharegpt / dpo / alpaca / generic)
- 派生列 (把嵌套结构降维成可扫视的摘要列)
- 详情渲染 (把选中样本按格式渲染成 Rich 可绘制对象)

与 Textual 无关, 纯数据 → Rich renderable, 便于单测。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Pattern, Tuple

import orjson
from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text

from ...i18n import t
from ...rowfn import (
    Turn,
    _as_text,
    _calls_sig,
    _image_ref,
    _normalize_turns,
    _roles_sig,
    _top_images,
    image_mismatch,
)

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
    "observation": "yellow",
    "function_call": "bold green",
}

# roles 列的缩写 (rowfn._roles_sig) → 角色, 表格与详情同色, 一眼对上号
_ABBR_ROLE = {"sys": "system", "u": "user", "a": "assistant", "t": "tool"}


def roles_text(sig: str) -> Text:
    """把 ``sys→u→a→t`` 签名按角色着色 (不加粗, 表格里太重); 箭头与未知角色原色。"""
    text = Text(no_wrap=True, overflow="ellipsis")
    for i, abbr in enumerate(sig.split("→")):
        if i:
            text.append("→", style="dim")
        role = _ABBR_ROLE.get(abbr)
        text.append(abbr, style=_ROLE_STYLE[role].replace("bold ", "") if role else "")
    return text


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


def _preview(text: str, n: Optional[int] = 40) -> str:
    """压平成单行; n=None 表示不截断 (搜索/包含筛选用全文, 不能只看可见前缀)。"""
    text = text.replace("\n", " ").strip()
    if n is None:
        return text
    return text[:n] + "…" if len(text) > n else text


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
# 表达式里不注入这些名字: 对话列对应 rowfn 的同名行函数 (turns(x)), 其余是字段的简单变换,
# 翻译规则见 DERIVED_EXPR。
_DERIVED_COLUMNS = {
    "openai_chat": ["turns", "roles", "first_user", "chars", "calls", "imgs"],
    "sharegpt": ["turns", "roles", "first_user", "chars", "calls", "imgs"],
    "dpo": ["prompt", "chosen_chars", "rejected_chars"],
    "alpaca": ["instruction", "has_input", "out_chars"],
}
# 数值型派生列: 值筛选翻译回 --where 时直接比数, 其余按字符串
NUMERIC_DERIVED = frozenset(
    {"turns", "chars", "imgs", "chosen_chars", "rejected_chars", "out_chars"}
)
# 派生列 → 取值表达式 (把表格上的列翻译成 dt filter / dt sort 能吃的 Python 表达式)。
# 对话列是 rowfn 行函数; dpo/alpaca 的列只是字段的简单变换, 直接写出来。
DERIVED_EXPR = {
    "turns": "turns(x)",
    "roles": "roles(x)",
    "first_user": "first_user(x)",
    "chars": "chars(x)",
    "calls": "calls(x)",
    "imgs": "imgs(x)",
    "prompt": "x.get('prompt')",
    "chosen_chars": "len(x.get('chosen') or '')",
    "rejected_chars": "len(x.get('rejected') or '')",
    "instruction": "x.get('instruction')",
    "has_input": "bool(x.get('input'))",
    "out_chars": "len(x.get('output') or x.get('response') or '')",
}

_TRAINING_FORMATS = frozenset(_DERIVED_COLUMNS)
_TRAINING_META_LIMIT = 8
_DIAGNOSTIC_COLUMNS = ("_parse_error", "_raw_line")


def derived_columns(fmt: str) -> set:
    """该格式的派生列名集合 (计算列, 无字段路径)。供筛选区分列名 vs 字段路径。"""
    return set(_DERIVED_COLUMNS.get(fmt, ()))


def derived_values(row: Dict, fmt: str) -> Dict[str, Any]:
    """该格式全部派生列的**原始值** (int/bool/全文, 不截断)。

    对话列与 rowfn 的行函数同源, 但这里只归一化一次、五列共享 (逐个调 turns(x)/roles(x)
    会把每行归一化五遍, 值筛选/排序扫描慢五倍)。字符串/预览形态只在 row_cells 最后一步生成。
    """
    if fmt in ("openai_chat", "sharegpt"):
        turns = _normalize_turns(row)
        first_user = next((t.content for t in turns if t.role in ("user", "human")), "")
        return {
            "turns": len(turns),
            "roles": _roles_sig(turns),
            "first_user": first_user,
            "chars": sum(t.chars for t in turns),
            "calls": _calls_sig(turns),
            "imgs": sum(len(t.images) for t in turns),
        }
    if fmt == "dpo":
        return {
            "prompt": _as_text(row.get("prompt", "")),
            "chosen_chars": len(_as_text(row.get("chosen", ""))),
            "rejected_chars": len(_as_text(row.get("rejected", ""))),
        }
    if fmt == "alpaca":
        return {
            "instruction": _as_text(row.get("instruction", "")),
            "has_input": bool(row.get("input")),
            "out_chars": len(_as_text(row.get("output") or row.get("response") or "")),
        }
    return {}


def build_columns(rows: List[Dict], fmt: str) -> List[str]:
    """返回当前窗口发现的完整列目录 (派生列 + 顶层元数据列)。"""
    # base = "#" + 派生列 (单一来源 _DERIVED_COLUMNS, 与筛选的 derived_columns 一致, 不漂移)
    base = ["#"] + _DERIVED_COLUMNS.get(fmt, [])
    if "imgs" in base and not any(_has_images(r) for r in rows):
        base.remove("imgs")  # 纯文本对话不占这一列; 后续窗口出现图片时由列目录合并补上
    if fmt in ("openai_chat", "sharegpt"):
        skip = {"messages", "conversations"}
    elif fmt == "dpo":
        skip = {"chosen", "rejected", "prompt"}
    elif fmt == "alpaca":
        skip = {"instruction", "input", "output", "response"}
    else:
        skip = set()
    return base + _top_level_fields(rows, skip, set(base))


def _has_images(row: Any) -> bool:
    """行里有没有图片 (只看结构, 不做完整归一化: 决定列目录时要扫整个窗口)。"""
    if not isinstance(row, dict):
        return False
    if _top_images(row):
        return True
    msgs = row.get("messages")
    return isinstance(msgs, list) and any(
        isinstance(m, dict)
        and isinstance(m.get("content"), list)
        and any(isinstance(seg, dict) and _image_ref(seg) is not None for seg in m["content"])
        for m in msgs
    )


def default_visible_columns(columns: List[str], fmt: str) -> List[str]:
    """给完整列目录套默认可见策略。

    generic/CSV 默认展示全部；训练格式已有派生摘要，先展示 8 个元数据，其余留在 ``c``
    列面板。坏行诊断列无论出现多晚都默认可见，避免“坏在哪”再次被紧凑策略藏掉。
    """
    if fmt not in _TRAINING_FORMATS:
        return list(columns)

    base = [c for c in ["#"] + _DERIVED_COLUMNS[fmt] if c in columns]
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
    # 截断只为控制表格里每格的字符串体量; 上限放宽到够拖宽列时看到更多内容
    n_long = 160 if preview else None  # 长文本列 (first_user/prompt/instruction)
    n_meta = 120 if preview else None  # 普通标量列
    display_no = idx + 1 if row_no is None else (row_no if row_no < 0 else row_no + 1)
    derived: Dict[str, Any] = {"#": str(display_no)}
    for name, v in derived_values(row, fmt).items():
        if isinstance(v, bool):
            derived[name] = "✓" if v else ""
        elif isinstance(v, int):
            derived[name] = str(v)
        elif name in ("roles", "calls"):
            derived[name] = v
        else:  # 长文本列
            derived[name] = _preview(v, n_long)

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
def _hl(text: Text, highlight: Optional[Pattern]) -> Text:
    """给 Text 里所有命中处叠加高亮样式 (原地改, 返回自身便于内联)。"""
    if highlight is not None:
        text.highlight_regex(highlight, style=HIGHLIGHT_STYLE)
    return text


def _render_content(
    content: str, highlight: Optional[Pattern] = None, code_bg: Optional[str] = None
) -> List[RenderableType]:
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
        out.append(_syntax(code, lang, code_bg))
        last = m.end()
    tail = content[last:].strip("\n")
    if tail or not out:
        out.append(_hl(Text(tail), highlight))
    return out


def _syntax(code: str, lang: str, code_bg: Optional[str]) -> Syntax:
    """代码/JSON 块。code_bg: 块底色 (TUI 按主题传入), 与正文分开; None 不铺底 ——
    dt head 直接打印到终端, 不知道终端底色, 硬铺一块深色在浅色终端上很扎眼。"""
    return Syntax(
        code, lang, theme="ansi_dark", word_wrap=True, padding=(0, 1), background_color=code_bg
    )


def _json_block(raw: str, code_bg: Optional[str] = None) -> Tuple[Optional[RenderableType], bool]:
    """字符串若是合法 JSON 对象/数组, 格式化成 json 高亮块; 否则返回 (None, False)。"""
    try:
        obj = orjson.loads(raw)
    except orjson.JSONDecodeError:
        return None, False
    if not isinstance(obj, (dict, list)):
        return None, True  # 合法 JSON 但只是标量, 原样显示即可
    pretty = json.dumps(obj, ensure_ascii=False, indent=2)
    return _syntax(pretty, "json", code_bg), True


def _badge(label: str, style: str) -> Text:
    """段标题徽章: 反色色块。长对话一屏十几条消息, 比 ``[role]`` 方括号更快找到换人处。"""
    color = " ".join(w for w in style.split() if w not in ("bold", "dim"))
    # 样式挂在这一段上而不是 Text 的底样式: 调用方还要在后面接 → fn / 字数, 不能跟着反色
    return Text.assemble((f" {label} ", f"bold reverse {color}"))


def _turn_title(turn: Turn, style: str, highlight: Optional[Pattern] = None) -> Text:
    """消息标题行: 角色徽章 + 调用/回执 (→ fn / ← call_id) + 暗色字数。

    字数是算出来的, 不是数据, 追加在搜索高亮之后 —— 否则搜数字时每条标题都是假命中。
    """
    title = _badge(turn.role, style)
    if turn.tool_calls:
        title.append(f" → {', '.join(c.name for c in turn.tool_calls)}", style=style)
    elif turn.call_id:
        title.append(f" ← {turn.call_id}", style=style)
    _hl(title, highlight)
    if turn.content:
        n = len(turn.content)
        title.append(t(f"  {n} chars", f"  {n} 字"), style="dim")
    return title


def _turn_header(turn: Turn) -> str:
    """纯文本标题 (命中查找用): ``[role]``; 发起调用的写成 ``[assistant → fn1, fn2]``,
    工具返回写成 ``[tool ← call_id]``。显示用 _turn_title。"""
    if turn.tool_calls:
        return f"[{turn.role} → {', '.join(c.name for c in turn.tool_calls)}]"
    if turn.call_id:
        return f"[{turn.role} ← {turn.call_id}]"
    return f"[{turn.role}]"


def image_label(ref: str) -> str:
    """图片引用的显示形态: data URI 只留头部与大小 (base64 正文动辄几十万字符)。"""
    if ref.startswith("data:"):
        head, _, body = ref.partition(",")
        return f"{head},… ({len(body) * 3 // 4 / 1024:.1f} KB)"
    return ref or t("(empty image reference)", "(图片引用为空)")


IMAGE_LINE_PREFIX = "🖼 "  # 详情里图片行的开头; app 靠它认出点击的是图片行


def _image_lines(turn: Turn, highlight: Optional[Pattern]) -> List[Text]:
    return [
        _hl(Text(IMAGE_LINE_PREFIX + image_label(ref), style="magenta"), highlight)
        for ref in turn.images
    ]


def _render_turn(
    turn: Turn, highlight: Optional[Pattern] = None, code_bg: Optional[str] = None
) -> RenderableType:
    """单条消息: 标题行 + (思维链) + 正文 + (工具调用块)。

    看 agent 数据最要核对的三件事都直接摆出来: arguments 是不是合法 JSON (不合法标红),
    tool 返回对应哪次调用 (标题带 call_id), 模型最后说的话是否有工具返回支撑 (紧挨着看)。
    JSON 块用 Syntax 着色, 与代码块一样不叠加搜索高亮。
    """
    style = _ROLE_STYLE.get(turn.role, "bold white")
    parts: List[RenderableType] = [_turn_title(turn, style, highlight)]
    if turn.reasoning:
        parts.append(Text("(reasoning)", style="dim italic"))
        parts.append(_hl(Text(turn.reasoning, style="dim"), highlight))
    if turn.content:
        if turn.call_id or turn.role in ("tool", "observation", "function"):
            block, _ = _json_block(turn.content, code_bg)  # 工具返回常是 JSON, 格式化后才看得清
            parts.append(block or _hl(Text(turn.content), highlight))
        else:
            parts.extend(_render_content(turn.content, highlight, code_bg))
    parts.extend(_image_lines(turn, highlight))
    for call in turn.tool_calls:
        title = Text(f"⚙ {call.name}", style="bold yellow")
        if call.call_id:
            title.append(f"  {call.call_id}", style="dim")
        parts.append(_hl(title, highlight))
        if call.name == "?":
            parts.append(Text(t("⚠ missing function name", "⚠ 缺少函数名"), style="bold red"))
        block, valid = _json_block(call.arguments, code_bg)
        if block is not None:
            parts.append(block)
        else:
            parts.append(_hl(Text(call.arguments), highlight))
            if not valid:
                parts.append(
                    Text(
                        t("⚠ arguments is not valid JSON", "⚠ arguments 不是合法 JSON"),
                        style="bold red",
                    )
                )
    return Group(*parts)


def _turn_plain(turn: Turn) -> str:
    """与 _render_turn 同源的纯文本 (命中查找用)。"""
    lines = [_turn_header(turn)]
    if turn.reasoning:
        lines.append(turn.reasoning)
    if turn.content:
        lines.append(turn.content)
    lines.extend(IMAGE_LINE_PREFIX + image_label(ref) for ref in turn.images)
    for c in turn.tool_calls:
        lines.append(f"{c.name}({c.arguments}) {c.call_id}".rstrip())
    return "\n".join(lines)


def _render_conversation(turns: List[Turn], highlight: Optional[Pattern] = None) -> RenderableType:
    parts: List[RenderableType] = []
    for turn in turns:
        parts.append(_render_turn(turn, highlight))
        parts.append(Text(""))
    return Group(*parts)


def _labeled(
    label: str, style: str, text: str, highlight: Optional[Pattern], code_bg: Optional[str]
):
    """徽章标题行 + 正文, 并返回配套纯文本 (供命中查找)。"""
    return (
        Group(_hl(_badge(label, style), highlight), *_render_content(text, highlight, code_bg)),
        f"[{label}]\n{text}",
    )


def render_detail_sections(
    row: Dict,
    fmt: str,
    hidden: Optional[set] = None,
    split_turns: bool = False,
    highlight: Optional[Pattern] = None,
    code_bg: Optional[str] = None,
) -> List[Tuple[str, RenderableType, str]]:
    """把详情拆成 [(字段名, renderable, 纯文本)] 分段, 供锚点定位与命中查找。

    分段名即"字段": generic 为每个顶层 key; dpo/alpaca 为段名; 对话为 对话 + 元数据。
    纯文本与 renderable 同源, 用来判断"这一段里有没有搜索命中"(``*`` 跳转)。

    hidden: 被折叠的字段, 详情里也不显示。
    split_turns: 对话格式下每条消息独立成段 (段名 ``msg0``/``msg1``…), 使 n/N 变成
        逐条消息导航。段名刻意不含 role —— 切样本时靠段名对齐位置, 而不同样本同一位置
        的角色未必相同, 名字带 role 会对不齐。role 仍显示在段内容的标题徽章上。
        默认 False: dt head/sample 的静态打印走 render_detail, 不该被拆成一堆分隔块。
    highlight: 搜索命中的正则, 命中处叠加黄底。
    code_bg: 代码/JSON 块底色 (见 _syntax)。
    """
    hidden = hidden or set()

    if fmt in ("openai_chat", "sharegpt"):
        turns = _normalize_turns(row)
        secs: List[Tuple[str, RenderableType, str]] = []
        if split_turns:
            for i, turn in enumerate(turns):
                secs.append((f"msg{i}", _render_turn(turn, highlight, code_bg), _turn_plain(turn)))
        else:
            plain = "\n".join(_turn_plain(turn) for turn in turns)
            secs.append((t("conversation", "对话"), _render_conversation(turns, highlight), plain))
        mismatch = image_mismatch(row, turns)
        if mismatch and secs:  # 坏样本放最上面, 一打开就看到
            n, m = mismatch
            if n > m:  # 占位没有图: 哪个框架都训不对
                warn = Text(
                    t(
                        f"⚠ {n} <image> placeholder(s) but {m} image(s)",
                        f"⚠ {n} 个 <image> 占位, 但有 {m} 张图",
                    ),
                    style="bold red",
                )
            else:  # 图多于占位: ms-swift 自动在首条消息前补占位, LLaMA-Factory 直接报错
                warn = Text(
                    t(
                        f"⚠ {m} image(s) but {n} <image> placeholder(s): ms-swift prepends the "
                        "missing ones to the first message (shown there), LLaMA-Factory rejects it",
                        f"⚠ {m} 张图但只有 {n} 个 <image> 占位: ms-swift 会在首条消息前补占位"
                        "(图已按此显示), LLaMA-Factory 会报错",
                    ),
                    style="bold yellow",
                )
            name, rend, plain = secs[0]
            secs[0] = (name, Group(warn, rend), f"{warn.plain}\n{plain}")
        extra = {
            k: v
            for k, v in row.items()
            if k not in ("messages", "conversations") and k not in hidden
        }
        if extra:
            secs.append((t("metadata", "元数据"), *_render_generic(extra, highlight)))
        return secs

    def labeled(name: str, style: str, value: Any) -> Tuple[str, RenderableType, str]:
        return (name, *_labeled(name, style, _as_text(value), highlight, code_bg))

    if fmt == "dpo":
        secs = []
        if row.get("prompt") and "prompt" not in hidden:
            secs.append(labeled("prompt", "bold cyan", row["prompt"]))
        secs.append(labeled("chosen", "bold green", row.get("chosen", "")))
        secs.append(labeled("rejected", "bold red", row.get("rejected", "")))
        return secs

    if fmt == "alpaca":
        secs = []
        for key in ("instruction", "input"):
            if row.get(key) and key not in hidden:
                secs.append(labeled(key, "bold cyan", row[key]))
        secs.append(labeled("output", "bold green", row.get("output") or row.get("response") or ""))
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
