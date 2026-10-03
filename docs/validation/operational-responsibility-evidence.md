# Operational responsibility and authorization evidence — issue #24

Status: **OPEN**. This document is a private-evidence handoff template for the
clinic owner, competent authority, SMIS owner, and independent reviewer. It does
not grant authorization, certify a professional role, or enable production
export. Complete it only with dated, de-identified evidence from the approved
clinic environment.

Use this record with [#24 — confirm operational responsibility and
authorization](https://github.com/lemonicefate/clinic-antiviral-reporter/issues/24),
[#3 — M0 external validation](https://github.com/lemonicefate/clinic-antiviral-reporter/issues/3),
and [the M0 gate checklist](m0-gates.md). Keep the completed copy outside Git;
the repository should contain only this blank template and links to redacted
evidence by hash or private reference.

## Evidence boundary

- Use roles and redacted reference IDs, never names, usernames, passwords, PINs,
  tokens, certificate private keys, patient identifiers, or real HIS rows.
- Record the environment, date, timezone, and decision owner. A software test,
  synthetic acceptance run, or operator claim cannot substitute for authority
  confirmation.
- Keep certificates, account details, policy documents, screenshots, logs, and
  backup copies in the approved private evidence store. Attach only a redacted
  summary and hashes to a public issue.
- Leave an item `OPEN` when the authority is unavailable, the wording is
  ambiguous, or the evidence covers only a synthetic environment.

## Required confirmations

An authorized owner must provide a dated answer for every row. The answer may be
`CONFIRMED`, `REJECTED`, or `OPEN`; a rejection is evidence that requires a
documented corrective decision, not permission to infer a replacement rule.

| ID | Responsibility or authorization question | Required confirmer | Required evidence | Status |
|---|---|---|---|---|
| O01 | Is proxy operation for the approved SMIS workflow authorized? | Competent authority or SMIS owner | Role, environment, scope, date, and redacted authorization reference | `OPEN` |
| O02 | Is the HTTPS certificate and hostname authorization confirmed? | Certificate/network owner and, where required, competent authority | Approved hostname/scope, certificate owner, renewal owner, expiry/rotation procedure, and redacted reference | `OPEN` |
| O03 | Who is responsible for validating actual lot, quantity, unit, and dispensing values before submission? | Clinic reporting lead and responsible professional owner | Role-based responsibility statement and reviewer sign-off rule | `OPEN` |
| O04 | Who performs the professional review and who may approve a correction or exclusion? | Responsible physician or other clinic-authorized professional owner | Role separation, approval boundary, and escalation path | `OPEN` |
| O05 | What is the approved paper fallback during a central outage? | Clinic administrator and responsible professional owner | Dated procedure, controlled form/version, storage owner, and later reconciliation owner | `OPEN` |
| O06 | How are outage-period records reconciled after service recovery? | Clinic administrator or delegated recovery owner | Rescan range, `系統外已完成` decision owner, duplicate prevention, and review procedure | `OPEN` |
| O07 | What retention category and period applies to cases, source snapshots, decisions, exports, platform results, audit, logs, and backups? | Records owner and clinic administrator | Owner-confirmed policy reference and disposal approval role; use ADR 0006's seven-year baseline as the repository starting point and confirm the final legal category before go-live | `OPEN` |
| O08 | Who can revoke a device or service credential, and how is the action verified? | Clinic administrator or security owner | Authorized role, revocation trigger, notification path, and verification procedure; the physical drill result belongs to #25 | `OPEN` |
| O09 | Who owns deployment, restore, backup-share, firewall, and certificate incidents? | Clinic administrator and infrastructure owner | Operational owner matrix, escalation contacts by role, and approved maintenance boundary | `OPEN` |

## Evidence record template

Copy this block into a private, ignored evidence file for each review. Replace
placeholders with roles and redacted references only.

```text
Repository revision:
Evidence record revision:
Scope / site / environment (if applicable):
Run timestamp and timezone:
Reporting lead role:
Clinic owner or responsible professional role:
Clinic administrator / infrastructure-owner role:
Records-owner role (if applicable):
Competent authority or SMIS-owner role (for O01/O02 only):
Independent reviewer role/date:

Item ID (O01–O09):
Decision: CONFIRMED / REJECTED / OPEN
Observed or documented rule:
Operational scope and boundary:
Evidence reference or hash:
Related M0 gate / issue:
Discrepancy or corrective action:
Owner and due date:
```

## Review and completion

1. The reporting lead prepares the questions and confirms the intended clinic
   workflow without including patient content.
2. Each required confirmer answers only the rows assigned to that role and
   supplies a dated reference. The competent authority or SMIS owner answers
   O01/O02; clinic owners answer O03–O09. A technical test tenant is not required
   for an institutional policy decision.
3. An independent reviewer checks the role boundary, certificate scope, paper
   process, outage reconciliation, retention categories, and revocation path.
   The actual revocation, restore, and outage drills are executed and evidenced
   under #25 after this responsibility record is agreed.
4. Keep every earlier answer and correction as a dated revision. Do not overwrite
   a previous decision or delete an unresolved discrepancy.
5. Only after all applicable rows have a confirmed or explicitly owner-approved
   `not applicable` result should the reviewer attach a redacted summary to #24
   and update the matching boxes in `m0-gates.md`.

This template does not close #24 and does not alter the production export gate.
The central service must continue to use a read-only HIS identity, a separate
backup share, and production export disabled until every independent M0 gate is
evidenced.
