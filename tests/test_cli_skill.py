from pathlib import Path

import pytest

from dtflow.cli import skill


def test_skill_target_directories():
    assert skill.get_skill_target_dir("claude") == Path.home() / ".claude/skills/dtflow"
    assert skill.get_skill_target_dir("codex") == Path.home() / ".agents/skills/dtflow"


def test_unknown_skill_target_is_rejected():
    with pytest.raises(ValueError, match="未知 skill 安装目标"):
        skill.get_skill_target_dir("other")


def test_install_skill_uses_selected_target(tmp_path, monkeypatch):
    monkeypatch.setattr(skill, "get_skill_target_dir", lambda target: tmp_path / target)

    skill.install_skill("codex")

    installed = tmp_path / "codex" / "SKILL.md"
    assert installed.read_bytes() == skill.get_skill_source_path().read_bytes()
