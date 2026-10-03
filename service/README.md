# Central service

Python 3.12/FastAPI central service. Issue #7 is in progress: device/session APIs
and central settings are implemented alongside a Windows device-management client.
Deployment acceptance remains open. The #8 slice adds a synthetic case queue and
detail API. #12 adds an explicitly enabled synthetic-file scanner; no live HIS
reader or production export is enabled. The current schema is v10; see
[backup and isolated restore](../docs/validation/backup-recovery-progress.md) for
backup configuration, recovery procedures, retention and deployment gates, and
[outage recovery](../docs/validation/outage-recovery-progress.md) for administrator
recovery scans, terminal outside completion, migration/rollback and acceptance.
Earlier scanner evidence remains in `docs/validation/scanner-progress.md`.

## Development

From the repository root on Windows:

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m unittest discover -s tests -v
.venv/Scripts/python -m mypy --check-untyped-defs service scripts
.venv/Scripts/python -m scripts.generate_openapi
```

From `client`, run `npm ci`, `npm run generate:api`, and `npm run typecheck`.
The versioned OpenAPI and generated TypeScript types are committed; regenerate
both after API edits. CI detects drift. API generation opens no state/source files.

## Mapping activation (#13)

Administrator devices configure the confirmed mapping through `/api/v1/mappings`
and the client mapping page. No deployment timestamp is seeded. Date-only sources
require an explicit timezone-bearing clinic-midnight effective boundary. The first
mapping fixes the initial scan start date; later versions preserve that boundary
and prior mapping/snapshot history. Synthetic file scanning waits for this setup.
`HIS_SCAN_FROM_DATE` is now a deprecated optional input, not the scan-range authority.
See [acceptance and recovery notes](../docs/validation/mapping-progress.md) and
[operator steps](../docs/validation/mapping-manual.md). Production gates remain closed.

## Runtime and initial device

Use the prefixed variables documented in the root example configuration. No file
is discovered implicitly; `--env-file` must name an existing absolute path. Process
environment values override that file. Keep production settings and credentials
outside Git in an ACL-protected location. Set the central Windows identity's HIS
share and NTFS rights read-only and backup share rights separately.

While the service is stopped, initialize the first administrator:

```powershell
.venv/Scripts/python -m service --env-file C:\ProtectedReporter\runtime.env provision --name InitialAdmin
```

The command prompts without echo for a freshly generated 32-byte random device
key encoded as 43 base64url characters without padding. It does not generate or
print a secret. Central storage keeps only its SHA-256 digest. Do not place device
keys in command arguments, shell history, logs, documentation, or Git. Import the
key through the desktop initial-device form; the native process stores it in Windows
Credential Manager. Provisioning cannot run while the
service owns the state directory or initialize a second administrator.

Start the HTTPS listener with the central certificate and key:

```powershell
.venv/Scripts/python -m service --env-file C:\ProtectedReporter\runtime.env serve --cert C:\ProtectedReporter\central.crt --key C:\ProtectedReporter\central.key
```

Use a certificate trusted by the managed clients. HTTP is rejected, proxy headers
are not trusted, access logging is disabled, and only one worker is allowed by the
entry point. The OS ownership lock also rejects a second independent process.
Synthetic real-listener tests verify trusted and untrusted TLS. Actual clinic
firewall/network/certificate provisioning and native connection remain M0 work.

Every protected request carries the individual device key as a Bearer credential;
session-bound operations also carry `X-Session-Id`. A session's operator is an
attribution claim, never authorization. Sessions expire after eight hours and every
request rechecks device revocation. Administrators issue single-use pairing codes
with a ten-minute lifetime and chosen capabilities. The last administrator cannot
be revoked until another administrator has been paired. Codes also become unusable if
their issuing device is revoked. Pairing responses are sensitive; keep them private.

All mutation envelopes contain `requestId` and `expectedRevision`. New sessions,
pairings, and devices expect revision zero. Revocation uses the device's displayed
revision. Command results, state, and audit are stored in one transaction. The audit
read API requires an administrator device; there is no audit edit/delete API.

## Schema and recovery

SQLite user_version 1 introduces devices, sessions, command results, and audit;
version 2 adds pairing grants; version 3 adds synthetic ingestion state, separate
report cases, and retained source snapshots. Migration runs under exclusive service ownership.
The service rejects a database from a newer schema. Tests use isolated temporary
state, exercise a cold restart and v1-to-v2 migration, and verify ownership rejection,
retry history, and unchanged database bytes when refusing a newer schema. A synthetic
SQLite audit-write failure verifies enrollment and pairing-consumption rollback.

Before deploying any new service version, stop the service and retain a consistent,
protected backup of the entire state directory and its private runtime settings.
Do not downgrade by deleting tables or clearing audit/command history. If a binary
cannot read the migrated schema, keep that state intact and use the compatible
binary until a reviewed forward fix is available. Restoring an old backup must
reconcile subsequent work; it is not a silent rollback of human decisions. Automated
off-host backup/restore and production migration drills remain in #20 and #25.

The settings loader performs no HIS I/O. It rejects relative/device-namespace paths,
path traversal, equal HIS/backup share names, production placeholders/documentation
addresses, wildcard listeners, and backup intervals above an hour. The export flag
is only an operational setting, not evidence or authorization to export; no export
implementation exists in this checkpoint.

## Synthetic case queue

`CLINIC_REPORTER_SYNTHETIC_ENABLED=true` explicitly enables fixed test samples in
development; production rejects this configuration. Administrator refresh uses
`POST /api/v1/synthetic/refresh`, with the current refresh revision obtained from
`GET /api/v1/cases`. Four fixed orders are imported once in a synthetic namespace,
all with source/report quantities of 10 capsules. Later refreshes retain their
original dates and raw facts; they do not represent changed-source synchronization.

`GET /api/v1/cases` defaults to the session operator's physician label. An explicit
empty physician selects all; an exact chart number crosses physician filters.
Duplicates are warnings across all cases, independent of the current filter.
`GET /api/v1/cases/{case_id}` requires an authorized session and returns preserved
raw synthetic snapshots. Dates are calendar dates; same-day order is not chronology.

Use the [prepared acceptance environment](../docs/validation/case-queue-manual.md)
for a real HTTPS API/browser journey. It keeps state and generated certificates
outside Git, never opens HIS paths, and does not certify native Windows transport.
Before upgrading an existing synthetic v2 environment, stop it and retain its
entire state directory. v1/v2 histories survive v3 migration. Older binaries refuse
v3; keep v3 intact and use a compatible forward fix rather than deleting case tables.

## Medication reasons (schema v4)

`GET /api/v1/reason-options` returns the 37 complete values from the preserved
official workbook's code sheet, E2:E38. The service verifies its pinned SHA-256;
deploy the original fixture at its repository-relative path with the service.
These values do not establish eligibility or conditional-field rules.

`POST /api/v1/cases/{case_id}/reason` requires physician or reporting capability,
an exact option, explicit `patientConfirmed: true`, requestId, and the displayed
revision. Administrator capability alone does not grant clinical editing.
The revision, reason, audit, and command result commit together. A conflict returns
the current reason/revision. The client requires a fresh read and renewed patient
confirmation before saving. Reason-complete cases remain unfinished pending reporting
reconciliation; `awaitingReason` is distinct from total unfinished/overdue counts.

Schema v4 adds a nullable reason column; v1/v2/v3 upgrade paths retain original
source facts and history. Before migration, stop and preserve the complete state
directory. Earlier binaries refuse v4: retain it and deploy a compatible forward
fix. Never roll back by discarding reasons or audit history.

Run `python -m scripts.run_acceptance_checks` after building the client for isolated
real-HTTPS/browser queue and two-client reason checks. The runner starts and stops
only its own temporary synthetic service. Its bridge models native IPC and does
not replace Windows deployment acceptance.

## Dispensing and exclusions (schema v5)

Reporting capability is required for quantity/lot changes, bulk lot replacement,
exclusion/reinclusion and case history. Source quantities remain immutable.
Positive integer lot quantities must sum exactly to actual quantity, which cannot
exceed source quantity. Quantity changes and exclusion decisions require reasons.
Bulk replacement requires confirmation and every selected case revision; any stale
case or audit failure rolls back the entire batch. Later individual edits remain
independent. No inventory inference is introduced.

Queues support date, physician, exact chart, status and exception filters. Excluded
cases leave default/unfinished views; explicit status filters retrieve them.
Internally complete data is distinct from official export eligibility, still false.

v5 adds lots, exclusion status and the latest decision reason. Historical decisions
remain in audit. Tested v1/v2/v3/v4 upgrades retain source facts and medication reasons.
Stop and retain complete state before upgrading. Pre-v5 binaries refuse v5: preserve
it and deploy a compatible forward fix rather than deleting human decisions.
The isolated acceptance runner now covers four real HTTPS browser journeys.
# Source reconciliation (schema v6)

Synthetic refresh accepts explicit original/modified/cancelled/unseen/deleted/missing
scenarios. Changed sources append snapshots while retaining the adopted reporting
source and all human fields. Reporting-only `source-review` requires a case revision,
latest snapshot, resolution and reason. Quarantine diagnostics are reporting/admin
only; valid recovery still requires review. Human command audits reference the
adopted source. See `docs/validation/source-review-progress.md` for migration,
recovery and evidence. Production HIS and export gates remain unchanged.
