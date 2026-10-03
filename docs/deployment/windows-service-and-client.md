# Windows central service and client deployment

This procedure completes the reproducible software instructions for issue #21.
It does not claim the clinic account, network, certificate, firewall, HIS share or
off-host backup acceptance required by #25. Record those results privately with
only de-identified evidence linked from the M0 checklist.

## Fixed layout and identities

Use versioned, ACL-protected directories on a fixed local NTFS volume. The examples
are placeholders and must be replaced with the clinic's approved paths.

```text
C:\ClinicReporter\releases\<release-id>\   immutable source plus its Python 3.12 venv
C:\ClinicReporter\services\<release-id>\  generated WinSW executable/XML/logs
C:\ClinicReporter\protected\runtime.env   central runtime configuration
C:\ClinicReporter\protected\central.crt   HTTPS certificate
C:\ClinicReporter\protected\central.key   HTTPS private key
C:\ClinicReporter\state\                  live single-owner state
```

Create one dedicated, non-interactive Windows service identity. It needs:

- read/execute on the selected release and service bundle;
- read on `runtime.env`, the certificate and private key;
- modify on the state directory and protected service log directory;
- read-only share and NTFS access to the HIS source;
- separate write access to the dedicated backup share, whose share name differs
  from the HIS DATA share even when both live on the same server;
- “Log on as a service”, with interactive sign-in denied by clinic policy.

Do not use LocalSystem: WinSW uses it by default, but this application needs a
least-privilege network identity. Do not put an account password in XML, command
arguments, the env file, shell history or Git. Set the Log On account through
Windows Services after installing the wrapper and before the first start. Protect
the wrapper log directory because controlled errors may still contain operational
diagnostics.

Each client uses its fixed standard Windows account and a separate device
credential. Clients never receive the HIS/backup paths or SMB credentials.

## Prepare a versioned central release

1. Copy a reviewed repository revision into a new release directory. Do not edit
   the active release in place.
2. Create its Python 3.12 virtual environment and install the repository
   requirements. Run the full automated checks before selecting this release.
3. Place `runtime.env`, TLS certificate and private key in the protected paths.
   Production must set `CLINIC_REPORTER_ENV=production`, a specific clinic-LAN
   bind address, a local absolute state directory, distinct UNC HIS/backup shares,
   all synthetic flags false, and production export false until every M0 export
   gate is evidenced. Process environment values override the env file, so remove
   inherited `CLINIC_REPORTER_*` variables from the service account.
4. Validate ACLs while acting as the service identity: read the HIS share without
   creating or modifying anything; create/remove a synthetic file only on the
   dedicated backup share; read protected configuration; write only the state/log
   directories. Keep the result outside Git.

