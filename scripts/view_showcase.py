"""生成 README 里 dt view 的展示素材 (PNG 截图 + GIF 动图)。

用 Textual 的 headless pilot 驱动真实的 ViewApp, 每个场景导出一张 SVG, 再用 playwright
(chromium) 栅格化成 PNG, 最后 ffmpeg 把关键帧串成 GIF。素材落在 docs/images/view/。
演示数据由本脚本现生成 (仓库不提交数据文件), 因而任何人都能重跑得到同样的图。

    python scripts/view_showcase.py            # 全部重新生成
    python scripts/view_showcase.py --no-gif   # 只出 PNG

依赖: pip install "dtflow[showcase]" (playwright + pillow) && playwright install chromium; ffmpeg;
字体: JetBrains Mono 与 Noto Sans Mono CJK SC (SVG 里指定, 缺失时 chromium 会退回别的字体,
图会略有不同)。
"""

from __future__ import annotations

import asyncio
import html
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

import orjson
from PIL import Image
from rich.cells import cell_len

os.environ["DTFLOW_VIEW_WORKERS"] = "1"  # headless 下不起进程池, 结果确定

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images" / "view"
SIZE = (124, 36)  # 终端列 × 行; 宽度贴合 GitHub README 正文栏
GIF_WIDTH = 960  # GIF 缩放到的像素宽

# ---------------------------------------------------------------------------
# 演示数据: 像一份真实的 SFT 混合数据集 (客服日志 / 代码问答 / 通用指令), 带元数据
# ---------------------------------------------------------------------------

SUPPORT = [
    [
        ("user", "你好，我昨天下的订单 A20260912-3381 想申请退款，还没发货。"),
        (
            "assistant",
            "您好，已为您查到订单 A20260912-3381，当前状态为「待发货」，可以直接退款。请确认是否全额退回原支付渠道？",
        ),
        ("user", "是的，全额退回。"),
        (
            "assistant",
            "已提交退款申请，预计 1-3 个工作日到账。退款进度可在「我的订单 - 退款/售后」中查看。",
        ),
    ],
    [
        ("user", "App 打开就闪退，安卓 14，刚更新到 3.8.0。"),
        (
            "assistant",
            "抱歉给您带来不便。请问闪退前是否有报错提示？另外请尝试：设置 → 应用 → 清除缓存后重新打开。",
        ),
        ("user", "清了缓存还是一样，没有任何报错，直接黑屏退出。"),
        (
            "assistant",
            "感谢反馈。3.8.0 在部分安卓 14 机型上存在已知的启动崩溃问题，修复版本 3.8.1 将于今晚发布。您也可以先回退到 3.7.6 使用。",
        ),
        ("user", "好的，那我等 3.8.1。"),
        ("assistant", "好的，发布后会通过应用内通知提醒您，再次抱歉。"),
    ],
    [
        ("user", "会员自动续费怎么关？"),
        (
            "assistant",
            "路径：我的 → 会员中心 → 管理自动续费 → 关闭。关闭后当前周期仍可正常使用，到期后不再扣费。",
        ),
    ],
    [
        ("user", "我的退款申请被拒了，理由写的是「商品已签收」，可我根本没收到货。"),
        ("assistant", "非常抱歉。请提供订单号，我为您核实物流签收记录。"),
        ("user", "B20260903-0217"),
        (
            "assistant",
            "已查到该订单由「XX快递」标记为 9 月 6 日签收，签收人为「门卫」。我已为您发起物流核查并重新开启退款通道，48 小时内会有专员联系您。",
        ),
        ("user", "谢谢，麻烦尽快。"),
        ("assistant", "已加急处理，请留意来电。"),
    ],
    [
        ("user", "上传文件时提示「报错：413 Request Entity Too Large」"),
        (
            "assistant",
            "该报错表示文件超过了单次上传上限（100MB）。您可以压缩后上传，或使用桌面客户端的分片上传功能。",
        ),
    ],
]

