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

import ast
import builtins
import json
import math
import re
from functools import lru_cache
from typing import Any, Callable, Dict, FrozenSet, Iterable, Optional

from .core import DictWrapper, unwrap
from .i18n import t
from .utils.field_path import get_field_with_spec

Row = Dict[str, Any]
ExtraFn = Callable[[Row], Dict[str, Any]]


def _get(obj: Any, spec: str, default: Any = None) -> Any:
    """旧字段路径 DSL 的入口: get(x, "messages[*].role:unique")"""
    return get_field_with_spec(unwrap(obj), spec, default)


_BASE: Dict[str, Any] = {"re": re, "json": json, "math": math, "get": _get}
_BUILTIN_NAMES = frozenset(dir(builtins))
_ALWAYS = frozenset(_BASE) | {"x"}


class ExprSyntaxError(ValueError):
    """表达式语法错误。继承 ValueError: view 层现有的 except ValueError 直接兼容。"""

    def __init__(self, expr: str, msg: str, offset: int):
        self.expr = expr
        self.msg = msg
        self.offset = max(offset, 1)
        super().__init__(t(f"Expression syntax error: {msg}", f"表达式语法错误: {msg}"))

    def caret(self) -> str:
        """表达式 + 指向出错位置的 ^, 给 stderr 提示用"""
        return f"{self.expr}\n{' ' * (self.offset - 1)}^"


def _free_names(tree: ast.AST) -> Dict[str, int]:
    """表达式里未在表达式内部绑定的名字 → 首次出现的列偏移 (1-based)。"""
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.Lambda):
            a = node.args
            bound.update(p.arg for p in [*a.posonlyargs, *a.args, *a.kwonlyargs])
            if a.vararg:
                bound.add(a.vararg.arg)
            if a.kwarg:
                bound.add(a.kwarg.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    free: Dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in bound and node.id not in free:
                free[node.id] = node.col_offset + 1
    return free


@lru_cache(maxsize=256)
def _compile(expr: str, mode: str, allowed: FrozenSet[str] = frozenset()):
    """编译 + 名字检查: 除 x / re / json / math / get / 内置名 / allowed 外的裸名字直接报错,
    否则 ``score > 0.5`` 这种漏写 x. 的表达式每行 NameError 却退出码 0, 静默得到 0 命中。"""
    if not expr.strip():
        raise ExprSyntaxError(expr, t("empty expression", "表达式为空"), 1)
    try:
        tree = ast.parse(expr, "<expr>", mode)
    except SyntaxError as e:
        offset = e.offset or 0
        if offset <= 0:  # 表达式在末尾不完整时 Python 报 0, 指到末尾更有用
            offset = len(expr) + 1
        raise ExprSyntaxError(expr, e.msg or "invalid syntax", offset) from None
    ok = _ALWAYS | _BUILTIN_NAMES | allowed
    for name, col in _free_names(tree).items():
        if name not in ok:
            raise ExprSyntaxError(
                expr,
                t(
                    f"unknown name {name!r}: write fields as x.{name}",
                    f"未知名字 {name!r}: 字段请写 x.{name}",
                ),
                col,
            )
    # 整个表达式就是一个内置函数名 (id / type / input …): 十有八九是想写字段
    body = tree.body if mode == "eval" else None
    if (
        isinstance(body, ast.Name)
        and body.id in _BUILTIN_NAMES
        and body.id not in ok - _BUILTIN_NAMES
    ):
        raise ExprSyntaxError(
            expr,
            t(
                f"{body.id!r} is a Python builtin: write fields as x.{body.id}",
                f"{body.id!r} 是 Python 内置名: 字段请写 x.{body.id}",
            ),
            1,
        )
    return compile(tree, "<expr>", mode)


def check_syntax(expr: str, mode: str = "eval", allowed: Iterable[str] = ()) -> None:
    """只做语法与名字检查 (pipeline 校验期提前报错), 失败抛 ExprSyntaxError"""
    _compile(expr, mode, frozenset(allowed))


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
    code = _compile(expr.strip(), "eval", extra_names or frozenset())
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
    code = _compile(expr.strip(), "eval", extra_names or frozenset())
    use_extra = _pick_extra(code, extra, extra_names)

    def predicate(row: Row) -> bool:
        return bool(eval(code, _namespace(row, use_extra)))

    return predicate


def compile_in(expr: str, allowed: Iterable[str] = ()) -> Callable[[Dict[str, Any]], Any]:
    """表达式 → 在调用方给定的命名空间里求值 (group --agg 用: 名字是 g/key/n, 不是 x)。"""
    code = _compile(expr.strip(), "eval", frozenset(allowed))

    def fn(names: Dict[str, Any]) -> Any:
        ns = dict(_BASE)
        ns.update(names)
        return eval(code, ns)

    return fn


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
