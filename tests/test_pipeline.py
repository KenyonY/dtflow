"""Pipeline: step 的 type = CLI 命令名, 参数 = CLI 选项名, 执行载体 StreamingTransformer。"""

import json

import orjson
import pytest

from dtflow.pipeline import (
    STEP_EXECUTORS,
    _format_step_description,
    build_pipeline,
    generate_pipeline_template,
    run_pipeline,
    validate_pipeline,
)
from dtflow.storage.io import load_data, save_data
from dtflow.streaming import StreamingTransformer

ROWS = [
    {
        "id": 1,
        "score": 0.8,
        "text": " high ",
        "q": "q1",
        "a": "a1",
        "tags": ["x", "y"],
        "m": {"s": "w"},
    },
    {"id": 2, "score": 0.3, "text": "low", "q": "q2", "a": "a2", "tags": ["y"], "m": {"s": "w"}},
    {"id": 3, "score": 0.9, "text": "higher", "q": "q3", "a": "a3", "tags": [], "m": {"s": "b"}},
    {"id": 4, "score": 0.9, "text": "higher", "q": "q3", "a": "a3", "tags": [], "m": {"s": "b"}},
]


def _st():
    return StreamingTransformer(iter([dict(r) for r in ROWS]), None, total=len(ROWS))


def _run(step):
    return STEP_EXECUTORS[step["type"]](_st(), step).collect()


class TestSteps:
    def test_filter(self):
        assert [r["id"] for r in _run({"type": "filter", "expr": "x.score > 0.5"})] == [1, 3, 4]

    def test_filter_requires_expr(self):
        with pytest.raises(ValueError, match="expr"):
            _run({"type": "filter"})

    def test_map_select_explode(self):
        assert _run({"type": "map", "code": "x.text = x.text.strip()"})[0]["text"] == "high"
        rows = _run({"type": "select", "fields": "id,s=x.m.s"})
        assert rows[0] == {"id": 1, "s": "w"}
        rows = _run({"type": "explode", "field": "tags", "as": "tag"})
        assert [r["tag"] for r in rows if "tag" in r] == ["x", "y", "y"]

    def test_sort_shuffle_group(self):
        assert [r["id"] for r in _run({"type": "sort", "by": "x.score", "desc": True})][:2] == [
            3,
            4,
        ]
        assert sorted(r["id"] for r in _run({"type": "shuffle", "seed": 1})) == [1, 2, 3, 4]
        assert _run({"type": "group", "by": "x.m.s"}) == [
            {"key": "w", "count": 2, "pct": 0.5},
            {"key": "b", "count": 2, "pct": 0.5},
        ]
        assert _run({"type": "group", "by": "x.m.s", "top": 1}) == [
            {"key": "w", "count": 2, "pct": 0.5}
        ]

    def test_join(self, tmp_path):
        right = tmp_path / "r.jsonl"
        save_data([{"id": 1, "label": "A"}], str(right))
        rows = _run({"type": "join", "right": str(right), "on": "x.id", "inner": True})
        assert rows == [{**ROWS[0], "label": "A"}]
        with pytest.raises(ValueError, match="on"):
            _run({"type": "join", "right": str(right)})
        anti = _run({"type": "join", "right": str(right), "on": "x.id", "anti": True})
        assert [r["id"] for r in anti] == [2, 3, 4]
        with pytest.raises(ValueError):
            _run({"type": "join", "right": str(right), "on": "x.id", "inner": True, "anti": True})

    def test_dedupe_key_list_and_similar_needs_key(self):
        assert len(_run({"type": "dedupe", "key": ["text", "q"]})) == 3
        assert len(_run({"type": "dedupe"})) == 4  # 全行去重: id 不同不算重复
        with pytest.raises(ValueError, match="key"):
            _run({"type": "dedupe", "similar": 0.9})

    def test_sample_head_tail(self):
        assert len(_run({"type": "sample", "num": 2, "seed": 1})) == 2
        assert [r["id"] for r in _run({"type": "head", "num": 1})] == [1]
        assert [r["id"] for r in _run({"type": "tail", "num": 1})] == [4]

    def test_transform_preset_and_config(self, tmp_path):
        rows = _run(
            {
                "type": "transform",
                "preset": "openai_chat",
                "params": {"user_field": "q", "assistant_field": "a"},
            }
        )
        assert rows[0]["messages"][0] == {"role": "user", "content": "q1"}
        cfg = tmp_path / "t.py"
        cfg.write_text("def transform(item):\n    return {'n': len(item.tags)}\n")
        assert _run({"type": "transform", "config": str(cfg)})[0] == {"n": 2}
        with pytest.raises(ValueError, match="preset 或 config"):
            _run({"type": "transform"})

    def test_clean_uses_cli_option_names(self):
        rows = _run(
            {
                "type": "clean",
                "strip": True,
                "min_len": "text:4",
                "drop": "q,a",
                "rename": "text:t",
                "promote": "m.s",
                "add_field": "src:demo",
                "reorder": "s,id",
            }
        )
        assert [r["id"] for r in rows] == [1, 3, 4]
        assert list(rows[0].keys())[:2] == ["s", "id"]
        assert rows[0]["t"] == "high" and rows[0]["src"] == "demo" and "q" not in rows[0]
        assert [r["id"] for r in _run({"type": "clean", "drop_empty": "tags"})] == [1, 2]
        with pytest.raises(ValueError):
            _run({"type": "clean", "min_len": "text"})


