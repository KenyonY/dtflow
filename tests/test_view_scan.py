"""dt view 扫描层: 约束 spec、并行分片、收紧与值行号表。

并行路径用真实子进程跑 (把 PARALLEL_MIN_ROWS 压到 0, 小文件也走多进程),
否则 pickle/分片/合并这些只在跨进程时才暴露的问题测不出来。
"""

import orjson
import pytest

from dtflow.cli.view import scan
from dtflow.cli.view.scan import ScanSpec
from dtflow.cli.view.source import open_source

FMT = "openai_chat"


def _write(tmp_path, n=200):
    path = tmp_path / "d.jsonl"
    with open(path, "wb") as f:
        for i in range(n):
            f.write(
                orjson.dumps(
                    {
                        "messages": [
                            {"role": "user", "content": f"q{i} " + "x" * (i % 7)},
                            {"role": "assistant", "content": "ans" if i % 3 else "other"},
                        ],
                        "source": "a" if i % 2 else "b",
                    }
                )
            )
            f.write(b"\n")
    return path


def _source(tmp_path, n=200):
    src = open_source(_write(tmp_path, n))
    src.ensure_index()
    return src


@pytest.fixture
def parallel(monkeypatch):
    """强制走并行路径 (真实 fork 子进程), 测完关掉池。"""
    if not scan.parallel_available():
        pytest.skip("本平台无 fork, 并行路径不可用")
    monkeypatch.setattr(scan, "PARALLEL_MIN_ROWS", 0)
    yield
    scan.shutdown_pool()


# --------------------------------------------------------------------------- #
# 分片
# --------------------------------------------------------------------------- #
def test_parallel_ranges_cover_every_row_once(tmp_path):
    # 分片必须无缝无叠: 字节首尾相接, 行号连续, 合起来正好是全量
    src = _source(tmp_path, 200)
    ranges = src.parallel_ranges(7)
    assert ranges[0][0] == 0 and ranges[0][2] == 0
    rows = []
    for a, b, first in ranges:
        rows.extend(i for i, _ in scan._iter_chunk(str(src.path), a, b, first))
    assert rows == list(range(200))
    assert [b for _, b, _ in ranges][:-1] == [a for a, _, _ in ranges][1:]


def test_parallel_ranges_needs_full_index(tmp_path):
    # 索引没补全就不能分片: 偏移表不全, 行号对不上
    src = open_source(_write(tmp_path, 200), initial_size=10)
    assert not src.fully_indexed
    assert src.parallel_ranges(4) is None


def test_memory_source_has_no_ranges(tmp_path):
    # 非 jsonl (csv/parquet/stdin) 全量在内存, 没有字节区间可分 → 串行
    path = tmp_path / "d.json"
    path.write_bytes(orjson.dumps([{"a": 1}]))
    assert open_source(path).parallel_ranges(4) is None


# --------------------------------------------------------------------------- #
# 并行 == 串行 (跨进程重建的谓词必须与主进程一致)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "spec",
    [
        ScanSpec(fmt=FMT, search="ans"),
        ScanSpec(fmt=FMT, search="re:q1[0-9] "),
        ScanSpec(fmt=FMT, wheres=("source==a",)),
        ScanSpec(fmt=FMT, wheres=("turns>=2", "chars>5")),
        ScanSpec(fmt=FMT, value_filters=(("source", ("a",)),)),
        ScanSpec(fmt=FMT, search="ans", wheres=("source==b",), sort_col="chars", sort_desc=True),
        ScanSpec(fmt=FMT, sort_col="chars"),  # 纯排序: 全部行按键重排
    ],
)
def test_parallel_matches_serial(tmp_path, monkeypatch, spec):
    src = _source(tmp_path)
    serial = scan.scan_rows(src, spec)
    if not scan.parallel_available():
        pytest.skip("本平台无 fork")
    monkeypatch.setattr(scan, "PARALLEL_MIN_ROWS", 0)
    try:
        assert scan.scan_rows(src, spec) == serial
    finally:
        scan.shutdown_pool()
    assert serial  # 每条 spec 都该有命中, 否则这条用例是空跑


def test_parallel_progress_and_cancel(tmp_path, parallel):
    import threading

    src = _source(tmp_path)
    seen = []
    spec = ScanSpec(fmt=FMT, search="q")
    scan.scan_rows(src, spec, progress=lambda d, t: seen.append((d, t)))
    assert seen and seen[-1] == (200, 200)  # 进度须走到全量

    cancel = threading.Event()
    cancel.set()
    assert scan.scan_rows(src, spec, cancel=cancel) is None


def test_serial_cancel(tmp_path):
    import threading

    src = _source(tmp_path)
    cancel = threading.Event()
    cancel.set()
    assert scan.scan_rows(src, ScanSpec(fmt=FMT, search="q"), cancel=cancel) is None


