import json
import hashlib
from dataclasses import replace
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from service.app import create_app
from service.provision import initialize_administrator
from service.settings import Settings


class BackupWorkflowTest(unittest.TestCase):
    def test_restore_accepts_version_one_configuration_with_missing_optional_settings(self):
        status = self.wait_backup()
        archive = Path(self.settings.state_dir) / "synthetic-backups" / ("backup-" + status["backupId"])
        runtime = archive / "runtime.json"
        snapshot = json.loads(runtime.read_text())
        for name in ("scan_from_date", "backup_enabled", "synthetic_backup_enabled", "scan_interval_seconds"):
            snapshot["settings"].pop(name)
        encoded = json.dumps(snapshot).encode()
        runtime.write_bytes(encoded)
        manifest = json.loads((archive / "manifest.json").read_text())
        manifest["files"]["runtime.json"] = {"sha256": hashlib.sha256(encoded).hexdigest(), "size": len(encoded)}
        (archive / "manifest.json").write_text(json.dumps(manifest))
        destination = self.directory / "compatible-restore"
        process = subprocess.run([sys.executable, "-m", "service.restore", "--backup", str(archive),
                                  "--destination", str(destination), "--operator", "SYN-RESTORE"], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        from dotenv import dotenv_values
        config = Settings.from_environment({k: v for k, v in dotenv_values(destination / "recovery.env", interpolate=False).items() if v is not None})
        self.assertEqual(config.scan_interval_seconds, 60)
        self.assertFalse(config.backup_enabled)

    def test_failed_restore_cleans_only_its_own_staging_and_preserves_archive(self):
        from service.restore import restore_backup
        status = self.wait_backup()
        archive = Path(self.settings.state_dir) / "synthetic-backups" / ("backup-" + status["backupId"])
        before = (archive / "central.sqlite3").read_bytes()
        sentinel = self.directory / "unrelated"
        sentinel.mkdir()
        (sentinel / "preserve.txt").write_text("synthetic unrelated data")
        original_open = Path.open
        def disk_error(path, mode="r", *args, **kwargs):
            if "x" in mode and path.name == "tls.key" and path.parent.name.startswith(".restore-pending-"):
                raise OSError("Synthetic restore disk failure")
            return original_open(path, mode, *args, **kwargs)
        with patch.object(Path, "open", disk_error), self.assertRaises(OSError):
            restore_backup(archive, self.directory / "failed-restore", "SYN-RESTORE")
        self.assertEqual(list(self.directory.glob(".restore-pending-*")), [])
        self.assertFalse((self.directory / "failed-restore").exists())
        self.assertEqual((archive / "central.sqlite3").read_bytes(), before)
        self.assertEqual((sentinel / "preserve.txt").read_text(), "synthetic unrelated data")

    def test_capability_disabled_mode_and_replay_after_restart(self):
        first = self.wait_backup()
        grant = self.client.post("/api/v1/pairings", headers=self.headers, json={
            "requestId": str(uuid4()), "expectedRevision": 0, "capabilities": ["reporting"]}).json()
        key = secrets.token_urlsafe(32)
        self.client.post("/api/v1/devices/enroll", json={"requestId": str(uuid4()), "expectedRevision": 0,
            "pairingCode": grant["pairingCode"], "credential": key, "name": "Synthetic unauthorized backup client"})
        session = self.client.post("/api/v1/sessions", headers={"Authorization": "Bearer " + key}, json={
            "requestId": str(uuid4()), "expectedRevision": 0, "operator": "SYN-BACKUP-ADMIN"}).json()
        unauthorized = {"Authorization": "Bearer " + key, "X-Session-Id": session["sessionId"]}
        command = {"requestId": str(uuid4()), "expectedRevision": first["revision"], "reason": "Synthetic request"}
        self.assertEqual(self.client.get("/api/v1/backups/status", headers=unauthorized).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/backups", headers=unauthorized, json=command).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/backups/status").status_code, 401)
        accepted = self.client.post("/api/v1/backups", headers=self.headers, json=command).json()
        self.wait_backup()
        self.client.__exit__(None, None, None)
        try:
            disabled = replace(self.settings, backup_enabled=False, synthetic_backup_enabled=False)
            with TestClient(create_app(disabled), base_url="https://testserver") as restarted:
                status = restarted.get("/api/v1/backups/status", headers=self.headers).json()
                self.assertEqual(status["status"], "disabled")
                self.assertEqual(restarted.post("/api/v1/backups", headers=self.headers, json=command).json(), accepted)
                self.assertEqual(restarted.post("/api/v1/backups", headers=self.headers,
                    json=command | {"requestId": str(uuid4()), "expectedRevision": status["revision"]}).status_code, 403)
        finally:
            self.client.__enter__()

    def test_restart_recovers_published_work_but_not_incomplete_work(self):
        original = self.wait_backup()
        self.client.__exit__(None, None, None)
        try:
            import sqlite3
            for published in (True, False):
                with sqlite3.connect(Path(self.settings.state_dir) / "central.sqlite3") as db:
                    db.execute("UPDATE backup_runs SET status='running',finished_at=NULL WHERE id=?", (original["backupId"],))
                db.close()
                root = Path(self.settings.state_dir) / "synthetic-backups"
                if not published:
                    (root / ("backup-" + original["backupId"])).rename(root / (".pending-" + original["backupId"]))
                with TestClient(create_app(self.settings), base_url="https://testserver") as restarted:
                    events = restarted.get("/api/v1/audit", headers=self.headers).json()
                    kind = "backup_recovered" if published else "backup_interrupted"
                    self.assertTrue(any(e["kind"] == kind and e["changes"]["backupId"] == original["backupId"] for e in events))
        finally:
            self.client.__enter__()

    def test_periodic_worker_runs_again_without_manual_backup_request(self):
        self.wait_backup()
        self.client.__exit__(None, None, None)
        try:
            with TestClient(create_app(replace(self.settings, backup_interval_seconds=1)), base_url="https://testserver") as client:
                first = client.get("/api/v1/backups/status", headers=self.headers).json()
                for _ in range(120):
                    status = client.get("/api/v1/backups/status", headers=self.headers).json()
                    if status["backupId"] != first["backupId"] and status["status"] == "ready":
                        break
                    time.sleep(.03)
                else:
                    self.fail("Periodic backup did not run")
                events = client.get("/api/v1/audit", headers=self.headers).json()
                self.assertTrue(any(e["kind"] == "backup_requested" and e["deviceId"] == "central-backup" and
                                    e["changes"]["backupId"] == status["backupId"] for e in events))
        finally:
            self.client.__enter__()

    def test_failed_copy_never_publishes_partial_backup_and_retry_recovers(self):
        first = self.wait_backup()
        original_open = Path.open
        def unavailable(path, mode="r", *args, **kwargs):
            if "x" in mode and path.name == "runtime.json" and path.parent.name.startswith(".pending-"):
                raise OSError("Synthetic private destination and secret must not appear in health")
            return original_open(path, mode, *args, **kwargs)
        with patch.object(Path, "open", unavailable):
            self.client.post("/api/v1/backups", headers=self.headers, json={
                "requestId": str(uuid4()), "expectedRevision": first["revision"], "reason": "Synthetic inaccessible destination"})
            failed = self.wait_backup()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["diagnostic"], "backup_failed")
        self.assertEqual(failed["lastSnapshotAt"], first["lastSnapshotAt"])
        self.assertNotIn("secret", json.dumps(failed))
        root = Path(self.settings.state_dir) / "synthetic-backups"
        self.assertFalse((root / ("backup-" + failed["backupId"])).exists())
        self.assertTrue((root / (".pending-" + failed["backupId"])).exists())
        self.client.post("/api/v1/backups", headers=self.headers, json={
            "requestId": str(uuid4()), "expectedRevision": failed["revision"], "reason": "Synthetic retry"})
        self.assertEqual(self.wait_backup()["status"], "ready")

    def test_backup_request_audit_is_atomic_and_rpo_uses_snapshot_age(self):
        import sqlite3
        first = self.wait_backup()
        command = {"requestId": str(uuid4()), "expectedRevision": first["revision"], "reason": "Synthetic atomic request"}
        with self.client.app.state.store.transaction() as db:
            db.execute("CREATE TRIGGER synthetic_backup_failure BEFORE INSERT ON audit_events "
                       "WHEN NEW.kind='backup_requested' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.client.post("/api/v1/backups", headers=self.headers, json=command)
        self.assertEqual(self.client.get("/api/v1/backups/status", headers=self.headers).json(), first)
        with self.client.app.state.store.transaction() as db:
            db.execute("DROP TRIGGER synthetic_backup_failure")
        self.assertEqual(self.client.post("/api/v1/backups", headers=self.headers, json=command).status_code, 200)
        fresh = self.wait_backup()
        with patch("time.time", return_value=fresh["lastSnapshotAt"] + 3601):
            breached = self.client.get("/api/v1/backups/status", headers=self.headers).json()
        self.assertTrue(breached["rpoBreached"])
        with patch("time.time", return_value=fresh["lastSnapshotAt"] - 10):
            reversed_clock = self.client.get("/api/v1/backups/status", headers=self.headers).json()
        self.assertTrue(reversed_clock["rpoBreached"])
        stale = self.client.post("/api/v1/backups", headers=self.headers, json=command | {"requestId": str(uuid4())})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"]["currentRevision"], fresh["revision"])

    def test_restore_rejects_corrupt_incomplete_and_traversing_archives(self):
        status = self.wait_backup()
        root = Path(self.settings.state_dir) / "synthetic-backups"
        archive = root / ("backup-" + status["backupId"])
        def restore_rejected(source, name):
            destination = self.directory / name
            result = subprocess.run([sys.executable, "-m", "service.restore", "--backup", str(source),
                                     "--destination", str(destination), "--operator", "SYN-RESTORE"], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(destination.exists())
        runtime = archive / "runtime.json"
        original = runtime.read_bytes()
        runtime.write_bytes(original + b"corruption")
        restore_rejected(archive, "corrupt-restore")
        runtime.write_bytes(original)
        manifest = json.loads((archive / "manifest.json").read_text())
        manifest["files"]["../escape.bin"] = manifest["files"]["runtime.json"]
        (archive / "manifest.json").write_text(json.dumps(manifest))
        restore_rejected(archive, "unsafe-restore")
        self.assertFalse((self.directory / "escape.bin").exists())
        manifest["files"].pop("../escape.bin")
        for name in ("immutable-artifacts/CON.txt", "immutable-artifacts/a:stream", "immutable-artifacts/../escape"):
            manifest["files"][name] = manifest["files"]["runtime.json"]
            (archive / "manifest.json").write_text(json.dumps(manifest))
            restore_rejected(archive, "invalid-name-restore")
            manifest["files"].pop(name)
        (archive / "manifest.json").write_text(json.dumps(manifest))
        pending = root / (".pending-" + status["backupId"])
        archive.rename(pending)
        restore_rejected(pending, "incomplete-restore")

    def test_restore_tool_recovers_history_artifacts_and_authorized_service(self):
        self.wait_backup()
        self.client.post("/api/v1/synthetic/refresh", headers=self.headers,
                         json={"requestId": str(uuid4()), "expectedRevision": 0})
        case = self.client.get("/api/v1/cases?physician=", headers=self.headers).json()["items"][0]
        grant = self.client.post("/api/v1/pairings", headers=self.headers, json={
            "requestId": str(uuid4()), "expectedRevision": 0, "capabilities": ["reporting"]}).json()
        reporter_key = secrets.token_urlsafe(32)
        self.client.post("/api/v1/devices/enroll", json={"requestId": str(uuid4()), "expectedRevision": 0,
            "pairingCode": grant["pairingCode"], "credential": reporter_key, "name": "Synthetic reporter"})
        session = self.client.post("/api/v1/sessions", headers={"Authorization": "Bearer " + reporter_key}, json={
            "requestId": str(uuid4()), "expectedRevision": 0, "operator": "SYN-REPORTER"}).json()
        reporter = {"Authorization": "Bearer " + reporter_key, "X-Session-Id": session["sessionId"]}
        path = f'/api/v1/cases/{case["caseId"]}'
        reason = self.client.get("/api/v1/reason-options", headers=reporter).json()["values"][0]
        for suffix, fields in [("reason", {"reason": reason, "patientConfirmed": True}),
                               ("dispensing", {"reportedQuantity": 8, "lots": [{"lot": "SYN-RESTORE", "quantity": 8}], "changeReason": "Synthetic partial quantity"}),
                               ("exclusion", {"excluded": True, "reason": "Synthetic retained decision"})]:
            response = self.client.post(path + "/" + suffix, headers=reporter, json={
                "requestId": str(uuid4()), "expectedRevision": case["revision"], **fields})
            self.assertEqual(response.status_code, 200, response.text)
            case = response.json()
        original = self.client.get(path, headers=self.headers).json()
        original_audit = self.client.get("/api/v1/audit", headers=self.headers).json()
        artifact = Path(self.settings.state_dir) / "immutable-artifacts" / "synthetic" / "record.bin"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"synthetic immutable artifact\x00\x01")
        status = self.client.get("/api/v1/backups/status", headers=self.headers).json()
        self.client.post("/api/v1/backups", headers=self.headers, json={
            "requestId": str(uuid4()), "expectedRevision": status["revision"], "reason": "Synthetic restore"})
        completed = self.wait_backup()
        self.assertEqual(completed["status"], "ready")
        archive = Path(self.settings.state_dir) / "synthetic-backups" / ("backup-" + completed["backupId"])
        destination = self.directory / "restored"
        process = subprocess.run([sys.executable, "-m", "service.restore", "--backup", str(archive),
                                  "--destination", str(destination), "--operator", "SYN-RESTORE-ADMIN"],
                                 capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue((destination / "recovery.env").is_file())
        self.assertEqual((destination / "immutable-artifacts/synthetic/record.bin").read_bytes(), artifact.read_bytes())
        self.assertEqual((destination / "tls.crt").read_bytes(), b"synthetic certificate bytes")
        self.assertEqual((destination / "tls.key").read_bytes(), b"synthetic private key bytes")
        from dotenv import dotenv_values
        restored_settings = Settings.from_environment({k: v for k, v in dotenv_values(destination / "recovery.env", interpolate=False).items() if v is not None})
        self.assertFalse(restored_settings.backup_enabled)
        self.assertFalse(restored_settings.synthetic_dbf_enabled)
        with TestClient(create_app(restored_settings), base_url="https://testserver") as restored:
            self.assertEqual(restored.get(path, headers=self.headers).status_code, 401)
            session = restored.post("/api/v1/sessions", headers={"Authorization": "Bearer " + self.key}, json={
                "requestId": str(uuid4()), "expectedRevision": 0, "operator": "SYN-RESTORE-ADMIN"}).json()
            headers = {"Authorization": "Bearer " + self.key, "X-Session-Id": session["sessionId"]}
            self.assertEqual(restored.get(path, headers=headers).json(), original)
            health = restored.get("/api/v1/backups/status", headers=headers).json()
            self.assertEqual(health["status"], "disabled")
            self.assertEqual(health["lastSnapshotAt"], completed["lastSnapshotAt"])
            self.assertEqual(health["lastSuccessfulAt"], completed["lastSuccessfulAt"])
            self.assertFalse(health["rpoBreached"])
            restored_audit = restored.get("/api/v1/audit", headers=headers).json()
            for event in original_audit:
                self.assertIn(event, restored_audit)
            self.assertTrue(any(event["kind"] == "backup_restored" for event in restored_audit))
        repeated = subprocess.run(process.args, capture_output=True, text=True)
        self.assertNotEqual(repeated.returncode, 0)
        self.assertEqual(self.client.get(path, headers=self.headers).json(), original)

    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.settings = Settings.from_environment({
            "CLINIC_REPORTER_STATE_DIR": str(self.directory / "central"),
            "CLINIC_REPORTER_HIS_SOURCE_PATH": r"\\synthetic-his\data",
            "CLINIC_REPORTER_BACKUP_ROOT": r"\\synthetic-his\backup",
            "CLINIC_REPORTER_SYNTHETIC_ENABLED": "true",
            "CLINIC_REPORTER_BACKUP_ENABLED": "true",
            "CLINIC_REPORTER_SYNTHETIC_BACKUP_ENABLED": "true",
        })
        self.key = secrets.token_urlsafe(32)
        initialize_administrator(self.settings, "Synthetic backup admin", self.key)
        cert, key = self.directory / "synthetic.crt", self.directory / "synthetic.key"
        cert.write_bytes(b"synthetic certificate bytes")
        key.write_bytes(b"synthetic private key bytes")
        self.client = self.enterContext(TestClient(create_app(self.settings, tls_files=(cert, key)), base_url="https://testserver"))
        self.headers = {"Authorization": "Bearer " + self.key}
        response = self.client.post("/api/v1/sessions", headers=self.headers, json={
            "requestId": str(uuid4()), "expectedRevision": 0, "operator": "SYN-BACKUP-ADMIN"})
        self.headers["X-Session-Id"] = response.json()["sessionId"]

    def wait_backup(self):
        for _ in range(100):
            response = self.client.get("/api/v1/backups/status", headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
            status = response.json()
            if status["status"] in ("ready", "failed", "interrupted"):
                return status
            time.sleep(.03)
        self.fail("Synthetic backup did not finish")

    def test_scheduled_backup_and_manual_retry_preserve_case_history(self):
        first = self.wait_backup()
        self.assertEqual(first["status"], "ready")
        self.assertEqual(first["destinationKind"], "local_synthetic")
        self.assertFalse(first["deploymentVerified"])
        self.assertFalse(first["rpoBreached"])
        self.assertNotIn(str(self.directory), json.dumps(first))
        self.client.post("/api/v1/synthetic/refresh", headers=self.headers,
                         json={"requestId": str(uuid4()), "expectedRevision": 0})
        command = {"requestId": str(uuid4()), "expectedRevision": first["revision"], "reason": "Synthetic recovery drill"}
        response = self.client.post("/api/v1/backups", headers=self.headers, json=command)
        self.assertEqual(response.status_code, 200, response.text)
        accepted = response.json()
        self.assertEqual(self.client.post("/api/v1/backups", headers=self.headers, json=command).json(), accepted)
        final = self.wait_backup()
        self.assertEqual(final["status"], "ready")
        self.assertNotEqual(first["backupId"], final["backupId"])
        self.assertIsNotNone(final["lastSnapshotAt"])
        events = self.client.get("/api/v1/audit", headers=self.headers).json()
        self.assertEqual(len([e for e in events if e["kind"] == "backup_requested" and
                            e["changes"]["backupId"] == final["backupId"]]), 1)
