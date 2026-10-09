"""Save one observation of GitHub traffic and PyPI downloads; no posting."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


def github(path: str):
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def downloads():
    request = Request(
        "https://pypistats.org/api/packages/dtflow/recent",
        headers={"User-Agent": "dtflow-growth-snapshot"},
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="KenyonY/dtflow")
    parser.add_argument("--output", type=Path, default=Path(".growth/snapshots"))
    parser.add_argument("--until", type=date.fromisoformat, help="Stop after this UTC date")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    if args.until and now.date() > args.until:
        return 0
    prefix = f"repos/{args.repo}"
    snapshot = {"observed_at": now.isoformat(), "repo": args.repo, "metrics": {}, "errors": {}}
    for key, fetch in {
        "repository": lambda: github(prefix),
        "views": lambda: github(f"{prefix}/traffic/views"),
        "clones": lambda: github(f"{prefix}/traffic/clones"),
        "referrers": lambda: github(f"{prefix}/traffic/popular/referrers"),
        "pypi_recent": downloads,
    }.items():
        try:
            value = fetch()
            if key == "repository":
                value = {
                    k: value[k]
                    for k in ["stargazers_count", "forks_count", "open_issues_count", "pushed_at"]
                }
            snapshot["metrics"][key] = value
        except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            snapshot["errors"][key] = str(exc)

    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / f"{now.strftime('%Y-%m-%dT%H-%M-%S-%fZ')}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"snapshot": str(path), "errors": snapshot["errors"]}))
    return 1 if snapshot["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
