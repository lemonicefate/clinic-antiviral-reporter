# Backup and isolated recovery (#20)

This software slice adds schema v10, administrator backup status and requests,
scheduled consistent snapshots, and an offline restore command. Production Excel
remains disabled. Local synthetic backup success does not establish off-host RPO,
clinic ACLs, network resilience, or the operational acceptance in #25.

## Configuration and archive contract

Backups are disabled by default. The central service owner configures
`CLINIC_REPORTER_BACKUP_ENABLED=true` and the existing backup root. The backup
share name must differ from the HIS share name (case-insensitive), even on another
server. No HIS files are copied or opened for write. Clients receive status and
opaque backup IDs, never source/backup paths or credentials.

The default interval is 1,800 seconds, with a maximum of 3,600. RPO status uses
the snapshot time, not the completion time; absent snapshots, age over one hour,
and clock reversal produce a breach. A slow or failed transfer can therefore
breach RPO even when scheduling is configured correctly.

Under central storage ownership, each snapshot captures SQLite using its backup
API, effective runtime configuration, `immutable-artifacts/`, and TLS certificate
and key when the HTTPS entry point supplied them. SQLite integrity and foreign
keys are checked locally. Checksummed payloads are copied into `.pending-<id>`;
only a verified manifest and directory publication yield `backup-<id>` and a
successful status. Incomplete directories are never accepted for restore.

Manifest format 1 records the snapshot time, payload-copy verification time
(`completedAt`), and SHA-256 inventory. `completedAt` is captured after copied
payload hashes match, before manifest verification and directory publication; it
is not the end time of those final operations. Only after publication verifies
does status expose that timestamp as `lastSuccessfulAt`. Restart/restore preserves
the same archive timestamp. Runtime configuration has its own format 1 envelope: known optional
settings can be omitted and use validated defaults. Unknown formats/settings are
rejected. Future releases must retain readers or explicit migrations for retained
formats; adding a setting is not permission to invalidate older archives.
Future immutable export artifacts must be written under `immutable-artifacts/`
with their database references synchronized under central storage ownership.
Extend inventory/version handling if any authoritative data moves elsewhere.

## Protection and retention

Archives contain sensitive database history, runtime paths and potentially the TLS
private key. Provision restrictive share and NTFS ACLs before enabling backups:
only the central backup identity and designated recovery administrators should
have access. Use a read-only identity for HIS and separately grant backup rights;
SMB credentials remain in Windows administration, never client configuration.
Coordinate certificate rotation with service restart and backup creation so the
certificate/key pair copied from disk matches the active service configuration.

This release performs no automatic retention deletion. Retain every published
archive and its immutable artifacts until an approved retention policy provides
evidence that disposal preserves required source, reporting and audit history.
Monitor capacity on both the central disk and backup share. Local
`backup-staging/<id>` working copies and remote `.pending-<id>` copies may remain
after transfer attempts and need the same ACLs as complete archives. An operator
must identify an inactive attempt and preserve its diagnostic evidence before
approved cleanup; never treat it as a usable restore point.

For this release, assign a named backup administrator to inspect free space and
backup status at least daily and after every failed transfer. Before enabling
scheduling, measure one complete synthetic archive at the expected data volume:
with the default interval, reserve at least 48 full snapshot sizes per day of
unattended operation on the central staging disk, plus active database/artifact
growth and restore working space. This is a minimum estimate, not a fixed size
guarantee; reassess when data volume grows. Configure external disk-capacity alerts
early enough to cover the administrator's response time. Without that capacity
and monitoring, operational deployment acceptance stays OPEN.

During daily maintenance, identify completed staging IDs from administrator backup
history, independently verify the corresponding published archive's full manifest
and payload hashes, and confirm that no worker is writing that ID. Record the ID
and verification in the protected maintenance record. Only then may the assigned
administrator remove that redundant local `backup-staging/<id>` directory after
checking its resolved location and rejecting reparse points. Preserve published
archives. Leave unmatched/failed attempts protected for investigation, and add
capacity if diagnosis cannot finish before the next backup. Never purge the active
database, immutable artifact originals or HIS source to make room.

