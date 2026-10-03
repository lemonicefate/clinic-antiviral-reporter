# Windows desktop lifecycle (#21, in progress)

The Windows client uses a per-user NSIS package, a native tray and application menu,
and a single running instance. Closing the window hides it; 「結束回報工具」 exits.
Opening a second copy restores the first window. The native
「Windows 登入時啟動並縮至系統列」 menu option controls current-user Windows startup;
launches with `--autostart` stay hidden until the user opens the tray icon. Repeated
autostart launches do not bring a window over ongoing work.

First installation under the fixed Windows account enables login startup. The
user can disable it in the native menu; a retained `StartAtLogin` preference keeps
later installs/upgrades from re-enabling that choice. Its
check mark is read back from the current-user Run entry, and failed changes display an error in the
menu. Ordinary launches never silently enable a previously disabled option.
Uninstall removes only a Run command pointing to that installation, while retaining
the allowed startup preference for reinstall/rollback.
Windows Startup Apps / Task Manager or clinic policy can additionally block login
startup. The application does not bypass those controls; verify actual login under
the fixed account and have its administrator resolve any policy conflict.

## Build and test

From `client`, run `npm run tauri -- build --debug` to create an NSIS test installer,
or add `--no-bundle` to build only the executable. Build outputs stay ignored.
The installer is configured for `currentUser`; do not run it under another account
or with elevated administrator credentials. WebView2 is a prerequisite managed by
the Windows installer/runtime bootstrapper; target-account installation evidence
must include machines with and without an existing runtime.

`python -m scripts.check_desktop_lifecycle <absolute-executable-path>` exercises the
actual Windows window boundary with no central connection or patient data. It owns
the process it launches and never attaches to an existing client. Close existing
test clients first. Keep native tests separate from real clinic operations.

`python -m scripts.check_desktop_installation <absolute-installer-path>` refuses an
elevated account or existing installation, installs into an isolated temporary
directory with spaces, runs the lifecycle checks on the installed executable, and
uninstalls. It verifies HKCU registration and absence of HKLM registration. The
lifecycle test refuses an existing autostart preference and cleans only the exact
Run value it created. Temporary installer remnants are retained outside Git.

On 2026-10-03, the original build failed the native Close test because it exited.
The implemented build passed close/hide, single-instance restore, explicit quit,
quoted HKCU startup, hidden startup, duplicate startup and disable checks. The
non-elevated NSIS install/lifecycle/uninstall test passed with existing WebView2.
The fresh-install startup assertion also failed before installer hooks were added,
then passed. Reinstall now demonstrably retains an explicit disabled preference;
uninstall removes an enabled command that points to its own executable.
The reinstall regression also seeds a retained disabled preference with a stale
matching Run command (representing a prior removal failure), and verifies that
reinstall removes it. Preference-save failures leave Run untouched; later Run
failures show an error/readback and installer failures return a nonzero exit code.
An intermittent hidden-startup activation failure prompted a follow-up: activation
requests received before main-window readiness are retained until setup completes,
and the test waits for the actual hidden window/menu instead of sleeping two
seconds. The full install/lifecycle/reinstall/uninstall sequence then passed three
consecutive runs. This is bounded regression evidence, not proof of every timing.
The current recheck on 2026-10-04 passes 128 Python tests, 5 Rust tests and mypy across 35 source
files. Native tray left/right clicks and an
actual Windows sign-out/sign-in remain manual checks; the native automation checks
the application menu and process/window behavior. The available GUI automation
provider reports tray/menu surfaces unsupported, so no tray-click success is claimed.

## Manual acceptance

Use the supplied synthetic test build and fixed test Windows account:

1. Install the NSIS package without elevation. Confirm installation belongs to the
   current account and can launch from the Start menu. Record the build version.
2. Close the window with its title-bar X. Confirm the process and tray icon remain;
   left-click the tray icon to reopen. Right-click exposes open, startup and quit.
