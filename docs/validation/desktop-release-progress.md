# Desktop release distribution — #21 progress

This records the central distribution portion of #21. The desktop does **not yet**
check, verify, install, or roll back updates. Do not treat the HTTP distribution
API or passing service tests as evidence that signed updating works.

## Implemented contract

- `GET /api/v1/client-releases/current` returns the catalog revision and latest
  published release, or revision zero and `release: null` before publication.
- `GET /api/v1/client-releases/{version}` returns immutable version metadata.
- `GET /api/v1/client-releases/{version}/installer` returns the exact retained
  bytes only after checking size and SHA-256. Missing or corrupt bytes return 503.
- All three require an active device credential, including devices with only
  physician capability. An operator session is unnecessary for startup checks.
  Revocation applies on every request. Responses contain no central paths.
- Releases contain version, SHA-256, byte count, signature text and public release
  notes. The service distributes signature text; it does not certify its validity.
  A desktop must verify the installer and signed version using its pinned public
  key before execution. No test fixture here is an executable or valid signature.

## Offline publication

Use planned maintenance, after users finish and save their work. Stop the central
service first; its exclusive owner lock rejects publication while it is running.
Keep installers, signatures, signing keys, deployment configuration and resulting
state outside Git. The release signing private key never belongs on clients.

From the repository, with the service virtual environment active:

```powershell
python -m service --env-file 'C:\ProtectedReporter\central.env' stage-release `
  --version 0.1.0 `
  --installer 'C:\ProtectedReleases\0.1.0-setup.exe' `
  --signature 'C:\ProtectedReleases\0.1.0-setup.exe.sig' `
  --operator 'REPLACE_WITH_OPERATOR' `
  --reason 'Initial verified desktop release' `
  --request-id '11111111-1111-4111-8111-111111111111' `
  --expected-revision 0 `
  --notes 'Public, non-patient release notes'
```

Paths above are placeholders. Use a new UUID for each intended publication and
the revision read from `current`. On an uncertain result, retry the same command
with the same UUID: it returns the original result without a second audit event.
A revision conflict returns the current catalog for review. A version cannot be
replaced. Restart the service after maintenance and check `current` from an
authorized client. Publication selects that version as the current announcement;
it does not install anything on clients. Publish the original installed version
before its successor so both installation packages are available for recovery.

Versions must be canonical numeric `major.minor.patch`, with each component at
most 65535. Installer size is limited to 128 MiB, signature text to 16 KiB, and
notes to 4000 characters. Only public non-patient information belongs in notes,
operator and reason fields. The service does not execute uploaded bytes.

## Durability and migration

Schema 11 adds an append-only release catalog. Existing cases, decisions, source
snapshots, exports, commands and audit events remain unchanged. File publication
precedes the single transaction that commits the catalog entry, audit event and
request result. An interrupted `.partial` file or a complete blob without a
catalog row cannot be downloaded. A retry may reuse a complete orphan only after
comparing its exact bytes. Old packages and partial files are retained; no history
cleanup is automated.

Packages live under the service's protected `immutable-artifacts` directory.
Existing backup inventory and isolated restore include both the catalog and
these files. Protect this directory with the same ACL as central state. Do not
edit files in place or downgrade the SQLite schema. A pre-schema-11 service
rejects the upgraded database. For service recovery, retain the matching service
version, or restore a verified pre-upgrade backup into an isolated directory and
reconcile any later work before cutover; never overwrite live history. Desktop
version rollback must not roll back the central database.

## Automated evidence and remaining work

Local verification on 2026-10-03: full Python discovery **90 tests passed**;
`mypy --check-untyped-defs service scripts` passed for 27 source files; regenerated
OpenAPI/TypeScript bindings passed `npm run typecheck`. These results cover central
distribution, not a native signed installation or recovery drill.

`python -m unittest tests.test_client_releases tests.test_migration -v` covers
publication/retry, audit uniqueness, conflicting revisions, immutable old
versions, byte-for-byte download, damaged artifacts, uncatalogued partial files,
device revocation, exclusive ownership, invalid input, schema 1–10 upgrades,
future-schema refusal, and release backup/restore. All data is generated under a
temporary directory. Partial-file tests model interrupted on-disk state; they
are not power-loss tests.

An injected audit storage failure also verifies that an installer already copied
to central state remains unavailable when the transaction fails, and that the
same request can subsequently recover without replacing the retained bytes.
An unreadable-database test checks that startup failure preserves the original
database bytes and emits a controlled error without an internal traceback/path.

Two-axis review used the approved `be7df98` baseline and the uncommitted release
changes, with gpt-6-luna/max for both reviewers. Standards review found outdated
schema documentation and a database-open error path; both were corrected, and
the latter was independently rechecked. Spec review found no distribution defect
and retained the unfinished native/operational #21 acceptance below.

Still required for #21: pinned-key signature and signed-version verification,
bounded HTTPS download, retained verified recovery installer, explicit update
confirmation, interrupted-update recovery, actual installed upgrade/rollback
with synthetic keys outside Git, and central Windows-service startup/recovery
instructions. The tray and Windows sign-in manual checks remain in
[desktop lifecycle progress](desktop-lifecycle-progress.md). No manual signed
update environment is ready yet; prepare and automatically exercise that
environment before asking a person to test it.
