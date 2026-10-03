"""Prepare a private, synthetic-only SMIS contract evidence kit."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Iterable


SCENARIOS: tuple[dict[str, str], ...] = (
    {"id": "S01", "name": "complete baseline", "instruction": "One synthetic outpatient declaration with one lot."},
    {"id": "S02", "name": "missing mandatory field", "instruction": "Remove one candidate mandatory field at a time."},
    {"id": "S03", "name": "valid multiple lots", "instruction": "Use total 10 with lot allocations 6 + 4."},
    {"id": "S04", "name": "invalid multiple-lot total", "instruction": "Use total 10 with lot allocations 6 + 3."},
    {"id": "S05", "name": "subsequent dose", "instruction": "Use a synthetic continuation record linked to a synthetic prior record."},
    {"id": "S06", "name": "exact duplicate", "instruction": "Upload S01 again without changing bytes or values."},
    {"id": "S07", "name": "correction", "instruction": "Correct one value in an accepted S01 record through the supported workflow."},
    {"id": "S08", "name": "partial batch result", "instruction": "Use 18 synthetic items: 16 intentionally valid and 2 intentionally invalid."},
    {"id": "S09", "name": "foreign and special identifiers", "instruction": "Exercise synthetic foreign markers, punctuation, Unicode, spaces, and blank/unknown values."},
    {"id": "S10", "name": "leading zeros and dates", "instruction": "Preserve a value such as 000123 and fixed synthetic date strings."},
    {"id": "S11", "name": "formula-like strings", "instruction": "Use harmless values beginning with =, +, -, and @ as text."},
    {"id": "S12", "name": "complete reconciliation", "instruction": "Reconcile every input, workbook row, platform result, and total."},
)


def _reject_reparse(path: Path) -> None:
    """Reject links and Windows reparse points anywhere in a path."""
    for item in (path, *path.parents):
        try:
            metadata = os.lstat(item)
        except FileNotFoundError:
            continue
        attributes = getattr(metadata, "st_file_attributes", 0)
        if stat.S_ISLNK(metadata.st_mode) or attributes & 0x400:
            raise ValueError(f"SMIS intake paths cannot contain links or reparse points: {item}")


def _source(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError(f"Use an absolute template path: {path}")
    _reject_reparse(path)
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise ValueError(f"Expected a non-empty template file: {path}")
    return resolved


def _private_output(path: Path, repository: Path) -> Path:
    if not path.is_absolute():
        raise ValueError(f"Use an absolute private output path: {path}")
    _reject_reparse(path)
    if path.exists():
        raise ValueError(f"Output already exists; choose a new private evidence directory: {path}")
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError(f"Output parent is not a directory: {parent}")
    destination = parent / path.name
    repository_root = repository.resolve(strict=True)
    resolved_destination = destination.resolve(strict=False)
    if resolved_destination == repository_root or repository_root in resolved_destination.parents:
        raise ValueError("SMIS evidence must be outside the repository")
    return destination


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _manifest(template_digest: str, created_at: str) -> dict:
    return {
        "kitVersion": 1,
        "syntheticOnly": True,
        "productionExportEnabled": False,
        "status": "OPEN",
        "createdAt": created_at,
        "template": {"file": "template.xlsx", "sha256": template_digest},
        "scenarios": [
            {**scenario, "status": "OPEN", "observedResult": None, "evidence": None}
            for scenario in SCENARIOS
        ],
    }


def _write_text(path: Path, lines: Iterable[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def prepare(
    output: Path,
    *,
    template: Path,
    repository: Path | None = None,
    created_at: datetime | None = None,
) -> Path:
    """Create an immutable private kit without writing under the repository."""
    repository_root = (repository or Path(__file__).resolve().parents[1]).resolve(strict=True)
    if not repository_root.is_dir():
        raise ValueError(f"Expected a repository directory: {repository_root}")
    source = _source(template)
    destination = _private_output(output, repository_root)
    template_digest = _sha256(source)
    timestamp = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()

    with tempfile.TemporaryDirectory(prefix=".smis-contract-pending-", dir=destination.parent) as staging_name:
        staging = Path(staging_name)
        shutil.copyfile(source, staging / "template.xlsx")
        _write_text(staging / "README.txt", (
            "Clinic Antiviral Reporter — private SMIS contract intake kit",
            "",
            "This directory is synthetic-only and must remain outside Git.",
            "The copied template is preserved byte-for-byte; do not edit it in place.",
            "Use manifest.json for S01–S12 and record only de-identified platform evidence.",
            "Production Excel generation is disabled and this kit does not submit to SMIS.",
            "Keep credentials, patient data, generated workbooks, logs, and raw result files private.",
            "",
            "Before upload, copy template.xlsx to a new scenario-specific artifact and record its hash.",
            "After upload, fill the scenario result and evidence reference in a private copy of manifest.json.",
        ))
        (staging / "evidence").mkdir()
        _write_text(staging / "evidence" / "README.txt", (
            "Store private, de-identified evidence records here.",
            "Do not commit this directory or place credentials and patient data in it.",
        ))
        (staging / "manifest.json").write_text(
            json.dumps(_manifest(template_digest, timestamp), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        staging.rename(destination)
    return destination


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="Absolute directory outside the repository for the private kit")
    parser.add_argument("--template", type=Path,
                        default=repository / "tests/fixtures/official/smis/template.xlsx")
    args = parser.parse_args()
    try:
        output = prepare(args.output, template=args.template, repository=repository)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    print(f"Prepared private SMIS contract intake kit: {output}")


if __name__ == "__main__":
    main()
