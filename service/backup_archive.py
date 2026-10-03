"""Versioned backup inventory and non-overwriting publication helpers."""

from dataclasses import asdict
import hashlib
import json
import math
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
from uuid import UUID

from service.settings import Settings


ENVIRONMENT_FIELDS = {
    "state_dir": "STATE_DIR", "his_source_path": "HIS_SOURCE_PATH", "backup_root": "BACKUP_ROOT",
    "environment": "ENV", "bind_host": "BIND_HOST", "bind_port": "BIND_PORT",
    "scan_interval_seconds": "HIS_SCAN_INTERVAL_SECONDS", "backup_interval_seconds": "BACKUP_INTERVAL_SECONDS",
    "export_enabled": "EXPORT_ENABLED", "synthetic_enabled": "SYNTHETIC_ENABLED",
    "synthetic_dbf_enabled": "SYNTHETIC_DBF_ENABLED", "scan_from_date": "HIS_SCAN_FROM_DATE",
    "backup_enabled": "BACKUP_ENABLED", "synthetic_backup_enabled": "SYNTHETIC_BACKUP_ENABLED",
}


class BackupError(RuntimeError):
    """Safe diagnostic; never include filenames or source exception messages."""


def reject_reparse(path: Path) -> None:
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            if item.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise BackupError("unsafe_backup_path")


def copy_new(source: Path, destination: Path) -> None:
    reject_reparse(source)
    reject_reparse(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing)
        outgoing.flush()
        os.fsync(outgoing.fileno())


def write_new(path: Path, value: bytes) -> None:
    reject_reparse(path)
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def discard_staging(directory: Path, expected_parent: Path, expected_name: str) -> None:
    if not directory.exists():
        return
    reject_reparse(directory)
    if directory.name != expected_name or directory.resolve().parent != expected_parent.resolve():
        raise BackupError("unsafe_staging_cleanup")
    # Check the entire owned tree before deletion; never follow a substituted
    # junction/symlink into another directory, source, or prior restored service.
    list(artifact_files(directory))
    shutil.rmtree(directory)


def fingerprint(path: Path) -> dict:
    reject_reparse(path)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return {"sha256": digest.hexdigest(), "size": size}


def artifact_files(root: Path):
    reject_reparse(root)
    if root.exists():
        for item in sorted(root.iterdir()):
            reject_reparse(item)
            if item.is_dir():
                yield from artifact_files(item)
            elif item.is_file():
                yield item
            else:
                raise BackupError("invalid_artifact")


def check_database(path: Path) -> None:
    db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchall():
            raise BackupError("invalid_database")
        if db.execute("PRAGMA user_version").fetchone()[0] > 10:
            raise BackupError("unsupported_schema")
    finally:
        db.close()


def runtime_configuration(settings: Settings) -> dict:
    # Only effective service settings, never unrelated process environment secrets.
    values = asdict(settings)
    if set(values) != set(ENVIRONMENT_FIELDS):
        raise BackupError("unsupported_configuration")
    return {"format": 1, "settings": {
        key: str(value) if value is not None and not isinstance(value, (str, int, bool)) else value
        for key, value in values.items()}}


def read_configuration(snapshot: dict) -> dict:
    if snapshot.get("format") != 1 or not isinstance(snapshot.get("settings"), dict):
        raise BackupError("unsupported_configuration")
    settings = snapshot["settings"]
    if not {"state_dir", "his_source_path", "backup_root", "environment"} <= settings.keys() or not settings.keys() <= ENVIRONMENT_FIELDS.keys():
        raise BackupError("unsupported_configuration")
    return settings


def inventory_path(name: str) -> bool:
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or str(path) != name or "\\" in name or ":" in name
            or any(part in (".", "..") or part.endswith((".", " ")) or
                   any(ord(char) < 32 or char in '<>"|?*' for char in part) or
                   part.split(".")[0].casefold() in {"con", "prn", "aux", "nul", "conin$", "conout$"} or
                   re.fullmatch(r"(?:com|lpt)[1-9¹²³]", part.split(".")[0], flags=re.IGNORECASE)
                   for part in path.parts)):
        return False
    return name in ("central.sqlite3", "runtime.json", "tls.crt", "tls.key") or (
        len(path.parts) > 1 and path.parts[0] == "immutable-artifacts")


def verify_archive(directory: Path, *, published: bool = True) -> dict:
    reject_reparse(directory)
    manifest_path = directory / "manifest.json"
    reject_reparse(manifest_path)
    if manifest_path.stat().st_size > 8 * 1024 * 1024:
        raise BackupError("invalid_manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("format") != 1 or str(UUID(manifest["backupId"])) != manifest["backupId"] or
            (published and directory.name != "backup-" + manifest["backupId"]) or
            not isinstance(manifest.get("snapshotAt"), (int, float)) or
            not isinstance(manifest.get("completedAt"), (int, float)) or
            not math.isfinite(manifest["snapshotAt"]) or not math.isfinite(manifest["completedAt"]) or
            not 0 < manifest["snapshotAt"] <= manifest["completedAt"]):
        raise BackupError("invalid_manifest")
    files = manifest["files"]
    if not isinstance(files, dict) or not {"central.sqlite3", "runtime.json"} <= files.keys():
        raise BackupError("incomplete_inventory")
    if ("tls.crt" in files) != ("tls.key" in files):
        raise BackupError("incomplete_inventory")
    if len({name.casefold() for name in files}) != len(files):
        raise BackupError("invalid_inventory")
    for name, expected in files.items():
        if not inventory_path(name) or fingerprint(directory / name) != expected:
            raise BackupError("backup_integrity_failed")
    return manifest
