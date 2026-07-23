"""版本号只有一个来源, 三个出口 (--help / --version / dt schema) 不得漂移。"""

import json
import subprocess
import sys

import dtflow


def _run(*args):
    return subprocess.run([sys.executable, "-m", "dtflow", *args], capture_output=True, text=True)


def test_version_flag_prints_bare_version():
    r = _run("--version")
    assert r.returncode == 0
    # 裸版本号: stdout 是数据, 版本号本身就是这条命令的数据, 便于直接比对
    assert r.stdout.strip() == dtflow.__version__


def test_help_header_shows_version():
    r = _run("--help")
    assert r.returncode == 0
    assert f"v{dtflow.__version__}" in r.stdout


def test_schema_version_matches():
    r = _run("schema")
    assert json.loads(r.stdout)["version"] == dtflow.__version__


def test_version_is_eager_and_ignores_other_options():
    # --version 不该被别的参数校验挡住 (is_eager)
    r = _run("--format", "不合法的值", "--version")
    assert r.returncode == 0 and r.stdout.strip() == dtflow.__version__
