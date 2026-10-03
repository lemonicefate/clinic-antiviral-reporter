"""Install, exercise and uninstall an unsigned synthetic NSIS test build as a standard user."""

import argparse
import ctypes
import os
from pathlib import Path
import subprocess
import tempfile
import time
import winreg

from scripts.check_desktop_lifecycle import check


def run(installer: Path) -> None:
    if ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError("Run this acceptance test as a standard, non-elevated Windows user")
    uninstall_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\公費抗病毒藥劑回報"
    preference_key = r"Software\tw.clinic.antiviral-reporter"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, preference_key) as key:
            winreg.QueryValueEx(key, "StartAtLogin")
    except FileNotFoundError:
        pass
    else:
        raise RuntimeError("Existing startup preference found; use a clean test account")
    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as key:
            winreg.QueryValueEx(key, "tw.clinic.antiviral-reporter")
    except FileNotFoundError:
        pass
    else:
        raise RuntimeError("Existing startup command found; use a clean test account")

    def installed(root):
        try:
            with winreg.OpenKey(root, uninstall_key) as key:
                return winreg.QueryValueEx(key, "InstallLocation")[0].strip('"')
        except FileNotFoundError:
            return None

    if any(installed(root) is not None for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)):
        raise RuntimeError("An existing installation was found; use a clean test account")
    for location in (Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs",
                     Path(os.environ["USERPROFILE"]) / "Desktop"):
        if (location / "公費抗病毒藥劑回報.lnk").exists():
            raise RuntimeError("An existing shortcut was found; use a clean test account")
    root = Path(tempfile.mkdtemp(prefix="ClinicReporter Desktop Acceptance ")).resolve()
    destination = root / "installed"
    # NSIS /D= and _?= must be last and unquoted, even with spaces. shell=False
    # passes this command directly to Windows; no shell metacharacters execute.
    command = subprocess.list2cmdline([str(installer), "/S"]) + " /D=" + str(destination)
    try:
        subprocess.run(command, check=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        executable = destination / "clinic-antiviral-reporter.exe"
        assert executable.is_file(), "Installer did not use the isolated per-user destination"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            value = winreg.QueryValueEx(key, "tw.clinic.antiviral-reporter")[0]
        assert value == '"' + str(executable) + '" --autostart', "Fresh installation must enable hidden login startup"
        assert Path(installed(winreg.HKEY_CURRENT_USER)).resolve() == destination.resolve()
        assert installed(winreg.HKEY_LOCAL_MACHINE) is None, "Installer wrote machine-wide registration"
        check(executable, installed_startup=True)
        # A subsequent install must retain the user's disabled preference.
        # Model a prior failed Run removal: preference 0 exists, but its own
        # command remains. Reinstall must complete that intended disable.
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "tw.clinic.antiviral-reporter", 0, winreg.REG_SZ,
                             '"' + str(executable) + '" --autostart')
        subprocess.run(command, check=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            try:
                winreg.QueryValueEx(key, "tw.clinic.antiviral-reporter")
            except FileNotFoundError:
                pass
            else:
                raise AssertionError("Reinstall re-enabled a disabled login preference")
        # Exercise the public uninstaller with an enabled synthetic startup
        # registration as input, after the real menu's enable/disable was tested.
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "tw.clinic.antiviral-reporter", 0, winreg.REG_SZ,
                             '"' + str(executable) + '" --autostart')
    finally:
        uninstaller = destination / "uninstall.exe"
        if uninstaller.is_file():
            if destination.resolve().parent != root or destination.is_symlink():
                raise RuntimeError("Unexpected uninstall target; refusing cleanup")
            command = subprocess.list2cmdline([str(uninstaller), "/S"]) + " _?=" + str(destination)
            subprocess.run(command, check=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
            for _ in range(100):
                if installed(winreg.HKEY_CURRENT_USER) is None:
                    break
                time.sleep(.1)
            assert installed(winreg.HKEY_CURRENT_USER) is None, "Uninstall registration remains"
            assert not (destination / "clinic-antiviral-reporter.exe").exists(), "Client executable remains"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as key:
                try:
                    winreg.QueryValueEx(key, "tw.clinic.antiviral-reporter")
                except FileNotFoundError:
                    pass
                else:
                    raise AssertionError("Uninstall left its startup command behind")
        # Only the preference created by this clean-account test is removed.
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, preference_key, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
                if winreg.QueryValueEx(key, "StartAtLogin")[0] in (0, 1):
                    winreg.DeleteValue(key, "StartAtLogin")
        except FileNotFoundError:
            pass
    print("PASS: non-elevated per-user install, default startup, lifecycle, retained disable and uninstall.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    run(parser.parse_args().installer.resolve(strict=True))
