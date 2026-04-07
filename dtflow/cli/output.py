"""
Agent 友好的 CLI 输出基础设施。

这个模块是整个 CLI 的输出契约层：
- stdout 只承载数据（JSON/NDJSON/CSV/Table）
- stderr 承载一切人类/agent 可读的消息（进度、警告、错误）
- 退出码语义稳定，遵循 Agent CLI Guide
- TTY/非 TTY 自动适配：TTY 默认 table + 彩色，非 TTY 默认 ndjson + 纯文本

所有 CLI 命令都应该通过这里的 `die / log / emit_data / emit_action` 与外界交互，
而不是直接调用 `print` 或 `rich.Console()`。
"""

from __future__ import annotations

import csv
import io
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, NoReturn, Optional, Union

import orjson
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# ============================================================================
# 退出码
# ============================================================================


class ExitCode:
    """语义化退出码。

    Agent 应当通过退出码判断命令结果，而不是解析 stderr 文本。
    """

    SUCCESS = 0  # 成功
    GENERAL = 1  # 一般错误（运行时、IO 等）
    USAGE = 2  # 参数/用法错误
    NOT_FOUND = 3  # 资源未找到（文件、字段等）
    PERMISSION = 4  # 权限错误
    CONFLICT = 5  # 冲突/已存在
    DRY_RUN_OK = 10  # dry-run 预演成功

    @classmethod
    def as_dict(cls) -> dict:
        return {
            "0": "success",
            "1": "general_error",
            "2": "usage_error",
            "3": "not_found",
            "4": "permission_denied",
            "5": "conflict",
            "10": "dry_run_ok",
        }


# ============================================================================
# CLI 全局状态（由 @app.callback 注入）
# ============================================================================


@dataclass
class CLIState:
    """CLI 全局运行状态。

    由 `dtflow/__main__.py` 中的 `@app.callback()` 通过 `set_state` 注入，
    各命令和本模块的输出函数通过 `get_state()` 读取。
    """

    fmt: Optional[str] = None  # 用户通过 --format 显式指定的格式
    no_color: bool = False  # --no-color
    yes: bool = False  # --yes (跳过所有确认)
    verbose: bool = False  # --verbose
    quiet: bool = False  # --quiet


_state: CLIState = CLIState()


def set_state(state: CLIState) -> None:
    global _state
    _state = state


def get_state() -> CLIState:
    return _state


# ============================================================================
# 环境检测
# ============================================================================


def is_stdout_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def is_stderr_tty() -> bool:
    try:
        return sys.stderr.isatty()
    except Exception:
        return False


def use_color() -> bool:
    """是否使用颜色输出。

    规则（优先级从高到低）：
    1. `--no-color` 明确禁用
    2. 环境变量 `NO_COLOR` 存在 → 禁用
    3. `TERM=dumb` → 禁用
    4. stderr 非 TTY → 禁用
    """
    if get_state().no_color:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return is_stderr_tty()


def default_format() -> str:
    """默认输出格式。

    - 用户通过 `--format` 显式指定时，使用用户指定值
    - 非 TTY → `ndjson`（agent 最友好）
    - TTY → `table`（人类最友好）
    """
    state = get_state()
    if state.fmt:
        return state.fmt
    return "table" if is_stdout_tty() else "ndjson"


def resolve_format(fmt: Optional[str] = None, default_for_tty: str = "table") -> str:
    """决定某条命令最终使用的输出格式。

    解析优先级：
    1. 命令级 `--format`
    2. 全局 `--format`（来自 callback）
    3. 非 TTY → `ndjson`
    4. TTY → `default_for_tty`（报告类命令可指定 `json`，records 类命令应给 `table`）
    """
    if fmt:
        return fmt
    state = get_state()
    if state.fmt:
        return state.fmt
    return default_for_tty if is_stdout_tty() else "ndjson"


# ============================================================================
# Console：stderr 专用
# ============================================================================


def _make_stderr_console() -> Console:
    return Console(
        stderr=True,
        force_terminal=is_stderr_tty(),
        no_color=not use_color(),
        highlight=False,
    )


class _LazyConsole:
    """按需构造 Console，保证每次读取都能响应最新的 CLIState / 终端状态。"""

    def __getattr__(self, name: str) -> Any:
        return getattr(_make_stderr_console(), name)


stderr_console: Console = _LazyConsole()  # type: ignore[assignment]


def log(msg: str, *, style: Optional[str] = None) -> None:
    """写一条消息到 stderr。

    - quiet 模式下丢弃
    - 支持 rich 标记（如 `[yellow]...[/yellow]`）
    """
    if get_state().quiet:
        return
    console = _make_stderr_console()
    if style:
        console.print(msg, style=style)
    else:
        console.print(msg)


