import secrets
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import time
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from service.app import create_app
from service.provision import initialize_administrator
from service.settings import Settings


class ClientReleaseTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.environment = {
            "CLINIC_REPORTER_STATE_DIR": str(self.root / "state"),
            "CLINIC_REPORTER_HIS_SOURCE_PATH": r"\\synthetic-his\data",
            "CLINIC_REPORTER_BACKUP_ROOT": r"\\synthetic-his\backup",
        }
        self.settings = Settings.from_environment(self.environment)
        self.key = secrets.token_urlsafe(32)
        initialize_administrator(self.settings, "Synthetic release administrator", self.key)
        self.installer = self.root / "synthetic.exe"
        self.installer.write_bytes(b"Synthetic installer: never execute")
        self.signature = self.root / "synthetic.exe.sig"
        self.signature.write_text("synthetic signature; native verification must reject", encoding="ascii")

    def publish(self, *, version="0.1.1", revision=0, request_id=None):
        return subprocess.run([
            sys.executable, "-m", "service", "stage-release", "--version", version,
            "--installer", str(self.installer), "--signature", str(self.signature),
            "--operator", "SYN-ADMIN", "--reason", "Synthetic update acceptance",
            "--request-id", request_id or str(uuid4()), "--expected-revision", str(revision)],
            env=os.environ | self.environment, capture_output=True, text=True)

    def client(self):
        return TestClient(create_app(self.settings), base_url="https://testserver")

    def test_previous_release_remains_downloadable_and_stale_or_reused_version_cannot_publish(self):
        first = self.publish()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.installer.write_bytes(b"Synthetic replacement: never execute")
        conflict = self.publish(version="0.1.2")
        self.assertNotEqual(conflict.returncode, 0)
        self.assertIn('"revision": 1', conflict.stderr)
        duplicate = self.publish(revision=1)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("cannot be replaced", duplicate.stderr)
        second = self.publish(version="0.1.2", revision=1)
        self.assertEqual(second.returncode, 0, second.stderr)
        with self.client() as client:
            headers = {"Authorization": "Bearer " + self.key}
            self.assertEqual(client.get("/api/v1/client-releases/current", headers=headers).json(), json.loads(second.stdout))
            self.assertEqual(client.get("/api/v1/client-releases/0.1.1/installer", headers=headers).content,
                             b"Synthetic installer: never execute")
            self.assertEqual(client.get("/api/v1/client-releases/0.1.2/installer", headers=headers).content,
                             b"Synthetic replacement: never execute")

    def test_incomplete_files_are_not_releases_and_corrupt_release_is_not_downloadable(self):
        root = Path(self.settings.state_dir) / "immutable-artifacts" / "client-releases"
        root.mkdir(parents=True)
        (root / "synthetic-interruption.partial").write_bytes(b"incomplete synthetic installer")
        with self.client() as client:
            headers = {"Authorization": "Bearer " + self.key}
            self.assertEqual(client.get("/api/v1/client-releases/current", headers=headers).json(), {"revision": 0, "release": None})
            self.assertEqual(client.get("/api/v1/client-releases/0.1.1/installer", headers=headers).status_code, 404)
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        release = json.loads(result.stdout)["release"]
        (root / (release["sha256"] + ".exe")).write_bytes(b"synthetic corruption")
        with self.client() as client:
            response = client.get("/api/v1/client-releases/0.1.1/installer", headers=headers)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(str(root), response.text)
            self.assertNotIn("synthetic corruption", response.text)

    def test_revocation_blocks_metadata_and_installer_without_an_operator_session(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.client() as client:
            headers = {"Authorization": "Bearer " + self.key}
            session = client.post("/api/v1/sessions", headers=headers, json={
                "requestId": str(uuid4()), "expectedRevision": 0, "operator": "SYN-ADMIN"}).json()
            headers["X-Session-Id"] = session["sessionId"]
            pairing = client.post("/api/v1/pairings", headers=headers, json={
                "requestId": str(uuid4()), "expectedRevision": 0, "capabilities": ["physician"]}).json()
            key = secrets.token_urlsafe(32)
            device = client.post("/api/v1/devices/enroll", json={"requestId": str(uuid4()), "expectedRevision": 0,
                "pairingCode": pairing["pairingCode"], "credential": key, "name": "Synthetic update device"}).json()
            device_headers = {"Authorization": "Bearer " + key}
            paths = ["/api/v1/client-releases/current", "/api/v1/client-releases/0.1.1", "/api/v1/client-releases/0.1.1/installer"]
            for path in paths:
                self.assertEqual(client.get(path, headers=device_headers).status_code, 200)
                self.assertEqual(client.get(path).status_code, 401)
            revoked = client.post(f"/api/v1/devices/{device['deviceId']}/revoke", headers=headers, json={
                "requestId": str(uuid4()), "expectedRevision": device["revision"], "reason": "Synthetic revocation"})
            self.assertEqual(revoked.status_code, 200, revoked.text)
            for path in paths:
                self.assertEqual(client.get(path, headers=device_headers).status_code, 401)

    def test_live_service_owner_prevents_offline_publication(self):
        with self.client() as client:
            result = self.publish()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already has an owner", result.stderr)
            self.assertEqual(client.get("/api/v1/client-releases/current", headers={"Authorization": "Bearer " + self.key}).json(),
                             {"revision": 0, "release": None})

    def test_unreadable_database_reports_safe_failure_and_preserves_original_bytes(self):
        database = Path(self.settings.state_dir) / "central.sqlite3"
        database.write_bytes(b"synthetic malformed database")
        failed = self.publish()
        self.assertNotEqual(failed.returncode, 0)
        self.assertNotIn("Traceback", failed.stderr)
        self.assertNotIn(str(self.root), failed.stderr)
        self.assertEqual(database.read_bytes(), b"synthetic malformed database")

    def test_invalid_version_and_empty_artifact_leave_no_published_release(self):
        for version in ("../escape", "01.2.3", "1.2", "1.2.3+build", "65536.1.2"):
            self.assertNotEqual(self.publish(version=version).returncode, 0)
        self.installer.write_bytes(b"")
        self.assertNotEqual(self.publish().returncode, 0)
        with self.client() as client:
            self.assertEqual(client.get("/api/v1/client-releases/current", headers={"Authorization": "Bearer " + self.key}).json(),
                             {"revision": 0, "release": None})

    def test_backup_restore_retains_release_metadata_and_exact_installer_bytes(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = replace(self.settings, synthetic_enabled=True, backup_enabled=True, synthetic_backup_enabled=True)
        certificate, tls_key = self.root / "synthetic.crt", self.root / "synthetic.key"
        certificate.write_bytes(b"synthetic test certificate")
        tls_key.write_bytes(b"synthetic test key")
        headers = {"Authorization": "Bearer " + self.key}
        with TestClient(create_app(settings, tls_files=(certificate, tls_key)), base_url="https://testserver") as client:
            session = client.post("/api/v1/sessions", headers=headers, json={
                "requestId": str(uuid4()), "expectedRevision": 0, "operator": "SYN-ADMIN"}).json()
            headers["X-Session-Id"] = session["sessionId"]
            for _ in range(100):
                status = client.get("/api/v1/backups/status", headers=headers).json()
                if status["status"] in ("ready", "failed", "interrupted"):
                    break
                time.sleep(.03)
            self.assertEqual(status["status"], "ready", status)
        archive = Path(settings.state_dir) / "synthetic-backups" / ("backup-" + status["backupId"])
        destination = self.root / "restored"
        restored = subprocess.run([sys.executable, "-m", "service.restore", "--backup", str(archive),
            "--destination", str(destination), "--operator", "SYN-RESTORE"], capture_output=True, text=True)
        self.assertEqual(restored.returncode, 0, restored.stderr)
        from dotenv import dotenv_values
        restored_settings = Settings.from_environment({k: v for k, v in dotenv_values(destination / "recovery.env", interpolate=False).items()
                                                       if v is not None})
        with TestClient(create_app(restored_settings), base_url="https://testserver") as client:
            self.assertEqual(client.get("/api/v1/client-releases/current", headers=headers).json(), json.loads(result.stdout))
            self.assertEqual(client.get("/api/v1/client-releases/0.1.1/installer", headers=headers).content,
                             b"Synthetic installer: never execute")

    def test_audit_failure_does_not_publish_and_same_request_can_recover_orphaned_bytes(self):
        database = Path(self.settings.state_dir) / "central.sqlite3"
        with sqlite3.connect(database) as db:
            db.execute("""CREATE TRIGGER synthetic_release_audit_failure BEFORE INSERT ON audit_events
                          WHEN NEW.kind='client_release_published'
                          BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END""")
        db.close()
        request_id = str(uuid4())
        failed = self.publish(request_id=request_id)
        self.assertNotEqual(failed.returncode, 0)
        self.assertNotIn("Traceback", failed.stderr)
        with self.client() as client:
            headers = {"Authorization": "Bearer " + self.key}
            self.assertEqual(client.get("/api/v1/client-releases/current", headers=headers).json(), {"revision": 0, "release": None})
            self.assertEqual(client.get("/api/v1/client-releases/0.1.1/installer", headers=headers).status_code, 404)
        with sqlite3.connect(database) as db:
            db.execute("DROP TRIGGER synthetic_release_audit_failure")
        db.close()
        recovered = self.publish(request_id=request_id)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(json.loads(recovered.stdout)["revision"], 1)
        with self.client() as client:
            self.assertEqual(client.get("/api/v1/client-releases/0.1.1/installer", headers=headers).content,
                             b"Synthetic installer: never execute")

    def test_operator_publishes_an_immutable_release_and_retry_does_not_duplicate_audit(self):
        request_id = str(uuid4())
        first = self.publish(request_id=request_id)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.publish(request_id=request_id).stdout, first.stdout)
        with self.client() as client:
            headers = {"Authorization": "Bearer " + self.key}
            current = client.get("/api/v1/client-releases/current", headers=headers)
            self.assertEqual(current.status_code, 200, current.text)
            self.assertEqual(current.json(), json.loads(first.stdout))
            self.assertEqual(current.json()["revision"], 1)
            self.assertEqual(current.json()["release"]["version"], "0.1.1")
            self.assertNotIn(str(self.root), current.text)
            release = client.get("/api/v1/client-releases/0.1.1", headers=headers)
            self.assertEqual(release.json(), current.json()["release"])
            downloaded = client.get("/api/v1/client-releases/0.1.1/installer", headers=headers)
            self.assertEqual(downloaded.content, b"Synthetic installer: never execute")
            session = client.post("/api/v1/sessions", headers=headers, json={
                "requestId": str(uuid4()), "expectedRevision": 0, "operator": "SYN-ADMIN"})
            headers["X-Session-Id"] = session.json()["sessionId"]
            events = client.get("/api/v1/audit", headers=headers).json()
            published = [event for event in events if event["kind"] == "client_release_published"]
            self.assertEqual(len(published), 1)
            self.assertEqual(published[0]["changes"]["reason"], "Synthetic update acceptance")

    def test_update_check_requires_a_device_but_not_an_operator_session(self):
        with self.client() as client:
            self.assertEqual(client.get("/api/v1/client-releases/current").status_code, 401)
            checked = client.get("/api/v1/client-releases/current", headers={"Authorization": "Bearer " + self.key})
            self.assertEqual(checked.status_code, 200, checked.text)
            self.assertEqual(checked.json(), {"revision": 0, "release": None})
