# MVP child-ticket proposal

Status: approved by the user and published on 2026-10-03. See ticket-issues.json for the proposal-to-GitHub mapping.

Based on SPEC v1.0 plus authoritative v1.1, CONTEXT, ADRs, the HIS read contract,
M0 evidence checklist, and GitHub issues #1–#6 including their comments, inspected
2026-10-03. Foundation #2 is closed. Product directories currently contain only
README placeholders. The latest #4 comment permits synthetic non-production M1
work without closing M0. Existing milestone bodies and states remain unchanged.

Numbers below are proposal identifiers, not GitHub issue numbers. Published in
topological order with native parent/sub-issue and blocked-by relationships. Cross-layer
slices have one primary parent; that parent does not limit their implementation
scope. Existing milestone dependencies remain milestone completion constraints.

## Shared acceptance and delivery contract

- Agent slices include durable central state, versioned API, generated TypeScript
  bindings, the relevant Tauri/React workflow, and synthetic acceptance evidence.
  No separate schema-only, API-only, or UI-only tickets are proposed.
- All mutations use requestId and expectedRevision; accepted changes and audit
  commit atomically. Audit includes device, selected operator, time, changes,
  reason where required, and related source/export identifiers.
- Use Python 3.12/FastAPI, a single SQLite owner, and Tauri 2/React/TypeScript.
  Introduce migrations with each slice; test upgrade and document recovery without
  deleting historical data. Retain records under the repository retention policy.
- Patient content stays in central storage and transient client memory. No patient
  content, credentials, source/backup paths, or sensitive diagnostics enter client
  persistence, telemetry, public evidence, or Git. Only synthetic test data is used.
- Each issue receives tests, operator/developer documentation, migration notes,
  rollback instructions, privacy effects, and evidence links before closure.
  Rollback preserves source versions and every human decision and export version.
- Production HIS access remains gated on live evidence. Production export remains
  disabled until ALL M0 gates are evidenced and its operational flag is enabled.
  A synthetic test mode must never provide a production bypass.
- Intake uses needs-triage; fully specified software slices become ready-for-agent.
  External evidence tasks become ready-for-human. Missing named official facts also
  receive needs-info. Dependent software tickets remain needs-info until those
  contracts are evidenced and their acceptance criteria can be finalized.
- Follow implement's tests, code review, and current-branch commit workflow. Run
  the repository unittest discovery command whenever fixture/check changes occur.

## 1. Pair a device and open a capability-aware session

Parent: #4. Owner: agent. Blocked by: none (foundation #2 complete).

Deliver an administrator pairing/revocation flow and a desktop connection screen
backed by central device/session storage and a versioned generated API client.

- Independently credentialed devices receive only assigned capabilities; changing
  selected operator identity never grants a capability.
- Unknown/revoked devices cannot read or mutate; revocation also invalidates
  existing sessions. Verify HTTPS credential handling and denied API requests.
- Persist only allowed client settings; disconnect clears protected content and
  displays the paper fallback. Every later patient screen uses this boundary.
- Validate central-only runtime settings, distinct backup/HIS share names, local
  state ownership, and disabled production gates; expose neither path in OpenAPI.
- Demonstrate pairing, permitted access, denial, revocation, restart persistence,
  and migration recovery using synthetic credentials outside Git.

## 2. Import synthetic source orders into the physician work queue

Parent: #4. Owner: agent. Blocked by: 1.

Deliver synthetic source refresh through the central ingestion seam to a physician
queue and detail screen. This does not claim a verified live HIS identity contract.

- Distinct synthetic order items remain distinct even for the same patient/date;
  repeated refresh is deduplicated and snapshots retain original raw facts.
- Use confirmed Eraflu mapping, calendar reporting date, and integer capsule
  quantity. Mark the candidate key and unresolved source encodings as unverified.
- Show physician filter, recent cases, exact chart-number lookup, duplicate warning,
  cross-physician assistance, counts, and overdue unfinished work.
- Show enough patient/source facts for explicit selection confirmation; never
  invent time-of-day or silently resolve tied calendar dates.
- Demonstrate two physicians, multiple same-day orders, restart, and refresh retry.

