# Architecture

```text
Tauri clients ── versioned HTTPS API ── FastAPI central service ── SQLite
                                               │
                                               ├── read-only HIS scanner
                                               ├── official-template exporter (M0 gated)
                                               └── hourly off-host backup

Human operator ── download ready export ── manual SMIS login/upload/verification
```

## Boundaries

- The central service is the only SQLite owner and the only domain-rule implementation. Case commands and export operations are versioned API contracts.
- Tauri clients keep patient data in memory only. Their persistent state is limited to device identity, endpoint, update state, and non-patient preferences.
- The HIS adapter is read-only and exposes verified snapshots plus quarantine diagnostics. It does not expose private `HIS-pro` implementation.
- The exporter consumes frozen export items and an immutable official template. Its production entry point remains disabled until M0 evidence enables it.
- SMIS remains outside the system boundary. Upload and result verification are human actions recorded as declarations and per-item results.

## Consistency and recovery

Commands use optimistic revisions and idempotency keys. Each accepted mutation and audit event shares one database transaction. Source snapshots, export versions, and platform results are append-only history; projections may be rebuilt from them.

The central host backs up the database, configuration, and audit material to a controlled second machine at least hourly. Restore drills must verify both data integrity and service startup. Client update packages are signed, per-user, and rollback-capable.

The HIS share and backup destination are separate seams even when hosted by the same remote computer. The central Windows identity receives read-only permission on the HIS share and write permission only on a dedicated backup share. After case-insensitive normalization of servers, share names, and trailing separators, backup code requires a different SMB share name from the HIS source; a sibling directory on the HIS share is not sufficient separation.

## Configuration

The central service loads one validated settings object from prefixed environment variables. A local `.env` is supported for development, while a Windows service receives the same variables from its service manager or an explicitly configured, ACL-protected file outside the repository; configuration discovery never depends on the process working directory. The tracked `.env.example` contains reserved example addresses only. Production validation rejects placeholders and documentation-only addresses, requires a local absolute state directory and UNC HIS/backup roots on distinct shares, and probes HIS availability through read-only operations only.

`CLINIC_REPORTER_EXPORT_ENABLED` is an additional operational feature flag: false always disables export, while true still requires the persisted M0 evidence gate.

The example loopback bind is for local development. Production clients reach the central host through the configured HTTPS endpoint and firewall allowlist; deployment must not expose an unauthenticated FastAPI listener on all interfaces.

Tauri build-time environment variables are not deployment secrets: Vite bundles them into the client. Each client stores only its central API endpoint, device identity, update state, and non-patient preferences in per-user configuration. HIS and backup paths remain central-only.

## Interfaces

The versioned OpenAPI surface covers session/device capabilities, HIS refresh, work queues and case detail, typed case commands, export-version creation and download, upload declarations, and per-case platform results. Generated TypeScript bindings are the client boundary.
