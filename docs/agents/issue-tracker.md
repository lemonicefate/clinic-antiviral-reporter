# Issue workflow

This repository uses one MVP map issue, milestone issues, and concrete child issues. The map and milestone issues are planning containers; implementation happens in the smallest child issue that has independently checkable acceptance criteria.

## Intake

1. Create the issue with `needs-triage` and state the observed need, scope, acceptance evidence, privacy impact, and known dependencies.
2. Apply `needs-info` when a named external fact or decision is missing. State the exact evidence needed and who can provide it.
3. Move a fully specified implementation task to either `ready-for-agent` or `ready-for-human`. Use only one readiness label.
4. Represent sequencing through GitHub's native sub-issue and blocked-by relationships. Do not encode dependencies only in prose or checklist text.
5. Close only after the issue's evidence is attached or linked. Use `wontfix` when the team explicitly declines the work and record why.

## Required issue content

- Outcome and in-scope behavior
- Acceptance evidence that another person can verify
- M0 gate or open official rule, when relevant
- Tests, documentation, migration, rollback, and privacy effects
- Native parent/sub-issue and blocked-by relationships

Issues involving real SMIS, HIS, devices, certificates, networking, backup destinations, or professional authorization are `ready-for-human`. Code and documentation work based entirely on verified contracts may be `ready-for-agent`.
