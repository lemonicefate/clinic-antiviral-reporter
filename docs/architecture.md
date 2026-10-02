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

## Interfaces

The versioned OpenAPI surface covers session/device capabilities, HIS refresh, work queues and case detail, typed case commands, export-version creation and download, upload declarations, and per-case platform results. Generated TypeScript bindings are the client boundary.
