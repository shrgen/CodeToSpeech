# Observation document — ClaimSense (Checkpoint 2)

What was observed while proving ClaimSense works: evals, observability, reliability and
handover. Every number below comes from a run committed under `runs/` (file named next to it).
All runs so far use the **mock brain** (deterministic, $0). **Live Bedrock (Claude Haiku 4.5)
numbers are not in this document yet** — they will be added only after a live run
(`make eval-live`), as section 6.

Run date: 2026-11-18. Release under test: `v1.0.0` (full 12-clause index, quarantine on).

## 1. Evals

**Result:** the golden gate passes: **150/150 (100%), 0 adversarial failures**
(`runs/eval_golden_mock_v1.0.0.json`).

| Family | Cases | Passed | What it covers |
|---|---|---|---|
| Base | 20 | 20 | the portal's real claims with the planning-session hand labels |
| Variant | 100 | 100 | a base claim normalised to clean + exactly one trigger (12 trigger types) |
| Adversarial | 30 | 30 | 10 prompt injection, 10 cross-record leakage, 10 forced auto-decision |

The **second grader agrees**: promptfoo replayed all 150 cases through the pipeline,
150/150 (`runs/promptfoo_golden_agreement.json`). The rubric grader (`evals/promptfoo.yaml`,
2 standard + 4 adversarial bundles built from the real seed data) validates but has not been
run, because it needs a live model (Ollama or Bedrock).

What I observed about the evals themselves:

1. **The gate can fail, and fails for the right reasons.** On the drill release `v1.1.0` the
   gate drops to 118/150 (78.7%) and FAILS (`runs/eval_golden_mock_v1.1.0.json`). Without that
   check, a 100% pass rate would prove nothing.
2. **The adversarial veto also fires on safe-but-wrong regressions.** All 32 `v1.1.0` failures
   are DENY → ESCALATE (a human sees the claim instead of a denial). None is an approval or a
   leak, yet 9 adversarial cases fail because their pass condition includes the expected
   outcome. That is a deliberate choice (wrong routing is still wrong), but it means "an
   adversarial failure" does not always mean "an attack worked". Reading the failure reason
   matters.
3. **Which guard actually carries the defence** (`runs/ablation.json`):

   | Configuration | Golden | Adversarial | Gate |
   |---|---|---|---|
   | Quarantine + output guardrail (shipped) | 150/150 | 30/30 | PASSED |
   | Output guardrail only (quarantine off) | 150/150 | 30/30 | PASSED |
   | Neither | 127/150 | 7/30 | FAILED |

   Against the mock, the **output guardrail alone** stops every attack; input quarantine is
   defence in depth (it matters more for a live model, which may be steered in ways the
   guardrail's string checks do not see). With both off, 7 adversarial cases still pass:
   3 are out-of-scope reads that the **door** refuses in code (correct — access control does
   not depend on the guards), and 4 (`ADV-inject-doc-03`, `ADV-inject-corpus-01/02/03`) use
   wording the deliberately naive mock does not act on. **Those 4 only test something against a
   live model.** They stay in the suite for the live run.
4. **Verdict source is visible and checked.** On `v1.0.0`, 131 verdicts came from the model,
   16 from the deterministic fallback (all adversarial cases where the guardrail rejected the
   model's proposal), and 3 were 403 refusals. Base and variant cases are required to be model
   verdicts, so the gate passes "with the model required", not by falling back to rules.

## 2. Observability

Dashboard: `ops/dashboard.html` (from `runs/traces/golden_mock_v1.0.0.jsonl`); the same
three metrics are defined for AWS in `ops/cloudwatch/observability.yaml`, fed by one EMF line
per request from `claimsense/service.py`.

| Metric | Golden run | Note |
|---|---|---|
| Call volume | 150 | one trace per claim run, one span per pipeline step |
| Error rate | 10.7% (16/150) | all 16 are adversarial cases where the guardrail rejected the model — correct behaviour |
| p50 / p95 latency | 2,078 / 3,357 ms | **includes a labelled simulation** of hosted-model time (lognormal, median ~700 ms per call); the mock itself answers in microseconds |
| Cost per resolution | $0.0033 | estimated from prompt size at $1 / $5 per million tokens; not a measured bill |

Observations:

1. **The error-rate alarm must not watch eval traffic.** Adversarial traffic is *designed* to
   be rejected, so a golden run trips the 5% alarm. The incident drill therefore uses base and
   variant traffic only, where the baseline error rate is 0%.
2. **The definition of "error" needed one fix.** At first, 403 scope refusals counted as
   errors in the trace summary but not in the service's EMF metric. A refusal is the door
   working, so both now exclude it (`claimsense/trace.py: is_error`).
3. **Latency numbers from the mock are not evidence.** They show the dashboard works; real
   latency comes only from a live run.

## 3. Reliability — incident drill

Run: `runs/drill/` (RCA in `runs/drill/RCA.md`, report in `docs/INCIDENT_REPORT.md`).

- Bad release `v1.1.0` (index without CLS-LIAB-003 and CLS-PER-006) pushed at request #30
  with the gate skipped.
- **Detected after 14 requests (3.551 s)** by the rolling pass rate falling to 90% (< 95% SLO).
- Rolled back with one command; **verified recovery in 0.404 s** (smoke 10/10 + golden 150/150).
- Blast radius: 15 requests on the bad release, 2 failed — both escalated to a human; **0
  unsafe approvals**.
- A regression case was spawned into `evals/regression_set.json` and runs in CI.

Observations:

1. **The pass-rate SLO caught it before the error-rate alarm would have.** Over a 20-request
   window, 2 failures move the pass rate to 90% immediately; the error rate also reached 10%,
   but the CloudWatch alarm is evaluated over 5 minutes, so in production the pass-rate signal
   (continuous eval on traffic) is the faster detector.
2. **The first version of the drill measured recovery wrongly.** It verified recovery only after the remaining
   traffic finished, which reported 14.6 s of mostly waiting. Verification now runs
   immediately at rollback. The 0.404 s is in-process; a live redeploy will add time.
3. **Fail-safe design held.** A missing clause made the system less useful (more escalations),
   not more dangerous. That came from three design choices: the fallback never approves on its
   own, a decision needs a citation, and every recommendation needs human confirmation.

## 4. Correctness checks beyond the gate

- 49 unit tests pass (`make test`), including the door against the portal's own access table
  (100 user × claim cells, 0 mismatches), idempotent tickets across processes, and the
  guardrail's money, citation, authority and leakage checks.
- The 20 hand labels match the pipeline on the real portal data.

## 5. Handover

- Runbook with the four procedures: `docs/RUNBOOK.md`.
- Everything is runnable without the builder: `make verify`, `make golden`, `make drill`,
  `make up`. CI re-runs the gate on every push and blocks the image push when it fails.
- Index of all artefacts: `docs/HANDOVER.md`.

## 6. Live model (Claude Haiku 4.5 on Bedrock) — pending

To be filled from a live run only: golden pass rate with `--brain bedrock`, adversarial
results (especially the 4 cases the mock cannot exercise), measured latency p50/p95, measured
token cost per resolution, and the promptfoo rubric results.
