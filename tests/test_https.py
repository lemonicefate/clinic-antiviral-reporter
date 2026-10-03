"""Real HTTPS acceptance with generated synthetic credentials outside Git."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import tempfile
from threading import Thread
import time
import unittest
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import uvicorn

from service.app import create_app
from service.provision import initialize_administrator
from service.settings import Settings


class HttpsAcceptanceTest(unittest.TestCase):
    def test_real_listener_accepts_trusted_tls_and_rejects_untrusted_tls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic localhost test")])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
                    .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
                    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                    .sign(key, hashes.SHA256()))
            cert_path, key_path = root / "synthetic.crt", root / "synthetic.key"
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            environment = dict(os.environ) | {
                "CLINIC_REPORTER_ENV": "development", "CLINIC_REPORTER_STATE_DIR": str(root / "state"),
                "CLINIC_REPORTER_HIS_SOURCE_PATH": r"\\synthetic-his\data",
                "CLINIC_REPORTER_BACKUP_ROOT": r"\\synthetic-his\backup",
                "CLINIC_REPORTER_BIND_HOST": "127.0.0.1", "CLINIC_REPORTER_BIND_PORT": str(port),
            }
            credential = secrets.token_urlsafe(32)
            initialize_administrator(Settings.from_environment(environment), "Synthetic TLS admin", credential)
            server = uvicorn.Server(uvicorn.Config(create_app(Settings.from_environment(environment)),
                                    host="127.0.0.1", port=port, ssl_certfile=str(cert_path),
                                    ssl_keyfile=str(key_path), access_log=False, log_level="critical"))
            thread = Thread(target=server.run)
            thread.start()
            try:
                endpoint = f"https://localhost:{port}"
                trusted = ssl.create_default_context(cafile=str(cert_path))
                deadline = time.monotonic() + 10
                while True:
                    self.assertTrue(thread.is_alive(), "Synthetic central service exited during startup")
                    try:
                        with urlopen(endpoint + "/api/v1/openapi.json", context=trusted, timeout=1):
                            break
                    except (URLError, TimeoutError):
                        if time.monotonic() >= deadline:
                            self.fail("Synthetic HTTPS listener did not become available")
                        time.sleep(0.1)
                with self.assertRaises(URLError):
                    urlopen(endpoint + "/api/v1/openapi.json", context=ssl.create_default_context(), timeout=2)
                payload = json.dumps({"requestId": str(uuid4()), "expectedRevision": 0, "operator": "synthetic"}).encode()
                request = Request(endpoint + "/api/v1/sessions", data=payload,
                                  headers={"Authorization": "Bearer " + credential, "Content-Type": "application/json"})
                with urlopen(request, context=trusted, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.load(response)["capabilities"], ["admin"])
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
            finally:
                server.should_exit = True
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive(), "Synthetic listener did not stop cleanly")
