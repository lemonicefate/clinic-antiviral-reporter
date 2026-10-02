# Agent guide

Read `tw-flu-antiviral-reporter_SPEC_v1.0.md` and its authoritative v1.1 amendment before changing product behavior. Read `CONTEXT.md` before naming domain concepts.

- For issue creation or status changes, follow `docs/agents/issue-tracker.md`; for label meaning, follow `docs/agents/triage-labels.md`.
- For commands, revisions, case states, exports, or source synchronization, follow `docs/agents/domain.md` and the ADRs under `docs/adr/`.
- Use only synthetic or irreversibly de-identified test data. Keep patient data, DBF/FPT/CDX files, credentials, deployment configuration, generated Excel files, logs, and backups out of Git.
- Treat HIS as read-only. Preserve every source version and every human-entered reason, lot allocation, exclusion decision, and export version.
- Keep production Excel export disabled until every M0 export gate is evidenced, including a synthetic outpatient import accepted by SMIS. Mark unknown official behavior `OPEN`; never infer it.
- Rebuild integrations clean-room. Consult private `HIS-pro` only to establish verified contracts and observable behavior; do not copy its code, comments, tests, or non-public data into this repository.
- Target Python 3.12/FastAPI for the central service and Tauri 2 with React/TypeScript for the Windows client. Generate the TypeScript client from versioned OpenAPI; keep domain decisions on the service.
- Run `python -m unittest discover -s tests -v` after changing repository fixtures or their integrity checks.
