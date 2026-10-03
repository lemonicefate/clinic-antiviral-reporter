# Excel exporter

Reserved for immutable export generation from the official workbook. The production path must remain disabled until all relevant M0 gates are evidenced.

The reporting client now exposes a read-only selection and validation preview,
implemented centrally in `service/export_preview.py`. It distinguishes internal
completeness from official exportability and refuses generation/download while
evidence is OPEN, even when the operational flag is true. See
[preview evidence and recovery](../docs/validation/export-preview-progress.md).
The actual immutable workbook generator remains a later, evidence-gated slice.
