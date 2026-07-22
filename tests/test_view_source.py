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


def test_malformed_line_becomes_visible_placeholder(tmp_path):
    """坏行 → 占位行, 而不是抛出。

    dt view 的职责就是"看数据", 语法坏掉的行恰恰是人打开它要找的东西: 崩掉最差,
    悄悄跳过次之 (行号会与文件错位), 显示出来才对。偏移索引按非空行计数, 坏行本就
    占一个行号 —— 占位行让 # 列与文件行号继续对齐。
    """
    from dtflow.cli.view.source import PARSE_ERROR_FIELD, RAW_LINE_FIELD, open_source

    p = tmp_path / "bad.jsonl"
    p.write_bytes(
        b"{ this is not json\n"  # 首行就坏: 以前连窗口都取不出来
        b'{"id":2}\n'
        b"also not json\n"
        b'{"id":4}\n'
    )
    src = open_source(p)
    assert src.total == 4  # 坏行也占行号

    rows = src.window(0, 4)
    assert PARSE_ERROR_FIELD in rows[0] and "this is not json" in rows[0][RAW_LINE_FIELD]
    assert rows[1] == {"id": 2}
    assert PARSE_ERROR_FIELD in rows[2]
    assert rows[3] == {"id": 4}  # 行号没有因为坏行而错位

    assert src.rows_at([1, 3]) == [{"id": 2}, {"id": 4}]  # 随机取行同样不抛
    assert [r.get("id") for r in src.iter_all()] == [None, 2, None, 4]


def test_format_detection_survives_leading_bad_line(tmp_path):
    # 坏行不该把格式检测带偏 (它不匹配任何格式, 应继续看后面的行)
    from dtflow.cli.view.render import detect_format
    from dtflow.cli.view.source import open_source

    p = tmp_path / "bad.jsonl"
    p.write_bytes(b"{ broken\n" + b'{"messages":[{"role":"user","content":"hi"}]}\n')
    assert detect_format(open_source(p).window(0, 10)) == "openai_chat"
