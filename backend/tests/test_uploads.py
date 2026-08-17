"""Replaying a step that picked a file by hand.

A browser never tells a page where a chosen file really lives - a security rule,
not an oversight - so all a recording can hold is the name:

    upload  photos_input   files: ["IMG_1234.jpg"]

Replayed as `set_input_files("IMG_1234.jpg")`, Playwright looks for that beside
the test. It is not there; it is in somebody's Pictures folder. The step raises,
the form never submits, and every case in the flow goes red on a listing form
with nothing wrong with it.

The file is built in memory instead. The generation half of this needs no
browser; the tests that prove the bytes really are an image drive a real one and
are marked integration.
"""

import base64
import importlib.util

import pytest

from app.codegen.converter import build_ir, normalise
from app.codegen.generator import render
from app.models.enums import ActionType

URL = "https://shop.test/listings/new"

PHOTOS = [{"strategy": "test_id", "value": "listing-photos", "unique": True, "score": 99}]


def upload(files):
    return {
        "action_type": ActionType.UPLOAD.value,
        "url": URL,
        "frame_path": [],
        "selectors": PHOTOS,
        "element": {
            "tag": "input", "input_type": "file", "role": None,
            "accessible_name": "Photos", "text": None,
            "attributes": {"data-testid": "listing-photos"},
            "bounding_box": {"x": 10, "y": 10, "width": 200, "height": 40},
        },
        "payload": {"files": files},
        "is_ignored": False,
    }


def built(actions):
    ir = build_ir(normalise(actions), suite_name="New listing", start_url=URL)
    return ir, render(ir, browser_info={})


def helper_module(tmp_path, files):
    """Import the generated pages/_files.py the way the suite would."""
    source = next(f.content for f in files if f.path == "pages/_files.py")
    path = tmp_path / "_files.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_files", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# What gets generated
# ---------------------------------------------------------------------------
def test_the_recorded_name_is_passed_to_a_builder_not_used_as_a_path() -> None:
    _, files = built([upload(["IMG_1234.jpg"])])
    body = next(f.content for f in files if f.path.startswith("tests/"))

    assert "set_input_files(sample_file('IMG_1234.jpg'))" in body
    assert "from pages._files import sample_file" in body
    # The old shape, and the whole bug: a path to a file on someone else's disk.
    assert "set_input_files('IMG_1234.jpg')" not in body


def test_several_files_each_get_one() -> None:
    """A listing form takes a handful of photographs at once."""
    _, files = built([upload(["front.jpg", "kitchen.jpg", "plan.png"])])
    body = next(f.content for f in files if f.path.startswith("tests/"))

    assert body.count("sample_file(") == 3
    assert "sample_file('plan.png')" in body


def test_a_suite_that_uploads_nothing_carries_no_fixture() -> None:
    """The JPEG is 9 KB. A suite that never asks for one should not ship it."""
    click = upload(["x.jpg"]) | {"action_type": ActionType.CLICK.value, "payload": {}}
    _, files = built([click])

    assert not [f for f in files if f.path == "pages/_files.py"]
    body = next(f.content for f in files if f.path.startswith("tests/"))
    assert "sample_file" not in body