CODE = [
    [
        ("user", "How do I read a large JSONL file in Python without loading it all into memory?"),
        (
            "assistant",
            "Iterate over the file object line by line so only one record is in memory at a time:\n\n"
            '```python\nimport json\n\ndef iter_jsonl(path):\n    with open(path, encoding="utf-8") as f:\n'
            "        for line in f:\n            line = line.strip()\n            if line:\n                yield json.loads(line)\n\n"
            'for row in iter_jsonl("train.jsonl"):\n    process(row)\n```\n\n'
            "For very large files, `orjson.loads` is roughly 10x faster than the standard library.",
        ),
    ],
    [
        ("user", "写一个函数，统计 messages 列表里 assistant 回复的总字符数。"),
        (
            "assistant",
            "```python\ndef assistant_chars(messages: list[dict]) -> int:\n"
            '    return sum(len(m["content"]) for m in messages if m["role"] == "assistant")\n```\n\n'
            "如果 content 可能是 list（多模态），先把文本片段拼起来再计长。",
        ),
        ("user", "那再加上 user 的呢，分开返回。"),
        (
            "assistant",
            "```python\nfrom collections import Counter\n\ndef chars_by_role(messages: list[dict]) -> dict[str, int]:\n"
            '    c = Counter()\n    for m in messages:\n        c[m["role"]] += len(m["content"])\n    return dict(c)\n```',
        ),
    ],
    [
        ("user", "pandas 读 30GB 的 CSV 直接 OOM 了，有什么办法？"),
        (
            "assistant",
            "三种常见做法：\n\n1. `pd.read_csv(path, chunksize=1_000_000)` 分块处理；\n"
            "2. 换 Polars 的 `scan_csv` 走惰性执行，只物化需要的列；\n"
            "3. 先转成 Parquet，列式存储 + 压缩后再读。\n\n"
            '```python\nimport polars as pl\n\nlf = pl.scan_csv("big.csv")\n'
            'out = lf.filter(pl.col("score") > 0.8).select(["id", "text"]).collect(streaming=True)\n```',
        ),
    ],
    [
        ("user", "git 里怎么把最近三次提交合并成一次？"),
        (
            "assistant",
            '```bash\ngit reset --soft HEAD~3\ngit commit -m "合并后的提交信息"\n```\n\n'
            "`--soft` 会保留工作区和暂存区，只回退提交指针，所以三次改动会作为一次提交重新提交。",
        ),
    ],
    [
        ("user", "Why does my Python script print 报错: 'dict' object has no attribute 'append'?"),
        (
            "assistant",
            "You are calling `.append()` on a dictionary. Dictionaries have no `append`; use item assignment instead:\n\n"
            '```python\nd = {}\nd["key"] = "value"   # instead of d.append(...)\n```\n\n'
            "If you actually need an ordered collection, initialise it as a list: `items = []`.",
        ),
    ],
]

GENERAL = [
    [
        ("user", "用一句话解释什么是过拟合。"),
        ("assistant", "模型把训练集里的噪声也当规律学了，于是在训练集上很准、换一批数据就不行。"),
    ],
    [
        ("user", "Give me three tips for writing clear commit messages."),
        (
            "assistant",
            "1. Lead with a short imperative summary (≤ 50 chars).\n2. Explain *why* in the body, not *what* — the diff already shows what.\n3. Reference the issue or decision that motivated the change.",
        ),
    ],
    [
        ("user", "Translate to English: 数据质量比数据数量更重要。"),
        ("assistant", "Data quality matters more than data quantity."),
    ],
    [
        ("user", "SFT 和 RLHF 的区别是什么？"),
        (
            "assistant",
            "SFT 用标注好的「输入-输出」对直接做监督学习，教模型「该怎么答」；RLHF 则用人类偏好训练奖励模型，再用强化学习让模型的回答更贴近偏好，解决的是「哪种答更好」。两者通常先后进行。",
        ),
    ],
    [
        ("user", "What is the capital of Australia?"),
        (
            "assistant",
            "Canberra. Many people assume it is Sydney, but Canberra was purpose-built as the capital in 1913.",
        ),
    ],
    [
        ("user", "帮我把这句话改得正式一点：这个方案不太行，得重做。"),
        ("assistant", "该方案在可行性上存在明显不足，建议重新设计。"),
    ],
]


