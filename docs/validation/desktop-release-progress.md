# Desktop release distribution — #21 progress

This records central release distribution and native signed updating for #21.
The desktop checks releases, verifies packages, installs only after confirmation,
and retains an independently executable recovery tool. Central Windows-service
startup/recovery documentation and operational acceptance remain open.

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
  key before execution. Checked-in service fixtures are inert; native acceptance
  generates executable packages and synthetic signing keys outside Git.

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

## Native update and recovery contract

The build embeds `CLINIC_REPORTER_UPDATE_PUBLIC_KEY`; an absent key disables
updates. No runtime or webview override exists. Both the currently installed
release and the announced successor must be published centrally. The native
client bounds HTTPS downloads, rejects redirects, verifies length and SHA-256,
and checks the pinned minisign signature including the authenticated version
comment. A valid signature without exactly one matching `version:` field is
rejected. This requirement concerns version binding, not the minisign algorithm.

Preparation preserves `previous.exe`, `next.exe`, a copy of the current native
client named `recovery.exe`, and a ready manifest in a new per-user attempt
folder. Files are never overwritten. Incomplete or malformed manifests do not
hide older valid plans. Every installer is verified again and held open without
write/delete sharing through process creation. Updating is limited to the
registered current-user installation; portable copies cannot update themselves.

Startup checks never install automatically. Installation and rollback require
an explicit saved-work confirmation. The client exits only after successfully
starting the installer. Reopen it from the Windows Start menu after installation.
Neither operation changes central data. If the new client cannot start, execute
`recovery.exe` from the retained attempt folder and confirm its native dialog.
This recovery needs neither the new executable nor a running central service.

The cache lives under `%LOCALAPPDATA%\tw.clinic.antiviral-reporter\updates`.
Use the UI's recovery-folder action before maintenance to locate the retained
attempt. Keep that folder until operational recovery and retention policy are
approved; no automated history cleanup exists.

## Signing and synthetic rehearsal

Use a protected signing workstation and retain one controlled signing key across
releases. Never put its private key, password, installer or deployment settings
in Git. Embed the public key before building the NSIS installer and use the
installed Tauri CLI signer with `--app-version` matching the canonical release
version. Publish the resulting installer and `.sig` through the offline command
above. The synthetic preparation script demonstrates this sequence; its generated
keys and debug installers are exclusively for tests, not production distribution.

From the repository with the Python 3.12 virtual environment active:

```powershell
python scripts/prepare_signed_updates.py
python -m scripts.check_signed_updates 'REPLACE_WITH_PRINTED_RELEASES_JSON_PATH'
```

Preparation builds versions 0.1.0 and 0.1.1 into a unique temporary directory.
Acceptance evidence uses a unique directory under `%LOCALAPPDATA%`, on the same
volume as the update cache, even when `%TEMP%` is on another disk.
Acceptance requires a standard Windows account with no existing installation,
startup preference, product shortcut or update cache. It starts an isolated HTTPS
service, temporarily trusts only its generated test certificate in CurrentUser,
uses synthetic credentials, exercises real WebView2/Tauri IPC and NSIS installers,
then restores the endpoint preference, removes synthetic credentials/certificate,
uninstalls its own test installation and retains artifacts outside Git. It never
opens HIS files or enables production exports. Do not use these scripts to replace
an existing clinic installation.

## Automated evidence and remaining work

The current recheck on 2026-10-04 passes Python discovery **130**, Vitest **11**,
browser Playwright **2**, Rust **5**, the frontend build, and mypy for 35 source
files. All 10 existing real-HTTPS business journeys
and the native lifecycle harness also passed. The first Python invocation used the system
interpreter without dependencies; the successful run used the repository's Python
3.12 virtual environment. Browser tests mock native IPC; they are separate from
the real Windows rehearsal below.

The final native rehearsal used synthetic releases under temporary folder
`ClinicReporter Signed Updates cqbeznvi`; final evidence was retained under
`%LOCALAPPDATA%\ClinicReporter Update Acceptance u_fjwy3w`. Both are outside Git. It verified:

- real HTTPS release discovery and bounded package retrieval;
- truncated response, prematurely disconnected stream and corrupted cache refusal;
- refusal to install without confirmation, keeping the current process alive;
- exact installed executable bytes for 0.1.0 → 0.1.1 → 0.1.0;
- preserved device connection credentials and disabled startup preference;
- a second upgrade followed by offline recovery with the new executable unavailable.

The exact-byte comparison accounts only for Tauri's unique bundle marker changing
from `UNK` to `NSS` during NSIS bundling. All remaining bytes must match. A startup
check/manual-operation race surfaced in the real rehearsal, received a failing
then passing UI regression test, and the installers were rebuilt before the final
successful run. This rehearsal does not simulate power loss or actual Windows
sign-out/sign-in.

Rust public-boundary tests generate real synthetic signatures and cover wrong key,
corruption, relabelled or missing signed version, retained recovery bytes, malformed
newest manifests, unrelated cache files, Unicode plan IDs and optional release
metadata. Service tests cover publication/retry, revisions, immutable versions,
revocation, damaged/partial artifacts, exclusive ownership, migration and backup.

The prior central-distribution review used the approved `be7df98` baseline. Native
review initially used AGY Claude Opus 5.5; its low-severity findings were addressed
in the subsequent implementation. Follow-up Opus and Sonnet attempts exhausted
quota; the requested Gemini 3.8 Flash medium fallback returned `Request Changes`.
After correcting concurrency, same-volume retention, Win32 callback declarations,
installer-exit waiting and independent cleanup stages, its focused re-review
returned `Approve` (job `review-muscgc38-53116514`). Full reports remain in the
ignored `.agy-staff/jobs` directory. Reviewers inspected code; the host executed
the tests. This approval covers the corrected paths, not production deployment.

The reproducible central Windows-service startup/recovery and client deployment
procedure is now in [Windows deployment](../deployment/windows-service-and-client.md).
Its generator pins and verifies WinSW, uses explicit versioned paths and emits no
account password. The current full Python discovery has 130 passing tests and mypy
covers 35 source files; an official-wrapper bundle was also generated outside Git.
Actual Windows SCM/reboot/account/firewall evidence belongs to #25. Tray and real
Windows sign-in checks remain in
[desktop lifecycle progress](desktop-lifecycle-progress.md); a fresh temporary
manual client was prepared and launched after the automated installer tests.
Its path, hash and PID are in the documented local metadata. Actual clinic account,
certificate, firewall and
operational cutover evidence remains in #25. M0 and production export gates stay
unchanged.
