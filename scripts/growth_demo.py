"""Run the synthetic training-data workflow and keep exact CLI evidence."""

from __future__ import annotations

import argparse
import json
import os
import random
import runpy
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".growth/demo")
    parser.add_argument("--from", dest="package", help="Use an isolated wheel or dtflow==VERSION")
    args = parser.parse_args()
    work = args.output.resolve()
    # Refuse to replace a previous demonstration's inputs or outputs.
    work.mkdir(parents=True, exist_ok=False)
    generator = runpy.run_path(str(ROOT / "examples/make_examples.py"))
    rows = generator["make_chat"](random.Random(generator["SEED"]))
    generator["write_jsonl"](work / "chat.jsonl", rows)
    package = (
        str(Path(args.package).resolve())
        if args.package and Path(args.package).exists()
        else args.package
    )
    prefix = (
        ["uv", "tool", "run", "--isolated", "--from", package, "dt"]
        if args.package
        else [sys.executable, "-m", "dtflow"]
    )
    commands = [
        ["--version"],
        ["stats", "chat.jsonl", "--schema"],
        [
            "filter",
            "chat.jsonl",
            "not calls(x) and bool(x.messages[-1].content)",
            "-o",
            "filtered.jsonl",
        ],
        ["dedupe", "filtered.jsonl", "--key=id", "-o", "clean.jsonl"],
        ["validate", "clean.jsonl", "--preset=openai_chat"],
        ["transform", "clean.jsonl", "--preset=sharegpt", "-o", "sharegpt.jsonl"],
        ["transform", "sharegpt.jsonl", "--preset=openai_chat", "-o", "sft.jsonl"],
        ["validate", "sft.jsonl", "--preset=openai_chat"],
        ["export", "sft.jsonl", "-f", "llama-factory", "-o", "llama"],
    ]
    evidence = []
    env = {**os.environ, "DT_LANG": "en", "NO_COLOR": "1"}
    if args.package:
        env.pop("PYTHONPATH", None)
    else:
        env["PYTHONPATH"] = str(ROOT)
    for command in commands:
        result = subprocess.run(
            [*prefix, *command],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        item = {
            "command": shlex.join(["dt", *command]),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        evidence.append(item)
        (work / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(f"{item['command']} -> exit {result.returncode}")
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            return result.returncode

    data = json.loads((work / "llama/custom_dataset.json").read_text())
    info = json.loads((work / "llama/dataset_info.json").read_text())["custom_dataset"]
    assert info["columns"] == {"messages": "messages"}
    assert all(
        info["tags"]["role_tag"] in m and info["tags"]["content_tag"] in m
        for row in data
        for m in row[info["columns"]["messages"]]
    )
    print(
        json.dumps(
            {
                "input_rows": len(rows),
                "exported_rows": len(data),
                "evidence": str(work / "evidence.json"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
