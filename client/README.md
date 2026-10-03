# Windows client

Tauri 2 with React/TypeScript. The current workflow covers device pairing,
operator attribution, administrator device management, and central outage handling.
The next slice provides a synthetic physician queue, exact chart search, and
explicit case detail selection and confirmed reason editing with conflict review.
Tray/startup behavior, signed installers, and updates remain pending.

## Development

Install Node 24, the Windows Rust toolchain, Visual Studio C++ build tools, and
WebView2. From this directory:

```powershell
npm ci
npm run generate:api
npm run typecheck
npm test
npm run test:e2e
cargo test --locked --manifest-path src-tauri/Cargo.toml
npm run tauri dev
```

Browser tests use installed Microsoft Edge and synthetic native IPC responses.
They do not prove a deployed native client can trust the clinic certificate.
Rust tests use a randomly named temporary Windows Credential Manager entry and
delete it after verification. Build a local executable with
`npm run tauri build -- --debug --no-bundle`; this is not a signed installer.

## Connect and pair

Enter the HTTPS central origin and the operator attribution label. For the first
administrator, choose the initial-device import and enter the key provisioned
offline on the central service. For subsequent devices, an administrator creates
a pairing code with the intended capabilities; enter that code and a device name.
Returning clients use their saved device identity. A fresh pairing rotates the
credential; retrying the same enrollment preserves its pending credential.

The native process stores the central origin and device identity in Windows
Credential Manager and performs HTTPS requests using system certificate trust.
Device keys are not returned to React. The client never receives HIS or backup
paths. Do not disable certificate verification to connect a deployment.

An unavailable or revoked session clears the protected view and directs staff to
the approved paper process. The heartbeat runs every five seconds; native requests
time out after five seconds. The service rejects revoked devices on every request.
There is no offline patient cache, editing, queue, synchronization, or export.

API bindings in `src/generated/api.ts` are generated from
`service/openapi/v1.json`. Domain decisions remain on the central service.
