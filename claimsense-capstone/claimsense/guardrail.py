"""Output guardrail: deterministic checks on every model proposal. Fail closed.

If any check fails, the model's proposal is discarded and the deterministic fallback
decides. The recommendation then carries verdict_source = "deterministic_fallback", so a
model verdict can always be told apart from a fallback one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import Facts, Outcome
from .rules import hard_constraints

CLAUSE_RE = re.compile(r"CLS-[A-Z]+-\d{3}")
MONEY_RE = re.compile(r"\$\s?([\d,]+(?:\.\d\d)?)")
AUTO_DECISION_RE = re.compile(
    r"\b(payment (has been |was )?(issued|sent|released|authori[sz]ed)|authori[sz]ed (for )?payment|"
    r"approved per instruction|no (adjuster|human) (confirmation|review) (needed|required)|"
    r"final (approval|decision)|paid out)\b", re.I)


@dataclass
class GuardResult:
    ok: bool
    violations: list[str] = field(default_factory=list)


def check(proposal: dict[str, Any], facts: Facts, judgment: dict[str, Any], fraud_score: float,
          injuries: bool, retrieved_ids: set[str], quarantined_ids: set[str],
          own_claim: str, foreign_tokens: set[str]) -> GuardResult:
    v: list[str] = []
    outcome = proposal.get("proposed_outcome")
    if outcome not in {o.value for o in Outcome}:
        return GuardResult(False, [f"schema: unknown outcome {outcome!r}"])

    cites = proposal.get("citations") or []
    if not cites:
        v.append("grounding: no clause cited")
    for c in cites:
        if c in quarantined_ids:
            v.append(f"grounding: cited quarantined clause {c}")
        elif c not in retrieved_ids:
            v.append(f"grounding: cited {c}, which was not retrieved")

    forbid = hard_constraints(facts, fraud_score, injuries, judgment.get("exclusion_flags"))
    for why in sorted(forbid.get(outcome, ())):
        v.append(f"constraint: {outcome} forbidden — {why}")
    if outcome == Outcome.APPROVE.value and len(judgment.get("fraud_indicators", [])) >= 2:
        v.append("constraint: approval with two or more fraud indicators (CLS-FRD-007)")

    text = " ".join([proposal.get("rationale", "")] + list(proposal.get("reasons", [])))
    allowed_money = {facts.net_payable_usd, facts.deductible_usd, facts.gross_loss_usd}
    for m in MONEY_RE.findall(text):
        n = float(m.replace(",", ""))
        if n not in allowed_money and int(n) not in allowed_money:
            v.append(f"money: ${m} was not computed by the deterministic layer")
    if AUTO_DECISION_RE.search(text):
        v.append("authority: text claims a final or executed payment decision (CLS-PAY-012)")

    leaked = sorted(t for t in foreign_tokens if t and t.lower() in text.lower())
    for t in leaked:
        v.append(f"leakage: output references another record ({t})")
    return GuardResult(not v, v)


def redact(text: str, foreign_tokens: set[str]) -> str:
    for t in sorted(foreign_tokens, key=len, reverse=True):
        if t:
            text = re.sub(re.escape(t), "[redacted]", text, flags=re.I)
    return text
