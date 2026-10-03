from contextlib import redirect_stdout
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts.check_acceptance_environment import main, preflight
from scripts.prepare_smis_contract_intake import prepare


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"synthetic acceptance")

    def log_message(self, *_args):
        pass


class _ConfiguredServer(ThreadingHTTPServer):
    response_status: int = 200
    location: str | None = None


class _ConfiguredHandler(BaseHTTPRequestHandler):
    server: _ConfiguredServer

    def do_GET(self):
        self.send_response(self.server.response_status)
        if self.server.location:
            self.send_header("Location", self.server.location)
        self.end_headers()
        self.wfile.write(b"synthetic response")

    def log_message(self, *_args):
        pass


class AcceptanceEnvironmentPreflightTest(unittest.TestCase):
    def _fixtures(self, root: Path) -> tuple[Path, Path, Path, Path]:
        repository = root / "repository"
        repository.mkdir()
        template = repository / "template.xlsx"
        template.write_bytes(b"synthetic official template")
        kit = root / "private" / "smis-kit"
        kit.parent.mkdir()
        prepare(kit, template=template, repository=repository)
        executable = root / "desktop" / "clinic-antiviral-reporter.exe"
        executable.parent.mkdir()
        executable.write_bytes(b"synthetic executable")
        desktop = root / "desktop" / "current.json"
        desktop.write_text(json.dumps({
            "executable": str(executable),
            "executableSha256": hashlib.sha256(executable.read_bytes()).hexdigest().upper(),
            "version": "0.1.0", "syntheticOnly": True,
        }), encoding="utf-8")
        browser = root / "browser" / "current.json"
        browser.parent.mkdir()
        return repository, desktop, browser, kit

    def test_valid_private_handoff_is_ready_without_closing_smis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, desktop, browser, kit = self._fixtures(root)
            server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
            browser.write_text(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/"}), encoding="utf-8")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = preflight(desktop, browser, kit, repository=repository)
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()
            self.assertEqual("READY_FOR_MANUAL", result["status"])
            self.assertEqual("OPEN", result["smis"]["status"])
            self.assertEqual(12, len(result["smis"]["openScenarios"]))
            self.assertFalse(result["productionExportEnabled"])

    def test_tampered_executable_and_non_loopback_url_block_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, desktop, browser, kit = self._fixtures(root)
            desktop_data = json.loads(desktop.read_text(encoding="utf-8"))
            desktop_data["executableSha256"] = "0" * 64
            desktop.write_text(json.dumps(desktop_data), encoding="utf-8")
            browser.write_text(json.dumps({"url": "http://192.0.2.1:8000/"}), encoding="utf-8")
            result = preflight(desktop, browser, kit, repository=repository, check_browser=False)
            self.assertEqual("BLOCKED", result["status"])
            self.assertTrue(any("SHA-256" in error for error in result["errors"]))
            self.assertTrue(any("loopback" in error for error in result["errors"]))

    def test_http_error_keeps_status_and_blocks_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, desktop, browser, kit = self._fixtures(root)
            server = _ConfiguredServer(("127.0.0.1", 0), _ConfiguredHandler)
            server.response_status = 503
            server.location = None
            browser.write_text(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/"}), encoding="utf-8")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = preflight(desktop, browser, kit, repository=repository)
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()
            self.assertEqual("BLOCKED", result["status"])
            self.assertEqual(503, result["browser"]["httpStatus"])
            self.assertTrue(any("HTTP 503" in error for error in result["errors"]))

    def test_browser_redirect_is_rejected_without_following_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, desktop, browser, kit = self._fixtures(root)
            server = _ConfiguredServer(("127.0.0.1", 0), _ConfiguredHandler)
            server.response_status = 302
            server.location = "http://192.0.2.1:8000/"
            browser.write_text(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/"}), encoding="utf-8")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = preflight(desktop, browser, kit, repository=repository)
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()
            self.assertEqual("BLOCKED", result["status"])
            self.assertTrue(any("redirects are not allowed" in error for error in result["errors"]))

    def test_windows_utf8_bom_metadata_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, desktop, browser, kit = self._fixtures(root)
            browser.write_text(json.dumps({"url": "http://127.0.0.1:8000/"}), encoding="utf-8")
            for path in (desktop, browser):
                path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
            result = preflight(desktop, browser, kit, repository=repository, check_browser=False)
            self.assertEqual("READY_FOR_MANUAL", result["status"])
            self.assertTrue(result["desktop"]["ready"])
            self.assertTrue(result["browser"]["ready"])

    def test_missing_metadata_has_uniform_not_ready_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, _desktop, _browser, kit = self._fixtures(root)
            result = preflight(root / "missing-desktop.json", root / "missing-browser.json", kit,
                               repository=repository, check_browser=False)
            self.assertEqual("BLOCKED", result["status"])
            self.assertFalse(result["desktop"]["ready"])
            self.assertFalse(result["browser"]["ready"])
            self.assertIn("metadata", result["desktop"])
            self.assertIn("metadata", result["browser"])

    def test_cli_emits_json_and_returns_one_for_blocked_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, desktop, browser, kit = self._fixtures(root)
            browser.write_text(json.dumps({"url": "http://127.0.0.1:8000/"}), encoding="utf-8")
            output = io.StringIO()
            with patch.object(sys, "argv", ["check_acceptance_environment", "--desktop-metadata", str(desktop),
                                               "--browser-metadata", str(browser), "--smis-kit", str(kit),
                                               "--no-browser-health"]), redirect_stdout(output):
                main()
            self.assertEqual("READY_FOR_MANUAL", json.loads(output.getvalue())["status"])

            bad_output = io.StringIO()
            with patch.object(sys, "argv", ["check_acceptance_environment", "--desktop-metadata",
                                               str(root / "missing.json"), "--browser-metadata", str(browser),
                                               "--smis-kit", str(kit), "--no-browser-health"]), \
                    redirect_stdout(bad_output):
                with self.assertRaises(SystemExit) as raised:
                    main()
            self.assertEqual(1, raised.exception.code)
            self.assertEqual("BLOCKED", json.loads(bad_output.getvalue())["status"])

    def test_metadata_inside_repository_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, desktop, browser, kit = self._fixtures(root)
            inside = repository / "desktop.json"
            inside.write_bytes(desktop.read_bytes())
            browser.write_text(json.dumps({"url": "http://127.0.0.1:8000/"}), encoding="utf-8")
            result = preflight(inside, browser, kit, repository=repository, check_browser=False)
            self.assertEqual("BLOCKED", result["status"])
            self.assertTrue(any("desktop metadata must be outside" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
