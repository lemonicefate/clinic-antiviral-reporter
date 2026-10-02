# HIS read contract

This is the clean-room contract for the central HIS adapter. It records behavioral knowledge reviewed from the private `HIS-pro` checkout at commit `f5859f3d67416febb250658107ccfad8be6510c6` and the clinic owner's confirmations on 2026-10-02; it contains no copied implementation or patient data.

## Safety interface

The HIS adapter accepts a configured source directory and returns parsed source snapshots or quarantined diagnostics. Its interface exposes no write, repair, delete, rename, move, restore, index-maintenance, or memo-maintenance operation.

- Open DBF/FPT/CDX only through read-only handles under a Windows identity with share and NTFS read-only permission.
- Perform availability checks through metadata and read operations only. Never test access by creating, renaming, replacing, truncating, or deleting a file.
- Preserve raw identifiers and values in the central snapshot before normalization. Write all application state only beneath the central state directory.
- Ignore DBF records marked deleted. If a non-deleted child has no parent, quarantine and retry it; never repair the HIS source.
- Read without the private project's cache. The owner expects a fresh uncached read to see a committed HIS write immediately; the periodic scanner can add up to its configured interval before detection. Measure both separately. Retry sharing violations with bounded backoff and quarantine persistent parsing failures.

## Reviewed schema relationships

The following fields are candidates documented by the reviewed HIS schema material. This project defines and validates its own minimal read allowlist; unresolved candidates do not become implementation requirements merely by appearing here.

| Source | Documented candidate fields | Relationship |
|---|---|---|
| `PD011M1` patient master | `NUM`, `NAME`, `SEX`, `BIRTH`, `ID` | Patient data is located by internal patient key `NUM`. |
| `RG011M1` registration | `NUM`, `SYS_2015`, `RELKEY`, `CCDATE`, `TETDAY`, `CCTIME`, `CCDOC`, `TREAT` | `NUM` links the patient; `RELKEY` connects registration to clinical data. Documented `TREAT` values are `Y` complete, `C` cancelled, and `N` not seen; transition timing and order-level amendments remain `OPEN`. |
| `CH011M1` encounter | `RELKEY`, `NUM`, `SDATE`, `DOC`, `DR_NAME`, `DR_ID`, `DRUG_ID`, `DRUG_NAME` | `RELKEY` links the encounter to order items; `NUM` links the patient. `SDATE` is the confirmed reporting date and is stored without time-of-day. |
| `CH012M1` order item | `RELKEY`, `SYS_2015`, `MED1`, `DESC1`, `PRICE1`, `USE_TAMT`, `USE0`, `USE1`, `USE_DAY1`, `U1`, `PATH1`, `SDATE1` | Preserve `(RELKEY, SYS_2015)` as the candidate stable item identity. `MED1` is the internal item code and links the item master. `USE_TAMT` is the clinic-confirmed total quantity. The rightmost 10 characters of `PRICE1` carry the NHI code for cross-checking. |
| `H_INV` item master | `ITEMN`, `DESC`, `USETYPE`, `LABNUM` | `ITEMN` corresponds to `CH012M1.MED1`; `LABNUM` is the authoritative NHI code for this clinic. |

`RELKEY` may contain meaningful embedded spaces; preserve the raw value and use trimmed comparison only for the documented join. The exact constructed composition of `RELKEY` is inconsistent in the private documentation, so the public adapter must never synthesize it.

## Product selections

- Select the target through the owner-confirmed mapping `CH012M1.MED1 = ERA` → `H_INV.ITEMN = ERA` → `H_INV.LABNUM = A059653100`. Here `ERA` is the internal item code and `A059653100` is the NHI code for publicly funded Eraflu (`易剋冒`).
- Treat `H_INV.LABNUM` as the authoritative NHI code. Compare it with the rightmost 10 characters of `CH012M1.PRICE1` as a consistency check; preserve the code as text, and quarantine a mismatch instead of silently choosing either value.
- Export the official SMIS material value exactly as `DDMTR2018090002:易剋冒膠囊(顆)`. Preserve both code and full label as text; do not substitute the NHI code or an abbreviated display name.
- Read the reporting date from `CH011M1.SDATE` and preserve only year, month, and day; do not invent a time-of-day.
- Read the HIS `總量` directly from `CH012M1.USE_TAMT` as an integer number of capsules. Preserve it as source quantity. Initialize reported quantity from it, then allow reporting staff to record a smaller actual dispensed quantity with an audited reason; do not derive total quantity from other dose fields or parse it from `PRICE1`.
- For `RG011M1.TREAT`, create normal work for `Y`. Retain and flag `C` as `HIS 異動待確認`. If an `N` registration nevertheless has an order, quarantine it for review. A person makes the final exclusion decision; the adapter never deletes a case automatically.
- Treat the Eraflu mapping as effective from the explicit MVP go-live timestamp until superseded. The administrator owns mapping maintenance.

## Remaining field evidence

1. Verify `(RELKEY, SYS_2015)` nullability, reuse, and behavior across edits/cancellations. Existing implementation is precedent, not live evidence.
2. Verify live `TREAT` transitions and identify order-level amendment behavior without relying on deleted-row restoration.
3. Exercise `CH011M1.SDATE`, integer `USE_TAMT`, partial dispensing, and audit behavior with synthetic data.
4. Measure sharing violations, partial-write behavior, and time from committed HIS write to an uncached reader result.

## Runtime configuration

`CLINIC_REPORTER_HIS_SOURCE_PATH` supplies the deployment UNC path through ignored central-service configuration. The path never enters OpenAPI or Tauri configuration. The backup root is independently configured and must use a different SMB share name, even on the same server; a sibling directory under the HIS share is rejected.
