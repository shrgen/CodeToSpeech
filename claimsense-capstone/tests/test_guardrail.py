from claimsense.door import ClaimsDoor
from claimsense.guardrail import check, redact
from claimsense.rules import compute_facts, table_peril


def setup():
    door = ClaimsDoor()
    b = door.bundle(door.identity("alice"), "CLM-2024-1800")
    f = compute_facts(b, table_peril(b.claim.incident_type))
    judgment = {"exclusion_flags": [], "fraud_indicators": []}
    retrieved = {"CLS-COLL-001", "CLS-DED-004", "CLS-PAY-012"}
    return f, judgment, retrieved


def run(prop, quarantined=frozenset(), foreign=frozenset({"CLM-2024-2019", "Maria Lopez"})):
    f, j, r = setup()
    return check(prop, f, j, 0.05, False, r, set(quarantined), "CLM-2024-1800", set(foreign))


GOOD = {"proposed_outcome": "RECOMMEND_APPROVE", "citations": ["CLS-COLL-001", "CLS-DED-004"],
        "rationale": "Covered collision; net payable $2,700 after $500 deductible, pending adjuster confirmation.",
        "reasons": []}


def test_good_proposal_passes():
    assert run(GOOD).ok


def test_invented_money_is_rejected():
    assert not run(dict(GOOD, rationale="Pay $3,100 now.")).ok


def test_uncited_or_unretrieved_or_quarantined_citations_are_rejected():
    assert not run(dict(GOOD, citations=[])).ok
    assert not run(dict(GOOD, citations=["CLS-TL-005"])).ok
    assert not run(GOOD, quarantined={"CLS-COLL-001"}).ok


def test_payment_authority_language_is_rejected():
    assert not run(dict(GOOD, rationale="Payment has been issued.")).ok
    assert not run(dict(GOOD, reasons=["No adjuster review needed."])).ok


def test_cross_record_leakage_is_rejected_and_redacted():
    r = run(dict(GOOD, rationale=GOOD["rationale"] + " Compare CLM-2024-2019."))
    assert not r.ok and any("leakage" in v for v in r.violations)
    assert "CLM-2024-2019" not in redact("see CLM-2024-2019 and maria lopez", {"CLM-2024-2019", "Maria Lopez"})


def test_unknown_outcome_fails_closed():
    assert not run(dict(GOOD, proposed_outcome="PAY_NOW")).ok
