"""dt describe: 表达式数值分布摘要 (view S 列快照的 CLI 版) + utils.stats 纯函数。"""

import json

import orjson
import pytest
import typer

from dtflow.cli import output
from dtflow.cli.describe import describe
from dtflow.utils.stats import histogram, percentile, render_histogram_lines, summarize

ROWS = [
    {"id": 1, "score": 0.5, "messages": [{"role": "user", "content": "a"}]},
    {
        "id": 2,
        "score": None,
        "messages": [{"role": "user", "content": "bb"}, {"role": "assistant", "content": "c"}],
    },
    {"id": 3, "score": "n/a", "messages": []},
    {"id": 4, "messages": [{"role": "user", "content": "dddd"}]},  # 无 score
    {"id": 5, "score": 1.0, "messages": [{"role": "user", "content": "e"}]},
]


@pytest.fixture
def data_file(tmp_path):
    f = tmp_path / "d.jsonl"
    f.write_bytes(b"".join(orjson.dumps(r) + b"\n" for r in ROWS))
    return f


@pytest.fixture
def not_tty(monkeypatch):
    monkeypatch.setattr(output, "is_stdout_tty", lambda: False)


def _json(capsys):
    return json.loads(capsys.readouterr().out)


class TestPureFunctions:
    def test_percentile_interpolates(self):
        assert percentile([1, 2, 3, 4], 50) == 2.5
        assert percentile([7], 99) == 7 and percentile([], 50) == 0.0

    def test_summarize(self):
        s = summarize([3, 1, 2])
        assert (s["n"], s["min"], s["max"], s["mean"], s["p50"]) == (3, 1, 3, 2.0, 2.0)
        assert isinstance(s["min"], int)  # 整数数据不输出 1.0
        assert summarize([0.5, 1.5])["min"] == 0.5
        empty = summarize([])
        assert empty["n"] == 0 and empty["mean"] is None and empty["p99"] is None

    def test_histogram_bins_and_single_value(self):
        h = histogram([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], bins=2)
        assert [c for _, _, c in h] == [5, 6]  # 最后一桶右闭, 10 落进去
        assert histogram([4, 4, 4]) == [(4, 4, 3)]
        assert histogram([]) == []
        lines = render_histogram_lines(h, width=10)
        assert lines[0].startswith("[0, 5)") and lines[1].startswith("[5, 10]")
        assert lines[1].endswith("█" * 10)


class TestDescribe:
    def test_json_fields_and_null_counting(self, data_file, capsys, not_tty):
        describe(str(data_file), ["x.score", "turns(x)"])
        score, turns = _json(capsys)
        # None / 非数值 / 缺字段 都是 null, 不中断
        assert score["expr"] == "x.score" and score["n"] == 2 and score["null"] == 3
        assert (score["min"], score["max"], score["mean"], score["p50"]) == (0.5, 1.0, 0.75, 0.75)
        assert turns["n"] == 5 and turns["null"] == 0 and turns["min"] == 0 and turns["max"] == 2
        assert set(turns) == {
            "expr",
            "n",
            "null",
            "min",
            "max",
            "mean",
            "std",
            "p25",
            "p50",
            "p75",
            "p90",
            "p99",
        }

    def test_bool_counts_as_int(self, data_file, capsys, not_tty):
        describe(str(data_file), ["x.id > 2"])
        (r,) = _json(capsys)
        assert r["n"] == 5 and r["mean"] == 0.6

    def test_syntax_error_is_usage_error(self, data_file, capsys, not_tty):
        with pytest.raises(typer.Exit) as ei:
            describe(str(data_file), ["turns(x)", "chars >"])
        assert ei.value.exit_code == 2

    def test_empty_file(self, tmp_path, capsys, not_tty):
        f = tmp_path / "e.jsonl"
        f.write_bytes(b"")
        with pytest.raises(typer.Exit) as ei:
            describe(str(f), ["x.a"])
        assert ei.value.exit_code == 1

    def test_tty_renders_table_and_histogram(self, data_file, capsys, monkeypatch):
        monkeypatch.setattr(output, "is_stdout_tty", lambda: True)
        describe(str(data_file), ["turns(x)"], bins=2)
        captured = capsys.readouterr()
        assert captured.out == ""  # 表格与直方图只走 stderr
        assert "p50" in captured.err and "█" in captured.err and "turns(x)" in captured.err