def log_panel(
    content: Union[str, Any], *, title: Optional[str] = None, style: str = "cyan"
) -> None:
    if get_state().quiet:
        return
    console = _make_stderr_console()
    console.print(Panel(content, title=title, border_style=style))


def log_table(table: Table) -> None:
    if get_state().quiet:
        return
    _make_stderr_console().print(table)


# ============================================================================
# 数据输出：emit_data / emit_action
# ============================================================================


def _json_dumps(obj: Any, *, indent: bool = True, sort_keys: bool = False) -> bytes:
    opts = 0
    if indent:
        opts |= orjson.OPT_INDENT_2
    if sort_keys:
        opts |= orjson.OPT_SORT_KEYS
    try:
        return orjson.dumps(obj, option=opts)
    except TypeError:
        # orjson 不原生支持某些类型，走兜底
        return orjson.dumps(obj, option=opts, default=_json_default)


def _json_default(o: Any) -> Any:
    # 常见兜底
    try:
        return str(o)
    except Exception:
        return repr(o)


def _write_stdout_bytes(data: bytes) -> None:
    try:
        sys.stdout.buffer.write(data)
        if not data.endswith(b"\n"):
            sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.flush()
    except BrokenPipeError:
        # 管道被下游关闭（如 `dt sample ... | head`），静默退出
        try:
            sys.stdout.close()
        except Exception:
            pass


def _write_stdout_text(text: str) -> None:
    try:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass


def emit_json(obj: Any, *, indent: bool = True) -> None:
    """把单个 JSON 对象写到 stdout。"""
    _write_stdout_bytes(_json_dumps(obj, indent=indent))


def emit_ndjson(items: Iterable[Any]) -> None:
    """把可迭代对象以 NDJSON 形式写到 stdout。"""
    for item in items:
        try:
            sys.stdout.buffer.write(orjson.dumps(item, default=_json_default))
            sys.stdout.buffer.write(b"\n")
        except BrokenPipeError:
            try:
                sys.stdout.close()
            except Exception:
                pass
            return
    try:
        sys.stdout.buffer.flush()
    except BrokenPipeError:
        pass


def emit_csv(items: List[dict], *, fields: Optional[List[str]] = None) -> None:
    """把记录列表以 CSV 形式写到 stdout。"""
    if not items:
        return
    if fields is None:
        # 以第一条记录的键作为字段序（保留插入顺序）
        fields = list(items[0].keys()) if isinstance(items[0], dict) else []
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for item in items:
        if isinstance(item, dict):
            row = {k: _csv_cell(item.get(k)) for k in fields}
            writer.writerow(row)
    _write_stdout_text(buf.getvalue())


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return orjson.dumps(value, default=_json_default).decode("utf-8")
    return str(value)


def emit_data(
    data: Any,
    *,
    format: Optional[str] = None,
    stream: bool = False,
    csv_fields: Optional[List[str]] = None,
    table_renderer: Optional[Any] = None,
) -> None:
    """写数据到 stdout，自动根据格式选择编码器。

    参数:
        data: 要输出的数据。ndjson/csv 期望 list，json 期望任意对象。
        format: 输出格式；为 None 时根据 TTY 自动决定。
        stream: True 时把 data 视作 generator（仅 ndjson 支持真正流式）。
        csv_fields: CSV 模式下的列顺序。
        table_renderer: `format="table"` 时的自定义渲染函数。如未提供，table 降级为 ndjson。
    """
    fmt = resolve_format(format)

    if fmt == "json":
        if stream:
            # 流式 + json 不兼容，收集成 list
            data = list(data)
        emit_json(data)
        return

    if fmt == "ndjson":
        if not isinstance(data, (list, tuple)) and not stream:
            # 单个对象当作 NDJSON 的单行
            emit_ndjson([data])
        else:
            emit_ndjson(data)
        return

    if fmt == "csv":
        if stream:
            data = list(data)
        if not isinstance(data, list):
            data = [data] if isinstance(data, dict) else list(data)
        emit_csv(data, fields=csv_fields)
        return

    if fmt == "table":
        if table_renderer is not None:
            table_renderer()
            return
        # 没有渲染器则降级为 ndjson，保证 stdout 仍然可被 agent 消费
        if stream:
            data = list(data)
        if isinstance(data, list):
            emit_ndjson(data)
        else:
            emit_ndjson([data])
        return

    # 未知格式兜底
    die(
        "usage_error",
        f"不支持的输出格式: {fmt}",
        suggestion="使用 --format=json|ndjson|csv|table",
        exit_code=ExitCode.USAGE,
    )


