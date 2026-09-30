"""数据原语: dtflow.ops (库层) + dt filter/select/map/explode/sort/shuffle/group/join (CLI)。"""

import json

import orjson
import pytest
import typer

from dtflow import ops
from dtflow.cli import pipe
from dtflow.cli.ops import (
    explode_cmd,
    filter_cmd,
    group_cmd,
    join_cmd,
    map_cmd,
    select_cmd,
    shuffle_cmd,
    sort_cmd,
)
from dtflow.cli.stats import stats
from dtflow.streaming import StreamingTransformer

ROWS = [
    {
        "id": 1,
        "text": " a ",
        "score": 0.5,
        "tags": ["x", "y"],
        "m": [{"r": "u"}, {"r": "a"}],
        "s": "wiki",
    },
    {"id": 2, "text": "b", "score": 0.9, "tags": ["y"], "m": [{"r": "u"}], "s": "web"},
    {"id": 3, "text": "c", "score": 0.1, "tags": [], "m": [{"r": "u"}], "s": "wiki"},
    {"id": 4, "text": "d", "tags": None, "m": [], "s": "wiki"},  # 无 score
]


def _st(rows=ROWS):
    return StreamingTransformer(iter([dict(r) for r in rows]), None, total=len(rows))


@pytest.fixture
def data_file(tmp_path):
    f = tmp_path / "d.jsonl"
    f.write_bytes(b"".join(orjson.dumps(r) + b"\n" for r in ROWS))
    return f


@pytest.fixture
def not_tty(monkeypatch):
    monkeypatch.setattr(pipe, "is_stdout_tty", lambda: False)


