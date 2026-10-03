# HIS adapter

The clean-room adapter is implemented in `service/his_reader.py`, with the central
worker in `service/scanner.py`. Its authoritative rules remain in
[`docs/integrations/his-read-contract.md`](../docs/integrations/his-read-contract.md).

Only explicitly enabled development scans of generated synthetic DBF files are
supported. Production source activation, dialect/encoding/date representations,
stable identity and live locking/load remain M0 gates. Read the
[evidence and reproduction guide](../docs/validation/scanner-progress.md) before
using the test scanner. The service never invokes fixture-generation writes.
