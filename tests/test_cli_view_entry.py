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


def test_negative_num_is_accepted_without_double_dash(monkeypatch, tmp_path):
    """Click 默认把 -100 当选项；view 必须把它作为负整数位置参数。"""
    from typer.testing import CliRunner

    import dtflow.__main__ as cli

    p = tmp_path / "d.jsonl"
    p.write_bytes(b'{"i":1}\n')
    called = {}

    def fake_view(filename, **kwargs):
        called.update(filename=filename, **kwargs)

    monkeypatch.setattr(cli, "_view", fake_view)
    result = CliRunner().invoke(cli.app, ["view", str(p), "-100"])
    assert result.exit_code == 0, result.output
    assert called["cap"] == 100 and called["tail"] is True and called["follow"] is False


def test_follow_uses_num_as_tail_capacity(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    import dtflow.__main__ as cli

    p = tmp_path / "d.ndjson"
    p.write_bytes(b'{"i":1}\n')
    called = {}
    monkeypatch.setattr(
        cli,
        "_view",
        lambda filename, **kwargs: called.update(filename=filename, **kwargs),
    )

    result = CliRunner().invoke(cli.app, ["view", str(p), "250", "--follow"])
    assert result.exit_code == 0, result.output
    assert called["cap"] == 250 and called["follow"] is True


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["d.jsonl", "0"], "必须大于 0"),
        (["d.jsonl", "-10", "--offset", "2"], "-NUM 不能与 --offset"),
        (["d.jsonl", "--follow", "--offset", "2"], "--follow 不能与 --offset"),
        (["d.jsonl", "--follow", "--sort=-i"], "--follow 不能与启动排序"),
        (["d.csv", "--follow"], "--follow 仅支持 JSONL/NDJSON"),
        (["-", "--follow"], "--follow 不支持 stdin"),
    ],
)
def test_view_tail_and_follow_conflicts_are_usage_errors(args, message):
    from typer.testing import CliRunner

    from dtflow.__main__ import app

    result = CliRunner().invoke(app, ["view", *args])
    assert result.exit_code == 2
    assert '"error": "usage_error"' in result.output
    assert message in result.output


@pytest.mark.parametrize("offset", [0, 5, 100])
def test_view_opens_only_through_requested_window(monkeypatch, tmp_path, offset):
    from dtflow.cli.view.app import ViewApp

    p = tmp_path / "d.jsonl"
    p.write_text("".join(f'{{"i":{i}}}\n' for i in range(20)))
    opened = []
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr(ViewApp, "run", lambda app: opened.append(app))
    view(str(p), cap=3, offset=offset)
    app = opened[0]
    assert app.source.total == min(offset + 3, 20)
    assert app.source.fully_indexed == (offset + 3 >= 20)
    start = min(offset, 19)
    assert app.all_rows == [{"i": i} for i in range(start, min(start + 3, 20))]
