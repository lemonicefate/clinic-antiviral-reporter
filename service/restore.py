"""Offline restore into a new local directory; never replace current central state."""

import argparse
import ctypes
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from service.backup_archive import (BackupError, ENVIRONMENT_FIELDS, check_database, copy_new, discard_staging,
                                    read_configuration, reject_reparse, verify_archive, write_new)
from service.settings import Settings


def recovery_environment(configuration: dict, destination: Path) -> dict[str, str]:
    environment = {"CLINIC_REPORTER_" + ENVIRONMENT_FIELDS[key]: str(value).lower() if isinstance(value, bool) else str(value)
                   for key, value in configuration.items() if value is not None}
    Settings.from_environment(environment)
    environment.update({"CLINIC_REPORTER_STATE_DIR": str(destination), "CLINIC_REPORTER_BIND_HOST": "127.0.0.1",
                        "CLINIC_REPORTER_BACKUP_ENABLED": "false", "CLINIC_REPORTER_SYNTHETIC_BACKUP_ENABLED": "false",
                        "CLINIC_REPORTER_SYNTHETIC_DBF_ENABLED": "false", "CLINIC_REPORTER_EXPORT_ENABLED": "false"})
    Settings.from_environment(environment)
    return environment


def restore_backup(archive: Path, destination: Path, operator: str) -> None:
    if not archive.is_absolute() or not destination.is_absolute() or not operator.strip() or len(operator) > 100:
        raise BackupError("invalid_restore_request")
    drive_type = ctypes.windll.kernel32.GetDriveTypeW
    drive_type.argtypes = [ctypes.c_wchar_p]
    drive_type.restype = ctypes.c_uint
    if str(destination).startswith("\\\\") or drive_type(destination.anchor) != 3:
        raise BackupError("restore_requires_local_disk")
    reject_reparse(destination)
    if destination.exists():
        raise BackupError("restore_destination_exists")
    manifest = verify_archive(archive)
    configuration = read_configuration(json.loads((archive / "runtime.json").read_text(encoding="utf-8")))
    if (destination.resolve().is_relative_to(Path(configuration["state_dir"]).resolve()) or
            destination.resolve().is_relative_to(archive.resolve())):
        raise BackupError("restore_requires_isolation")
    environment = recovery_environment(configuration, destination)
    restore_id = str(uuid4())
    staging = destination.parent / (".restore-pending-" + restore_id)
    reject_reparse(staging)
    staging.mkdir(parents=True)
    try:
        for name in manifest["files"]:
            copy_new(archive / name, staging / name)
        copy_new(archive / "manifest.json", staging / "manifest.json")
        verify_archive(staging, published=False)
        check_database(staging / "central.sqlite3")
        db = sqlite3.connect(staging / "central.sqlite3")
        try:
            with db:
                recorded = db.execute("SELECT 1 FROM backup_runs WHERE id=?", (manifest["backupId"],)).fetchone()
                if recorded is None:
                    raise BackupError("backup_history_mismatch")
                # Its own snapshot necessarily precedes the live 'ready' update.
                # The verified published manifest proves that this run completed.
                db.execute("UPDATE backup_runs SET status='ready',snapshot_at=?,finished_at=?,diagnostic=NULL WHERE id=?",
                           (manifest["snapshotAt"], manifest["completedAt"], manifest["backupId"]))
                db.execute("UPDATE backup_state SET revision=revision+1 WHERE id=1")
                db.execute("UPDATE sessions SET expires_at=0")
                db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                           ("backup_restored", "restore-tool", operator, time.time(), json.dumps({
                               "restoreId": restore_id, "backupId": manifest["backupId"], "snapshotAt": manifest["snapshotAt"],
                               "verifiedCompletionAt": manifest["completedAt"], "sessionsInvalidated": True})))
        finally:
            db.close()
        write_new(staging / "recovery.env", ("\n".join(key + "=" + json.dumps(value, ensure_ascii=False)
                                                      for key, value in environment.items()) + "\n").encode("utf-8"))
        (staging / "manifest.json").rename(staging / "restored-from-manifest.json")
        staging.rename(destination)
    finally:
        discard_staging(staging, destination.parent, ".restore-pending-" + restore_id)


def main():
    parser = argparse.ArgumentParser(description="Restore a verified backup into a new isolated local directory")
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--operator", required=True)
    args = parser.parse_args()
    try:
        restore_backup(args.backup, args.destination, args.operator)
    except Exception as error:
        diagnostic = str(error) if isinstance(error, BackupError) else "restore_failed"
        parser.exit(1, diagnostic + "\n")
    print("Restore verified. Review recovery.env and ACLs before starting the isolated service; backups, scans and exports are disabled.")


if __name__ == "__main__":
    main()
