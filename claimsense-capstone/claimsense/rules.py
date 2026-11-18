"""Deterministic layer: dates, money, thresholds, document readiness.

These are computed in code, never by the model (W14 boundary: identity, access control,
dates and monetary calculations stay deterministic). Each function cites the clause it
implements.
"""
from __future__ import annotations

from datetime import date

from .models import ClaimBundle, Facts, Outcome, Peril

# Incident types the client already uses -> peril. Unknown types fall to model judgment.
PERIL_TABLE: dict[str, Peril] = {
    # CLS-COLL-001 (collision or upset; CLS-COMP-002: pothole impact is collision)
    "parking lot collision": Peril.COLLISION, "single-vehicle accident": Peril.COLLISION,
    "t-bone collision": Peril.COLLISION, "rear-end on highway": Peril.COLLISION,
    "hit and run": Peril.COLLISION, "rollover": Peril.COLLISION,
    "backing accident": Peril.COLLISION, "multi-vehicle pileup": Peril.COLLISION,
    "side-swipe": Peril.COLLISION, "pothole damage": Peril.COLLISION,
    "low-speed collision": Peril.COLLISION, "underride accident": Peril.COLLISION,
    # CLS-COMP-002 (other-than-collision)
    "hail damage": Peril.COMPREHENSIVE, "animal strike": Peril.COMPREHENSIVE,
    "flood damage": Peril.COMPREHENSIVE, "vandalism": Peril.COMPREHENSIVE,
    "theft recovery": Peril.COMPREHENSIVE, "storm damage": Peril.COMPREHENSIVE,
    "carjacking": Peril.COMPREHENSIVE, "garage fire": Peril.COMPREHENSIVE,
}

TOTAL_LOSS_RATIO = 0.75            # CLS-TL-005
SENIOR_CONFIRM_USD = 25_000        # CLS-PAY-012
FRAUD_SCORE_SIU = 0.50             # client's model score at/above which SIU referral is required
PROOF_OF_LOSS = {"DAMAGE_PHOTOS", "POLICE_REPORT", "WITNESS_STATEMENT"}


def table_peril(incident_type: str) -> Peril:
    return PERIL_TABLE.get(incident_type.strip().lower(), Peril.UNKNOWN)


def in_policy_period(incident: str, start: str, end: str) -> bool:
    """CLS-PER-006: effective through expiration inclusive. Status field is ignored on purpose."""
    d, s, e = date.fromisoformat(incident), date.fromisoformat(start), date.fromisoformat(end)
    return s <= d <= e


def compute_facts(b: ClaimBundle, peril: Peril) -> Facts:
    c, p = b.claim, b.policy
    liability_only = p.coverage_type.strip().lower() == "liability only"
    if peril == Peril.COLLISION:
        covered, ded = (p.collision_coverage and not liability_only), p.collision_deductible_usd
    elif peril == Peril.COMPREHENSIVE:
        covered, ded = (p.comprehensive_coverage and not liability_only), p.comprehensive_deductible_usd
    else:
        covered, ded = False, 0
    gross = min(c.repair_estimate_usd, c.vehicle_acv_usd)                     # CLS-COLL-001
    net = max(gross - ded, 0) if covered else 0                               # CLS-DED-004
    ratio = round(c.repair_estimate_usd / max(c.vehicle_acv_usd, 1), 4)

    by_type: dict[str, list[str]] = {}
    for d in b.documents:
        by_type.setdefault(d.document_type, []).append(d.ocr_status)
    pending = sorted(t for t, sts in by_type.items() if any(s != "Completed" for s in sts))
    completed = {t for t, sts in by_type.items() if "Completed" in sts}
    missing = []                                                              # CLS-DOC-009
    if "FNOL_FORM" not in completed:
        missing.append("FNOL_FORM")
    if "REPAIR_ESTIMATE" not in completed:
        missing.append("REPAIR_ESTIMATE")
    if not (completed & PROOF_OF_LOSS):
        missing.append("PROOF_OF_LOSS")
    inconsistency = ("MEDICAL_REPORT" in by_type) and not c.injuries_reported  # CLS-INJ-008

    return Facts(
        in_policy_period=in_policy_period(c.incident_date, p.policy_start, p.policy_end),
        peril=peril.value, peril_covered=covered, liability_only=liability_only,
        deductible_usd=ded if covered else 0, gross_loss_usd=gross, net_payable_usd=net,
        total_loss_ratio=ratio, total_loss_candidate=ratio >= TOTAL_LOSS_RATIO,
        docs_pending=pending, required_docs_missing=missing,
        injury_doc_inconsistency=inconsistency, high_value=net > SENIOR_CONFIRM_USD,
    )


