"""Command-line interface: ``codetospeech FILE``."""

from __future__ import annotations

import argparse
import sys

from .tts import NoBackendError, speak
from .verbalizer import Verbalizer


def _parse_range(value: str) -> tuple[int, int]:
    start, _, end = value.partition("-")
    try:
        lo = int(start)
        hi = int(end) if end else lo
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid line range: {value!r} (use N or N-M)")
    if lo < 1 or hi < lo:
        raise argparse.ArgumentTypeError(f"invalid line range: {value!r}")
    return lo, hi


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="codetospeech", description="Read source code aloud.")
    p.add_argument("file", help="source file to read, or '-' for stdin")
    p.add_argument("-l", "--lines", type=_parse_range, help="only read lines N or N-M")
    p.add_argument("-t", "--text-only", action="store_true", help="print the spoken text instead of speaking")
    p.add_argument("-o", "--output", help="save audio to this file instead of playing it")
    p.add_argument("-r", "--rate", type=int, default=175, help="speech rate in words per minute")
    p.add_argument("--brief", action="store_true", help="skip commas, brackets and other low-information punctuation")
    p.add_argument("--no-indent", action="store_true", help="don't announce indentation changes")
    p.add_argument("--no-comments", action="store_true", help="say 'comment' instead of reading comment text")
    p.add_argument("-n", "--line-numbers", action="store_true", help="announce line numbers")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.file == "-":
            code = sys.stdin.read()
        else:
            with open(args.file, encoding="utf-8") as fh:
                code = fh.read()
    except OSError as exc:
        print(f"codetospeech: {exc}", file=sys.stderr)
        return 1

    start = 1
    if args.lines:
        lo, hi = args.lines
        code = "\n".join(code.splitlines()[lo - 1 : hi])
        start = lo

    verbalizer = Verbalizer(
        brief=args.brief,
        announce_indent=not args.no_indent,
        read_comments=not args.no_comments,
        line_numbers=args.line_numbers,
    )
    sentences = verbalizer.verbalize(code, start_line=start)

    if args.text_only:
        print("\n".join(sentences))
        return 0

    try:
        speak(sentences, rate=args.rate, output=args.output)
    except NoBackendError as exc:
        print(f"codetospeech: {exc}", file=sys.stderr)
        print("Tip: use --text-only to print the spoken text.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
