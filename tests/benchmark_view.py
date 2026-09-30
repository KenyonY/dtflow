"""dt view 显示性能基准 (Textual headless, 不进 pytest 收集)。

测三件事, 改 view 渲染路径前后各跑一次对比:
1. 首屏: 窗口载入 + 表格填充 (_populate)
2. 连按 j: 一次性排队 N 个按键 (模拟长按的键盘重复), 到最终样本首帧的耗时 + 详情实际渲染次数
3. 最长样本: 从小样本跳过去的首帧 / 全部挂完耗时; 以及挂载进行中按 j 的响应 (到下一样本首帧)

运行方式:
    python tests/benchmark_view.py data.jsonl [--cap 10000] [--size 200x50]
"""

import argparse
import asyncio
import os
import time
from pathlib import Path

os.environ.setdefault("DTFLOW_VIEW_WORKERS", "1")  # headless 下不起进程池, 结果稳定

from textual import events  # noqa: E402

from dtflow.cli.view import render  # noqa: E402
from dtflow.cli.view.app import ViewApp  # noqa: E402
from dtflow.cli.view.source import open_source  # noqa: E402
from dtflow.rowfn import _normalize_turns  # noqa: E402


def _size_of(row) -> int:
    """对话按消息数, 其余按序列化长度。"""
    turns = _normalize_turns(row)
    return len(turns) if turns else len(str(row))


async def _settle(pilot, app) -> None:
    """等详情稳定: 若干帧内详情 widget 数不再变化。"""
    last, same = -1, 0
    while same < 3:
        await pilot.pause(0.02)
        n = len(app.query_one("#detail").children)
        same = same + 1 if n == last else 0
        last = n


async def _first_paint(pilot, app, table, row: int) -> None:
    """等光标到 row 且该样本的详情已画出首批 (渲染代次推进过且有 widget)。"""
    gen0 = getattr(app, "_mount_gen", None)
    while table.cursor_row != row:
        await pilot.pause(0.005)
    while True:
        await pilot.pause(0.005)
        gen = getattr(app, "_mount_gen", None)
        if app._field_widgets and (
            gen is None or gen != gen0 or getattr(app, "_highlight_gen", 0) == 0
        ):
            if app._field_widgets[0].size.height:
                return


async def run(path: Path, cap: int, size) -> None:
    t0 = time.perf_counter()
    src = open_source(path, initial_size=cap)
    win = src.window(0, cap)
    fmt = render.detect_format(win)
    load = time.perf_counter() - t0

    renders = {"n": 0}
    orig_refresh, orig_populate = ViewApp._refresh_detail, ViewApp._populate
    populate = {}

    def counting(self, row):
        renders["n"] += 1
        return orig_refresh(self, row)

    def timed_populate(self, *a, **k):
        s = time.perf_counter()
        r = orig_populate(self, *a, **k)
        populate["ms"] = (time.perf_counter() - s) * 1000
        return r

    ViewApp._refresh_detail, ViewApp._populate = counting, timed_populate

    app = ViewApp(src, win, 0, cap, fmt, path.name)
    t0 = time.perf_counter()
    async with app.run_test(size=size) as pilot:
        await _settle(pilot, app)
        first = time.perf_counter() - t0
        print(f"{path.name}: {len(win)} rows, fmt={fmt}, load {load:.2f}s")
        print(f"  first screen {first:.2f}s (populate {populate['ms']:.0f}ms)")

        sizes = [_size_of(r) for r in app.all_rows]
        big = max(range(len(sizes)), key=sizes.__getitem__)
        table = app.query_one("#table")

        for label, start in (("start", 0), ("near longest", max(0, big - 10))):
            table.move_cursor(row=start)
            await _settle(pilot, app)
            renders["n"] = 0
            n = min(20, len(win) - 1 - start)
            t0 = time.perf_counter()
            for _ in range(n):
                app.post_message(events.Key("j", "j"))
            await _first_paint(pilot, app, table, start + n)
            print(
                f"  burst {n}x j ({label}): {(time.perf_counter() - t0) * 1000:.0f}ms, "
                f"detail renders={renders['n']}"
            )

        small = min(range(len(sizes)), key=sizes.__getitem__)
        table.move_cursor(row=small)
        await _settle(pilot, app)
        t0 = time.perf_counter()
        table.move_cursor(row=big)
        await _first_paint(pilot, app, table, big)
        first_paint = time.perf_counter() - t0
        await _settle(pilot, app)
        print(
            f"  jump to longest (#{big + 1}, size {sizes[big]}): first paint "
            f"{first_paint * 1000:.0f}ms, settled {(time.perf_counter() - t0) * 1000:.0f}ms"
        )
        table.move_cursor(row=small)
        await _settle(pilot, app)
        table.move_cursor(row=big)
        await _first_paint(pilot, app, table, big)
        t0 = time.perf_counter()  # 最长样本刚出首帧, 余下字段还在挂: 此时按 j
        app.post_message(events.Key("j", "j"))
        await _first_paint(pilot, app, table, big + 1)
        print(f"  j while longest still mounting: {(time.perf_counter() - t0) * 1000:.0f}ms")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--cap", type=int, default=10000)
    ap.add_argument("--size", default="200x50")
    args = ap.parse_args()
    w, h = map(int, args.size.split("x"))
    asyncio.run(run(args.file, args.cap, (w, h)))


if __name__ == "__main__":
    main()
