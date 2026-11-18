"""Release configuration: what is deployed, and the one-command rollback.

A release pins the retrieval index, the model id, the guardrail version and top-k. The
active release is named in releases/ACTIVE; every promotion is appended to
releases/HISTORY.log, so rollback means "re-activate the previous good release".
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASES = ROOT / "releases"


@dataclass
class Release:
    version: str
    model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    index_exclude: list[str] = field(default_factory=list)   # clause ids left out of the index
    top_k: int = 6
    quarantine: bool = True
    notes: str = ""

    @classmethod
    def load(cls, version: str, root: Path = RELEASES) -> "Release":
        return cls(**json.loads((root / f"{version}.json").read_text()))


def active_version(root: Path = RELEASES) -> str:
    return (root / "ACTIVE").read_text().strip()


def active(root: Path = RELEASES) -> Release:
    return Release.load(active_version(root), root)


def promote(version: str, actor: str, reason: str, root: Path = RELEASES) -> None:
    Release.load(version, root)                       # must exist and parse
    (root / "ACTIVE").write_text(version + "\n")
    with (root / "HISTORY.log").open("a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "version": version,
                            "actor": actor, "reason": reason}) + "\n")


def history(root: Path = RELEASES) -> list[dict]:
    p = root / "HISTORY.log"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def rollback(actor: str, reason: str, root: Path = RELEASES) -> str:
    """Re-activate the most recent release before the current one."""
    cur = active_version(root)
    for h in reversed(history(root)):
        if h["version"] != cur:
            promote(h["version"], actor, f"ROLLBACK from {cur}: {reason}", root)
            return h["version"]
    raise RuntimeError("no earlier release in HISTORY.log to roll back to")
