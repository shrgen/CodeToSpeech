from claimsense.door import ClaimsDoor
from claimsense.models import Outcome, Peril
from claimsense.rules import compute_facts, in_policy_period, route_for, rule_outcome, table_peril


def facts_for(cid, user="bob"):
    door = ClaimsDoor()
    b = door.bundle(door.identity(user), cid)
    return b, compute_facts(b, table_peril(b.claim.incident_type))


def test_policy_period_is_inclusive_and_ignores_status():
    assert in_policy_period("2024-04-25", "2023-04-25", "2024-04-25")
    assert not in_policy_period("2024-04-26", "2023-04-25", "2024-04-25")
    b, f = facts_for("CLM-2024-2822")                    # status "Active" but lapsed
    assert b.policy.policy_status == "Active" and not f.in_policy_period


def test_money_is_computed_in_code():
    _, f = facts_for("CLM-2024-1800")                    # estimate 3,200, ACV 24,500, deductible 500
    assert (f.gross_loss_usd, f.deductible_usd, f.net_payable_usd) == (3200, 500, 2700)


def test_total_loss_threshold():
    _, f = facts_for("CLM-2024-3187")                    # 38,500 / 42,000 = 0.917
    assert f.total_loss_candidate and f.total_loss_ratio >= 0.75


def test_unknown_incident_type_is_unknown_peril():
    assert table_peril("Falling debris") == Peril.UNKNOWN
    assert table_peril("Hail damage") == Peril.COMPREHENSIVE


def test_precedence_deny_beats_siu_beats_escalate():
    b, f = facts_for("CLM-2024-1873")
    assert rule_outcome(f, 0.87, False)[0] == Outcome.REFER_SIU
    b, f = facts_for("CLM-2024-2822")
    assert rule_outcome(f, 0.99, True)[0] == Outcome.DENY  # lapse wins over fraud and injury


def test_high_value_approval_needs_senior_confirmation():
    b, f = facts_for("CLM-2024-1800")
    f.high_value = True
    assert route_for(Outcome.APPROVE, f, False) == ("adjuster", "senior-adjuster")