Download the x64 WinSW 2.12.0 asset from the [official release](https://github.com/winsw/winsw/releases/tag/v2.12.0).
The generator accepts only this SHA-256:

```text
05B82D46AD331CC16BDC00DE5C6332C1EF818DF8CEEFCD49C726553209B3A0DA
```

Generate a new bundle from the repository root. It refuses relative paths,
reparse points, an existing output directory, an external Python runtime and an
unrecognized wrapper. It escapes XML paths and writes no account password or
device credential.

```powershell
.venv\Scripts\python.exe -m scripts.windows_service_bundle `
  --output 'C:\ClinicReporter\services\REPLACE_RELEASE_ID' `
  --release-root 'C:\ClinicReporter\releases\REPLACE_RELEASE_ID' `
  --python 'C:\ClinicReporter\releases\REPLACE_RELEASE_ID\.venv\Scripts\python.exe' `
  --env-file 'C:\ClinicReporter\protected\runtime.env' `
  --cert 'C:\ClinicReporter\protected\central.crt' `
  --key 'C:\ClinicReporter\protected\central.key' `
  --winsw 'C:\ClinicReporter\downloads\WinSW-x64-2.12.0.exe'
```

The generated service uses one Python process, delayed automatic start, a
30-second Ctrl+C shutdown window, restart after non-zero exits with the failure
counter reset after one successful hour, and a pre-created protected rolling-log
directory. The app's state ownership lock independently refuses a second owner.

## Install and verify startup

Use an elevated PowerShell only for Windows service and firewall administration.
Application provisioning commands run while the service is stopped under the
dedicated service identity.

1. If this is the first deployment, provision the initial administrator exactly
   once with the hidden prompt documented in [service README](../../service/README.md).
   Keep the device key out of scripts and logs.
2. From the new generated service directory, run
   `.\central-service.exe install`. Do not start it yet.
3. Open `services.msc`, find **Clinic Antiviral Reporter Central Service**, set its
   Log On account to the dedicated service identity, and enter the password through
   the Windows dialog. Confirm Automatic (Delayed Start) and recovery restart.
4. Add an inbound Windows Firewall rule for the configured TCP port, scoped to the
   clinic LAN addresses and central executable. Do not expose a wildcard/public
   network. Record the private rule name and scope; actual approval is #25 evidence.
5. Start with `.\central-service.exe start`, then require
   `.\central-service.exe status` to report running. Inspect the protected wrapper
   log and Windows Event Viewer without copying sensitive logs into Git.
6. From an authorized managed client, connect using the certificate hostname,
   verify its trust chain, create a session, and read the health/backup/update
   views. HTTP, a wrong hostname, an untrusted certificate and a revoked device
   must fail. Automated synthetic tests do not replace this clinic check.
7. Reboot the central host during an approved maintenance window. Confirm the
   service starts without an interactive logon, only one owner exists, scheduled
   scans/backups resume, and no production export becomes enabled.

If startup fails, stop after collecting the event and protected log references.
Check the configured account, explicit paths, ACLs, certificate/key pair, port and
inherited environment. Never make the HIS share writable to cure startup failure.

## Deploy clients

1. Publish both the currently installed and successor signed installers using the
   offline release procedure in [desktop release evidence](../validation/desktop-release-progress.md).
2. On each fixed standard Windows account, run the reviewed per-user NSIS installer
   without elevation. Verify its registered install directory and Start-menu entry.
3. Import the initial administrator only on the designated first device. Use a
   short-lived pairing code with minimum capabilities for every other device.
   Never reuse or share a device credential.
4. Verify connection, pairing, immediate revocation, close-to-tray, explicit quit
   and the chosen Windows sign-in startup behavior. The prepared local manual flow
   is in [desktop lifecycle evidence](../validation/desktop-lifecycle-progress.md).
5. Verify an announced signed update does not close the client until the operator
   confirms saved work. Confirm exact upgraded version, retained credential and
   preference, rollback, and independent `recovery.exe` while central is offline.

## Maintenance upgrade

1. Announce the maintenance window and have users save and explicitly exit clients.
2. Confirm a current verified off-host backup and preserve the active service
   bundle, release, protected configuration and state. Do not copy HIS data.
3. Prepare and test a new immutable release and generated service bundle alongside
   the old one. Never replace the active files in place.
4. Stop the old wrapper and require stopped status. Verify the central port is
   closed and no service Python process owns the state.
5. Run the new release's migration-sensitive commands, if any, only while stopped.
   Never lower SQLite `user_version` or delete historical records.
6. Uninstall the old wrapper registration; retain its directory. Install the new
   wrapper, set the same dedicated Log On identity through `services.msc`, confirm
   its firewall scope, and start it.
7. Verify authorized HTTPS, current schema, backup health, scanner status and
   client update discovery. Record the release ID and result privately.

## Failure and recovery

For a configuration or wrapper failure before database changes, stop the new
service, retain all evidence, and reinstall the last compatible service bundle.
Keep the current state directory unchanged.

After any schema migration, application rollback is allowed only to a build known
to support the current schema. Otherwise deploy a reviewed forward fix. Never copy
an older database over newer source versions, human decisions, audit, release or
export history.

For state loss/corruption, keep the failed state untouched and follow the isolated
restore procedure in [backup and recovery evidence](../validation/backup-recovery-progress.md).
Verify the restored copy on loopback with synthetic/no-live scanning first. Before
cutover, reconcile all work after the chosen snapshot, reapply the approved
service identity/ACLs, and obtain #25 operational approval. Desktop rollback never
rolls back central state.

For a central outage, clients clear protected views and staff use the approved
paper process. After recovery, an administrator rescans the explicit outage range
and records already completed work as `系統外已完成`; do not create an offline queue.

Uninstalling the wrapper removes only Windows service registration. Retain its
versioned files, state, immutable artifacts, protected configuration and backups
until the approved retention process permits disposal.

## Evidence boundary

Repository tests prove deterministic bundle generation, fixed wrapper hash,
secret-free XML, absolute paths, no replacement, and service command construction.
The local acceptance run verifies the official wrapper hash, generates a bundle
outside Git and includes the pre-created log directory. The full Python discovery
run passes 94 tests and mypy passes 30 source files. Actual SCM installation, reboot
autostart, account rights, certificate
trust, firewall scope, device fleet and off-host restore must be performed on the
clinic environment and remain tracked by #25 and `docs/validation/m0-gates.md`.
