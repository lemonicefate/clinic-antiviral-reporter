# Live HIS read-contract intake — issue #23

Status: **OPEN**. This procedure prepares a private, synthetic-only evidence
manifest for the live HIS owner. It does not read the configured HIS path, copy
DBF/FPT/CDX files, exercise a production account, or change the scanner contract.
Unknown behavior stays `OPEN` until the clinic HIS owner supplies dated,
reviewed evidence.

Use this document with [#23 — validate the live HIS read
contract](https://github.com/lemonicefate/clinic-antiviral-reporter/issues/23),
[#12 — the scanner contract](https://github.com/lemonicefate/clinic-antiviral-reporter/issues/12),
and [the clean-room HIS contract](../integrations/his-read-contract.md). Keep
the completed kit and all raw operational evidence outside Git.

## Safety boundary

- The repository-side kit contains only a manifest and README files. It never
  accepts a HIS source path and never copies a source artifact.
- The clinic measurement must use a read-only Windows identity and read-only
  handles. Do not create, replace, truncate, rename, delete, repair, or restore
  any DBF/FPT/CDX file as part of a test.
- Use only synthetic or irreversibly de-identified records. Keep source paths,
  patient values, credentials, raw files, screenshots, and logs in the approved
  private evidence store. The manifest should contain only an opaque evidence
  reference or hash.
- Measure committed-write visibility separately from the configured periodic
  scanner delay. Do not call a scan interval a database commit guarantee.

## Prepare and validate the private kit

From the repository root, choose a new absolute directory outside the repository:

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_his_contract_intake `
  --output "$env:LOCALAPPDATA\ClinicReporterAcceptance\his-contract-v1"
.\.venv\Scripts\python.exe -m scripts.validate_his_contract_intake `
  --kit "$env:LOCALAPPDATA\ClinicReporterAcceptance\his-contract-v1"
```

The initial result must be `OPEN` with H01–H11 open. The validator rejects a kit
containing a `.DBF`, `.FPT`, or `.CDX` file, a source path, a reparse point, or a
manifest that enables production HIS access. After each private evidence update,
run the validator again. Use `--require-complete` only after every applicable
scenario has a reviewed result; the manifest's top-level `status` remains
`OPEN` and no product gate changes.

## Scenario matrix

| ID | Scenario | Minimum observation |
|---|---|---|
| H01 | Stable key null/reuse/edit | `(RELKEY, SYS_2015)` nullability, reuse, edit behavior, and preserved versions |
| H02 | TREAT transitions and order amendments | `Y`, `C`, `N` transitions and order-level amendment behavior |
| H03 | Date, quantity, and partial dispensing | `CH011M1.SDATE`, integer `CH012M1.USE_TAMT`, and smaller actual dispensing with an audit reason |
| H04 | CP950/Big5 decoding | Encoding result and representative non-ASCII values without source changes |
| H05 | Partial writes and truncated source | Bounded retry or quarantine for incomplete records |
| H06 | Read locks and sharing violations | Read-only lock behavior, backoff bounds, and final safe failure |
| H07 | Committed visibility versus scan delay | Uncached read time after commit measured separately from periodic scan delay |
| H08 | Deleted rows and orphan joins | Deleted rows ignored; surviving orphans quarantined; no source repair |
| H09 | Mapping mismatch and ambiguity | Clinic/NHI mismatch and ambiguous rows quarantined, never inferred |
| H10 | Safe load and retry bounds | Load measurement, retry limits, and recovery without source mutation |
| H11 | Source immutability and handles | Read-only identity cannot create, replace, truncate, rename, or delete source files |

## Required record for each scenario

An authorized HIS owner records only a role, date/timezone, synthetic scenario
identifier, observed result, and opaque private evidence reference. The
independent reviewer records a role and review date. Include the exact source
revision or synthetic fixture revision, but never include a live source path or
raw patient row in the repository or public issue.

For H01–H03, preserve every earlier source version and record the difference
between source facts and reporting data. For H05–H07, record timestamps and retry
counts so committed visibility is not confused with scanner polling. For H08–H11,
record the final quarantine/error and source byte/hash comparison privately.

## Completion and re-triage

1. The HIS owner runs the approved read-only measurements and fills H01–H11 as
   `PASS`, `FAIL`, or owner-confirmed `NOT_APPLICABLE`, with a dated reference.
2. An independent reviewer reconciles the observations with the clean-room
   contract and records every discrepancy; a failure does not authorize an
   inferred replacement rule.
3. Attach only a de-identified matrix and hashes/references to #23. Update the
   affected implementation issue if a key, transition, encoding, lock, or timing
   contract differs from the current documented behavior.
4. Update the matching M0 gate only after the owner and reviewer accept the
   evidence. Keep the production HIS gate and production Excel export disabled
   until all independent M0 evidence is complete.

This kit is an evidence handoff, not a live HIS test harness. The source remains
an immutable external system throughout the measurement.