# ---------------------------------------------------------------------------
# What the builder returns
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name, expected_name, mime, magic",
    [
        ("IMG_1234.jpg", "IMG_1234.jpg", "image/jpeg", "ffd8ff"),
        ("photo.JPEG", "photo.JPEG", "image/jpeg", "ffd8ff"),
        ("plan.png", "plan.png", "image/png", "89504e47"),
        ("deed.pdf", "deed.pdf", "application/pdf", "25504446"),
        ("notes.txt", "notes.txt", "text/plain", None),
    ],
)
def test_name_type_and_bytes_all_agree(tmp_path, name, expected_name, mime, magic) -> None:
    """A site may check the extension, the type the browser reports, or the
    first few bytes. All three have to say the same thing, or a rejection tells
    you about the fixture instead of about the site."""
    _, files = built([upload([name])])
    sample = helper_module(tmp_path, files).sample_file(name)

    assert sample["name"] == expected_name
    assert sample["mimeType"] == mime
    if magic:
        assert sample["buffer"][: len(magic) // 2].hex() == magic


def test_a_type_we_cannot_produce_is_renamed_rather_than_faked(tmp_path) -> None:
    """PNG bytes wearing a .gif extension are turned away by anything that looks
    inside the file, and that failure reads as a bug in the upload. Changing the
    name says what is actually being sent."""
    _, files = built([upload(["clip.gif"])])
    sample = helper_module(tmp_path, files).sample_file("clip.gif")

    assert sample["name"] == "clip.png"
    assert sample["mimeType"] == "image/png"
    assert sample["buffer"][:4].hex() == "89504e47"


def test_a_name_with_no_extension_still_produces_something(tmp_path) -> None:
    _, files = built([upload(["scan"])])
    sample = helper_module(tmp_path, files).sample_file("scan")

    assert sample["name"] == "scan.png"
    assert sample["buffer"][:4].hex() == "89504e47"


def test_the_generated_helper_is_plain_ascii(tmp_path) -> None:
    """The JPEG is carried as base64 for exactly this reason: a generated file
    with raw image bytes in it is not a text file, and the suite is checked out,
    diffed and edited as text."""
    _, files = built([upload(["x.jpg"])])
    source = next(f.content for f in files if f.path == "pages/_files.py")

    assert source.isascii()


# ---------------------------------------------------------------------------
# They really are images
# ---------------------------------------------------------------------------
UPLOAD_PAGE = """
<input type="file" id="f"><img id="p">
<script>
document.getElementById('f').addEventListener('change', (e) => {
  const r = new FileReader();
  r.onload = () => { document.getElementById('p').src = r.result; };
  r.readAsDataURL(e.target.files[0]);
});
</script>
"""


@pytest.mark.integration
@pytest.mark.parametrize("name", ["IMG_1234.jpg", "plan.png"])
def test_a_browser_decodes_what_we_upload(tmp_path, name) -> None:
    """The point of all of it. Valid magic bytes are not the same as an image a
    browser will actually render, and a form that resizes or previews the photo
    does exactly that.
    """
    from playwright.sync_api import sync_playwright

    _, files = built([upload([name])])
    sample = helper_module(tmp_path, files).sample_file(name)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content(UPLOAD_PAGE)
        page.locator("#f").set_input_files(sample)

        seen = page.evaluate(
            "() => { const f = document.getElementById('f').files[0];"
            " return [f.name, f.type, f.size]; }"
        )
        assert seen[0] == name
        assert seen[2] == len(sample["buffer"])

        page.wait_for_function(
            "() => document.getElementById('p').naturalWidth > 0", timeout=5_000
        )
        width, height = page.evaluate(
            "() => { const i = document.getElementById('p');"
            " return [i.naturalWidth, i.naturalHeight]; }"
        )
        # Big enough that a form asking for a minimum size accepts it.
        assert (width, height) == (800, 600)
        browser.close()


@pytest.mark.integration
def test_the_base64_in_the_template_is_a_real_jpeg(tmp_path) -> None:
    """Guards the one part that cannot be regenerated from code. If this ever
    fails, the constant has been mangled - by an editor, a merge, or a rewrite
    of the template - and every upload step in every suite is broken."""
    _, files = built([upload(["x.jpg"])])
    module = helper_module(tmp_path, files)
    raw = base64.b64decode(module._JPEG_BASE64)

    assert raw[:3].hex() == "ffd8ff"       # SOI, and it is a JFIF stream
    assert raw[-2:].hex() == "ffd9"        # EOI: the file is whole, not truncated
    assert len(raw) > 1_000


# ---------------------------------------------------------------------------
# The project's own files, when it has any
# ---------------------------------------------------------------------------
"""A generated placeholder uploads correctly and gets past the form. It is still
a grey rectangle, so a site that shows the photograph back on the listing has
nothing to show, and a test that checks the gallery cannot be written against
it. A project that has uploaded real ones gets those instead."""


def with_samples(tmp_path, files: dict[str, bytes]):
    """The generated helper, with a `samples/` folder beside it as a run has."""
    _, generated = built([upload(["IMG_1234.jpg"])])
    source = next(f.content for f in generated if f.path == "pages/_files.py")

    pages = tmp_path / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "_files.py").write_text(source, encoding="utf-8")
    samples = tmp_path / "samples"
    samples.mkdir(exist_ok=True)
    for name, data in files.items():
        (samples / name).write_bytes(data)

    spec = importlib.util.spec_from_file_location("_files_lib", pages / "_files.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REAL_JPEG = b"\xff\xd8\xff" + b"a photograph" * 20 + b"\xff\xd9"


def test_a_real_photograph_is_used_instead_of_the_placeholder(tmp_path) -> None:
    module = with_samples(tmp_path, {"house-01.jpg": REAL_JPEG})

    sample = module.sample_file("IMG_1234.jpg")

    assert sample["buffer"] == REAL_JPEG
    assert sample["name"] == "house-01.jpg"
    assert sample["mimeType"] == "image/jpeg"


def test_a_form_asking_for_six_photographs_gets_six_different_ones(tmp_path) -> None:
    """A listing whose gallery is the same picture six times is not what anybody
    meant by uploading a library."""
    module = with_samples(tmp_path, {
        f"house-{n}.jpg": b"\xff\xd8\xff" + bytes([n]) * 50 + b"\xff\xd9" for n in range(3)
    })

    picked = [module.sample_file("IMG.jpg")["name"] for _ in range(3)]

    assert len(set(picked)) == 3


def test_the_library_wraps_round_rather_than_running_out(tmp_path) -> None:
    module = with_samples(tmp_path, {"only.jpg": REAL_JPEG})

    assert [module.sample_file("x.jpg")["name"] for _ in range(3)] == ["only.jpg"] * 3


def test_a_kind_nobody_uploaded_falls_back_to_the_placeholder(tmp_path) -> None:
    """An image asked for where only PDFs were uploaded must not upload the PDF.
    A form that takes images will not take it, and the failure would read as a
    bug in the upload."""
    module = with_samples(tmp_path, {"terms.pdf": b"%PDF-1.4 ..."})

    sample = module.sample_file("IMG_1234.jpg")

    assert sample["mimeType"] == "image/jpeg"
    assert sample["buffer"][:3].hex() == "ffd8ff"      # the built-in one
    assert b"%PDF" not in sample["buffer"]


def test_a_project_with_no_library_behaves_exactly_as_before(tmp_path) -> None:
    module = with_samples(tmp_path, {})

    sample = module.sample_file("IMG_1234.jpg")

    assert sample["name"] == "IMG_1234.jpg"
    assert sample["buffer"][:3].hex() == "ffd8ff"


def test_a_png_asked_for_takes_a_png_from_the_library(tmp_path) -> None:
    """Matched on the kind of file, not just on there being one."""
    module = with_samples(tmp_path, {
        "photo.jpg": REAL_JPEG,
        "plan.png": b"\x89PNG\r\n\x1a\n" + b"pixels" * 10,
    })

    assert module.sample_file("anything.png")["name"] == "plan.png"
    assert module.sample_file("anything.jpg")["name"] == "photo.jpg"
