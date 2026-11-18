# Incident report — staged retrieval regression (incident drill)

**Status:** drill, not a production incident · **Run:** `runs/drill/` (started
2026-11-18T02:30:02.895Z, mock brain, 100 requests paced at 0.25 s) · **Generated RCA:**
`runs/drill/RCA.md`. Facts are copied from that run. Items marked **[owner]** are judgment
calls for the engagement owner to complete or confirm.

## What happened
At request #30, release `v1.1.0` was promoted with the eval gate skipped. Its retrieval index
silently dropped two clauses: CLS-LIAB-003 (Liability Only scope) and CLS-PER-006 (policy
period). Claims that should be denied for a lapsed policy or Liability-Only cover could no
longer cite their denial grounds.

## Timeline (UTC)
| Time | Request | Event |
|---|---|---|
| 02:30:10.225 | #30 | `v1.1.0` promoted, gate skipped |
| 02:30:13.776 | #44 | **Detected**: rolling pass rate (last 20) fell to 90%, below the 95% SLO. Evidence trace `trc-d643918688b1` |
| 02:30:14.028 | #45 | Rolled back to `v1.0.0` (`release rollback`) |
| 02:30:14.180 | #45 | **Verified recovery**: smoke 10/10 and golden 150/150 gates passed on `v1.0.0` |

## Numbers
| | |
|---|---|
| Time to detect | **3.551 s**, 14 requests after the push |
| Time to verified recovery (detection → both gates green) | **0.404 s** |
| Requests served by the bad release | 15 |
| Of those, failed the eval check | 2 (both escalated to a human instead of denied) |
| Unsafe approvals that reached a ticket | **0** |
| What the skipped gate would have said about `v1.1.0` | 118/150 (78.7%), 9 adversarial failures → **FAIL** (`runs/eval_golden_mock_v1.1.0.json`) |

The recovery time is in-process on the mock brain, so it is mostly the 0.25 s request pacing
plus 0.16 s of gate runs. On AWS, add the Lambda redeploy (`deploy/deploy_api.sh`) and the
5-minute alarm window. **[owner]: measure this on a live deployment before quoting it to the client.**

## Root cause
The index config of `v1.1.0` excluded two clauses. The decide step cannot cite a clause it was
not given, so the output guardrail rejected its proposals, and the deterministic fallback —
unable to cite the clause it needed — routed the claims to a human (ESCALATE) rather than
deny them. First failure: request #43, `VAR-liability_only-07`.

## What held
- The failure was **loud and safe**: wrong routing to a human, never a wrong approval. Across
  all 150 golden cases on `v1.1.0`, all 32 failures were DENY → ESCALATE; 0 approvals,
  0 forbidden strings.
- Every recommendation still required human confirmation (CLS-PAY-012).
- The gate, had it run, would have blocked the release.

## Action items
- [x] Regression case `REG-20261118-VAR-liability_only-07` added to `evals/regression_set.json`;
      CI runs it on every push (min pass 100%).
- [ ] **[owner]** Decide whether `--skip-gate` should be removed or require a second approver.
- [ ] **[owner]** Decide whether index changes need their own review step.
