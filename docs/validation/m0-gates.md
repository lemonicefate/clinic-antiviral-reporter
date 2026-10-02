# M0 validation gates

Production Excel export stays disabled until every blocking item below has dated evidence, reviewer identity, synthetic fixtures where applicable, and a linked issue.

## HIS on-device evidence

- [ ] Validate `(RELKEY, SYS_2015)` as the stable order-item key, including reuse and null behavior.
- [ ] Capture cancellation and amendment markers and their transitions.
- [ ] Validate prescription/dispensing timestamps and timezone precision.
- [ ] Validate quantity semantics, units, conversions, and partial dispensing.
- [ ] Determine whether deleted DBF rows must be read and how they represent business changes.
- [ ] Verify encoding, partially written records, DBF/FPT/CDX locking, refresh delay, retry, and safe scan load.

## Mapping evidence

- [ ] Validate clinic order code → NHI code → official material code for every enabled antiviral.
- [ ] Record effective dates and the owner of each mapping.

## Official outpatient export evidence

- [ ] Obtain or formally confirm the outpatient-applicable official workbook and mandatory/conditional fields.
- [ ] Validate exact codes, dose/quantity units, date/string formatting, formula-injection defenses, and leading zeros.
- [ ] Use synthetic data to test multiple lots, subsequent doses, duplicate upload, correction, and partial platform results.
- [ ] Complete an actual SMIS outpatient import with synthetic data and retain a de-identified result report.

## Operational evidence

- [ ] Confirm proxy-operation and certificate authorization with the competent authority/SMIS owner.
- [ ] Confirm the central Windows account, HIS read-only account/path, firewall/network configuration, authorized devices, and revocation procedure.
- [ ] Confirm the off-host backup destination; demonstrate hourly RPO and a successful restore.
- [ ] Record the explicit go-live timestamp and test outage-interval rescanning plus `系統外已完成` handling.
