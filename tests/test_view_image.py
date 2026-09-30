"""dt view 多模态图片: 引用抽取 (rowfn) / 详情与派生列 (render) / 读图 (image)。"""

import base64
import functools
import http.server
import io
import threading

import pytest
from PIL import Image

from dtflow.cli.view import image as vimg
from dtflow.cli.view import render as R
from dtflow.rowfn import _normalize_turns, image_mismatch, imgs


def _png(w=4, h=3) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "red").save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# 引用抽取
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "seg, ref",
    [
        ({"type": "image_url", "image_url": {"url": "a.png"}}, "a.png"),
        ({"type": "image_url", "image_url": "b.png"}, "b.png"),
        ({"type": "input_image", "image_url": "c.png"}, "c.png"),
        ({"type": "image", "image": "d.png"}, "d.png"),
        (
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": "AA"},
            },
            "data:image/jpeg;base64,AA",
        ),
        ({"type": "image_url"}, ""),  # 引用缺失: 保留一张空引用, 渲染时报出来而不是悄悄丢掉
    ],
)
def test_inline_image_segments(seg, ref):
    row = {"messages": [{"role": "user", "content": [{"type": "text", "text": "看"}, seg]}]}
    (turn,) = _normalize_turns(row)
    assert turn.content == "看 <image>"  # 图的位置留在正文里, 不再是字面的 "image_url"
    assert turn.images == (ref,)
    assert image_mismatch(row, [turn]) is None


def test_top_level_images_follow_placeholders():
    row = {
        "images": ["a.jpg", {"path": "b.jpg"}, "c.jpg"],
        "messages": [
            {"role": "user", "content": "<image><image>比较"},
            {"role": "assistant", "content": "差不多"},
            {"role": "user", "content": "再看 <image>"},
        ],
    }
    turns = _normalize_turns(row)
    assert [t.images for t in turns] == [("a.jpg", "b.jpg"), (), ("c.jpg",)]
    assert image_mismatch(row, turns) is None
    assert imgs(row) == 3


def test_llava_single_image_field():
    row = {"image": "coco/1.jpg", "conversations": [{"from": "human", "value": "<image>\n什么"}]}
    assert _normalize_turns(row)[0].images == ("coco/1.jpg",)


def test_extra_images_follow_ms_swift_to_first_non_system_message():
    # 图多于占位: 缺的占位补在首条非 system 消息开头 (ms-swift _add_default_tags), 图不丢
    row = {
        "images": ["a", "b", "c"],
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "<image>再看"},
        ],
    }
    turns = _normalize_turns(row)
    assert [t.images for t in turns] == [(), ("a", "b"), (), ("c",)]
    assert imgs(row) == 3
    assert image_mismatch(row, turns) == (1, 3)


def test_images_null_falls_back_to_image():
    row = {"images": None, "image": "x.png", "messages": [{"role": "user", "content": "<image>"}]}
    assert _normalize_turns(row)[0].images == ("x.png",)


def test_sharegpt_multimodal_value():
    row = {
        "conversations": [
            {
                "from": "human",
                "value": [{"type": "image", "image": "a.png"}, {"type": "text", "text": "?"}],
            }
        ]
    }
    (turn,) = _normalize_turns(row)
    assert turn.images == ("a.png",) and turn.content == "<image> ?"


@pytest.mark.parametrize(
    "row, color",
    [
        ({"images": ["a"], "messages": [{"role": "user", "content": "<image><image>"}]}, "red"),
        ({"images": ["a", "b"], "messages": [{"role": "user", "content": "<image>"}]}, "yellow"),
    ],
)
def test_mismatch_warning_severity(row, color):
    rend = R.render_detail_sections(row, "openai_chat", split_turns=True)[0][1]
    assert color in str(rend.renderables[0].style)


@pytest.mark.parametrize(
    "row, expected",
    [
        ({"images": ["a", "b"], "messages": [{"role": "user", "content": "<image>"}]}, (1, 2)),
        ({"images": ["a"], "messages": [{"role": "user", "content": "<image><image>"}]}, (2, 1)),
        ({"messages": [{"role": "user", "content": "<image> 但没图"}]}, (1, 0)),
        ({"messages": [{"role": "user", "content": "纯文本"}]}, None),
    ],
)
def test_image_mismatch(row, expected):
    assert image_mismatch(row, _normalize_turns(row)) == expected


