"""在 view 里跑一段 shell 管道: 当前数据源的全部行以 NDJSON 喂给它的 stdin, 它的 stdout
(NDJSON) 成为新的浏览数据。

刻意用 shell 子进程而不是进程内解析 dt 子命令: 用户输入的就是终端里那句
``dt filter - "…" | dt sort - --by …``, 不需要一张"CLI 参数 → pipeline 步骤"的映射表跟着
CLI 长期同步; 新加的选项自动可用, 顺手也能接 jq/grep。不做沙箱, 与表达式一致 —— 这本来
就是用户自己的终端。

本模块不 import textual, 可单测。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional

import orjson

from ...i18n import t
from .source import _loads

_STDERR_KEEP = 4096  # 只留 stderr 末尾这么多字节: 错误信息在最后, 前面的进度噪音不要


@dataclass(frozen=True)
class PipeResult:
    rows: Optional[List[Dict]]  # None = 被取消
    returncode: int
    stderr_tail: str
    fed: int  # 喂进去的行数


def _env() -> Dict[str, str]:
    """子进程环境: 把当前解释器所在目录前置到 PATH, 保证 ``dt`` 解析到运行 view 的这一份。"""
    env = dict(os.environ)
    bin_dir = os.path.dirname(sys.executable)
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    return env


def run_pipe(
    cmd: str,
    rows: Iterable[Dict],
    cancel: threading.Event,
    progress_cb: Optional[Callable[[int], None]] = None,
) -> PipeResult:
    """``sh -c cmd``: rows → stdin (NDJSON), stdout (NDJSON) → 行列表。

    喂入在单独线程里做 (下游可能先读完再出, 也可能像 head 那样提前退出), 主线程读 stdout,
    第三个线程收 stderr 尾巴。cancel 置位 → kill, 返回 rows=None。成败不在这里判, 交给
    调用方看 returncode。
    """
    # 新进程组: 取消时 killpg 整组 —— 只杀 sh 的话管道各段还在跑, 读 stdout 会一直等它们
    proc = subprocess.Popen(  # noqa: S603  用户自己敲的命令, 与表达式一样不做沙箱
        _shell_argv(cmd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env(),
        start_new_session=True,
    )
    assert proc.stdin and proc.stdout and proc.stderr
    fed = 0
    err_buf = bytearray()
    feed_error: List[BaseException] = []

    def feed() -> None:
        nonlocal fed
        try:
            for row in rows:
                if cancel.is_set():
                    break
                proc.stdin.write(orjson.dumps(row) + b"\n")
                fed += 1
                if progress_cb is not None and fed % 5000 == 0:
                    progress_cb(fed)
        except (BrokenPipeError, OSError):
            pass  # 下游提前退出 (dt head / head): 不是错误, 剩下的行它本来就不要
        except Exception as e:  # noqa: BLE001  数据源迭代本身出错 (坏文件): 带回主线程报出
            feed_error.append(e)
            cancel.set()
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    def drain_stderr() -> None:
        for chunk in iter(lambda: proc.stderr.read(1024), b""):
            err_buf.extend(chunk)
            if len(err_buf) > 2 * _STDERR_KEEP:
                del err_buf[:-_STDERR_KEEP]

    def watch_cancel() -> None:
        cancel.wait()
        if proc.poll() is None:
            _kill_group(proc)

    threads = [
        threading.Thread(target=feed, daemon=True),
        threading.Thread(target=drain_stderr, daemon=True),
        threading.Thread(target=watch_cancel, daemon=True),
    ]
    for th in threads:
        th.start()
    out: List[Dict] = []
    for line in proc.stdout:
        line = line.strip()
        if line:
            out.append(_loads(line))
    proc.wait()
    cancelled = cancel.is_set()
    cancel.set()  # 放掉 watch_cancel; 进程已结束, kill 是空操作
    for th in threads:
        th.join(timeout=2)
    tail = bytes(err_buf[-_STDERR_KEEP:]).decode("utf-8", "replace")
    if feed_error:
        raise feed_error[0]
    return PipeResult(None if cancelled else out, proc.returncode, tail, fed)


def _shell_argv(cmd: str) -> List[str]:
    """能用 bash 就 ``bash -o pipefail``: /bin/sh 常是 dash, 管道退出码只看末段, 于是
    ``dt filter - "x.a >" | dt head - 5`` 会以 0 退出、把"语法错误"伪装成"0 行"。"""
    bash = shutil.which("bash")
    if bash:
        return [bash, "-o", "pipefail", "-c", cmd]
    return ["/bin/sh", "-c", cmd]


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def dt_error(stderr_tail: str) -> Optional[str]:
    """stderr 里最后一个 dt 结构化错误 (``{"error": …, "message": …}``) 的 message
    (有 suggestion 一并带上); 没有则 None。

    错误对象不一定在末尾: 上游段的 "filter: N rows written" 汇总可能排在它后面
    (各段并行, 谁先写完谁在前), 所以从每个行首 ``{`` 起试着解出完整对象。
    """
    decoder = json.JSONDecoder()
    found = None
    for m in re.finditer(r"^\{", stderr_tail, re.MULTILINE):
        try:
            obj, _ = decoder.raw_decode(stderr_tail, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and "error" in obj and "message" in obj:
            found = obj
    if found is None:
        return None
    msg = str(found["message"])
    if found.get("suggestion"):
        msg += "\n" + str(found["suggestion"])
    return msg


def error_message(stderr_tail: str) -> str:
    """stderr 尾巴 → 一句给人看的错误: 有 dt 的结构化错误就用它, 否则末尾几行。"""
    text = stderr_tail.strip()
    if not text:
        return t("(no error output)", "(没有错误输出)")
    return dt_error(text) or "\n".join(text.splitlines()[-3:])


_LEADING_DT_STDIN = re.compile(r"^(\s*dt\s+\S+\s+)-(?=\s|$)")


def shell_form(cmd: str, src: str) -> str:
    """view 里跑的管道 → 能在 shell 里对源文件重跑的命令 (P 用)。

    首段形如 ``dt filter - …`` 就把那个 ``-`` 换成源文件; 否则前面接一段恒等流
    ``dt concat FILE |``。
    """
    quoted = shlex.quote(src)
    replaced, n = _LEADING_DT_STDIN.subn(lambda m: m.group(1) + quoted, cmd, count=1)
    if n:
        return replaced
    return f"dt concat {quoted} | {cmd.strip()}"
