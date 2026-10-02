# Device/session implementation evidence (in progress)

Issue: https://github.com/lemonicefate/clinic-antiviral-reporter/issues/7

This checkpoint is partial and must not close #7. All test identities are synthetic.

Verified through public service/configuration interfaces on Windows with Python 3.12:

- Unknown devices are denied; operator labels cannot elevate physician capability.
- Administrator-approved pairing creates a device; retry returns the original result.
- Revocation denies an existing session and new session creation immediately.
- Session retry creates one audited event and survives service restart.
- A second state-directory owner and online bootstrap are rejected.
- HTTP is rejected; invalid-body responses do not echo device secrets; the OpenAPI
  document contains neither runtime state nor HIS/backup paths.
- Configuration rejects equal share names, invalid paths, placeholders, invalid
  intervals, and wildcard bind addresses. Export defaults off.
- The original official workbook's hash, sheets, and Eraflu value still pass.

Commands: unittest discovery (12 tests), mypy on service/scripts, generated OpenAPI
and TypeScript bindings, and TypeScript typecheck passed before review.

Still required for #7: desktop pairing/session/device management and credential
storage, explicit client outage clearing, real HTTPS transport integration, broader
conflict/expiry/transaction-failure/migration tests, and final two-axis review.
Production deployment evidence, HIS access, and export remain unverified/disabled.
