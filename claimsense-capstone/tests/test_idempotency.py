import pytest

from claimsense.door import ClaimsDoor
from claimsense.models import ContractError


def test_same_key_returns_the_original_ticket():
    door = ClaimsDoor()
    bob = door.identity("bob")
    first = door.write_ticket(bob, "CLM-2024-1800", "recommendation", {"outcome": "X"}, "k1")
    again = door.write_ticket(bob, "CLM-2024-1800", "recommendation", {"outcome": "X"}, "k1")
    assert again["ticket_id"] == first["ticket_id"] and again["idempotent_replay"]
    assert len(door._tickets) == 1


def test_writes_require_a_key():
    door = ClaimsDoor()
    with pytest.raises(ContractError):
        door.write_ticket(door.identity("bob"), "CLM-2024-1800", "recommendation", {}, "")


def test_ticket_log_keeps_idempotency_across_processes(tmp_path):
    log = tmp_path / "tickets.jsonl"
    d1 = ClaimsDoor(ticket_log=log)
    t1 = d1.escalate(d1.identity("bob"), "CLM-2024-1873", "siu", "fraud score 0.87", "esc-1")
    d2 = ClaimsDoor(ticket_log=log)                     # a fresh process
    t2 = d2.escalate(d2.identity("bob"), "CLM-2024-1873", "siu", "fraud score 0.87", "esc-1")
    assert t2["ticket_id"] == t1["ticket_id"] and t2["idempotent_replay"]
    t3 = d2.escalate(d2.identity("bob"), "CLM-2024-2603", "siu", "fraud score 0.78", "esc-2")
    assert t3["ticket_id"] != t1["ticket_id"]


def test_escalation_validation():
    door = ClaimsDoor()
    bob = door.identity("bob")
    with pytest.raises(ContractError):
        door.escalate(bob, "CLM-2024-1873", "adjuster", "x", "k")
    with pytest.raises(ContractError):
        door.escalate(bob, "CLM-2024-1873", "siu", "   ", "k")
