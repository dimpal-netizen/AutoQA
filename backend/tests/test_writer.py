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


def test_suite_directory_reads_like_a_path_a_person_would_type() -> None:
    """This is pasted into VS Code, so no database ids in the common case."""
    path = suite_directory("Shop Checkout", "Login flow")

    assert path.name == "login-flow"
    assert path.parent.name == "shop-checkout"


def test_a_clashing_suite_name_is_disambiguated() -> None:
    """Two suites called the same thing must not overwrite each other."""
    plain = suite_directory("Shop Checkout", "Login flow")
    disambiguated = suite_directory("Shop Checkout", "Login flow", disambiguator=8)

    assert disambiguated.name == "login-flow-8"
    assert disambiguated != plain
    assert disambiguated.parent == plain.parent


def test_removing_a_suite_folder_refuses_paths_outside_generated(tmp_path: Path) -> None:
    """A stale database row must not become an arbitrary rmtree."""
    from app.codegen.writer import remove_suite_directory

    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "keep.txt").write_text("do not delete me")

    remove_suite_directory(outside)

    assert (outside / "keep.txt").exists()


def test_removing_a_suite_folder_deletes_it_and_an_emptied_project(tmp_path: Path) -> None:
    from app.codegen.writer import remove_suite_directory
    from app.core.config import settings

    root = settings.generated_dir
    suite = root / "shop" / "old-name"
    suite.mkdir(parents=True, exist_ok=True)
    (suite / "conftest.py").write_text("x = 1")

    remove_suite_directory(suite)

    assert not suite.exists()
    # The project folder held nothing else, so it goes too.
    assert not (root / "shop").exists()


def test_content_is_written_with_unix_newlines(tmp_path: Path) -> None:
    """Generated Python should not gain CRLF just because it was made on Windows."""
    write_suite(tmp_path, {"conftest.py": "import pytest\nimport os\n"})

    raw = (tmp_path / "conftest.py").read_bytes()
    assert b"\r\n" not in raw
