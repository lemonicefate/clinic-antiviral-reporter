# Reporting reconciliation evidence — #10

2026-10-03, synthetic only. No HIS access; production export disabled.

## Delivered behavior

Reporting-only dispensing commands preserve source quantity, require a reason for
quantity changes, validate positive integer allocations and exact unique-lot totals.
Bulk replacement carries every selected revision and commits all cases/audits
together; subsequent individual edits remain independent.

Exclusion/reinclusion requires reasons and preserves decisions in audit. Default
queues omit excluded cases; explicit status filters retrieve them. UI filters cover
physician, chart, date, status and exception concerns. History shows operator/device,
time, before/after fields and reasons. Stale writes show case/revisions and original,
current and draft values, with explicit reload before another submission.
Internally complete data is not officially exportable; no inventory is implemented.

## Verification

- 32 Python tests pass: 6+4=10, rejection of 6+3, audited 10-to-5 with unchanged
  source, integer validation, retry, independent allocations, exclusion history,
  role denial, reason-only bulk conflict, and second-case audit failure rollback.
- Migration fixtures exercise v1/v2/v3/v4 to v5, preserving source and saved reason.
- Six Vitest tests, two prior browser scenarios, Python/TypeScript types and native
  Windows debug build pass.
- Four isolated real HTTPS browser journeys pass. Reporting covers bulk/individual
  lots, quantities, exclusion/reinclusion/history, quantity-difference filter,
  720px layout and outage clearing. Reporting conflicts cover visible old/current/
  draft fields, reason-only concurrent change, blocked writes and untouched peers.
- Synthetic reporting screenshot inspected; local screenshots remain ignored.

## Standards

One P2: bulk conflicts omitted a concurrently changed reason. Fixed with the full
shared current-field payload. Targeted reviewer and regression test confirm resolution.

## Spec

One P2: reporting editors hid field differences. Both editors now display case,
revisions and old/current/draft fields. Targeted reviewer confirms resolution.

Standards: one resolved finding, zero outstanding. Spec: one resolved finding,
zero outstanding.

## Reproduce

Build the client, then run from the repository root:

    .venv/Scripts/python -m scripts.run_acceptance_checks

The runner creates and cleans its own synthetic environment; no manual repetition
is requested. Native IPC is modeled by the browser bridge, so native deployment,
actual Windows networking and all external M0 facts remain OPEN.
For optional inspection, the prepared homepage offers D reporting profile.
This checkpoint does not establish full MVP or production readiness.
