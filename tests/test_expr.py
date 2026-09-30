"""统一表达式引擎 dtflow/expr.py 的测试"""

import multiprocessing
import re

import pytest

from dtflow import rowfn
from dtflow.core import DictWrapper
from dtflow.expr import (
    ExprSyntaxError,
    check_syntax,
    compile_in,
    compile_map,
    compile_value,
    compile_where,
)
from dtflow.rowfn import HELPERS

ROW = {
    "id": 7,
    "score": 0.8,
    "text": "机器学习 入门",
    "meta": {"source": "wiki-zh", "tags": ["a", "b"]},
    "messages": [
        {"role": "user", "content": "退款怎么办"},
        {"role": "assistant", "content": "请联系客服"},
    ],
}


class TestWhere:
    @pytest.mark.parametrize(
        "expr,expected",
        [
            ("x.score > 0.5", True),
            ("x.score > 0.9", False),
            ("x.id == 7 and 'wiki' in x.meta.source", True),
            ("len(x.messages) >= 2 and x.messages[-1].role == 'assistant'", True),
            ("any('退款' in m.content for m in x.messages)", True),
            ("[m.role for m in x.messages] == ['user', 'assistant']", True),
            ("'b' in x.meta.tags", True),
            ("re.search(r'\\d', x.text) is None", True),
            ("get(x, 'messages[*].role:join') == 'user|assistant'", True),
            ("x['meta']['source'].startswith('wiki')", True),
            ("math.floor(x.score * 10) == 8", True),
        ],
    )
    def test_predicates(self, expr, expected):
        assert compile_where(expr)(ROW) is expected

    def test_truthiness(self):
        assert compile_where("x.text")(ROW) is True
        assert compile_where("x.meta.tags[5:]")(ROW) is False

    def test_missing_field_raises(self):
        with pytest.raises(AttributeError):
            compile_where("x.scroe > 0.5")(ROW)

    def test_none_comparison_raises(self):
        with pytest.raises(TypeError):
            compile_where("x.nothing > 1")({"nothing": None})

    def test_does_not_mutate_row(self):
        row = {"a": [1]}
        compile_where("x.a + [2]")(row)
        assert row == {"a": [1]}


class TestSyntaxErrors:
    def test_syntax_error_position(self):
        with pytest.raises(ExprSyntaxError) as ei:
            compile_where("x.score > and 1")
        err = ei.value
        assert isinstance(err, ValueError)
        assert err.expr == "x.score > and 1"
        lines = err.caret().splitlines()
        assert lines[0] == "x.score > and 1"
        assert lines[1].index("^") == err.offset - 1

    def test_empty(self):
        with pytest.raises(ExprSyntaxError):
            compile_where("   ")

    def test_statement_in_where(self):
        with pytest.raises(ExprSyntaxError):
            compile_where("x.a = 1")

    def test_check_syntax(self):
        check_syntax("x.a == 1")
        check_syntax("x.a = 1", mode="exec")
        with pytest.raises(ExprSyntaxError):
            check_syntax("x.a = 1")


class TestValue:
    def test_value(self):
        assert compile_value("len(x.messages)")(ROW) == 2
        assert compile_value("(x.id, -x.score)")(ROW) == (7, -0.8)

    def test_value_unwrapped(self):
        v = compile_value("x.messages")(ROW)
        assert type(v) is list and v == ROW["messages"]
        assert type(compile_value("x.meta")(ROW)) is dict


class TestMap:
    def test_in_place_statements(self):
        row = {"text": "  hi  ", "messages": [{"role": "user"}], "debug": 1}
        out = compile_map("x.text = x.text.strip(); x.n = len(x.messages); del x.debug")(row)
        assert out == {"text": "hi", "messages": [{"role": "user"}], "n": 1}

    def test_multiline_and_list_mutation(self):
        row = {"messages": [{"role": "user"}]}
        out = compile_map("x.messages.append({'role': 'assistant'})\nx.turns = len(x.messages)")(
            row
        )
        assert out["turns"] == 2 and out["messages"][-1] == {"role": "assistant"}
        assert type(out["messages"]) is list

    def test_syntax_error(self):
        with pytest.raises(ExprSyntaxError):
            compile_map("x.a = = 1")