class TestBuildAndRun:
    @pytest.fixture
    def files(self, tmp_path):
        inp = tmp_path / "in.jsonl"
        save_data(ROWS, str(inp))
        return tmp_path, inp

    def test_build_is_lazy_and_ordered(self, files):
        tmp_path, inp = files
        cfg = {
            "steps": [
                {"type": "filter", "expr": "x.score > 0.5"},
                {"type": "select", "fields": "id"},
            ]
        }
        st = build_pipeline(cfg, str(inp))
        assert st.collect() == [{"id": 1}, {"id": 3}, {"id": 4}]

    def test_run_pipeline_saves(self, files):
        tmp_path, inp = files
        cfg = tmp_path / "p.yaml"
        cfg.write_text(
            f"""
version: "1.0"
input: {inp}
output: {tmp_path}/out.jsonl
steps:
  - type: filter
    expr: "x.score > 0.5"
  - type: dedupe
    key: text
  - type: transform
    preset: openai_chat
    params: {{user_field: q, assistant_field: a}}
"""
        )
        result = run_pipeline(str(cfg), verbose=False)
        assert result == {"output": f"{tmp_path}/out.jsonl", "rows": 2}
        assert "messages" in load_data(f"{tmp_path}/out.jsonl")[0]

    def test_run_pipeline_override_and_errors(self, files):
        tmp_path, inp = files
        cfg = tmp_path / "p.yaml"
        cfg.write_text(
            "version: '1.0'\ninput: nope.jsonl\noutput: nope_out.jsonl\nsteps:\n  - type: head\n    num: 1\n"
        )
        out = tmp_path / "o.jsonl"
        assert (
            run_pipeline(str(cfg), input_file=str(inp), output_file=str(out), verbose=False)["rows"]
            == 1
        )
        cfg.write_text("version: '1.0'\nsteps: []\n")
        with pytest.raises(ValueError, match="未指定输入文件"):
            run_pipeline(str(cfg), verbose=False)
        cfg.write_text(f"input: {inp}\nsteps: []\n")
        with pytest.raises(ValueError, match="未指定输出文件"):
            run_pipeline(str(cfg), verbose=False)
        cfg.write_text(f"input: {inp}\noutput: {out}\nsteps:\n  - type: nope\n")
        with pytest.raises(ValueError, match="未知步骤类型"):
            run_pipeline(str(cfg), verbose=False)
        cfg.write_text(f"input: {inp}\noutput: {out}\nsteps:\n  - expr: x\n")
        with pytest.raises(ValueError, match="未指定 type"):
            run_pipeline(str(cfg), verbose=False)

    def test_split_terminal_writes_all_parts(self, files):
        tmp_path, inp = files
        cfg = tmp_path / "p.yaml"
        cfg.write_text(
            f"""
input: {inp}
output: {tmp_path}/out/data.jsonl
steps:
  - type: filter
    expr: "x.id != 2"
  - type: split
    ratio: 0.7,0.15,0.15
    seed: 1
"""
        )
        result = run_pipeline(str(cfg), verbose=False)
        names = [s["name"] for s in result["splits"]]
        assert names == ["train", "val", "test"] and result["rows"] == 3
        for s in result["splits"]:
            assert s["path"].endswith(f"data_{s['name']}.jsonl")
            assert len(load_data(s["path"])) == s["rows"]
        cfg.write_text(
            f"input: {inp}\noutput: {tmp_path}/o.jsonl\nsteps:\n  - type: split\n  - type: head\n"
        )
        with pytest.raises(ValueError, match="最后一步"):
            run_pipeline(str(cfg), verbose=False)

    def test_run_pipeline_from_stdin(self, files, monkeypatch):
        import io
        import sys

        tmp_path, inp = files
        raw = b"".join(orjson.dumps(r) + b"\n" for r in ROWS)
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
        cfg = tmp_path / "p.yaml"
        cfg.write_text("steps:\n  - type: head\n    num: 2\n")
        out = tmp_path / "o.jsonl"
        assert (
            run_pipeline(str(cfg), input_file="-", output_file=str(out), verbose=False)["rows"] == 2
        )


