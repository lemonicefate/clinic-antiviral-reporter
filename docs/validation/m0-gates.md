# M0 validation gates

Production Excel export stays disabled until every blocking item below has dated evidence, reviewer identity, synthetic fixtures where applicable, and a linked issue.

Tracking issue: [#3 — M0 external HIS, SMIS, authorization, and operations validation](https://github.com/lemonicefate/clinic-antiviral-reporter/issues/3).

## HIS on-device evidence

- [ ] Validate `(RELKEY, SYS_2015)` as the stable order-item key, including reuse and null behavior. `HIS-pro` documents and uses both, but live reuse/null evidence is still required.
- [ ] Verify live registration `TREAT` transitions (`Y` complete, `C` cancelled, `N` not seen) and identify order-level amendment behavior.
- [x] Limit the reporting date to a calendar date without time-of-day (owner confirmation, 2026-10-02); the authoritative source date field remains to be verified.
- [x] Read HIS `總量` directly from `CH012M1.USE_TAMT`; do not derive it from other dose fields or parse it from `PRICE1` (owner live inspection, 2026-10-02).
- [ ] Validate the `USE_TAMT` unit, decimal rules, official-unit conversion, and partial-dispensing behavior.
- [x] Ignore DBF rows marked deleted as a product rule (owner confirmation, 2026-10-02); quarantine surviving orphan children instead of restoring or mutating HIS data.
- [ ] Verify CP950/Big5 decoding, partially written records, DBF/FPT/CDX locking, retry, and safe scan load. Measure fresh uncached visibility separately from the configured periodic-scan delay; the owner expects committed writes to be immediately readable.

## Mapping evidence

- [x] Validate the clinic-to-NHI mapping for Eraflu: `CH012M1.MED1 = ERA` → `H_INV.ITEMN = ERA` → `H_INV.LABNUM = A059653100`; cross-check against the rightmost 10 characters of `CH012M1.PRICE1` (owner confirmation, 2026-10-02).
- [ ] Map NHI code `A059653100` to the exact official SMIS material code and validate mismatch/quarantine behavior with synthetic data.
- [ ] Record effective dates and the owner of each mapping.

## Official outpatient export evidence

- [x] Confirm the supplied workbook is accepted for outpatient import despite the `住院病患` sheet name (owner-confirmed successful SMIS upload, 2026-10-02).
- [ ] Record mandatory and conditional outpatient fields from an authoritative source or a de-identified accepted/rejected test matrix.
- [ ] Validate exact codes, dose/quantity units, date/string formatting, formula-injection defenses, and leading zeros.
- [ ] Use synthetic data to test multiple lots, subsequent doses, duplicate upload, correction, and partial platform results.
- [x] Complete an actual accepted SMIS outpatient import (owner confirmation, 2026-10-02).
- [ ] Retain a de-identified import result report and repeat with repository-controlled synthetic data.

## Operational evidence

- [ ] Confirm proxy-operation and certificate authorization with the competent authority/SMIS owner.
- [x] Use the current dedicated PC as the central host and keep its local state directory configurable (owner confirmation, 2026-10-02).
- [ ] Confirm the central Windows account, firewall/network configuration, authorized devices, and revocation procedure. The deployment HIS source is owner-confirmed as a private configurable UNC path.
- [ ] Provision a dedicated off-host backup share on the HIS computer, separate from the HIS data share; record its exact path in private configuration and demonstrate hourly RPO plus a successful restore.
- [ ] Record the explicit go-live timestamp and test outage-interval rescanning plus `系統外已完成` handling.