def hard_constraints(f: Facts, fraud_score: float, injuries: bool,
                     exclusion_flags: list[str] | None = None) -> dict[str, set[str]]:
    """Outcomes the facts FORBID. A model proposal in a forbidden set is rejected."""
    forbid: dict[str, set[str]] = {o.value: set() for o in Outcome}
    approve = forbid[Outcome.APPROVE.value]
    if not f.in_policy_period:
        approve.add("incident outside policy period (CLS-PER-006)")
    if not f.peril_covered:
        approve.add("peril not covered by this policy (CLS-LIAB-003 / CLS-COLL-001 / CLS-COMP-002)")
    if f.total_loss_candidate:
        approve.add("total-loss candidate needs appraiser (CLS-TL-005)")
    if f.required_docs_missing:
        approve.add(f"required documents not processed: {f.required_docs_missing} (CLS-DOC-009)")
    if f.injury_doc_inconsistency:
        approve.add("medical report on a no-injury FNOL (CLS-INJ-008)")
    if injuries:
        approve.add("bodily injury routes to an injury-qualified adjuster (CLS-INJ-008)")
    if fraud_score >= FRAUD_SCORE_SIU:
        approve.add(f"fraud score {fraud_score:.2f} >= {FRAUD_SCORE_SIU} requires SIU (CLS-FRD-007)")
        forbid[Outcome.ESCALATE.value].add("fraud score requires SIU referral, not general escalation")
    if f.in_policy_period and not (f.liability_only and not injuries) and not exclusion_flags:
        # a DENY needs a coverage reason: lapse, Liability-Only own-vehicle, or an exclusion finding
        forbid[Outcome.DENY.value].add("no coverage bar found; a denial needs lapse, Liability Only, or an exclusion")
    if not f.in_policy_period or exclusion_flags or (f.liability_only and not injuries):
        forbid[Outcome.REFER_SIU.value].add("coverage is barred; deny rather than refer")
        forbid[Outcome.ESCALATE.value].add("coverage is barred; deny rather than escalate")
    return forbid


def rule_outcome(f: Facts, fraud_score: float, injuries: bool,
                 exclusion_flags: list[str] | None = None) -> tuple[Outcome, list[str]]:
    """The deterministic fallback decision (no model). Precedence: deny > SIU > escalate > approve."""
    if not f.in_policy_period:
        return Outcome.DENY, ["Loss occurred outside the policy period (CLS-PER-006)."]
    if exclusion_flags:
        return Outcome.DENY, [f"General exclusion applies: {', '.join(exclusion_flags)} (CLS-EXC-010)."]
    if f.liability_only and not injuries:
        return Outcome.DENY, ["Liability Only policy excludes damage to the insured's own vehicle (CLS-LIAB-003)."]
    if fraud_score >= FRAUD_SCORE_SIU:
        return Outcome.REFER_SIU, [f"Fraud risk score {fraud_score:.2f} meets the SIU referral bar (CLS-FRD-007)."]
    reasons = escalation_reasons(f, injuries)
    if reasons:
        return Outcome.ESCALATE, reasons
    return Outcome.APPROVE, ["Covered peril within the policy period; documents complete (CLS-COLL-001/CLS-COMP-002, CLS-DOC-009)."]


def escalation_reasons(f: Facts, injuries: bool) -> list[str]:
    r = []
    if f.total_loss_candidate:
        r.append(f"Repair estimate is {f.total_loss_ratio:.0%} of ACV — total-loss appraiser referral (CLS-TL-005).")
    if injuries:
        r.append("Bodily injury reported — route to an injury-qualified adjuster (CLS-INJ-008).")
    if f.injury_doc_inconsistency:
        r.append("Medical report present on a claim whose FNOL reports no injuries (CLS-INJ-008).")
    if f.required_docs_missing:
        r.append(f"Required documents not yet processed: {', '.join(f.required_docs_missing)} (CLS-DOC-009).")
    if f.peril == Peril.UNKNOWN.value:
        r.append("Peril could not be classified — adjuster to classify.")
    return r


def route_for(outcome: Outcome, f: Facts, injuries: bool) -> tuple[str, str]:
    """(queue, confirming role). Every outcome is confirmed by a licensed human."""
    if outcome == Outcome.REFER_SIU:
        return "siu", "fraud-investigator"
    if outcome == Outcome.ESCALATE:
        if f.total_loss_candidate:
            return "total-loss", "total-loss-appraiser"
        return "senior-review", "senior-adjuster"
    if outcome == Outcome.APPROVE and f.high_value:
        return "adjuster", "senior-adjuster"                                 # CLS-PAY-012
    return "adjuster", "adjuster"
