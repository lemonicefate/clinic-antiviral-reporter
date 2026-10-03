import secrets
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from service.app import create_app
from service.provision import initialize_administrator
from service.settings import Settings


class MappingWorkflowTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = Settings.from_environment({
            "CLINIC_REPORTER_STATE_DIR": directory.name,
            "CLINIC_REPORTER_HIS_SOURCE_PATH": r"\\synthetic-his\data",
            "CLINIC_REPORTER_BACKUP_ROOT": r"\\synthetic-his\backup",
        })
        credential = secrets.token_urlsafe(32)
        initialize_administrator(self.settings, "synthetic-admin", credential)
        self.client = self.enterContext(TestClient(create_app(self.settings), base_url="https://testserver"))
        self.headers = {"Authorization": "Bearer " + credential}
        session = self.client.post("/api/v1/sessions", headers=self.headers, json={
            "requestId": str(uuid4()), "expectedRevision": 0, "operator": "synthetic-admin"})
        self.headers["X-Session-Id"] = session.json()["sessionId"]

    def command(self, **changes):
        return {"requestId": str(uuid4()), "expectedRevision": 0,
                "effectiveFrom": "2026-10-01T00:00:00+08:00", "initialDateFrom": "2026-10-01",
                "internalCode": "ERA", "nhiCode": "A059653100",
                "materialValue": "DDMTR2018090002:易剋冒膠囊(顆)", "quantityRule": "integer_capsules",
                "enabled": True, "reason": "synthetic explicit activation", **changes}

    def get(self):
        response = self.client.get("/api/v1/mappings", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_no_invented_activation_then_explicit_mapping_is_audited_and_replayable(self):
        initial = self.get()
        self.assertEqual(initial["revision"], 0)
        self.assertIsNone(initial["goLiveAt"])
        self.assertEqual(initial["versions"], [])
        command = self.command()
        response = self.client.post("/api/v1/mappings", headers=self.headers, json=command)
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertEqual(saved["goLiveAt"], "2026-10-01T00:00:00+08:00")
        self.assertEqual(saved["initialDateFrom"], "2026-10-01")
        self.assertEqual(saved["versions"][0]["materialValue"], "DDMTR2018090002:易剋冒膠囊(顆)")
        self.assertEqual(saved["revision"], 1)
        self.assertFalse(saved["productionExportEnabled"])
        replay = self.client.post("/api/v1/mappings", headers=self.headers, json=command)
        self.assertEqual(replay.json(), saved)
        events = self.client.get("/api/v1/audit", headers=self.headers).json()
        changes = [event["changes"] for event in events if event["kind"] == "mapping_version_created"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["reason"], command["reason"])
        self.assertEqual(self.get(), saved)

    def test_ambiguous_boundaries_and_unverified_profiles_cannot_activate(self):
        before = self.get()
        invalid = [
            {"effectiveFrom": "2026-10-01T00:00:00"},
            {"effectiveFrom": "2026-10-01T10:00:00+08:00"},
            {"initialDateFrom": "2026-09-30"},
            {"initialDateFrom": "2099-01-01"},
            {"enabled": False},
            {"internalCode": "UNKNOWN"}, {"nhiCode": "A000000000"},
            {"materialValue": "DDID-001:克流感膠囊(顆)"}, {"quantityRule": "millilitres"},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                response = self.client.post("/api/v1/mappings", headers=self.headers, json=self.command(**changes))
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.get(), before)

    def test_version_conflict_keeps_old_history_and_initial_boundary(self):
        first = self.client.post("/api/v1/mappings", headers=self.headers, json=self.command()).json()
        stale = self.client.post("/api/v1/mappings", headers=self.headers,
                                 json=self.command(effectiveFrom="2026-10-02T00:00:00+08:00", enabled=False))
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"]["currentRevision"], 1)
        self.assertEqual(stale.json()["detail"]["differences"], first)
        for changes in ({"initialDateFrom": "2026-10-02"},
                        {"effectiveFrom": "2026-09-30T00:00:00+08:00"},
                        {"effectiveFrom": "2026-10-01T00:00:00+08:00"}):
            command = self.command(expectedRevision=1, **changes)
            self.assertEqual(self.client.post("/api/v1/mappings", headers=self.headers, json=command).status_code, 422)
        second = self.client.post("/api/v1/mappings", headers=self.headers, json=self.command(
            expectedRevision=1, effectiveFrom="2026-10-01T16:00:00Z", enabled=False))
        self.assertEqual(second.status_code, 200, second.text)
        current = second.json()
        self.assertEqual(current["versions"][0], first["versions"][0])
        self.assertEqual(current["versions"][1]["effectiveFrom"], "2026-10-02T00:00:00+08:00")
        self.assertFalse(current["versions"][1]["enabled"])
        self.assertEqual(current["goLiveAt"], first["goLiveAt"])

    def test_operator_claim_cannot_grant_mapping_administration(self):
        for capability in ("physician", "reporting"):
            pairing = self.client.post("/api/v1/pairings", headers=self.headers, json={
                "requestId": str(uuid4()), "expectedRevision": 0, "capabilities": [capability]}).json()
            credential = secrets.token_urlsafe(32)
            self.client.post("/api/v1/devices/enroll", json={"requestId": str(uuid4()), "expectedRevision": 0,
                "name": "synthetic " + capability, "credential": credential, "pairingCode": pairing["pairingCode"]})
            headers = {"Authorization": "Bearer " + credential}
            session = self.client.post("/api/v1/sessions", headers=headers, json={
                "requestId": str(uuid4()), "expectedRevision": 0, "operator": "admin"})
            headers["X-Session-Id"] = session.json()["sessionId"]
            self.assertEqual(self.client.get("/api/v1/mappings", headers=headers).status_code, 403)
            self.assertEqual(self.client.post("/api/v1/mappings", headers=headers, json=self.command()).status_code, 403)
        self.assertEqual(self.get()["revision"], 0)

    def test_failed_audit_rolls_back_mapping_and_retry_commits_once(self):
        before = self.get()
        command = self.command()
        # Inject a storage failure; observe rollback/retry through public APIs.
        with self.client.app.state.store.transaction() as db:
            db.execute("CREATE TRIGGER synthetic_mapping_failure BEFORE INSERT ON audit_events "
                       "WHEN NEW.kind='mapping_version_created' BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.client.post("/api/v1/mappings", headers=self.headers, json=command)
        self.assertEqual(self.get(), before)
        with self.client.app.state.store.transaction() as db:
            db.execute("DROP TRIGGER synthetic_mapping_failure")
        result = self.client.post("/api/v1/mappings", headers=self.headers, json=command)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["revision"], 1)
        self.assertEqual(self.client.post("/api/v1/mappings", headers=self.headers, json=command).json(), result.json())

    def test_mapping_history_and_original_command_result_survive_restart(self):
        command = self.command()
        first = self.client.post("/api/v1/mappings", headers=self.headers, json=command).json()
        second = self.client.post("/api/v1/mappings", headers=self.headers, json=self.command(
            expectedRevision=1, effectiveFrom="2026-10-02T00:00:00+08:00", enabled=False)).json()
        self.client.__exit__(None, None, None)
        try:
            with TestClient(create_app(self.settings), base_url="https://testserver") as restarted:
                self.assertEqual(restarted.get("/api/v1/mappings", headers=self.headers).json(), second)
                self.assertEqual(restarted.post("/api/v1/mappings", headers=self.headers, json=command).json(), first)
        finally:
            self.client.__enter__()