def emit_action(
    action: str,
    *,
    status: str = "ok",
    input_files: Optional[List[str]] = None,
    output: Optional[str] = None,
    stats: Optional[dict] = None,
    dry_run: bool = False,
    extra: Optional[dict] = None,
    exit_after: bool = True,
) -> None:
    """副作用命令统一的动作摘要。

    dry-run 模式下会以 ExitCode.DRY_RUN_OK (10) 退出；
    正常模式下不退出（由命令决定后续流程）。

    参数:
        action: "clean", "transform", "concat", ...
        status: "ok" | "dry_run" | 其它自定义状态
        input_files: 输入文件路径列表
        output: 输出文件路径
        stats: 统计信息字典（输入行数、输出行数、删除行数等）
        dry_run: 是否是 dry-run 结果
        extra: 其它需要附加到输出的字段
        exit_after: dry_run=True 时是否调用 sys.exit
    """
    payload: dict = {
        "action": action,
        "status": "dry_run" if dry_run else status,
        "dry_run": bool(dry_run),
    }
    if input_files is not None:
        payload["input"] = input_files if len(input_files) != 1 else input_files[0]
    if output is not None:
        payload["output"] = output
    if stats:
        payload["stats"] = stats
    if extra:
        payload.update(extra)

    fmt = resolve_format(None, default_for_tty="table")

    if fmt == "table":
        # TTY：把摘要渲染为 Panel 写到 stderr，stdout 保持干净
        _render_action_panel(payload)
    else:
        # 非 TTY / 显式 json|ndjson|csv：stdout JSON
        emit_json(payload)

    if dry_run and exit_after:
        raise typer.Exit(code=ExitCode.DRY_RUN_OK)


def _render_action_panel(payload: dict) -> None:
    status = payload.get("status", "ok")
    action = payload.get("action", "action")
    title = f"[bold]{action}[/bold] · {status}"
    lines: List[str] = []
    if "input" in payload:
        lines.append(f"[dim]input:[/dim] {payload['input']}")
    if "output" in payload:
        lines.append(f"[dim]output:[/dim] {payload['output']}")
    stats = payload.get("stats") or {}
    for k, v in stats.items():
        lines.append(f"[dim]{k}:[/dim] {v}")
    for k, v in payload.items():
        if k in {"action", "status", "dry_run", "input", "output", "stats"}:
            continue
        lines.append(f"[dim]{k}:[/dim] {v}")
    body = "\n".join(lines) if lines else "(no details)"
    border = "yellow" if payload.get("dry_run") else "green"
    log_panel(body, title=title, style=border)


# ============================================================================
# 结构化错误：CLIError / die
# ============================================================================


class CLIError(Exception):
    """机器可读的 CLI 错误。"""

    def __init__(
        self,
        error: str,
        message: str,
        *,
        suggestion: Optional[str] = None,
        retryable: bool = False,
        exit_code: int = ExitCode.GENERAL,
        context: Optional[dict] = None,
    ):
        super().__init__(message)
        self.error = error
        self.message = message
        self.suggestion = suggestion
        self.retryable = retryable
        self.exit_code = exit_code
        self.context = context or {}

    def to_dict(self) -> dict:
        payload: dict = {
            "error": self.error,
            "message": self.message,
            "retryable": self.retryable,
            "exit_code": self.exit_code,
        }
        if self.suggestion:
            payload["suggestion"] = self.suggestion
        if self.context:
            payload["context"] = self.context
        return payload


def die(
    error: str,
    message: str,
    *,
    suggestion: Optional[str] = None,
    retryable: bool = False,
    exit_code: int = ExitCode.GENERAL,
    context: Optional[dict] = None,
) -> NoReturn:
    """立即以结构化错误终止命令。

    行为：
    - 非 TTY 或显式 JSON 格式：把错误 JSON 写到 stderr
    - TTY table 模式：彩色文本写到 stderr
    - 抛出 `typer.Exit(exit_code)`（本质是 SystemExit）
    """
    err = CLIError(
        error,
        message,
        suggestion=suggestion,
        retryable=retryable,
        exit_code=exit_code,
        context=context,
    )

    state = get_state()
    explicit_json = state.fmt in {"json", "ndjson"}
    use_json = explicit_json or not is_stderr_tty()

    if use_json:
        try:
            sys.stderr.buffer.write(_json_dumps(err.to_dict(), indent=True))
            sys.stderr.buffer.write(b"\n")
            sys.stderr.buffer.flush()
        except Exception:
            # 兜底
            sys.stderr.write(f"{err.error}: {err.message}\n")
    else:
        console = _make_stderr_console()
        console.print(f"[red bold]✗ {error}[/red bold]: {message}")
        if suggestion:
            console.print(f"[yellow]提示:[/yellow] {suggestion}")
        if retryable:
            console.print("[dim](此错误可重试)[/dim]")

    raise typer.Exit(code=exit_code)


