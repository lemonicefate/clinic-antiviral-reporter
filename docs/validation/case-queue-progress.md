# Synthetic case queue evidence — #8

Scope: four built-in synthetic orders, two physicians, two independent same-day
orders for one synthetic patient, one prior-day unfinished order. Quantities are
fixed at 10 capsules. No live HIS source was opened, and no official gate is closed.

User reports the preceding connection acceptance environment passed. A user-requested
gpt-6-luna/max read-only inspection identified its service as e44d0f4 and its bridge
as a browser stand-in for native Tauri. It was stopped. Its files and state were
preserved; the new case-queue environment uses a separate LocalAppData directory.

## Automated evidence

- 24 Python tests pass, including distinct cases, exact cross-physician lookup,
  capability/revocation denial, disabled/production refresh gates, request replay,
  refresh conflicts, restart deduplication, raw facts, and v1/v2-to-v3 migration.
- TypeScript and Python type checks; 6 Vitest tests; 2 prior browser regression
  scenarios; 4 native Rust tests including encoded filters and credential storage.
- `client/e2e-real/case-queue.cjs` passed against real local HTTPS API and built React:
  physician filter, exact lookup, detail focus, counts, dedup, outage clearing,
  no browser storage, and restart persistence. Native IPC is modeled by the harness.
- Synthetic screenshots inspected at 1080 and 720px. Windows debug build verified.

## Standards

Parallel review of the #8 changes since e44d0f4 (within the approved be7df98 baseline)
found no concrete documented-standard breach or material maintainability finding.

## Spec

Parallel review found no actionable deviation for the fixed synthetic slice.
The evidence does not cover arbitrary quantities, changed-source reconciliation,
scheduled HIS scanning, or real HIS behavior; those remain future slices/gates.

Standards: 0 actionable findings. Spec: 0 actionable findings.

## Human handoff

The environment and [seven-step manual guide](case-queue-manual.md) are prepared.
At the user's request, the agent also executed the guide's deterministic steps:
no-match/cleared exact search, two independent detail selections, raw snapshot,
Tab/Enter focus, widths 720/1080/1440px, and 125% CSS page zoom. All passed against
the running real HTTPS environment, including outage and recovery. This is browser
automation evidence, not a claim about subjective comfort or native Windows DPI.
The user need not repeat these checks. The committed tests, real-HTTPS journey and
completed review close the synthetic #8 slice. Live HIS identity behavior remains
#23 evidence, and production Excel remains disabled.
