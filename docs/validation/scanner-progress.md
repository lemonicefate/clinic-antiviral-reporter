# Read-only scanner evidence — #12

2026-10-03. This slice exercises synthetic files only. Production HIS activation
remains blocked by [#23](https://github.com/lemonicefate/clinic-antiviral-reporter/issues/23).
No production source path is opened, and production Excel remains disabled.

## Behavior and limits

The sole central process owns a background worker. It scans on startup and at the
configured interval (60 seconds by default), independent of connected clients.
Each periodic scan rechecks the explicit initial date through the clinic's current
date. Authorized devices can request an inclusive subrange and retry quarantine;
requests carry revision and request ID, are durably queued and replay the original
accepted response. Completion is a separate state, never implied by acceptance.

Requests, running/completion/interruption events and source changes are retained
centrally. Stable source snapshots deduplicate. A case is reconciled when its prior
or current date is in the selected range, including date changes out of that range.
Cases with both dates outside the range are unchanged. New cases must be in range.
Invalid sources whose current dates cannot be established are conservatively isolated;
full-file read/encoding failures still prevent publication of a source batch.
Failed reads publish no partial source batch. A scan with invalid rows is partial,
does not advance last-success time, and retains restricted diagnostics. Failed
ingestion rolls back case changes and leaves a retryable failure. Clients display
progress, last complete success, stale/failure states, counts and date-range retry.

Read access uses freshly opened binary handles, no cache and no source writes.
Fixed-width raw values survive under `raw.TABLE.FIELD`; normalization is separate.
The synthetic key namespace hashes the raw RELKEY/order pair, including boundary
and embedded spaces. Trimming is limited to association/field normalization, never
candidate identity. No stable live-key contract is inferred.

The intentionally narrow test dialect is dBASE III, strict CP950 character/numeric/
date allowlist values, ISO calendar strings and positive integer capsule totals.
Memo/index contents are not needed or parsed. Other dialects, live date encodings,
null flags and memo requirements remain OPEN and cannot enable production reading.
Tables are capped at 16 MB each; unsupported framing, incomplete transactions,
changed metadata, decoding errors and access/sharing failures stop the batch.
Read attempts are bounded to three with 50/100/200 ms waits. Real UNC load and
cross-file consistency still require on-device evidence.

## Verification

49 Python tests, six frontend tests, two device browser scenarios, six isolated
real HTTPS journeys, Python/TypeScript type checks and the Windows debug build pass.

Synthetic tests cover unattended periodic ingestion, fresh file changes, unchanged
retries, date bounds, raw spaces, deleted records, orphan and ambiguous associations,
missing/duplicate keys, code mismatch, malformed bytes, short writes and N policy.
Source hash/name comparisons and open-mode interception verify no reader writes.
A real Windows CreateFileW exclusive read handle produces a bounded sharing failure;
closing it permits successful retry. Audit-failure injection proves ingestion
rollback and continued worker availability. Physicians may request refresh but
cannot inspect quarantine. Settings reject production/synthetic bypasses.

The real HTTPS browser journey checks startup scan results, progress, orphan
diagnostics, repair/retry without duplication, 720px layout and outage clearing.
This bridge-based browser test is not native IPC or live HIS acceptance.
Schema migrations exercise v1 through v6 into v7 while preserving prior snapshots,
adopted-source pointers, reasons, allocations, exclusions and quarantine attempts.

## Reproduce

From the repository environment, build the client, then run
`.venv/Scripts/python -m scripts.run_acceptance_checks`. The runner creates separate
disposable environments for prior scenarios and the file-scanner scenario. Every
DBF/FPT/CDX sample is generated in temporary local storage and stays outside Git.
No manual repetition is requested.

For an optional dedicated development service, explicitly generate fixtures with
`.venv/Scripts/python -m scripts.synthetic_dbf --state-dir <dedicated-state-under-TEMP> --date YYYY-MM-DD`.
Set `SYNTHETIC_ENABLED=true`, `SYNTHETIC_DBF_ENABLED=true` and the explicit
`HIS_SCAN_FROM_DATE` with the `CLINIC_REPORTER_` prefix. Only the state's
`synthetic-dbf` directory is read. This does not redirect or activate HIS_SOURCE_PATH.
The generator rejects destinations outside system temporary storage, its root, UNC
paths and reparse points. It is test authoring tooling, never called by the service
or a client API.

## Migration and recovery

Schema v7 adds scan state and append-only run history. Before operational upgrades,
stop the central owner and preserve complete central state at the separately
configured backup destination. Interrupted running jobs are recorded as interrupted
on restart; queued jobs remain available, followed by periodic reconciliation.
Rollback uses a compatible service binary with the preserved v7 database. Do not
downgrade or delete its tables. A pre-upgrade restore must preserve the newer state
separately and reconcile all later human/source events before operational use.

## Dependency source

`dbfread==2.0.7` is pinned. Its [DBF object documentation](https://dbfread.readthedocs.io/en/latest/dbf_objects.html)
documents raw-byte mode and streaming. The installed implementation was inspected:
DBF files use `rb`, and raw mode does not open memo contents. The service adds its
own strict framing, identity/join validation and conservative failure policy.

## Standards

Independent `gpt-6-luna` max review found one replay violation: a feature gate
preceded saved-result lookup. Fixed and independently rechecked; the restart test
proves accepted requests replay after disabling scans, while new requests fail.
One heuristic noted repeated audit SQL; direct audit inserts remain consistent
with existing modules and no speculative abstraction was added. One hard finding
resolved, zero remaining hard findings; one heuristic intentionally retained.

## Spec

Independent `gpt-6-luna` max review found two issues across review/recheck: fixture
output could escape temporary local storage, and invalid observations moving into
a selected date range could be missed. Both are fixed and independently rechecked.
Regression tests cover path refusal with no files created and current/prior date
selection with unchanged snapshots. Two findings resolved, zero outstanding.
