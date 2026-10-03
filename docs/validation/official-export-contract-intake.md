# Official SMIS export contract intake — issue #15

Status: **OPEN**. This checklist captures the evidence still needed from an
authorized SMIS owner before the repository can claim an official export
contract. It is deliberately an intake record, not an implementation of
unknown platform rules.

Use this document with [#15 — establish the official synthetic SMIS test
contract](https://github.com/lemonicefate/clinic-antiviral-reporter/issues/15),
then attach a dated, de-identified result to [#26 — verify actual synthetic
SMIS import and production readiness](https://github.com/lemonicefate/clinic-antiviral-reporter/issues/26).
The immutable export work in [#16](https://github.com/lemonicefate/clinic-antiviral-reporter/issues/16)
must remain blocked until the relevant rows have an observed result.

## Evidence boundary

- Use only repository-controlled synthetic records. Every identifier must be
  obviously synthetic, for example `SYN-PT-001`, `SYN-ORDER-001`, and
  `SYN-REPORT-20261003`; never use a real patient, chart, national ID, phone
  number, address, credential, or copied HIS row.
- The official workbook fixture at
  `tests/fixtures/official/smis/template.xlsx` is preserved byte-for-byte.
  Copy it to a private temporary directory before any manual work and record
  its SHA-256. Never edit, replace, or commit the repository fixture.
- The outpatient workbook has already been accepted despite its
  `住院病患` worksheet name. Treat that as existing evidence; do not reopen
  the accepted sheet-name question or infer any other field rule from it.
- Production Excel generation and download remain disabled. A successful
  repository preview, a locally opened workbook, or an accepted historical
  upload does not complete this intake.
- Keep generated workbooks, SMIS result files, logs, screenshots, private
  account details, and backup copies outside Git. If a screenshot is needed,
  it must show synthetic values only. Prefer a redacted structured result
  table over a screenshot.

## Required participants and evidence

| Participant | Responsibility | Required record |
|---|---|---|
| Reporting lead | Defines the clinic scenario and confirms the selected synthetic cases/items | Name or role, date, scenario IDs, and signed/reviewed result |
| Authorized SMIS operator | Performs the upload in a permitted test account and records the platform response | Operator role, platform/environment, timestamp with timezone, import or batch identifier, per-item result |
| SMIS owner or authority contact | Confirms which observed behavior is the official contract | Dated confirmation or an authoritative document reference; unresolved behavior stays `OPEN` |
| Independent reviewer | Reconciles the source, workbook, platform result, and hashes | Reviewer identity/role, review date, discrepancies and disposition |

Do not put a person’s credential or a real identifier in the repository or in a
GitHub issue. The public issue needs only the de-identified matrix, hashes of
synthetic artifacts where useful, and the reviewer/date fields.

## Questions that must be answered by observation

Ask the SMIS owner to answer each question with an accepted/rejected result,
the exact platform message or documented rule, and the artifact or import ID
that supports it. Do not fill an answer from a nearby HIS or workbook field.

| Contract area | Question to test | Evidence to retain | Status |
|---|---|---|---|
| Mandatory fields | Which fields are mandatory for an outpatient antiviral declaration? Which are conditional, and what activates each condition? | De-identified accepted and rejected records plus the field-level error/result | `OPEN` |
| Codes and labels | What exact code, label, and code/label pairing does SMIS require for the medication, clinic, dose, unit, result, and reason fields? | Redacted field/value table and owner confirmation | `OPEN` |
| Types and formatting | Which values must remain text? Are leading zeros preserved? What date format, timezone, decimal/negative rules, whitespace, and character set are accepted? | Input/output values and import result for each boundary value | `OPEN` |
| Dose and quantity | Does quantity mean the HIS total, the actually dispensed amount, or another value? Which dose and unit are valid for Eraflu? | Synthetic quantity cases, exact platform response, and reviewer reconciliation | `OPEN` |
| Multiple lots | Are two or more lots represented as separate rows, fields, or another structure? Must lot totals equal the reported quantity? | Valid `6 + 4` case and invalid `6 + 3` case with observed results | `OPEN` |
| Subsequent dose | How is a continuation or subsequent dose identified, and which fields change from the first declaration? | Separate synthetic first/subsequent records and result | `OPEN` |
| Duplicate upload | What happens when the same declaration is uploaded again? Is it rejected, ignored, merged, or assigned a new import? | First and exact-repeat import IDs/results | `OPEN` |
| Correction | What is the supported correction sequence after an accepted declaration? Does the old result remain visible and immutable? | Original, correction, and platform history/result references | `OPEN` |
| Partial results | Can a batch contain mixed success and failure? Are results available per item, and how are retryable items identified? | Mixed batch result, item statuses, and retry guidance | `OPEN` |
| Foreign/special identifiers | What is accepted for synthetic foreign identifiers and special fields? Are punctuation, Unicode, embedded spaces, and blank/unknown markers allowed? | Synthetic boundary values and field-level responses | `OPEN` |
| Formula/string safety | When a value begins with `=`, `+`, `-`, or `@`, does the generated workbook preserve it as text and does SMIS reject or accept it safely? | Workbook cell type/value plus platform response; never use executable content | `OPEN` |
| Workbook shape | Which worksheet, columns, row order, header spelling, and version are required? | Template hash, sheet/column inventory, and owner confirmation | `PARTIAL`: outpatient acceptance and `住院病患` name are already confirmed |

The formula/string cases use harmless synthetic strings only. Do not place a
formula that reads files, calls a URL, or executes a command in a workbook.

## Synthetic scenario matrix

Create one deterministic input set per row, or a deterministic batch where the
platform's item-level result is retained. The `Observed result` and `Evidence`
columns must stay blank until an authorized operator has run the scenario.

| ID | Synthetic scenario | Minimum input | Expected evidence to record | Observed result | Evidence |
|---|---|---|---|---|---|
| S01 | Complete baseline | One outpatient declaration, one lot, valid mapped medication, date, dose, quantity, and unit | Import ID, accepted item status, exact values echoed by SMIS | `OPEN` | |
| S02 | Missing mandatory field | Copy S01 and remove one candidate mandatory field at a time | Field-level rejection, or owner confirmation that the field is conditional | `OPEN` | |
| S03 | Valid multiple lots | Total 10 with lot allocations `6 + 4` | Whether the import accepts the representation and preserves both lots and total | `OPEN` | |
| S04 | Invalid multiple-lot total | Total 10 with allocations `6 + 3` | Rejection reason or documented normalization; no silent correction | `OPEN` | |
| S05 | Subsequent dose | Synthetic continuation record linked only to synthetic prior record | Required linkage/flag, accepted fields, and whether it counts separately | `OPEN` | |
| S06 | Exact duplicate | Upload S01 again without changing bytes or values | Duplicate policy, second import ID if any, and old-result preservation | `OPEN` | |
| S07 | Correction | Correct one value in an accepted S01 record using the supported workflow | Correction linkage, old/new result visibility, and immutable history | `OPEN` | |
| S08 | Partial batch result | Batch of 18 synthetic items with 16 intentionally valid and 2 intentionally invalid items | Per-item statuses, retryable subset, batch status, and reconciliation count | `OPEN` | |
| S09 | Foreign/special identifiers | Synthetic foreign-ID marker, punctuation, Unicode, embedded spaces, and blank/unknown boundary values | Accepted representation or exact field-level rejection for each value | `OPEN` | |
| S10 | Leading zeros and dates | Text value such as `000123`, fixed synthetic date, and boundary date/string values | Whether leading zeros and date text remain exact through workbook and import | `OPEN` | |
| S11 | Formula-like strings | Values beginning with `=`, `+`, `-`, and `@`, escaped as text by the generator | Workbook cell type/value and safe SMIS result; no formula execution | `OPEN` | |
| S12 | Complete reconciliation | Reconcile the selected cases, workbook rows, platform item results, and totals | Reviewer sign-off that every input has one traceable result and no hidden row | `OPEN` | |

The matrix does not prescribe whether a scenario should pass. An observed
rejection is valid evidence when the platform owner documents the rule and the
software records it as a contract. An unexplained response remains `OPEN`.

## Execution procedure

1. Prepare a private intake kit outside Git. From the repository root, run
   `python -m scripts.prepare_smis_contract_intake --output
   "<absolute-private-directory>"`. The command copies the preserved template,
   records its SHA-256, creates the S01–S12 `OPEN` manifest, and refuses output
   paths inside the repository or over an existing directory. It does not create
   a workbook row, contact HIS, or submit to SMIS.
2. Confirm that the operator is authorized to use the SMIS test or approved
   environment, and record the environment name and timezone without recording
   credentials.
3. Check out the repository revision under test. Generate the synthetic input
   from repository-controlled data; do not read the configured HIS directory,
   use a real patient, or copy a production export.
4. Copy the official template to a new scenario-specific artifact in the private
   kit. Record
   the source template hash, generated input hash, and generated workbook hash
   before upload. Keep the original bytes for every retry; never overwrite an
   accepted artifact.
5. Upload each scenario through the authorized SMIS workflow. Record the
   timestamp, operator role, scenario ID, import/batch ID, overall status,
   per-item status, exact error/result text, and whether a retry or correction
   was requested.
6. For S06 and S07, preserve the original import/result alongside the repeat or
   correction. Do not replace the first result or call a corrected file the
   original version.
7. Export or transcribe only the de-identified result needed for review. Remove
   names, national IDs, addresses, credentials, session tokens, and unrelated
   rows. Store the private raw evidence outside Git and attach only the
   redacted matrix or a hash/reference in the issue.
8. Have the independent reviewer reconcile every scenario against the hashes,
   row counts, quantities, lots, and platform item statuses. Record all
   mismatches as `OPEN`; do not repair the evidence by editing the source.
9. If SMIS behavior is unavailable, ambiguous, or differs between runs, stop
   the scenario at that boundary, preserve the response, and create or update
   a needs-info issue. Do not enable production export or infer a rule.

## Evidence record template

Copy this block into a private, ignored evidence file for each run. Replace
placeholders with synthetic values only.

```text
Repository revision:
Template SHA-256:
Generated input SHA-256:
Generated workbook SHA-256:
SMIS environment/test tenant:
Operator role:
Run timestamp and timezone:
Reviewer role/date:

Scenario ID:
Synthetic case/item IDs:
Import or batch ID:
Overall result:
Per-item result:
Exact platform message:
Retry/correction reference:
Redacted artifact reference/hash:
Open questions or discrepancies:
```

## Completion and re-triage

The intake is complete only when S01–S12 have a documented observed result or
an explicit owner-confirmed `not applicable` decision, S12 reconciles all rows,
and the independent reviewer signs the record. Then:

1. Attach the de-identified matrix and reviewer/date evidence to #15 and link
   the private artifact location by hash only.
2. Update [m0-gates.md](m0-gates.md) for mandatory/conditional fields,
   formatting, quantity/lots, subsequent/duplicate/correction/partial results,
   and retained import report. Keep a checkbox unchecked when the evidence is
   incomplete.
3. Update #16 with the exact accepted contract and template hash before
   implementing immutable export generation. Do not copy platform data into
   the repository fixture.
4. Update #26 with the complete de-identified import report and the operator
   and reviewer roles. Only the authorized owner can request a readiness label;
   repository tests alone do not satisfy this gate.
5. Leave the official Excel export feature disabled until the M0 checklist and
   the actual synthetic outpatient import are both evidenced.

This process is reversible: if a platform result is later corrected, retain the
old evidence and add a new dated revision. Never delete an earlier result,
rewrite a source artifact, or treat a later answer as proof that the earlier
behavior did not occur.