def test_text_only_rows_unchanged():
    row = {"messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]}
    assert _normalize_turns(row)[0].content == "hi"
    assert imgs(row) == 0


# --------------------------------------------------------------------------- #
# 渲染: 详情图片行 / 数量不匹配警告 / imgs 列
# --------------------------------------------------------------------------- #
def test_detail_shows_image_lines_and_is_searchable():
    row = {"images": ["img/cat.png"], "messages": [{"role": "user", "content": "<image>猫?"}]}
    secs = R.render_detail_sections(row, "openai_chat", split_turns=True)
    plain = secs[0][2]
    assert R.IMAGE_LINE_PREFIX + "img/cat.png" in plain  # 按路径搜得到


def test_detail_warns_on_mismatch_at_top():
    row = {"images": ["a"], "messages": [{"role": "user", "content": "<image><image>"}]}
    secs = R.render_detail_sections(row, "openai_chat", split_turns=True)
    assert secs[0][2].startswith("⚠ 2 个 <image> 占位, 但有 1 张图")


def test_data_uri_label_is_short():
    ref = "data:image/png;base64," + "A" * 4096
    assert R.image_label(ref) == "data:image/png;base64,… (3.0 KB)"


def test_imgs_column_only_when_window_has_images():
    text_row = {"messages": [{"role": "user", "content": "hi"}]}
    img_row = {"images": ["a"], "messages": [{"role": "user", "content": "<image>"}]}
    assert "imgs" not in R.build_columns([text_row], "openai_chat")
    assert "imgs" not in R.default_visible_columns(
        R.build_columns([text_row], "openai_chat"), "openai_chat"
    )
    cols = R.build_columns([text_row, img_row], "openai_chat")
    assert "imgs" in cols and "imgs" in R.default_visible_columns(cols, "openai_chat")
    cells = dict(zip(cols, R.row_cells(0, img_row, "openai_chat", cols), strict=False))
    assert cells["imgs"] == "1"
    assert R.DERIVED_EXPR["imgs"] == "imgs(x)"


# --------------------------------------------------------------------------- #
# 读图
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _fresh_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(vimg, "CACHE_DIR", tmp_path / "cache")
    vimg.load.cache_clear()


def test_load_relative_and_absolute_path(tmp_path):
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "a.png").write_bytes(_png(8, 6))
    got = vimg.load("img/a.png", str(tmp_path))
    assert got.image.size == (8, 6)
    assert got.describe().startswith("8×6 PNG ")
    assert vimg.load(str(tmp_path / "img" / "a.png"), "/nowhere").image.size == (8, 6)


def test_load_file_uri(tmp_path):
    (tmp_path / "a.png").write_bytes(_png(3, 3))
    assert vimg.load(f"file://{tmp_path}/a.png", "/nowhere").image.size == (3, 3)


def test_load_data_uri():
    ref = "data:image/png;base64," + base64.b64encode(_png(2, 2)).decode()
    assert vimg.load(ref, ".").image.size == (2, 2)


@pytest.mark.parametrize(
    "ref, reason",
    [
        ("", "图片引用为空"),
        ("missing.png", "文件不存在"),
        ("oss://bucket/a.png", "不支持的协议: oss://"),
        ("data:image/png;base64,bm90IGFuIGltYWdl", "不是可识别的图片格式"),
    ],
)
def test_load_errors(tmp_path, ref, reason):
    with pytest.raises(vimg.ImageError, match=reason):
        vimg.load(ref, str(tmp_path))


@pytest.fixture
def http_root(tmp_path):
    (tmp_path / "a.png").write_bytes(_png(5, 5))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *a, **k: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", tmp_path
    server.shutdown()


def test_load_url_downloads_once(http_root):
    base, root = http_root
    assert vimg.load(f"{base}/a.png", ".").image.size == (5, 5)
    (root / "a.png").unlink()  # 源站没了也能从磁盘缓存读
    vimg.load.cache_clear()
    assert vimg.load(f"{base}/a.png", ".").image.size == (5, 5)


def test_load_url_404(http_root):
    base, _ = http_root
    with pytest.raises(vimg.ImageError, match="HTTP 404"):
        vimg.load(f"{base}/nope.png", ".")


