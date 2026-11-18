# ClaimSense runbook

For the on-call engineer and the claims-ops admin at AutoSure. Every command runs from the
`claimsense-capstone/` directory. All commands work offline on the mock brain; add
`--brain bedrock` (with AWS credentials) only where noted.

| When | Go to |
|---|---|
| The error-rate alarm fired, or a release looks wrong | [2. Roll back a deployment](#2-roll-back-a-deployment) |
| A new adjuster/investigator joins | [1. Add a user](#1-add-a-user) |
| A claim needs a specialist now, regardless of ClaimSense | [3. Escalate a flagged claim manually](#3-escalate-a-flagged-claim-manually) |
| The policy manual changed | [4. Update the policy corpus](#4-update-the-policy-corpus) |

---

## 1. Add a user

Access is decided by **group**, in code (`claimsense/door.py`), never by the model:

| Group | Can read |
|---|---|
| `adjuster` | only claims assigned to them |
| `senior-adjuster` | every claim |
| `fraud-investigator` | claims with fraud risk score ≥ 0.50 |
| `total-loss-appraiser` | claims with status Escalated, or repair/ACV ≥ 0.75 |

1. Confirm the person's group with their manager (the group is the whole permission).
2. Add them:
   ```
   python3 -m claimsense user add --id frank --name "Frank Li" --group adjuster --actor <your-id>
   ```
   The command refuses duplicate ids and unknown groups, re-validates `users.json`, prints how
   many claims the new user can read, and appends a line to `runs/admin.log`.
3. Check the scope is what you expect: `python3 -m claimsense user list`, then open the portal
   and "Sign in as" the new user.
4. Commit `claimsense/data/users.json` and open a PR; CI re-runs the RBAC tests and the gate.
5. To remove a user, delete their entry from `claimsense/data/users.json` and commit. Their
   past audit rows stay.

## 2. Roll back a deployment

**Trigger:** the CloudWatch alarm `claimsense-error-rate-above-5pct` (error rate > 5% over 5
minutes), the rolling pass rate on the ops dashboard below the 95% SLO, or adjusters reporting
odd recommendations.

1. **Look (2 minutes).** Open the CloudWatch dashboard `claimsense-ops` (or
   `ops/dashboard.html` locally). Note the time the error rate rose and one `trace_id` from a
   bad request (`aws logs tail /aws/lambda/claimsense-recommend --since 30m`).
2. **See what is deployed:** `python3 -m claimsense release show` — the active release and
   the last promotions with who and why.
3. **Roll back (one command):**
   ```
   python3 -m claimsense release rollback --actor <your-id> --reason "alarm at 14:05, trace trc-..."
   ```
   This re-activates the previous release in `releases/ACTIVE` and appends to
   `releases/HISTORY.log`. On AWS, redeploy so the Lambda picks it up:
   `deploy/deploy_api.sh <artifact-bucket> <mock|bedrock>`.
4. **Verify recovery — do not skip:**
   ```
   python3 -m claimsense eval --suite smoke --min-pass 0.95 --brain mock
   python3 -m claimsense eval --suite golden --min-pass 0.95 --brain mock
   ```
   Both must print `GATE PASSED`. Then watch the alarm return to OK.
5. **Write it up** with `docs/INCIDENT_REPORT.md` as the template, and add the failing case to
   `evals/regression_set.json` so the same regression can never ship again (the incident
   drill shows how: `ops/incident_drill.py`).

Never promote with `--skip-gate` outside a drill. `release promote` runs the golden gate first
and refuses a release that fails it.

## 3. Escalate a flagged claim manually

Use when a person (not ClaimSense) decides a claim must go to a specialist queue now — e.g.
an SIU tip, an injury found by phone, or the system is down.

```
python3 -m claimsense escalate --user bob --claim CLM-2024-1873 --to siu \
  --reason "Tip from body shop: estimate inflated; prior claims 2"
```

- `--to`: `siu`, `senior-adjuster`, `fraud-investigator` or `total-loss-appraiser`.
- The escalating user must be able to read the claim; otherwise the door returns
  `403 forbidden_scope` and logs the attempt.
- The ticket is idempotent: re-running the same command returns the same ticket
  (`"idempotent_replay": true`), so a retry never files twice. Tickets are kept in
  `runs/tickets.jsonl`; every access is in `runs/audit.jsonl`.
- Escalation never moves money and never changes the claim's coverage decision.

## 4. Update the policy corpus

The policy manual lives in `claimsense/data/corpus/`, one clause per file.

1. Edit or add a file. The first line must be `# CLS-XXX-NNN — Title` and the file name must
   start with the clause id (e.g. `CLS-RNT-011-rental-reimbursement.md`).
2. Validate:
   ```
   python3 -m claimsense corpus check
   ```
   It fails on bad headers, duplicate ids, a clause the code references but the corpus lacks,
   and on any clause text that reads like an instruction to the model (it would be quarantined
   and never cited).
3. Run the full gate on the change: `make verify && make golden`.
4. Cut a release: copy `releases/v1.0.0.json` to the next version, update `notes`, then
   `python3 -m claimsense release promote v1.0.1 --actor <you> --reason "corpus: <what changed>"`
   (the promote command runs the golden gate and refuses on failure).
5. If a clause's *meaning* changed (a threshold, a deductible rule), add or relabel golden
   cases in `evals/build_golden.py` and rebuild: `python3 evals/build_golden.py`.

## Alarm reference

- **Metric:** `ClaimSense/Errors ÷ ClaimSense/Requests`, 5-minute sum, from the EMF line the
  service prints per request.
- **Error:** the request raised (5xx), or its verdict came from the deterministic fallback
  (the model's output was rejected by the guardrail). A 403 scope refusal is **not** an error.
- **Known behaviour:** adversarial or injection-heavy traffic raises the error rate on purpose
  (the guardrail rejecting the model is the correct outcome). Golden-suite traffic runs at
  10.7% for this reason (`runs/eval_golden_mock_v1.0.0.json`); do not point eval traffic at
  the production alarm.
