# DECISIONS.md — Week 5 build decisions (DRAFT)

> **DRAFT for the engagement owner to review, edit and own.** These record decisions taken while
> building the Week 5 deliverables on 2026-11-18. They are not the owner's earlier W1–W2
> decisions; those live in the owner's own DECISIONS.md (linked from `docs/HANDOVER.md`).
> Merge, reword or reject each entry before submission.

## D-W5-1 · 2026-11-18 · The mock brain is the CI gate; live runs are separate
- **Decision:** CI and the image build always run the golden gate on the deterministic mock
  brain ($0, reproducible). Live Bedrock runs (`make eval-live`) are evidence, not the gate.
- **Why:** a gate that costs money or varies between runs gets skipped or argued with.
- **Trade-off:** the mock does not exercise 4 adversarial cases (see `docs/OBSERVATION.md` §1.3);
  only a live run tests those.

## D-W5-2 · 2026-11-18 · The deterministic fallback never approves on its own
- **Decision:** when the model's output is rejected, the rules decide, but an APPROVE becomes
  ESCALATE_HUMAN.
- **Why:** failures should be loud and safe. The drill confirmed it: a broken index produced
  escalations, 0 unsafe approvals.

## D-W5-3 · 2026-11-18 · Adversarial cases pass only with the expected outcome
- **Decision:** an adversarial case fails on a wrong outcome, not only on a leak or an
  approval. For an approvable claim under attack, ESCALATE is also accepted.
- **Why:** wrong routing is still wrong. **Consequence:** the zero-tolerance veto also fires on
  safe regressions (9 on `v1.1.0`). Owner to confirm this is the intended bar.

## D-W5-4 · 2026-11-18 · A 403 refusal is not an error
- **Decision:** the error rate (alarm metric) counts requests that raised or fell back; a scope
  refusal is excluded, in both the traces and the EMF metric.
- **Why:** a refusal is the door working; counting it would page on-call for correct behaviour.

## D-W5-5 · 2026-11-18 · Detect on rolling pass rate; alarm on error rate
- **Decision:** the drill detects on the rolling eval pass rate (20 requests, 95% SLO); the
  single CloudWatch alarm is error rate > 5% over 5 minutes.
- **Why:** the course requires one alarm on error rate; pass rate detected the drill
  regression faster. Eval traffic must not feed the production alarm.

## D-W5-6 · 2026-11-18 · Lambda for the demo API; AgentCore as the managed option
- **Decision:** the demo deploys as Lambda + HTTP API with reserved concurrency 5; the
  AgentCore entrypoint is provided but optional.
- **Why:** lowest cost and simplest teardown for test workloads.
