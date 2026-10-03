import hashlib
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.prepare_smis_contract_intake import SCENARIOS, prepare


class SmisContractIntakeTest(unittest.TestCase):
    def test_creates_private_kit_with_open_synthetic_manifest_and_exact_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            source = repository / "template.xlsx"
            source.write_bytes(b"synthetic official template bytes")
            output = root / "private-evidence" / "smis-contract-v1"
            output.parent.mkdir()

            result = prepare(output, template=source, repository=repository,
                             created_at=datetime(2026, 10, 3, tzinfo=timezone.utc))

            # Windows may spell the same temporary directory with its long
            # name or an 8.3 short name.  Compare canonical paths so the
            # assertion checks the returned location rather than spelling.
            self.assertEqual(result.resolve(), output.resolve())
            self.assertEqual((output / "template.xlsx").read_bytes(), source.read_bytes())
            digest = hashlib.sha256(source.read_bytes()).hexdigest().upper()
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["syntheticOnly"])
            self.assertFalse(manifest["productionExportEnabled"])
            self.assertEqual(manifest["status"], "OPEN")
            self.assertEqual(manifest["template"]["sha256"], digest)
            self.assertEqual([scenario["id"] for scenario in manifest["scenarios"]],
                             [scenario["id"] for scenario in SCENARIOS])
            self.assertTrue(all(scenario["status"] == "OPEN" and scenario["observedResult"] is None
                                for scenario in manifest["scenarios"]))
            self.assertTrue((output / "evidence").is_dir())
            self.assertIn("synthetic-only", (output / "README.txt").read_text(encoding="utf-8"))

    def test_refuses_repository_output_and_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            source = repository / "template.xlsx"
            source.write_bytes(b"synthetic")

            with self.assertRaisesRegex(ValueError, "outside the repository"):
                prepare(repository / "evidence", template=source, repository=repository)

            output = root / "evidence"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                prepare(output, template=source, repository=repository)

    def test_refuses_empty_template_and_leaves_no_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            source = repository / "template.xlsx"
            source.write_bytes(b"")
            output = root / "evidence"

            with self.assertRaisesRegex(ValueError, "non-empty template"):
                prepare(output, template=source, repository=repository)
            self.assertFalse(output.exists())

    def test_refuses_relative_paths_and_cleans_staging_after_copy_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            source = repository / "template.xlsx"
            source.write_bytes(b"synthetic")
            output = root / "evidence"

            with self.assertRaisesRegex(ValueError, "absolute"):
                prepare(Path("relative-output"), template=source, repository=repository)
            with self.assertRaisesRegex(ValueError, "absolute"):
                prepare(output, template=Path("relative-template.xlsx"), repository=repository)
            with patch("scripts.prepare_smis_contract_intake.shutil.copyfile",
                       side_effect=OSError("synthetic copy failure")):
                with self.assertRaisesRegex(OSError, "synthetic copy failure"):
                    prepare(output, template=source, repository=repository)
            self.assertEqual(list(root.glob(".smis-contract-pending-*")), [])

    def test_refuses_linked_template_when_windows_allows_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            target = root / "target"
            target.mkdir()
            source = target / "template.xlsx"
            source.write_bytes(b"synthetic")
            linked_directory = repository / "linked-template"
            try:
                os.symlink(source, repository / "linked-template.xlsx")
                linked = repository / "linked-template.xlsx"
            except OSError:
                result = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked_directory), str(target)],
                                        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode:
                    self.skipTest("This Windows account cannot create a test link or junction")
                linked = linked_directory / "template.xlsx"
            try:
                with self.assertRaisesRegex(ValueError, "links or reparse"):
                    prepare(root / "evidence", template=linked, repository=repository)
            finally:
                if linked_directory.exists():
                    linked_directory.rmdir()


if __name__ == "__main__":
    unittest.main()
