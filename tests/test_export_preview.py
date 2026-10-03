from pathlib import Path
import secrets
import tempfile
import time
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from scripts.synthetic_dbf import prepare, write_table
from service.app import create_app
from service.cases import clinic_today
from service.provision import initialize_administrator
from service.settings import Settings


class ExportPreviewTest(unittest.TestCase):
    def test_default_selection_over_one_hundred_can_be_manually_reduced(self):
        write_table(self.root / "CH012M1.DBF", [("RELKEY", 30), ("SYS_2015", 30), ("MED1", 10), ("PRICE1", 20), ("USE_TAMT", 8)],
                    [{"RELKEY": "SYN  ENCOUNTER", "SYS_2015": f"SYN-PREVIEW-{i:02}", "MED1": "ERA",
                      "PRICE1": "SYN-A059653100", "USE_TAMT": "10"} for i in range(103)])
        status = self.client.get("/api/v1/scans/status", headers=self.admin).json()
        self.post("/api/v1/scans", {"dateFrom": clinic_today().isoformat(), "dateTo": clinic_today().isoformat()},
                  self.admin, revision=status["revision"])
        for _ in range(100):
            if self.client.get("/api/v1/scans/status", headers=self.admin).json()["status"] == "succeeded":
                break
            time.sleep(.02)
        cases = self.client.get("/api/v1/cases?physician=", headers=self.reporter).json()["items"]
        self.assertEqual(len(cases), 103)
        for case in cases:
            self.complete(case)
        before = self.client.get("/api/v1/export-preview", headers=self.reporter).json()
        self.assertEqual(before["selectedCount"], 103)
        result = self.client.get("/api/v1/export-preview", headers=self.reporter,
            params=[("manualSelection", "true")] + [("selected", case["caseId"]) for case in cases[1:]])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["selectedCount"], 102)
        body_preview = self.client.post("/api/v1/export-preview", headers=self.reporter,
                                        json={"selected": [case["caseId"] for case in cases[1:]]})
        self.assertEqual(body_preview.status_code, 200, body_preview.text)
        self.assertEqual(body_preview.json(), result.json())

    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.settings = Settings.from_environment({
            "CLINIC_REPORTER_STATE_DIR": directory,
            "CLINIC_REPORTER_HIS_SOURCE_PATH": r"\\synthetic-his\data",
            "CLINIC_REPORTER_BACKUP_ROOT": r"\\synthetic-his\backup",
            "CLINIC_REPORTER_SYNTHETIC_ENABLED": "true",
            "CLINIC_REPORTER_SYNTHETIC_DBF_ENABLED": "true",
            "CLINIC_REPORTER_EXPORT_ENABLED": "true",
        })
        root = prepare(Path(directory), clinic_today())
        self.root = root
        write_table(root / "CH012M1.DBF", [("RELKEY", 30), ("SYS_2015", 30), ("MED1", 10), ("PRICE1", 20), ("USE_TAMT", 8)],
                    [{"RELKEY": "SYN  ENCOUNTER", "SYS_2015": f"SYN-PREVIEW-{i:02}", "MED1": "ERA",
                      "PRICE1": "SYN-A059653100", "USE_TAMT": "10"} for i in range(20)])
        key = secrets.token_urlsafe(32)
        initialize_administrator(self.settings, "Synthetic preview administrator", key)
        self.client = self.enterContext(TestClient(create_app(self.settings), base_url="https://testserver"))
        self.admin = self.session(key)
        self.reporter = self.device("reporting")
        self.physician = self.device("physician")
        self.post("/api/v1/mappings", {"effectiveFrom": clinic_today().isoformat() + "T00:00:00+08:00",
                  "initialDateFrom": clinic_today().isoformat(), "enabled": True, "reason": "synthetic preview activation"}, self.admin)
        for _ in range(100):
            status = self.client.get("/api/v1/scans/status", headers=self.admin).json()
            if status["status"] == "succeeded":
                break
            time.sleep(.02)
        else:
            self.fail("Synthetic preview sources were not scanned")
        self.cases = self.client.get("/api/v1/cases?physician=", headers=self.reporter).json()["items"]
        self.assertEqual(len(self.cases), 20)

    def session(self, credential):
        headers = {"Authorization": "Bearer " + credential}
        result = self.client.post("/api/v1/sessions", headers=headers, json={
            "requestId": str(uuid4()), "expectedRevision": 0, "operator": "SYN-PREVIEW"})
        self.assertEqual(result.status_code, 200, result.text)
        return headers | {"X-Session-Id": result.json()["sessionId"]}

    def device(self, capability):
        grant = self.post("/api/v1/pairings", {"capabilities": [capability]}, self.admin)
        key = secrets.token_urlsafe(32)
        self.post("/api/v1/devices/enroll", {"pairingCode": grant["pairingCode"],
                  "credential": key, "name": "Synthetic " + capability}, {})
        return self.session(key)

    def post(self, path, fields, headers=None, revision=0):
        result = self.client.post(path, headers=self.reporter if headers is None else headers,
            json={"requestId": str(uuid4()), "expectedRevision": revision, **fields})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def complete(self, case):
        path = f'/api/v1/cases/{case["caseId"]}'
        saved = self.post(path + "/reason", {"reason": "23:未滿5歲及65歲以上之類流感患者", "patientConfirmed": True}, revision=case["revision"])
        return self.post(path + "/dispensing", {"reportedQuantity": 10, "lots": [{"lot": "SYN-LOT", "quantity": 10}],
                         "changeReason": "Synthetic verification"}, revision=saved["revision"])

    def test_eighteen_complete_cases_are_preselected_but_official_export_remains_blocked(self):
        for case in self.cases[:18]:
            self.complete(case)
        response = self.client.get("/api/v1/export-preview", headers=self.reporter)
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()
        self.assertEqual(preview["selectedCount"], 18)
        self.assertEqual(preview["internallyCompleteCount"], 18)
        self.assertTrue(preview["operationalFlagEnabled"])
        self.assertFalse(preview["productionExportEnabled"])
        self.assertTrue(all(gate["status"] == "OPEN" for gate in preview["gates"]))
        incomplete = [item for item in preview["items"] if not item["defaultSelected"]]
        self.assertEqual(len(incomplete), 2)
        for item in incomplete:
            self.assertIn("reason_missing", item["internalIssues"])
            self.assertIn("lots_missing", item["internalIssues"])
        for item in preview["items"]:
            self.assertIn("duplicate_concern", item["warnings"])
            self.assertIn("official_required_fields_unverified", item["officialBlockers"])
            self.assertFalse(item["officiallyExportable"])

    def test_manual_selection_exclusion_and_date_range_are_checked_centrally(self):
        first, second = (self.complete(case) for case in self.cases[:2])
        self.post(f'/api/v1/cases/{second["caseId"]}/exclusion',
                  {"excluded": True, "reason": "Synthetic uncollected medicine"}, revision=second["revision"])
        response = self.client.get("/api/v1/export-preview", headers=self.reporter,
            params=[("manualSelection", "true"), ("selected", first["caseId"]), ("selected", second["caseId"])])
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()
        self.assertEqual(preview["selectedCount"], 1)
        excluded = next(item for item in preview["items"] if item["case"]["caseId"] == second["caseId"])
        self.assertFalse(excluded["selected"])
        self.assertFalse(excluded["defaultSelected"])
        self.assertIn("excluded", excluded["internalIssues"])
        cleared = self.client.get("/api/v1/export-preview?manualSelection=true", headers=self.reporter).json()
        self.assertEqual(cleared["selectedCount"], 0)
        missing = self.client.get("/api/v1/export-preview", headers=self.reporter,
            params={"manualSelection": "true", "selected": str(uuid4())})
        self.assertEqual(missing.status_code, 422)
        wrong_range = self.client.get("/api/v1/export-preview?dateFrom=2026-10-03&dateTo=2026-10-01", headers=self.reporter)
        self.assertEqual(wrong_range.status_code, 422)

    def test_capability_and_production_gates_refuse_generation_and_download_even_with_flag(self):
        before = self.client.get("/api/v1/audit", headers=self.admin).json()
        command = {"requestId": str(uuid4()), "expectedRevision": 0,
                   "cases": [{"caseId": self.cases[0]["caseId"], "expectedRevision": self.cases[0]["revision"]}]}
        for headers in (self.admin, self.physician):
            self.assertEqual(self.client.get("/api/v1/export-preview", headers=headers).status_code, 403)
            self.assertEqual(self.client.post("/api/v1/export-preview", headers=headers, json={"selected": []}).status_code, 403)
            self.assertEqual(self.client.post("/api/v1/exports", headers=headers, json=command).status_code, 403)
        denied = self.client.post("/api/v1/exports", headers=self.reporter, json=command)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["detail"]["code"], "production_export_gated")
        self.assertTrue(denied.json()["detail"]["operationalFlagEnabled"])
        download = self.client.get(f'/api/v1/exports/{uuid4()}/file', headers=self.reporter)
        self.assertEqual(download.status_code, 403)
        self.assertNotIn("spreadsheet", download.headers["content-type"])
        self.assertEqual(self.client.get("/api/v1/audit", headers=self.admin).json(), before)
        self.assertEqual(list(Path(self.settings.state_dir).rglob("*.xlsx")), [])

    def test_source_refresh_blocks_preselection_without_overwriting_verified_reporting(self):
        complete = self.complete(self.cases[0])
        write_table(self.root / "CH012M1.DBF", [("RELKEY", 30), ("SYS_2015", 30), ("MED1", 10), ("PRICE1", 20), ("USE_TAMT", 8)],
                    [{"RELKEY": "SYN  ENCOUNTER", "SYS_2015": f"SYN-PREVIEW-{i:02}", "MED1": "ERA",
                      "PRICE1": "SYN-A059653100", "USE_TAMT": "5" if f"SYN-PREVIEW-{i:02}" == complete["sourceOrder"] else "10"}
                     for i in range(20)])
        status = self.client.get("/api/v1/scans/status", headers=self.admin).json()
        self.post("/api/v1/scans", {"dateFrom": clinic_today().isoformat(), "dateTo": clinic_today().isoformat()},
                  self.admin, revision=status["revision"])
        for _ in range(100):
            if self.client.get("/api/v1/scans/status", headers=self.admin).json()["status"] == "succeeded":
                break
            time.sleep(.02)
        preview = self.client.get("/api/v1/export-preview", headers=self.reporter).json()
        changed = next(item for item in preview["items"] if item["case"]["caseId"] == complete["caseId"])
        self.assertFalse(changed["defaultSelected"])
        self.assertIn("source_review_required", changed["internalIssues"])
        self.assertIn("source_changed", changed["warnings"])
        self.assertEqual(changed["case"]["reportedQuantity"], 10)
        self.assertEqual(changed["case"]["lots"], complete["lots"])
