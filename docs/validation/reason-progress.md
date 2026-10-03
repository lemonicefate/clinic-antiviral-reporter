# Confirmed medication reason evidence — #9

2026-10-03. All data synthetic; no live HIS access or production Excel export.

Implemented: preserve all 37 full official option values (code sheet E2:E38) from
the hash-verified original workbook; require physician/reporting capability and
explicit selected-patient confirmation. No eligibility or conditional-field rule
is inferred. Administrator-only sessions cannot edit clinical reasons.

Successful saves/revisions atomically retain before/after reason, operator, device,
time, source snapshot, revision and patient confirmation in audit. Request replay
returns the original result. A stale writer gets current revision/reason and cannot
overwrite until explicitly reloading and reconfirming. The selected reason does not
make the case officially exportable. Counts distinguish missing reasons from cases
still awaiting reporting reconciliation.

## Evidence

- 28 Python tests pass: original fixture integrity; options; confirmation; reporting
  edits; stale writes; replay; injected SQLite audit failure rollback; v1/v2 history
  and v3 source snapshot preservation through schema v4.
- Six frontend tests and two existing browser scenarios pass; Python and TypeScript
  type checks pass; Windows native debug executable rebuilt.
- `client/e2e-real/reasons.cjs` passed on real HTTPS API with two browser clients:
  all 37 options, disabled save until confirmation, Enter-key save, counts, conflict
  content, blocked overwrite, explicit reload/new confirmation, revision, and clearing
  unsaved reason content on outage without browser persistence.
- A deliberately failed list GET after a successful save reports the two outcomes
  honestly. `scripts/run_acceptance_checks.py` creates an isolated fresh environment
  for queue and reason flows; CI invokes it after the desktop build.
- 720px conflict screenshot was inspected locally; synthetic screenshots remain ignored.

The harness models Tauri IPC. These checks do not certify native deployment,
Windows certificate provisioning, official eligibility, or actual SMIS import.

## Standards

Review within approved baseline be7df98 identified one P3: a failed follow-up list
read incorrectly announced refresh success. Fixed by returning guarded load success
and regression-tested with an injected 400 response. A second P2 found Windows
cleanup could race SQLite handle release after terminating the venv launcher.
The runner now requests graceful shutdown, waits for exit, and retries transient
cleanup failures within a bound; the isolated full journey passes with exit 0.

## Spec

No concrete deviation found for #9. Planned two-client and schema-v4 migration
evidence has now been executed. Future dispensing/lot and platform workflows remain
outside this slice.

Standards: two addressed findings. Spec: zero concrete findings.

## Reproduce or inspect

Build the client, then from the repo root run:

```powershell
.venv/Scripts/python -m scripts.run_acceptance_checks
```

No manual repetition is requested. For optional inspection, open the prepared
acceptance homepage, choose B physician, enter `SYN-DR-A`, open a case, select an
official reason, confirm the displayed patient/order, and save. Two B tabs opened
before saving demonstrate conflict and mandatory re-review. Do not enter real data.
Future genuine on-device or SMIS steps require a separately prepared environment
and instructions; they remain OPEN.