# --------------------------------------------------------------------------- #
# 收紧
# --------------------------------------------------------------------------- #
def test_is_refinement_rules():
    base = ScanSpec(fmt=FMT, search="a", wheres=("x>1",))
    assert scan.is_refinement(base, ScanSpec(fmt=FMT, search="a", wheres=("x>1", "y<2")))
    assert scan.is_refinement(ScanSpec(fmt=FMT), ScanSpec(fmt=FMT, search="a"))  # 从无到有加搜索
    assert scan.is_refinement(
        ScanSpec(fmt=FMT, value_filters=(("s", ("a", "b")),)),
        ScanSpec(fmt=FMT, value_filters=(("s", ("a",)),)),  # 值集收窄
    )
    assert not scan.is_refinement(None, base)  # 没有已落地约束
    assert not scan.is_refinement(base, ScanSpec(fmt=FMT, search="b", wheres=("x>1",)))  # 换搜索词
    assert not scan.is_refinement(base, ScanSpec(fmt=FMT, search="a"))  # 去掉一条 where
    assert not scan.is_refinement(
        base, ScanSpec(fmt=FMT, search="a", wheres=("y<2", "x>1"))
    )  # 不是追加
    assert not scan.is_refinement(
        ScanSpec(fmt=FMT, value_filters=(("s", ("a",)),)),
        ScanSpec(fmt=FMT, value_filters=(("s", ("a", "b")),)),  # 值集放宽
    )
    assert not scan.is_refinement(
        base, ScanSpec(fmt=FMT, search="a", wheres=("x>1",), sort_col="c")
    )


def test_refine_base_rejects_big_subset():
    # 子集太大时逐行回读不划算, 交给全量并行重扫
    old, new = ScanSpec(fmt=FMT), ScanSpec(fmt=FMT, search="a")
    assert scan.refine_base(old, new, list(range(50)), 1000) == list(range(50))
    assert scan.refine_base(old, new, list(range(500)), 1000) is None
    assert scan.refine_base(old, new, None, 1000) is None


def test_refine_rows_equals_full_scan(tmp_path):
    src = _source(tmp_path)
    old = ScanSpec(fmt=FMT, search="ans")
    new = ScanSpec(fmt=FMT, search="ans", wheres=("source==a",))
    subset = scan.scan_rows(src, old)
    assert scan.refine_rows(src, subset, new) == scan.scan_rows(src, new)


def test_refine_rows_keeps_sorted_order(tmp_path):
    # 已按键排好的子集收紧后, 顺序原样保留 (不该退回文件顺序)
    src = _source(tmp_path)
    spec = ScanSpec(fmt=FMT, search="ans", sort_col="chars", sort_desc=True)
    subset = scan.scan_rows(src, spec)
    tighter = ScanSpec(
        fmt=FMT, search="ans", wheres=("source==a",), sort_col="chars", sort_desc=True
    )
    refined = scan.refine_rows(src, subset, tighter)
    assert refined == [i for i in subset if i in set(refined)]
    assert refined != sorted(refined)  # 确实不是文件顺序


# --------------------------------------------------------------------------- #
# 值 → 行号表
# --------------------------------------------------------------------------- #
def test_scan_values_rows_match_full_scan(tmp_path, parallel):
    src = _source(tmp_path)
    serial_spec = ScanSpec(fmt=FMT)
    values = scan.scan_values(src, "source", serial_spec)
    assert set(values) == {"a", "b"}
    assert sum(len(v) for v in values.values()) == src.total  # 覆盖全部行
    for rows in values.values():
        assert list(rows) == sorted(rows)  # 各表行号升序
    picked = scan.merge_value_rows(values, ["a"])
    assert picked == scan.scan_rows(src, ScanSpec(fmt=FMT, value_filters=(("source", ("a",)),)))


def test_scan_values_applies_other_constraints(tmp_path):
    # 算候选值时带上"除本列外"的约束, 本列自己的约束要排除掉 (否则筛掉的值加不回来)
    src = _source(tmp_path)
    spec = ScanSpec(fmt=FMT, wheres=("source==a",))
    values = scan.scan_values(src, "turns", spec)
    assert sum(len(v) for v in values.values()) == len(scan.scan_rows(src, spec))
    assert ScanSpec(fmt=FMT, value_filters=(("turns", ("2",)),)).without_column(
        "turns"
    ) == ScanSpec(fmt=FMT)


def test_scan_values_parallel_matches_serial(tmp_path, monkeypatch):
    src = _source(tmp_path)
    spec = ScanSpec(fmt=FMT)
    serial = {k: list(v) for k, v in scan.scan_values(src, "source", spec).items()}
    if not scan.parallel_available():
        pytest.skip("本平台无 fork")
    monkeypatch.setattr(scan, "PARALLEL_MIN_ROWS", 0)
    try:
        assert {k: list(v) for k, v in scan.scan_values(src, "source", spec).items()} == serial
    finally:
        scan.shutdown_pool()
