import secrets
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from service.app import create_app
from service.provision import initialize_administrator
from service.settings import Settings


class DeviceWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings.from_environment({
            "CLINIC_REPORTER_STATE_DIR": self.directory.name,
            "CLINIC_REPORTER_HIS_SOURCE_PATH": r"\\synthetic-his\data",
            "CLINIC_REPORTER_BACKUP_ROOT": r"\\synthetic-his\backup",
        })
        self.credential = secrets.token_urlsafe(32)
        initialize_administrator(self.settings, "test-admin", self.credential)
        self.client = self.enterContext(TestClient(create_app(self.settings), base_url="https://testserver"))

    def session(self, credential, operator="synthetic-operator"):
        response = self.client.post("/api/v1/sessions", headers={"Authorization": "Bearer " + credential}, json={
            "requestId": str(uuid4()), "expectedRevision": 0, "operator": operator,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": "Bearer " + credential, "X-Session-Id": response.json()["sessionId"]}

    def test_initial_administrator_session_is_authorized_but_unknown_device_is_not(self):
        headers = self.session(self.credential)
        current = self.client.get("/api/v1/session", headers=headers)
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["capabilities"], ["admin"])
        self.assertEqual(current.json()["operator"], "synthetic-operator")
        denied = self.client.get("/api/v1/session", headers=headers | {"Authorization": "Bearer unknown"})
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(current.headers["cache-control"], "no-store")

    def test_pairing_does_not_grant_operator_claimed_authority_and_revocation_is_immediate(self):
        admin = self.session(self.credential)
        pairing = self.client.post("/api/v1/pairings", headers=admin, json={
            "requestId": str(uuid4()), "expectedRevision": 0,
            "capabilities": ["physician"],
        })
        self.assertEqual(pairing.status_code, 200, pairing.text)
        credential = secrets.token_urlsafe(32)
        command = {"requestId": str(uuid4()), "expectedRevision": 0,
                   "pairingCode": pairing.json()["pairingCode"], "name": "Synthetic physician device",
                   "credential": credential}
        enrolled = self.client.post("/api/v1/devices/enroll", json=command)
        self.assertEqual(enrolled.status_code, 200, enrolled.text)
        self.assertEqual(self.client.post("/api/v1/devices/enroll", json=command).json(), enrolled.json())
        physician = self.session(credential, "administrator")
        current = self.client.get("/api/v1/session", headers=physician)
        self.assertEqual(current.json()["capabilities"], ["physician"])
        self.assertEqual(self.client.get("/api/v1/devices", headers=physician).status_code, 403)
        device = enrolled.json()
        revoke = {"requestId": str(uuid4()), "expectedRevision": 1, "reason": "synthetic revocation drill"}
        result = self.client.post(f'/api/v1/devices/{device["deviceId"]}/revoke', headers=admin, json=revoke)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get("/api/v1/session", headers=physician).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/sessions", headers={"Authorization": "Bearer " + credential},
                         json={"requestId": str(uuid4()), "expectedRevision": 0, "operator": "doctor"}).status_code, 401)

    def test_session_retry_is_one_audited_change_and_survives_restart(self):
        command = {"requestId": str(uuid4()), "expectedRevision": 0, "operator": "synthetic-doctor"}
        headers = {"Authorization": "Bearer " + self.credential}
        first = self.client.post("/api/v1/sessions", headers=headers, json=command)
        second = self.client.post("/api/v1/sessions", headers=headers, json=command)
        self.assertEqual(first.json(), second.json())
        headers["X-Session-Id"] = first.json()["sessionId"]
        events = self.client.get("/api/v1/audit", headers=headers)
        self.assertEqual(events.status_code, 200, events.text)
        self.assertEqual([e["kind"] for e in events.json()], ["administrator_initialized", "session_created"])
        self.client.__exit__(None, None, None)
        with TestClient(create_app(self.settings), base_url="https://testserver") as restarted:
            self.assertEqual(restarted.get("/api/v1/session", headers=headers).json(), first.json())
            self.assertEqual(restarted.post("/api/v1/sessions", headers=headers, json=command).json(), first.json())

    def test_http_and_invalid_requests_cannot_expose_device_credentials(self):
        command = {"requestId": str(uuid4()), "expectedRevision": 0, "operator": "synthetic"}
        response = self.client.post("http://testserver/api/v1/sessions", json=command,
                                    headers={"Authorization": "Bearer " + self.credential})
        self.assertEqual(response.status_code, 400)
        invalid = self.client.post("/api/v1/devices/enroll", json={"credential": self.credential})
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn(self.credential, invalid.text)
        schema = self.client.get("/api/v1/openapi.json").text
        self.assertNotIn(self.directory.name, schema)
        self.assertNotIn("synthetic-his", schema)

    def test_second_central_owner_is_rejected_and_bootstrap_cannot_run_online(self):
        with self.assertRaisesRegex(RuntimeError, "already has an owner"):
            with TestClient(create_app(self.settings), base_url="https://testserver"):
                self.fail("Second service unexpectedly acquired the state directory")
        with self.assertRaisesRegex(RuntimeError, "already has an owner"):
            initialize_administrator(self.settings, "another", secrets.token_urlsafe(32))