def _rows(seed: int = 7, n: int = 96) -> List[dict]:
    rng = random.Random(seed)
    pool: List[Tuple[str, str, List[Tuple[str, str]]]] = []
    pool += [("support_log", "zh", c) for c in SUPPORT]
    pool += [("stackoverflow", "en" if c[0][1][0].isascii() else "zh", c) for c in CODE]
    pool += [
        (
            "alpaca_zh" if not c[0][1][0].isascii() else "synthetic",
            "zh" if not c[0][1][0].isascii() else "en",
            c,
        )
        for c in GENERAL
    ]
    rows = []
    for i in range(n):
        source, lang, conv = pool[i % len(pool)]
        turns = list(conv)
        if rng.random() < 0.35:  # 一部分样本带 system
            turns = [("system", "你是一名耐心、专业的助手。")] + turns
        rows.append(
            {
                "messages": [{"role": r, "content": c} for r, c in turns],
                "source": source,
                "lang": lang,
                "score": round(rng.uniform(0.55, 0.99), 2),
                "tags": rng.sample(
                    ["refund", "crash", "code", "howto", "policy", "translate"], k=2
                ),
                "id": f"s{seed}-{i:04d}",
            }
        )
    rng.shuffle(rows)
    return rows


def _dpo_rows(seed: int = 3, n: int = 40) -> List[dict]:
    rng = random.Random(seed)
    base = [
        (
            "用户: 我的订单还没发货, 想退款。",
            "好的，已为您核实订单状态为「待发货」，可直接全额退款至原支付渠道，预计 1-3 个工作日到账。是否现在为您提交？",
            "退款请自己去订单页面申请。",
        ),
        (
            "Explain what a race condition is in one paragraph.",
            "A race condition happens when two or more threads access shared state concurrently and at least one of them writes, so the final result depends on the unpredictable order in which they run. The classic fix is to serialise the critical section with a lock, or to redesign so the state is not shared.",
            "It's when code races. Use threads carefully.",
        ),
        (
            "写一个 Python 函数判断一个数是否为质数。",
            "```python\ndef is_prime(n: int) -> bool:\n    if n < 2:\n        return False\n    if n % 2 == 0:\n        return n == 2\n    i = 3\n    while i * i <= n:\n        if n % i == 0:\n            return False\n        i += 2\n    return True\n```",
            "```python\ndef is_prime(n):\n    for i in range(2, n):\n        if n % i == 0:\n            return False\n    return True\n```\n\n注意: 这个实现对 0 和 1 会错误地返回 True。",
        ),
        (
            "SFT 数据里为什么要去重？",
            "重复样本会让模型对这些样本过度拟合、放大它们的权重；训练/验证集之间的重复还会让评估虚高。去重（精确 + 近似）是数据清洗里性价比最高的一步。",
            "因为重复不好。",
        ),
    ]
    rows = []
    for i in range(n):
        p, c, r = base[i % len(base)]
        rows.append(
            {
                "prompt": p,
                "chosen": c,
                "rejected": r,
                "source": rng.choice(["human_pref", "gpt4_judge"]),
                "margin": round(rng.uniform(0.3, 2.5), 2),
            }
        )
    return rows


def _write_jsonl(path: Path, rows: List[dict]) -> None:
    with open(path, "wb") as f:
        for r in rows:
            f.write(orjson.dumps(r, option=orjson.OPT_APPEND_NEWLINE))


# ---------------------------------------------------------------------------
# 驱动 TUI 出图
# ---------------------------------------------------------------------------


class Shots:
    """收集 (名字, SVG, 停留秒) 三元组; 名字给 PNG 用, 停留秒给 GIF 用。"""

    def __init__(self):
        self.frames: List[Tuple[str, str, float]] = []

    def take(self, app, name: str, hold: float = 2.2) -> None:
        title = f"dt view {app.filename}"
        self.frames.append((name, app.export_screenshot(title=title), hold))


