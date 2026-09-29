"""生成 examples/ 下的示例数据集 (确定性: 同一 seed 产出完全相同的文件)。

    python examples/make_examples.py          # 重新生成全部文件

全部内容为合成数据: 中英双语的客服对话、编程问答、常识问答、agent 工具调用轨迹。
刻意埋入少量"脏数据", 让 README 与文档里的命令有东西可演示:
- 若干条精确重复            → dt dedupe
- 若干条没有 score 字段      → 表达式求值失败的默认策略 (filter 跳过 / select 置 null)
- 若干条 assistant 内容为空   → dt clean --drop-empty
- 一条 tool_calls 的参数不是合法 JSON → dt view 里标红
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

HERE = Path(__file__).resolve().parent
SEED = 42

Turn = Tuple[str, str]  # (role, content)

# --------------------------------------------------------------------------- #
# 素材池: (source, lang, turns)
# --------------------------------------------------------------------------- #
SUPPORT: List[List[Turn]] = [
    [
        ("user", "我昨天更新到 3.8.0 之后 App 打开就闪退，重装也不行。"),
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
    [
        ("user", "退款多久能到账？我 3 天前就申请了。"),
        (
            "assistant",
            "退款审核通过后，原路退回一般 1-3 个工作日到账，信用卡可能需要 5-7 个工作日。请提供订单号，我帮您查一下当前进度。",
        ),
        ("user", "A20260911-4471"),
        (
            "assistant",
            "该笔退款已于 9 月 12 日退回您的支付宝账户，金额 129.00 元。如未收到，请查看支付宝账单中的「退款」记录。",
        ),
    ],
    [
        ("user", "I was charged twice for the same order."),
        (
            "assistant",
            "I'm sorry about that. Could you share the order number and the last four digits of the card? I'll check both transactions.",
        ),
        ("user", "Order 7781-Q, card ending 4402."),
        (
            "assistant",
            "I see two authorizations on 9/14. One is a temporary hold that will drop off within 3-5 business days; only one charge will settle. I've added a note so you can reach us directly if it doesn't.",
        ),
    ],
    [
        ("user", "How do I reset my password? The reset email never arrives."),
        (
            "assistant",
            "Please check the spam folder first. If it's not there, the address on the account may differ from the one you're checking. Tell me the username and I'll confirm which email is on file (I'll only show the first two characters).",
        ),
    ],
    [
        ("user", "订单显示已发货，但物流三天没更新了。"),
        (
            "assistant",
            "这种情况多为快递揽收后未及时扫描。我已联系承运方查询，通常 24 小时内会有更新。若明天仍无进展，我们会为您重新发货或退款，您选哪种？",
        ),
        ("user", "重新发货吧。"),
        ("assistant", "好的，已登记补发申请，新单号会以短信发送给您。"),
    ],
    [
        ("user", "Can I change the shipping address after placing the order?"),
        (
            "assistant",
            "Yes, as long as the order hasn't shipped. Go to Orders → select the order → Edit address. Once a tracking number exists, the carrier has to handle changes and I can file that request for you.",
        ),
    ],
    [
        ("user", "发票怎么开？我需要公司抬头。"),
        (
            "assistant",
            "订单完成后，在「我的 → 发票管理」里选择该订单，填写公司抬头和税号，电子发票会在 24 小时内发送到您的邮箱。",
        ),
    ],
]

CODE: List[List[Turn]] = [
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
    [
        ("user", "SQL 里怎么查每个用户最近的一条订单？"),
        (
            "assistant",
            "用窗口函数按用户分组、按时间倒序编号，取第 1 条：\n\n"
            "```sql\nSELECT * FROM (\n  SELECT o.*, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC) AS rn\n  FROM orders o\n) t WHERE rn = 1;\n```\n\n"
            "MySQL 8 / PostgreSQL / SQLite 3.25+ 都支持。",
        ),
    ],
    [
        ("user", "Write a regex that matches an ISO date like 2026-09-29."),
        (
            "assistant",
            "```\n^\\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\\d|3[01])$\n```\n\n"
            "This validates the shape and the month/day ranges but not calendar rules such as February 30; parse with `datetime.date.fromisoformat` if you need that.",
        ),
    ],
    [
        ("user", "Docker 容器里时区不对，怎么改成 Asia/Shanghai？"),
        (
            "assistant",
            "最简单的是运行时传环境变量并挂载时区文件：\n\n"
            "```bash\ndocker run -e TZ=Asia/Shanghai -v /etc/localtime:/etc/localtime:ro your-image\n```\n\n"
            "或者在 Dockerfile 里 `ENV TZ=Asia/Shanghai` 并安装 `tzdata`。",
        ),
        ("user", "compose 文件里怎么写？"),
        (
            "assistant",
            "```yaml\nservices:\n  app:\n    image: your-image\n    environment:\n      TZ: Asia/Shanghai\n```",
        ),
    ],
    [
        ("user", "What's the difference between `is` and `==` in Python?"),
        (
            "assistant",
            "`==` compares values; `is` compares identity (whether both names point to the same object). Use `is` only for singletons such as `None`, `True`, `False`:\n\n"
            "```python\na = [1, 2]; b = [1, 2]\na == b   # True\na is b   # False\n```",
        ),
    ],
    [
        ("user", "怎么把一个 list 按每 100 个切成一批？"),
        (
            "assistant",
            "```python\ndef batched(items, size=100):\n    for i in range(0, len(items), size):\n        yield items[i:i + size]\n```\n\n"
            "Python 3.12 起标准库有 `itertools.batched(items, 100)`，语义一样。",
        ),
    ],
]

GENERAL: List[List[Turn]] = [
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
    [
        (
            "user",
            "Summarize in one sentence: The meeting covered Q3 revenue (up 12%), the delayed launch of the mobile app, and the plan to hire two backend engineers.",
        ),
        (
            "assistant",
            "Q3 revenue grew 12%, the mobile app launch slipped, and two backend engineers will be hired.",
        ),
    ],
    [
        (
            "user",
            "一个水池有进水管和出水管，单开进水管 6 小时灌满，单开出水管 9 小时放空，两管同开多久灌满？",
        ),
        ("assistant", "每小时净进水 1/6 − 1/9 = 1/18，所以 18 小时灌满。"),
    ],
    [
        ("user", "Is it safe to store passwords with MD5?"),
        (
            "assistant",
            "No. MD5 is fast and broken; use a slow, salted password hash such as bcrypt, scrypt or Argon2, which are designed to make brute force expensive.",
        ),
    ],
    [
        ("user", "把「机器学习」翻译成英文并给一个例句。"),
        (
            "assistant",
            "Machine learning. Example: Machine learning models improve with more high-quality data.",
        ),
    ],
    [
        ("user", "What does 'idempotent' mean for an HTTP API?"),
        (
            "assistant",
            "Calling the endpoint once or several times leaves the server in the same state. GET, PUT and DELETE are expected to be idempotent; POST usually is not.",
        ),
    ],
    [
        ("user", "简述 Transformer 里注意力机制在做什么。"),
        (
            "assistant",
            "为序列中的每个位置计算它应该「看」其他位置多少：用查询与键的相似度得到权重，再对值做加权求和，从而让每个 token 的表示融入上下文信息。",
        ),
    ],
]

# agent 轨迹: (user 问题, 工具名, 参数 dict, 工具返回, 最终回复, reasoning 或 None)
AGENT = [
    (
        "北京明天天气怎么样？",
        "get_weather",
        {"city": "北京", "date": "tomorrow"},
        '{"city":"北京","high":24,"low":15,"condition":"晴"}',
        "北京明天晴，最高 24℃、最低 15℃，早晚偏凉。",
        "用户问的是明天，需要带 date 参数调用天气工具。",
    ),
    (
        "What's the weather in Tokyo right now?",
        "get_weather",
        {"city": "Tokyo"},
        '{"city":"Tokyo","temp":27,"condition":"cloudy"}',
        "It's 27°C and cloudy in Tokyo right now.",
        None,
    ),
    (
        "帮我查一下订单 B20260903-0217 到哪了",
        "lookup_shipment",
        {"order_id": "B20260903-0217"},
        '{"status":"in_transit","last_scan":"上海转运中心","eta":"2026-09-07"}',
        "订单 B20260903-0217 正在运输中，最新扫描在上海转运中心，预计 9 月 7 日送达。",
        "先查物流再回答，不要凭空猜测送达时间。",
    ),
    (
        "How many orders did we get last week?",
        "run_sql",
        {"query": "SELECT count(*) FROM orders WHERE created_at >= date('now','-7 days')"},
        '[{"count(*)": 1842}]',
        "1,842 orders were placed in the last 7 days.",
        None,
    ),
    (
        "把 user_id 为 42 的用户最近三笔订单列出来",
        "run_sql",
        {
            "query": "SELECT id, amount, created_at FROM orders WHERE user_id = 42 ORDER BY created_at DESC LIMIT 3"
        },
        '[{"id":9001,"amount":129.0,"created_at":"2026-09-11"},{"id":8877,"amount":58.5,"created_at":"2026-09-02"},{"id":8710,"amount":260.0,"created_at":"2026-08-25"}]',
        "用户 42 最近三笔订单：9001（129.00 元，9-11）、8877（58.50 元，9-02）、8710（260.00 元，8-25）。",
        None,
    ),
    (
        "Search our docs for how to rotate an API key.",
        "search_docs",
        {"query": "rotate API key", "top_k": 3},
        '[{"title":"Managing API keys","url":"/docs/keys#rotate"}]',
        "See “Managing API keys” → Rotate: create a new key, switch your clients, then revoke the old one. Link: /docs/keys#rotate",
        "Docs search first; summarize the top hit rather than guessing.",
    ),
    (
        "我这个月退款了几笔？",
        "search_orders",
        {"user_id": "current", "status": "refunded", "month": "2026-09"},
        '{"count":2,"orders":["A20260911-4471","A20260902-0113"]}',
        "您本月有 2 笔退款：A20260911-4471 和 A20260902-0113。",
        None,
    ),
    (
        "Convert 350 USD to EUR.",
        "fx_rate",
        {"from": "USD", "to": "EUR", "amount": 350},
        '{"rate":0.91,"result":318.5}',
        "350 USD is about 318.50 EUR at today's rate (0.91).",
        None,
    ),
]


# --------------------------------------------------------------------------- #
# 生成
# --------------------------------------------------------------------------- #
def _lang(turns: List[Turn]) -> str:
    return "en" if turns[0][1][0].isascii() else "zh"


def _pool() -> List[Tuple[str, List[Turn]]]:
    pool: List[Tuple[str, List[Turn]]] = []
    pool += [("support_log", c) for c in SUPPORT]
    pool += [("stackoverflow", c) for c in CODE]
    pool += [("alpaca_zh" if _lang(c) == "zh" else "synthetic", c) for c in GENERAL]
    return pool


def _agent_messages(rng: random.Random, i: int, spec, bad_json: bool = False) -> List[Dict]:
    q, tool, args, result, answer, reasoning = spec
    call_id = f"call_{rng.randrange(10**8):08x}"
    arguments = json.dumps(args, ensure_ascii=False)
    if bad_json:
        arguments = arguments[:-1]  # 缺右括号 → dt view 里参数标红
    call: Dict = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": tool, "arguments": arguments}}
        ],
    }
    if reasoning:
        call["reasoning_content"] = reasoning
    return [
        {
            "role": "system",
            "content": "You are a helpful assistant with access to tools. Call a tool when it is needed.",
        },
        {"role": "user", "content": q},
        call,
        {"role": "tool", "tool_call_id": call_id, "content": result},
        {"role": "assistant", "content": answer},
    ]


def make_chat(rng: random.Random, n: int = 300) -> List[Dict]:
    pool = _pool()
    day0 = date(2026, 6, 1)
    rows: List[Dict] = []
    for i in range(n):
        if i % 7 == 3:  # ~14% agent 轨迹
            spec = AGENT[(i // 7) % len(AGENT)]
            msgs = _agent_messages(rng, i, spec, bad_json=(i == 24))
            source, lang, tags = "agent_traces", _lang([("user", spec[0])]), ["tool_use", "agent"]
        else:
            source, conv = pool[(i * 7) % len(pool)]
            lang = _lang(conv)
            turns = list(conv)
            if rng.random() < 0.35:
                turns = [
                    (
                        "system",
                        "你是一名耐心、专业的助手。"
                        if lang == "zh"
                        else "You are a patient, precise assistant.",
                    )
                ] + turns
            msgs = [{"role": r, "content": c} for r, c in turns]
            tags = rng.sample(
                ["refund", "crash", "code", "howto", "policy", "translate", "sql", "shipping"], k=2
            )
        row: Dict = {
            "id": f"chat-{i:04d}",
            "messages": msgs,
            "source": source,
            "lang": lang,
            "score": round(rng.uniform(0.3, 0.99), 2),
            "tags": tags,
            "created_at": (day0 + timedelta(days=rng.randrange(0, 110))).isoformat(),
            "meta": {
                "annotator": rng.choice(["ann01", "ann02", "ann03", "auto"]),
                "reviewed": rng.random() < 0.6,
            },
        }
        rows.append(row)

    # 脏数据: 精确重复 (id 也相同, dedupe -i 能去掉)
    for j in range(8):
        rows.append(dict(rows[j * 13]))
    # 缺 score 字段
    for j in range(6):
        rows[j * 37 + 5].pop("score", None)
    # assistant 内容为空
    for j in range(5):
        r = rows[j * 29 + 11]
        if r["source"] != "agent_traces":
            r["messages"][-1] = {"role": "assistant", "content": ""}
    rng.shuffle(rows)
    return rows


def make_sharegpt(rng: random.Random, n: int = 100) -> List[Dict]:
    pool = _pool()
    role = {"user": "human", "assistant": "gpt", "system": "system"}
    rows = []
    for i in range(n):
        source, conv = pool[(i * 5) % len(pool)]
        convs = [{"from": role[r], "value": c} for r, c in conv]
        row: Dict = {"id": f"sg-{i:04d}", "conversations": convs, "source": source}
        if rng.random() < 0.3:
            row["system"] = "You are a helpful assistant."
        rows.append(row)
    # 少量 function_call / observation 形态的工具调用
    for i in range(0, n, 12):
        spec = AGENT[(i // 12) % len(AGENT)]
        q, tool, args, result, answer, _ = spec
        rows[i]["conversations"] = [
            {"from": "human", "value": q},
            {
                "from": "function_call",
                "value": json.dumps({"name": tool, "arguments": args}, ensure_ascii=False),
            },
            {"from": "observation", "value": result},
            {"from": "gpt", "value": answer},
        ]
        rows[i]["source"] = "agent_traces"
    return rows


def make_alpaca(rng: random.Random, n: int = 120) -> List[Dict]:
    pool = _pool()
    rows = []
    for i in range(n):
        source, conv = pool[(i * 3) % len(pool)]
        user = [c for r, c in conv if r == "user"]
        assistant = [c for r, c in conv if r == "assistant"]
        instruction, output = user[0], assistant[0]
        inp = ""
        # 翻译/改写类把句子拆进 input
        if "：" in instruction and len(instruction) < 60:
            instruction, inp = instruction.split("：", 1)
        elif ": " in instruction and len(instruction) < 120:
            instruction, inp = instruction.split(": ", 1)
        rows.append(
            {
                "id": f"alp-{i:04d}",
                "instruction": instruction,
                "input": inp,
                "output": output,
                "source": source,
                "lang": _lang(conv),
            }
        )
    return rows


DPO_BASE = [
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
    (
        "How should I store API keys in a Python project?",
        "Keep them out of the repository: read them from environment variables (or a `.env` file that is git-ignored) with `os.environ`, and use a secrets manager in production. Never hard-code them or commit them, and rotate any key that was ever committed.",
        "Put them in a config.py and import it. Just don't share the file.",
    ),
    (
        "把这段话缩成一句：我们这个季度的营收增长了 12%，移动端的发布推迟了，另外计划再招两名后端工程师。",
        "本季度营收增长 12%，移动端发布推迟，并计划增招两名后端工程师。",
        "营收涨了，发布推迟了，要招人。",
    ),
    ("What is 17 × 23?", "17 × 23 = 391.", "17 × 23 is 381."),
    (
        "解释一下什么是「幂等」。",
        "同一个操作执行一次和执行多次，对系统状态的影响完全相同。例如按主键的「设置为 X」是幂等的，而「加 1」不是；HTTP 里 GET/PUT/DELETE 应当幂等，POST 通常不是。",
        "就是重复做也没事的意思。",
    ),
    (
        "Write a one-line shell command that counts lines in all .jsonl files in the current directory.",
        "```bash\nwc -l *.jsonl\n```",
        "```bash\ncat *.jsonl | wc\n```\n(this prints lines, words and bytes, not just lines)",
    ),
    (
        "客户说「你们的产品太贵了」，怎么回复比较合适？",
        "先认同感受再给出价值说明：「理解您的顾虑。我们的定价包含全年更新和优先支持，如果您主要用基础功能，也可以选择更便宜的标准版，我给您对比一下？」",
        "一分钱一分货。",
    ),
]


def make_dpo(rng: random.Random, n: int = 120) -> List[Dict]:
    rows = []
    for i in range(n):
        p, c, r = DPO_BASE[i % len(DPO_BASE)]
        rows.append(
            {
                "id": f"dpo-{i:04d}",
                "prompt": p,
                "chosen": c,
                "rejected": r,
                "source": rng.choice(["human_pref", "gpt4_judge", "rule_based"]),
                "margin": round(rng.uniform(0.3, 2.5), 2),
            }
        )
    return rows


def make_labels(rng: random.Random, chat_rows: List[Dict]) -> List[Dict]:
    """chat.jsonl 里约 70% 样本的人工标签, 用于 dt join 演示 (故意缺一部分 → 左连接可见)。"""
    ids = sorted({r["id"] for r in chat_rows})
    rows = []
    for cid in ids:
        if rng.random() < 0.7:
            rows.append(
                {
                    "id": cid,
                    "label": rng.choice(["keep", "keep", "keep", "drop", "review"]),
                    "quality": rng.randrange(1, 6),
                }
            )
    return rows


def write_jsonl(path: Path, rows: List[Dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    rng = random.Random(SEED)
    chat = make_chat(rng)
    write_jsonl(HERE / "chat.jsonl", chat)
    write_jsonl(HERE / "sharegpt.jsonl", make_sharegpt(rng))
    write_jsonl(HERE / "alpaca.jsonl", make_alpaca(rng))
    write_jsonl(HERE / "dpo.jsonl", make_dpo(rng))
    write_jsonl(HERE / "labels.jsonl", make_labels(rng, chat))
    for p in sorted(HERE.glob("*.jsonl")):
        print(
            f"{p.name:16s} {sum(1 for _ in p.open(encoding='utf-8')):5d} rows  {p.stat().st_size / 1024:6.1f} KB"
        )


if __name__ == "__main__":
    main()
