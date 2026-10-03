"""Exercise the built Windows client through its native window/menu boundary.

Uses no central connection or patient data. Refuses to attach to existing clients.
"""

import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import time
import winreg


def check(executable: Path, installed_startup: bool = False) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetMenu.argtypes = [wintypes.HWND]
    user32.GetMenu.restype = wintypes.HMENU
    user32.GetSubMenu.argtypes = [wintypes.HMENU, ctypes.c_int]
    user32.GetSubMenu.restype = wintypes.HMENU
    user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
    user32.GetMenuItemID.argtypes = [wintypes.HMENU, ctypes.c_int]
    user32.GetMenuItemID.restype = wintypes.UINT
    user32.GetMenuStringW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.LPWSTR, ctypes.c_int, wintypes.UINT]
    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    startup_name = "tw.clinic.antiviral-reporter"
    preference_key = r"Software\tw.clinic.antiviral-reporter"
    if not installed_startup:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, preference_key) as key:
                winreg.QueryValueEx(key, "StartAtLogin")
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError("Existing startup preference found; use a clean test account")

    def startup_value(root=winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, run_key) as key:
                return winreg.QueryValueEx(key, startup_name)[0]
        except FileNotFoundError:
            return None

    expected_command = '"' + str(executable) + '" --autostart'
    if startup_value() is not None and not (installed_startup and startup_value() == expected_command):
        raise RuntimeError("Existing startup preference found; use a clean test account instead of overwriting it")
    system_startup = startup_value(winreg.HKEY_LOCAL_MACHINE)

    def menu_command(hwnd, label):
        def find(menu):
            for index in range(user32.GetMenuItemCount(menu)):
                text = ctypes.create_unicode_buffer(256)
                user32.GetMenuStringW(menu, index, text, len(text), 0x400)
                if text.value == label:
                    return user32.GetMenuItemID(menu, index)
                child = user32.GetSubMenu(menu, index)
                if child:
                    result = find(child)
                    if result is not None:
                        return result
            return None
        item = find(user32.GetMenu(hwnd))
        assert item is not None, "Native menu item missing: " + label
        user32.PostMessageW(hwnd, 0x0111, item, 0)  # Same command as a native menu click.

    def windows(pid):
        found = []
        @callback_type
        def collect(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, len(title))
            if owner.value == pid and title.value == "公費抗病毒藥劑回報" and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True
        user32.EnumWindows(collect, 0)
        return found

    def wait_for(predicate, message):
        for _ in range(100):
            if predicate():
                return
            time.sleep(.1)
        raise AssertionError(message)

    owned = []
    def launch(*arguments):
        process = subprocess.Popen([str(executable), *arguments], creationflags=subprocess.CREATE_NO_WINDOW)
        owned.append(process)
        return process

    process = launch()
    try:
        wait_for(lambda: windows(process.pid), "Owned client window did not open (close existing clients first)")
        hwnd = windows(process.pid)[0]
        if installed_startup:
            menu_command(hwnd, "Windows 登入時啟動並縮至系統列")
            wait_for(lambda: startup_value() is None, "Initial default startup could not be disabled")
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # Native title-bar Close.
        wait_for(lambda: not windows(process.pid), "Close did not hide the window")
        time.sleep(.5)
        assert process.poll() is None, "Close terminated the client instead of keeping the tray process"
        second = launch()
        assert second.wait(timeout=10) == 0, "Second launch did not hand off to the first client"
        wait_for(lambda: windows(process.pid), "Second launch did not restore the first window")
        hwnd = windows(process.pid)[0]
        menu_command(hwnd, "Windows 登入時啟動並縮至系統列")
        expected = '"' + str(executable) + '" --autostart'
        wait_for(lambda: startup_value() == expected, "Per-user startup command was not saved with a quoted path")
        assert startup_value(winreg.HKEY_LOCAL_MACHINE) == system_startup, "System startup entry changed"
        menu_command(hwnd, "結束回報工具")
        assert process.wait(timeout=10) == 0, "Explicit quit failed"
        process = launch("--autostart")
        time.sleep(2)
        assert process.poll() is None and not windows(process.pid), "Login startup must remain in the tray"
        duplicate = launch("--autostart")
        assert duplicate.wait(timeout=10) == 0
        assert not windows(process.pid), "Repeated login startup interrupted the desktop"
        second = launch()
        assert second.wait(timeout=10) == 0
        wait_for(lambda: windows(process.pid), "Manual launch did not restore the hidden client")
        hwnd = windows(process.pid)[0]
        menu_command(hwnd, "Windows 登入時啟動並縮至系統列")
        wait_for(lambda: startup_value() is None, "Disabling startup did not remove the per-user command")
        menu_command(hwnd, "結束回報工具")
        assert process.wait(timeout=10) == 0
        print("PASS: close-to-tray, single instance, explicit quit, quoted per-user startup, hidden login and disable.")
    finally:
        for process in owned:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
        # Remove only the exact synthetic command created by this test, even if
        # an assertion failed. Preserve any concurrent operator change.
        if startup_value() == '"' + str(executable) + '" --autostart':
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, startup_name)
        if not installed_startup:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, preference_key, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
                    if winreg.QueryValueEx(key, "StartAtLogin")[0] in (0, 1):
                        winreg.DeleteValue(key, "StartAtLogin")
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    check(parser.parse_args().executable.resolve(strict=True))