# --------------------------------------------------------------------------- #
# 弹窗 (Textual pilot)
# --------------------------------------------------------------------------- #
def _vlm_app(tmp_path):
    import textual_image.widget  # noqa: F401  (非 TTY 下探测直接给默认值, 走 unicode 渲染)

    from dtflow.cli.view.app import ViewApp
    from dtflow.cli.view.source import RowSource

    (tmp_path / "a.png").write_bytes(_png(40, 30))
    rows = [
        {
            "images": ["a.png", "missing.png"],
            "messages": [
                {"role": "user", "content": "<image>这是什么"},
                {"role": "assistant", "content": "红块"},
                {"role": "user", "content": "那这张 <image>"},
            ],
        },
        {"messages": [{"role": "user", "content": "纯文本"}]},
    ]

    class Src(RowSource):
        total = len(rows)

        def window(self, offset, size):
            return rows[offset : offset + size]

    src = Src()
    return ViewApp(src, src.window(0, 2), 0, 2, "openai_chat", "t.jsonl", image_root=str(tmp_path))


async def _settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()  # 读图 worker (弹窗的 worker 也挂在 app 上)
    await pilot.pause()


@pytest.mark.asyncio
async def test_popup_by_key_switches_and_reports_errors(tmp_path):
    from dtflow.cli.view.app import ImageScreen

    app = _vlm_app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("i")
        await _settle(app, pilot)
        scr = app.screen
        assert isinstance(scr, ImageScreen)
        title = str(scr.query_one("#img-title").render())
        assert "1/2 · msg0 user · a.png" in title and "40×30 PNG" in title
        assert scr.query("#img-view .img")  # 图片 widget 已挂上

        await pilot.press("right")  # 翻页是读好下一张后整屏替换, 所以要重新取 screen
        await _settle(app, pilot)
        scr = app.screen
        assert "2/2 · msg2 user · missing.png" in str(scr.query_one("#img-title").render())
        assert "文件不存在" in str(scr.query_one("#img-view .img-msg").render())

        await pilot.press("right", "right")  # 连按: 按次数累加 (2/2 → 1/2 → 2/2), 不叠屏
        await _settle(app, pilot)
        assert app.screen._i == 1 and len(app.screen_stack) == 2

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ImageScreen)