class TestNames:
    def test_unknown_bare_name_is_syntax_error(self):
        # 漏写 x. 的裸字段名不能每行 NameError 却退出码 0
        with pytest.raises(ExprSyntaxError, match="x.score"):
            compile_where("score > 0.5")
        with pytest.raises(ExprSyntaxError, match="x.id"):
            compile_value("id")  # 整个表达式是内置函数名
        assert compile_value("len(x.messages)")(ROW) == 2  # 内置函数照常
        assert compile_where("[m for m in x.messages if m.role == 'user']")(ROW)  # 推导式变量
        assert compile_where("(lambda y: y > 1)(len(x.messages))")(ROW)

    def test_incomplete_expr_caret_at_end(self):
        with pytest.raises(ExprSyntaxError) as ei:
            compile_where("x.a >")
        assert ei.value.offset == len("x.a >") + 1


SHAREGPT_ROW = {
    "id": 1,
    "conversations": [
        {"from": "human", "value": "查天气 Beijing"},
        {"from": "function_call", "value": '{"name": "get_weather", "arguments": "{}"}'},
        {"from": "observation", "value": "22"},
        {"from": "gpt", "value": "22 度"},
    ],
}


class TestRowHelpers:
    """行函数与 dt view 的派生列同源: 见 dtflow/rowfn.py。"""

    def test_helpers_on_dict_and_wrapper_agree_and_do_not_copy(self):
        w = DictWrapper(ROW)
        for name in ("turns", "roles", "first_user", "chars", "calls", "fulltext"):
            assert HELPERS[name](ROW) == HELPERS[name](w), name
        assert rowfn._raw(w) is ROW and rowfn._raw(w.messages) is ROW["messages"]

    def test_chat_helpers(self):
        assert compile_value("turns(x)")(ROW) == 2
        assert compile_value("roles(x)")(ROW) == "u→a"
        assert compile_value("first_user(x)")(ROW) == "退款怎么办"
        assert compile_value("chars(x)")(ROW) == len("退款怎么办") + len("请联系客服")
        assert compile_value("calls(x)")(ROW) == ""
        assert compile_where("turns(x) >= 2 and '退款' in first_user(x)")(ROW)

    def test_autodetects_sharegpt_and_non_chat(self):
        assert compile_value("turns(x)")(SHAREGPT_ROW) == 4
        assert compile_value("roles(x)")(SHAREGPT_ROW) == "u→a→t→a"
        assert compile_value("calls(x)")(SHAREGPT_ROW) == "get_weather"
        assert compile_where("'get_weather' in calls(x)")(SHAREGPT_ROW)
        plain = {"text": "hello"}
        assert compile_value("(turns(x), roles(x), first_user(x), chars(x), calls(x))")(plain) == (
            0,
            "",
            "",
            0,
            "",
        )

    def test_search_and_fulltext(self):
        assert compile_where("search(x, '退款')")(ROW)
        assert compile_where("search(x, 'WIKI')")(ROW)  # 不分大小写, 搜所有标量值
        assert not compile_where("search(x, 'messages')")(ROW)  # 不含键名
        assert compile_where(r"search(x, r're:wiki-\w+')")(ROW)
        assert not compile_where("search(x, 're:^wiki$')")(ROW)
        assert compile_where("search(x.messages, '客服') and not search(x.meta, '客服')")(ROW)
        assert "退款怎么办" in compile_value("fulltext(x)")(ROW)
        assert rowfn.compile_search("a.b") is rowfn.compile_search("a.b")  # 缓存
        # 字面量正则写错在编译期就报 (否则每行 re.error 被当求值失败, 静默 0 命中)
        with pytest.raises(ExprSyntaxError, match="search"):
            compile_where("search(x, 're:(')")
        with pytest.raises(re.error):  # 非字面量只能运行期发现
            compile_where("search(x, 're:' + '(')")(ROW)

    def test_bare_helper_name_is_syntax_error_with_hint(self):
        # 老 view 语法 turns>=6: 不能编译通过后每行 TypeError (CLI 报失败, view 静默 0 命中)
        with pytest.raises(ExprSyntaxError, match=r"turns\(x\)") as ei:
            compile_where("turns >= 2")
        assert ei.value.offset == 1
        with pytest.raises(ExprSyntaxError, match=r"first_user\(x\)"):
            compile_where("'退款' in first_user")
        with pytest.raises(ExprSyntaxError, match=r"chars\(x\)"):
            compile_value("len(x.messages) + chars")
        # 合法的裸引用: 被调用 / 当高阶函数参数
        assert compile_value("sorted([x], key=turns)")(ROW) == [ROW]
        assert compile_value("list(map(turns, [x]))")(ROW) == [2]

    def test_helpers_available_in_compile_in(self):
        fn = compile_in("mean(turns(r) for r in g)", allowed=("g", "mean"))
        assert (
            fn({"g": [DictWrapper(ROW), DictWrapper(SHAREGPT_ROW)], "mean": lambda it: sum(it) / 2})
            == 3
        )

    def test_schema_lists_helpers(self):
        assert [d[0] for d in rowfn.HELPER_DOCS] == list(HELPERS)


