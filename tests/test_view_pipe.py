"""view 内管道 (dtflow/cli/view/pipe.py): 真实子进程跑 dt, stdin/stdout 都是 NDJSON。"""

import os
import sys
import threading

import pytest

from dtflow.cli.view.pipe import _env, error_message, run_pipe, shell_form

ROWS = [{"a": 1, "s": "x"}, {"a": 2, "s": "y"}, {"a": 3, "s": "z"}]


def _run(cmd, rows=ROWS, cancel=None):
    return run_pipe(cmd, iter(rows), cancel or threading.Event())


class TestRunPipe:
    def test_filter_and_select_through_real_dt(self):
        r = _run('dt filter - "x.a > 1" | dt select - "a"')
        assert r.returncode == 0 and r.fed == 3
        assert r.rows == [{"a": 2}, {"a": 3}]
        assert r.stderr_tail  # dt 的 stderr 汇总 (输出 N 条) 被收进尾巴

    def test_env_prefers_this_interpreter(self):
        assert _env()["PATH"].split(os.pathsep)[0] == os.path.dirname(sys.executable)

    def test_bad_output_line_becomes_placeholder_row(self):
        r = _run("printf 'not json\\n{\"ok\":1}\\n'")
        assert r.returncode == 0
        assert r.rows[0]["_parse_error"] and r.rows[0]["_raw_line"] == "not json"
        assert r.rows[1] == {"ok": 1}

    def test_nonzero_exit_and_structured_message(self):
        r = _run('dt filter - "x.a >"')
        assert r.returncode == 2 and r.rows == []
        msg = error_message(r.stderr_tail)
        assert "x.a >" in msg and "^" in msg  # JSON 错误的 message + suggestion (caret)
        assert error_message("plain\nlast line") == "plain\nlast line"
        assert error_message("") == "(没有错误输出)"

    def test_downstream_exiting_early_is_not_an_error(self):
        many = [{"a": i} for i in range(20000)]
        r = _run("dt head - 1", rows=many)
        assert r.returncode == 0 and r.rows == [{"a": 0}]

    def test_cancel_kills_process(self):
        cancel = threading.Event()
        rows = ({"a": i} for i in range(10**9))  # 永远喂不完

        def stop_soon():
            import time

            time.sleep(0.2)
            cancel.set()

        threading.Thread(target=stop_soon).start()
        r = run_pipe("cat", rows, cancel)
        assert r.rows is None and r.fed > 0

    def test_progress_callback(self):
        seen = []
        run_pipe(
            "cat > /dev/null", iter({"a": i} for i in range(12000)), threading.Event(), seen.append
        )
        assert seen == [5000, 10000]


@pytest.mark.parametrize(
    "cmd,expected",
    [
        (
            'dt filter - "x.a > 1" | dt head - 5',
            "dt filter 'my file.jsonl' \"x.a > 1\" | dt head - 5",
        ),
        ("dt select - a", "dt select 'my file.jsonl' a"),
        ("dt shuffle -", "dt shuffle 'my file.jsonl'"),
        ("jq -c .a | dt head - 3", "dt concat 'my file.jsonl' | jq -c .a | dt head - 3"),
        ("dt group --by x.s -", "dt concat 'my file.jsonl' | dt group --by x.s -"),
    ],
)
def test_shell_form(cmd, expected):
    assert shell_form(cmd, "my file.jsonl") == expected
