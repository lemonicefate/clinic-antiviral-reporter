# MVP acceptance traceability matrix

Status date: 2026-10-03. This matrix traces SPEC v1.0 section 11 and the
authoritative v1.1 section 9 additions. `PASS` means the complete stated scenario
has reproducible repository evidence. `PARTIAL` identifies the exact remaining
clause. `BLOCKED` means the scenario depends on named external evidence and must
not be inferred from nearby tests.

All test data referenced here is synthetic. Production HIS reading and Excel
export remain disabled. The current full Python discovery passes 128 tests; client,
browser, Rust and native Windows evidence is recorded in the linked progress files.

| # | Status | Reproducible evidence | Remaining evidence |
|---|---|---|---|
| 1 | PASS (synthetic) | `tests.test_scanner.ScannerTest.test_periodic_file_scan_runs_without_client_and_preserves_source_bytes`, `tests.test_cases.SyntheticQueueTest.test_exact_chart_lookup_crosses_physicians_without_granting_refresh`, `client/e2e-real/case-queue.cjs` | Live clinic timing and identities remain #23. |
| 2 | PASS (synthetic) | `test_refresh_keeps_same_day_orders_distinct_and_retry_survives_restart`, `test_raw_key_boundaries_remain_distinct_cases`; duplicate warning in the real HTTPS queue journey | Candidate live key behavior remains #23. |
| 3 | PASS (synthetic) | Periodic scanner test above plus queue unfinished/overdue assertions documented in [case queue](case-queue-progress.md) | Live unattended-host evidence remains #25. |
| 4 | PASS (synthetic) | `test_reason_requires_patient_confirmation_and_records_exact_option_once`, `test_dispensing_preserves_source_and_requires_exact_lot_totals`, case history and audit assertions; reason/reporting browser journeys | Clinic attribution remains an operator claim, as required. |
| 5 | PARTIAL | `test_dispensing_preserves_source_and_requires_exact_lot_totals` proves 6+4 acceptance and 6+3 refusal; reporting browser journey repeats it | Official multi-lot Excel row behavior is OPEN in #15/#16. |
| 6 | PASS (synthetic) | `test_bulk_lots_remain_independent_and_exclusion_retains_history`, bulk/individual real HTTPS reporting journey | None for the software behavior. |
| 7 | PARTIAL | `test_dispensing_preserves_source_and_requires_exact_lot_totals` proves source 10 remains while reported 5 is audited | Actual exported dose/unit value is blocked by #15/#16. |
| 8 | PARTIAL | `test_source_changes_preserve_reporting_and_require_explicit_review`, `test_source_refresh_blocks_preselection_without_overwriting_verified_reporting`, source-review journey | Export-history preservation cannot be exercised until #16 creates export versions. |
| 9 | PASS (synthetic) | `test_bulk_lots_remain_independent_and_exclusion_retains_history`, `test_manual_selection_exclusion_and_date_range_are_checked_centrally` | None for the software behavior. |
| 10 | PARTIAL | `test_eighteen_complete_cases_are_preselected_but_official_export_remains_blocked` proves 18 selected and 2 unfinished; export-preview browser journey | Producing the selected workbook is intentionally blocked by #15/#16. |
| 11 | BLOCKED | Existing preview refuses generation/download and retains all current human history | Immutable export/regeneration/upload history requires #16–#18. |
| 12 | BLOCKED | No platform success state is fabricated | 18 declarations, 16 confirmations, remaining work and repeat warning require #17/#18. |
| 13 | PASS (synthetic) | `client/e2e-real/outages.cjs`, scanner recovery/dedup tests and late-response clearing documented in [outage recovery](outage-recovery-progress.md) | Clinic outage drill remains #25. |
| 14 | PASS (synthetic) | Device authorization/revocation tests, trusted/untrusted TLS test, Rust Credential Manager test, ignored synthetic artifacts and [device evidence](device-session-progress.md) | Fleet/network acceptance remains #25. |
| 15 | BLOCKED | The official workbook is pinned byte-for-byte and its sheets/code value are tested | Synthetic SMIS import and de-identified report require #15/#26. |
| 16 | PASS (synthetic) | `test_reporting_revision_conflict_does_not_overwrite_first_reason`, mapping/source/bulk conflicts and real two-client browser journeys | None for current mutation surfaces. |
| 17 | PASS (synthetic) | Device, reason, scanner, mapping, backup and release replay tests verify one mutation/audit and the original result across restart | Future export/result commands must retain the same invariant. |
| 18 | BLOCKED | Backup/release publication tests demonstrate the repository's general pending→ready pattern, but are not Excel evidence | Export generation, reopen validation and hash interruption require #16. |
| 19 | PASS (synthetic) | `test_pairing_does_not_grant_operator_claimed_authority_and_revocation_is_immediate`, expired-session and release-revocation tests | Actual device drill remains #25. |
| 20 | PASS (synthetic Windows) | Rust signature/cache tests and `scripts.check_signed_updates` exercise corrupt, truncated and disconnected downloads, confirmation, exact upgrade/rollback and central-offline recovery; see [desktop release evidence](desktop-release-progress.md) | Clinic deployment acceptance remains #25. |
| 21 | PASS (synthetic) | Explicit recovery scans, no duplicate cases, terminal `系統外已完成`, outage clearing and reconnect are covered in scanner/API and real HTTPS browser tests | Approved paper-process drill remains #24/#25. |
| 22 | BLOCKED | Post-upload state is not invented or carried into current cases | Required reason, correction versions, old results and new per-item aggregation require #17/#18 plus official behavior from #15. |

## Cross-cutting checks for #22

- Generated OpenAPI and TypeScript bindings are committed and checked for drift in
  CI; API changes must regenerate both.
- `tests/test_migration.py` covers v1 through v10 into the current v11 schema and
  refuses future schemas without changing bytes. Feature-specific progress files
  state recovery boundaries and preservation rules.
- [Backup evidence](backup-recovery-progress.md) verifies restart, incomplete
  publication handling, immutable artifact inventory, isolated restoration and
  expired restored sessions.
- Client patient state remains memory-only and is unmounted on outage. Native
  persistent state is limited to endpoint/device identity, updater state and
  non-patient preferences. `.gitignore` excludes credentials, logs, DBF-family
  sources, generated workbooks, backups and local acceptance artifacts.
- The preserved official workbook integrity tests prove the fixture is unchanged;
  they do not prove platform acceptance.

## Current blocking chain

```text
#15 official synthetic export/correction contract
  → #16 immutable synthetic export version
    → #17 upload declarations and per-item results
      → #18 correction/repeat workflow
        → #22 complete synthetic acceptance
          → #26 actual synthetic SMIS readiness report
```

The executable intake for the still-open #15 evidence is
[official-export-contract-intake.md](official-export-contract-intake.md). It
keeps the official questions and observed scenario results separate from the
repository's synthetic preview tests. The private kit preparer and read-only
validator preserve the template hash and keep all S01–S12 results `OPEN` until
authorized SMIS evidence is supplied; no production export is enabled by
completing the repository side alone.

#21 additionally awaits the prepared tray/sign-in human check. Live HIS (#23),
authorization (#24), and operational deployment/restore (#25) remain independent
M0 evidence. Passing repository tests never closes those gates.
