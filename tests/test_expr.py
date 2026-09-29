"""统一表达式引擎 dtflow/expr.py 的测试"""

import multiprocessing

import pytest

from dtflow.expr import (
    ExprSyntaxError,
    check_syntax,
    compile_map,
    compile_value,
    compile_where,
)

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


class TestExtra:
    def test_extra_names_used_lazily(self):
        calls = []

        def extra(row):
            calls.append(1)
            return {"turns": len(row["messages"])}

        names = frozenset({"turns", "chars"})
        pred = compile_where("turns >= 2", extra=extra, extra_names=names)
        assert pred(ROW) is True
        assert calls == [1]
        pred2 = compile_where("x.id == 7", extra=extra, extra_names=names)
        assert pred2(ROW) is True
        assert calls == [1], "未引用派生名时不应计算 extra"

    def test_extra_without_names_always_called(self):
        pred = compile_where("turns == 2", extra=lambda r: {"turns": 2})
        assert pred(ROW) is True


def _eval_in_child(args):
    expr, row = args
    return compile_where(expr)(row)


class TestMultiprocess:
    def test_compile_inside_fork_child(self):
        ctx = multiprocessing.get_context("fork")
        with ctx.Pool(2) as pool:
            got = pool.map(_eval_in_child, [("x.id == 7", ROW), ("x.id == 8", ROW)])
        assert got == [True, False]
