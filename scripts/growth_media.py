"""Render two short, reproducible terminal demos from real CLI/TUI output."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path

from rich.console import Console
from rich.text import Text
from view_showcase import Shots, _fix_svg, _prompt, _settle, rasterize

os.environ["DT_LANG"] = "en"
os.environ.pop("NO_COLOR", None)


async def browse(work: Path, shots: Shots):
    from dtflow.cli.view.app import ViewApp
    from dtflow.cli.view.render import detect_format
    from dtflow.cli.view.source import open_source

    source = open_source(work / "chat.jsonl", initial_size=20)
    window = source.window(0, 20)
    app = ViewApp(
        source,
        window,
        0,
        20,
        detect_format(window),
        "chat.jsonl",
        filepath=str(work / "chat.jsonl"),
    )
    async with app.run_test(size=(124, 36)) as pilot:
        await _settle(app, pilot)
        shots.take(app, "sample", 7)
        await _prompt(app, pilot, "slash", "refund", shots, "search")
        assert app._subset is not None and len(app._subset) > 0
        shots.take(app, "search", 6)
        await _prompt(
            app, pilot, "f", "not calls(x) and bool(x.messages[-1].content)", shots, "filter"
        )
        shots.take(app, "filter", 6)
        export_path = work / "viewer-subset.jsonl"
        await _prompt(app, pilot, "w", str(export_path), shots, "export")
        assert export_path.exists() and export_path.stat().st_size > 0
        shots.take(app, "export", 9)


def video(frames, destination: Path, temp: Path):
    manifest = temp / f"{destination.stem}.txt"
    manifest.write_text(
        "\n".join(
            [line for path, hold in frames for line in [f"file '{path}'", f"duration {hold}"]]
            + [f"file '{frames[-1][0]}'"]
        )
        + "\n"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest),
            "-vf",
            "scale=1280:-2,pad=1280:ceil(ih/2)*2:0:0:color=black",
            "-r",
            "10",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("docs/images/growth"))
    args = parser.parse_args()
    work, output = args.demo.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    shots = Shots()
    asyncio.run(browse(work, shots))
    evidence = json.loads((work / "evidence.json").read_text())
    with tempfile.TemporaryDirectory(prefix="dtflow-media-") as temporary:
        temp = Path(temporary)
        svg_paths = []
        for name, svg, _ in shots.frames:
            path = temp / f"{name}.svg"
            path.write_text(_fix_svg(svg))
            svg_paths.append((name, path))
        pngs = rasterize(svg_paths, temp)
        video(
            list(zip(pngs, [hold for _, _, hold in shots.frames], strict=True)),
            output / "entry.mp4",
            temp,
        )
        (output / "entry.png").write_bytes(pngs[2].read_bytes())

        workflow_paths = []
        # The version screen isn't part of the workflow video.
        for index, item in enumerate(evidence[1:]):
            console = Console(file=io.StringIO(), record=True, width=112, color_system="truecolor")
            console.print(
                Text(
                    "dtflow: inspect -> filter -> dedupe -> validate -> transform -> export",
                    style="bold cyan",
                )
            )
            console.print(Text("$ " + item["command"], style="bold green"))
            lines = item["stdout"].splitlines()
            preview = lines[:22]
            if len(lines) > len(preview):
                preview.append("... (full stdout/stderr retained in evidence.json)")
            console.print(Text("\n".join(preview)))
            console.print(Text(f"exit code: {item['exit_code']}", style="bold green"))
            path = temp / f"workflow-{index}.svg"
            path.write_text(_fix_svg(console.export_svg(title="dtflow training-data workbench")))
            workflow_paths.append((f"workflow-{index}", path))
        pngs = rasterize(workflow_paths, temp)
        # Equal canvas height prevents varying report lengths from cropping the video.
        from PIL import Image

        height = max(Image.open(path).height for path in pngs)
        width = max(Image.open(path).width for path in pngs)
        for path in pngs:
            with Image.open(path) as frame:
                canvas = Image.new("RGB", (width, height), "#292929")
                canvas.paste(frame.convert("RGB"), (0, 0))
                canvas.save(path)
        video([(path, 5) for path in pngs], output / "workflow.mp4", temp)
        (output / "workflow.png").write_bytes(pngs[-1].read_bytes())
    print(output)


if __name__ == "__main__":
    main()
