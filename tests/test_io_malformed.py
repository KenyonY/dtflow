"""坏行在三类路径上的行为必须各自正确, 且都能定位到行。

- 浏览 (dt view): 显示出来, 绝不拦门 —— 见 tests/test_view_source.py
- 预览/采样 (head/tail/sample): 跳过, 但必须吭声 (dt sample -o 会写出新文件)
- 加载/流式 (clean/transform/dedupe): 抛错, 因为静默丢行等于悄悄改数据
"""

import pytest

from dtflow.storage.io import _load_jsonl, _stream_head_jsonl, _stream_tail_jsonl


@pytest.fixture
def bad_file(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_bytes(b'{"a":1}\n{"a":2}\n{ broken here\n{"a":4}\n')
    return p


def test_load_jsonl_raises_with_line_number(bad_file):
    # 抛错是对的 (这条路径喂给会写文件的操作), 但必须说清第几行、坏成什么样
    with pytest.raises(ValueError) as ei:
        _load_jsonl(bad_file)
    msg = str(ei.value)
    assert "第 3 行" in msg and "broken here" in msg and "dt view" in msg


def test_stream_head_skips_but_warns(bad_file, capsys):
    rows = _stream_head_jsonl(bad_file, 10)
    assert [r["a"] for r in rows] == [1, 2, 4]  # 坏行跳过
    err = capsys.readouterr().err
    assert "已跳过" in err and "第 3 行" in err  # 但不是无声无息


def test_stream_tail_skips_but_warns(bad_file, capsys):
    rows = _stream_tail_jsonl(bad_file, 10)
    assert [r["a"] for r in rows] == [1, 2, 4]
    assert "第 3 行" in capsys.readouterr().err


def test_clean_file_is_untouched_by_the_warning_path(tmp_path, capsys):
    # 没有坏行时不该冒出任何警告 (免得把正常输出污染成"看起来出事了")
    p = tmp_path / "ok.jsonl"
    p.write_bytes(b'{"a":1}\n{"a":2}\n')
    assert len(_stream_head_jsonl(p, 10)) == 2
    assert "已跳过" not in capsys.readouterr().err
