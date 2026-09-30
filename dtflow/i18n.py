"""dt 的界面语言 (en / zh)。

所有面向用户的文本 (CLI 帮助、报错、提示、dt view 界面) 都写成 t("English", "中文")，
两种语言并排写在调用处: 只有两种语言, 并排比翻译目录简单, 也不会出现 key 漂移。

语言在导入时确定一次, 优先级: 环境变量 DT_LANG > 配置文件 (dt lang 写入) > en。
typer 的帮助文本和 Textual 的 BINDINGS 都在导入时求值, 所以不支持运行中切换。
"""

import json
import os
from pathlib import Path

LANGS = ("en", "zh")
CONFIG_PATH = Path.home() / ".config" / "dtflow" / "config.json"


def _read_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _resolve_lang() -> str:
    lang = os.environ.get("DT_LANG") or _read_config().get("lang")
    return lang if lang in LANGS else "en"


LANG = _resolve_lang()


def t(en: str, zh: str) -> str:
    """按当前界面语言返回其一。含变量时两边各写 f-string。"""
    return zh if LANG == "zh" else en


def save_lang(lang: str) -> None:
    """把界面语言写入配置文件, 保留文件里的其他键。"""
    config = _read_config()
    config["lang"] = lang
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
