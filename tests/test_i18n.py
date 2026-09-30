"""界面语言: 守卫 (面向用户的中文必须走 t()) + 英文界面端到端 + dt lang 切换。"""

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent / "dtflow"
CJK = re.compile(r"[一-鿿　-〿＀-￯]")

# 不经 t() 的中文常量, 按 (相对路径, 字符串原文) 列出, 不随行号漂移
ALLOWED = {
    # dt lang 用刚选的语言回显, 不是当前语言, 不能走 t()
    ("dtflow/__main__.py", "界面语言已设置为中文"),
    # 识别帮助文本里的示例段标题, 不是界面文本
    ("dtflow/cli/schema.py", "^\\s*(?:示例|Examples?|EXAMPLES)\\s*[:：]\\s*$"),
}


def _docstring_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _is_t_call(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t"


def _scan(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstring_ids(tree)
    problems = []
    for node in ast.walk(tree):
        if not _is_t_call(node):
            continue
        if len(node.args) != 2 or node.keywords:
            problems.append((node.lineno, "t() 必须恰好两个位置参数 (en, zh)"))
            continue
        en, zh = node.args
        for sub in ast.walk(en):
            if (
                isinstance(sub, ast.Constant)
                and isinstance(sub.value, str)
                and CJK.search(sub.value)
            ):
                problems.append((sub.lineno, "t() 的英文参数含中文"))
        skip.update(id(sub) for sub in ast.walk(zh))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
            and CJK.search(node.value)
        ):
            problems.append((node.lineno, node.value))
    return problems


def test_user_facing_chinese_goes_through_t():
    bad = []
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG.parent).as_posix()
        for lineno, msg in _scan(path):
            if (rel, msg) not in ALLOWED:
                bad.append(f"{rel}:{lineno}: {msg.strip()[:60]!r}")
    assert not bad, "\n".join(bad)


def _run(args, env_extra, home):
    env = {**os.environ, "HOME": str(home), "NO_COLOR": "1", "COLUMNS": "200", **env_extra}
    env.pop("DT_LANG", None) if "DT_LANG" not in env_extra else None
    return subprocess.run(
        [sys.executable, *args], capture_output=True, text=True, env=env, timeout=120
    )


# 渲染每个命令的 --help 与 dt schema, 拼接输出
_HELP_SCRIPT = r"""
import click, typer
from typer.testing import CliRunner
from dtflow.__main__ import app
runner = CliRunner()
cmd = typer.main.get_command(app)
out = [runner.invoke(app, ["--help"]).output, runner.invoke(app, ["schema"]).output]
for name in cmd.commands:
    out.append(runner.invoke(app, [name, "--help"]).output)
print("\n".join(out))
"""


def test_english_help_has_no_chinese(tmp_path):
    r = _run(["-c", _HELP_SCRIPT], {"DT_LANG": "en"}, tmp_path)
    assert r.returncode == 0, r.stderr
    hits = [line for line in r.stdout.splitlines() if CJK.search(line)]
    assert not hits, "\n".join(hits[:30])


def test_lang_command_switches_and_persists(tmp_path):
    dt = ["-m", "dtflow"]
    assert _run([*dt, "lang"], {}, tmp_path).stdout.strip() == "en"  # 默认英文
    assert _run([*dt, "lang", "zh"], {}, tmp_path).returncode == 0
    config = json.loads((tmp_path / ".config/dtflow/config.json").read_text())
    assert config == {"lang": "zh"}
    assert _run([*dt, "lang"], {}, tmp_path).stdout.strip() == "zh"
    assert "界面语言" in _run([*dt, "--help"], {}, tmp_path).stdout
    # 环境变量优先于配置文件
    assert _run([*dt, "lang"], {"DT_LANG": "en"}, tmp_path).stdout.strip() == "en"
    assert _run([*dt, "lang", "fr"], {}, tmp_path).returncode == 2


@pytest.mark.parametrize("lang,expected", [("en", "Language: English"), ("zh", "界面语言: 中文")])
def test_help_mentions_language_switch(tmp_path, lang, expected):
    assert expected in _run(["-m", "dtflow", "--help"], {"DT_LANG": lang}, tmp_path).stdout
