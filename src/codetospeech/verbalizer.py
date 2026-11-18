"""Convert source code into text a speech engine can read naturally.

The verbalizer tokenizes each line, splits identifiers into words
(``getUserName`` -> "get user name", ``MAX_SIZE`` -> "max size"), names
punctuation and operators ("==" -> "equals equals"), and announces
indentation changes so the listener can follow block structure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Longest operators first so the tokenizer matches greedily.
OPERATORS: dict[str, str] = {
    "===": "strict equals",
    "!==": "strict not equals",
    "**=": "power equals",
    "//=": "floor divide equals",
    "<<=": "shift left equals",
    ">>=": "shift right equals",
    "...": "ellipsis",
    "==": "equals equals",
    "!=": "not equals",
    "<=": "less than or equal",
    ">=": "greater than or equal",
    "->": "arrow",
    "=>": "fat arrow",
    "+=": "plus equals",
    "-=": "minus equals",
    "*=": "times equals",
    "/=": "divide equals",
    "%=": "mod equals",
    "&&": "and and",
    "||": "or or",
    "++": "plus plus",
    "--": "minus minus",
    "**": "power",
    "//": "floor divide",
    "<<": "shift left",
    ">>": "shift right",
    "::": "double colon",
    ":=": "walrus",
    "=": "equals",
    "+": "plus",
    "-": "minus",
    "*": "star",
    "/": "slash",
    "%": "percent",
    "<": "less than",
    ">": "greater than",
    "!": "bang",
    "&": "ampersand",
    "|": "pipe",
    "^": "caret",
    "~": "tilde",
    "?": "question mark",
    ":": "colon",
    ";": "semicolon",
    ",": "comma",
    ".": "dot",
    "(": "open paren",
    ")": "close paren",
    "[": "open bracket",
    "]": "close bracket",
    "{": "open brace",
    "}": "close brace",
    "@": "at",
    "#": "hash",
    "$": "dollar",
    "\\": "backslash",
}

# Punctuation that is usually noise when listening; skipped in "brief" mode.
BRIEF_SILENT = {",", ";", "(", ")", "[", "]", "{", "}", "."}

_OP_PATTERN = "|".join(re.escape(op) for op in sorted(OPERATORS, key=len, reverse=True))
TOKEN_RE = re.compile(
    r"""
    (?P<comment>\#[^\n]*|//[^\n]*)
  | (?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
  | (?P<number>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>""" + _OP_PATTERN + r""")
  | (?P<space>\s+)
  | (?P<other>.)
    """,
    re.VERBOSE,
)

_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def split_identifier(name: str) -> list[str]:
    """Split ``camelCase``, ``PascalCase`` and ``snake_case`` names into lowercase words."""
    words: list[str] = []
    for part in name.split("_"):
        words.extend(w.lower() for w in _CAMEL_RE.findall(part))
    return words


@dataclass
class Verbalizer:
    """Turns code into speakable sentences.

    Args:
        brief: skip low-information punctuation such as commas and brackets.
        announce_indent: say "indent" / "dedent" when block depth changes.
        read_comments: include comment text; otherwise just say "comment".
        line_numbers: prefix each spoken line with "line N".
    """

    brief: bool = False
    announce_indent: bool = True
    read_comments: bool = True
    line_numbers: bool = False
    indent_width: int = 4
    _depth_stack: list[int] = field(default_factory=lambda: [0], init=False, repr=False)

    def verbalize_line(self, line: str) -> str:
        words: list[str] = []
        for match in TOKEN_RE.finditer(line):
            kind, text = match.lastgroup, match.group()
            if kind == "space":
                continue
            if kind == "comment":
                body = text.lstrip("#/").strip()
                words.append(f"comment {body}" if self.read_comments and body else "comment")
            elif kind == "string":
                body = text[1:-1]
                words.append(f"string {body}" if body else "empty string")
            elif kind == "number":
                words.append(text)
            elif kind == "ident":
                words.extend(split_identifier(text) or [text])
            elif kind == "op":
                if self.brief and text in BRIEF_SILENT:
                    continue
                words.append(OPERATORS[text])
            else:
                words.append(text)
        return " ".join(words)

    def _indent_words(self, line: str) -> list[str]:
        expanded = line.expandtabs(self.indent_width)
        depth = len(expanded) - len(expanded.lstrip(" "))
        out: list[str] = []
        if depth > self._depth_stack[-1]:
            self._depth_stack.append(depth)
            out.append("indent")
        else:
            while depth < self._depth_stack[-1]:
                self._depth_stack.pop()
                out.append("dedent")
        return out

    def verbalize(self, code: str, start_line: int = 1) -> list[str]:
        """Return one spoken sentence per non-blank line of ``code``."""
        self._depth_stack = [0]
        sentences: list[str] = []
        for number, line in enumerate(code.splitlines(), start=start_line):
            if not line.strip():
                continue
            parts: list[str] = []
            if self.line_numbers:
                parts.append(f"line {number}")
            if self.announce_indent:
                parts.extend(self._indent_words(line))
            spoken = self.verbalize_line(line)
            if spoken:
                parts.append(spoken)
            sentences.append(" ".join(parts) + ".")
        return sentences


def verbalize(code: str, **options) -> str:
    """Convenience wrapper: verbalize ``code`` and join the sentences."""
    return "\n".join(Verbalizer(**options).verbalize(code))
