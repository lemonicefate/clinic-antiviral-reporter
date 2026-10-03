import secrets
import tempfile
import unittest
from uuid import uuid4
from dataclasses import replace
import sqlite3

from fastapi.testclient import TestClient

from service.app import create_app
from service.provision import initialize_administrator
from service.settings import Settings


class SyntheticQueueTest(unittest.TestCase):
    def test_bulk_conflict_reports_reason_change_and_keeps_every_selected_case_unchanged(self):
        _, editor = self.reason_context("reporting")
        cases = self.client.get("/api/v1/cases?physician=", headers=editor).json()["items"][:2]
        changed = cases[1]
        reason = "23:未滿5歲及65歲以上之類流感患者"
        self.client.post(f'/api/v1/cases/{changed["caseId"]}/reason', headers=editor, json={
            "requestId": str(uuid4()), "expectedRevision": 1, "reason": reason, "patientConfirmed": True})
        bulk = {"requestId": str(uuid4()), "expectedRevision": 0, "lot": "SYN-CONFLICT", "replaceConfirmed": True,
                "cases": [{"caseId": c["caseId"], "expectedRevision": 1} for c in cases]}
        result = self.client.post("/api/v1/cases/bulk-lot", headers=editor, json=bulk)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["detail"]["caseId"], changed["caseId"])
        self.assertEqual(result.json()["detail"]["differences"]["reason"], reason)
        for case in cases:
            latest = self.client.get(f'/api/v1/cases/{case["caseId"]}', headers=editor).json()
            self.assertEqual(latest["lots"], [])
        self.assertEqual(self.client.post("/api/v1/cases/bulk-lot", headers=self.headers, json=bulk).status_code, 403)

    def test_bulk_audit_failure_rolls_back_the_entire_batch(self):
        _, editor = self.reason_context("reporting")
        cases = self.client.get("/api/v1/cases?physician=", headers=editor).json()["items"][:2]
        with self.client.app.state.store.transaction() as db:
            db.execute("CREATE TRIGGER synthetic_bulk_failure BEFORE INSERT ON audit_events "
                       "WHEN NEW.kind='bulk_lot_saved' AND json_extract(NEW.changes,'$.caseId')='" +
                       cases[1]["caseId"] + "' BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        command = {"requestId": str(uuid4()), "expectedRevision": 0, "lot": "SYN-ATOMIC", "replaceConfirmed": True,
                   "cases": [{"caseId": c["caseId"], "expectedRevision": 1} for c in cases]}
        with self.assertRaises(sqlite3.IntegrityError):
            self.client.post("/api/v1/cases/bulk-lot", headers=editor, json=command)
        for case in cases:
            latest = self.client.get(f'/api/v1/cases/{case["caseId"]}', headers=editor).json()
            self.assertEqual(latest["lots"], [])
            self.assertEqual(latest["revision"], 1)
        events = self.client.get("/api/v1/audit", headers=self.headers).json()
        self.assertFalse(any(e["kind"] == "bulk_lot_saved" for e in events))
        with self.client.app.state.store.transaction() as db:
            db.execute("DROP TRIGGER synthetic_bulk_failure")
        self.assertEqual(self.client.post("/api/v1/cases/bulk-lot", headers=editor, json=command).status_code, 200)

    def test_bulk_lots_remain_independent_and_exclusion_retains_history(self):
        _, editor = self.reason_context("reporting")
        cases = self.client.get("/api/v1/cases?physician=", headers=editor).json()["items"][:2]
        bulk = {"requestId": str(uuid4()), "expectedRevision": 0, "lot": "SYN-SHARED",
                "replaceConfirmed": True, "cases": [{"caseId": c["caseId"], "expectedRevision": 1} for c in cases]}
        first = self.client.post("/api/v1/cases/bulk-lot", headers=editor, json=bulk)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(len(first.json()["appliedCases"]), 2)
        self.assertEqual(self.client.post("/api/v1/cases/bulk-lot", headers=editor, json=bulk).json(), first.json())
        path = f'/api/v1/cases/{cases[0]["caseId"]}'
        changed = self.client.post(path + "/dispensing", headers=editor, json={
            "requestId": str(uuid4()), "expectedRevision": 2, "reportedQuantity": 10,
            "lots": [{"lot": "SYN-OTHER", "quantity": 10}], "changeReason": ""})
        self.assertEqual(changed.status_code, 200)
        other = self.client.get(f'/api/v1/cases/{cases[1]["caseId"]}', headers=editor).json()
        self.assertEqual(other["lots"], [{"lot": "SYN-SHARED", "quantity": 10}])
        excluded = {"requestId": str(uuid4()), "expectedRevision": 3, "excluded": True, "reason": "synthetic not collected"}
        self.assertEqual(self.client.post(path + "/exclusion", headers=editor, json=excluded).status_code, 200)
        queue = self.client.get("/api/v1/cases?physician=", headers=editor).json()
        self.assertEqual(queue["total"], 3)
        self.assertEqual(queue["awaitingReason"], 3)
        hidden = self.client.get("/api/v1/cases?physician=&caseStatus=excluded", headers=editor).json()
        self.assertEqual(hidden["total"], 1)
        self.assertFalse(hidden["items"][0]["exportEligible"])
        self.assertFalse(hidden["items"][0]["overdue"])
        included = excluded | {"requestId": str(uuid4()), "expectedRevision": 4, "excluded": False,
                               "reason": "synthetic dispensing confirmed"}
        self.assertEqual(self.client.post(path + "/exclusion", headers=editor, json=included).status_code, 200)
        history = self.client.get(path + "/history", headers=editor).json()
        decisions = [event for event in history if event["kind"] == "exclusion_changed"]
        self.assertEqual([event["changes"]["reason"] for event in decisions], [excluded["reason"], included["reason"]])
        self.assertEqual(self.client.get(path, headers=editor).json()["lots"], [{"lot": "SYN-OTHER", "quantity": 10}])

    def test_dispensing_preserves_source_and_requires_exact_lot_totals(self):
        case, editor = self.reason_context("reporting")
        route = f'/api/v1/cases/{case["caseId"]}/dispensing'
        command = {"requestId": str(uuid4()), "expectedRevision": 1, "reportedQuantity": 10,
                   "lots": [{"lot": "SYN-LOT-A", "quantity": 6}, {"lot": "SYN-LOT-B", "quantity": 3}],
                   "changeReason": ""}
        self.assertEqual(self.client.post(route, headers=editor, json=command).status_code, 422)
        command["lots"][1]["quantity"] = 4
        saved = self.client.post(route, headers=editor, json=command)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["lots"], command["lots"])
        self.assertEqual(self.client.post(route, headers=editor, json=command).json(), saved.json())
        reduced = {"requestId": str(uuid4()), "expectedRevision": 2, "reportedQuantity": 5,
                   "lots": [{"lot": "SYN-LOT-A", "quantity": 5}], "changeReason": ""}
        self.assertEqual(self.client.post(route, headers=editor, json=reduced).status_code, 422)
        reduced["changeReason"] = "synthetic partial dispensing"
        response = self.client.post(route, headers=editor, json=reduced)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sourceQuantity"], 10)
        self.assertEqual(response.json()["reportedQuantity"], 5)
        for value in [0, -1, 5.5, "5", True, 11]:
            invalid = reduced | {"requestId": str(uuid4()), "expectedRevision": 3, "reportedQuantity": value}
            self.assertEqual(self.client.post(route, headers=editor, json=invalid).status_code, 422)
        history = self.client.get(f'/api/v1/cases/{case["caseId"]}/history', headers=editor)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()[-1]["changes"]["reason"], reduced["changeReason"])

    def reason_context(self, capability):
        self.client.post("/api/v1/synthetic/refresh", headers=self.headers,
                         json={"requestId": str(uuid4()), "expectedRevision": 0})
        case = self.client.get("/api/v1/cases", headers=self.headers).json()["items"][0]
        key = secrets.token_urlsafe(32)
        grant = self.client.post("/api/v1/pairings", headers=self.headers, json={
            "requestId": str(uuid4()), "expectedRevision": 0, "capabilities": [capability]}).json()
        self.client.post("/api/v1/devices/enroll", json={
            "requestId": str(uuid4()), "expectedRevision": 0, "pairingCode": grant["pairingCode"],
            "credential": key, "name": "synthetic-reason-workstation"})
        return case, self.session(key, "SYN-DR-A")

    def test_reporting_revision_conflict_does_not_overwrite_first_reason(self):
        case, editor = self.reason_context("reporting")
        route = f'/api/v1/cases/{case["caseId"]}/reason'
        options = self.client.get("/api/v1/reason-options", headers=editor).json()["values"]
        first = {"requestId": str(uuid4()), "expectedRevision": 1, "reason": options[0], "patientConfirmed": True}
        self.assertEqual(self.client.post(route, headers=self.headers, json=first).status_code, 403)
        self.assertEqual(self.client.post(route, headers=editor, json=first).status_code, 200)
        second = first | {"requestId": str(uuid4()), "reason": options[1]}
        conflict = self.client.post(route, headers=editor, json=second)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["detail"], {"currentRevision": 2, "differences": {"reason": options[0]}})
        detail = self.client.get(f'/api/v1/cases/{case["caseId"]}', headers=editor).json()
        self.assertEqual(detail["reason"], options[0])
        revised = self.client.post(route, headers=editor, json=second | {"expectedRevision": 2})
        self.assertEqual(revised.json()["revision"], 3)
        self.assertEqual(revised.json()["reason"], options[1])
        self.assertEqual(len(detail["snapshots"]), 1)

    def test_reason_audit_failure_rolls_back_and_retry_is_safe(self):
        case, editor = self.reason_context("physician")
        route = f'/api/v1/cases/{case["caseId"]}/reason'
        command = {"requestId": str(uuid4()), "expectedRevision": 1,
                   "reason": "23:未滿5歲及65歲以上之類流感患者", "patientConfirmed": True}
        with self.client.app.state.store.transaction() as db:
            db.execute("CREATE TRIGGER synthetic_reason_failure BEFORE INSERT ON audit_events "
                       "WHEN NEW.kind='reason_saved' BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.client.post(route, headers=editor, json=command)
        unchanged = self.client.get(f'/api/v1/cases/{case["caseId"]}', headers=editor).json()
        self.assertEqual(unchanged["revision"], 1)
        self.assertIsNone(unchanged["reason"])
        with self.client.app.state.store.transaction() as db:
            db.execute("DROP TRIGGER synthetic_reason_failure")
        first = self.client.post(route, headers=editor, json=command)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.client.post(route, headers=editor, json=command).json(), first.json())
        events = self.client.get("/api/v1/audit", headers=self.headers).json()
        self.assertEqual(sum(e["kind"] == "reason_saved" for e in events), 1)

    def test_reason_requires_patient_confirmation_and_records_exact_option_once(self):
        self.client.post("/api/v1/synthetic/refresh", headers=self.headers,
                         json={"requestId": str(uuid4()), "expectedRevision": 0})
        case = self.client.get("/api/v1/cases", headers=self.headers).json()["items"][0]
        grant = self.client.post("/api/v1/pairings", headers=self.headers, json={
            "requestId": str(uuid4()), "expectedRevision": 0, "capabilities": ["physician"]}).json()
        key = secrets.token_urlsafe(32)
        self.client.post("/api/v1/devices/enroll", json={
            "requestId": str(uuid4()), "expectedRevision": 0, "pairingCode": grant["pairingCode"],
            "credential": key, "name": "synthetic-reason-device"})
        doctor = self.session(key, "SYN-DR-A")
        options = self.client.get("/api/v1/reason-options", headers=doctor)
        self.assertEqual(options.status_code, 200, options.text)
        reason = "23:未滿5歲及65歲以上之類流感患者"
        self.assertIn(reason, options.json()["values"])
        command = {"requestId": str(uuid4()), "expectedRevision": 1, "reason": reason,
                   "patientConfirmed": False}
        route = f'/api/v1/cases/{case["caseId"]}/reason'
        self.assertEqual(self.client.post(route, headers=doctor, json=command).status_code, 422)
        command["patientConfirmed"] = True
        first = self.client.post(route, headers=doctor, json=command)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["reason"], reason)
        self.assertEqual(first.json()["revision"], 2)
        self.assertEqual(self.client.post(route, headers=doctor, json=command).json(), first.json())
        queue = self.client.get("/api/v1/cases", headers=doctor).json()
        self.assertEqual(queue["awaitingReason"], 2)
        events = self.client.get("/api/v1/audit", headers=self.headers).json()
        changes = [e for e in events if e["kind"] == "reason_saved"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["changes"]["before"], None)
        self.assertEqual(changes[0]["changes"]["after"], reason)
        self.assertEqual(changes[0]["operator"], "SYN-DR-A")

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
