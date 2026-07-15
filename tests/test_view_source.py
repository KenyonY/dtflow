"""dt view 数据源: JSONL 偏移索引 + 随机窗口访问 + stdin 管道。"""

import io
from pathlib import Path

from dtflow.cli.view.source import open_source, read_stdin_source


def _write(tmp_path, name, lines):
    p = Path(tmp_path) / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_jsonl_window_random_access(tmp_path):
    p = _write(tmp_path, "d.jsonl", [f'{{"i": {i}}}' for i in range(100)])
    src = open_source(p)
    assert src.total == 100
    # 任意窗口: 只 parse 该窗口, 内容正确
    assert src.window(0, 3) == [{"i": 0}, {"i": 1}, {"i": 2}]
    assert src.window(50, 2) == [{"i": 50}, {"i": 51}]
    # 尾部不足一窗
    assert src.window(98, 10) == [{"i": 98}, {"i": 99}]
    # 越界返回空
    assert src.window(100, 10) == []


def test_jsonl_index_skips_blank_lines(tmp_path):
    # 夹杂空行: 索引与 window 都应跳过, 与 _stream_jsonl 一致
    p = _write(
        tmp_path,
        "b.jsonl",
        ['{"i": 0}', "", '{"i": 1}', "  ", '{"i": 2}'],
    )
    src = open_source(p)
    assert src.total == 3
    assert src.window(0, 3) == [{"i": 0}, {"i": 1}, {"i": 2}]
    assert src.window(1, 2) == [{"i": 1}, {"i": 2}]


def test_stdin_source_reads_ndjson_skipping_blanks(monkeypatch):
    # 管道: 逐行 NDJSON, 跳空行/纯空白行, 全量入内存后窗口即切片
    monkeypatch.setattr("sys.stdin", io.StringIO('{"i":0}\n\n{"i":1}\n  \n{"i":2}\n'))
    src = read_stdin_source()
    assert src.total == 3
    assert src.window(0, 10) == [{"i": 0}, {"i": 1}, {"i": 2}]
    assert src.window(1, 1) == [{"i": 1}]


def test_stdin_source_empty(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert read_stdin_source().total == 0
