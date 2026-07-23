"""dt view 入口检查: 与其他命令共用同一套存在性/格式门禁与退出码。

view 曾是唯一绕开这套约定的命令 (自己 print + SystemExit, 且完全不查格式),
于是 dt view x.md 会一路把 markdown 当 jsonl 解析, 最后抛"第 1 行不是合法 JSON"
——答非所问。
"""

import pytest
import typer

from dtflow.cli.view import view


def _run(monkeypatch, path, isatty=True):
    """跑 view 并返回退出码 (die_* 抛 typer.Exit, 与其他命令一致)。"""
    monkeypatch.setattr("sys.stdout.isatty", lambda: isatty, raising=False)
    with pytest.raises(typer.Exit) as ei:
        view(str(path))
    return ei.value.exit_code


def test_unsupported_format_says_so(monkeypatch, tmp_path, capsys):
    p = tmp_path / "readme.md"
    p.write_text("# 标题\n\n正文\n")
    assert _run(monkeypatch, p) == 2  # USAGE, 与 dt head 一致
    err = capsys.readouterr().err
    assert "unsupported_format" in err and "支持的格式" in err


def test_missing_file_uses_shared_not_found_error(monkeypatch, tmp_path, capsys):
    assert _run(monkeypatch, tmp_path / "nope.jsonl") == 3  # NOT_FOUND
    assert "file_not_found" in capsys.readouterr().err


def test_format_is_checked_before_tty(monkeypatch, tmp_path, capsys):
    # 非 TTY 下也应先报"格式不支持": 那是关于文件本身的、更根本的问题
    p = tmp_path / "readme.md"
    p.write_text("# x\n")
    assert _run(monkeypatch, p, isatty=False) == 2
    assert "unsupported_format" in capsys.readouterr().err


def test_tty_requirement_is_structured(monkeypatch, tmp_path, capsys):
    p = tmp_path / "d.jsonl"
    p.write_bytes(b'{"a":1}\n')
    assert _run(monkeypatch, p, isatty=False) == 2
    err = capsys.readouterr().err
    assert "usage_error" in err and "dt head" in err  # 指明替代命令


@pytest.mark.parametrize("name", ["d.tsv", "d.ndjson"])
def test_readable_formats_are_not_gated_out(monkeypatch, tmp_path, name):
    """回归: .tsv/.ndjson 早就读得动 (有 _load_tsv / 落到 jsonl 分支),
    却漏在 SUPPORTED_FORMATS 外, 被所有命令挡在门外。"""
    from dtflow.cli.common import _check_file_format

    p = tmp_path / name
    p.write_bytes(b"a\tb\n1\t2\n" if name.endswith(".tsv") else b'{"a":1}\n')
    assert _check_file_format(p) is True  # 不 die


def test_supported_formats_matches_loader():
    """门禁列表不得比实际能读的格式窄 —— 窄了就是把能用的文件拒之门外。"""
    from pathlib import Path

    from dtflow.cli.common import SUPPORTED_FORMATS
    from dtflow.storage.io import _detect_format

    for ext in SUPPORTED_FORMATS:
        assert _detect_format(Path(f"x{ext}"))  # 每个都能映射到一个 loader
    # 反向: io 明确列出的扩展名都应在门禁内
    for ext in (".csv", ".tsv", ".jsonl", ".ndjson", ".json", ".parquet", ".arrow", ".feather"):
        assert ext in SUPPORTED_FORMATS, f"{ext} 能读却被门禁挡住"


def test_streaming_formats_are_actually_streamable(tmp_path):
    """流式列表里的每种格式都必须真的能流式读 —— 列表与实现脱节过一次:
    .ndjson 和 .jsonl 是同一种东西, 却因为 streaming.py 里 `ext == ".jsonl"` 的
    字符串比较掉出快路径, 悄悄变成全量入内存。分发改走 _detect_format 后不再有这种漏。
    """
    from dtflow.cli.common import STREAMING_FORMATS as CLI_SF
    from dtflow.streaming import STREAMING_FORMATS, load_stream

    assert STREAMING_FORMATS == CLI_SF  # 两份列表必须同步

    nd = tmp_path / "d.ndjson"
    nd.write_bytes(b'{"a":1,"b":"x"}\n{"a":2,"b":"y"}\n')
    assert list(load_stream(str(nd))) == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]

    tsv = tmp_path / "d.tsv"
    tsv.write_text("a\tb\n1\tx\n2\ty\n")
    rows = list(load_stream(str(tsv)))
    assert rows == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]  # 分隔符生效, 不是单列


def test_streaming_roundtrip_tsv_and_ndjson(tmp_path):
    # 流式写也要认这两种 (此前 save 按 ext 分发, tsv 会被当 jsonl 写)
    from dtflow.streaming import load_stream

    src = tmp_path / "s.ndjson"
    src.write_bytes(b'{"a":1,"b":"x"}\n{"a":2,"b":"y"}\n')

    out_tsv = tmp_path / "o.tsv"
    load_stream(str(src)).save(str(out_tsv), show_progress=False)
    assert out_tsv.read_text().splitlines()[0] == "a\tb"  # 制表符表头, 不是逗号
    assert list(load_stream(str(out_tsv))) == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]

    out_nd = tmp_path / "o.ndjson"
    load_stream(str(out_tsv)).save(str(out_nd), show_progress=False)
    assert list(load_stream(str(out_nd))) == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]


def test_row_count_matches_for_tsv_and_ndjson(tmp_path):
    # 进度条依赖它; tsv 走 csv 分支时必须带上分隔符, 否则行数/列数都不对
    from dtflow.streaming import _count_rows_fast

    nd = tmp_path / "d.ndjson"
    nd.write_bytes(b'{"a":1}\n{"a":2}\n{"a":3}\n')
    assert _count_rows_fast(str(nd)) == 3

    tsv = tmp_path / "d.tsv"
    tsv.write_text("a\tb\n1\tx\n2\ty\n")
    assert _count_rows_fast(str(tsv)) == 2  # 表头不算数据行
