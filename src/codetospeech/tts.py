"""Text-to-speech backends.

Tries, in order: pyttsx3 (cross-platform, optional dependency), the
``espeak-ng``/``espeak`` command, and macOS ``say``. If none is available,
``speak`` raises :class:`NoBackendError`.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Iterable, Optional


class NoBackendError(RuntimeError):
    """Raised when no text-to-speech engine is installed."""


def _command_backend() -> Optional[str]:
    for cmd in ("espeak-ng", "espeak", "say"):
        if shutil.which(cmd):
            return cmd
    return None


def available_backend() -> Optional[str]:
    try:
        import pyttsx3  # noqa: F401

        return "pyttsx3"
    except ImportError:
        return _command_backend()


def speak(sentences: Iterable[str], rate: int = 175, output: Optional[str] = None) -> str:
    """Speak ``sentences`` (or save them to ``output``). Returns the backend used."""
    text = "\n".join(sentences)
    backend = available_backend()
    if backend is None:
        raise NoBackendError(
            "No text-to-speech engine found. Install one with "
            "`pip install codetospeech[tts]` or your system's espeak-ng."
        )

    if backend == "pyttsx3":
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", rate)
        if output:
            engine.save_to_file(text, output)
        else:
            engine.say(text)
        engine.runAndWait()
    elif backend in ("espeak-ng", "espeak"):
        args = [backend, "-s", str(rate)]
        if output:
            args += ["-w", output]
        subprocess.run(args + [text], check=True)
    else:  # macOS say
        args = ["say", "-r", str(rate)]
        if output:
            args += ["-o", output]
        subprocess.run(args + [text], check=True)
    return backend