async def _settle(app, pilot):
    await app.workers.wait_for_complete()
    await pilot.pause()
    await pilot.pause()


async def _prompt(app, pilot, key: str, text: str, shots: Shots, name: str):
    """按 key 打开输入框, 填入 text (提交前截一帧), 回车提交并等扫描完。"""
    await pilot.press(key)
    await pilot.pause()
    prompt = app.query_one("#prompt")
    prompt.value = text
    await pilot.pause()
    shots.take(app, f"{name}_typing", 1.6)
    await pilot.press("enter")
    await _settle(app, pilot)


async def shoot_chat(path: Path, shots: Shots):
    from dtflow.cli.view.app import ViewApp
    from dtflow.cli.view.render import detect_format
    from dtflow.cli.view.source import open_source

    src = open_source(path, initial_size=10000)
    window = src.window(0, 10000)
    app = ViewApp(src, window, 0, 10000, detect_format(window), path.name, filepath=str(path))
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        # 主界面: 光标停在一条带代码块的样本上, 详情区显示语法高亮
        for i, r in enumerate(window):
            if "```python" in r["messages"][-1]["content"]:
                for _ in range(i):
                    await pilot.press("j")
                break
        await pilot.pause()
        shots.take(app, "main", 3.0)

        # / 全量搜索: 整条记录任意值, 命中处黄底高亮
        await _prompt(app, pilot, "slash", "报错", shots, "search")
        shots.take(app, "search", 3.0)

        # f 全量筛选: 表达式叠加在搜索之上
        await _prompt(app, pilot, "f", "turns>=4 and source~=support", shots, "filter")
        shots.take(app, "filter", 3.0)

        # r 清空条件
        await pilot.press("r")
        await _settle(app, pilot)

        # F 列值勾选筛选 (Excel AutoFilter 式面板)
        await _prompt(app, pilot, "F", "source", shots, "value_filter")
        sl = app.screen.query_one("SelectionList")
        sl.select("support_log")  # 勾两个值 (与键盘 ↓ + 空格 等价)
        sl.select("stackoverflow")
        await pilot.pause()
        assert len(sl.selected) == 2, sl.selected
        shots.take(app, "value_filter", 3.0)
        await pilot.press("enter")
        await _settle(app, pilot)
        shots.take(app, "value_filter_applied", 2.4)

        # Enter 放大当前样本
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#detail").has_class("zoomed"), "Enter 未放大, zoom 帧会与上一帧相同"
        shots.take(app, "zoom", 2.6)
        await pilot.press("escape")
        await pilot.pause()

        # ? 帮助
        await pilot.press("question_mark")
        await pilot.pause()
        shots.take(app, "help", 2.6)
        await pilot.press("escape")
        await pilot.pause()


async def shoot_dpo(path: Path, shots: Shots):
    from dtflow.cli.view.app import ViewApp
    from dtflow.cli.view.render import detect_format
    from dtflow.cli.view.source import open_source

    src = open_source(path, initial_size=10000)
    window = src.window(0, 10000)
    app = ViewApp(src, window, 0, 10000, detect_format(window), path.name, filepath=str(path))
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        await pilot.press("j", "j")
        await pilot.pause()
        shots.take(app, "dpo", 3.0)


# ---------------------------------------------------------------------------
# SVG → PNG → GIF
# ---------------------------------------------------------------------------

# Rich 15 的 export_svg 有两处让中文走样:
# 1. 字体写死 Fira Code, 本机没有时 chromium 退回的 CJK 字体宽窄不一;
# 2. <text textLength> 按 len(text) 算, 而 x 坐标按 cell_len 推进 —— 中文 (1 字 2 cell)
#    的文本段被压成一半宽。这里把 textLength 按 cell 宽重算, 字体换成等宽 + CJK 等宽, 并关掉连字。
FONT_STACK = '"JetBrains Mono", "Noto Sans Mono CJK SC", monospace'
_TEXT_RE = re.compile(r'(<text[^>]*textLength=")([\d.]+)("[^>]*>)([^<]*)(</text>)')