# ============================================================================
# 常用 die 快捷函数
# ============================================================================


def die_file_not_found(path: str) -> NoReturn:
    die(
        "file_not_found",
        f"文件不存在: {path}",
        suggestion=f"检查路径是否正确，或确认文件是否已创建: ls -l {path}",
        exit_code=ExitCode.NOT_FOUND,
    )


def die_unsupported_format(path: str, supported: Iterable[str]) -> NoReturn:
    die(
        "unsupported_format",
        f"不支持的文件格式: {path}",
        suggestion=f"支持的格式: {', '.join(sorted(supported))}",
        exit_code=ExitCode.USAGE,
    )


def die_usage(message: str, *, suggestion: Optional[str] = None) -> NoReturn:
    die(
        "usage_error",
        message,
        suggestion=suggestion,
        exit_code=ExitCode.USAGE,
    )


def die_io(message: str, *, suggestion: Optional[str] = None) -> NoReturn:
    die(
        "io_error",
        message,
        suggestion=suggestion,
        exit_code=ExitCode.GENERAL,
        retryable=True,
    )


def die_permission(message: str, *, suggestion: Optional[str] = None) -> NoReturn:
    die(
        "permission_denied",
        message,
        suggestion=suggestion,
        exit_code=ExitCode.PERMISSION,
    )


def die_conflict(message: str, *, suggestion: Optional[str] = None) -> NoReturn:
    die(
        "conflict",
        message,
        suggestion=suggestion,
        exit_code=ExitCode.CONFLICT,
    )


def die_io_error(exc: BaseException, *, operation: str, path: Optional[str] = None) -> NoReturn:
    """把任意 I/O 异常映射到精确的退出码。

    映射规则：
    - FileNotFoundError → exit 3 (NOT_FOUND)
    - PermissionError   → exit 4 (PERMISSION)
    - FileExistsError   → exit 5 (CONFLICT)
    - IsADirectoryError → exit 2 (USAGE)
    - 其它 OSError/Exception → exit 1 (GENERAL，retryable)

    用于副作用命令的读/写包裹层，让 agent 能根据退出码区分错误类别。
    """
    target = f": {path}" if path else ""
    if isinstance(exc, FileNotFoundError):
        die(
            "file_not_found",
            f"{operation}失败，文件不存在{target}",
            suggestion="检查路径是否正确" + (f": ls -l {path}" if path else ""),
            exit_code=ExitCode.NOT_FOUND,
        )
    if isinstance(exc, PermissionError):
        die(
            "permission_denied",
            f"{operation}失败，权限被拒绝{target}",
            suggestion=(
                f"检查文件/目录权限: ls -ld {Path(path).parent}" if path else "检查文件/目录权限"
            ),
            exit_code=ExitCode.PERMISSION,
        )
    if isinstance(exc, FileExistsError):
        die(
            "conflict",
            f"{operation}失败，目标已存在{target}",
            suggestion="使用不同的输出路径，或先删除已存在的目标",
            exit_code=ExitCode.CONFLICT,
        )
    if isinstance(exc, IsADirectoryError):
        die(
            "usage_error",
            f"{operation}失败，目标是目录而非文件{target}",
            suggestion="提供文件路径而不是目录路径",
            exit_code=ExitCode.USAGE,
        )
    # 兜底：通用 I/O 错误
    die(
        "io_error",
        f"{operation}失败: {exc}",
        suggestion="检查文件是否可访问、磁盘空间是否充足",
        exit_code=ExitCode.GENERAL,
        retryable=True,
    )


__all__ = [
    "ExitCode",
    "CLIState",
    "CLIError",
    "set_state",
    "get_state",
    "is_stdout_tty",
    "is_stderr_tty",
    "use_color",
    "default_format",
    "resolve_format",
    "stderr_console",
    "log",
    "log_panel",
    "log_table",
    "emit_json",
    "emit_ndjson",
    "emit_csv",
    "emit_data",
    "emit_action",
    "die",
    "die_file_not_found",
    "die_unsupported_format",
    "die_usage",
    "die_io",
    "die_permission",
    "die_conflict",
    "die_io_error",
]