def _out(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# 库层
# --------------------------------------------------------------------------- #
class TestParseSpec:
    def test_literal_and_derived(self):
        assert ops.parse_spec("id, text,n=len(x.m)") == [
            ("id", None),
            ("text", None),
            ("n", "len(x.m)"),
        ]

    def test_commas_inside_brackets_and_quotes(self):
        spec = "a=(x.p, x.q),b=x.s.split(',')[0],c={'k': x.v},d"
        assert [n for n, _ in ops.parse_spec(spec)] == ["a", "b", "c", "d"]
        assert ops.parse_spec(spec)[1][1] == "x.s.split(',')[0]"

    def test_literal_name_can_contain_dash(self):
        assert ops.parse_spec("原始-风险,id") == [("原始-风险", None), ("id", None)]

    def test_rejects_bad_items(self):
        with pytest.raises(ValueError):
            ops.parse_spec("a==1")
        with pytest.raises(ValueError):
            ops.parse_spec("bad name=x.a")
        with pytest.raises(ValueError):
            ops.parse_spec("  ,  ")


class TestRowOps:
    def test_filter_skips_failed_rows_and_counts(self):
        st = ops.filter_rows(_st(), "x.score > 0.2")
        assert [r["id"] for r in st.collect()] == [1, 2]
        assert st._error_count == 1  # id=4 无 score

    def test_filter_strict_raises(self):
        st = ops.filter_rows(_st(), "x.score > 0.2", strict=True)
        with pytest.raises(AttributeError):
            st.collect()

    def test_select_order_missing_and_derived(self):
        rows = ops.select_rows(_st(), "n=len(x.m),id,score").collect()
        assert list(rows[0].keys()) == ["n", "id", "score"]
        assert "score" not in rows[3]  # 字面字段缺失 → 省略, 不报错
        assert rows[0]["n"] == 2

    def test_map_in_place(self):
        rows = ops.map_rows(_st(), "x.text = x.text.strip(); x.n = len(x.m); del x.tags").collect()
        assert rows[0]["text"] == "a" and rows[0]["n"] == 2 and "tags" not in rows[0]

    def test_explode(self):
        rows = ops.explode_rows(_st(), "tags", as_name="tag", index_as="i").collect()
        assert [(r["id"], r["tag"], r["i"]) for r in rows[:3]] == [
            (1, "x", 0),
            (1, "y", 1),
            (2, "y", 0),
        ]
        # id=3 空 list → 0 行; id=4 非 list → 原样透传
        assert [r["id"] for r in rows] == [1, 1, 2, 4] and "tag" not in rows[-1]

    def test_sort_failed_keys_last(self):
        rows = ops.sort_rows(_st(), "x.score", desc=True).collect()
        assert [r["id"] for r in rows] == [2, 1, 3, 4]

    def test_sort_mixed_types_is_value_error(self):
        st = _st([{"k": 1}, {"k": "a"}])
        with pytest.raises(ValueError, match="类型不一致"):
            ops.sort_rows(st, "x.k")

    def test_shuffle_seeded(self):
        a = [r["id"] for r in ops.shuffle_rows(_st(), seed=7).collect()]
        b = [r["id"] for r in ops.shuffle_rows(_st(), seed=7).collect()]
        assert a == b and sorted(a) == [1, 2, 3, 4]

    def test_group_count(self):
        rows = ops.group_rows(_st(), "x.s").collect()
        assert rows == [
            {"key": "wiki", "count": 3, "pct": 0.75},
            {"key": "web", "count": 1, "pct": 0.25},
        ]

    def test_group_top_and_pct_denominator(self, data_file, capsys, not_tty):
        # --top 只留前 N 组; 键求值失败的行仍在 pct 分母里 (stderr 汇总失败数)
        group_cmd(str(data_file), by="x.s", top=1)
        rows = _out(capsys)
        assert rows == [{"key": "wiki", "count": 3, "pct": 0.75}]
        group_cmd(str(data_file), by="x.s if x.id != 1 else x.nope")
        rows = _out(capsys)
        assert sum(r["pct"] for r in rows) == 0.75 and sum(r["count"] for r in rows) == 3
        group_cmd(str(data_file), by="x.s", agg="n=len(g)", top=1)
        assert _out(capsys) == [{"key": "wiki", "n": 3}]
        with pytest.raises(typer.Exit) as ei:
            group_cmd(str(data_file), by="x.s", top=0)
        assert ei.value.exit_code == 2

    def test_group_unhashable_key(self):
        rows = ops.group_rows(_st(), "x.tags").collect()
        assert rows[0]["count"] == 1 and any(r["key"] == ["x", "y"] for r in rows)

    def test_group_agg(self):
        rows = ops.group_rows(
            _st(), "x.s", agg="ids=[r.id for r in g],mx=max(r.get('score') or 0 for r in g)"
        ).collect()
        assert rows[0] == {"key": "wiki", "n": 3, "ids": [1, 3, 4], "mx": 0.5}

    def test_join_left_prefix_inner_and_dups(self):
        right = [
            {"id": 1, "label": "A", "text": "R"},
            {"id": 3, "label": "B"},
            {"id": 3, "label": "dup"},
        ]
        st, dup = ops.join_rows(_st(), right, on="x.id")
        rows = st.collect()
        assert dup == 1
        assert rows[0]["label"] == "A" and rows[0]["text"] == " a "  # 左表字段优先
        assert "label" not in rows[1]  # 左连接透传
        st, _ = ops.join_rows(_st(), right, on="x.id", inner=True, prefix="r_")
        rows = st.collect()
        assert [r["id"] for r in rows] == [1, 3] and rows[0]["r_text"] == "R"

    def test_join_left_right_on(self):
        right = [{"uid": 2, "v": 1}]
        st, _ = ops.join_rows(_st(), right, left_on="x.id", right_on="x.uid", inner=True)
        assert [r["id"] for r in st.collect()] == [2]

    def test_join_anti(self):
        right = [{"id": 1}, {"id": 3}]
        st, _ = ops.join_rows(_st(), right, on="x.id", anti=True)
        rows = st.collect()
        assert [r["id"] for r in rows] == [2, 4] and rows == [ROWS[1], ROWS[3]]  # 原样透传
        with pytest.raises(ValueError):
            ops.join_rows(_st(), right, on="x.id", inner=True, anti=True)

    def test_join_left_key_failure_counted_or_strict(self):
        # 左表键求值失败: 默认按未命中处理并计数 (不再静默), strict 则抛出
        right = [{"score": 0.5}]
        st, _ = ops.join_rows(_st(), right, on="x.score")  # id=4 无 score
        rows = st.collect()
        assert len(rows) == 4 and st._err.count == 1 and "左表键" in st._err.first
        st, _ = ops.join_rows(_st(), right, on="x.score", anti=True)
        assert [r["id"] for r in st.collect()] == [2, 3, 4]  # 失败行无键 → 未命中 → anti 保留
        st, _ = ops.join_rows(_st(), right, on="x.score", strict=True)
        with pytest.raises(AttributeError):
            st.collect()


class TestInferSchema:
    def test_nested(self):
        s = ops.infer_schema(iter(ROWS))
        assert s["rows_scanned"] == 4
        f = s["fields"]
        assert f["id"]["type"] == "int" and f["id"]["non_null"] == 1.0
        assert f["score"]["non_null"] == 0.75
        assert f["s"]["values"] == ["web", "wiki"]
        assert f["m"]["items"]["fields"]["r"]["values"] == ["a", "u"]
        assert f["tags"]["type"] == "list" and f["tags"]["items"]["type"] == "str"


# --------------------------------------------------------------------------- #
# CLI 层
# --------------------------------------------------------------------------- #
class TestCli:
    def test_filter_select_sort_pipeline_in_process(self, data_file, capsys, not_tty):
        filter_cmd(str(data_file), "x.score > 0.2")
        assert [r["id"] for r in _out(capsys)] == [1, 2]
        select_cmd(str(data_file), "id,n=len(x.m)")
        assert _out(capsys)[0] == {"id": 1, "n": 2}
        sort_cmd(str(data_file), "x.id", desc=True)
        assert [r["id"] for r in _out(capsys)] == [4, 3, 2, 1]

    def test_syntax_error_exit_2_with_caret(self, data_file, capsys, not_tty):
        with pytest.raises(typer.Exit) as ei:
            filter_cmd(str(data_file), "x.score >")
        assert ei.value.exit_code == 2
        assert "表达式语法错误" in capsys.readouterr().err

    def test_strict_exit_1(self, data_file, capsys, not_tty):
        with pytest.raises(typer.Exit) as ei:
            filter_cmd(str(data_file), "x.nope > 1", strict=True)
        assert ei.value.exit_code == 1
        assert "AttributeError" in capsys.readouterr().err

    def test_non_strict_summarizes(self, data_file, capsys, not_tty):
        filter_cmd(str(data_file), "x.score > 0.2")
        assert "1 条记录求值失败" in capsys.readouterr().err

    def test_map_explode_shuffle_group(self, data_file, capsys, not_tty):
        map_cmd(str(data_file), "x.text = x.text.upper()")
        assert _out(capsys)[1]["text"] == "B"
        explode_cmd(str(data_file), "tags", as_name="tag")
        assert [r["tag"] for r in _out(capsys) if "tag" in r] == ["x", "y", "y"]
        shuffle_cmd(str(data_file), seed=1)
        assert sorted(r["id"] for r in _out(capsys)) == [1, 2, 3, 4]
        group_cmd(str(data_file), "x.s")
        assert _out(capsys)[0] == {"key": "wiki", "count": 3, "pct": 0.75}

    def test_join_cli(self, data_file, tmp_path, capsys, not_tty):
        right = tmp_path / "r.jsonl"
        right.write_bytes(b'{"id": 1, "label": "A"}\n')
        join_cmd(str(data_file), str(right), on="x.id", inner=True)
        assert _out(capsys) == [{**ROWS[0], "label": "A"}]
        with pytest.raises(typer.Exit) as ei:
            join_cmd(str(data_file), str(right))
        assert ei.value.exit_code == 2
        join_cmd(str(data_file), str(right), on="x.id", anti=True)
        assert [r["id"] for r in _out(capsys)] == [2, 3, 4]
        with pytest.raises(typer.Exit) as ei:
            join_cmd(str(data_file), str(right), on="x.id", inner=True, anti=True)
        assert ei.value.exit_code == 2
        by_score = tmp_path / "s.jsonl"
        by_score.write_bytes(b'{"score": 0.5, "label": "half"}\n')
        join_cmd(str(data_file), str(by_score), on="x.score")  # id=4 无 score: 计数, 不静默
        assert "1 条记录求值失败" in capsys.readouterr().err
        with pytest.raises(typer.Exit) as ei:
            join_cmd(str(data_file), str(by_score), on="x.score", strict=True)
        assert ei.value.exit_code == 1

    def test_output_to_file_emits_action(self, data_file, tmp_path, capsys, not_tty):
        out = tmp_path / "o.jsonl"
        select_cmd(str(data_file), "id", output=str(out))
        payload = json.loads(capsys.readouterr().out)
        assert payload["action"] == "select" and payload["stats"]["output_rows"] == 4
        assert out.read_text().count("\n") == 4

    def test_stats_schema_json_and_tree(self, data_file, capsys, monkeypatch):
        monkeypatch.setattr(pipe, "is_stdout_tty", lambda: False)
        stats(str(data_file), schema=True, format="json")
        d = json.loads(capsys.readouterr().out)
        assert d["rows_scanned"] == 4 and "m" in d["fields"]
        stats(str(data_file), schema=True, sample=2, format="table")
        captured = capsys.readouterr()
        assert captured.out == "" and "扫描 2 行" in captured.err and "items" not in captured.err


class TestQaRegressions:
    """QA 验收报出的契约/数据级问题, 逐条钉住"""

    def test_group_agg_failure_is_null_not_traceback(self, data_file, capsys, not_tty):
        group_cmd(str(data_file), "x.s", agg="avg=mean(r.score for r in g)")
        captured = capsys.readouterr()
        rows = [json.loads(line) for line in captured.out.splitlines()]
        assert {r["key"]: r["avg"] for r in rows} == {
            "wiki": None,
            "web": 0.9,
        }  # wiki 组含无 score 的行
        assert "聚合 avg" in captured.err and "Traceback" not in captured.err
        with pytest.raises(typer.Exit) as ei:
            group_cmd(str(data_file), "x.s", agg="avg=mean(r.score for r in g)", strict=True)
        assert ei.value.exit_code == 1

    def test_map_and_select_keep_row_count(self, data_file, capsys, not_tty):
        map_cmd(str(data_file), "x.s2 = x.score * 2")
        rows = _out(capsys)
        assert len(rows) == 4 and "s2" not in rows[3]  # id=4 无 score: 原样保留
        select_cmd(str(data_file), "id,s=x.score")
        rows = _out(capsys)
        assert len(rows) == 4 and rows[3] == {"id": 4, "s": None}

    def test_output_dash_means_stdout(self, data_file, capsys, not_tty, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        filter_cmd(str(data_file), "x.id > 3", output="-")
        assert _out(capsys) == [ROWS[3]]
        assert not (tmp_path / "-").exists()

    def test_strict_failure_with_output_file(self, data_file, capsys, not_tty, tmp_path):
        out = tmp_path / "st.jsonl"
        with pytest.raises(typer.Exit) as ei:
            filter_cmd(str(data_file), "x.score > 0.2", output=str(out), strict=True)
        assert ei.value.exit_code == 1
        err = capsys.readouterr().err
        assert err.count('"error"') == 1  # 只有一份错误 JSON
        payload = json.loads(err[err.index("{") :])
        assert payload["error"] == "filter_failed" and not payload["retryable"]
        assert not out.exists() and not list(tmp_path.glob(".tmp_*"))

    def test_json_and_gz_outputs(self, data_file, capsys, not_tty, tmp_path):
        from dtflow.storage.io import load_data

        out = tmp_path / "s.json"
        select_cmd(str(data_file), "id", output=str(out))
        assert load_data(str(out)) == [{"id": i} for i in (1, 2, 3, 4)]
        with pytest.raises(typer.Exit) as ei:
            select_cmd(str(data_file), "id", output=str(tmp_path / "s.csv.gz"))
        assert ei.value.exit_code == 2

    def test_field_path_args_reject_expression(self, data_file, not_tty):
        from dtflow.cli.clean import dedupe
        from dtflow.cli.sample import sample

        with pytest.raises(typer.Exit) as ei:
            dedupe(str(data_file), key="x.s")
        assert ei.value.exit_code == 2
        with pytest.raises(typer.Exit) as ei:
            sample(str(data_file), num=2, by="x.s")
        assert ei.value.exit_code == 2

    def test_bare_field_name_is_usage_error(self, data_file, not_tty):
        with pytest.raises(typer.Exit) as ei:
            filter_cmd(str(data_file), "score > 0.2")
        assert ei.value.exit_code == 2
        with pytest.raises(typer.Exit) as ei:
            group_cmd(str(data_file), "id")
        assert ei.value.exit_code == 2

    def test_join_on_and_left_on_conflict(self, data_file, tmp_path, not_tty):
        right = tmp_path / "r.jsonl"
        right.write_bytes(b'{"id": 1}\n')
        with pytest.raises(typer.Exit) as ei:
            join_cmd(str(data_file), str(right), on="x.id", left_on="x.id")
        assert ei.value.exit_code == 2


def test_field_path_guard_checks_every_item(data_file, not_tty):
    from dtflow.cli.clean import clean, dedupe

    with pytest.raises(typer.Exit) as ei:
        dedupe(str(data_file), key="s,x.id")
    assert ei.value.exit_code == 2
    with pytest.raises(typer.Exit) as ei:
        clean(str(data_file), keep="x.id")
    assert ei.value.exit_code == 2


def test_pipeline_caret_aligned(tmp_path):
    from dtflow.pipeline import validate_pipeline

    cfg = tmp_path / "p.yaml"
    cfg.write_text("steps:\n  - type: filter\n    expr: 'x.a > > 1'\n")
    (err,) = validate_pipeline(str(cfg))
    expr_line, caret_line = err.splitlines()[1:]
    assert expr_line.index("x.a") == caret_line.index("^") - len("x.a > ")


def test_tty_preview_has_no_misleading_total(monkeypatch, capsys):
    from dtflow.streaming import StreamingTransformer

    monkeypatch.setattr(pipe, "is_stdout_tty", lambda: True)
    monkeypatch.setattr(pipe, "TTY_PREVIEW_LIMIT", 3)
    st = StreamingTransformer(({"i": i} for i in range(10)), None, total=None)
    pipe.emit_rows(st, action="select")
    err = capsys.readouterr().err
    assert "输出 3 条" not in err and "预览只显示前 3 条" in err
