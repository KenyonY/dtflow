"""
`dt schema` — 输出命令树与参数定义 (JSON)。

用途：让 agent 通过单次调用获取所有命令的结构化元数据，
避免依赖 `--help` 的文本解析。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import click
import typer
from click.core import Argument as ClickArgument
from click.core import Option as ClickOption

from .output import ExitCode, die, emit_json

# 匹配 docstring 中的"示例:"段落标题（中英文均可）
_EXAMPLES_HEADER = re.compile(r"^\s*(?:示例|Examples?|EXAMPLES)\s*[:：]\s*$")


def _extract_examples(help_text: Optional[str]) -> List[str]:
    """从命令 docstring 中提取 `示例:` 段的命令行。

    约定：
      - 段落以 `示例:` / `Examples:` 开头
      - 后续缩进的非空行视为示例命令
      - 第一个不缩进的非空行（如 `退出码:`）标志段落结束
      - 示例文本保留原样（含 `# 注释`），由 agent 自行解析
    """
    if not help_text:
        return []
    lines = help_text.splitlines()
    examples: List[str] = []
    in_section = False
    for line in lines:
        if not in_section:
            if _EXAMPLES_HEADER.match(line):
                in_section = True
            continue
        if not line.strip():
            continue
        if line[0] not in (" ", "\t"):
            break
        examples.append(line.strip())
    return examples


def _param_to_dict(p: click.Parameter) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "name": p.name,
        "required": bool(getattr(p, "required", False)),
    }

    # 参数 vs 选项
    if isinstance(p, ClickArgument):
        info["kind"] = "argument"
    elif isinstance(p, ClickOption):
        info["kind"] = "option"
        info["flags"] = list(p.opts)
        if p.secondary_opts:
            info["secondary_flags"] = list(p.secondary_opts)
        if p.help:
            info["help"] = p.help
        if getattr(p, "is_flag", False):
            info["type"] = "bool"
    else:
        info["kind"] = p.__class__.__name__.lower()

    # 类型信息
    if "type" not in info:
        type_name = getattr(p.type, "name", None) or p.type.__class__.__name__
        info["type"] = type_name

    # 枚举值
    choices = getattr(p.type, "choices", None)
    if choices:
        info["choices"] = list(choices)

    # 默认值
    default = p.default
    if default is not None and default is not ... and not callable(default):
        try:
            # 只输出 JSON 可序列化的默认值
            import orjson

            orjson.dumps(default)
            info["default"] = default
        except Exception:
            info["default"] = str(default)

    # 多值（typer 的 List[...])
    if getattr(p, "multiple", False):
        info["multiple"] = True

    return info


def _command_to_dict(name: str, cmd: click.Command) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "name": name,
        "description": (cmd.help or cmd.short_help or "").strip(),
    }
    if cmd.epilog:
        info["epilog"] = cmd.epilog.strip()
    if getattr(cmd, "hidden", False):
        info["hidden"] = True

    examples = _extract_examples(cmd.help)
    if examples:
        info["examples"] = examples

    params: List[Dict[str, Any]] = []
    for p in cmd.params:
        # 内置 help 参数跳过，没有信息量
        if isinstance(p, ClickOption) and p.name == "help":
            continue
        params.append(_param_to_dict(p))
    info["params"] = params
    return info


def _collect_commands(app: typer.Typer) -> Dict[str, click.Command]:
    """把 Typer app 转成 click.Command 树，返回 name -> click.Command。"""
    click_app = typer.main.get_command(app)
    if not isinstance(click_app, click.Group):
        return {}
    return {name: click_app.get_command(None, name) for name in click_app.list_commands(None)}  # type: ignore[arg-type]


def schema(
    command: Optional[str] = None,
    *,
    app: Optional[typer.Typer] = None,
) -> None:
    """输出命令 schema 到 stdout。

    参数:
        command: 若指定则只输出该命令；否则输出全部。
        app: 可选 typer app 引用（测试用）；默认导入 dtflow.__main__.app。
    """
    if app is None:
        from ..__main__ import app as real_app  # 延迟导入避免循环

        app = real_app

    commands = _collect_commands(app)

    if command:
        if command not in commands:
            die(
                "command_not_found",
                f"未知命令: {command}",
                suggestion=f"可用命令: {', '.join(sorted(commands.keys()))}",
                exit_code=ExitCode.NOT_FOUND,
            )
        emit_json(_command_to_dict(command, commands[command]))
        return

    # 输出完整 schema
    try:
        from .. import __version__ as version  # type: ignore[attr-defined]
    except Exception:
        version = "unknown"

    payload = {
        "name": "dt",
        "version": version,
        "description": "Datatron CLI - Agent 友好的数据转换工具",
        "exit_codes": ExitCode.as_dict(),
        "output_contract": {
            "stdout": "数据 (JSON / NDJSON / CSV / Table)",
            "stderr": "进度 / 警告 / 错误消息",
            "default_format_tty": "table",
            "default_format_non_tty": "ndjson",
        },
        "global_options": [
            {"flag": "--format", "choices": ["json", "ndjson", "csv", "table"]},
            {"flag": "--no-color", "type": "bool"},
            {"flag": "--yes", "type": "bool"},
            {"flag": "--verbose", "type": "bool"},
            {"flag": "--quiet", "type": "bool"},
        ],
        "commands": [
            _command_to_dict(name, cmd)
            for name, cmd in sorted(commands.items())
            if not getattr(cmd, "hidden", False)
        ],
    }
    emit_json(payload)