## 3. Confirm a patient and save or revise a medication reason

Parent: #5. Owner: agent. Blocked by: 2.

Deliver the physician reason workflow using the official workbook's preserved
option values, without inferring eligibility or unresolved conditional rules.

- Confirm the selected patient before saving; physicians need not enter lots.
- Save/change reason and refresh queue counts; reporting capability can also edit.
- Two clients editing one revision receive field differences on the stale write;
  require re-review before another submission, never last-write-wins.
- Timeout/retry returns the first result with one audit event. Inject transaction
  failure to prove neither data nor audit can commit alone.
- Verify keyboard operation, non-disruptive counts, error visibility, and no local
  persistence of form content.

## 4. Reconcile actual quantity, lots, and exclusions

Parent: #5. Owner: agent. Blocked by: 3.

Deliver the reporting queue with filters and case editing for actual dispensing.

- Preserve source quantity; an audited reason supports reducing 10 capsules to 5.
- Support multiple lot allocations, exact total validation, bulk same-lot entry,
  and independent later edits. Test 6+4=10 versus 6+3 and invalid numeric inputs.
- Exclude/reinclude only through human commands with retained reasons; excluded
  cases leave unfinished counts and default export selection.
- Show original/report differences, date/physician/chart/status/exception filters,
  and audit history; no inventory functionality or automatic exclusion.

## 5. Review source changes without overwriting reporting work

Parent: #4. Owner: agent. Blocked by: 4.

Deliver source-version history and explicit reporting reconciliation.

- Refresh appends changed snapshots; it preserves reasons, lots, exclusion decisions,
  and any export/platform history introduced by later slices.
- Show before/after differences and HIS 異動待確認 for cancellations/important edits.
- Apply confirmed Y/C/N policy. Deleted rows never automatically delete a case;
  unresolved or missing sources never become inferred exclusions.
- Human review records the resolution and reason atomically; concurrent source
  refresh cannot silently invalidate a reporting decision.

## 6. Schedule read-only refresh and inspect quarantine

Parent: #4. Owner: agent. Blocked by: 5.

Deliver the clean-room adapter, periodic/manual refresh, progress, and restricted
quarantine/retry workflow, exercised only with synthetic source files initially.

- Default configurable 60-second scans run without a client; bounded retry and
  date-range reconciliation avoid missed work and duplicate cases.
- All source handles are read-only; no write probe, repair, rename, or auxiliary
  file creation. Generate synthetic DBF-family samples in temporary test storage.
- Exercise deleted rows, orphan joins, meaningful RELKEY spaces, code mismatch,
  missing/ambiguous keys, decoding errors, partial writes, and sharing violations.
- Only reporting/admin capabilities see quarantined details. Failure/stale scan
  diagnostics never imply a successful refresh and do not leak patient data.
- Production adapter activation awaits 16; unresolved live facts remain OPEN.

## 7. Maintain effective mappings and the initial scan boundary

Parent: #4. Owner: agent. Blocked by: 6.

Deliver administrator mapping version history and explicit go-live/initial-range
configuration through the central service and client.

- Seed the confirmed ERA → A059653100 → exact SMIS label chain, effective from an
  explicit go-live boundary, without inventing a deployment timestamp.
- Preserve superseded mappings and snapshot references; reject mismatched codes
  rather than silently selecting a value.
- Unknown units/material rules cannot be enabled merely by entering a new code.
- Show unresolved gates and reject ambiguous boundary configuration; a date-only
  source must not be assigned an invented event timestamp.

## 8. Review export selection and production gate status

Parent: #6. Owner: agent. Blocked by: 4.

Deliver selection/validation preview and readable M0 gate status without producing
a production workbook or pretending OPEN official rules are validated.

- Default-select complete, not-uploaded eligible cases; allow manual selection,
  show missing fields, source warnings, and duplicate concerns per case.
- Distinguish internally complete data from officially exportable data; unknown
  mandatory/conditional rules are explicit blockers.
- Test 18 complete and 2 incomplete cases, excluded cases, and capability denial.
- Both API and client refuse production generation/download while any required
  evidence is absent; an enabled environment flag alone is insufficient.

## 9. Generate and download an immutable synthetic export version

