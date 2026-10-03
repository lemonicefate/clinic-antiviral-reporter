import secrets
import tempfile
import unittest
from uuid import uuid4
from dataclasses import replace

from fastapi.testclient import TestClient

from service.app import create_app
from service.provision import initialize_administrator
from service.settings import Settings


class SyntheticQueueTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.settings = Settings.from_environment({
            "CLINIC_REPORTER_STATE_DIR": directory,
            "CLINIC_REPORTER_HIS_SOURCE_PATH": r"\\synthetic-his\data",
            "CLINIC_REPORTER_BACKUP_ROOT": r"\\synthetic-his\backup",
            "CLINIC_REPORTER_SYNTHETIC_ENABLED": "true",
        })
        self.key = secrets.token_urlsafe(32)
        initialize_administrator(self.settings, "synthetic-admin", self.key)
        self.client = self.enterContext(TestClient(create_app(self.settings), base_url="https://testserver"))
        self.headers = self.session(self.key, "SYN-DR-A")

    def session(self, key, operator):
        headers = {"Authorization": "Bearer " + key}
        response = self.client.post("/api/v1/sessions", headers=headers, json={
            "requestId": str(uuid4()), "expectedRevision": 0, "operator": operator})
        self.assertEqual(response.status_code, 200)
        return headers | {"X-Session-Id": response.json()["sessionId"]}

    def test_refresh_keeps_same_day_orders_distinct_and_retry_survives_restart(self):
        command = {"requestId": str(uuid4()), "expectedRevision": 0}
        first = self.client.post("/api/v1/synthetic/refresh", headers=self.headers, json=command)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["created"], 4)
        self.assertEqual(self.client.post("/api/v1/synthetic/refresh", headers=self.headers,
                                         json=command).json(), first.json())
        queue = self.client.get("/api/v1/cases", headers=self.headers).json()
        self.assertEqual(queue["total"], 3)
        self.assertEqual(queue["overdue"], 1)
        self.assertEqual(queue["items"][0]["chartNumber"], "SYN-0002")
        same_day = [item for item in queue["items"] if item["chartNumber"] == "SYN-0001"]
        self.assertEqual(len(same_day), 2)
        self.assertNotEqual(same_day[0]["caseId"], same_day[1]["caseId"])
        self.assertTrue(all(item["duplicateConcern"] for item in same_day))
        self.client.__exit__(None, None, None)
        with TestClient(create_app(self.settings), base_url="https://testserver") as restarted:
            self.assertEqual(restarted.post("/api/v1/synthetic/refresh", headers=self.headers,
                                            json=command).json(), first.json())
            second = restarted.post("/api/v1/synthetic/refresh", headers=self.headers,
                                    json=command | {"requestId": str(uuid4()), "expectedRevision": 1})
            self.assertEqual(second.json()["created"], 0)
            self.assertEqual(second.json()["unchanged"], 4)
            detail = restarted.get(f'/api/v1/cases/{same_day[0]["caseId"]}', headers=self.headers).json()
            self.assertEqual(len(detail["snapshots"]), 1)
            self.assertEqual(detail["sourceQuantity"], 10)
            self.assertEqual(detail["reportedQuantity"], 10)
            self.assertEqual(detail["snapshots"][0]["raw"]["CH012M1.USE_TAMT"], "10")
            self.assertFalse(detail["liveIdentityVerified"])

    def test_exact_chart_lookup_crosses_physicians_without_granting_refresh(self):
        self.client.post("/api/v1/synthetic/refresh", headers=self.headers,
                         json={"requestId": str(uuid4()), "expectedRevision": 0})
        grant = self.client.post("/api/v1/pairings", headers=self.headers, json={
            "requestId": str(uuid4()), "expectedRevision": 0, "capabilities": ["physician"]}).json()
        key = secrets.token_urlsafe(32)
        enrolled = self.client.post("/api/v1/devices/enroll", json={
            "requestId": str(uuid4()), "expectedRevision": 0, "pairingCode": grant["pairingCode"],
            "credential": key, "name": "synthetic-physician"}).json()
        doctor = self.session(key, "SYN-DR-B")
        self.assertEqual(self.client.get("/api/v1/cases", headers=doctor).json()["total"], 1)
        matches = self.client.get("/api/v1/cases?chart=SYN-0001", headers=doctor).json()
        self.assertEqual(matches["total"], 2)
        self.assertEqual(self.client.get("/api/v1/cases?chart=0001", headers=doctor).json()["total"], 0)
        self.assertEqual(self.client.get("/api/v1/cases?physician=", headers=doctor).json()["total"], 4)
        self.assertEqual(self.client.post("/api/v1/synthetic/refresh", headers=doctor,
                         json={"requestId": str(uuid4()), "expectedRevision": 1}).status_code, 403)
        self.client.post(f'/api/v1/devices/{enrolled["deviceId"]}/revoke', headers=self.headers,
                         json={"requestId": str(uuid4()), "expectedRevision": 1, "reason": "synthetic drill"})
        self.assertEqual(self.client.get("/api/v1/cases", headers=doctor).status_code, 401)
        self.assertEqual(self.client.get(f'/api/v1/cases/{matches["items"][0]["caseId"]}', headers=doctor).status_code, 401)

    def test_refresh_disabled_by_default_and_in_production_and_conflicts_are_explicit(self):
        for settings in (replace(self.settings, synthetic_enabled=False),
                         replace(self.settings, environment="production")):
            self.client.__exit__(None, None, None)
            with TestClient(create_app(settings), base_url="https://testserver") as disabled:
                self.assertEqual(disabled.post("/api/v1/synthetic/refresh", headers=self.headers,
                    json={"requestId": str(uuid4()), "expectedRevision": 0}).status_code, 403)
            self.client.__enter__()
        self.client.post("/api/v1/synthetic/refresh", headers=self.headers,
                         json={"requestId": str(uuid4()), "expectedRevision": 0})
        conflict = self.client.post("/api/v1/synthetic/refresh", headers=self.headers,
                                   json={"requestId": str(uuid4()), "expectedRevision": 0})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["detail"]["currentRevision"], 1)
        self.assertEqual(self.client.get("/api/v1/cases?physician=", headers=self.headers).json()["total"], 4)
