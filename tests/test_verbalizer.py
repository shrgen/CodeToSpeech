import pytest

from codetospeech.cli import main
from codetospeech.verbalizer import Verbalizer, split_identifier, verbalize


@pytest.mark.parametrize(
    "name, words",
    [
        ("getUserName", ["get", "user", "name"]),
        ("HTTPServer", ["http", "server"]),
        ("MAX_SIZE", ["max", "size"]),
        ("snake_case_name", ["snake", "case", "name"]),
        ("parse2Json", ["parse", "2", "json"]),
        ("x", ["x"]),
    ],
)
def test_split_identifier(name, words):
    assert split_identifier(name) == words


def test_operators_and_numbers():
    assert Verbalizer().verbalize_line("x == 10") == "x equals equals 10"
    assert Verbalizer().verbalize_line("a != b") == "a not equals b"


def test_strings_and_comments():
    v = Verbalizer()
    assert v.verbalize_line('msg = "hi"  # greet') == "msg equals string hi comment greet"
    assert Verbalizer(read_comments=False).verbalize_line("# secret") == "comment"
    assert v.verbalize_line("s = ''") == "s equals empty string"


def test_brief_mode_skips_punctuation():
    assert Verbalizer(brief=True).verbalize_line("f(a, b)") == "f a b"
    assert Verbalizer().verbalize_line("f(a, b)") == "f open paren a comma b close paren"


def test_indentation_announced():
    code = "def add(a, b):\n    return a + b\nprint(add(1, 2))\n"
    lines = Verbalizer(brief=True).verbalize(code)
    assert lines == [
        "def add a b colon.",
        "indent return a plus b.",
        "dedent print add 1 2.",
    ]


def test_line_numbers_and_blank_lines():
    out = verbalize("x = 1\n\ny = 2", line_numbers=True, announce_indent=False)
    assert out == "line 1 x equals 1.\nline 3 y equals 2."


def test_cli_text_only(tmp_path, capsys):
    src = tmp_path / "sample.py"
    src.write_text("a = 1\nb = 2\nc = 3\n")
    assert main([str(src), "--text-only", "--lines", "2-3"]) == 0
    assert capsys.readouterr().out.splitlines() == ["b equals 2.", "c equals 3."]


def test_cli_missing_file(capsys):
    assert main(["/nonexistent/file.py", "--text-only"]) == 1
