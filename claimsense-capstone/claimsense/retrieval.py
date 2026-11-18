"""Retrieval over the policy corpus, with an input guardrail that quarantines injected text.

The index is plain keyword scoring (BM25-style) over the clause markdown files, so it runs
offline at $0 and every hit carries its clause id. The quarantine step runs BEFORE anything
reaches model context: clauses or document text that read like instructions to the model
are pulled out, recorded, and never cited.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from .models import Clause, Document

CORPUS_DIR = Path(__file__).parent / "data" / "corpus"
CLAUSE_ID = re.compile(r"^#\s*(CLS-[A-Z]+-\d{3})\s*[—-]\s*(.+)$")
TOKEN = re.compile(r"[a-z0-9]+")
STOP = set("the a an of to and or is are be by for on in any from with as at this that its it not no "
           "shown under before after only".split())

# Tripwire patterns: text addressed to the model rather than describing a loss or a rule.
INJECTION_PATTERNS = [
    r"ignore (all |any )?(prior|previous|above) (instructions|constraints|rules)",
    r"\bsystem (instruction|prompt|override)\b",
    r"\bdisregard\b.*\b(policy|instructions|rules)\b",
    r"\b(auto[- ]?approve|pre[- ]?authori[sz]ed|authori[sz]e (the )?payment|issue (the )?payment)\b",
    r"\bno (human|adjuster) (review|confirmation|needed|required)\b",
    r"\b(skip|bypass) (the )?(adjuster|human|review|siu)\b",
    r"\b(include|attach|append|send|email|forward) (the )?(full|complete|entire)? ?(customer |claimant )?(record|file|claims?)\b.*\b(for|of)\b",
    r"\bemail\b.*@",
    r"\byou (must|are required to|will now)\b",
    r"\bas the (ai|assistant|model)\b",
]
_INJ = [re.compile(p, re.I) for p in INJECTION_PATTERNS]


def injection_hits(text: str) -> list[str]:
    return [p.pattern for p in _INJ if p.search(text or "")]


def load_corpus(directory: Path = CORPUS_DIR, exclude: set[str] | None = None) -> list[Clause]:
    out = []
    for f in sorted(directory.glob("*.md")):
        lines = f.read_text().strip().splitlines()
        m = CLAUSE_ID.match(lines[0]) if lines else None
        if not m:
            continue
        cid, title = m.group(1), m.group(2).strip()
        if exclude and cid in exclude:
            continue
        out.append(Clause(cid, title, "\n".join(lines[1:]).strip()))
    return out


def _tok(s: str) -> list[str]:
    return [t for t in TOKEN.findall(s.lower()) if t not in STOP]


class PolicyIndex:
    def __init__(self, clauses: list[Clause], name: str = "full"):
        self.name = name
        self.clauses = clauses
        self.quarantined: list[Clause] = []
        clean = []
        for c in clauses:
            hits = injection_hits(c.text)
            if hits:
                c.quarantined, c.quarantine_reason = True, hits[0]
                self.quarantined.append(c)
            else:
                clean.append(c)
        self.docs = [(c, Counter(_tok(c.title + " " + c.text + " " + c.title))) for c in clean]
        n = max(len(self.docs), 1)
        df = Counter(t for _, tf in self.docs for t in tf)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self.avg = sum(sum(tf.values()) for _, tf in self.docs) / n

    def search(self, query: str, k: int = 5) -> list[Clause]:
        q = _tok(query)
        scored = []
        for c, tf in self.docs:
            L = sum(tf.values())
            s = sum(self.idf.get(t, 0) * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * L / self.avg))
                    for t in q if t in tf)
            if s > 0:
                scored.append((s, c.clause_id, c))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [c for _, _, c in scored[:k]]

    def ids(self) -> set[str]:
        return {c.clause_id for c, _ in self.docs}


def quarantine_documents(docs: list[Document]) -> tuple[list[Document], list[str]]:
    """Strip instruction-like OCR text before it reaches context. Metadata is kept."""
    flagged = []
    for d in docs:
        if d.text and injection_hits(d.text):
            flagged.append(d.document_id)
            d.text = "[quarantined: text removed by input guardrail]"
    return docs, flagged
