import builtins
from dataclasses import replace
import io
from contextlib import contextmanager
from datetime import date, timedelta
import hashlib
from pathlib import Path
import secrets
import tempfile
import time
from threading import Event
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from scripts.synthetic_dbf import prepare
from service.app import create_app
from service.provision import initialize_administrator
from service.settings import Settings


class ScannerTest(unittest.TestCase):
    def test_initial_range_excludes_older_sources_and_rejects_earlier_manual_scan(self):
        yesterday = date.today() - timedelta(days=1)
        with self.environment(fixture_date=yesterday) as (client, headers, state, root):
            status = self.wait_scan(client, headers)
            self.assertEqual(status["status"], "succeeded")
            self.assertEqual(client.get("/api/v1/cases", headers=headers).json()["total"], 0)
            response = client.post("/api/v1/scans", headers=headers, json={"requestId": str(uuid4()),
                "expectedRevision": status["revision"], "dateFrom": yesterday.isoformat(), "dateTo": date.today().isoformat()})
            self.assertEqual(response.status_code, 422)
            prepare(state, date.today())
            self.assertEqual(self.rescan(client, headers)["status"], "succeeded")
            self.assertEqual(client.get("/api/v1/cases", headers=headers).json()["total"], 1)

    def test_mapping_change_during_file_read_applies_only_to_later_scan(self):
        initial = date.today() - timedelta(days=1)
        with self.environment(configure=False) as (client, headers, state, root):
            entered, release = Event(), Event()
            original_open = io.open
            def delayed_open(file, mode="r", *args, **kwargs):
                if isinstance(file, (str, Path)) and Path(file).suffix == ".DBF" and Path(file).is_relative_to(root) and not entered.is_set():
                    entered.set()
                    if not release.wait(5):
                        raise OSError("Synthetic boundary wait timed out")
                return original_open(file, mode, *args, **kwargs)
            with patch("io.open", delayed_open):
                try:
                    self.configure_mapping(client, headers, initial)
                    self.assertTrue(entered.wait(2))
                    changed = client.post("/api/v1/mappings", headers=headers, json={
                        "requestId": str(uuid4()), "expectedRevision": 1,
                        "effectiveFrom": date.today().isoformat() + "T00:00:00+08:00",
                        "initialDateFrom": initial.isoformat(), "enabled": False,
                        "reason": "Synthetic mapping changed during source read"})
                    self.assertEqual(changed.status_code, 200, changed.text)
                finally:
                    release.set()
                self.assertEqual(self.wait_scan(client, headers)["status"], "succeeded")
            case = client.get("/api/v1/cases", headers=headers).json()["items"][0]
            detail = client.get(f'/api/v1/cases/{case["caseId"]}', headers=headers).json()
            self.assertEqual(detail["snapshots"][0]["mappingVersion"], 1)
            self.assertEqual(self.rescan(client, headers)["status"], "partial")
            self.assertTrue(client.get(f'/api/v1/cases/{case["caseId"]}', headers=headers).json()["sourceUnresolved"])

    def configure_mapping(self, client, headers, initial_date):
        response = client.post("/api/v1/mappings", headers=headers, json={
            "requestId": str(uuid4()), "expectedRevision": 0,
            "effectiveFrom": initial_date.isoformat() + "T00:00:00+08:00",
            "initialDateFrom": initial_date.isoformat(), "enabled": True,
            "reason": "Explicit synthetic scan activation"})
        self.assertEqual(response.status_code, 200, response.text)

    def test_scanner_waits_for_explicit_mapping_and_preserves_version_reference(self):
        with self.environment(configure=False) as (client, headers, state, root):
            time.sleep(.2)
            status = client.get("/api/v1/scans/status", headers=headers).json()
            self.assertEqual(status["status"], "awaiting_configuration")
            self.assertEqual(client.get("/api/v1/cases", headers=headers).json()["total"], 0)
            self.configure_mapping(client, headers, date.today())
            self.assertEqual(self.wait_scan(client, headers)["status"], "succeeded")
            case = client.get("/api/v1/cases", headers=headers).json()["items"][0]
            detail = client.get(f'/api/v1/cases/{case["caseId"]}', headers=headers).json()
            self.assertEqual(detail["snapshots"][0]["mappingVersion"], 1)
            self.assertEqual(detail["snapshots"][0]["raw"]["CH011M1.SDATE"], date.today().isoformat())

    def test_effective_versions_isolate_disabled_sources_and_keep_old_snapshots(self):
        initial = date.today() - timedelta(days=2)
        with self.environment(initial_date=initial, fixture_date=initial) as (client, headers, state, root):
            self.wait_scan(client, headers)
            case = client.get("/api/v1/cases", headers=headers).json()["items"][0]
            path = f'/api/v1/cases/{case["caseId"]}'
            original = client.get(path, headers=headers).json()
            for revision, effective, enabled in [(1, date.today() - timedelta(days=1), False), (2, date.today(), True)]:
                response = client.post("/api/v1/mappings", headers=headers, json={
                    "requestId": str(uuid4()), "expectedRevision": revision,
                    "effectiveFrom": effective.isoformat() + "T00:00:00+08:00",
                    "initialDateFrom": initial.isoformat(), "enabled": enabled,
                    "reason": "synthetic version transition"})
                self.assertEqual(response.status_code, 200, response.text)
            prepare(state, date.today() - timedelta(days=1), "quantity")
            status = client.get("/api/v1/scans/status", headers=headers).json()
            client.post("/api/v1/scans", headers=headers, json={"requestId": str(uuid4()),
                "expectedRevision": status["revision"], "dateFrom": initial.isoformat(), "dateTo": date.today().isoformat()})
            self.assertEqual(self.wait_scan(client, headers)["status"], "partial")
            isolated = client.get(path, headers=headers).json()
            self.assertTrue(isolated["sourceUnresolved"])
            self.assertEqual(isolated["snapshots"], original["snapshots"])
            prepare(state, date.today(), "quantity")
            self.assertEqual(self.rescan(client, headers)["status"], "succeeded")
            recovered = client.get(path, headers=headers).json()
            self.assertEqual([s["mappingVersion"] for s in recovered["snapshots"]], [1, 3])
            self.assertEqual(recovered["snapshots"][0], original["snapshots"][0])
            self.assertEqual(recovered["reportedQuantity"], 10)
            self.assertEqual(recovered["sourceDifferences"]["mappingVersion"], {"before": "1", "after": "3"})
            self.assertTrue(recovered["sourceReviewRequired"])

    def test_invalid_update_moving_into_manual_date_range_is_quarantined(self):
        yesterday = date.today() - timedelta(days=1)
        with self.environment(initial_date=yesterday, fixture_date=yesterday) as (client, headers, state, root):
            self.wait_scan(client, headers)
            case = client.get("/api/v1/cases", headers=headers).json()["items"][0]
            prepare(state, date.today(), "mismatch")
            result = self.rescan(client, headers)
            self.assertEqual(result["status"], "partial")
            detail = client.get(f'/api/v1/cases/{case["caseId"]}', headers=headers).json()
            self.assertTrue(detail["sourceUnresolved"])
            self.assertEqual(detail["revision"], case["revision"] + 1)
            self.assertEqual(len(detail["snapshots"]), 1)

    def test_fixture_author_rejects_non_temporary_roots_without_creating_files(self):
        for destination in (Path.cwd(), Path(tempfile.gettempdir()), Path(r"\\synthetic-his\data")):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                prepare(destination, date.today())
        with tempfile.TemporaryDirectory() as directory:
            with patch("service.synthetic_paths.ctypes.windll.kernel32.GetDriveTypeW", return_value=4):
                with self.assertRaises(ValueError):
                    prepare(Path(directory), date.today())
            self.assertEqual(list(Path(directory).iterdir()), [])
            with patch.object(Path, "is_junction", return_value=True):
                with self.assertRaises(ValueError):
                    prepare(Path(directory), date.today())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_raw_key_boundaries_remain_distinct_cases(self):
        with self.environment("boundary_keys") as (client, headers, state, root):
            self.assertEqual(self.wait_scan(client, headers)["status"], "succeeded")
            cases = client.get("/api/v1/cases", headers=headers).json()["items"]
            self.assertEqual(len(cases), 2)
            self.assertNotEqual(cases[0]["caseId"], cases[1]["caseId"])
            keys = [client.get(f'/api/v1/cases/{case["caseId"]}', headers=headers).json()["snapshots"][0]["raw"]["raw.CH012M1.SYS_2015"] for case in cases]
            self.assertNotEqual(keys[0], keys[1])

    def test_manual_range_does_not_revise_cases_outside_both_prior_and_new_dates(self):
        yesterday = date.today() - timedelta(days=1)
        with self.environment(initial_date=yesterday) as (client, headers, state, root):
            status = self.wait_scan(client, headers)
            case = client.get("/api/v1/cases", headers=headers).json()["items"][0]
            path = f'/api/v1/cases/{case["caseId"]}'
            before = client.get(path, headers=headers).json()
            prepare(state, date.today(), "quantity")
            response = client.post("/api/v1/scans", headers=headers, json={"requestId": str(uuid4()),
                "expectedRevision": status["revision"], "dateFrom": yesterday.isoformat(), "dateTo": yesterday.isoformat()})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.wait_scan(client, headers)["status"], "succeeded")
            self.assertEqual(client.get(path, headers=headers).json(), before)
            self.assertEqual(self.rescan(client, headers)["status"], "succeeded")
            self.assertTrue(client.get(path, headers=headers).json()["sourceReviewRequired"])

    def test_accepted_request_replays_after_restart_with_scanner_disabled(self):
        with self.environment() as (client, headers, state, root):
            status = self.wait_scan(client, headers)
            command = {"requestId": str(uuid4()), "expectedRevision": status["revision"],
                       "dateFrom": date.today().isoformat(), "dateTo": date.today().isoformat()}
            accepted = client.post("/api/v1/scans", headers=headers, json=command)
            self.assertEqual(accepted.status_code, 200)
            self.wait_scan(client, headers)
            settings = replace(client.app.state.scanner.settings, synthetic_dbf_enabled=False)
            client.__exit__(None, None, None)
            try:
                with TestClient(create_app(settings), base_url="https://testserver") as restarted:
                    replay = restarted.post("/api/v1/scans", headers=headers, json=command)
                    self.assertEqual(replay.status_code, 200)
                    self.assertEqual(replay.json(), accepted.json())
                    new = restarted.post("/api/v1/scans", headers=headers, json=command | {"requestId": str(uuid4())})
                    self.assertEqual(new.status_code, 403)
            finally:
                client.__enter__()

    def test_failed_ingestion_rolls_back_and_worker_remains_retryable(self):
        with self.environment() as (client, headers, state, root):
            self.wait_scan(client, headers)
            case = client.get("/api/v1/cases", headers=headers).json()["items"][0]
            path = f'/api/v1/cases/{case["caseId"]}'
            before = client.get(path, headers=headers).json()
            prepare(state, date.today(), "quantity")
            with client.app.state.store.transaction() as db:
                db.execute("CREATE TRIGGER synthetic_scan_failure BEFORE INSERT ON audit_events "
                           "WHEN NEW.kind='scan_finished' BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
            failed = self.rescan(client, headers)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["diagnostic"], "ingestion_failed")
            self.assertEqual(client.get(path, headers=headers).json(), before)
            with client.app.state.store.transaction() as db:
                db.execute("DROP TRIGGER synthetic_scan_failure")
            self.assertEqual(self.rescan(client, headers)["status"], "succeeded")
            self.assertEqual(len(client.get(path, headers=headers).json()["snapshots"]), 2)

    def test_authorized_physician_can_request_scan_but_cannot_read_quarantine(self):
        with self.environment("orphan") as (client, headers, state, root):
            status = self.wait_scan(client, headers)
            grant = client.post("/api/v1/pairings", headers=headers, json={
                "requestId": str(uuid4()), "expectedRevision": 0, "capabilities": ["physician"]}).json()
            key = secrets.token_urlsafe(32)
            client.post("/api/v1/devices/enroll", json={"requestId": str(uuid4()), "expectedRevision": 0,
                "pairingCode": grant["pairingCode"], "credential": key, "name": "Synthetic scan physician"})
            session = client.post("/api/v1/sessions", headers={"Authorization": "Bearer " + key}, json={
                "requestId": str(uuid4()), "expectedRevision": 0, "operator": "SYN-DR-A"}).json()
            physician = {"Authorization": "Bearer " + key, "X-Session-Id": session["sessionId"]}
            self.assertEqual(client.get("/api/v1/source-quarantine", headers=physician).status_code, 403)
            command = {"requestId": str(uuid4()), "expectedRevision": status["revision"],
                       "dateFrom": "1900-01-01", "dateTo": date.today().isoformat()}
            self.assertEqual(client.post("/api/v1/scans", headers=physician, json=command).status_code, 422)
            self.assertEqual(self.rescan(client, physician)["status"], "partial")
            latest = client.get("/api/v1/scans/status", headers=physician).json()
            stale = client.post("/api/v1/scans", headers=physician, json=command | {"dateFrom": date.today().isoformat()})
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(stale.json()["detail"]["currentRevision"], latest["revision"])

    @contextmanager
    def environment(self, scenario="valid", interval=60, initial_date=None, fixture_date=None, configure=True):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            root = prepare(state, fixture_date or date.today(), scenario)
            settings = Settings.from_environment({"CLINIC_REPORTER_STATE_DIR": directory,
                "CLINIC_REPORTER_HIS_SOURCE_PATH": r"\\synthetic-his\data",
                "CLINIC_REPORTER_BACKUP_ROOT": r"\\synthetic-his\backup",
                "CLINIC_REPORTER_SYNTHETIC_ENABLED": "true", "CLINIC_REPORTER_SYNTHETIC_DBF_ENABLED": "true",
                "CLINIC_REPORTER_HIS_SCAN_INTERVAL_SECONDS": str(interval)})
            key = secrets.token_urlsafe(32)
            initialize_administrator(settings, "Synthetic scanner admin", key)
            with TestClient(create_app(settings), base_url="https://testserver") as client:
                session = client.post("/api/v1/sessions", headers={"Authorization": "Bearer " + key}, json={
                    "requestId": str(uuid4()), "expectedRevision": 0, "operator": "SYN-DR-A"}).json()
                headers = {"Authorization": "Bearer " + key, "X-Session-Id": session["sessionId"]}
                if configure:
                    self.configure_mapping(client, headers, initial_date or date.today())
                yield client, headers, state, root

    def rescan(self, client, headers):
        status = self.wait_scan(client, headers)
        response = client.post("/api/v1/scans", headers=headers, json={
            "requestId": str(uuid4()), "expectedRevision": status["revision"],
            "dateFrom": date.today().isoformat(), "dateTo": date.today().isoformat()})
        self.assertEqual(response.status_code, 200, response.text)
        return self.wait_scan(client, headers)

    def test_bad_sources_quarantine_recover_and_do_not_expose_paths(self):
        for scenario, expected in [("orphan", "orphan_join"), ("mismatch", "code_mismatch"),
                ("ambiguous", "ambiguous_key"), ("missing_key", "missing_key"),
                ("decode", "decoding_error"), ("partial", "partial_or_unsupported_table"),
                ("unseen", "registration_not_seen_with_order")]:
            with self.subTest(scenario=scenario), self.environment(scenario) as (client, headers, state, root):
                status = self.wait_scan(client, headers)
                self.assertIn(status["status"], ("failed", "partial"))
                self.assertIsNone(status["lastSuccessAt"])
                self.assertEqual(client.get("/api/v1/cases", headers=headers).json()["total"], 0)
                quarantine = client.get("/api/v1/source-quarantine", headers=headers).json()
                self.assertIn(expected, [q["diagnosis"] for q in quarantine])
                self.assertNotIn(str(state), str(status) + str(quarantine))
                prepare(state, date.today())
                recovered = self.rescan(client, headers)
                self.assertEqual(recovered["status"], "succeeded")
                self.assertEqual(client.get("/api/v1/cases", headers=headers).json()["total"], 1)
                self.assertTrue(all(q["resolved"] for q in client.get("/api/v1/source-quarantine", headers=headers).json()))

    def test_periodic_rescan_detects_changed_file_and_deleted_order_never_deletes_case(self):
        with self.environment(interval=1) as (client, headers, state, root):
            first = self.wait_scan(client, headers)
            prepare(state, date.today(), "quantity")
            for _ in range(100):
                status = client.get("/api/v1/scans/status", headers=headers).json()
                if status["jobId"] != first["jobId"] and status["status"] == "succeeded":
                    break
                time.sleep(.03)
            else:
                self.fail("Periodic worker did not observe fresh source bytes")
            case = client.get("/api/v1/cases", headers=headers).json()["items"][0]
            self.assertTrue(case["sourceReviewRequired"])
            self.assertEqual(case["reportedQuantity"], 10)
            self.assertEqual(case["sourceDifferences"]["CH012M1.USE_TAMT"]["after"], "5")
            prepare(state, date.today(), "deleted")
            self.rescan(client, headers)
            latest = client.get(f'/api/v1/cases/{case["caseId"]}', headers=headers).json()
            self.assertFalse(latest["excluded"])
            self.assertTrue(latest["sourceUnresolved"])
            self.assertEqual(len(latest["snapshots"]), 2)

    def test_windows_sharing_violation_is_bounded_and_retry_recovers(self):
        import ctypes
        from ctypes import wintypes
        with self.environment() as (client, headers, state, root):
            self.wait_scan(client, headers)
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                               wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            close = kernel.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close.restype = wintypes.BOOL
            handle = create(str(root / "CH012M1.DBF"), 0x80000000, 0, None, 3, 0x80, None)
            self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
            try:
                started = time.monotonic()
                failure = self.rescan(client, headers)
                self.assertEqual(failure["status"], "failed")
                self.assertEqual(failure["diagnostic"], "sharing_or_access_denied")
                self.assertLess(time.monotonic() - started, 3)
            finally:
                close(handle)
            self.assertEqual(self.rescan(client, headers)["status"], "succeeded")

    def test_periodic_file_scan_runs_without_client_and_preserves_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            root = prepare(state, date.today())
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
            settings = Settings.from_environment({"CLINIC_REPORTER_STATE_DIR": directory,
                "CLINIC_REPORTER_HIS_SOURCE_PATH": r"\\synthetic-his\data",
                "CLINIC_REPORTER_BACKUP_ROOT": r"\\synthetic-his\backup",
                "CLINIC_REPORTER_SYNTHETIC_ENABLED": "true", "CLINIC_REPORTER_SYNTHETIC_DBF_ENABLED": "true",
                "CLINIC_REPORTER_HIS_SCAN_FROM_DATE": date.today().isoformat()})
            key = secrets.token_urlsafe(32)
            initialize_administrator(settings, "Synthetic scanner admin", key)
            opened = []
            with TestClient(create_app(settings), base_url="https://testserver") as setup_client:
                setup_headers = {"Authorization": "Bearer " + key}
                session = setup_client.post("/api/v1/sessions", headers=setup_headers, json={
                    "requestId": str(uuid4()), "expectedRevision": 0, "operator": "SYN-ADMIN"}).json()
                setup_headers["X-Session-Id"] = session["sessionId"]
                self.configure_mapping(setup_client, setup_headers, date.today())
                self.wait_scan(setup_client, setup_headers)
            def spy(original):
                def checked(file, mode="r", *args, **kwargs):
                    if isinstance(file, (str, Path)) and Path(file).is_relative_to(root):
                        opened.append((Path(file).name, mode))
                        self.assertFalse(any(flag in mode for flag in ("w", "a", "+", "x")))
                    return original(file, mode, *args, **kwargs)
                return checked
            with patch("builtins.open", spy(builtins.open)), patch("io.open", spy(io.open)), \
                    TestClient(create_app(settings), base_url="https://testserver") as client:
                # Restarted scanner runs from persisted configuration without an active client.
                time.sleep(.3)
                session = client.post("/api/v1/sessions", headers={"Authorization": "Bearer " + key}, json={
                    "requestId": str(uuid4()), "expectedRevision": 0, "operator": "SYN-DR-A"}).json()
                headers = {"Authorization": "Bearer " + key, "X-Session-Id": session["sessionId"]}
                status = self.wait_scan(client, headers)
                self.assertEqual(status["status"], "succeeded")
                queue = client.get("/api/v1/cases", headers=headers).json()
                self.assertEqual(queue["total"], 1)
                case = queue["items"][0]
                self.assertEqual(case["sourceQuantity"], 10)
                detail = client.get(f'/api/v1/cases/{case["caseId"]}', headers=headers).json()
                self.assertEqual(detail["snapshots"][0]["raw"]["raw.CH012M1.RELKEY"], "SYN  ENCOUNTER".ljust(30))
                command = {"requestId": str(uuid4()), "expectedRevision": status["revision"],
                           "dateFrom": date.today().isoformat(), "dateTo": date.today().isoformat()}
                accepted = client.post("/api/v1/scans", headers=headers, json=command)
                self.assertEqual(accepted.status_code, 200, accepted.text)
                self.assertEqual(client.post("/api/v1/scans", headers=headers, json=command).json(), accepted.json())
                self.assertEqual(self.wait_scan(client, headers)["status"], "succeeded")
                self.assertEqual(client.get("/api/v1/cases", headers=headers).json()["total"], 1)
            after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
            self.assertEqual(before, after)
            self.assertTrue(any(name == "CH012M1.DBF" and mode == "rb" for name, mode in opened))

    def wait_scan(self, client, headers):
        for _ in range(100):
            response = client.get("/api/v1/scans/status", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            if result["status"] not in ("queued", "running", "idle"):
                return result
            time.sleep(.02)
        self.fail("Synthetic scan did not complete")
