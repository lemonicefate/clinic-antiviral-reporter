# Device/session implementation evidence

Issue: https://github.com/lemonicefate/clinic-antiviral-reporter/issues/7

This is a local development checkpoint, not deployment acceptance. All identities
and failure fixtures are synthetic. Production export remains disabled.

## Service

- Unknown devices are denied; operator labels cannot elevate capability.
- Administrator-approved, expiring, single-use pairing enrolls a device.
- Revocation rejects existing sessions and new sessions immediately; the last
  administrator is protected from accidental lockout.
- Request retries, including cross-command reuse, return the original result
  without another audit event; results survive service restart.
- Stale revocation returns the current revision and field differences, preserving
  the first reason. Expired sessions and pairing codes are rejected.
- A real SQLite audit-write failure rolls back enrollment and grant consumption;
  the same command can then succeed once on retry.
- Single-owner locking, offline provisioning, migration from schema v1 to v2,
  and byte-preserving refusal of a newer schema are verified.
- A real HTTPS listener accepts a trusted synthetic certificate and rejects an
  untrusted certificate. Invalid responses do not echo device credentials.
- Configuration and OpenAPI expose no runtime paths to clients. Source and backup
  must have different share names. Official fixture integrity remains unchanged.

## Desktop

- Initial key import, new pairing, reconnection, device listing, and reasoned
  revocation are implemented with generated OpenAPI types.
- Native Windows Credential Manager round-trip and cleanup are tested. Fresh
  enrollment rotates the credential; retries preserve the pending identity.
- Native HTTPS uses system trust, rejects redirects, and never returns keys to React.
- Outage handling unmounts the protected view. Generation guards reject stale
  requests; pairing/revocation request IDs survive reconnection.
- Loading, empty, retryable failure, mutation status, and keyboard focus behavior
  are tested. Browser flows at widths 1080 and 720 have no horizontal overflow.
- A built native executable was launched locally: real IPC loaded the blank
  connection form and rejected an insecure endpoint before saving configuration.

## Verification commands

On Windows, Python 3.12 and the installed Rust/Node toolchains:

```powershell
.venv/Scripts/python -m unittest discover -s tests -v
.venv/Scripts/python -m mypy --check-untyped-defs service scripts
.venv/Scripts/python -m scripts.generate_openapi
```

From `client`:

```powershell
npm run generate:api
npm run typecheck
npm test
npm run test:e2e
cargo test --locked --manifest-path src-tauri/Cargo.toml
npm run tauri build -- --debug --no-bundle
```

Results: 20 Python tests, 5 Vitest tests, 2 Playwright tests, and 3 Rust tests pass;
type checks and native debug build pass. Browser tests mock the native transport.
The native smoke test is not a successful end-to-end pairing against deployed TLS.
Screenshots are local ignored synthetic evidence under `screenshots/`; automated
tests are the reproducible evidence committed to this repository.

## Standards

Review baseline: user-approved `be7df98`. The standards review found cross-command
response validation failure, lost mutation request IDs on reconnect, and stale list
responses replacing newer state. All were fixed and regression-tested; targeted
follow-up reported no remaining finding in those fixes.

## Spec

The spec review found last-administrator lockout, cross-command replay failure,
and inability to re-pair a revoked device with a fresh key. All were fixed and
targeted follow-up confirmed credential rotation and retry preservation.

Standards: 3 resolved findings. Spec: 3 resolved findings. No remaining issue in
these targeted fixes; this review does not establish completion of the whole MVP.

Native successful pairing against a trusted deployment, real revocation/network
drills, signed packaging, and M0 evidence remain open. #7 is not closed by this
checkpoint. No HIS source or patient data was accessed.
