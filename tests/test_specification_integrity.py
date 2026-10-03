"""Guard the baseline and authoritative amendment specification files."""

from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]


class SpecificationIntegrityTest(unittest.TestCase):
    def test_baseline_and_authoritative_amendment_are_strict_utf8_and_present(self) -> None:
        specifications = {
            "tw-flu-antiviral-reporter_SPEC_v1.0.md": "MVP v1.0",
            "tw-flu-antiviral-reporter_SPEC_v1.1.md": "SPEC v1.1",
        }
        for filename, marker in specifications.items():
            path = REPOSITORY / filename
            self.assertTrue(path.is_file(), f"Missing specification: {filename}")
            content = path.read_bytes()
            self.assertTrue(content, f"Empty specification: {filename}")
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as error:
                self.fail(f"Specification is not strict UTF-8: {filename}: {error}")
            self.assertIn(marker, text, f"Version marker missing from {filename}")


if __name__ == "__main__":
    unittest.main()
