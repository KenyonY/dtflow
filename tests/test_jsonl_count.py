"""快速计数必须保持浏览器的非空行、坏行和固定快照语义。"""

import gzip
import threading
import zlib

import polars as pl
import pytest

from dtflow.utils.jsonl import count_jsonl_rows


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\n \t\r\n\v\f\n",
        b'{"a":1}\n\n {"a":2}',
        b'bad json\n{"a":1}\n',
        b"{}\n1\nnull\n[]",
        b"\xff\n{}\n",
        b"\xef\xbb\xbf\n{}\n",
        b"\x1f\x8b broken compression\n{}",
        b"\x28\xb5\x2f\xfd broken compression\n{}",
        b"{broken",
        b" \r\n\v\f\n{}\n",
        gzip.compress(b"{}\n" * 7, mtime=0),
        zlib.compress(b"{}\n" * 7),
        b"{}\n" + b"\n".join(bytes([i]) for i in range(256) if i not in (11, 12)),
    ],
)
def test_native_count_preserves_all_nonempty_rows(tmp_path, data):
    p = tmp_path / "literal[1].jsonl"
    p.write_bytes(data)
    assert count_jsonl_rows(p) == sum(bool(line.strip()) for line in data.split(b"\n"))


def test_count_fixed_snapshot_excludes_later_appends(tmp_path):
    p = tmp_path / "snapshot.jsonl"
    original = b'{}\n{"incomplete":'
    p.write_bytes(original + b"true}\n{}\n")
    assert count_jsonl_rows(p, end=len(original)) == 2


def test_append_during_native_count_recounts_only_snapshot(tmp_path, monkeypatch):
    p = tmp_path / "append.jsonl"
    p.write_bytes(b"{}\n{}\n")
    original_scan = pl.scan_ndjson

    def append_then_scan(*args, **kwargs):
        with p.open("ab") as f:
            f.write(b"{}\n")
        return original_scan(*args, **kwargs)

    monkeypatch.setattr(pl, "scan_ndjson", append_then_scan)
    assert count_jsonl_rows(p) == 2


def test_count_cancel_before_scan(tmp_path):
    p = tmp_path / "cancel.jsonl"
    p.write_bytes(b"{}\n")
    cancel = threading.Event()
    cancel.set()
    assert count_jsonl_rows(p, cancel=cancel) is None


def test_count_cancel_requests_native_query_cancellation(tmp_path, monkeypatch):
    p = tmp_path / "cancel.jsonl"
    p.write_bytes(b"{}\n")
    cancel = threading.Event()
    cancelled = []

    class PendingQuery:
        def select(self, *args):
            return self

        def collect(self, **kwargs):
            return self

        def fetch(self):
            cancel.set()
            return None

        def cancel(self):
            cancelled.append(True)

    monkeypatch.setattr(pl, "scan_ndjson", lambda *args, **kwargs: PendingQuery())
    assert count_jsonl_rows(p, cancel=cancel) is None
    assert cancelled == [True]


def test_count_rejects_truncated_snapshot_and_wrong_identity(tmp_path):
    p = tmp_path / "changed.jsonl"
    p.write_bytes(b"{}\n")
    with pytest.raises(OSError, match="截断"):
        count_jsonl_rows(p, end=10)
    with pytest.raises(OSError, match="替换"):
        count_jsonl_rows(p, expected_identity=(-1, -1))