class TestFormatAndTemplate:
    def test_format(self):
        assert (
            _format_step_description({"type": "filter", "expr": "x.a > 1"})
            == "filter (expr=x.a > 1)"
        )
        assert _format_step_description({"type": "shuffle"}) == "shuffle"

    def test_generate_template(self, tmp_path):
        inp = tmp_path / "in.jsonl"
        save_data([{"q": "question", "a": "answer"}], str(inp))
        out = tmp_path / "pipeline.yaml"
        generate_pipeline_template(str(inp), str(out))
        content = out.read_text()
        assert "openai_chat" in content and "expr: x.q" in content
        assert validate_pipeline(str(out)) == []
        generate_pipeline_template(str(inp), str(out), preset="alpaca")
        assert "alpaca" in out.read_text()
        (tmp_path / "empty.jsonl").write_text("")
        with pytest.raises(ValueError, match="输入文件为空"):
            generate_pipeline_template(str(tmp_path / "empty.jsonl"), str(out))


class TestValidatePipeline:
    def _errors(self, tmp_path, yaml_text):
        cfg = tmp_path / "p.yaml"
        cfg.write_text(yaml_text)
        return validate_pipeline(str(cfg))

    def test_valid(self, tmp_path):
        assert (
            self._errors(
                tmp_path,
                """
steps:
  - type: filter
    expr: "x.score > 0.5"
  - type: select
    fields: "id,n=len(x.tags)"
  - type: map
    code: "x.a = 1"
  - type: transform
    preset: alpaca
  - type: join
    right: r.jsonl
    on: x.id
  - type: split
""",
            )
            == []
        )

    @pytest.mark.parametrize(
        "yaml_text,needle",
        [
            ("version: '1.0'\n", "缺少 steps"),
            ("steps:\n  - expr: x\n", "缺少 type"),
            ("steps:\n  - type: nope\n", "未知类型"),
            ("steps:\n  - type: transform\n", "preset 或 config"),
            ("steps:\n  - type: filter\n", "需要指定 expr"),
            ("steps:\n  - type: filter\n    expr: 'x.a >'\n", "语法错误"),
            ("steps:\n  - type: map\n    code: 'x.a = = 1'\n", "语法错误"),
            ("steps:\n  - type: select\n    fields: 'a==1'\n", "select"),
            ("steps:\n  - type: join\n    right: r.jsonl\n", "on"),
            ("steps:\n  - type: split\n  - type: head\n", "最后一步"),
        ],
    )
    def test_errors(self, tmp_path, yaml_text, needle):
        errors = self._errors(tmp_path, yaml_text)
        assert any(needle in e for e in errors), errors

    def test_invalid_yaml(self, tmp_path):
        assert any("无法解析" in e for e in self._errors(tmp_path, "invalid: yaml: content:["))


