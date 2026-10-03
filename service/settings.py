"""Central-only runtime configuration. Loading settings performs no source I/O."""

from dataclasses import dataclass
from datetime import date
import ipaddress
from pathlib import PureWindowsPath
import re
from typing import Mapping


class SettingsError(ValueError):
    """Invalid runtime configuration, with no sensitive values in the message."""


def _production_host(host: str, *, remote: bool) -> None:
    host = host.casefold().rstrip(".")
    if host == "localhost" or any(host == domain or host.endswith("." + domain)
                                   for domain in ("example.com", "example.net", "example.org", "invalid", "test")):
        raise SettingsError("Production hosts cannot be placeholders")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    documentation = ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")
    if (address.is_unspecified or address.is_multicast or (remote and address.is_loopback)
            or any(address in ipaddress.ip_network(network) for network in documentation)):
        raise SettingsError("Production hosts cannot use documentation or non-routable addresses")


def _path(environment: Mapping[str, str], name: str, *, unc: bool) -> PureWindowsPath:
    value = environment.get("CLINIC_REPORTER_" + name, "")
    normalized = value.replace("/", "\\")
    path = PureWindowsPath(normalized)
    valid_drive = (path.drive.startswith("\\\\") and len(path.drive.split("\\")) == 4
                   if unc else bool(re.fullmatch(r"[A-Za-z]:", path.drive)))
    segments = normalized.split("\\")
    invalid_segment = any(
        part in (".", "..") or part.endswith((" ", "."))
        or any(c in part for c in '<>"|?*')
        or any(ord(c) < 32 for c in part)
        or (":" in part and not (i == 0 and not unc and re.fullmatch(r"[A-Za-z]:", part)))
        for i, part in enumerate(segments) if part
    )
    if not value or not path.is_absolute() or not valid_drive or invalid_segment:
        raise SettingsError(f"{name} must be a plain absolute {'UNC' if unc else 'local Windows'} path")
    return path


@dataclass(frozen=True)
class Settings:
    state_dir: PureWindowsPath
    his_source_path: PureWindowsPath
    backup_root: PureWindowsPath
    environment: str = "development"
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000
    scan_interval_seconds: int = 60
    backup_interval_seconds: int = 1800
    export_enabled: bool = False
    synthetic_enabled: bool = False
    synthetic_dbf_enabled: bool = False
    scan_from_date: date | None = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "Settings":
        state = _path(environment, "STATE_DIR", unc=False)
        source = _path(environment, "HIS_SOURCE_PATH", unc=True)
        backup = _path(environment, "BACKUP_ROOT", unc=True)
        if source.drive.split("\\")[-1].casefold() == backup.drive.split("\\")[-1].casefold():
            raise SettingsError("HIS and backup must use different SMB share names")
        mode = environment.get("CLINIC_REPORTER_ENV", "development")
        if mode not in ("development", "production"):
            raise SettingsError("ENV must be development or production")
        enabled = environment.get("CLINIC_REPORTER_EXPORT_ENABLED", "false")
        if enabled not in ("true", "false"):
            raise SettingsError("EXPORT_ENABLED must be true or false")
        synthetic = environment.get("CLINIC_REPORTER_SYNTHETIC_ENABLED", "false")
        if synthetic not in ("true", "false") or (mode == "production" and synthetic == "true"):
            raise SettingsError("Synthetic fixtures are allowed only in explicit development mode")
        dbf = environment.get("CLINIC_REPORTER_SYNTHETIC_DBF_ENABLED", "false")
        scan_from = None
        if dbf not in ("true", "false") or (dbf == "true" and (mode != "development" or synthetic != "true")):
            raise SettingsError("Synthetic DBF scans require explicit development synthetic mode")
        if dbf == "true":
            try:
                scan_from = date.fromisoformat(environment.get("CLINIC_REPORTER_HIS_SCAN_FROM_DATE", ""))
            except ValueError:
                raise SettingsError("Synthetic DBF scans require an explicit initial date") from None
        host = environment.get("CLINIC_REPORTER_BIND_HOST", "127.0.0.1")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise SettingsError("BIND_HOST must be an explicit IP address") from None
        if address.is_unspecified or address.is_multicast:
            raise SettingsError("BIND_HOST cannot be a wildcard or multicast address")
        if mode == "production":
            for path in (state, source, backup):
                if "replace_with" in str(path).casefold():
                    raise SettingsError("Production paths cannot contain placeholders")
            for path in (source, backup):
                _production_host(path.drive.split("\\")[2], remote=True)
            _production_host(host, remote=False)

        def integer(name: str, default: int, maximum: int) -> int:
            value = environment.get("CLINIC_REPORTER_" + name, str(default))
            if not re.fullmatch(r"[0-9]+", value) or not 1 <= int(value) <= maximum:
                raise SettingsError(f"{name} is outside its supported range")
            return int(value)

        return cls(
            state, source, backup, mode, host,
            integer("BIND_PORT", 8000, 65535),
            integer("HIS_SCAN_INTERVAL_SECONDS", 60, 86400),
            integer("BACKUP_INTERVAL_SECONDS", 1800, 3600),
            enabled == "true",
            synthetic == "true",
            dbf == "true",
            scan_from,
        )
