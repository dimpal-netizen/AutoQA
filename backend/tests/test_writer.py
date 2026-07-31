"""Writing a suite to disk.

The folder is what a QA Engineer opens in VS Code, so it must match the current
recording exactly — no stale files from a previous generation, and nothing
written outside the suite folder.
"""

from pathlib import Path

import pytest

from app.codegen.writer import ALLOWED_SUFFIXES, safe_segment, suite_directory, write_suite

BUNDLE = {
    "tests/test_login.py": "def test_login(page):\n    pass\n",
    "pages/login_page.py": "class LoginPage:\n    pass\n",
    "conftest.py": "import pytest\n",
    "pytest.ini": "[pytest]\n",
}


def test_writes_the_whole_bundle(tmp_path: Path) -> None:
    written = write_suite(tmp_path, BUNDLE)

    assert sorted(written) == sorted(BUNDLE)
    for relative, content in BUNDLE.items():
        assert (tmp_path / relative).read_text(encoding="utf-8") == content


def test_nested_directories_are_created(tmp_path: Path) -> None:
    write_suite(tmp_path, BUNDLE)

    assert (tmp_path / "pages" / "login_page.py").is_file()
    assert (tmp_path / "tests" / "test_login.py").is_file()


def test_regenerating_removes_files_that_are_gone(tmp_path: Path) -> None:
    """A renamed page must not leave its old page object behind.

    Otherwise the folder slowly fills with dead files that still import and
    still look real to whoever opens it.
    """
    write_suite(tmp_path, BUNDLE)
    assert (tmp_path / "pages" / "login_page.py").is_file()

    smaller = {k: v for k, v in BUNDLE.items() if k != "pages/login_page.py"}
    write_suite(tmp_path, smaller)

    assert not (tmp_path / "pages" / "login_page.py").exists()
    assert (tmp_path / "conftest.py").is_file()


def test_empty_directories_are_tidied_away(tmp_path: Path) -> None:
    write_suite(tmp_path, BUNDLE)
    write_suite(tmp_path, {"conftest.py": "import pytest\n"})

    assert not (tmp_path / "pages").exists()


def test_files_we_did_not_generate_are_left_alone(tmp_path: Path) -> None:
    """Someone's notes or a .env in the folder must survive regeneration."""
    write_suite(tmp_path, BUNDLE)
    (tmp_path / "notes.rst").write_text("mine", encoding="utf-8")

    write_suite(tmp_path, BUNDLE)

    assert (tmp_path / "notes.rst").read_text(encoding="utf-8") == "mine"


@pytest.mark.parametrize(
    "path",
    ["../escape.py", "../../etc/passwd.py", "pages/../../outside.py"],
)
def test_paths_escaping_the_folder_are_refused(tmp_path: Path, path: str) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()

    written = write_suite(suite, {path: "print('nope')"})

    assert written == []
    assert not (tmp_path / "escape.py").exists()
    assert not (tmp_path / "outside.py").exists()


def test_unexpected_file_types_are_refused(tmp_path: Path) -> None:
    written = write_suite(tmp_path, {"payload.exe": "MZ", "run.sh": "rm -rf /"})

    assert written == []
    assert not (tmp_path / "payload.exe").exists()
    assert not (tmp_path / "run.sh").exists()


def test_allowed_suffixes_cover_what_the_generator_emits() -> None:
    for path in BUNDLE:
        assert Path(path).suffix in ALLOWED_SUFFIXES


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Shop Checkout", "shop-checkout"),
        ("../../etc", "etc"),
        ("Order #42 / edit", "order-42-edit"),
        ("", "fallback"),
        ("...", "fallback"),
    ],
)
def test_directory_names_are_safe(raw: str, expected: str) -> None:
    assert safe_segment(raw, "fallback") == expected


def test_suite_directory_is_readable_and_unique() -> None:
    first = suite_directory(1, "Shop Checkout", 7, "Login flow")
    second = suite_directory(1, "Shop Checkout", 8, "Login flow")

    assert first.name == "007-login-flow"
    assert first.parent.name == "001-shop-checkout"
    # Same name, different suite: the id keeps them apart.
    assert first != second


def test_content_is_written_with_unix_newlines(tmp_path: Path) -> None:
    """Generated Python should not gain CRLF just because it was made on Windows."""
    write_suite(tmp_path, {"conftest.py": "import pytest\nimport os\n"})

    raw = (tmp_path / "conftest.py").read_bytes()
    assert b"\r\n" not in raw
