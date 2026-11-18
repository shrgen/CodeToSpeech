"""Typed contracts for ClaimSense.

Everything that crosses a boundary (door -> agents, agents -> guardrail, pipeline -> UI)
is one of these dataclasses. `validate()` methods fail closed: a malformed object raises
ContractError instead of flowing downstream.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ContractError(ValueError):
    """A value violated a typed contract. Never caught silently."""


class Outcome(str, Enum):
    """The four first-decision outcomes. Every one is a RECOMMENDATION (CLS-PAY-012)."""

    APPROVE = "RECOMMEND_APPROVE"      # covered, clean file: adjuster confirms payment
    DENY = "RECOMMEND_DENY"            # not covered (lapse, Liability Only own-vehicle, exclusion)
    REFER_SIU = "REFER_SIU"            # fraud indicators: Special Investigation Unit first
    ESCALATE = "ESCALATE_HUMAN"        # needs a specialist / missing evidence / high value


class VerdictSource(str, Enum):
    MODEL = "model"                    # outcome chosen by model judgment (live or mock brain)
    DETERMINISTIC_FALLBACK = "deterministic_fallback"  # model unavailable / output rejected


class Peril(str, Enum):
    COLLISION = "collision"
    COMPREHENSIVE = "comprehensive"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Identity:
    """Who the agent is acting as (the on-behalf-of identity). Never 'the bot'."""

    user_id: str
    group: str


@dataclass
class Claim:
    claim_id: str
    policy_id: str
    vehicle_vin: str
    vehicle_year: str
    vehicle_make: str
    vehicle_model: str
    vehicle_acv_usd: int
    incident_date: str
    incident_type: str
    incident_description: str
    damage_description: str
    repair_estimate_usd: int
    injuries_reported: bool
    police_report_filed: bool
    assigned_adjuster: str
    prior_claims_12mo: int
    fraud_risk_score: float
    claim_status: str
    created_at: str

    @classmethod
    def from_row(cls, r: dict[str, Any]) -> "Claim":
        try:
            return cls(
                claim_id=str(r["claim_id"]), policy_id=str(r["policy_id"]),
                vehicle_vin=str(r["vehicle_vin"]), vehicle_year=str(r["vehicle_year"]),
                vehicle_make=str(r["vehicle_make"]), vehicle_model=str(r["vehicle_model"]),
                vehicle_acv_usd=int(r["vehicle_acv_usd"]), incident_date=str(r["incident_date"]),
                incident_type=str(r["incident_type"]),
                incident_description=str(r["incident_description"]),
                damage_description=str(r["damage_description"]),
                repair_estimate_usd=int(r["repair_estimate_usd"]),
                injuries_reported=_yes(r["injuries_reported"]),
                police_report_filed=_yes(r["police_report_filed"]),
                assigned_adjuster=str(r["assigned_adjuster"]),
                prior_claims_12mo=int(r["prior_claims_12mo"]),
                fraud_risk_score=float(r["fraud_risk_score"]),
                claim_status=str(r["claim_status"]), created_at=str(r["created_at"]),
            )
        except (KeyError, ValueError, TypeError) as e:
            raise ContractError(f"claim row invalid: {e}") from e


@dataclass
class Policy:
    policy_id: str
    holder_first: str
    holder_last: str
    vehicle_vin: str
    coverage_type: str               # "Full Coverage" | "Liability Only"
    collision_coverage: bool
    comprehensive_coverage: bool
    collision_deductible_usd: int
    comprehensive_deductible_usd: int
    policy_status: str               # administrative only — never controls coverage (CLS-PER-006)
    policy_start: str
    policy_end: str

    @classmethod
    def from_row(cls, r: dict[str, Any]) -> "Policy":
        try:
            return cls(
                policy_id=r["policy_id"], holder_first=r["holder_first"], holder_last=r["holder_last"],
                vehicle_vin=r["vehicle_vin"], coverage_type=r["coverage_type"],
                collision_coverage=_yes(r["collision_coverage"]),
                comprehensive_coverage=_yes(r["comprehensive_coverage"]),
                collision_deductible_usd=_money(r["collision_deductible_usd"]),
                comprehensive_deductible_usd=_money(r["comprehensive_deductible_usd"]),
                policy_status=r["policy_status"], policy_start=r["policy_start"], policy_end=r["policy_end"],
            )
        except (KeyError, ValueError, TypeError) as e:
            raise ContractError(f"policy row invalid: {e}") from e


@dataclass
class Document:
    document_id: str
    claim_id: str
    document_type: str
    description: str
    upload_date: str
    page_count: int
    ocr_status: str
    uploaded_by: str
    text: str = ""                   # OCR text; untrusted input (may carry injected instructions)

    @classmethod
    def from_row(cls, r: dict[str, Any]) -> "Document":
        try:
            return cls(
                document_id=r["document_id"], claim_id=r["claim_id"], document_type=r["document_type"],
                description=r["description"], upload_date=r["upload_date"],
                page_count=int(r["page_count"]), ocr_status=r["ocr_status"],
                uploaded_by=r["uploaded_by"], text=r.get("text", ""),
            )
        except (KeyError, ValueError, TypeError) as e:
            raise ContractError(f"document row invalid: {e}") from e


@dataclass
class ClaimBundle:
    """Everything the agents may see about ONE claim, fetched through the door."""

    claim: Claim
    policy: Policy
    documents: list[Document]
    request_note: str = ""           # free text from the requester; untrusted


@dataclass
class Clause:
    clause_id: str
    title: str
    text: str
    quarantined: bool = False
    quarantine_reason: str = ""


@dataclass
class Facts:
    """Deterministic facts computed in code. The model never computes these."""

    in_policy_period: bool
    peril: str
    peril_covered: bool
    liability_only: bool
    deductible_usd: int
    gross_loss_usd: int
    net_payable_usd: int
    total_loss_ratio: float
    total_loss_candidate: bool
    docs_pending: list[str]
    required_docs_missing: list[str]
    injury_doc_inconsistency: bool
    high_value: bool


@dataclass
class Judgment:
    """Model judgment over the bundle (interpretation, not arithmetic)."""

    peril_guess: str
    fraud_indicators: list[str]
    exclusion_flags: list[str]
    rationale: str
    source: str = VerdictSource.MODEL.value


@dataclass
class Recommendation:
    claim_id: str
    outcome: str
    verdict_source: str
    rationale: str
    citations: list[str]
    reasons: list[str]
    net_payable_usd: int | None
    requires_human_confirmation: bool = True
    confirm_role: str = "adjuster"
    route_to: str = ""
    quarantined_clauses: list[str] = field(default_factory=list)
    release: str = ""
    trace_id: str = ""

    def validate(self) -> "Recommendation":
        if self.outcome not in {o.value for o in Outcome}:
            raise ContractError(f"unknown outcome {self.outcome!r}")
        if self.verdict_source not in {v.value for v in VerdictSource}:
            raise ContractError(f"unknown verdict_source {self.verdict_source!r}")
        if not self.requires_human_confirmation:
            raise ContractError("every recommendation requires human confirmation (CLS-PAY-012)")
        if not self.citations:
            raise ContractError("a recommendation must cite at least one retrieved clause")
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _yes(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"yes", "y", "true", "1"}


def _money(v: Any) -> int:
    """Deductible fields: 'N/A' (no such coverage) -> 0; anything else must be an integer."""
    if v is None or str(v).strip().upper() in {"", "N/A", "NA"}:
        return 0
    return int(str(v).replace("$", "").replace(",", ""))