Parent: #6. Owner: agent after official contract evidence. Blocked by: 8, 17.

Deliver the verified workbook-generation workflow in synthetic mode first.

- Freeze selected case revisions and item/lot snapshots; start from the untouched
  official fixture, preserve sheets/validation/options, reopen/validate, hash, then
  publish ready. Concurrent changes cannot alter frozen content.
- Test exact official values, multi-lot rules, conditional fields, leading zeros,
  text/date types, formula defense, and actual quantity under the evidenced rules.
- Inject failure at each stage; interrupted versions are not ready/downloadable,
  and restart/retry never overwrites an artifact or marks a partial file complete.
- Show pending-upload versions and immutable history; pre-upload regeneration
  voids the prior version and creates a new one.
- Production remains disabled pending all M0 evidence, including 20.

## 10. Record upload declarations and per-item platform results

Parent: #6. Owner: agent. Blocked by: 9.

Deliver manual upload tracking, result entry, and batch summaries.

- Declaration identifies the exact export version, operator, and time; it cannot
  imply platform acceptance. No SMIS automation or credential collection.
- Record success, failure, pending confirmation, notes/reference information per
  case/export item with immutable history; derive batch state from these results.
- Test 18 declared items with only 16 confirmed, independent retries/conflicts,
  authorization, and remaining-work visibility.

## 11. Create correction versions and warn on repeat reporting

Parent: #6. Owner: agent. Blocked by: 10, 5.

Deliver post-upload editing and explicit correction/repeat submission workflows.

- Post-declaration or post-result edits require a reason and produce a linked
  correction version; preserve prior source, export, and result history.
- Never carry prior acceptance into new content. Warn and require confirmation
  when users select already-uploaded content for another export.
- Apply only evidenced official correction/duplicate behavior; test changes to
  required reporting fields, lots, and source reconciliation after upload.

## 12. Recover an outage and record 系統外已完成

Parent: #6. Owner: agent. Blocked by: 6.

Deliver administrator outage-range rescanning and independent outside-system
completion, with the paper workflow enforced throughout disconnection.

- Interrupt every implemented patient workflow: clear/invalidate patient content,
  including modals and in-flight responses; prohibit offline read/edit/queue/export.
- Reconnect through fresh authorized reads. Re-scan the chosen interval without
  duplicating orders or losing previously entered reporting data.
- Administrators record operator/time/reason/source association for the distinct
  terminal state; it is neither exclusion nor an inherited export/platform result.
- Extend outage tests to export/result screens as they are added.

## 13. Back up central history hourly and restore a working service

Parent: #4. Owner: agent. Blocked by: 1.

Deliver scheduled central backup, administrator health/status, and a restore tool
with a synthetic recovery drill; extend the backup inventory with later slices.

- Back up consistent SQLite state, audit, configuration, and immutable artifacts;
  reject a backup on the HIS share even under another directory or case spelling.
- Expose last successful backup/failure and RPO breach without exposing paths or
  secrets. Recover after interruption without advertising incomplete backups.
- Restore into an isolated synthetic environment and verify history/service startup.
  Document retained-record handling, ACL/credential recovery, and rollback.
- Real off-host hourly RPO and restore evidence belong to 19; synthetic success
  does not close that deployment gate.

## 14. Install the Windows app and safely update or roll back

Parent: #5. Owner: agent. Blocked by: 1.

Deliver per-user packaging, tray/autostart, update verification, and rollback.

- Install without administrator privilege under the fixed Windows account; close
  minimizes to tray, explicit quit exits, and startup behavior is configurable.
- Check updates without forcing closure during care; require user confirmation,
  validate signatures, and retain a working rollback version.
- Exercise rejected/corrupt/interrupted updates and rollback with synthetic keys
  outside Git; retain allowed preferences but never patient content.
- Document central Windows-service startup/recovery and client deployment. Real
  certificates/device/account evidence remains part of 19.

## 15. Verify the complete synthetic MVP acceptance journey

Parent: #6. Owner: agent. Blocked by: 7, 11, 12, 13, 14.

Deliver repeatable end-to-end evidence across the service and actual Windows client.

