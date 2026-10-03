from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.prepare_his_contract_intake import SCENARIOS, main as prepare_main, prepare
from scripts.validate_his_contract_intake import main as validate_main, validate


class HisContractValidatorTest(unittest.TestCase):
    def _kit(self, root: Path) -> Path:
        repository = root / "repository"
        repository.mkdir()
        output = root / "private" / "kit"
        output.parent.mkdir()
        prepare(output, repository=repository)
        return output

    def test_prepared_kit_is_valid_but_remains_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = validate(self._kit(Path(directory)))
            self.assertFalse(result.errors)
            self.assertFalse(result.complete)
            self.assertEqual(result.open_scenarios,
                             tuple(scenario["id"] for scenario in SCENARIOS))

    def test_complete_results_require_roles_and_do_not_enable_his(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kit = self._kit(Path(directory))
            manifest_path = kit / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for scenario in manifest["scenarios"]:
                scenario.update(status="PASS", observedResult="synthetic owner result",
                                evidence="sha256:" + "A" * 64,
                                observedAt="2026-10-03T12:00:00+08:00",
                                ownerRole="synthetic HIS owner",
                                reviewerRole="independent synthetic reviewer")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = validate(kit, require_complete=True)

            self.assertTrue(result.complete)
            self.assertFalse(result.errors)
            self.assertFalse(manifest["productionHISAccessEnabled"])

    def test_rejects_raw_source_files_and_source_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kit = self._kit(Path(directory))
            (kit / "raw.DBF").write_bytes(b"synthetic source is forbidden")
            manifest_path = kit / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["sourcePath"] = r"\\synthetic-his\data"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = validate(kit)

            self.assertTrue(any("raw HIS source file" in error for error in result.errors))
            self.assertTrue(any("source path" in error for error in result.errors))

    def test_rejects_source_path_hidden_in_created_at(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kit = self._kit(Path(directory))
            manifest_path = kit / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["createdAt"] = r"2026-10-03T12:00:00+08:00 C:\Clinic\his"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = validate(kit)

            self.assertTrue(any("createdAt" in error and "absolute path" in error
                                for error in result.errors))

    def test_rejects_nested_unknown_fields_and_directory_junctions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kit = self._kit(root)
            manifest_path = kit / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["scenarios"][0]["source_path"] = r"\\live-his\data"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = validate(kit)
            self.assertTrue(any("source_path" in error for error in result.errors))

            target = root / "target"
            target.mkdir()
            linked = kit / "linked"
            junction = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(target)],
                                      capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if junction.returncode:
                self.skipTest("This Windows account cannot create a test junction")
            try:
                result = validate(kit)
                self.assertTrue(any("links or reparse" in error for error in result.errors))
            finally:
                linked.rmdir()

    def test_observation_text_and_roles_allow_slashes_but_reject_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kit = self._kit(Path(directory))
            manifest_path = kit / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["scenarios"][0].update(
                status="PASS", observedResult="CP950/Big5 decoded; 10/10 items\nN/A not needed",
                evidence="sha256:" + "A" * 64, observedAt="2026-10-03T12:00:00+08:00",
                ownerRole="Clinic IT / Admin", reviewerRole="HIS owner / reviewer")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = validate(kit)
            self.assertIn("H01", result.completed_scenarios)

            manifest["scenarios"][1].update(
                status="PASS", observedResult=r"Read C:\Clinic\source",
                evidence="sha256:" + "B" * 64, observedAt="2026-10-03T12:00:00+08:00",
                ownerRole="Clinic IT", reviewerRole="HIS owner")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = validate(kit)
            self.assertTrue(any("absolute path" in error for error in result.errors))
            self.assertNotIn("H02", result.completed_scenarios)

    def test_tampered_scenario_is_not_reported_as_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kit = self._kit(Path(directory))
            manifest_path = kit / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["scenarios"][0].update(
                name="tampered", status="PASS", observedResult="result",
                evidence="sha256:" + "A" * 64, observedAt="2026-10-03T12:00:00+08:00",
                ownerRole="owner", reviewerRole="reviewer")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = validate(kit)
            self.assertTrue(any("repository-controlled" in error for error in result.errors))
            self.assertNotIn("H01", result.completed_scenarios)

    def test_bom_is_accepted_and_missing_completion_fields_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kit = self._kit(Path(directory))
            manifest_path = kit / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["scenarios"][0].update(status="PASS", observedResult="result")
            manifest_path.write_text("\ufeff" + json.dumps(manifest), encoding="utf-8")

            result = validate(kit)

            self.assertTrue(any("needs result, evidence" in error for error in result.errors))
            self.assertNotIn("H01", result.completed_scenarios)

    def test_cli_reports_open_kit_and_require_complete_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "kit"
            with patch.object(sys, "argv", ["prepare_his_contract_intake", "--output", str(output)]), \
                    redirect_stdout(io.StringIO()):
                prepare_main()
            stdout = io.StringIO()
            with patch.object(sys, "argv", ["validate_his_contract_intake", "--kit", str(output)]), \
                    redirect_stdout(stdout):
                validate_main()
            self.assertIn('"status": "OPEN"', stdout.getvalue())
            with patch.object(sys, "argv", ["validate_his_contract_intake", "--kit", str(output),
                                               "--require-complete"]), redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(SystemExit, "1"):
                    validate_main()


if __name__ == "__main__":
    unittest.main()
