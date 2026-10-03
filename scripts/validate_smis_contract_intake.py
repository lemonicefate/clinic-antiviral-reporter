"""Validate a private SMIS contract evidence kit without changing it."""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from scripts.prepare_smis_contract_intake import SCENARIOS, _sha256


_DIGEST = re.compile(r"^[0-9A-Fa-f]{64}$")
_STATUSES = {"OPEN", "PASS", "FAIL", "NOT_APPLICABLE"}


def _reject_reparse(path: Path) -> None:
    for item in (path, *path.parents):
        try:
            metadata = os.lstat(item)
        except FileNotFoundError:
            continue
        attributes = getattr(metadata, "st_file_attributes", 0)
        if stat.S_ISLNK(metadata.st_mode) or attributes & 0x400:
            raise ValueError(f"SMIS intake paths cannot contain links or reparse points: {item}")


def _kit_path(path: Path, repository: Path) -> Path:
    if not path.is_absolute():
        raise ValueError(f"Use an absolute kit path: {path}")
    _reject_reparse(path)
    kit = path.resolve(strict=True)
    if not kit.is_dir():
        raise ValueError(f"Expected a kit directory: {path}")
    repository_root = repository.resolve(strict=True)
    if kit == repository_root or repository_root in kit.parents:
        raise ValueError("SMIS evidence must be outside the repository")
    return kit


def _load_manifest(kit: Path) -> dict[str, Any]:
    manifest = kit / "manifest.json"
    _reject_reparse(manifest)
    if not manifest.is_file():
        raise ValueError("The kit is missing manifest.json")
    try:
        value = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read manifest.json: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("manifest.json must contain an object")
    return value


def _relative_file(kit: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise ValueError(f"{field} must be a non-empty single-line string")
    candidate = Path(value)
    if candidate.is_absolute() or candidate.anchor or any(part == ".." for part in candidate.parts):
        raise ValueError(f"{field} must not escape the kit")
    _reject_reparse(kit / candidate)
    resolved = (kit / candidate).resolve(strict=False)
    if resolved != kit and kit not in resolved.parents:
        raise ValueError(f"{field} must stay inside the kit")
    return resolved


@dataclass(frozen=True)
class IntakeValidation:
    kit: Path
    errors: tuple[str, ...]
    open_scenarios: tuple[str, ...]
    completed_scenarios: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.errors and not self.open_scenarios


def validate(kit_path: Path, *, repository: Path | None = None, require_complete: bool = False) -> IntakeValidation:
    repository_root = (repository or Path(__file__).resolve().parents[1]).resolve(strict=True)
    errors: list[str] = []
    open_scenarios: list[str] = []
    completed_scenarios: list[str] = []
    try:
        kit = _kit_path(kit_path, repository_root)
        manifest = _load_manifest(kit)
    except (OSError, ValueError) as error:
        return IntakeValidation(kit_path, (str(error),), (), ())

    if manifest.get("kitVersion") != 1:
        errors.append("kitVersion must be 1")
    if manifest.get("status") != "OPEN":
        errors.append("status must remain OPEN; this validator never changes the product gate")
    if manifest.get("syntheticOnly") is not True:
        errors.append("syntheticOnly must remain true")
    if manifest.get("productionExportEnabled") is not False:
        errors.append("productionExportEnabled must remain false")

    template = manifest.get("template")
    if not isinstance(template, dict):
        errors.append("template must be an object")
    else:
        try:
            template_path = _relative_file(kit, template.get("file"), "template.file")
            if not template_path.is_file() or template_path.stat().st_size == 0:
                errors.append("template.file must name a non-empty file in the kit")
            expected = template.get("sha256")
            if not isinstance(expected, str) or not _DIGEST.fullmatch(expected):
                errors.append("template.sha256 must be a 64-character hexadecimal digest")
            elif template_path.is_file() and _sha256(template_path) != expected.upper():
                errors.append("template.sha256 does not match the preserved template bytes")
        except (OSError, ValueError, AssertionError) as error:
            errors.append(str(error))

    scenarios = manifest.get("scenarios")
    expected_scenarios = {scenario["id"]: scenario for scenario in SCENARIOS}
    if not isinstance(scenarios, list):
        errors.append("scenarios must be an array")
        scenarios = []
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        prefix = f"scenarios[{index}]"
        scenario_error_count = len(errors)
        if not isinstance(scenario, dict):
            errors.append(f"{prefix} must be an object")
            continue
        scenario_id = scenario.get("id")
        if not isinstance(scenario_id, str) or scenario_id not in expected_scenarios:
            errors.append(f"{prefix}.id is not one of S01–S12")
            continue
        if scenario_id in seen:
            errors.append(f"duplicate scenario id: {scenario_id}")
            continue
        seen.add(scenario_id)
        for key in ("name", "instruction"):
            if scenario.get(key) != expected_scenarios[scenario_id][key]:
                errors.append(f"{prefix}.{key} must remain repository-controlled")
        status = scenario.get("status")
        observed = scenario.get("observedResult")
        evidence = scenario.get("evidence")
        if status not in _STATUSES:
            errors.append(f"{scenario_id}.status must be one of {sorted(_STATUSES)}")
            continue
        if observed is not None and (not isinstance(observed, str) or not observed.strip() or len(observed) > 2000):
            errors.append(f"{scenario_id}.observedResult must be a short non-empty result or null")
        if evidence is not None and (not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 500):
            errors.append(f"{scenario_id}.evidence must be a short reference or null")
        if status == "OPEN":
            open_scenarios.append(scenario_id)
        elif observed is None or evidence is None:
            errors.append(f"{scenario_id} needs observedResult and evidence when status is {status}")
        elif len(errors) == scenario_error_count:
            completed_scenarios.append(scenario_id)

    missing = sorted(set(expected_scenarios) - seen)
    errors.extend(f"missing scenario id: {scenario_id}" for scenario_id in missing)
    if require_complete and open_scenarios:
        errors.append("OPEN scenarios remain: " + ", ".join(open_scenarios))
    return IntakeValidation(kit, tuple(errors), tuple(open_scenarios), tuple(completed_scenarios))


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True, help="Absolute private intake-kit directory")
    parser.add_argument("--require-complete", action="store_true",
                        help="Return failure while any scenario remains OPEN")
    args = parser.parse_args()
    result = validate(args.kit, repository=repository, require_complete=args.require_complete)
    if result.errors:
        parser.exit(1, "\n".join(result.errors) + "\n")
    state = "COMPLETE" if result.complete else "OPEN"
    print(json.dumps({"kit": str(result.kit), "status": state,
                      "openScenarios": list(result.open_scenarios),
                      "completedScenarios": list(result.completed_scenarios)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
