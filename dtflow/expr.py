"""
统一表达式引擎: CLI/pipeline/view 里所有 --where / select / map 的求值都走这里。

表达式就是 Python, 当前行叫 ``x`` (DictWrapper, 属性访问, 读写直落原 dict):

    x.score > 0.5 and 'wiki' in x.meta.source
    len(x.messages) >= 2 and x.messages[-1].role == 'assistant'
    any('退款' in m.content for m in x.messages)

命名空间另有 re / json / math, ``get(x, "messages[*].role:join")`` 通向旧的字段路径 DSL,
以及 rowfn 的行函数 turns(x) / roles(x) / first_user(x) / chars(x) / calls(x) / fulltext(x) /
search(x, pat) —— 与 dt view 表头上的派生列同一实现, 于是 view 里筛出来的条件能原样交给 dt filter。
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
from typing import Any, Callable, Dict, FrozenSet, Iterable

from .core import DictWrapper, unwrap
from .i18n import t
from .rowfn import HELPERS, compile_search
from .utils.field_path import get_field_with_spec

Row = Dict[str, Any]


def _get(obj: Any, spec: str, default: Any = None) -> Any:
    """旧字段路径 DSL 的入口: get(x, "messages[*].role:unique")"""
    return get_field_with_spec(unwrap(obj), spec, default)


_BASE: Dict[str, Any] = {"re": re, "json": json, "math": math, "get": _get, **HELPERS}
_BUILTIN_NAMES = frozenset(dir(builtins))
_ALWAYS = frozenset(_BASE) | {"x"}
_HELPER_NAMES = frozenset(HELPERS)


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


def _check_helper_misuse(tree: ast.AST, expr: str) -> None:
    """裸用行函数名 (``turns >= 6``, 老 view 语法) 直接报错并提示 ``turns(x)``。

    不拦的话它能编译通过, 每行拿函数对象和 6 比较抛 TypeError: CLI 报 N 行求值失败,
    view 静默 0 命中 —— 都比一条明确的语法错误糟。合法的裸引用只有作为被调用者
    (``turns(x)``) 与作为别的调用的参数 (``sorted(g, key=turns)`` / ``map(turns, g)``)。
    """
    ok_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            ok_ids.add(id(node.func))
            ok_ids.update(id(a) for a in node.args)
        elif isinstance(node, ast.keyword):
            ok_ids.add(id(node.value))
    for node in ast.walk(tree):
        # search(x, 're:[') 这种字面量正则写错, 每行 re.error 会被当"求值失败"静默成 0 命中
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "search"
            and len(node.args) == 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            try:
                compile_search(node.args[1].value)
            except re.error as e:
                raise ExprSyntaxError(
                    expr,
                    t(f"invalid regex in search(): {e}", f"search() 的正则无效: {e}"),
                    node.args[1].col_offset + 1,
                ) from None
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in _HELPER_NAMES
            and id(node) not in ok_ids
        ):
            raise ExprSyntaxError(
                expr,
                t(
                    f"{node.id} is a row function: write {node.id}(x)",
                    f"{node.id} 是行函数, 请写 {node.id}(x)",
                ),
                node.col_offset + 1,
            )


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
    _check_helper_misuse(tree, expr)
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


def _namespace(row: Row) -> Dict[str, Any]:
    # 单个 dict 同时作 globals 和 locals: 3.10/3.11 的推导式作用域只看 globals
    ns = dict(_BASE)
    ns["x"] = DictWrapper(row)
    return ns


def compile_value(expr: str) -> Callable[[Row], Any]:
    """表达式 → 取值函数 (sort/group --by、select 的派生列)。返回值已 unwrap。"""
    code = _compile(expr.strip(), "eval")

    def value_fn(row: Row) -> Any:
        return unwrap(eval(code, _namespace(row)))

    return value_fn


def compile_where(expr: str) -> Callable[[Row], bool]:
    """表达式 → 谓词。"""
    code = _compile(expr.strip(), "eval")

    def predicate(row: Row) -> bool:
        return bool(eval(code, _namespace(row)))

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
        ns = _namespace(row)
        exec(code, ns)
        return unwrap(ns["x"])

    return map_fn


# --------------------------------------------------------------------------- #
# 字段改名翻译: dt view 里列被重命名后, 用户按看到的新名写条件, 存储/扫描/复制命令用磁盘原名
# --------------------------------------------------------------------------- #
_FIELD_PATH_HEAD = re.compile(r"^([^.\[]+)(.*)$", re.S)
_SCOPES = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)


def _binds_x(target: ast.AST) -> bool:
    return any(isinstance(n, ast.Name) and n.id == "x" for n in ast.walk(target))


def _is_x(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "x" and isinstance(node.ctx, ast.Load)


def _str_const(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def rename_fields(expr: str, mapping: Dict[str, str]) -> str:
    """把表达式里对当前行**顶层**字段的引用按 mapping 改名, 其余一字不动。

    认的写法: ``x.a`` / ``x['a']`` / ``x.get('a', …)`` / ``'a' in x`` / ``get(x, 'a.b…')``。
    所有替换同时生效 (交换 a↔b 不会互相覆盖)。按源码位置替换而不是 ast.unparse, 用户的
    空格与引号保留。推导式/lambda 里把 x 重新绑定的部分不动 (那个 x 不是当前行)。
    语法错误原样返回, 交给随后的编译按用户原文报位置。
    """
    if not mapping:
        return expr
    try:
        tree = ast.parse(expr, "<expr>", "eval")
    except SyntaxError:
        return expr
    data = expr.encode("utf-8")  # ast 的列偏移是 UTF-8 字节
    line_starts = [0] + [i + 1 for i, b in enumerate(data) if b == 0x0A]
    edits = []  # (起, 止, 新文本)

    def span(node: ast.AST):
        return (
            line_starts[node.lineno - 1] + node.col_offset,
            line_starts[node.end_lineno - 1] + node.end_col_offset,
        )

    def put_str(node: ast.Constant, new: str) -> None:
        a, b = span(node)
        old = data[a:b].decode("utf-8")
        q = old[:1]
        if q in ("'", '"') and q not in new and "\\" not in new and "\n" not in new:
            edits.append((a, b, q + new + q))
        else:
            edits.append((a, b, repr(new)))

    def attr_form(new: str) -> str:
        import keyword

        return f"x.{new}" if new.isidentifier() and not keyword.iskeyword(new) else f"x[{new!r}]"

    def visit(node: ast.AST, shadowed: bool) -> None:
        if isinstance(node, ast.Lambda):
            a = node.args
            params = [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]
            for d in [*a.defaults, *(d for d in a.kw_defaults if d is not None)]:
                visit(d, shadowed)
            visit(node.body, shadowed or any(p is not None and p.arg == "x" for p in params))
            return
        if isinstance(node, _SCOPES):
            sh = shadowed
            for i, gen in enumerate(node.generators):
                visit(gen.iter, shadowed if i == 0 else sh)
                sh = sh or _binds_x(gen.target)
                for cond in gen.ifs:
                    visit(cond, sh)
            for part in (node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,):
                visit(part, sh)
            return
        if not shadowed:
            if isinstance(node, ast.Attribute) and _is_x(node.value) and node.attr in mapping:
                a, b = span(node)
                edits.append((a, b, attr_form(mapping[node.attr])))
                return
            if (
                isinstance(node, ast.Subscript)
                and _is_x(node.value)
                and _str_const(node.slice)
                and node.slice.value in mapping
            ):
                put_str(node.slice, mapping[node.slice.value])
            elif isinstance(node, ast.Call) and node.args and _str_const(node.args[0]):
                f = node.func
                if (
                    isinstance(f, ast.Attribute)
                    and f.attr == "get"
                    and _is_x(f.value)
                    and node.args[0].value in mapping
                ):
                    put_str(node.args[0], mapping[node.args[0].value])
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "get"
                and len(node.args) >= 2
                and _is_x(node.args[0])
                and _str_const(node.args[1])
            ):
                m = _FIELD_PATH_HEAD.match(node.args[1].value)
                if m and m.group(1) in mapping:
                    put_str(node.args[1], mapping[m.group(1)] + m.group(2))
            elif isinstance(node, ast.Compare):
                left = node.left
                for op, right in zip(node.ops, node.comparators, strict=True):
                    if (
                        isinstance(op, (ast.In, ast.NotIn))
                        and _is_x(right)
                        and _str_const(left)
                        and left.value in mapping
                    ):
                        put_str(left, mapping[left.value])
                    left = right
        for child in ast.iter_child_nodes(node):
            visit(child, shadowed)

    visit(tree.body, False)
    if not edits:
        return expr
    out = data
    for a, b, new in sorted(set(edits), reverse=True):
        out = out[:a] + new.encode("utf-8") + out[b:]
    return out.decode("utf-8")
