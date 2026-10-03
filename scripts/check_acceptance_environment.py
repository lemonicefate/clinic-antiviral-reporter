"""Run a read-only preflight for the private synthetic manual-test handoff."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener, ProxyHandler, Request

from scripts.validate_smis_contract_intake import validate as validate_smis


_DIGEST = re.compile(r"^[0-9A-Fa-f]{64}$")
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise URLError("browser URL redirects are not allowed")


def _reparse_path(path: Path) -> Path | None:
    for item in (path, *path.parents):
        try:
            metadata = os.lstat(item)
        except FileNotFoundError:
            continue
        attributes = getattr(metadata, "st_file_attributes", 0)
        if stat.S_ISLNK(metadata.st_mode) or attributes & 0x400:
            return item
    return None


def _private_path(value: Path, repository: Path, label: str) -> Path:
    if not value.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    if (linked := _reparse_path(value)) is not None:
        raise ValueError(f"{label} contains a link or reparse point: {linked.name}")
    resolved = value.resolve(strict=False)
    repository_root = repository.resolve(strict=True)
    if resolved == repository_root or repository_root in resolved.parents:
        raise ValueError(f"{label} must be outside the repository")
    return resolved


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes().decode("utf-8-sig"))
    except FileNotFoundError as error:
        raise ValueError(f"{label} is missing") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _desktop(metadata_path: Path, repository: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    details: dict[str, Any] = {"metadata": metadata_path.name, "ready": False}
    try:
        metadata = _load_json(metadata_path, "desktop metadata")
    except ValueError as error:
        return details, [str(error)]
    if metadata.get("syntheticOnly") is not True:
        errors.append("desktop metadata must declare syntheticOnly=true")
    executable_value = metadata.get("executable")
    if not isinstance(executable_value, str) or not executable_value:
        errors.append("desktop metadata executable is missing")
    else:
        executable = Path(executable_value)
        try:
            executable = _private_path(executable, repository, "desktop executable")
            details["executableExists"] = executable.is_file()
            if not executable.is_file():
                errors.append("desktop executable is missing")
        except ValueError as error:
            errors.append(str(error))
            details["executableExists"] = False
    expected = metadata.get("executableSha256")
    if not isinstance(expected, str) or not _DIGEST.fullmatch(expected):
        details["hashMatches"] = False
        errors.append("desktop metadata executableSha256 is invalid")
    elif details.get("executableExists"):
        actual = _sha256(executable)
        details["hashMatches"] = actual == expected.upper()
        if actual != expected.upper():
            errors.append("desktop executable SHA-256 does not match metadata")
    else:
        details["hashMatches"] = False
    details["version"] = metadata.get("version")
    details["ready"] = not errors
    return details, errors


def _browser(metadata_path: Path, *, check_health: bool, timeout: float) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    details: dict[str, Any] = {"metadata": metadata_path.name, "healthChecked": check_health, "ready": False}
    try:
        metadata = _load_json(metadata_path, "browser metadata")
    except ValueError as error:
        return details, [str(error)]
    url = metadata.get("url")
    if not isinstance(url, str) or not url:
        errors.append("browser metadata url is missing")
        details["urlValid"] = False
    else:
        parts = urlsplit(url)
        try:
            port = parts.port
        except ValueError:
            port = None
            errors.append("browser URL has an invalid port")
        host = parts.hostname.casefold() if parts.hostname else None
        valid = (parts.scheme == "http" and host in _LOCAL_HOSTS and port is not None
                 and not parts.username and not parts.password and not parts.query and not parts.fragment)
        details["urlValid"] = valid
        if not valid:
            errors.append("browser URL must be an HTTP loopback URL without credentials or fragments")
        elif check_health:
            try:
                request = Request(url, method="GET")
                opener = build_opener(ProxyHandler({}), _NoRedirectHandler())
                with opener.open(request, timeout=timeout) as response:
                    details["httpStatus"] = response.status
                if details["httpStatus"] != 200:
                    errors.append("browser URL did not return HTTP 200")
            except HTTPError as error:
                details["httpStatus"] = error.code
                errors.append(f"browser URL returned HTTP {error.code}")
            except (URLError, OSError, TimeoutError) as error:
                errors.append(f"browser URL health check failed: {error}")
    details["ready"] = not errors
    return details, errors


def _smis(kit_path: Path, repository: Path) -> tuple[dict[str, Any], list[str]]:
    result = validate_smis(kit_path, repository=repository)
    details = {"status": "COMPLETE" if result.complete else "OPEN",
               "openScenarios": list(result.open_scenarios),
               "completedScenarios": list(result.completed_scenarios),
               "ready": not result.errors}
    return details, list(result.errors)


def preflight(desktop_metadata: Path, browser_metadata: Path, smis_kit: Path, *,
              repository: Path | None = None, check_browser: bool = True,
              timeout: float = 5.0) -> dict[str, Any]:
    repository_root = (repository or Path(__file__).resolve().parents[1]).resolve(strict=True)
    errors: list[str] = []
    try:
        desktop_path = _private_path(desktop_metadata, repository_root, "desktop metadata")
        desktop, desktop_errors = _desktop(desktop_path, repository_root)
    except (OSError, ValueError) as error:
        desktop = {"metadata": desktop_metadata.name, "ready": False}
        desktop_errors = [str(error)]
    errors.extend(f"desktop: {error}" for error in desktop_errors)
    try:
        browser_path = _private_path(browser_metadata, repository_root, "browser metadata")
        browser, browser_errors = _browser(browser_path, check_health=check_browser, timeout=timeout)
    except (OSError, ValueError) as error:
        browser = {"metadata": browser_metadata.name, "healthChecked": check_browser, "ready": False}
        browser_errors = [str(error)]
    errors.extend(f"browser: {error}" for error in browser_errors)
    smis, smis_errors = _smis(smis_kit, repository_root)
    errors.extend(f"smis: {error}" for error in smis_errors)
    return {"status": "READY_FOR_MANUAL" if not errors else "BLOCKED",
            "syntheticOnly": True, "productionExportEnabled": False,
            "desktop": desktop, "browser": browser, "smis": smis, "errors": errors}


def _default_paths() -> tuple[Path, Path, Path]:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        missing = Path("__missing_local_app_data__")
        return missing / "desktop-v1" / "current.json", missing / "case-queue-v1" / "current.json", missing / "smis-contract-v1"
    root = Path(local_app_data) / "ClinicReporterAcceptance"
    return (root / "desktop-v1" / "current.json", root / "case-queue-v1" / "current.json",
            root / "smis-contract-v1")


def main() -> None:
    defaults = _default_paths()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop-metadata", type=Path, default=defaults[0])
    parser.add_argument("--browser-metadata", type=Path, default=defaults[1])
    parser.add_argument("--smis-kit", type=Path, default=defaults[2])
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--no-browser-health", action="store_true",
                        help="Validate the local URL shape without making a request")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        result = preflight(args.desktop_metadata, args.browser_metadata, args.smis_kit,
                           check_browser=not args.no_browser_health, timeout=args.timeout)
    except (OSError, ValueError) as error:
        result = {"status": "BLOCKED", "syntheticOnly": True,
                  "productionExportEnabled": False, "errors": [str(error)]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["status"] != "READY_FOR_MANUAL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
