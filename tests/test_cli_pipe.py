"""管道层: FILE=- 读 stdin, 无 -o 写 stdout, 摘要/进度只走 stderr。"""

import io
import json
import subprocess
import sys

import orjson
import pytest
import typer

from dtflow.cli import pipe
from dtflow.cli.clean import clean, dedupe
from dtflow.cli.io_ops import concat
from dtflow.cli.sample import head, sample
from dtflow.cli.split import split
from dtflow.cli.transform import transform
from dtflow.storage.io import load_data

ROWS = [
    {"id": 1, "text": "  a  ", "q": "q1", "a": "a1"},
    {"id": 2, "text": "b", "q": "q2", "a": "a2"},
    {"id": 2, "text": "b", "q": "q2", "a": "a2"},
]


def _feed_stdin(monkeypatch, rows):
    raw = b"".join(orjson.dumps(r) + b"\n" for r in rows)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))


def _stdout_rows(capsys):
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


@pytest.fixture
def not_tty(monkeypatch):
    monkeypatch.setattr(pipe, "is_stdout_tty", lambda: False)


class TestStdinStdout:
    def test_head_from_stdin(self, monkeypatch, capsys, not_tty):
        _feed_stdin(monkeypatch, ROWS)
        head("-", num=2)
        assert [r["id"] for r in _stdout_rows(capsys)] == [1, 2]

    def test_sample_where_from_stdin(self, monkeypatch, capsys, not_tty):
        _feed_stdin(monkeypatch, ROWS)
        sample("-", num=0, where=["x.id==2"])
        assert len(_stdout_rows(capsys)) == 2

    def test_clean_stdin_to_stdout_keeps_stdout_clean(self, monkeypatch, capsys, not_tty):
        _feed_stdin(monkeypatch, ROWS)
        clean("-", strip=True)
        captured = capsys.readouterr()
        rows = [json.loads(line) for line in captured.out.splitlines()]
        assert [r["text"] for r in rows] == ["a", "b", "b"]
        # 摘要只在 stderr, stdout 每行都是 JSON
        assert "clean" in captured.err and "action" not in captured.out

    def test_dedupe_stdin_streaming(self, monkeypatch, capsys, not_tty):
        _feed_stdin(monkeypatch, ROWS)
        dedupe("-", key="id")
        assert [r["id"] for r in _stdout_rows(capsys)] == [1, 2]

    def test_transform_preset_stdin(self, monkeypatch, capsys, not_tty):
        _feed_stdin(monkeypatch, ROWS[:1])
        transform("-", preset="simple_qa")
        assert _stdout_rows(capsys) == [{"question": "q1", "answer": "a1"}]

    def test_transform_config_mode_needs_config_for_stdin(self, monkeypatch, not_tty):
        _feed_stdin(monkeypatch, ROWS)
        with pytest.raises(typer.Exit) as ei:
            transform("-")
        assert ei.value.exit_code == 2

    def test_concat_stdin_and_file(self, monkeypatch, capsys, tmp_path, not_tty):
        f = tmp_path / "b.jsonl"
        f.write_bytes(orjson.dumps({"id": 9}) + b"\n")
        _feed_stdin(monkeypatch, ROWS[:1])
        concat("-", str(f))
        assert [r["id"] for r in _stdout_rows(capsys)] == [1, 9]

    def test_concat_rejects_two_stdin(self, not_tty):
        with pytest.raises(typer.Exit) as ei:
            concat("-", "-")
        assert ei.value.exit_code == 2

    def test_split_stdin_requires_dir_and_name(self, monkeypatch, tmp_path, not_tty):
        _feed_stdin(monkeypatch, ROWS)
        with pytest.raises(typer.Exit) as ei:
            split("-", ratio="0.5")
        assert ei.value.exit_code == 2
        _feed_stdin(monkeypatch, ROWS)
        split("-", ratio="0.5", output=str(tmp_path / "o"), name="z", seed=1)
        assert sorted(p.name for p in (tmp_path / "o").iterdir()) == [
            "z_test.jsonl",
            "z_train.jsonl",
        ]


