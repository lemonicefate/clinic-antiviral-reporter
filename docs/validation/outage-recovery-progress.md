# Outage recovery — issue #19

The service and Windows client implement administrator recovery scans and the separate terminal result `系統外已完成`. This is synthetic acceptance; live HIS, SMIS and deployment evidence remain OPEN. The authoritative requirements are SPEC v1.1 sections 3, 4 and 6, ADR 0004 and issue #19.

## Commands and preserved history

An administrator selects the outage's calendar-date interval in the scan panel and explicitly checks **停機復原補掃（管理者）**. `POST /api/v1/scans` accepts `outageRecovery: true` only from an administrator device. It retains the interval, requesting device/operator, request time and audit, uses the configured mapping/initial-range boundaries, and runs through the same central read-only scanner. Periodic and ordinary manual scans cannot support an outside completion. Source dates contain no time-of-day; operators must identify the affected orders from paper records within that date interval.

Every successful observation links its scan job, case and immutable source snapshot. A finished recovery scan must have observed the exact case/snapshot before `POST /api/v1/cases/{case_id}/outside-completion` can accept it. Date coincidence or a scan of another source is insufficient. A partial scan can support a safely observed, non-quarantined case; unresolved cases cannot be completed. A later source version requires a new matching recovery observation. `GET /api/v1/outage-rescans/latest` returns the latest explicitly requested recovery scan, unaffected by later periodic scans. Failed, queued or interrupted recovery scans are not completion evidence.

The completion command requires the current case revision, latest source snapshot, recovery scan ID, a nonblank reason, and explicit confirmation that paper and SMIS work completed. Administrator capability alone grants this command; an operator-name claim does not. The central recording time, device and operator are preserved. The terminal row, revision change, audit event and replay result commit atomically. Retrying the same request returns the original accepted result, including after restart; a conflicting revision or source requires re-reading and confirming again.

Existing medication reason, quantity, lot allocations, exclusion history and adopted source remain untouched. An excluded case must be explicitly re-included by reporting staff before the administrator can record outside completion. This avoids silently reversing a human exclusion decision. The completion links the reviewed latest source without overwriting the separately adopted reporting source. Further HIS changes append snapshots and remain visible in history, but never reopen a completed case. The terminal case is absent from active/unfinished/overdue/reason counts and cannot be selected for export or modified through ordinary reporting/reason/source-review commands. It remains searchable under **系統外已完成** or **所有案件**. There is no reopen operation, fabricated upload/platform result or inherited export version.

## Automated evidence and reproduction

Final verification on Windows passed: **69 Python tests**, **8 Vitest tests**, **9 real HTTPS browser journeys**, Mypy with `--check-untyped-defs` across 21 source files, generated OpenAPI/TypeScript, the production React build, and the Windows Tauri debug build. The shared command rename does not change the wire contract. `git diff --check` passed. No production HIS or SMIS submission was performed.

The API acceptance workflows in `tests/test_scanner.py` cover explicit recovery versus periodic scans, unrelated same-date source rejection, date bounds, stale snapshots, unresolved sources, administrator authorization, revision conflicts, false confirmations, atomic audit rollback, replay/restart, preservation of human data, terminal command guards, export-selection exclusion, and later source changes without duplicate cases or reopened work. `tests/test_migration.py` covers preserved history from schemas 1–8 and rejection of a future schema.

`client/e2e-real/outages.cjs` uses the built React client and real HTTPS service with synthetic files. It checks administrator recovery scan, unsaved-draft clearing during outage, fresh authorized reconnect, completion and searchable history. It also holds a real authorized patient-detail response at the native bridge boundary, disconnects the service, and releases that response after the patient workspace has unmounted; the late response must not restore patient content. Existing journeys cover reason, reporting, source review, bulk/conflict and export-preview outages. Platform-result screens will receive corresponding outage checks when implemented under their own tickets.

Run from the repository root:

```powershell
.venv/Scripts/python -m unittest discover -s tests -v
.venv/Scripts/python -m mypy --check-untyped-defs service scripts
npm --prefix client test
npm --prefix client run build
.venv/Scripts/python -m scripts.run_acceptance_checks
npm --prefix client run tauri -- build --debug --no-bundle
```

The browser suite creates isolated temporary environments and stops its own services. It never uses a user's active manual test database. The native bridge is simulated only for browser automation; the central requests use real TLS and authorization. Native credentials and actual clinic networking remain separate deployment evidence.