@pytest.mark.asyncio
async def test_popup_by_imgs_cell_and_detail_line(tmp_path):
    from dtflow.cli.view import render as R
    from dtflow.cli.view.app import ImageScreen

    app = _vlm_app(tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        table = app.query_one("#table")
        vis = app._visible_columns()
        widths = app._column_widths(vis)
        ci = vis.index("imgs")
        x = sum(widths[j] + 2 * table.cell_padding for j in range(ci)) + table.cell_padding
        await pilot.click("#table", offset=(x + 1, 2))  # y=2: 表头下第一行数据
        await _settle(app, pilot)
        assert isinstance(app.screen, ImageScreen) and app.screen._i == 0
        await pilot.press("escape")
        await pilot.pause()

        # 详情里 msg2 的 🖼 行 → 从第 2 张图开始
        w = next(f for f in app._field_widgets if f._field_name == "msg2")
        y = next(
            i
            for i, ln in enumerate(w._plain_lines())
            if ln.lstrip().startswith(R.IMAGE_LINE_PREFIX)
        )
        await pilot.click(offset=(w.content_region.x + 1, w.content_region.y + y))
        await _settle(app, pilot)
        assert isinstance(app.screen, ImageScreen) and app.screen._i == 1


@pytest.mark.asyncio
async def test_popup_without_images_just_notifies(tmp_path):
    from dtflow.cli.view.app import ImageScreen

    app = _vlm_app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        assert not isinstance(app.screen, ImageScreen)


@pytest.mark.parametrize("has_image, probed", [(False, False), (True, True)])
def test_terminal_probe_only_when_first_window_has_images(tmp_path, has_image, probed):
    # 子进程: 本进程的 textual_image 可能已被别的测试 import 过
    import subprocess
    import sys

    content = "<image>" if has_image else "hi"
    row = {"images": ["a.png"]} if has_image else {}
    row["messages"] = [{"role": "user", "content": content}]
    code = (
        "import sys; from dtflow.cli.view import _probe_graphics; "
        f"_probe_graphics('openai_chat', [{row!r}]); "
        "print('textual_image.widget' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == str(probed)


@pytest.mark.asyncio
async def test_sixel_image_is_sent_once_then_skipped():
    # 图已发给终端后, 重画只输出"光标右移"跳过该区域: 不重发 sixel, 也不写空格
    # (tmux 收到写在图上的空格会删图, 每次重画都闪)。尺寸变了才重发。
    from textual.app import App
    from textual.geometry import Region

    from dtflow.cli.view.app import _sixel_once_class

    class Demo(App):
        def compose(self):
            yield _sixel_once_class()(Image.new("RGB", (40, 20), "red"), id="img")

    app = Demo()
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        impl = app.query_one("#img").children[0]
        full = Region(0, 0, *impl.content_size)
        text = lambda lines: "".join(seg.text for line in lines for seg in line)  # noqa: E731
        impl._painted = None
        assert "\x1bP" in text(impl.render_lines(full))  # 首次: 发 sixel
        again = impl.render_lines(full)
        assert "\x1bP" not in text(again) and " " not in text(again)
        assert len(again) == full.height and all(line.cell_length == full.width for line in again)
        assert "\x1bP" not in text(impl.render_lines(Region(0, 1, full.width, 1)))  # 取样式那种单行


# --------------------------------------------------------------------------- #
# 详情内缩略图
# --------------------------------------------------------------------------- #
@pytest.fixture
def graphics(monkeypatch):
    """假装终端能画真图 (测试进程没有 TTY): 用会渲染成字符的 UnicodeImage 代替。"""
    from textual_image.widget import UnicodeImage

    from dtflow.cli.view import app as A

    monkeypatch.setattr(A, "_graphics_image_class", lambda: UnicodeImage)
    return UnicodeImage


@pytest.mark.asyncio
async def test_thumbnails_follow_their_message(tmp_path, graphics):
    from dtflow.cli.view.app import THUMB_ROWS, ImageScreen, _Thumbs

    app = _vlm_app(tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await _settle(app, pilot)
        detail = list(app.query_one("#detail").children)
        names = [getattr(w, "_field_name", None) for w in detail]
        thumbs = [w for w in detail if isinstance(w, _Thumbs)]
        # 图挂在引用它的消息后面: msg0 一张, msg2 一张, 没图的 msg1 没有
        assert [t._field_name for t in thumbs] == ["msg0", "msg2"]
        assert names.index("msg0") + 1 == detail.index(thumbs[0])
        assert all(t.outer_size.height == THUMB_ROWS for t in thumbs)
        assert isinstance(thumbs[0].children[0], graphics)  # 读好后占位换成图
        assert "文件不存在" in str(thumbs[1].children[0].render())  # 坏图写原因
        # 锚点把缩略图条高度算进所属消息
        anchors = app._cur_anchors
        f0 = app._field_widgets[0]
        assert anchors["msg1"] == f0.outer_size.height + THUMB_ROWS

        th = thumbs[1]  # 点第二条消息的缩略图 → 从那张开大图
        await pilot.click(offset=(th.region.x + 1, th.region.y))
        await _settle(app, pilot)
        assert isinstance(app.screen, ImageScreen) and app.screen._i == 1
        await pilot.press("escape")
        await pilot.pause()

        app.query_one("#table").move_cursor(row=1)  # 换到纯文本样本: 缩略图跟着清掉
        await _settle(app, pilot)
        await pilot.pause()
        assert not app.query(_Thumbs) and not app._thumbs


@pytest.mark.asyncio
async def test_no_thumbnails_without_graphics(tmp_path):
    from dtflow.cli.view.app import _Thumbs

    app = _vlm_app(tmp_path)  # 测试进程不是 TTY: 探测结果不是 kitty/sixel
    async with app.run_test(size=(140, 45)) as pilot:
        await _settle(app, pilot)
        assert not app.query(_Thumbs)
        assert R_PREFIX_IN_DETAIL(app)


def R_PREFIX_IN_DETAIL(app):  # noqa: N802
    from dtflow.cli.view import render as R

    return any(R.IMAGE_LINE_PREFIX in t for t in app._field_texts)  # 🖼 路径行照常在


@pytest.mark.asyncio
async def test_sixel_thumbnails_hold_while_scrolling_and_free_in_tmux(tmp_path, monkeypatch):
    # sixel 缩略图: 滚动开始时每行 ECH 擦 1 格 (tmux 只在擦除时删存着的图, 否则成残影),
    # 滚动中画空白不发图, 停下 _HOLD_SECONDS 后再发。
    import re

    from dtflow.cli.view import app as A

    monkeypatch.setattr(A, "_graphics_image_class", lambda: A._sixel_once_class())
    app = _vlm_app(tmp_path)
    async with app.run_test(size=(140, 20)) as pilot:
        await _settle(app, pilot)
        await pilot.pause(A.ViewApp._HOLD_SECONDS + 0.2)  # 挂载后的等待期结束
        assert app._thumbs and not app.images_hold
        written = []
        monkeypatch.setattr(app._driver, "write", lambda data: written.append(data))
        detail = app.query_one("#detail")
        detail.scroll_to(y=3, animate=False)
        await pilot.pause()
        assert app.images_hold  # 滚动中停画
        ech = [w for w in written if "\x1b[1X" in w]
        assert ech and len(re.findall(r"\x1b\[1X", ech[0])) == detail.content_region.height
        await pilot.pause(A.ViewApp._HOLD_SECONDS + 0.2)
        assert not app.images_hold  # 停下后恢复


@pytest.mark.asyncio
async def test_sixel_blank_while_hold():
    from textual.app import App
    from textual.geometry import Region

    from dtflow.cli.view.app import _sixel_once_class

    class Demo(App):
        images_hold = True

        def compose(self):
            yield _sixel_once_class()(Image.new("RGB", (40, 20), "red"), id="img")

    app = Demo()
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        impl = app.query_one("#img").children[0]
        lines = impl.render_lines(Region(0, 0, *impl.content_size))
        assert "\x1bP" not in "".join(seg.text for line in lines for seg in line)
        assert impl._painted is None


def test_concurrent_download_same_url(tmp_path):
    # 缩略图与大图弹窗可能同时下载同一 URL: 临时文件名须唯一, 两边都要成功
    import time

    (tmp_path / "a.png").write_bytes(_png(6, 6))

    class Slow(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            time.sleep(0.3)
            super().do_GET()

        def log_message(self, *a):
            pass

    handler = functools.partial(Slow, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/a.png"
    results, errors = [], []

    def fetch():
        try:
            results.append(vimg._fetch(url))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=fetch) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    server.shutdown()
    assert not errors and len(results) == 4
    assert not list(vimg.CACHE_DIR.glob("*.part"))  # 不留半截文件


@pytest.mark.asyncio
async def test_thumbnail_keeps_aspect_ratio(graphics):
    # 宽度不够时整体缩小, 而不是只截宽 (图被压扁)
    from textual.app import App
    from textual_image._terminal import get_cell_size

    from dtflow.cli.view.app import THUMB_ROWS, _Thumbs

    class Demo(App):
        def compose(self):
            yield _Thumbs("msg0", ["a"], graphics)

    app = Demo()
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        th = app.query_one(_Thumbs)
        cell = get_cell_size()
        for w, h in [(580, 164), (1600, 900), (300, 1200)]:
            cols, rows = th._fit(w, h)
            assert rows <= THUMB_ROWS and cols <= th.size.width
            shown = (cols * cell.width) / (rows * cell.height)  # 画出来的宽高比
            assert abs(shown - w / h) / (w / h) < 0.25  # 取整误差内保持比例


@pytest.mark.asyncio
async def test_popup_not_blanked_by_thumbnail_hold(tmp_path, monkeypatch):
    # 大图弹窗开着时缩略图读完/缩放: 不擦 (ECH 会在大图上擦洞), 也不让大图变空白
    from dtflow.cli.view import app as A

    monkeypatch.setattr(A, "_graphics_image_class", lambda: A._sixel_once_class())
    app = _vlm_app(tmp_path)
    async with app.run_test(size=(140, 30)) as pilot:
        await _settle(app, pilot)
        await pilot.pause(A.ViewApp._HOLD_SECONDS + 0.2)
        await pilot.press("i")
        await _settle(app, pilot)
        assert isinstance(app.screen, A.ImageScreen)
        written = []
        monkeypatch.setattr(app._driver, "write", lambda data: written.append(data))
        app._hold_thumbs(full=True)
        assert not app.images_hold and not any("\x1b[1X" in w for w in written)


@pytest.mark.asyncio
async def test_layout_change_frees_whole_screen(tmp_path, monkeypatch):
    # 调分界/切布局后缩略图挪位: 图原来的行可能已不在详情区, 须擦整屏每行
    import re

    from dtflow.cli.view import app as A

    monkeypatch.setattr(A, "_graphics_image_class", lambda: A._sixel_once_class())
    app = _vlm_app(tmp_path)
    async with app.run_test(size=(140, 30)) as pilot:
        await _settle(app, pilot)
        await pilot.pause(A.ViewApp._HOLD_SECONDS + 0.2)
        for key in ("plus", "z"):
            written = []
            monkeypatch.setattr(app._driver, "write", lambda data, w=written: w.append(data))
            app.images_hold = False
            await pilot.press(key)
            await pilot.pause()
            assert app.images_hold
            assert max(len(re.findall(r"\x1b\[1X", w)) for w in written) == app.size.height