def _eval_in_child(args):
    expr, row = args
    return compile_where(expr)(row)


class TestMultiprocess:
    def test_compile_inside_fork_child(self):
        ctx = multiprocessing.get_context("fork")
        with ctx.Pool(2) as pool:
            got = pool.map(_eval_in_child, [("x.id == 7", ROW), ("x.id == 8", ROW)])
        assert got == [True, False]


class TestRenameFields:
    """dt view 列改名后按新名写条件: 翻译回磁盘原名 (以及反向用于显示)。"""

    def test_forms_and_formatting_kept(self):
        from dtflow.expr import rename_fields

        m = {"quality": "score"}
        assert rename_fields("x.quality  >  0.5", m) == "x.score  >  0.5"
        assert rename_fields('x["quality"] > 1', m) == 'x["score"] > 1'
        assert rename_fields("x.get('quality', 0) > 1", m) == "x.get('score', 0) > 1"
        assert rename_fields("'quality' in x", m) == "'score' in x"
        assert rename_fields("get(x, 'quality.a[0]') == 1", m) == "get(x, 'score.a[0]') == 1"
        # 嵌套字段与非 x 的同名属性不动
        assert rename_fields("x.meta.quality and m.quality", m) == "x.meta.quality and m.quality"

    def test_swap_and_chain_are_simultaneous(self):
        from dtflow.expr import rename_fields

        assert rename_fields("x.a < x.b", {"a": "b", "b": "a"}) == "x.b < x.a"
        assert rename_fields("x.c + x.b", {"c": "b", "b": "a"}) == "x.b + x.a"

    def test_shadowed_x_untouched(self):
        from dtflow.expr import rename_fields

        m = {"role": "kind", "msgs": "messages"}
        e = "any(x.role == 'u' for x in x.msgs)"
        assert rename_fields(e, m) == "any(x.role == 'u' for x in x.messages)"
        assert rename_fields("(lambda x: x.role)(x.msgs)", m) == "(lambda x: x.role)(x.messages)"
        assert rename_fields("[m.role for m in x.msgs if x.role]", m) == (
            "[m.role for m in x.messages if x.kind]"
        )

    def test_non_identifier_target_and_unicode(self):
        from dtflow.expr import rename_fields

        assert rename_fields("x.q > 1", {"q": "my score"}) == "x['my score'] > 1"
        assert rename_fields("'中文' in x.标题 and x.标题", {"标题": "title"}) == (
            "'中文' in x.title and x.title"
        )

    def test_syntax_error_returned_unchanged(self):
        from dtflow.expr import rename_fields

        assert rename_fields("x.a >", {"a": "b"}) == "x.a >"
        assert rename_fields("x.a", {}) == "x.a"
