"""CLI export output contract tests."""

import json
import subprocess
import sys

import pytest


@pytest.mark.parametrize("framework", ["llama-factory", "swift", "axolotl"])
@pytest.mark.parametrize("quiet", [False, True])
def test_export_stdout_is_one_json_summary(tmp_path, framework, quiet):
    source = tmp_path / "chat.jsonl"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                ]
            }
        )
        + "\n"
    )
    output_dir = tmp_path / framework / "[red]"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "dtflow",
            *(["--quiet"] if quiet else []),
            "export",
            str(source),
            "-f",
            framework,
            "-o",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    summary = json.loads(result.stdout)
    assert summary["action"] == "export"
    assert summary["status"] == "ok"
    assert summary["stats"]["detected_format"] == "openai_chat"
    assert summary["output"] == str(output_dir)
    if quiet:
        assert result.stderr == ""
    else:
        assert "custom_dataset" in result.stderr.replace("\n", "")
        assert "[red]" in result.stderr.replace("\n", "")
    saved = json.loads(next(output_dir.glob("custom_dataset.*")).read_text())
    expected = json.loads(source.read_text())
    assert saved == ([expected] if framework == "llama-factory" else expected)
