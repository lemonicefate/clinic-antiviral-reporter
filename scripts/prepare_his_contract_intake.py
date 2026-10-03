"""Prepare a private, synthetic-only HIS read-contract evidence kit."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Iterable


SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "id": "H01",
        "name": "stable key null/reuse/edit",
        "instruction": "Measure (RELKEY, SYS_2015) nullability, reuse, and behavior after source edits without inventing a key.",
    },
    {
        "id": "H02",
        "name": "TREAT transitions and order amendments",
        "instruction": "Observe Y, C, and N transitions plus order-level amendments while preserving every source version.",
    },
    {
        "id": "H03",
        "name": "date, quantity, and partial dispensing",
        "instruction": "Measure CH011M1.SDATE, integer CH012M1.USE_TAMT, and smaller actual dispensing values with audit reasons.",
    },
    {
        "id": "H04",
        "name": "CP950/Big5 decoding",
        "instruction": "Exercise the approved encoding and representative non-ASCII values without changing source bytes.",
    },
    {
        "id": "H05",
        "name": "partial writes and truncated source",
        "instruction": "Observe incomplete source records and confirm bounded retry or quarantine behavior.",
    },
    {
        "id": "H06",
        "name": "read locks and sharing violations",
        "instruction": "Measure read-only sharing violations, bounded backoff, and the final safe failure state.",
    },
    {
        "id": "H07",
        "name": "committed visibility versus scan delay",
        "instruction": "Measure fresh uncached visibility after a committed write separately from periodic scanner delay.",
    },
    {
        "id": "H08",
        "name": "deleted rows and orphan joins",
        "instruction": "Verify deleted rows are ignored and non-deleted orphan children are quarantined without source repair.",
    },
    {
        "id": "H09",
        "name": "mapping mismatch and ambiguity",
        "instruction": "Exercise clinic/NHI mismatch and ambiguous candidate rows; record quarantine rather than inferred selection.",
    },
    {
        "id": "H10",
        "name": "safe load and retry bounds",
        "instruction": "Measure scanner load, retry limits, and recovery without modifying HIS source files.",
    },
    {
        "id": "H11",
        "name": "source immutability and read-only handles",
        "instruction": "Verify the Windows identity and handles cannot create, replace, truncate, rename, or delete HIS files.",
    },
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
            raise ValueError(f"HIS intake paths cannot contain links or reparse points: {item}")


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
        raise ValueError("HIS evidence must be outside the repository")
    return destination


def _manifest(created_at: str) -> dict:
    return {
        "kitVersion": 1,
        "syntheticOnly": True,
        "productionHISAccessEnabled": False,
        "sourceArtifactsCopied": False,
        "status": "OPEN",
        "createdAt": created_at,
        "sourcePolicy": {
            "readOnlyIdentityRequired": True,
            "rawSourceFilesAllowed": False,
            "sourcePathStored": False,
        },
        "scenarios": [
            {
                **scenario,
                "status": "OPEN",
                "observedResult": None,
                "evidence": None,
                "observedAt": None,
                "ownerRole": None,
                "reviewerRole": None,
            }
            for scenario in SCENARIOS
        ],
    }


def _write_text(path: Path, lines: Iterable[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def prepare(
    output: Path,
    *,
    repository: Path | None = None,
    created_at: datetime | None = None,
) -> Path:
    """Create a private manifest kit without reading or copying an HIS source."""
    repository_root = (repository or Path(__file__).resolve().parents[1]).resolve(strict=True)
    if not repository_root.is_dir():
        raise ValueError(f"Expected a repository directory: {repository_root}")
    destination = _private_output(output, repository_root)
    timestamp = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()

    with tempfile.TemporaryDirectory(prefix=".his-contract-pending-", dir=destination.parent) as staging_name:
        staging = Path(staging_name)
        _write_text(staging / "README.txt", (
            "Clinic Antiviral Reporter — private HIS read-contract intake kit",
            "",
            "This directory contains only a synthetic evidence manifest and must remain outside Git.",
            "It never reads, copies, opens, or modifies the configured HIS source.",
            "Use a read-only Windows identity and read-only handles for any approved live measurement.",
            "Keep DBF/FPT/CDX files, source paths, patient data, credentials, logs, and screenshots outside this kit.",
            "Record only de-identified results and opaque private evidence references in manifest.json.",
            "Production HIS access and production Excel export remain disabled.",
        ))
        (staging / "evidence").mkdir()
        _write_text(staging / "evidence" / "README.txt", (
            "Store only a redacted evidence index here if the clinic policy permits it.",
            "Do not copy DBF, FPT, CDX, patient data, credentials, source paths, or raw logs into this kit.",
        ))
        (staging / "manifest.json").write_text(
            json.dumps(_manifest(timestamp), ensure_ascii=False, indent=2) + "\n",
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
    args = parser.parse_args()
    try:
        output = prepare(args.output, repository=repository)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    print(f"Prepared private HIS contract intake kit: {output}")


if __name__ == "__main__":
    main()