## Migration, rollback and privacy

Schema v9 adds `scan_runs.outage_recovery`, `scan_case_observations` and `outside_completions`. Historical scans are ordinary scans by default; migration does not fabricate evidence of prior recovery observations. An explicit new recovery scan is needed after upgrade. Existing sources, mappings, reasons, lots, exclusions, commands and audit remain unchanged. The shared mutation-envelope class is now named `RevisionCommand`; wire fields remain `requestId` and `expectedRevision`.

Before deployment, stop the single central owner cleanly and preserve its complete state and protected runtime configuration outside Git. Older v8 binaries reject v9 state. Roll back application code only with a reviewed v9-compatible build; never lower `user_version`, remove tables or restore an older database over newer human decisions. If a pre-upgrade copy is used for diagnosis, use an isolated copy and preserve the current state for recovery. Retain all completion and observation history under the existing retention policy. Actual off-host backup/restore acceptance remains #20/#25 work.

All patient views, drafts and pending command IDs are transient client memory. Disconnect or session exit unmounts them; no offline queue or sync is created. The browser late-response check deliberately retains only a synthetic response in test memory. No clinical DBF, patient data, deployment path, credentials or generated log is committed. Test authors write only synthetic files under dedicated local temporary roots, never into a HIS share. Production HIS and Excel gates remain disabled.

## Prepared environment and optional operator check

The persistent synthetic environment's current entry URL is in `%LOCALAPPDATA%\ClinicReporterAcceptance\case-queue-v1\current.json`. This recovery environment must have synthetic DBF mode enabled, a configured mapping, and the case `SYN-DBF-ORDER-1`. Its temporary synthetic source directory is separate from both real HIS and the repository. Earlier manual runs are retained.

The prepared handoff run is **http://127.0.0.1:9215/**. A browser check verified its current client, an explicit administrator recovery scan and one uncompleted synthetic DBF case; the final completion is left available for the optional operator exercise. The preceding manual harness was stopped using its own control token and its files were retained. This run's data is under a dedicated temporary root; if Windows cleanup removes it, create a new synthetic run rather than treating it as clinical storage.

No manual repetition of automated checks is required. To assess whether the language and steps fit the clinic's approved paper procedure:

1. Open the environment entry page and the **管理者** client. Enter a synthetic operator name and connect. Choose **案件工作清單**.
2. In **來源檔案掃描**, select the start/end dates covering the synthetic case (today in the prepared run). Check **停機復原補掃（管理者）**, press **要求檔案重掃**, and wait for **掃描完成**. A failed or interrupted result is not a completed scan.
3. Press **查詢清單**, locate `SYN-DBF-ORDER-1` / `SYN-DBF-P1`, then **核對此案**. Check the displayed source and date. Press **讀取補掃結果** and verify the displayed date interval.
4. In this synthetic exercise only, enter a test reason, check the paper/SMIS completion confirmation, then press **確認系統外已完成**. Do not represent this exercise as an actual SMIS import. Expect the case to leave the active list.
5. Select **系統外已完成**, query again and open the case. Check that the reason, operator, recording time, recovery range and linked source version are readable. There must be no ordinary editing or export action for this terminal case.
6. To assess outage wording, use **停止中央** on the environment entry page while a patient case is open. Expect the client to clear patient content and direct staff to paper. Use **啟動中央** and reconnect for fresh data. This control affects only the synthetic service.
7. Report only unclear wording, the step number and expected workflow. Use synthetic screenshots if useful; do not supply real patient records, credentials or HIS paths.

## Standards

The independent `gpt-6-luna` max reviewer rechecked the explicit administrator recovery scans, exact observation links, migration, UI and shared `RevisionCommand` name. The initial generic-scan evidence gap and naming concern are resolved. **Zero remaining documented-standard violations or actionable heuristic smells.** The reviewer inspected code; the root agent ran the verification listed above.

## Spec

The independent `gpt-6-luna` max reviewer rechecked recovery-scan association, the late in-flight patient-response outage check and recovery/migration/privacy documentation. **Zero remaining #19 behavior or acceptance findings.** The reviewer inspected code and evidence descriptions; the root agent ran all tests. Actual M0 evidence and downstream export/platform/backup work remain separate outstanding tickets.
