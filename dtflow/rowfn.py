"""行函数 (row functions): 给一行训练样本算摘要的纯函数, 表达式命名空间与 dt view 共用。

``dt filter d.jsonl "turns(x)>=6 and search(x, '退款')"`` 与 view 表头上的 turns/roles/chars
列算的是同一个东西 —— 这里是唯一实现, 免得两处各算一遍还算不一样。

只依赖 orjson, 不 import typer/textual/expr (expr 会 import 本模块; view 的 fork 子进程也用)。
helper 接受 dict 或表达式里的 DictWrapper, 不深拷贝。
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Callable, Dict, List, NamedTuple, Pattern, Tuple

import orjson

from .i18n import t


class ToolCall(NamedTuple):
    name: str
    arguments: str  # 原样保留: 是否合法 JSON 正是要检查的东西, 渲染时再判断
    call_id: str


class Turn(NamedTuple):
    """一条消息归一化后的样子, 供表格摘要与详情渲染共用。"""

    role: str
    content: str
    reasoning: str = ""  # reasoning_content / reasoning (思维链)
    tool_calls: Tuple[ToolCall, ...] = ()
    call_id: str = ""  # tool 消息回应的 tool_call_id

    @property
    def chars(self) -> int:
        """模型实际读/写的字符数: 正文 + 思维链 + 工具调用参数。"""
        return (
            len(self.content)
            + len(self.reasoning)
            + sum(len(c.name) + len(c.arguments) for c in self.tool_calls)
        )


def _parse_tool_calls(raw: Any) -> Tuple[ToolCall, ...]:
    """tool_calls 列表 (或旧版 function_call 单个 dict) → ToolCall 元组。

    结构不对的条目不丢: name 缺失记 "?", arguments 缺失/为 null 记空串 (渲染时会标红),
    坏掉的调用恰恰是要找的东西。
    """
    if isinstance(raw, dict):  # 旧版 OpenAI: "function_call": {"name", "arguments"}
        raw = [raw]
    if not isinstance(raw, list):
        return ()
    out = []
    for tc in raw:
        if not isinstance(tc, dict):
            out.append(ToolCall("?", str(tc), ""))
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
        args = fn.get("arguments")
        if args is None:
            args = ""
        elif not isinstance(args, str):  # 有的数据直接放 dict
            args = orjson.dumps(args).decode()
        out.append(ToolCall(str(fn.get("name") or "?"), args, str(tc.get("id") or "")))
    return tuple(out)


def _normalize_turns(row: Any) -> List[Turn]:
    """统一抽取消息列表, 供表格摘要、详情渲染和行函数共用。按行识别: ``messages`` 是
    list → openai_chat, ``conversations`` 是 list → sharegpt, 其余 (含非 dict) 为空。

    openai_chat: content 为 null 的 tool_calls 消息不再显示成 "None", 调用本身进 tool_calls;
    sharegpt: LLaMA-Factory 约定 from=function_call 的 value 是 {"name","arguments"} JSON。
    """
    if not isinstance(row, dict):
        return []
    if isinstance(row.get("messages"), list):
        msgs = row["messages"]
        return [
            Turn(
                role=str(m.get("role", "")),
                content=_as_text(m.get("content")),
                reasoning=_as_text(m.get("reasoning_content") or m.get("reasoning")),
                tool_calls=_parse_tool_calls(m.get("tool_calls") or m.get("function_call")),
                call_id=str(m.get("tool_call_id") or ""),
            )
            for m in msgs
        ]
    if isinstance(row.get("conversations"), list):
        turns = []
        for m in row["conversations"]:
            role, value = str(m.get("from", "")), m.get("value")
            calls: Tuple[ToolCall, ...] = ()
            if role == "function_call":
                try:
                    fc = orjson.loads(value) if isinstance(value, str) else value
                except orjson.JSONDecodeError:
                    fc = None
                if isinstance(fc, dict) and "name" in fc:
                    calls = _parse_tool_calls([fc])
                else:  # 解析不了/没有 name: 原文当参数, 渲染时标红, 别让坏样本混过 calls 筛选
                    raw = value if isinstance(value, str) else orjson.dumps(value).decode()
                    calls = (ToolCall("?", raw, ""),)
                value = None
            turns.append(Turn(role=role, content=_as_text(value), tool_calls=calls))
        return turns
    return []


def _as_text(v: Any) -> str:
    """content 可能是 str/None, 也可能是多模态 list, 统一成字符串。"""
    if v is None:
        return ""
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


def _roles_sig(turns: List[Turn]) -> str:
    """角色序列签名, 如 u→a→t→a; 长了截断。工具返回记 t, 发起调用的仍是 a。"""
    abbr = {
        "system": "sys",
        "user": "u",
        "human": "u",
        "assistant": "a",
        "gpt": "a",
        "tool": "t",
        "function": "t",
        "observation": "t",
        "function_call": "a",  # sharegpt 里发起调用的是模型自己
    }
    seq = [abbr.get(t.role, t.role[:3]) for t in turns]
    if len(seq) > 5:
        seq = seq[:4] + ["…"]
    return "→".join(seq)


def _calls_sig(turns: List[Turn]) -> str:
    """样本里调用过的函数名 (按首次出现顺序去重), 无工具调用为空。

    列名叫 calls 而不是 tools: 顶层 ``tools`` 是 OpenAI/LLaMA-Factory 存工具定义的标准字段,
    派生列撞名会把它从列目录里挤掉。
    """
    seen: List[str] = []
    for turn in turns:
        for c in turn.tool_calls:
            if c.name not in seen:
                seen.append(c.name)
    return ",".join(seen)


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
# 表达式里可直接调用的行函数
# --------------------------------------------------------------------------- #
def _raw(v: Any) -> Any:
    """DictWrapper/ListWrapper → 底层对象 (零拷贝; unwrap 是深拷贝, 每行调用付不起)。"""
    from .core import DictWrapper, ListWrapper

    if isinstance(v, DictWrapper):
        return object.__getattribute__(v, "_data")
    if isinstance(v, ListWrapper):
        return v._data
    return v


def turns(x: Any) -> int:
    """消息条数 (openai_chat 的 messages / sharegpt 的 conversations); 非对话样本为 0。"""
    return len(_normalize_turns(_raw(x)))


def roles(x: Any) -> str:
    """角色序列签名, 如 u→a→t→a (工具返回记 t); 超过 5 段截断。"""
    return _roles_sig(_normalize_turns(_raw(x)))


def first_user(x: Any) -> str:
    """第一条 user/human 消息的全文 (不截断); 没有则为空串。"""
    ts = _normalize_turns(_raw(x))
    return next((t.content for t in ts if t.role in ("user", "human")), "")


def chars(x: Any) -> int:
    """全部消息的字符数: 正文 + 思维链 + 工具调用名与参数。"""
    return sum(t.chars for t in _normalize_turns(_raw(x)))


def calls(x: Any) -> str:
    """调用过的函数名, 逗号分隔, 按首次出现去重; 无工具调用为空串 (故可当布尔用)。"""
    return _calls_sig(_normalize_turns(_raw(x)))


def fulltext(x: Any) -> str:
    """整条记录 (或传入的子结构) 所有标量值拼成的文本, 只取值不含键名。"""
    return row_text(_raw(x))


@lru_cache(maxsize=256)
def compile_search(pattern: str) -> Pattern:
    """搜索词 → 正则: 默认按字面子串 (转义), ``re:`` 前缀走正则; 一律不分大小写。

    search() 与 view 的 ``/`` 必须同源: 同一个 pattern 既用来筛命中子集, 也用来画黄底。
    非法正则原样抛 re.error, 由调用方提示。
    """
    if pattern.startswith("re:"):
        return re.compile(pattern[3:], re.IGNORECASE)
    return re.compile(re.escape(pattern), re.IGNORECASE)


def search(x: Any, pattern: str) -> bool:
    """整条记录里是否含 pattern (语义同 dt view 的 ``/``): 子串不分大小写, ``re:`` 前缀为正则。"""
    return compile_search(pattern).search(row_text(_raw(x))) is not None


HELPERS: Dict[str, Callable[..., Any]] = {
    "turns": turns,
    "roles": roles,
    "first_user": first_user,
    "chars": chars,
    "calls": calls,
    "fulltext": fulltext,
    "search": search,
}

# (名字, 签名, 一句话) —— dt schema 与文档用
HELPER_DOCS: List[Tuple[str, str, str]] = [
    ("turns", "turns(x) -> int", t("number of messages", "消息条数")),
    (
        "roles",
        "roles(x) -> str",
        t("role sequence signature, e.g. u→a→t→a", "角色序列签名, 如 u→a→t→a"),
    ),
    (
        "first_user",
        "first_user(x) -> str",
        t("full text of the first user message", "第一条 user 消息全文"),
    ),
    (
        "chars",
        "chars(x) -> int",
        t(
            "characters of all messages incl. reasoning and tool arguments",
            "全部消息字符数 (含思维链与工具参数)",
        ),
    ),
    (
        "calls",
        "calls(x) -> str",
        t(
            "called function names, comma-joined; empty when none",
            "调用过的函数名, 逗号分隔; 无则空串",
        ),
    ),
    (
        "fulltext",
        "fulltext(x) -> str",
        t("every scalar value of the record joined as text", "整条记录所有标量值拼成的文本"),
    ),
    (
        "search",
        "search(x, pattern) -> bool",
        t(
            "case-insensitive substring over the whole record; re: prefix for regex (same as dt view /)",
            "整条记录不分大小写子串匹配; re: 前缀为正则 (同 dt view 的 /)",
        ),
    ),
]
