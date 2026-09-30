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

        await pilot.press("right")
        await _settle(app, pilot)
        assert "2/2 · msg2 user · missing.png" in str(scr.query_one("#img-title").render())
        assert "文件不存在" in str(scr.query_one("#img-view .img-msg").render())

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