Ordinary failed restores remove only their own validated staging directory.
Process termination or power loss can leave `.restore-pending-<id>` in the restore
parent. Protect that parent before starting, and reconcile orphan directories
against active restore processes before any manual cleanup.

## Isolated restore procedure

Use synthetic data for rehearsal. Do not point this procedure at a live HIS share.

1. Select a published `backup-<id>` directory; retain the original archive and
   current central state. Record its ID, snapshot time, software revision and the
   recovery operator in the protected operational record.
2. Prepare a new, ACL-protected parent on a fixed local Windows disk, with enough
   free space. Choose a destination that does not yet exist and is outside both
   the original state directory and the archive. Reparse points are refused.
3. Run from this repository using absolute paths (replace the example paths):

   ```powershell
   .venv/Scripts/python -m service.restore --backup C:\ProtectedRehearsal\backup-UUID --destination C:\ProtectedRecovery\new-state --operator SYN-RECOVERY-ADMIN
   ```

4. Require exit code zero. The tool verifies the inventory/database, preserves
   history, records `backup_restored`, expires old sessions, and reconciles this
   archive's own backup run from its verified manifest timestamp. It never
   overwrites an existing destination. Failed/corrupt archives must not be used.
5. Inspect the new `recovery.env` privately. It binds to loopback and disables
   scans, backups and exports. Review all paths and ACLs before starting anything.
   Use a fresh PowerShell process with no inherited `CLINIC_REPORTER_*` overrides:
   process environment takes precedence over the env file. Do not reuse a live
   service environment or change restored settings to live endpoints for rehearsal.
6. If TLS files were included, verify certificate/key access and trust, then start
   the isolated service with the compatible Python environment:

   ```powershell
   .venv/Scripts/python -m service --env-file C:\ProtectedRecovery\new-state\recovery.env serve --cert C:\ProtectedRecovery\new-state\tls.crt --key C:\ProtectedRecovery\new-state\tls.key
   ```

   If certificates were not supplied during backup, provision a separate trusted
   rehearsal pair first. Choose an unused port in the protected env file. Never
   expose the restored listener as the production endpoint during validation.
7. Reconnect with an existing authorized device credential and a fresh session.
   Device credentials are retained in Windows Credential Manager, not backed up
   as plaintext by the service. Confirm case snapshots, reasons, lot allocations,
   exclusions, outside completions, audit history and immutable artifacts against
   the selected snapshot. Confirm old sessions fail and production export stays
   disabled. Reconcile any changes after the snapshot before a real cutover.
8. Stop the isolated listener. Retain evidence and both old and restored histories.
   Restoring SMB identity rights, TLS trust, lost device credentials and an actual
   endpoint cutover require the designated administrator's documented procedure;
   the restore tool does not reset authorization or invent replacement credentials.

### Device credential recovery decision

Before cutover, verify at least one retained administrator device can open a fresh
authorized session against the isolated restored service. A credential issued or
rotated after the selected snapshot might not match the restored authorization
history; do not assume the newest client key will work with an older snapshot.

If another administrator credential still works, use that device's management page
to create a single-use pairing code with administrator capability, and use
「以管理者配對碼啟用」 on the authorized replacement Windows client. Confirm the
replacement can open a fresh administrator session before revoking the lost
device. Record pairing/revocation evidence; keep at least one working administrator
and never place credentials in tickets or logs. Re-pair reporter/physician devices
through the same administrator path with only their required capabilities.

If every administrator credential is lost, block production cutover and escalate
to the responsible clinic administrator and service maintainer. `provision` refuses
an already initialized database; this release has no supported emergency credential
reset. Preserve the archive, current state and restored state, and require a
separately reviewed recovery procedure. Do not clear device tables, edit credential
hashes or delete audit history to bypass this protection.

