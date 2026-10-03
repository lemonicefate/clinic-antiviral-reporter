# Mapping configuration progress — issue #13

Status: implementation and synthetic acceptance completed locally; final review and prepared-environment refresh are recorded below. This is evidence for the #13 software workflow, not M0 or live deployment completion.

## Implemented API boundary

`GET /api/v1/mappings` and `POST /api/v1/mappings` require an administrator device and active session. Choosing an administrator operator name does not grant this capability. Schema v8 appends mapping versions; migrating existing history does not invent a go-live timestamp or mapping assignment.

The confirmed profile is ERA → A059653100 → `DDMTR2018090002:易剋冒膠囊(顆)` with integer capsule quantities. Unknown profiles are rejected, including attempts to enable an unverified quantity rule by typing a code. Production export stays disabled.

The first version requires an explicit timezone-bearing timestamp and initial scan start date between the go-live date and today. Because source reporting dates contain no time, accepted effective boundaries must normalize to midnight at UTC+08:00. An intraday or timezone-free timestamp is rejected rather than assigning a fictitious event time. The first version must enable the confirmed profile. Later versions may enable or disable it, must have a strictly later effective boundary, and retain the initial range and previous versions. The administrator UI labels the midnight timezone explicitly, starts with blank date fields, displays immutable history and OPEN gates, and requires reloading/reviewing after a conflict without overwriting another administrator's changes.

Commands enforce expected revision, return current values on conflicts, replay the original result by request ID, and commit the mapping, audit event and replay record atomically.

## Scanner integration

The synthetic DBF scanner waits in `awaiting_configuration` until an administrator explicitly configures the mapping. Both automatic and manual requests use the configured initial start date. Each queued run captures the mapping revision and resolves the effective version against the date-only source within that fixed revision. Disabled or unavailable effective mappings quarantine the observation rather than create a case. Source snapshots reference the immutable mapping version through a foreign key; legacy snapshots retain NULL rather than an invented assignment. Changing a mapping reference appends a snapshot and requires human review; the difference is visible in source review. Human reporting values remain unchanged.

The runtime development/synthetic-reader gates from #12 remain required. The legacy `HIS_SCAN_FROM_DATE` setting is optional and no longer selects the scan range; a supplied value is still parsed for compatibility, but no value is inferred as go-live. The built-in demonstration refresh remains a separate synthetic namespace with NULL mapping references and no production export eligibility.

## Evidence at this checkpoint

- `python -m unittest discover -s tests -v` using the repository Python 3.12 virtual environment: **59 tests passed**.
- Six mapping API tests cover explicit activation, ambiguous boundaries and unknown profiles, version conflicts and immutable history, device capability, injected audit failure rollback, and restart/replay persistence.
- Migration acceptance covers versions 1–7, including preservation of source snapshots, human decisions, quarantine and the previous scan result, without seeding a deployment timestamp.
- Scanner tests additionally cover waiting for configuration, initial-range exclusion, version references, disabled-date isolation, reactivation and preservation of the old snapshot and reported quantity. A file-boundary pause exercises an administrator changing the mapping during a running scan: the in-flight run uses its captured version; the next run uses the new version.
- Mypy, the client production build and Windows Tauri debug build pass. OpenAPI and generated TypeScript client have been regenerated. Seven Vitest tests pass, including conflict draft retention and explicit reload.
- The isolated real HTTPS DBF acceptance journey passes: background scan, progress, orphan quarantine/recovery, no duplicate case, responsive layout and clearing the screen on outage. Its temporary environment explicitly configures the synthetic mapping through the API.
- All seven real HTTPS browser journeys pass. The mapping journey exercises successful explicit activation, rendered history, OPEN-gate display, concurrent administrator conflicts, restricted reporting-device navigation, and 720px layout. It found an unstable textarea label; using an explicit label association fixed the real-browser failure.

## Migration and recovery

Schema v8 adds append-only mapping versions, a nullable mapping foreign key on source snapshots and the captured mapping revision on scan runs. Existing source/human/audit history and completed scan metadata survive the migration. It does not seed a deployment timestamp. Version 7 and older binaries reject v8 rather than silently discarding its data.

Before upgrading an operational central state directory, stop its single owner cleanly and retain a complete, access-controlled copy of the stopped state directory and its matching runtime configuration outside Git. Do not copy an actively written SQLite database or touch HIS files. Test the upgrade on a separate local copy first. If the new binary cannot start, preserve both pre-upgrade and failed/current directories; diagnose on copies. Prefer a corrected v8-compatible binary so post-upgrade mappings, snapshots and human decisions remain available. Starting an older binary against a restored pre-upgrade copy is only a recovery rehearsal until every later audit/decision has been reconciled and retained; it is not permission to discard post-upgrade history. Do not lower `user_version`, drop tables, rewrite snapshots or delete the current state to bypass the version guard.

## Privacy and operation

Mapping commands contain only confirmed product codes, dates, administrator reasons and audit identity. The client receives no HIS/backup path or SMB credential and writes no mapping or patient data to browser storage. Reasons must not contain patient data or credentials. The test runner creates only synthetic data in an isolated temporary environment. Live HIS remains disabled and production Excel remains disabled regardless of mapping activation. The [manual guide](mapping-manual.md) covers optional native/human checks after the environment is prepared; automated browser checks do not prove actual clinic DPI, professional authorization or SMIS acceptance.

## Standards

Independent `gpt-6-luna` max review against `be7df98` plus the current working tree reported zero hard violations and zero material smell findings.

## Spec

Independent `gpt-6-luna` max review found stale/incomplete documentation and missing acceptance evidence. Documentation now includes migration recovery and privacy; successful UI/history/OPEN-gate acceptance and in-flight mapping concurrency have been added. The reviewer rechecked both findings and confirmed them resolved: zero remaining findings.

## Prepared environment

The persistent manual harness was stopped through its own authenticated control endpoint, preserving its prior run. A fresh synthetic run was started with the current schema v8 service and current React build. Its live loopback URL is recorded by the launcher in the private local `current.json`; use the link supplied at handoff or the launcher in the manual guide. No live deployment setting was copied. The first mapping remains unset so the administrator can inspect the explicit configuration flow.

No live HIS or SMIS testing was performed; all M0 evidence requirements remain in force.
