# Implementation domain rules

Use `CONTEXT.md` as the canonical glossary. This document defines invariants that code, commands, APIs, and tests must preserve.

## Case and source invariants

- One verified stable HIS order item creates one report case. The candidate source key `(RELKEY, SYS_2015)` remains an M0 gate until validated on the live HIS.
- A source refresh appends a source snapshot. It never overwrites human-entered reporting data or a prior export snapshot.
- Orphaned, unparseable, partially written, or otherwise suspect HIS rows enter quarantine with retry metadata. They are visible only to reporting and administrative capabilities.
- A case is not merged merely because patient, date, encounter, drug, or course appears equal.

## Command contract

- Every mutation is a typed case command carrying `requestId` and `expectedRevision`.
- Reusing a `requestId` returns the first command result without applying the mutation again.
- A stale `expectedRevision` returns a conflict containing the current revision and field-level differences. Last-write-wins is not an allowed recovery.
- A successful state change and its audit event commit in the same SQLite transaction.
- Device capability authorizes commands; selected operator identity attributes work for filtering and audit but does not grant capability.

## Reporting and export invariants

- One MVP case records one dispensing event. Multiple physical lots are allocations inside that case, and their quantities must sum to the verified reported quantity.
- For Eraflu, preserve integer `CH012M1.USE_TAMT` as source capsule quantity. Reported quantity initially equals it; reporting staff may auditably replace it with the smaller actual dispensed quantity without changing the source snapshot.
- Creating a production export first freezes the included case revisions and item rows. Generation then starts from the unmodified official template, reopens and validates the file, computes its digest, and only then marks that export version ready.
- A ready export moves included, not-yet-uploaded cases to the pending-upload view. Regeneration voids the superseded version; it never overwrites it.
- Changing a case after an upload declaration requires a reason and produces a correction version. It never changes prior export or platform history.
- Platform results are recorded per case/export item. Batch status is a projection of those results, not an independently editable success flag.
- Production export is feature-gated off until the M0 outpatient-template and SMIS import evidence is complete.

## Outage invariant

When the central service is unavailable, clients hold no patient data for later use and allow no view, edit, queue, sync, or export operation. Staff use the approved paper workflow. After recovery, an administrator rescans the outage interval and may end the resulting case as `系統外已完成`; this terminal result remains distinct from exclusion and platform confirmation.
