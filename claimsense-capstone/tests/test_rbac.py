import json
from pathlib import Path

import pytest

from claimsense.door import AccessDenied, ClaimsDoor

ORACLE = json.loads((Path(__file__).parent / "portal_access_oracle.json").read_text())


def test_door_matches_portal_access_table_exactly():
    door = ClaimsDoor()
    mismatches = [(cid, u) for cid, row in ORACLE.items() for u, expected in row.items()
                  if door.can_read(door.identity(u), door._claims[cid])[0] != expected]
    assert mismatches == []
    assert len(ORACLE) == 20 and all(len(r) == 5 for r in ORACLE.values())


def test_denial_raises_and_is_audited_before_anything_is_returned():
    door = ClaimsDoor()
    with pytest.raises(AccessDenied) as e:
        door.get_claim(door.identity("alice"), "CLM-2024-2019")
    assert e.value.code == "forbidden_scope"
    row = door.audit.rows[-1]
    assert (row.acting_user, row.resource, row.decision) == ("alice", "CLM-2024-2019", "deny")


def test_policy_and_documents_only_reachable_through_an_authorized_claim():
    door = ClaimsDoor()
    for tool in (door.get_policy_for_claim, door.list_documents):
        with pytest.raises(AccessDenied):
            tool(door.identity("david"), "CLM-2024-1800")


def test_unknown_user_has_no_seat():
    with pytest.raises(AccessDenied):
        ClaimsDoor().identity("mallory")


def test_same_question_two_identities_different_answers():
    door = ClaimsDoor()
    assert door.get_claim(door.identity("alice"), "CLM-2024-1800").claim_id == "CLM-2024-1800"
    with pytest.raises(AccessDenied):
        door.get_claim(door.identity("david"), "CLM-2024-1800")
    assert [r.decision for r in door.audit.rows[-2:]] == ["allow", "deny"]