## Migration and rollback

The v9-to-v10 migration adds backup history/state without replacing case history.
At delivery of this backup slice, tests constructed source schemas v1 through v9,
including v9 outside-completion history. The later
[release catalog slice](desktop-release-progress.md) extends migration coverage
through v10 and advances the current schema to v11. Older binaries that
cannot read v10 must not open this state. Never change `user_version`, delete tables,
or copy an old database over a newer one to downgrade. Preserve the migrated state
and use a compatible binary or a reviewed forward fix. Any older isolated restore
requires reconciliation of intervening history before production cutover.

## Automated and remaining evidence

The current recheck on 2026-10-03 passes 107 Python unittest tests, 11 Vitest tests,
all 10 real HTTPS browser journeys, mypy (32 source files), the TypeScript/Vite build,
and the Windows Tauri debug build. OpenAPI/TypeScript clients were regenerated. This is
software and local synthetic evidence, not off-host deployment acceptance.

`tests/test_backups.py` covers scheduled/manual runs, retry and audit atomicity,
RPO and clock reversal, capability checks, incomplete/corrupt archives, restart
recovery, failed restore cleanup, optional configuration compatibility, and restored
service authorization plus retained history/artifacts. `tests/test_migration.py`
includes v9-to-current preservation. `client/e2e-real/backups.cjs` exercises the
administrator UI against real local HTTPS, a manual backup, narrow viewport,
reporter denial and disconnection behavior. All data is synthetic in temporary
directories; local backup destination mode requires explicit development flags.

Actual off-host hourly RPO, backup-share outage/capacity alerts, recovery identity
ACLs, native device credential recovery and clinic cutover remain OPEN under #25.
SMIS acceptance remains a separate M0 gate and cannot be proven by this archive.

## 已搭建的人工操作環境

2026-10-03 本次環境入口為 <http://127.0.0.1:13086/>，已啟用合成 DBF
與本機合成備份，並以瀏覽器自動確認「備份完成」。環境僅限本機；資料、
憑證與備份均在 Windows 暫存目錄，未存入 Git。前一個測試環境已停止，
其資料保留。重新搭建後網址可能變動，可讀取
`%LOCALAPPDATA%\ClinicReporterAcceptance\case-queue-v1\current.json` 的 `url`。

以下介面操作已自動測過，僅供你驗收操作感受，無須重新替代自動測試：

1. 開啟入口，再開啟管理電腦測試頁；也可直接開啟
   <http://127.0.0.1:13086/app?profile=admin>。
2. 「操作身分」輸入 `SYN-MANUAL-ADMIN`，按「連線」，進入「備份與還原」。
   預期顯示「備份完成」，並明示「本機合成測試；不構成正式異機備份證據」。
3. 記下畫面的備份 ID 與成功時間。在「備份原因」輸入「合成資料人工驗收」，
   按「立即要求備份」。預期先顯示受理，再回到「備份完成」，備份 ID 更新。
   不應顯示 HIS 路徑、SMB 密碼或 TLS 私鑰。
4. 另開 <http://127.0.0.1:13086/app?profile=reporting>，使用
   `SYN-MANUAL-REPORTER` 連線。預期回報身分看不到「備份與還原」導覽。
5. 若要驗收離線顯示，保持管理頁開啟，回入口使用停止中央服務控制。
   預期管理頁清除備份狀態並回到連線畫面。再由入口啟動服務並重新連線，
   預期已完成的備份歷史仍存在。請保留入口以便重新啟動。

真正需要現場管理員執行的是異機備份分享、Windows ACL／憑證／裝置金鑰
復原，以及停機後實際切換的驗收；這些仍是 #25 的 OPEN 項目。
上述英文隔離還原流程提供管理員逐步操作與預期檢查，不要求把真實 HIS
或病人資料帶入本機合成環境。
