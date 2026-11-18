# CodeToSpeech

Read source code aloud. CodeToSpeech turns code into natural, speakable
text and plays it through a text-to-speech engine — useful for
accessibility, code review by ear, or listening to code on the go.

```
$ codetospeech example.py --text-only --brief
def get user name user id colon.
indent return users dot get user id.
```

## What it does

- **Splits identifiers into words** — `getUserName` → "get user name", `MAX_SIZE` → "max size".
- **Names operators and punctuation** — `==` → "equals equals", `->` → "arrow".
- **Announces block structure** — "indent" / "dedent" when indentation changes.
- **Reads strings and comments** — or just says "comment" with `--no-comments`.
- **Speaks or saves audio** via pyttsx3, `espeak-ng`/`espeak`, or macOS `say`.

## Install

```bash
pip install -e .            # core (text output, uses espeak/say if installed)
pip install -e ".[tts]"     # adds pyttsx3 for cross-platform speech
pip install -e ".[dev]"     # adds pytest
```

## Usage

```bash
codetospeech FILE                 # speak the whole file
codetospeech FILE --lines 10-20   # speak only lines 10–20
codetospeech FILE --text-only     # print what would be spoken
codetospeech FILE -o out.wav      # save audio instead of playing
cat FILE | codetospeech -         # read from stdin
```

Options: `--brief` (skip commas/brackets), `--no-indent`, `--no-comments`,
`-n/--line-numbers`, `-r/--rate WPM`.

### As a library

```python
from codetospeech import verbalize
print(verbalize("total += price * qty", brief=True))
# total plus equals price star qty.
```

## Development

```bash
pytest
```

## Roadmap

- Language-aware keywords (e.g. read `def` as "define function")
- Configurable pronunciation dictionaries
- Editor integrations (VS Code, Vim)