def _fix_svg(svg: str, char_width: float = 20 * 0.61) -> str:
    """char_width = Rich 默认 font_size 20 × font_aspect_ratio 0.61。"""

    def fix(m: re.Match) -> str:
        cells = cell_len(html.unescape(m.group(4)))
        return f"{m.group(1)}{cells * char_width:.1f}{m.group(3)}{m.group(4)}{m.group(5)}"

    svg = _TEXT_RE.sub(fix, svg)
    svg = svg.replace('"Fira Code"', FONT_STACK).replace("Fira Code, monospace", FONT_STACK)
    # JetBrains Mono 的连字会把 -> == <= 画成 → ═ ≤, 终端里并不是这样
    return svg.replace("<style>", "<style>\n        text { font-variant-ligatures: none; }", 1)


def rasterize(svgs: List[Tuple[str, Path]], out_dir: Path) -> List[Path]:
    from playwright.sync_api import sync_playwright

    pngs = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=2)
        for name, svg_path in svgs:
            page.goto(svg_path.as_uri())
            el = page.locator("svg").first
            png = out_dir / f"{name}.png"
            el.screenshot(path=str(png), omit_background=True)
            # 终端截图颜色极少, 转 255 色调色板体积降 2/3, 肉眼无差
            Image.open(png).convert("RGB").quantize(colors=255).save(png, optimize=True)
            pngs.append(png)
        browser.close()
    return pngs


def make_gif(frames: List[Tuple[Path, float]], out: Path, tmp: Path) -> None:
    lst = tmp / "frames.txt"
    lines = []
    for png, hold in frames:
        lines.append(f"file '{png}'\nduration {hold}")
    lines.append(f"file '{frames[-1][0]}'")  # concat demuxer 需要最后一帧再列一次才吃到 duration
    lst.write_text("\n".join(lines) + "\n")
    vf = (
        f"scale={GIF_WIDTH}:-1:flags=lanczos,split[a][b];"
        "[a]palettegen=max_colors=96:stats_mode=diff[p];"
        "[b][p]paletteuse=dither=none:diff_mode=rectangle"
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
            str(lst),
            "-vf",
            vf,
            "-loop",
            "0",
            str(out),
        ],
        check=True,
    )


GIF_SEQUENCE = [
    "main",
    "search_typing",
    "search",
    "filter_typing",
    "filter",
    "value_filter_typing",
    "value_filter",
    "value_filter_applied",
    "zoom",
    "dpo",
    "help",
]

# 单独作为静态图放进 README 的帧
PNG_KEEP = {"main", "search", "value_filter", "dpo"}


def main(with_gif: bool = True) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    shots = Shots()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        chat = tmp / "sft_mixed.jsonl"
        dpo = tmp / "dpo_pairs.jsonl"
        _write_jsonl(chat, _rows())
        _write_jsonl(dpo, _dpo_rows())

        asyncio.run(shoot_chat(chat, shots))
        asyncio.run(shoot_dpo(dpo, shots))

        svg_dir = tmp / "svg"
        svg_dir.mkdir()
        svgs = []
        for name, svg, _ in shots.frames:
            p = svg_dir / f"{name}.svg"
            p.write_text(_fix_svg(svg), encoding="utf-8")
            svgs.append((name, p))

        png_dir = tmp / "png"
        png_dir.mkdir()
        pngs = {p.stem: p for p in rasterize(svgs, png_dir)}
        for name in PNG_KEEP:
            (OUT / f"{name}.png").write_bytes(pngs[name].read_bytes())
            print("png ", OUT / f"{name}.png")

        if with_gif:
            hold = {name: h for name, _, h in shots.frames}
            seq = [(pngs[n], hold[n]) for n in GIF_SEQUENCE]
            make_gif(seq, OUT / "demo.gif", tmp)
            print("gif ", OUT / "demo.gif")


if __name__ == "__main__":
    main(with_gif="--no-gif" not in sys.argv)
