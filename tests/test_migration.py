import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from service.app import create_app
from service.settings import Settings


class MigrationAcceptanceTest(unittest.TestCase):
    def settings(self, directory):
        return Settings.from_environment({
            "CLINIC_REPORTER_STATE_DIR": directory,
            "CLINIC_REPORTER_HIS_SOURCE_PATH": r"\\synthetic-his\data",
            "CLINIC_REPORTER_BACKUP_ROOT": r"\\synthetic-his\backup",
        })

    def test_version_one_history_and_session_survive_pairing_migration(self):
        # Synthetic input fixture for the published v1 on-disk contract. Observe
        # migration results only through the versioned API, not private tables.
        with tempfile.TemporaryDirectory() as directory:
            credential = secrets.token_urlsafe(32)
            with sqlite3.connect(Path(directory) / "central.sqlite3") as db:
                db.executescript("""
                    CREATE TABLE devices(id TEXT PRIMARY KEY,name TEXT NOT NULL,credential_hash TEXT UNIQUE NOT NULL,
                        capabilities TEXT NOT NULL,revision INTEGER NOT NULL,revoked INTEGER NOT NULL DEFAULT 0);
                    CREATE TABLE sessions(id TEXT PRIMARY KEY,device_id TEXT NOT NULL REFERENCES devices(id),
                        operator TEXT NOT NULL,expires_at REAL NOT NULL);
                    CREATE TABLE commands(actor TEXT NOT NULL,request_id TEXT NOT NULL,result TEXT NOT NULL,
                        PRIMARY KEY(actor,request_id));
                    CREATE TABLE audit_events(sequence INTEGER PRIMARY KEY,kind TEXT NOT NULL,device_id TEXT NOT NULL,
                        operator TEXT NOT NULL,occurred_at REAL NOT NULL,changes TEXT NOT NULL);
                    PRAGMA user_version=1;
                """)
                db.execute("INSERT INTO devices VALUES (?,?,?,?,?,?)", ("old-admin", "Synthetic v1 admin",
                           hashlib.sha256(credential.encode()).hexdigest(), '["admin"]', 1, 0))
                db.execute("INSERT INTO sessions VALUES (?,?,?,?)", ("old-session", "old-admin", "original operator", 9999999999))
                db.execute("INSERT INTO audit_events VALUES (1,?,?,?,?,?)", ("synthetic_v1_history", "old-admin",
                           "original operator", 1, json.dumps({"reason": "preserve this original reason"})))
            db.close()
            with TestClient(create_app(self.settings(directory)), base_url="https://testserver") as client:
                headers = {"Authorization": "Bearer " + credential, "X-Session-Id": "old-session"}
                session = client.get("/api/v1/session", headers=headers)
                self.assertEqual(session.status_code, 200)
                self.assertEqual(session.json()["operator"], "original operator")
                history = client.get("/api/v1/audit", headers=headers).json()
                self.assertEqual(history[0]["changes"], {"reason": "preserve this original reason"})
                pairing = client.post("/api/v1/pairings", headers=headers, json={
                    "requestId": str(uuid4()), "expectedRevision": 0, "capabilities": ["physician"]})
                self.assertEqual(pairing.status_code, 200, pairing.text)
                queue = client.get("/api/v1/cases", headers=headers)
                self.assertEqual(queue.status_code, 200)
                self.assertEqual(queue.json()["total"], 0)

    def test_version_two_history_survives_case_schema_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            credential = secrets.token_urlsafe(32)
            with sqlite3.connect(Path(directory) / "central.sqlite3") as db:
                db.executescript("""
                    CREATE TABLE devices(id TEXT PRIMARY KEY,name TEXT NOT NULL,credential_hash TEXT UNIQUE NOT NULL,
                        capabilities TEXT NOT NULL,revision INTEGER NOT NULL,revoked INTEGER NOT NULL DEFAULT 0);
                    CREATE TABLE sessions(id TEXT PRIMARY KEY,device_id TEXT NOT NULL REFERENCES devices(id),
                        operator TEXT NOT NULL,expires_at REAL NOT NULL);
                    CREATE TABLE commands(actor TEXT NOT NULL,request_id TEXT NOT NULL,result TEXT NOT NULL,
                        PRIMARY KEY(actor,request_id));
                    CREATE TABLE audit_events(sequence INTEGER PRIMARY KEY,kind TEXT NOT NULL,device_id TEXT NOT NULL,
                        operator TEXT NOT NULL,occurred_at REAL NOT NULL,changes TEXT NOT NULL);
                    CREATE TABLE pairings(code_hash TEXT PRIMARY KEY,capabilities TEXT NOT NULL,expires_at REAL NOT NULL,
                        used INTEGER NOT NULL DEFAULT 0,issuer TEXT NOT NULL REFERENCES devices(id));
                    PRAGMA user_version=2;
                """)
                db.execute("INSERT INTO devices VALUES (?,?,?,?,1,0)", ("v2-admin", "Synthetic v2 admin",
                           hashlib.sha256(credential.encode()).hexdigest(), '["admin"]'))
                db.execute("INSERT INTO sessions VALUES (?,?,?,?)", ("v2-session", "v2-admin", "SYN-DR-A", 9999999999))
                db.execute("INSERT INTO audit_events VALUES (1,?,?,?,?,?)", ("synthetic_v2_history", "v2-admin",
                           "SYN-DR-A", 1, json.dumps({"reason": "retain v2 reason"})))
            db.close()
            with TestClient(create_app(self.settings(directory)), base_url="https://testserver") as client:
                headers = {"Authorization": "Bearer " + credential, "X-Session-Id": "v2-session"}
                self.assertEqual(client.get("/api/v1/cases", headers=headers).json()["total"], 0)
                self.assertEqual(client.get("/api/v1/audit", headers=headers).json()[0]["changes"],
                                 {"reason": "retain v2 reason"})

    def test_newer_schema_is_rejected_without_changing_its_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "central.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("PRAGMA user_version=99")
            db.close()
            original = path.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "newer"):
                with TestClient(create_app(self.settings(directory)), base_url="https://testserver"):
                    self.fail("Future schema should not start")
            self.assertEqual(path.read_bytes(), original)

    def test_version_three_through_ten_history_survives_migration(self):
        for version in (3, 4, 5, 6, 7, 8, 9, 10):
            with tempfile.TemporaryDirectory() as directory:
                credential = secrets.token_urlsafe(32)
                case_id = "11111111-1111-4111-8111-111111111111"
                facts = {"PD011M1.NUM": "SYN-OLD", "PD011M1.NAME": "Synthetic old patient",
                         "PD011M1.BIRTH": "1990-01-01", "CH011M1.DOC": "SYN-DR-A",
                         "CH011M1.SDATE": "2026-10-02", "CH012M1.SYS_2015": "SYN-OLD-ORDER",
                         "CH012M1.USE_TAMT": "10", "CH012M1.RELKEY": "SYN RAW SPACE"}
                with sqlite3.connect(Path(directory) / "central.sqlite3") as db:
                    db.executescript("""
                        CREATE TABLE devices(id TEXT PRIMARY KEY,name TEXT,credential_hash TEXT UNIQUE,
                            capabilities TEXT,revision INTEGER,revoked INTEGER);
                        CREATE TABLE sessions(id TEXT PRIMARY KEY,device_id TEXT,operator TEXT,expires_at REAL);
                        CREATE TABLE commands(actor TEXT,request_id TEXT,result TEXT,PRIMARY KEY(actor,request_id));
                        CREATE TABLE audit_events(sequence INTEGER PRIMARY KEY,kind TEXT,device_id TEXT,
                            operator TEXT,occurred_at REAL,changes TEXT);
                        CREATE TABLE pairings(code_hash TEXT PRIMARY KEY,capabilities TEXT,expires_at REAL,used INTEGER,issuer TEXT);
                        CREATE TABLE ingestion_state(id TEXT PRIMARY KEY,revision INTEGER,anchor_date TEXT);
                        CREATE TABLE report_cases(id TEXT PRIMARY KEY,source_key TEXT UNIQUE,revision INTEGER,reported_quantity INTEGER);
                        CREATE TABLE source_snapshots(sequence INTEGER PRIMARY KEY,case_id TEXT,captured_at REAL,facts TEXT);
                        CREATE INDEX snapshots_case ON source_snapshots(case_id,sequence);
                        PRAGMA user_version=3;
                    """)
                    db.execute("INSERT INTO devices VALUES (?,?,?,?,1,0)", ("v3-admin", "Synthetic v3 admin",
                               hashlib.sha256(credential.encode()).hexdigest(), '["admin"]'))
                    db.execute("INSERT INTO sessions VALUES (?,?,?,?)", ("v3-session", "v3-admin", "SYN-DR-A", 9999999999))
                    db.execute("INSERT INTO report_cases VALUES (?,?,1,10)", (case_id, "synthetic-v1:SYN-OLD-ORDER"))
                    db.execute("INSERT INTO source_snapshots VALUES (1,?,1,?)", (case_id, json.dumps(facts)))
                if version >= 4:
                    db.execute("ALTER TABLE report_cases ADD COLUMN reason TEXT")
                    db.execute("UPDATE report_cases SET reason=?", ("23:未滿5歲及65歲以上之類流感患者",))
                    db.execute("PRAGMA user_version=4")
                    db.commit()
                if version >= 5:
                    db.execute("ALTER TABLE report_cases ADD COLUMN lots TEXT NOT NULL DEFAULT '[]'")
                    db.execute("ALTER TABLE report_cases ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0")
                    db.execute("ALTER TABLE report_cases ADD COLUMN exclusion_reason TEXT")
                    db.execute("UPDATE report_cases SET lots=?,excluded=1,exclusion_reason=?",
                               ('[{"lot":"SYN-OLD-LOT","quantity":10}]', 'synthetic previous decision'))
                    db.execute("PRAGMA user_version=5")
                    db.commit()
                if version >= 6:
                    db.executescript("""
                        ALTER TABLE report_cases ADD COLUMN reporting_snapshot INTEGER;
                        ALTER TABLE report_cases ADD COLUMN reviewed_snapshot INTEGER;
                        UPDATE report_cases SET reporting_snapshot=1,reviewed_snapshot=1;
                        CREATE TABLE source_quarantine(sequence INTEGER PRIMARY KEY,source_key TEXT,
                            captured_at REAL,facts TEXT,diagnosis TEXT,last_seen REAL,attempts INTEGER,resolved INTEGER);
                        PRAGMA user_version=6;
                    """)
                    db.execute("INSERT INTO source_snapshots VALUES (2,?,2,?)", (case_id, json.dumps(facts | {"CH012M1.USE_TAMT": "5"})))
                    db.execute("INSERT INTO source_quarantine VALUES (1,?,1,'{}','source_not_observed',2,3,0)", ("synthetic-v1:SYN-OLD-ORDER",))
                    db.commit()
                if version >= 7:
                    db.executescript("""
                        CREATE TABLE scan_state(id INTEGER PRIMARY KEY,revision INTEGER NOT NULL,current_job TEXT,last_success REAL);
                        INSERT INTO scan_state VALUES (1,2,'synthetic-old-job',100);
                        CREATE TABLE scan_runs(id TEXT PRIMARY KEY,status TEXT NOT NULL,date_from TEXT NOT NULL,
                            date_to TEXT NOT NULL,device_id TEXT NOT NULL,operator TEXT NOT NULL,requested_at REAL NOT NULL,
                            started_at REAL,finished_at REAL,diagnostic TEXT,counts TEXT NOT NULL DEFAULT '{}');
                        INSERT INTO scan_runs VALUES ('synthetic-old-job','succeeded','2026-10-01','2026-10-02',
                            'v3-admin','SYN-DR-A',98,99,100,NULL,'{"created":1}');
                        PRAGMA user_version=7;
                    """)
                if version >= 8:
                    db.executescript("""
                        CREATE TABLE mapping_versions(sequence INTEGER PRIMARY KEY,effective_from TEXT UNIQUE,
                            initial_date_from TEXT,internal_code TEXT,nhi_code TEXT,material_value TEXT,
                            quantity_rule TEXT,enabled INTEGER,reason TEXT,device_id TEXT,operator TEXT,created_at REAL);
                        ALTER TABLE source_snapshots ADD COLUMN mapping_version INTEGER;
                        ALTER TABLE scan_runs ADD COLUMN mapping_revision INTEGER NOT NULL DEFAULT 0;
                        PRAGMA user_version=8;
                    """)
                if version >= 9:
                    db.executescript("""
                        ALTER TABLE scan_runs ADD COLUMN outage_recovery INTEGER NOT NULL DEFAULT 0;
                        CREATE TABLE scan_case_observations(scan_job_id TEXT,case_id TEXT,source_snapshot INTEGER,
                            PRIMARY KEY(scan_job_id,case_id));
                        CREATE TABLE outside_completions(case_id TEXT PRIMARY KEY,source_snapshot INTEGER,
                            scan_job_id TEXT,device_id TEXT,operator TEXT,recorded_at REAL,reason TEXT);
                        PRAGMA user_version=9;
                    """)
                    db.execute("UPDATE report_cases SET excluded=0")
                    db.execute("INSERT INTO outside_completions VALUES (?,1,'synthetic-old-job','v3-admin','SYN-DR-A',101,'synthetic paper completion')", (case_id,))
                    db.commit()
                if version >= 10:
                    db.executescript("""
                        CREATE TABLE backup_state(id INTEGER PRIMARY KEY,revision INTEGER NOT NULL,current_job TEXT);
                        INSERT INTO backup_state VALUES (1,0,NULL);
                        CREATE TABLE backup_runs(id TEXT PRIMARY KEY,status TEXT NOT NULL,
                            requested_at REAL NOT NULL,snapshot_at REAL,finished_at REAL,
                            device_id TEXT NOT NULL,operator TEXT NOT NULL,reason TEXT NOT NULL,diagnostic TEXT);
                        PRAGMA user_version=10;
                    """)
                db.close()
                with TestClient(create_app(self.settings(directory)), base_url="https://testserver") as client:
                    detail = client.get(f"/api/v1/cases/{case_id}", headers={
                        "Authorization": "Bearer " + credential, "X-Session-Id": "v3-session"}).json()
                    self.assertEqual(detail["snapshots"][0]["raw"], facts)
                    self.assertEqual(detail["revision"], 1)
                    if version >= 9:
                        self.assertEqual(detail["status"], "outside_completed")
                        self.assertEqual(detail["outsideCompletion"]["reason"], "synthetic paper completion")
                        self.assertEqual(detail["outsideCompletion"]["recordedAt"], 101)
                    else:
                        self.assertIsNone(detail["outsideCompletion"])
                    backup = client.get("/api/v1/backups/status", headers={
                        "Authorization": "Bearer " + credential, "X-Session-Id": "v3-session"}).json()
                    self.assertEqual(backup["status"], "disabled")
                    self.assertTrue(backup["rpoBreached"])
                    releases = client.get("/api/v1/client-releases/current", headers={
                        "Authorization": "Bearer " + credential}).json()
                    self.assertEqual(releases, {"revision": 0, "release": None})
                    self.assertEqual(detail["reportedQuantity"], 10)
                    self.assertEqual(detail["reason"], "23:未滿5歲及65歲以上之類流感患者" if version >= 4 else None)
                    self.assertEqual(detail["lots"], [{"lot": "SYN-OLD-LOT", "quantity": 10}] if version >= 5 else [])
                    self.assertEqual(detail["excluded"], 5 <= version < 9)
                    self.assertEqual(detail["reportingSourceSnapshot"], 1)
                    self.assertEqual(detail["latestSourceSnapshot"], 2 if version >= 6 else 1)
                    mappings = client.get("/api/v1/mappings", headers={
                        "Authorization": "Bearer " + credential, "X-Session-Id": "v3-session"}).json()
                    self.assertIsNone(mappings["goLiveAt"])
                    self.assertEqual(mappings["versions"], [])
                    if version >= 7:
                        scan = client.get("/api/v1/scans/status", headers={
                            "Authorization": "Bearer " + credential, "X-Session-Id": "v3-session"}).json()
                        self.assertEqual(scan["jobId"], "synthetic-old-job")
                        self.assertEqual(scan["counts"], {"created": 1})
                        self.assertEqual(scan["lastSuccessAt"], 100)
                    if version >= 6:
                        self.assertTrue(detail["sourceReviewRequired"])
                        self.assertTrue(detail["sourceUnresolved"])
                        quarantine = client.get("/api/v1/source-quarantine", headers={
                            "Authorization": "Bearer " + credential, "X-Session-Id": "v3-session"}).json()
                        self.assertEqual(quarantine[0]["attempts"], 3)