- Trace every v1.0 section 11 scenario and v1.1 section 9 addition to an automated
  test or explicit reproducible manual result; exercise multi-client conflicts,
  revocation, recovery, export failures, and update rollback.
- Verify generated-client drift, migrations from earlier slices, history retention,
  restart, privacy in client storage/logs/build artifacts, and immutable fixtures.
- Publish synthetic-only operator/deployment/recovery instructions and acceptance
  results. Keep live-system evidence marked incomplete until 16–20 are satisfied.

## 16. Validate the live HIS read contract

Parent: #3. Owner: human. Blocked by: 6.

Deliver dated, reviewed, de-identified measurements for candidate key null/reuse/
edit behavior, live TREAT transitions and order amendments, encodings, partial
writes, read locks, retry behavior, and safe load. Measure committed-write visibility
separately from scan delay. Use a read-only Windows identity and handles; never
mutate the source as a test. The clinic HIS owner supplies evidence. Record any
contract discrepancy and re-triage affected implementation rather than assuming it.

## 17. Establish the official synthetic SMIS test contract

Parent: #3. Owner: human. Blocked by: none.

Deliver authoritative field/conditional-field/code/quantity rules plus an accepted/
rejected synthetic test matrix for multiple lots, subsequent doses, duplicates,
corrections, partial results, foreign identifiers, and special fields. The clinic
reporting lead/SMIS owner supplies dated evidence and reviewer identity. Existing
outpatient sheet acceptance remains confirmed; do not re-open it or invent other
rules. Attach no patient data or identifiable screenshots. This establishes the
contract for 9; actual generated-file acceptance is separately verified in 20.

## 18. Confirm operational responsibility and authorization

Parent: #3. Owner: human. Blocked by: none.

Deliver competent-authority/SMIS-owner confirmation of proxy operation and
certificate authorization, the clinic's actual-lot/quantity/professional-review
responsibilities, approved paper fallback, and responsible-owner confirmation of
record-category retention policy. Capture dated de-identified evidence and roles;
never attach credentials/PINs or equate software capability with qualifications.

## 19. Rehearse deployment, restore, revocation, and paper recovery

Parent: #3. Owner: human. Blocked by: 7, 12, 13, 14, 16, 18.

Deliver on-device evidence for central service autostart, Windows accounts, HTTPS,
firewall/allowlist, device pairing/revocation, signed client install/update rollback,
and a dedicated off-host backup share distinct from HIS DATA. Prove RPO ≤1 hour
and restoration, record explicit go-live boundary/initial scope, and rehearse outage
rescan plus outside-system completion. Keep all real paths/secrets private. The
clinic administrator supplies dated results; store only de-identified evidence.

## 20. Verify actual synthetic SMIS import and production readiness

Parent: #3. Owner: human. Blocked by: 15, 16, 17, 18, 19.

Deliver a retained de-identified report of actual SMIS acceptance of repository-
controlled synthetic exports, including the official scenario matrix. The authorized
reporting operator performs manual SMIS work. Reconcile every M0 checklist entry
with dated reviewer evidence; failures create linked corrective work and remain OPEN.
Verify the service gate denies production before evidence is complete and enables
it only with complete evidence plus the operational flag. No milestone or MVP map
is closed merely because software tests pass.

## Coverage and review

| Requirement group | Proposal tickets |
|---|---|
| v1.0 scenarios 1–3: collection, identity, queues | 2, 6, 7, 15, 16 |
| v1.0 scenarios 4–9: reason, lots, quantity, source, exclusions | 3, 4, 5, 15 |
| v1.0 scenarios 10–12: selective export, history, partial results | 8, 9, 10, 11, 15 |
| v1.0 scenarios 13–15: outage, devices, official acceptance | 1, 12, 15, 17, 19, 20 |
| v1.1 scenarios 16–19: conflicts, retry, export failure, revocation | 1, 3, 9, 15 |
| v1.1 scenarios 20–22: update rollback, paper recovery, corrections | 11, 12, 14, 15, 19 |
| M0, backups, retention, operations | 7, 13, 16, 17, 18, 19, 20 |

The user approved this breakdown with "ok". Continue implementation from the
unblocked software frontier; external evidence gates remain OPEN.
