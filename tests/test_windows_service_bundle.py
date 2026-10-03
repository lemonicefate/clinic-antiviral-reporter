import hashlib
import io
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from scripts.windows_service_bundle import (
    PINNED_WINSW_SHA256,
    ServiceBundle,
    create_bundle,
    main,
)


class WindowsServiceBundleTest(unittest.TestCase):
    def test_bundle_is_explicit_secret_free_and_refuses_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release & version"
            release.mkdir()
            python = release / ".venv/Scripts/python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"synthetic python")
            environment = root / "protected/runtime.env"
            certificate = root / "protected/central.crt"
            private_key = root / "protected/central.key"
            for path in (environment, certificate, private_key):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("synthetic", encoding="utf-8")
            wrapper = root / "download/WinSW-x64.exe"
            wrapper.parent.mkdir()
            wrapper.write_bytes(b"synthetic pinned wrapper")
            digest = hashlib.sha256(wrapper.read_bytes()).hexdigest().upper()
            output = root / "service"

            result = create_bundle(
                ServiceBundle(output, release, python, environment, certificate, private_key, wrapper),
                expected_winsw_sha256=digest,
            )

            self.assertEqual(result, output.resolve())
            self.assertEqual((output / "central-service.exe").read_bytes(), wrapper.read_bytes())
            self.assertTrue((output / "logs").is_dir())
            document = ET.parse(output / "central-service.xml").getroot()
            self.assertEqual(document.findtext("id"), "ClinicAntiviralReporter")
            self.assertEqual(document.findtext("executable"), str(python.resolve()))
            self.assertEqual(document.findtext("workingdirectory"), str(release.resolve()))
            arguments = document.findtext("arguments") or ""
            self.assertIn(str(environment.resolve()), arguments)
            self.assertIn(str(certificate.resolve()), arguments)
            self.assertIn(str(private_key.resolve()), arguments)
            self.assertEqual(document.findtext("startmode"), "Automatic")
            self.assertIsNotNone(document.find("delayedAutoStart"))
            self.assertEqual(document.find("onfailure").attrib, {"action": "restart", "delay": "10 sec"})
            self.assertIsNone(document.find("serviceaccount"))
            self.assertNotIn("password", (output / "central-service.xml").read_text(encoding="utf-8").lower())
            manifest = (output / "README.txt").read_text(encoding="utf-8")
            self.assertIn(digest, manifest)
            self.assertIn(PINNED_WINSW_SHA256, manifest)
            with self.assertRaisesRegex(ValueError, "already exists"):
                create_bundle(
                    ServiceBundle(output, release, python, environment, certificate, private_key, wrapper),
                    expected_winsw_sha256=digest,
                )

    def test_rejects_unpinned_wrapper_and_relative_or_linked_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            release.mkdir()
            python = release / "python.exe"
            environment = root / "runtime.env"
            certificate = root / "central.crt"
            private_key = root / "central.key"
            wrapper = root / "WinSW-x64.exe"
            for path in (python, environment, certificate, private_key, wrapper):
                path.write_bytes(b"synthetic")
            bundle = ServiceBundle(root / "service", release, python, environment, certificate, private_key, wrapper)
            with self.assertRaisesRegex(ValueError, "WinSW SHA-256"):
                create_bundle(bundle)
            relative = ServiceBundle(Path("relative"), release, python, environment, certificate, private_key, wrapper)
            with self.assertRaisesRegex(ValueError, "absolute"):
                create_bundle(relative, expected_winsw_sha256=hashlib.sha256(b"synthetic").hexdigest())

            external_python = root / "other-python.exe"
            external_python.write_bytes(b"synthetic")
            external = ServiceBundle(root / "external", release, external_python, environment,
                                     certificate, private_key, wrapper)
            with self.assertRaisesRegex(ValueError, "inside the versioned release"):
                create_bundle(external, expected_winsw_sha256=hashlib.sha256(b"synthetic").hexdigest())

            environment.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "non-empty"):
                create_bundle(bundle, expected_winsw_sha256=hashlib.sha256(b"synthetic").hexdigest())

    def test_rejects_a_broken_link_before_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            broken = root / "broken-output"
            try:
                os.symlink(root / "missing-target", broken, target_is_directory=True)
            except OSError:
                target = root / "junction-target"
                target.mkdir()
                result = subprocess.run(["cmd", "/c", "mklink", "/J", str(broken), str(target)],
                                        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode:
                    self.skipTest("This Windows account cannot create a test link or junction")
                target.rmdir()
            bundle = ServiceBundle(broken, root, root / "python.exe", root / "runtime.env",
                                   root / "central.crt", root / "central.key", root / "WinSW-x64.exe")
            with self.assertRaisesRegex(ValueError, "links or reparse"):
                create_bundle(bundle)

    def test_public_cli_parses_paths_and_reports_a_controlled_error(self) -> None:
        arguments = ["windows_service_bundle", "--output", "C:\\service", "--release-root", "C:\\release",
                     "--python", "C:\\release\\python.exe", "--env-file", "C:\\protected\\runtime.env",
                     "--cert", "C:\\protected\\central.crt", "--key", "C:\\protected\\central.key",
                     "--winsw", "C:\\download\\WinSW-x64.exe"]
        with patch.object(sys, "argv", arguments), patch(
            "scripts.windows_service_bundle.create_bundle", side_effect=ValueError("synthetic refusal")
        ), patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaisesRegex(SystemExit, "1"):
                main()
        self.assertEqual(stderr.getvalue(), "synthetic refusal\n")


if __name__ == "__main__":
    unittest.main()
