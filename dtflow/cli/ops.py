"""
CLI 数据原语命令: filter / select / map / explode / sort / shuffle / group / join。
参数解析 + 管道层 (pipe.open_input / write_output), 逻辑全在 dtflow.ops。
"""

from typing import Optional

from .. import ops
from ..expr import ExprSyntaxError
from .output import die, die_usage, log
from .pipe import load_rows, open_input, write_output


def _guard(action, fn):
    """表达式语法错误 → 用法错误 (退出码 2, 带位置); 其它 ValueError → 用法错误;
    构建阶段就消费数据的命令 (sort/group/join) 的运行时失败 → <action>_failed (退出码 1)。"""
    import typer

    try:
        return fn()
    except ExprSyntaxError as e:
        die_usage(str(e), suggestion=e.caret())
    except ValueError as e:
        die_usage(str(e))
    except typer.Exit:
        raise
    except Exception as e:
        die(f"{action}_failed", f"{type(e).__name__}: {e}", exit_code=1)


def _emit(st, output, action, filename, **stats):
    write_output(st, output, action=action, inputs=[filename], stats=stats or None)


def filter_cmd(
    filename: str, expr: str, output: Optional[str] = None, strict: bool = False
) -> None:
    """
    保留表达式为真的行。

    Examples:
        dt filter data.jsonl "x.score > 0.5 and 'wiki' in x.meta.source"
        dt filter data.jsonl "len(x.messages) >= 2 and x.messages[-1].role == 'assistant'"
        dt filter data.jsonl "any('退款' in m.content for m in x.messages)" -o hit.jsonl
        cat a.jsonl | dt filter - "x.ok" | dt head -
    """
    st = _guard("filter", lambda: ops.filter_rows(open_input(filename), expr, strict))
    _emit(st, output, "filter", filename)


def select_cmd(
    filename: str, spec: str, output: Optional[str] = None, strict: bool = False
) -> None:
    """
    投影 / 重命名 / 派生字段: SPEC 形如 ``id,text,n=len(x.messages),src=x.meta.source``。

    无 = 的项是字面顶层字段名 (缺失则省略); name=表达式 是派生; 重命名即 new=x.old。
    输出键序 = SPEC 序。一进一出: 派生项求值失败置 null 并汇总 (--strict 则报错)。

    Examples:
        dt select data.jsonl "id,text"
        dt select data.jsonl "id,n=len(x.messages),last=x.messages[-1].content"
        dt select data.jsonl "prompt=x.instruction,answer=x.output" -o qa.jsonl
    """
    st = _guard("select", lambda: ops.select_rows(open_input(filename), spec, strict))
    _emit(st, output, "select", filename)


def map_cmd(filename: str, code: str, output: Optional[str] = None, strict: bool = False) -> None:
    """
    对每行执行 Python 语句 (原地修改 x)。一进一出: 语句失败的行原样保留并汇总 (--strict 则报错)。

    Examples:
        dt map data.jsonl "x.text = x.text.strip()"
        dt map data.jsonl "x.n = len(x.messages); del x.debug"
        dt map data.jsonl "x.messages.append({'role': 'assistant', 'content': x.answer})"
    """
    st = _guard("map", lambda: ops.map_rows(open_input(filename), code, strict))
    _emit(st, output, "map", filename)


def explode_cmd(
    filename: str,
    field: str,
    output: Optional[str] = None,
    as_name: Optional[str] = None,
    index_as: Optional[str] = None,
) -> None:
    """
    把 list 字段展开为多行 (其余字段复制); 非 list / 缺失的行原样透传。

    Examples:
        dt explode data.jsonl --field messages                # 每条消息一行
        dt explode data.jsonl --field tags --as tag --index-as i
    """
    from .common import field_path_arg

    field_path_arg(field, "--field")
    st = ops.explode_rows(open_input(filename), field, as_name, index_as)
    _emit(st, output, "explode", filename)


def sort_cmd(
    filename: str, by: str, output: Optional[str] = None, desc: bool = False, strict: bool = False
) -> None:
    """
    按表达式排序 (全量加载)。键求值失败的行排最后 (--strict 则报错)。

    Examples:
        dt sort data.jsonl --by x.score --desc
        dt sort data.jsonl --by "len(x.messages)"
        dt sort data.jsonl --by "(x.source, -x.score)"
    """
    st = open_input(filename)
    if st._total:
        log(f"📊 全量加载 {st._total} 行用于排序")
    st = _guard("sort", lambda: ops.sort_rows(st, by, desc, strict))
    _emit(st, output, "sort", filename)


def shuffle_cmd(filename: str, output: Optional[str] = None, seed: Optional[int] = None) -> None:
    """
    全量打乱 (均匀随机排列必须先知道全集, 流式做不到)。

    Examples:
        dt shuffle data.jsonl --seed 42 -o shuffled.jsonl
    """
    st = ops.shuffle_rows(open_input(filename), seed)
    _emit(st, output, "shuffle", filename, seed=seed)


def group_cmd(
    filename: str,
    by: str,
    output: Optional[str] = None,
    agg: Optional[str] = None,
    strict: bool = False,
) -> None:
    """
    按表达式分组。无 --agg 流式计数 ({"key","count"} 按 count 降序);
    有 --agg 按组收集, 表达式里可用 g (组内行列表) / key / n / mean / median。

    Examples:
        dt group data.jsonl --by x.meta.source
        dt group data.jsonl --by "len(x.messages)"
        dt group data.jsonl --by x.label --agg "avg_len=mean(len(r.text) for r in g),ids=[r.id for r in g][:3]"
        dt group data.jsonl --by x.label | dt sort - --by x.count --desc | dt head - 5
    """
    st = _guard("group", lambda: ops.group_rows(open_input(filename), by, agg, strict))
    _emit(st, output, "group", filename)


def join_cmd(
    left: str,
    right: str,
    output: Optional[str] = None,
    on: Optional[str] = None,
    left_on: Optional[str] = None,
    right_on: Optional[str] = None,
    inner: bool = False,
    prefix: Optional[str] = None,
) -> None:
    """
    键连接: 左表流式, 右表入内存 (右表同键多行只取首条)。默认左连接, --inner 丢弃未命中。
    合并时左表字段优先; --prefix 则右表全部字段加前缀。

    Examples:
        dt join data.jsonl meta.jsonl --on x.id
        dt join data.jsonl meta.jsonl --left-on x.uid --right-on x.user_id --prefix m_
        dt join data.jsonl labels.jsonl --on x.id --inner -o labeled.jsonl
    """
    if not (on or (left_on and right_on)):
        die_usage("需要 --on EXPR, 或同时给 --left-on 与 --right-on")
    if on and (left_on or right_on):
        die_usage("--on 与 --left-on/--right-on 只能二选一")
    if left == "-" and right == "-":
        die_usage("stdin (-) 只能出现一次")
    right_rows = load_rows(right)
    result = _guard(
        "join",
        lambda: ops.join_rows(open_input(left), right_rows, on, left_on, right_on, inner, prefix),
    )
    st, dup = result
    if dup:
        log(f"[yellow]⚠ 右表有 {dup} 行重复键, 只取首条[/yellow]")
    _emit(st, output, "join", left, right=right, right_rows=len(right_rows), right_dup_keys=dup)