class TestOutputModes:
    def test_in_place_and_output_exclusive(self, tmp_path, not_tty):
        f = tmp_path / "d.jsonl"
        f.write_bytes(orjson.dumps(ROWS[0]) + b"\n")
        with pytest.raises(typer.Exit) as ei:
            clean(str(f), strip=True, output=str(tmp_path / "o.jsonl"), in_place=True)
        assert ei.value.exit_code == 2

    def test_in_place_rewrites_file(self, tmp_path, capsys, not_tty):
        f = tmp_path / "d.jsonl"
        f.write_bytes(b"".join(orjson.dumps(r) + b"\n" for r in ROWS))
        clean(str(f), strip=True, in_place=True)
        assert [r["text"] for r in load_data(str(f))] == ["a", "b", "b"]
        assert not list(tmp_path.glob(".tmp_*")), "临时文件必须清理"
        # -o 模式下 stdout 只有动作摘要 JSON, 没有进度条/数据
        out = capsys.readouterr().out
        assert json.loads(out)["action"] == "clean"

    def test_no_output_goes_to_stdout_not_file(self, tmp_path, capsys, not_tty):
        f = tmp_path / "d.jsonl"
        raw = b"".join(orjson.dumps(r) + b"\n" for r in ROWS)
        f.write_bytes(raw)
        clean(str(f), strip=True)
        assert f.read_bytes() == raw, "无 -o/-i 不得改动原文件"
        assert len(_stdout_rows(capsys)) == 3

    def test_tty_preview_truncates(self, monkeypatch, capsys):
        from dtflow.streaming import StreamingTransformer

        monkeypatch.setattr(pipe, "is_stdout_tty", lambda: True)
        monkeypatch.setattr(pipe, "TTY_PREVIEW_LIMIT", 5)
        st = StreamingTransformer(({"i": i} for i in range(100)), None, total=None)
        n = pipe.emit_rows(st)
        captured = capsys.readouterr()
        assert n == 5 and len(captured.out.splitlines()) == 5
        assert "前 5 条" in captured.err

    def test_explicit_format_disables_tty_truncation(self, monkeypatch, capsys):
        from dtflow.cli.output import CLIState, get_state, set_state
        from dtflow.streaming import StreamingTransformer

        monkeypatch.setattr(pipe, "is_stdout_tty", lambda: True)
        monkeypatch.setattr(pipe, "TTY_PREVIEW_LIMIT", 5)
        old = get_state()
        set_state(CLIState(fmt="ndjson"))
        try:
            st = StreamingTransformer(({"i": i} for i in range(20)), None, total=None)
            assert pipe.emit_rows(st) == 20
        finally:
            set_state(old)
        assert len(capsys.readouterr().out.splitlines()) == 20

    def test_filter_errors_summarized_on_stderr(self, tmp_path, capsys, not_tty):
        from dtflow.streaming import StreamingTransformer

        st = StreamingTransformer(iter([{"a": 1}, {"b": 2}, {"a": 3}]), None).filter(
            lambda x: x["a"] > 0, raw=True
        )
        assert pipe.emit_rows(st) == 2
        err = capsys.readouterr().err
        assert "跳过 1 条" in err and "KeyError" in err


def _run_shell(cmd: str):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def test_end_to_end_shell_pipeline(tmp_path):
    f = tmp_path / "d.jsonl"
    f.write_bytes(
        b"".join(
            orjson.dumps({"id": i, "text": f" t{i} ", "messages": [{"role": "user"}] * (i % 3 + 1)})
            + b"\n"
            for i in range(30)
        )
    )
    py = sys.executable
    cmd = (
        f"{py} -m dtflow sample {f} 0 -w 'len(x.messages)>=2' "
        f"| {py} -m dtflow clean - --strip --drop=messages "
        f"| {py} -m dtflow dedupe - --key=text "
        f"| {py} -m dtflow head - 3"
    )
    r = _run_shell(cmd)
    assert r.returncode == 0, r.stderr
    rows = [json.loads(line) for line in r.stdout.splitlines()]
    assert [row["id"] for row in rows] == [1, 2, 4]
    assert all(row["text"] == f"t{row['id']}" and "messages" not in row for row in rows)


class TestQaRegressions:
    def test_stdin_gzip_auto_detected(self, monkeypatch, capsys, not_tty):
        import gzip

        raw = gzip.compress(b"".join(orjson.dumps(r) + b"\n" for r in ROWS))
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
        head("-", num=2)
        assert [r["id"] for r in _stdout_rows(capsys)] == [1, 2]

    def test_validate_filter_to_file_single_stdout_json(self, tmp_path, capsys, not_tty):
        from dtflow.cli.validate import validate

        f = tmp_path / "d.jsonl"
        f.write_bytes(
            b'{"messages":[{"role":"user","content":"a"},{"role":"assistant","content":"b"}]}\n{"x":1}\n'
        )
        out = tmp_path / "v.jsonl"
        validate(str(f), preset="openai_chat", output=str(out), filter_invalid=True)
        payload = json.loads(capsys.readouterr().out)  # 只有一份 JSON
        assert payload["action"] == "validate" and payload["stats"]["valid"] == 1
        assert out.read_text().count("\n") == 1

    def test_run_output_dash(self, tmp_path, capsys, not_tty):
        from dtflow.cli.pipeline import run

        f = tmp_path / "d.jsonl"
        f.write_bytes(b"".join(orjson.dumps(r) + b"\n" for r in ROWS))
        cfg = tmp_path / "p.yaml"
        cfg.write_text(f"input: {f}\noutput: o.jsonl\nsteps:\n  - type: head\n    num: 1\n")
        run(str(cfg), output="-")
        assert _stdout_rows(capsys) == [ROWS[0]]
        assert not (tmp_path / "-").exists() and not (tmp_path / "o.jsonl").exists()
