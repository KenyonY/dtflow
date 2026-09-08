"""dt view 数据源: JSONL 偏移索引 + 随机窗口访问 + stdin 管道。"""

import io
import os
from array import array
from pathlib import Path

import orjson
import pytest

from dtflow.cli.view.source import (
    PARSE_ERROR_FIELD,
    SourceChangedError,
    open_source,
    read_stdin_source,
)


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


def test_jsonl_fast_tail_is_relative_until_history_is_indexed(tmp_path):
    p = _write(tmp_path, "tail.jsonl", [f'{{"i": {i}}}' for i in range(10)])
    src = open_source(p, tail_size=3)

    assert src.has_unindexed_history
    assert src.total == 3
    assert src.window(0, 3) == [{"i": 7}, {"i": 8}, {"i": 9}]
    assert src.row_numbers(0, 3) == [-3, -2, -1]
    assert isinstance(src._offsets, array) and src._offsets.itemsize == 8

    assert src.ensure_index()
    assert src.fully_indexed and src.total == 10
    assert src.window(4, 3) == [{"i": 4}, {"i": 5}, {"i": 6}]
    assert src.row_numbers(7, 3) == [7, 8, 9]


def test_static_jsonl_snapshot_does_not_absorb_appends_and_rejects_truncate(tmp_path):
    p = _write(tmp_path, "snapshot.jsonl", ['{"i": 0}', '{"i": 1}'])
    src = open_source(p)
    with p.open("ab") as f:
        f.write(b'{"i": 2}\n')

    assert src.total == 2
    assert list(src.iter_all()) == [{"i": 0}, {"i": 1}]
    assert src.window(0, 10) == [{"i": 0}, {"i": 1}]

    p.write_bytes(b'{"new": true}\n')
    with pytest.raises(SourceChangedError, match="截断"):
        src.window(0, 2)


def test_follow_waits_for_partial_line_then_commits_once(tmp_path):
    p = Path(tmp_path) / "live.jsonl"
    p.write_bytes(b'{"i":0}\n{"i":')
    src = open_source(p, tail_size=3, follow=True)

    assert src.window(0, 10) == [{"i": 0}]
    waiting = src.poll()
    assert waiting.kind == "unchanged" and waiting.pending

    with p.open("ab") as f:
        f.write(b"1}\nnot json\n")
    update = src.poll()
    assert [row.get("i") for row in update.rows] == [1, None]
    assert PARSE_ERROR_FIELD in update.rows[1]
    assert update.added == 2 and not update.pending
    assert src.poll().added == 0  # 同一批不重复提交


def test_follow_is_bounded_and_detects_rotation_and_copytruncate(tmp_path):
    p = _write(tmp_path, "live.jsonl", [f'{{"i": {i}}}' for i in range(5)])
    src = open_source(p, tail_size=3, follow=True)
    with p.open("ab") as f:
        f.write(b'{"i":5}\n{"i":6}\n')
    assert src.poll().added == 2
    assert src.total == 3
    assert src.window(0, 3) == [{"i": 4}, {"i": 5}, {"i": 6}]

    replacement = Path(tmp_path) / "next.jsonl"
    replacement.write_bytes(b'{"generation":1}\n')
    os.replace(replacement, p)
    rotated = src.poll()
    assert rotated.kind == "rotation" and rotated.generation == 1
    assert rotated.rows == [{"generation": 1}]

    # copytruncate 保持 inode，但长度退回，也应切新代。
    p.write_bytes(b'{"g":2}\n')
    copied = src.poll()
    assert copied.kind == "rotation" and copied.generation == 2
    assert copied.rows == [{"g": 2}]


def test_tail_reader_handles_blank_lines_utf8_and_a_line_larger_than_block(tmp_path):
    p = Path(tmp_path) / "large.jsonl"
    huge = "中" * 100_000
    p.write_text(
        '{"i":0}\n\n' + orjson.dumps({"text": huge}).decode() + '\n  \n{"i":2}',
        encoding="utf-8",
    )
    src = open_source(p, tail_size=2)
    rows = src.window(0, 2)
    assert rows[0] == {"text": huge}
    assert rows[1] == {"i": 2}  # 静态尾窗包含无末尾换行的合法记录


