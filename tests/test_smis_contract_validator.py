from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.prepare_smis_contract_intake import main as prepare_main, prepare
from scripts.validate_smis_contract_intake import main as validate_main, validate


class SmisContractValidatorTest(unittest.TestCase):
    def _kit(self, root: Path) -> Path:
        repository = root / "repository"
        repository.mkdir()
        template = repository / "template.xlsx"
        template.write_bytes(b"synthetic official template")
        output = root / "private" / "kit"
        output.parent.mkdir()
        prepare(output, template=template, repository=repository)
        return output

    def test_prepared_kit_is_structurally_valid_but_not_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = validate(self._kit(Path(directory)))
            self.assertFalse(result.errors)
            self.assertFalse(result.complete)
            self.assertEqual(result.open_scenarios, tuple(f"S{index:02d}" for index in range(1, 13)))

    def test_complete_observed_results_pass_require_complete_without_enabling_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kit = self._kit(Path(directory))
            manifest_path = kit / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for scenario in manifest["scenarios"]:
                scenario.update(status="PASS", observedResult="synthetic owner result",
                                evidence="sha256:" + "A" * 64)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = validate(kit, require_complete=True)

            self.assertTrue(result.complete)
            self.assertFalse(result.errors)
            self.assertFalse(manifest["productionExportEnabled"])

    def test_tampered_template_and_path_escape_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kit = self._kit(Path(directory))
            (kit / "template.xlsx").write_bytes(b"tampered")
            manifest_path = kit / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = validate(kit)

            self.assertTrue(any("does not match" in error for error in result.errors))

            manifest["template"]["file"] = "../outside.xlsx"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = validate(kit)
            self.assertTrue(any("template.file" in error for error in result.errors))

    def test_bom_is_accepted_and_invalid_scenario_is_not_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kit = self._kit(Path(directory))
            manifest_path = kit / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["scenarios"][0].update(status="PASS", observedResult=" ", evidence="reference")
            manifest_path.write_text("\ufeff" + json.dumps(manifest), encoding="utf-8")

            result = validate(kit)

            self.assertTrue(any("observedResult" in error for error in result.errors))
            self.assertNotIn("S01", result.completed_scenarios)

    def test_invalid_manifest_bytes_return_a_controlled_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kit = self._kit(Path(directory))
            (kit / "manifest.json").write_bytes(b"\xff\xfe\x00\x00")

            result = validate(kit)

            self.assertTrue(any(error.startswith("Cannot read manifest.json:") for error in result.errors))

    def test_root_and_drive_relative_template_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kit = self._kit(Path(directory))
            manifest_path = kit / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for value in (r"\Windows\template.xlsx", r"C:outside.xlsx"):
                manifest["template"]["file"] = value
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                result = validate(kit)
                self.assertTrue(any("template.file must not escape" in error for error in result.errors))

    def test_validator_rejects_a_directory_junction_kit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kit = self._kit(root)
            linked = root / "linked-kit"
            junction = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(kit)],
                                      capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if junction.returncode:
                self.skipTest("This Windows account cannot create a test junction")
            try:
                result = validate(linked)
                self.assertTrue(any("links or reparse" in error for error in result.errors))
            finally:
                linked.rmdir()

    def test_cli_reports_open_kit_and_rejects_require_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "kit"
            with patch("sys.argv", ["prepare_smis_contract_intake", "--output", str(output)]), \
                    redirect_stdout(io.StringIO()):
                prepare_main()
            stdout = io.StringIO()
            with patch("sys.argv", ["validate_smis_contract_intake", "--kit", str(output)]), \
                    redirect_stdout(stdout):
                validate_main()
            self.assertIn('"status": "OPEN"', stdout.getvalue())
            with patch("sys.argv", ["validate_smis_contract_intake", "--kit", str(output), "--require-complete"]), \
                    redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(SystemExit, "1"):
                    validate_main()


if __name__ == "__main__":
    unittest.main()
