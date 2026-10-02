# Central service

Python 3.12/FastAPI central service. Issue #7 is in progress: device/session APIs
and central settings are implemented; the desktop workflow and full acceptance
are not complete. No HIS scanner, patient workflow, or export endpoint is enabled.

## Development

From the repository root on Windows:

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m unittest discover -s tests -v
.venv/Scripts/python -m mypy service scripts
.venv/Scripts/python -m scripts.generate_openapi
```

From `client`, run `npm ci`, `npm run generate:api`, and `npm run typecheck`.
The versioned OpenAPI and generated TypeScript types are committed; regenerate
both after API edits. CI detects drift. API generation opens no state/source files.

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
keys in command arguments, shell history, logs, documentation, or Git. The desktop
credential storage/import flow is still pending. Provisioning cannot run while the
service owns the state directory or initialize a second administrator.

Start the HTTPS listener with the central certificate and key:

```powershell
.venv/Scripts/python -m service --env-file C:\ProtectedReporter\runtime.env serve --cert C:\ProtectedReporter\central.crt --key C:\ProtectedReporter\central.key
```

Use a certificate trusted by the managed clients. HTTP is rejected, proxy headers
are not trusted, access logging is disabled, and only one worker is allowed by the
entry point. The OS ownership lock also rejects a second independent process.
Firewall/network/certificate provisioning and real TLS verification remain M0 work.

Every protected request carries the individual device key as a Bearer credential;
session-bound operations also carry `X-Session-Id`. A session's operator is an
attribution claim, never authorization. Sessions expire after eight hours and every
request rechecks device revocation. Administrators issue single-use pairing codes
with a ten-minute lifetime and chosen capabilities. Codes also become unusable if
their issuing device is revoked. Pairing responses are sensitive; keep them private.

All mutation envelopes contain `requestId` and `expectedRevision`. New sessions,
pairings, and devices expect revision zero. Revocation uses the device's displayed
revision. Command results, state, and audit are stored in one transaction. The audit
read API requires an administrator device; there is no audit edit/delete API.

## Schema and recovery

SQLite user_version 1 introduces devices, sessions, command results, and audit;
version 2 adds pairing grants. Migration runs under exclusive service ownership.
The service rejects a database from a newer schema. Tests use isolated temporary
state, exercise a cold restart, and verify ownership rejection and retry history.

Before deploying any new service version, stop the service and retain a consistent,
protected backup of the entire state directory and its private runtime settings.
Do not downgrade by deleting tables or clearing audit/command history. If a binary
cannot read the migrated schema, keep that state intact and use the compatible
binary until a reviewed forward fix is available. Restoring an old backup must
reconcile subsequent work; it is not a silent rollback of human decisions. Automated
off-host backup/restore and migration failure drills remain in #20 and #7.

The settings loader performs no HIS I/O. It rejects relative/device-namespace paths,
path traversal, equal HIS/backup share names, production placeholders/documentation
addresses, wildcard listeners, and backup intervals above an hour. The export flag
is only an operational setting, not evidence or authorization to export; no export
implementation exists in this checkpoint.
