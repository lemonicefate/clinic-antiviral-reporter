"""Exercise real Tauri IPC, HTTPS and signed NSIS updates with isolated synthetic data."""

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
from threading import Thread
import time
import winreg
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from fastapi.responses import Response
import uvicorn

from service.app import create_app
from service.client_releases import PublishRelease, publish_release
from service.provision import initialize_administrator
from service.settings import Settings


class Credential(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


def manage_generated_certificate(cert: Path, thumbprint: str, *, remove: bool = False) -> None:
    """Confirm only the owned certutil dialog containing the generated fingerprint."""
    process = subprocess.Popen(["certutil", "-user", "-delstore" if remove else "-addstore", "Root", thumbprint if remove else str(cert)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    user32 = ctypes.WinDLL("user32")
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.EnumChildWindows.argtypes = [wintypes.HWND, callback, wintypes.LPARAM]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    @callback
    def collect(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == process.pid:
            texts = []
            @callback
            def child(child_hwnd, _):
                text = ctypes.create_unicode_buffer(8192)
                user32.GetWindowTextW(child_hwnd, text, len(text))
                texts.append(text.value)
                return True
            user32.EnumChildWindows(hwnd, child, 0)
            message = "".join(texts)
            if "Synthetic desktop update " in message and thumbprint.upper() in "".join(message.upper().split()):
                user32.PostMessageW(hwnd, 0x0111, 6, 0)
        return True

    try:
        for _ in range(300):
            if process.poll() is not None:
                if process.returncode: raise RuntimeError("Synthetic certificate store operation failed")
                return
            user32.EnumWindows(collect, 0)
            time.sleep(.1)
        raise RuntimeError("Synthetic certificate confirmation timed out")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def confirm_recovery_dialog(pid: int, expected_executable: Path) -> None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle: raise RuntimeError("Owned recovery process unavailable")
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            raise RuntimeError("Cannot verify recovery process identity")
        if Path(buffer.value).resolve() != expected_executable.resolve(strict=True) or expected_executable.name != "recovery.exe":
            raise RuntimeError("Recovery process identity mismatch")
    finally:
        kernel.CloseHandle(handle)
    user32 = ctypes.WinDLL("user32")
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.EnumChildWindows.argtypes = [wintypes.HWND, callback, wintypes.LPARAM]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    confirmed = []
    @callback
    def collect(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            texts = []
            @callback
            def child(child_hwnd, _):
                text = ctypes.create_unicode_buffer(4096)
                user32.GetWindowTextW(child_hwnd, text, len(text))
                texts.append(text.value)
                return True
            user32.EnumChildWindows(hwnd, child, 0)
            message = "".join(texts)
            if "將回復至 0.1.0" in message and "中央案件與資料庫不會回復舊版" in message and "確定開始安裝" in message:
                if user32.PostMessageW(hwnd, 0x0111, 6, 0): confirmed.append(True)
        return True
    for _ in range(150):
        user32.EnumWindows(collect, 0)
        if confirmed: return
        time.sleep(.1)
    raise RuntimeError("Owned recovery confirmation did not appear")


def run(metadata: Path) -> None:
    if ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError("Use a standard, non-elevated test account")
    repo = Path(__file__).resolve().parents[1]
    releases = json.loads(metadata.read_text(encoding="utf-8"))
    if releases.get("syntheticOnly") is not True:
        raise RuntimeError("Only generated synthetic release metadata is accepted")
    uninstall_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\公費抗病毒藥劑回報"
    preference_key = r"Software\tw.clinic.antiviral-reporter"
    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, uninstall_key):
                raise RuntimeError("Existing installation found; use a clean account")
        except FileNotFoundError:
            pass
    for registry_path, name in ((preference_key, "StartAtLogin"), (run_key, "tw.clinic.antiviral-reporter")):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
                winreg.QueryValueEx(key, name)
                raise RuntimeError("Existing startup preference found; use a clean account")
        except FileNotFoundError:
            pass
    for location in (Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs", Path(os.environ["USERPROFILE"]) / "Desktop"):
        if (location / "公費抗病毒藥劑回報.lnk").exists():
            raise RuntimeError("Existing shortcut found; use a clean account")
    cache = Path(os.environ["LOCALAPPDATA"]) / "tw.clinic.antiviral-reporter/updates"
    if cache.exists():
        raise RuntimeError("Existing update cache found; preserve it and use a clean test account")
    # Retain the cache by rename on its own volume, regardless of TEMP/TMP.
    root = Path(tempfile.mkdtemp(prefix="ClinicReporter Update Acceptance ", dir=cache.parent.parent)).resolve()
    installation = root / "installed"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    endpoint = f"https://127.0.0.1:{port}"
    credential = secrets.token_urlsafe(32)
    settings = Settings.from_environment({"CLINIC_REPORTER_STATE_DIR": str(root / "state"),
        "CLINIC_REPORTER_HIS_SOURCE_PATH": r"\\synthetic-his\data", "CLINIC_REPORTER_BACKUP_ROOT": r"\\synthetic-his\backup"})
    initialize_administrator(settings, "Synthetic update administrator", credential)
    for revision, version in enumerate(("0.1.0", "0.1.1")):
        release = releases["releases"][version]
        publish_release(settings, PublishRelease(requestId=uuid4(), expectedRevision=revision, version=version,
            operator="SYN-UPDATE", reason="Synthetic signed update acceptance"), Path(release["installer"]), Path(release["signature"]))

    certificate_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    certificate_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic desktop update " + uuid4().hex)])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(certificate_subject).issuer_name(certificate_subject).public_key(certificate_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False).sign(certificate_key, hashes.SHA256()))
    cert, private = root / "tls.crt", root / "tls.key"
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(certificate_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    thumbprint = certificate.fingerprint(hashes.SHA1()).hex()
    app = create_app(settings)
    scenario = root / "scenario.json"
    scenario.write_text('{}')

    @app.middleware("http")
    async def synthetic_transport_fault(request, call_next):
        mode = json.loads(scenario.read_text()).get("mode")
        if mode == "truncate" and request.url.path == "/api/v1/client-releases/0.1.1/installer":
            return Response(b"synthetic interrupted response", media_type="application/octet-stream")
        if mode == "disconnect" and request.url.path == "/api/v1/client-releases/0.1.1/installer":
            return Response(b"synthetic short stream", media_type="application/octet-stream",
                            headers={"Content-Length": str(Path(releases["releases"]["0.1.1"]["installer"]).stat().st_size)})
        return await call_next(request)

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, ssl_certfile=str(cert), ssl_keyfile=str(private),
                                         access_log=False, log_level="critical"))
    worker = Thread(target=server.run, daemon=True)
    def stop_on_owned_signal():
        while not server.should_exit:
            try:
                if json.loads(scenario.read_text()).get("mode") == "offline":
                    server.should_exit = True
                    return
            except (OSError, ValueError):
                pass
            time.sleep(.1)
    monitor = Thread(target=stop_on_owned_signal, daemon=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    pointer = ctypes.POINTER(Credential)
    advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pointer)]
    advapi.CredWriteW.argtypes = [pointer, wintypes.DWORD]
    advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    endpoint_target = "central-endpoint.tw.clinic.antiviral-reporter"
    synthetic_target = endpoint + ".tw.clinic.antiviral-reporter"
    old = pointer()
    if not advapi.CredReadW(endpoint_target, 1, 0, ctypes.byref(old)) and ctypes.get_last_error() != 1168:
        raise RuntimeError("Could not preserve existing central endpoint preference")
    existing = pointer()
    if advapi.CredReadW(synthetic_target, 1, 0, ctypes.byref(existing)):
        advapi.CredFree(existing)
        if old: advapi.CredFree(old)
        raise RuntimeError("Synthetic credential name already exists; rerun with another port")
    certificate_added = False
    startup_created = False
    try:
        certificate_added = True
        manage_generated_certificate(cert, thumbprint)
        worker.start()
        for _ in range(100):
            if server.started: break
            if not worker.is_alive(): raise RuntimeError("Synthetic central failed to start")
            time.sleep(.1)
        if not server.started: raise RuntimeError("Synthetic central startup timed out")
        monitor.start()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, preference_key) as key:
            winreg.SetValueEx(key, "StartAtLogin", 0, winreg.REG_DWORD, 0)
        startup_created = True
        first = releases["releases"]["0.1.0"]["installer"]
        subprocess.run(subprocess.list2cmdline([first, "/S"]) + " /D=" + str(installation), check=True,
                       timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        config = root / "acceptance.json"
        config.write_text(json.dumps({"endpoint": endpoint, "credential": credential, "installation": str(installation),
            "cache": str(cache), "scenario": str(scenario), "releases": releases["releases"],
            "python": str(Path(sys.executable)), "repo": str(repo)}), encoding="utf-8")
        subprocess.run(["node", str(repo / "client/e2e-real/signed-updates.cjs"), str(config)], cwd=repo / "client", check=True, timeout=240)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, preference_key) as key:
            assert winreg.QueryValueEx(key, "StartAtLogin")[0] == 0, "Update changed disabled startup preference"
        print("PASS: real native signed update, corrupt/truncated rejection, confirmation, rollback and offline independent recovery.")
    finally:
        primary_error = sys.exception()
        cleanup_errors: list[BaseException] = []

        @contextmanager
        def cleanup_step() -> Iterator[None]:
            try:
                yield
            except Exception as error:
                cleanup_errors.append(error)

        server.should_exit = True
        if worker.is_alive(): worker.join(10)
        if monitor.is_alive(): monitor.join(5)
        with cleanup_step():
            if old:
                try:
                    if not advapi.CredWriteW(old, 0): raise RuntimeError("Restore of original endpoint preference failed")
                finally:
                    advapi.CredFree(old)
            elif not advapi.CredDeleteW(endpoint_target, 1, 0) and ctypes.get_last_error() != 1168:
                raise RuntimeError("Cleanup of synthetic endpoint preference failed")
        with cleanup_step():
            if not advapi.CredDeleteW(synthetic_target, 1, 0) and ctypes.get_last_error() != 1168:
                raise RuntimeError("Cleanup of synthetic device credential failed")
        with cleanup_step():
            # Attempt removal even after an uncertain import outcome; retain the
            # original setup failure and still perform all other cleanup steps.
            if certificate_added:
                manage_generated_certificate(cert, thumbprint, remove=True)
        with cleanup_step():
            uninstaller = installation / "uninstall.exe"
            if uninstaller.is_file():
                if installation.resolve().parent != root or installation.is_symlink():
                    raise RuntimeError("Unexpected uninstall target")
                subprocess.run(subprocess.list2cmdline([str(uninstaller), "/S"]) + " _?=" + str(installation), check=True,
                               timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        with cleanup_step():
            if startup_created:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, preference_key, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, "StartAtLogin")
        # Retain owned evidence and signed packages; never remove prior history.
        with cleanup_step():
            if cache.exists():
                if cache.resolve().parent != (Path(os.environ["LOCALAPPDATA"]) / "tw.clinic.antiviral-reporter").resolve() or cache.is_symlink():
                    raise RuntimeError("Unexpected update cache location")
                cache.rename(root / "retained-update-cache")
        print("Synthetic acceptance evidence retained outside Git: " + str(root))
        if cleanup_errors:
            raise BaseExceptionGroup("Synthetic acceptance cleanup failed", ([primary_error] if primary_error else []) + cleanup_errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metadata", type=Path, nargs="?")
    parser.add_argument("--confirm-recovery", type=int)
    parser.add_argument("--recovery-executable", type=Path)
    arguments = parser.parse_args()
    if arguments.confirm_recovery is not None:
        if arguments.recovery_executable is None: parser.error("--recovery-executable is required")
        confirm_recovery_dialog(arguments.confirm_recovery, arguments.recovery_executable)
    else:
        if arguments.metadata is None: parser.error("metadata is required")
        run(arguments.metadata.resolve(strict=True))