def test_full_iteration_keeps_its_high_water_while_follow_poll_adds_rows(tmp_path):
    p = _write(tmp_path, "high-water.jsonl", [f'{{"i": {i}}}' for i in range(4)])
    src = open_source(p, tail_size=2, follow=True)
    assert src.ensure_index()

    scan = src.iter_all()
    assert next(scan) == {"i": 0}  # 此时捕获 total=4 / byte_end
    with p.open("ab") as f:
        f.write(b'{"i":4}\n')
    assert src.poll().added == 1

    assert list(scan) == [{"i": 1}, {"i": 2}, {"i": 3}]
    assert src.total == 5 and src.window(4, 1) == [{"i": 4}]


def test_follow_waits_through_missing_rotation_path(tmp_path):
    p = _write(tmp_path, "live.jsonl", ['{"i":0}'])
    src = open_source(p, tail_size=10, follow=True)
    moved = tmp_path / "live.jsonl.1"
    os.replace(p, moved)
    assert src.poll().kind == "missing"

    p.write_bytes(b'{"i":1}\n')
    update = src.poll()
    assert update.kind == "rotation" and update.rows == [{"i": 1}]


def test_jsonl_head_indexes_only_requested_rows_and_resumes(tmp_path, monkeypatch):
    import dtflow.cli.view.source as source

    p = _write(tmp_path, "head.jsonl", [f'{{"i":{i}}}' for i in range(100)])
    scans = []
    scan_offsets = source._scan_offsets

    def track(*args, **kwargs):
        result = scan_offsets(*args, **kwargs)
        scans.append((args[1], result[1], len(result[0])))
        return result

    monkeypatch.setattr(source, "_scan_offsets", track)
    src = open_source(p, initial_size=3)
    assert src.total == 3 and src.has_unindexed_tail and not src.has_unindexed_history
    assert src.row_numbers(0, 3) == [0, 1, 2]
    assert src.window(0, 3) == [{"i": 0}, {"i": 1}, {"i": 2}]
    assert scans == [(0, 24, 3)]  # 首窗不读后面的 97 行

    assert src.ensure_rows(6)
    assert scans[-1] == (24, 48, 3)  # 下一窗接着读，不重扫文件头
    assert src.window(3, 3) == [{"i": 3}, {"i": 4}, {"i": 5}]
    assert src.ensure_rows(4)
    assert len(scans) == 2
    assert src.ensure_index()
    assert scans[-1][0] == 48
    assert src.total == 100 and src.fully_indexed
    assert list(src.iter_all()) == [{"i": i} for i in range(100)]


def test_jsonl_head_cancel_keeps_prefix_and_snapshot_excludes_appends(tmp_path):
    import threading

    p = _write(tmp_path, "snapshot-head.jsonl", [f'{{"i":{i}}}' for i in range(6)])
    src = open_source(p, initial_size=2)
    cancel = threading.Event()
    cancel.set()
    assert not src.ensure_rows(4, cancel=cancel)
    assert not src.ensure_index(cancel=cancel)
    assert src.total == 2 and src.window(0, 2) == [{"i": 0}, {"i": 1}]
    with p.open("ab") as f:
        f.write(b'{"i":6}\n')
    assert src.ensure_index()
    assert src.total == 6
    assert list(src.iter_all()) == [{"i": i} for i in range(6)]


def test_jsonl_head_blanks_bad_lines_and_unterminated_last_row(tmp_path):
    p = tmp_path / "head.ndjson"
    p.write_bytes(b' \r\n{"i":0}\r\n\t\r\nbad json\r\n{"i":2}')
    src = open_source(p, initial_size=1)
    assert src.window(0, 1) == [{"i": 0}]
    assert src.ensure_rows(2)
    assert PARSE_ERROR_FIELD in src.window(1, 1)[0]
    assert src.ensure_rows(3)
    assert src.fully_indexed and src.total == 3
    assert src.window(2, 1) == [{"i": 2}]
    assert src.row_numbers(0, 3) == [0, 1, 2]


@pytest.mark.parametrize("replace", [True, False])
def test_jsonl_head_rejects_changed_snapshot_during_extension(tmp_path, replace):
    p = _write(tmp_path, "head.jsonl", [f'{{"i":{i}}}' for i in range(10)])
    src = open_source(p, initial_size=2)
    if replace:
        replacement = _write(tmp_path, "replacement.jsonl", ['{"new":true}'] * 10)
        os.replace(replacement, p)
    else:
        p.write_bytes(b'{"i":0}\n')
    with pytest.raises(SourceChangedError):
        src.ensure_index()
    assert src.total == 2 and not src.fully_indexed
