"""
统一表达式引擎: CLI/pipeline/view 里所有 --where / select / map 的求值都走这里。

表达式就是 Python, 当前行叫 ``x`` (DictWrapper, 属性访问, 读写直落原 dict):

    x.score > 0.5 and 'wiki' in x.meta.source
    len(x.messages) >= 2 and x.messages[-1].role == 'assistant'
    any('退款' in m.content for m in x.messages)

命名空间另有 re / json / math, 以及 ``get(x, "messages[*].role:join")`` 通向旧的字段路径 DSL。
不做沙箱: 这是用户自己 shell 里跑的本地工具, dt transform 早就在执行 .dt/*.py 了。

本模块不 import typer/output: view 的 fork 子进程和 pipeline 都要用。
多进程约定: 只传表达式字符串, 子进程内再 compile (lru_cache 保证每个进程只编译一次)。
运行时错误 (缺字段 AttributeError / None>0.5 TypeError / IndexError) 原样抛出,
"判 False 还是报错" 由调用方的 on_error 决定, 这里保持纯函数。
"""

import json
import math
import re
from functools import lru_cache
from typing import Any, Callable, Dict, FrozenSet, Optional

from .core import DictWrapper, unwrap
from .utils.field_path import get_field_with_spec

Row = Dict[str, Any]
ExtraFn = Callable[[Row], Dict[str, Any]]


def _get(obj: Any, spec: str, default: Any = None) -> Any:
    """旧字段路径 DSL 的入口: get(x, "messages[*].role:unique")"""
    return get_field_with_spec(unwrap(obj), spec, default)


_BASE: Dict[str, Any] = {"re": re, "json": json, "math": math, "get": _get}


class ExprSyntaxError(ValueError):
    """表达式语法错误。继承 ValueError: view 层现有的 except ValueError 直接兼容。"""

    def __init__(self, expr: str, msg: str, offset: int):
        self.expr = expr
        self.msg = msg
        self.offset = max(offset, 1)
        super().__init__(f"表达式语法错误: {msg}")

    def caret(self) -> str:
        """表达式 + 指向出错位置的 ^, 给 stderr 提示用"""
        return f"{self.expr}\n{' ' * (self.offset - 1)}^"


@lru_cache(maxsize=256)
def _compile(expr: str, mode: str):
    if not expr.strip():
        raise ExprSyntaxError(expr, "表达式为空", 1)
    try:
        return compile(expr, "<expr>", mode)
    except SyntaxError as e:
        raise ExprSyntaxError(expr, e.msg or "invalid syntax", e.offset or 1) from None


def check_syntax(expr: str, mode: str = "eval") -> None:
    """只做语法检查 (pipeline 校验期提前报错), 失败抛 ExprSyntaxError"""
    _compile(expr, mode)


def _namespace(row: Row, extra: Optional[ExtraFn]) -> Dict[str, Any]:
    # 单个 dict 同时作 globals 和 locals: 3.10/3.11 的推导式作用域只看 globals
    ns = dict(_BASE)
    ns["x"] = DictWrapper(row)
    if extra is not None:
        ns.update(extra(row))
    return ns


def _pick_extra(code, extra: Optional[ExtraFn], extra_names: Optional[FrozenSet[str]]):
    """extra (如 view 派生列) 只在表达式真的引用到那些名字时才每行计算"""
    if extra is None:
        return None
    if extra_names is not None and not (set(code.co_names) & extra_names):
        return None
    return extra


def compile_value(
    expr: str,
    extra: Optional[ExtraFn] = None,
    extra_names: Optional[FrozenSet[str]] = None,
) -> Callable[[Row], Any]:
    """表达式 → 取值函数 (sort/group --by、select 的派生列)。返回值已 unwrap。"""
    code = _compile(expr.strip(), "eval")
    use_extra = _pick_extra(code, extra, extra_names)

    def value_fn(row: Row) -> Any:
        return unwrap(eval(code, _namespace(row, use_extra)))

    return value_fn


def compile_where(
    expr: str,
    extra: Optional[ExtraFn] = None,
    extra_names: Optional[FrozenSet[str]] = None,
) -> Callable[[Row], bool]:
    """表达式 → 谓词。extra(row) 可注入额外名字 (view 的 turns/chars 等派生列)。"""
    code = _compile(expr.strip(), "eval")
    use_extra = _pick_extra(code, extra, extra_names)

    def predicate(row: Row) -> bool:
        return bool(eval(code, _namespace(row, use_extra)))

    return predicate


def compile_map(code_str: str) -> Callable[[Row], Row]:
    """
    语句 → 行变换函数: exec 后返回 x (原地修改)。

        x.text = x.text.strip(); x.n = len(x.messages)
        del x.debug

    只做语句模式: 要产出全新结构用 select, 一个命令干一件事。
    """
    code = _compile(code_str.strip(), "exec")

    def map_fn(row: Row) -> Row:
        ns = _namespace(row, None)
        exec(code, ns)
        return unwrap(ns["x"])

    return map_fn