def test_cli_run_to_stdout_and_dry_run(tmp_path, capsys, monkeypatch):
    from dtflow.cli import pipe
    from dtflow.cli.pipeline import run

    monkeypatch.setattr(pipe, "is_stdout_tty", lambda: False)
    inp = tmp_path / "in.jsonl"
    save_data(ROWS, str(inp))
    cfg = tmp_path / "p.yaml"
    cfg.write_text(f"input: {inp}\nsteps:\n  - type: select\n    fields: id\n")
    run(str(cfg))
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows == [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]
    import typer

    with pytest.raises(typer.Exit) as ei:
        run(str(cfg), dry_run=True)
    assert ei.value.exit_code == 10
    assert json.loads(capsys.readouterr().out)["plan"][0]["step"] == "select"


def test_validate_rejects_unknown_keys_and_join_conflict(tmp_path):
    cfg = tmp_path / "p.yaml"
    cfg.write_text(
        "steps:\n  - type: clean\n    stirp: true\n  - type: sort\n    by: x.a\n    dsc: true\n"
    )
    errors = validate_pipeline(str(cfg))
    assert any("stirp" in e for e in errors) and any("dsc" in e for e in errors)
    cfg.write_text("steps:\n  - type: join\n    right: r.jsonl\n    on: x.id\n    left_on: x.id\n")
    assert any("二选一" in e for e in validate_pipeline(str(cfg)))
    cfg.write_text("steps:\n  - type: group\n    by: x.a\n    agg: 'm=mean(r.v for r in g)'\n")
    assert validate_pipeline(str(cfg)) == []


def test_run_pipeline_input_directory(tmp_path):
    from dtflow.pipeline import run_pipeline
    from dtflow.storage.io import load_data, save_data

    d = tmp_path / "in"
    d.mkdir()
    save_data([{"a": 1}], str(d / "x.jsonl"))
    save_data([{"a": 2}], str(d / "y.jsonl"))
    cfg = tmp_path / "p.yaml"
    cfg.write_text(f"input: {d}\nsteps:\n  - type: filter\n    expr: 'x.a > 1'\n")
    out = tmp_path / "o.jsonl"
    run_pipeline(str(cfg), output_file=str(out))
    assert load_data(str(out)) == [{"a": 2}]


def test_clean_step_rejects_duplicate_keys(tmp_path):
    """pipeline 的 clean 步与 dt clean 共用解析: 同一字段出现两次报错, 不静默取后者。"""
    import pytest

    from dtflow.pipeline import run_pipeline

    src = tmp_path / "in.jsonl"
    src.write_text('{"a":1,"x":2}\n')
    for key, spec in (("rename", "a:b,a:c"), ("fill", "a:1,a:2"), ("add_field", "k:1,k:2")):
        cfg = tmp_path / f"{key}.yaml"
        cfg.write_text(
            f"version: '1.0'\ninput: {src}\noutput: {tmp_path}/out.jsonl\n"
            f"steps:\n  - type: clean\n    {key}: '{spec}'\n"
        )
        with pytest.raises(ValueError, match="twice|两次"):
            run_pipeline(str(cfg))
