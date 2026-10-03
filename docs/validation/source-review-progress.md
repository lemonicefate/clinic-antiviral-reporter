# Source reconciliation evidence — #11

2026-10-03. Synthetic only; no live HIS access or production Excel export.

## Delivered behavior

Changed observations append source snapshots and advance case revisions. The
reporting-selected snapshot is independent of the latest source and the last
reviewed observation. Reasons, quantities, allocations and exclusion decisions
survive refresh. Reporting staff explicitly adopt, retain or exclude with a reason.
Adopting source facts does not replace actual dispensing or reverse exclusions.
Reported quantities above the adopted source cannot become internally complete.

The client shows old/new source fields, pending-review warnings, restricted
quarantine diagnostics and retained conflict drafts. Concurrent refresh invalidates
stale decisions. Missing/deleted observations never delete or infer exclusion.
Y builds ordinary work; C requires review; N-with-order is quarantined. Existing
unresolved cases remain visible with a warning and cannot finish source review.
Recovery permits review but never silently confirms it. Repeated identical
observations preserve snapshot count; quarantine retries record attempts.

## Verification

- 37 Python tests pass, including human-data preservation, explicit resolution,
  concurrent refresh, required capability, audit failure rollback, identical-source
  recovery audit and migrations from v1/v2/v3/v4/v5 to v6.
- Python/TypeScript types, six Vitest tests, two device browser checks and the native
  Windows debug build pass.
- Five real HTTPS browser flows include source differences, concurrent refresh,
  blocked stale writes, retain/update, unresolved diagnostics and recovery.
- Tests use isolated disposable synthetic environments. The browser bridge models
  native IPC; it does not prove native deployment or live HIS behavior.

## Standards

Two P2 findings: human audits initially cited the latest rather than adopted source,
and identical-source recovery initially lacked a case-level event. Both are fixed
and covered by public API regressions. Independent `gpt-6-luna` max verification
confirmed both fixes. Standards: two resolved findings, zero outstanding.

## Spec

No concrete missing, incorrect or out-of-scope behavior found by the independent
reviewer for this slice. Spec: zero findings. Real reading and scheduled retries remain #12; live key,
encoding, locking, cancellation timing and official export gates remain OPEN.

## Reproduce and inspect

Build the client, then run `.venv/Scripts/python -m scripts.run_acceptance_checks`.
No manual repetition is required. To inspect optionally, launch
`scripts/start_acceptance.ps1`, use A's case queue to choose a synthetic source
scenario and refresh, then open SYN-ORDER-1 from D reporting. Compare source fields,
choose a resolution, enter a reason and save. Refresh from A while D holds an old
form to exercise the explicit conflict/reload flow. N or missing observations
produce restricted diagnostics and block review until A restores valid facts.

## Migration and recovery

Schema v6 adds adopted/reviewed snapshot references and durable quarantine history;
v5 snapshots and every human decision are retained. Before upgrading an operational
central service, stop its sole owner and preserve the complete state directory in
the configured backup destination. Do not downgrade v6 files: older binaries refuse
the schema. Resume with the compatible v6 binary. If a pre-upgrade restore is needed,
retain the entire newer state separately and reconcile subsequent events before
operational use; never discard source versions or human decisions to roll back.

No additional patient persistence or logging is introduced in clients. All source
and case state remains central; outage unmounts the source-review form and diagnostics.