3. Enable login startup through 「程式」. Explicitly quit, sign out and sign back in
   to the test account. Confirm a tray icon appears with no foreground window.
4. Open the app, disable startup, quit and sign out/in again. Confirm it stays off.
   Re-enable it only if that is the clinic's intended preference.
5. Launch the app twice. Confirm only one client remains and the original window
   is restored. Explicit quit must remove its process and tray icon.

No central schema migration is introduced. Client updates must preserve the
Credential Manager identity and allowed preferences; uninstalling or downgrading
must never touch central history. Disable autostart before moving a test executable
or removing a test installation, so Windows does not retain a stale startup path.

## 本次已準備的人工測試環境

2026-10-03 20:05（Asia/Taipei）已在安裝／更新自動測試後重新準備測試版，
核對 EXE 的 SHA-256 並以 `--autostart` 啟動（準備時 PID 10548）。
檔案位置、雜湊與程序編號記錄於
`%LOCALAPPDATA%\ClinicReporterAcceptance\desktop-v1\current.json`，與瀏覽器
合成測試環境分開。測試版已啟動，不需自行建置；若已結束，可依 metadata
中的 `executable` 重新開啟。這是只供測試的 debug EXE，不能當成正式部署。

**系統列操作（不需登入中央服务）：**

1. 查看 Windows 右下角通知區；若圖示被收起，先按「顯示隱藏的圖示」。
   將滑鼠停在圖示上，預期提示「公費抗病毒藥劑回報」。若沒有圖示，
   記錄失敗，不要以工作管理員仍有程序代替圖示驗收。
2. 左鍵點該圖示，預期開啟連線畫面。不要填入真實病人資料或裝置金鑰。
3. 按視窗右上角 X，預期視窗消失、圖示保留；再次左鍵點擊應開啟原視窗。
4. 右鍵點圖示，預期包含「開啟回報工具」、Windows 登入自啟選項、
   「結束回報工具」。選「結束回報工具」，預期視窗與該圖示都消失。
5. 若要繼續下一段，從上述 `current.json` 找到 `executable` 並開啟。

**真正的 Windows 登入自啟（需你自行保存其他工作，再登出）：**

1. 開啟視窗的「程式」選單，勾選「Windows 登入時啟動並縮至系統列」。
   確認選項出現勾號；若顯示設定失敗，先記錄，不要繼續宣稱成功。
2. 明確結束工具，保存其他程式的工作後，自行登出並重新登入同一個測試
   Windows 帳號。預期有系統列圖示，且沒有回報工具視窗自動搶到前景。
3. 左鍵圖示開啟，取消自啟勾選，明確結束，再登出／登入。
   預期不再自動執行。若 Windows「啟動應用程式」或管理政策曾禁用此項，
   請由現場管理員核對；本程式不會繞過該限制。
4. 測完維持自啟關閉並結束測試版，避免留下指向暫存目錄的登入項目。
   正式安裝後才在固定 Windows 帳號重新設定所需偏好。

上述 sign-out 操作會影響整個工作階段，因此沒有由自動化代你執行。
免管理員安裝、含空白路徑、自啟登錄項目、原生視窗操作及移除，均已自動測試。

## Remaining local manual evidence

The central release catalog and authorized download API are now implemented;
see [release distribution progress](desktop-release-progress.md) for its separate
evidence and maintenance procedure.

Startup update checks, confirmation, signature validation, retained rollback
packages and corrupt/interrupted update rehearsal are now implemented and tested;
see the separate release evidence above. Central Windows-service startup/recovery
and client deployment are documented in
[Windows deployment](../deployment/windows-service-and-client.md). Do not distribute
this unsigned test executable as a production release or use it as clinic deployment
evidence. Actual account, device,
certificate and operational cutover acceptance remains in #25.

Implementation references: [Tauri system tray](https://v2.tauri.app/learn/system-tray/),
[single instance](https://v2.tauri.app/plugin/single-instance/), and
[Windows installer](https://v2.tauri.app/distribute/windows-installer/).
