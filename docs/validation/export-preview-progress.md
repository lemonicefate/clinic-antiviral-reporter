# Export selection preview — issue #14

The software now provides a read-only selection/validation preview; it does not generate a production workbook or declare that OPEN rules have passed. Synthetic acceptance is recorded below; actual M0 evidence is not inferred from these tests.

## API and client behavior

Reporting-capable devices can open `GET /api/v1/export-preview`. The service projects the current durable case, adopted source snapshot and human reporting data in one transaction. It returns default selection, selected counts, internal issues, duplicate/source warnings, per-case official blockers and readable OPEN M0 groups. Administrator capability alone does not grant reporting authority. Optional date bounds filter the projection; an inverted interval or a selected ID outside the requested range is rejected.

The default selection includes internally complete, non-excluded cases. There are no export/upload records in this release because production generation is unavailable; implementing export/upload lifecycle later must update this default to omit uploaded records. Users can clear, select or deselect cases for review, including an incomplete case to examine its blockers. Excluded cases are never selected by the service. Each manual selection is rechecked centrally through the read-only `POST /api/v1/export-preview` body, avoiding URL-length limits for large selections. GET selection queries remain compatible. This POST is a read projection, not a mutation: no case change, persisted selection, export record or audit event is created.

Internal completeness is not official exportability. Missing medication reasons, absent/mismatched lot allocations, invalid reported quantities, unresolved sources and pending source review are shown separately from unverified official mandatory/conditional fields, dose/quantity semantics and multiple-lot rules. Missing mapping references and unverified live source contracts remain explicit. Duplicate concerns are warnings, not automatic merging or an invented prohibition.

`POST /api/v1/exports` is a typed, revision/request-ID-bearing boundary but refuses every new generation request with `production_export_gated`; `GET /api/v1/exports/{id}/file` also refuses access. An environment flag alone cannot pass evidence. An accepted command retried on the wrong mutation route retains the repository's original-result replay contract; this does not create an export. No workbook writer is called. The UI exposes disabled generation/download actions and clears the entire preview on central disconnection through the existing session boundary.

## Evidence

- **64 Python tests pass.** Five new API workflows use synthetic DBF order items and real case commands: 18 complete plus 2 incomplete, manual/excluded selections, date bounds, authority denial, production generation/download refusal even with the environment flag enabled, source-change preservation of human quantities/lots, and 103 default-selected complete cases manually reduced to 102. The latter regression failed with the former arbitrary 100-ID query limit and passes after removing that inconsistency.
- **8 Vitest tests pass**, including server-reviewed selection and disabled workbook actions despite an enabled operational flag.
- Mypy, generated OpenAPI/TypeScript bindings, client production build and Windows Tauri debug build pass.
- The dedicated real HTTPS browser journey passes: a complete case is preselected, selection can be cleared and manually restored, OPEN rules remain readable, generation/download requests are denied, 720px layout stays within the viewport, and outage clears the preview. A checkbox is asserted only after the central response, not optimistically at click time.
- All **eight** combined real HTTPS browser journeys pass, including the seven previous flows and the new preview flow. The selection-limit fix was additionally checked with the 103-case API regression.

## Standards

Independent `gpt-6-luna` max review found no documented standards violations or material heuristic smells. It also identified a cross-axis functional mismatch between unlimited default selection and a 100-ID manual-selection limit; this was reproduced and fixed.

## Spec

The independent `gpt-6-luna` max Spec review found the requested preview/gate behavior implemented. It independently ran the 103-to-102 regression and confirmed the selection-limit defect fixed. Its additional request-length caveat was addressed by moving client selection IDs into a read-only POST body; the same central authorization and date/selection checks apply. The reviewer rechecked this final GET/POST split and reported no new blocker. Zero unresolved acceptance findings remain.

## Migration, recovery and privacy

There is no schema change from v8 and no persistent preview state. All existing case revisions, source/mapping history, human reasons, lot allocations and exclusion decisions remain in central storage. No official fixture is modified. Tests author synthetic files only in dedicated temporary local directories, never in the configured HIS share.

For rollback, stop the single central owner cleanly, retain the complete state/configuration outside Git, and use the prior v8-compatible release (`36e6f0d`) with the same state. No downgrade, table deletion, history deletion or snapshot rewrite is required. Older pre-v8 binaries still reject this state. Keep new human decisions made during operation; a rollback is not permission to restore an older data copy over them.

Preview content and selection IDs stay in transient client memory and are discarded on page/session exit. No patient data, credentials, runtime HIS/backup path, produced workbook or sensitive logs are committed or put in browser persistence. Operator reasons must not contain credentials or patient data. Global OPEN status is not a editable bypass. Actual HIS, SMIS, professional authorization and operational evidence remain outstanding M0 work.

## Reproduction and optional human checks

Run the repository unittest command, `npm test` and `npm run build` in `client`, then `.venv/Scripts/python -m scripts.run_acceptance_checks` from the repository root for isolated real-API journeys. The browser harness uses real HTTPS to the central service while substituting its in-memory synthetic device bridge for native Windows credential storage.

When the updated prepared environment is handed off, open the reporting-device entry, enter `SYN-REPORTER`, connect and choose **匯出前核對**. Check the date range, each case's warnings and the distinction between internal completeness and official eligibility. Use **清除選取**, manually check a row, and wait for the central summary. Both Excel actions must remain disabled. Return to **案件工作清單** to correct missing reasons/lots and reopen the preview to see updated checks. No manual repetition of the already automated cases is required. Actual native Windows DPI/readability and clinic workflow suitability remain optional human checks; screenshots must contain synthetic data only.

The persistent synthetic harness has been refreshed to the current service and React build. Its previous run was stopped through the owned control endpoint and retained. A new run was started and the reporting preview was opened through the browser to verify the live environment. The handoff URL is also available from `%LOCALAPPDATA%\ClinicReporterAcceptance\case-queue-v1\current.json`. If stopped, run `scripts/start_acceptance.ps1`; the launcher creates a new synthetic run and opens the entry page. Initial four demonstration cases intentionally have missing fields, so the first preview shows zero internally complete/selected cases until reporting data is entered. This preparation is not a live HIS/SMIS deployment.
