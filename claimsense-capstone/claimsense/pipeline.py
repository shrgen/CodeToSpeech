"""The ClaimSense first-decision pipeline.

door (scope + audit) -> input quarantine -> triage (model) -> deterministic facts (code)
-> evidence (model) -> retrieval (cited clauses) -> decide (model) -> output guardrail
-> recommendation ticket (idempotent write, human confirms).

The boundary is explicit: the model interprets (peril, exclusions, fraud narrative, the
proposed outcome and its wording); code owns identity, access, dates, money, thresholds
and the final accept/reject of the model's proposal.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from typing import Any

from .brain import Brain
from .door import AccessDenied, AuditRow, ClaimsDoor
from .guardrail import CLAUSE_RE, check, redact
from .models import Outcome, Peril, Recommendation, VerdictSource
from .release import Release
from .retrieval import PolicyIndex, injection_hits, load_corpus, quarantine_documents
from .rules import compute_facts, route_for, rule_outcome, table_peril
from .trace import Tracer, cost_usd


class Pipeline:
    def __init__(self, door: ClaimsDoor, brain: Brain, release: Release,
                 tracer: Tracer | None = None, index: PolicyIndex | None = None):
        self.door, self.brain, self.release = door, brain, release
        self.tracer = tracer or Tracer()
        self.index = index or PolicyIndex(load_corpus(exclude=set(release.index_exclude)),
                                          name="thin" if release.index_exclude else "full")

    # identifiers of every OTHER record, for the leakage check
    def _foreign_tokens(self, claim_id: str) -> set[str]:
        own = self.door._claims[claim_id]
        own_pol = self.door._policies.get(own["policy_id"], {})
        own_name = f"{own_pol.get('holder_first', '')} {own_pol.get('holder_last', '')}".strip()
        toks: set[str] = set()
        for cid, row in self.door._claims.items():
            if cid != claim_id:
                toks |= {cid, row["vehicle_vin"]}
        for pid, p in self.door._policies.items():
            if pid != own["policy_id"]:
                name = f"{p['holder_first']} {p['holder_last']}"
                if name != own_name:
                    toks.add(name)
                toks.add(pid)
        return toks

    def run(self, user_id: str, claim_id: str, request_note: str = "",
            write_ticket: bool = True) -> Recommendation:
        t = self.tracer
        tid = t.new_trace()
        usage = {"input_tokens": 0, "output_tokens": 0}
        sim_ms = 0.0
        with t.span(tid, "claim.run", kind="request", claim_id=claim_id, user=user_id,
                    release=self.release.version, brain=self.brain.name, index=self.index.name) as root:
            ident = self.door.identity(user_id)
            with t.span(tid, "door.bundle", kind="tool"):
                b = self.door.bundle(ident, claim_id, request_note)

            # ── input guardrail: quarantine instruction-like text before context ──
            with t.span(tid, "guard.input", kind="guard") as g:
                quarantined_docs: list[str] = []
                if self.release.quarantine:
                    _, quarantined_docs = quarantine_documents(b.documents)
                    if injection_hits(b.request_note):
                        quarantined_docs.append("request_note")
                        b.request_note = "[quarantined: text removed by input guardrail]"
                g["quarantined"] = quarantined_docs

            view: dict[str, Any] = {
                "claim": asdict(b.claim), "policy": asdict(b.policy),
                "documents": [{"document_id": d.document_id, "type": d.document_type,
                               "ocr_status": d.ocr_status, "text": d.text} for d in b.documents],
                "request_note": b.request_note,
            }

            with t.span(tid, "agent.triage", kind="model") as s:
                tri, u = self.brain.triage(view)
                s.update(u)
            sim_ms += s.get("simulated_model_ms", 0)
            for k in usage:
                usage[k] += u.get(k, 0)

            peril = table_peril(b.claim.incident_type)
            peril_source = "table"
            if peril == Peril.UNKNOWN and tri.get("peril_guess") in ("collision", "comprehensive"):
                peril, peril_source = Peril(tri["peril_guess"]), "model"
            with t.span(tid, "rules.facts", kind="code"):
                facts = compute_facts(b, peril)

            with t.span(tid, "agent.evidence", kind="model") as s:
                ev, u = self.brain.evidence(view)
                s.update(u)
            sim_ms += s.get("simulated_model_ms", 0)
            for k in usage:
                usage[k] += u.get(k, 0)
            judgment = {"peril_guess": tri.get("peril_guess", "unknown"),
                        "exclusion_flags": list(tri.get("exclusion_flags", [])),
                        "fraud_indicators": list(ev.get("fraud_indicators", []))}

            with t.span(tid, "retrieval.search", kind="tool") as s:
                q = self._query(b, facts, judgment)
                clauses = self.index.search(q, k=self.release.top_k)
                s["retrieved"] = [c.clause_id for c in clauses]
            retrieved_ids = {c.clause_id for c in clauses}
            quarantined_ids = {c.clause_id for c in self.index.quarantined}

            view.update(facts=asdict(facts), judgment=judgment,
                        clauses=[{"clause_id": c.clause_id, "title": c.title, "text": c.text} for c in clauses])
            with t.span(tid, "agent.decide", kind="model") as s:
                try:
                    prop, u = self.brain.decide(view)
                except Exception as e:                       # model unavailable / malformed -> fallback
                    prop, u = {"proposed_outcome": None, "error": str(e)}, {}
                    s["model_error"] = str(e)
                s.update(u)
            sim_ms += s.get("simulated_model_ms", 0)
            for k in usage:
                usage[k] += u.get(k, 0)

            # the agent has no cross-claim tool; any attempt is refused and audited
            for other in prop.get("requested_lookups", []) or []:
                self.door.audit.write(AuditRow(time.time(), ident.user_id, ident.group,
                                               "claims.get(cross-claim)", other, "deny",
                                               "tool not granted: agent tools are scoped to one claim"))

            foreign = self._foreign_tokens(claim_id)
            with t.span(tid, "guard.output", kind="guard") as s:
                gr = check(prop, facts, judgment, b.claim.fraud_risk_score, b.claim.injuries_reported,
                           retrieved_ids, quarantined_ids, claim_id, foreign)
                s["violations"] = gr.violations

            if gr.ok:
                outcome = Outcome(prop["proposed_outcome"])
                rec = Recommendation(
                    claim_id=claim_id, outcome=outcome.value, verdict_source=VerdictSource.MODEL.value,
                    rationale=prop.get("rationale", ""), citations=list(prop["citations"]),
                    reasons=list(prop.get("reasons", [])),
                    net_payable_usd=facts.net_payable_usd if outcome == Outcome.APPROVE else None)
            else:
                rec = self._fallback(claim_id, facts, b, retrieved_ids, gr.violations, foreign)
                outcome = Outcome(rec.outcome)

            queue, role = route_for(outcome, facts, b.claim.injuries_reported)
            rec.route_to, rec.confirm_role = queue, role
            rec.quarantined_clauses = sorted(quarantined_ids) + quarantined_docs
            rec.release, rec.trace_id = self.release.version, tid
            rec.validate()

            if write_ticket:
                body = rec.to_dict()
                key = f"{claim_id}:{self.release.version}:" + hashlib.sha256(
                    json.dumps({k: body[k] for k in ("outcome", "citations", "rationale")},
                               sort_keys=True).encode()).hexdigest()[:16]
                with t.span(tid, "door.write_ticket", kind="tool") as s:
                    s["ticket_id"] = self.door.write_ticket(ident, claim_id, "recommendation", body, key)["ticket_id"]

            root.update(outcome=rec.outcome, verdict_source=rec.verdict_source,
                        guard_violations=len(gr.violations), peril_source=peril_source,
                        cost_usd=round(cost_usd(usage["input_tokens"], usage["output_tokens"]), 6),
                        simulated_total_model_ms=round(sim_ms, 1), **usage)
        return rec

    def _query(self, b, facts, judgment) -> str:
        parts = [b.claim.incident_type, b.claim.incident_description, facts.peril,
                 "payment authority licensed adjuster confirmation deductible"]
        if facts.liability_only:
            parts.append("Liability Only own vehicle third parties excluded")
        if not facts.in_policy_period:
            parts.append("policy period expiration lapse incident date")
        if facts.total_loss_candidate:
            parts.append("total loss actual cash value appraiser")
        if facts.required_docs_missing or facts.docs_pending:
            parts.append("documentation FNOL repair estimate OCR pending")
        if b.claim.injuries_reported or facts.injury_doc_inconsistency:
            parts.append("bodily injury medical report police report")
        if judgment["fraud_indicators"] or b.claim.fraud_risk_score >= 0.5:
            parts.append("fraud SIU investigation referral indicators")
        if judgment["exclusion_flags"]:
            parts.append("general exclusions racing livery intentional")
        return " ".join(parts)

    def _fallback(self, claim_id, facts, b, retrieved_ids, violations, foreign) -> Recommendation:
        """Deterministic decision when the model's proposal is rejected. Never approves on its own."""
        outcome, reasons = rule_outcome(facts, b.claim.fraud_risk_score, b.claim.injuries_reported)
        needed = sorted({c for r in reasons for c in CLAUSE_RE.findall(r)})
        cites = [c for c in needed if c in retrieved_ids]
        if outcome == Outcome.APPROVE:
            outcome = Outcome.ESCALATE
            reasons = ["Model proposal rejected by guardrail; approval requires a human review."] + reasons
        if needed and not cites:
            outcome = Outcome.ESCALATE
            reasons = [f"Policy support {needed} not found in retrieval — route to a human."] + reasons
        if not cites:
            backup = [c.clause_id for c in self.index.search("payment authority licensed adjuster", k=1)]
            cites = backup
        reasons = [redact(r, foreign) for r in reasons]
        return Recommendation(
            claim_id=claim_id, outcome=outcome.value,
            verdict_source=VerdictSource.DETERMINISTIC_FALLBACK.value,
            rationale="Deterministic fallback: " + " ".join(reasons),
            citations=cites, reasons=reasons + [redact(f"guardrail: {v}", foreign) for v in violations[:5]],
            net_payable_usd=None)
