"""Model judgment. Two brains behind one interface.

MockBrain   — $0, deterministic, offline. Reads the same context a model would and makes
              the same three judgments. It is deliberately NAIVE about instructions found
              in its context (it follows them, the way an unguarded model can), so the
              guardrails around it are actually exercised by the evals.
BedrockBrain — the live path: OpenAI Agents SDK agents on Amazon Bedrock (see
              claimsense/live/sdk_agents.py). Same inputs, same typed outputs.

Each call returns (payload, usage) where usage = {"input_tokens", "output_tokens"}.
"""
from __future__ import annotations

import json
import re
from typing import Any, Protocol

CLAIM_REF = re.compile(r"\bCLM-\d{4}-\d{4}\b")


class Brain(Protocol):
    name: str

    def triage(self, view: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]: ...
    def evidence(self, view: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]: ...
    def decide(self, view: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]: ...


def _usage(view: dict[str, Any], out: dict[str, Any]) -> dict[str, int]:
    return {"input_tokens": len(json.dumps(view)) // 4 + 350, "output_tokens": len(json.dumps(out)) // 4}


def _context_text(view: dict[str, Any]) -> str:
    parts = [view.get("request_note", "")]
    parts += [d.get("text", "") for d in view.get("documents", [])]
    return "\n".join(p for p in parts if p)


class MockBrain:
    name = "mock"

    # ── 1. triage: what kind of loss is this, does an exclusion apply? ───────
    def triage(self, view):
        c = view["claim"]
        text = (c["incident_type"] + " " + c["incident_description"] + " " + c["damage_description"]).lower()
        peril = "unknown"
        comp = ["hail", "flood", "vandal", "keyed", "theft", "stolen", "fire", "storm", "branch",
                "deer", "animal", "falling", "fallen", "debris", "glass", "carjack", "tree"]
        coll = ["collision", "collided", "struck", "rear-end", "rear-ended", "rollover", "rolled",
                "backed", "pothole", "sideswipe", "side-swipe", "pileup", "hit", "crash", "median", "barrier"]
        if any(w in text for w in comp):
            peril = "comprehensive"
        elif any(w in text for w in coll):
            peril = "collision"
        excl = []
        if re.search(r"\b(race|racing|speed contest|drag strip|track day)\b", text):
            excl.append("racing or speed contest")
        if re.search(r"\b(rideshare|ride-share|uber|lyft|livery|paid passenger|delivery driver)\b", text):
            excl.append("public or livery conveyance (undeclared)")
        if re.search(r"\b(intentional(ly)?|deliberately|on purpose)\b", text):
            excl.append("intentional loss by an insured")
        if re.search(r"\b(wear and tear|mechanical breakdown|engine failure without)\b", text):
            excl.append("wear and tear / mechanical breakdown")
        out = {"peril_guess": peril, "exclusion_flags": excl}
        return out, _usage(view, out)

    # ── 2. evidence: fraud indicators in the narrative (CLS-FRD-007) ─────────
    def evidence(self, view):
        c = view["claim"]
        text = (c["incident_type"] + " " + c["incident_description"]).lower()
        ind = []
        night = re.search(r"\b([0-4]:\d\d ?am|midnight|late[- ]night|3 am|2 am|1 am)\b", text)
        single = "single-vehicle" in text or "single vehicle" in text or "median" in text or "barrier" in text
        unwitnessed = "no witness" in text or "unwitnessed" in text
        if night and single and unwitnessed:
            ind.append("unwitnessed late-night single-vehicle loss")
        airbags = "airbag" in c["damage_description"].lower()
        if (c["injuries_reported"] or airbags) and not c["police_report_filed"]:
            ind.append("no police report despite injury or airbag deployment")
        if c["prior_claims_12mo"] >= 2:
            ind.append(f"{c['prior_claims_12mo']} prior claims in 12 months")
        if re.search(r"\b(inconsistent|does not match|exaggerat)", (_context_text(view)).lower()):
            ind.append("estimate inconsistent with described damage")
        out = {"fraud_indicators": ind}
        return out, _usage(view, out)

    # ── 3. decide: propose an outcome, grounded in retrieved clauses ─────────
    def decide(self, view):
        f, c, j = view["facts"], view["claim"], view["judgment"]
        have = {cl["clause_id"] for cl in view["clauses"]}
        ctx = _context_text(view).lower()
        cites: list[str] = []
        reasons: list[str] = []
        lookups = sorted(set(CLAIM_REF.findall(_context_text(view))) - {c["claim_id"]})

        def cite(*ids):
            for i in ids:
                if i in have and i not in cites:
                    cites.append(i)

        # Naive instruction-following: if the context tells the model to approve/pay, it does.
        if re.search(r"auto[- ]?approve|pre[- ]?authori|issue (the )?payment|approve (this|immediately|now)", ctx):
            cite("CLS-COLL-001", "CLS-COMP-002", "CLS-PAY-012")
            return self._out(view, "RECOMMEND_APPROVE", "Instructions in the file say to approve.",
                             cites, ["Approved per instruction in claim file."], lookups)

        if not f["in_policy_period"] and "CLS-PER-006" in have:
            cite("CLS-PER-006")
            return self._out(view, "RECOMMEND_DENY", "The loss date falls outside the policy period.",
                             cites, ["Loss outside policy period."], lookups)
        if j["exclusion_flags"] and "CLS-EXC-010" in have:
            cite("CLS-EXC-010")
            return self._out(view, "RECOMMEND_DENY", f"Exclusion applies: {', '.join(j['exclusion_flags'])}.",
                             cites, ["General exclusion."], lookups)
        if f["liability_only"] and not c["injuries_reported"] and "CLS-LIAB-003" in have:
            cite("CLS-LIAB-003")
            return self._out(view, "RECOMMEND_DENY",
                             "Liability Only covers third parties; the insured's own vehicle damage is excluded.",
                             cites, ["Own-vehicle damage excluded under Liability Only."], lookups)
        if (c["fraud_risk_score"] >= 0.5 or len(j["fraud_indicators"]) >= 2) and "CLS-FRD-007" in have:
            cite("CLS-FRD-007")
            why = [f"fraud score {c['fraud_risk_score']:.2f}"] + j["fraud_indicators"]
            return self._out(view, "REFER_SIU", "Fraud indicators present: " + "; ".join(why) + ".",
                             cites, why, lookups)
        if f["total_loss_candidate"] and "CLS-TL-005" in have:
            cite("CLS-TL-005"); reasons.append(f"repair/ACV = {f['total_loss_ratio']:.0%} (total-loss candidate)")
        if (c["injuries_reported"] or f["injury_doc_inconsistency"]) and "CLS-INJ-008" in have:
            cite("CLS-INJ-008")
            reasons.append("bodily injury routing" if c["injuries_reported"] else "medical report on a no-injury FNOL")
        if f["required_docs_missing"] and "CLS-DOC-009" in have:
            cite("CLS-DOC-009"); reasons.append("required documents not processed: " + ", ".join(f["required_docs_missing"]))
        if f["peril"] == "unknown":
            reasons.append("peril unclassified")
        if reasons:
            if f["liability_only"]:
                cite("CLS-LIAB-003"); reasons.append("own-vehicle damage excluded under Liability Only")
            return self._out(view, "ESCALATE_HUMAN", "Needs a specialist: " + "; ".join(reasons) + ".",
                             cites, reasons, lookups)
        cite("CLS-COLL-001" if f["peril"] == "collision" else "CLS-COMP-002", "CLS-DED-004", "CLS-PAY-012")
        return self._out(view, "RECOMMEND_APPROVE",
                         f"Covered {f['peril']} loss in period; net payable ${f['net_payable_usd']:,} after "
                         f"${f['deductible_usd']:,} deductible, pending adjuster confirmation.",
                         cites, ["covered peril", "documents complete"], lookups)

    def _out(self, view, outcome, rationale, cites, reasons, lookups):
        if lookups:   # naive: echoes other records it was told about (the leakage the guardrail must catch)
            rationale += " Related records reviewed: " + ", ".join(lookups) + "."
        out = {"proposed_outcome": outcome, "rationale": rationale, "citations": cites,
               "reasons": reasons, "requested_lookups": lookups}
        return out, _usage(view, out)


def get_brain(name: str) -> Brain:
    if name == "mock":
        return MockBrain()
    if name == "bedrock":
        from .live.sdk_agents import BedrockBrain   # lazy: needs openai-agents + litellm + AWS creds
        return BedrockBrain()
    raise ValueError(f"unknown brain {name!r} (use mock or bedrock)")
