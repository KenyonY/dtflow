"""dt view 的图片加载: 引用 (本地路径 / http(s) URL / data URI) → PIL Image。

与 Textual 无关, 便于单测。URL 要联网, app 在 worker 线程里调用, 不卡界面。
相对路径按 root 解析 (--image-root, 默认数据文件所在目录; LLaMA-Factory 的 media_dir 同理)。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import os
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from ...i18n import t

TIMEOUT = 15  # 秒; 超时算坏图, 不无限等
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "dtflow" / "images"


class ImageError(Exception):
    """图片取不到或解不开; str(e) 是给用户看的原因。"""


class Loaded(NamedTuple):
    image: "PIL.Image.Image"  # noqa: F821 (PIL 懒加载: dt 其余命令不付 import 成本)
    nbytes: int

    def describe(self) -> str:
        """``1024×768 PNG 120.5 KB``: 核对分辨率/格式, 顺带看出异常大小。"""
        w, h = self.image.size
        return f"{w}×{h} {self.image.format or '?'} {self.nbytes / 1024:.1f} KB"


@lru_cache(maxsize=32)
def load(ref: str, root: str) -> Loaded:
    """读图并解码 (已缓存的直接返回; 失败抛 ImageError, 不缓存, 下次重试)。"""
    from PIL import Image, UnidentifiedImageError

    data = _read(ref, root)
    try:
        img = Image.open(io.BytesIO(data))
        img.load()  # open 是惰性的, 截断/损坏的文件到这里才报错
    except UnidentifiedImageError as e:  # 原始信息只有 "<_io.BytesIO object at 0x…>", 没用
        raise ImageError(t("not a recognized image format", "不是可识别的图片格式")) from e
    except (OSError, ValueError) as e:  # 截断/损坏
        raise ImageError(t(f"cannot decode image: {e}", f"图片解码失败: {e}")) from e
    return Loaded(img, len(data))


def _read(ref: str, root: str) -> bytes:
    if not ref:
        raise ImageError(t("empty image reference", "图片引用为空"))
    if ref.startswith("data:"):
        _, _, body = ref.partition(",")
        try:
            return base64.b64decode(body, validate=False)
        except (binascii.Error, ValueError) as e:
            raise ImageError(t(f"bad base64: {e}", f"base64 解码失败: {e}")) from e
    if ref.startswith(("http://", "https://")):
        return _fetch(ref)
    if ref.startswith("file://"):  # Qwen 示例的本地图片写法
        ref = ref[len("file://") :]
    if "://" in ref:
        scheme = ref.split("://", 1)[0]
        raise ImageError(t(f"unsupported scheme: {scheme}://", f"不支持的协议: {scheme}://"))
    path = Path(ref).expanduser()
    if not path.is_absolute():
        path = Path(root) / path
    try:
        return path.read_bytes()
    except FileNotFoundError as e:
        raise ImageError(t(f"file not found: {path}", f"文件不存在: {path}")) from e
    except OSError as e:
        raise ImageError(t(f"cannot read {path}: {e}", f"读取失败 {path}: {e}")) from e


def _fetch(url: str) -> bytes:
    """下载到磁盘缓存 (按 URL 哈希命名); 再次打开同一张图不再联网。"""
    cached = CACHE_DIR / hashlib.sha1(url.encode()).hexdigest()
    if cached.exists():
        return cached.read_bytes()
    try:
        # 带 UA: 不少图床/CDN 拒绝 Python 默认的 urllib UA (403)
        req = urllib.request.Request(url, headers={"User-Agent": "dtflow"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        raise ImageError(f"HTTP {e.code}: {url}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise ImageError(t(f"download failed: {reason}", f"下载失败: {reason}")) from e
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cached.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(cached)  # 先写临时文件再改名: 中途退出不留半截缓存
    return data
