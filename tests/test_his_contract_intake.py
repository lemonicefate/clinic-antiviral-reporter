from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.prepare_his_contract_intake import SCENARIOS, prepare


class HisContractIntakeTest(unittest.TestCase):
    def test_creates_private_manifest_without_source_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            output = root / "private" / "his-contract-v1"
            output.parent.mkdir()

            result = prepare(output, repository=repository,
                             created_at=datetime(2026, 10, 3, tzinfo=timezone.utc))

            self.assertEqual(result.resolve(), output.resolve())
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["syntheticOnly"])
            self.assertFalse(manifest["productionHISAccessEnabled"])
            self.assertFalse(manifest["sourceArtifactsCopied"])
            self.assertEqual(manifest["status"], "OPEN")
            self.assertEqual([scenario["id"] for scenario in manifest["scenarios"]],
                             [scenario["id"] for scenario in SCENARIOS])
            self.assertTrue(all(scenario["status"] == "OPEN" and
                                scenario["observedResult"] is None and
                                scenario["evidence"] is None
                                for scenario in manifest["scenarios"]))
            self.assertFalse(list(output.rglob("*.DBF")))
            self.assertIn("never reads", (output / "README.txt").read_text(encoding="utf-8"))

    def test_refuses_relative_repository_and_existing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            with self.assertRaisesRegex(ValueError, "absolute"):
                prepare(Path("relative-output"), repository=repository)
            with self.assertRaisesRegex(ValueError, "outside the repository"):
                prepare(repository / "evidence", repository=repository)
            output = root / "evidence"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                prepare(output, repository=repository)
            self.assertEqual(list(root.glob(".his-contract-pending-*")), [])

    def test_rejects_a_linked_output_parent_and_cleans_staging_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            target = root / "target"
            target.mkdir()
            linked = root / "linked"
            junction = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(target)],
                                      capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if junction.returncode:
                self.skipTest("This Windows account cannot create a test junction")
            try:
                with self.assertRaisesRegex(ValueError, "links or reparse"):
                    prepare(linked / "kit", repository=repository)
            finally:
                linked.rmdir()
            output = root / "private" / "kit"
            output.parent.mkdir()
            with patch("scripts.prepare_his_contract_intake._write_text",
                       side_effect=OSError("synthetic write failure")):
                with self.assertRaisesRegex(OSError, "synthetic write failure"):
                    prepare(output, repository=repository)
            self.assertEqual(list(root.glob(".his-contract-pending-*")), [])


if __name__ == "__main__":
    unittest.main()
