"""Validate a private HIS read-contract evidence kit without changing it."""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from scripts.prepare_his_contract_intake import SCENARIOS


_STATUSES = {"OPEN", "PASS", "FAIL", "NOT_APPLICABLE"}
_SOURCE_SUFFIXES = {".dbf", ".fpt", ".cdx"}
_MANIFEST_KEYS = {"kitVersion", "syntheticOnly", "productionHISAccessEnabled",
                  "sourceArtifactsCopied", "status", "createdAt", "sourcePolicy", "scenarios"}
_POLICY_KEYS = {"readOnlyIdentityRequired", "rawSourceFilesAllowed", "sourcePathStored"}
_SCENARIO_KEYS = {"id", "name", "instruction", "status", "observedResult", "evidence",
                  "observedAt", "ownerRole", "reviewerRole"}
_SOURCE_KEYS = {"sourcepath", "sourcedirectory", "hissourcepath", "smbpath"}
_SECRET_KEYS = {"credential", "credentials", "password", "token", "privatekey", "secret"}
_ABSOLUTE_PATH = re.compile(r"(?:\\\\|(?<![A-Za-z0-9])[A-Za-z]:[\\/])")


def _reject_reparse(path: Path) -> None:
    for item in (path, *path.parents):
        try:
            metadata = os.lstat(item)
        except FileNotFoundError:
            continue
        attributes = getattr(metadata, "st_file_attributes", 0)
        if stat.S_ISLNK(metadata.st_mode) or attributes & 0x400:
            raise ValueError(f"HIS intake paths cannot contain links or reparse points: {item}")


def _kit_path(path: Path, repository: Path) -> Path:
    if not path.is_absolute():
        raise ValueError(f"Use an absolute kit path: {path}")
    _reject_reparse(path)
    kit = path.resolve(strict=True)
    if not kit.is_dir():
        raise ValueError(f"Expected a kit directory: {path}")
    repository_root = repository.resolve(strict=True)
    if kit == repository_root or repository_root in kit.parents:
        raise ValueError("HIS evidence must be outside the repository")
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


def _opaque_reference(value: Any, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be a short non-empty opaque reference")
    if any(character in value for character in ("/", "\\", "\r", "\n")) or ".." in value:
        raise ValueError(f"{field} must not contain a path")
    return value.strip()


def _reject_source_files(kit: Path) -> list[str]:
    errors: list[str] = []
    for path in kit.rglob("*"):
        _reject_reparse(path)
        if not path.is_file():
            continue
        if path.suffix.casefold() in _SOURCE_SUFFIXES:
            errors.append(f"raw HIS source file is not allowed in the kit: {path.name}")
    return errors


def _normalized_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _key_errors(value: dict[str, Any], allowed: set[str], prefix: str) -> list[str]:
    errors: list[str] = []
    for key in value:
        if key in allowed:
            continue
        normalized = _normalized_key(key)
        if normalized in _SOURCE_KEYS:
            errors.append(f"{prefix}.{key} must not record an HIS source path")
        elif normalized in _SECRET_KEYS:
            errors.append(f"{prefix}.{key} must not record credentials or secrets")
        else:
            errors.append(f"{prefix}.{key} is not a repository-controlled field")
    return errors


def _text(value: Any, field: str, maximum: int, *, allow_newlines: bool = True,
          reject_absolute_path: bool = True) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters")
    if not allow_newlines and any(character in value for character in ("\r", "\n")):
        raise ValueError(f"{field} must be a single-line string")
    if reject_absolute_path and _ABSOLUTE_PATH.search(value):
        raise ValueError(f"{field} must not contain an absolute path")
    return value.strip()


@dataclass(frozen=True)
class IntakeValidation:
    kit: Path
    errors: tuple[str, ...]
    open_scenarios: tuple[str, ...]
    completed_scenarios: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.errors and not self.open_scenarios


def validate(kit_path: Path, *, repository: Path | None = None,
             require_complete: bool = False) -> IntakeValidation:
    repository_root = (repository or Path(__file__).resolve().parents[1]).resolve(strict=True)
    errors: list[str] = []
    open_scenarios: list[str] = []
    completed_scenarios: list[str] = []
    try:
        kit = _kit_path(kit_path, repository_root)
        manifest = _load_manifest(kit)
        errors.extend(_reject_source_files(kit))
    except (OSError, ValueError) as error:
        return IntakeValidation(kit_path, (str(error),), (), ())

    if manifest.get("kitVersion") != 1:
        errors.append("kitVersion must be 1")
    if manifest.get("status") != "OPEN":
        errors.append("status must remain OPEN; this validator never changes the product gate")
    if manifest.get("syntheticOnly") is not True:
        errors.append("syntheticOnly must remain true")
    if manifest.get("productionHISAccessEnabled") is not False:
        errors.append("productionHISAccessEnabled must remain false")
    if manifest.get("sourceArtifactsCopied") is not False:
        errors.append("sourceArtifactsCopied must remain false")
    try:
        created_at = _text(manifest.get("createdAt"), "createdAt", 80,
                           allow_newlines=False)
        if created_at is None:
            errors.append("createdAt must be a non-empty timestamp")
    except ValueError as error:
        errors.append(str(error))
    source_policy = manifest.get("sourcePolicy")
    expected_policy = {"readOnlyIdentityRequired": True, "rawSourceFilesAllowed": False,
                       "sourcePathStored": False}
    if source_policy != expected_policy:
        errors.append("sourcePolicy must remain the repository-controlled read-only policy")
    errors.extend(_key_errors(manifest, _MANIFEST_KEYS, "manifest"))
    if isinstance(source_policy, dict):
        errors.extend(_key_errors(source_policy, _POLICY_KEYS, "sourcePolicy"))

    scenarios = manifest.get("scenarios")
    expected_scenarios = {scenario["id"]: scenario for scenario in SCENARIOS}
    if not isinstance(scenarios, list):
        errors.append("scenarios must be an array")
        scenarios = []
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        prefix = f"scenarios[{index}]"
        if not isinstance(scenario, dict):
            errors.append(f"{prefix} must be an object")
            continue
        scenario_id = scenario.get("id")
        if not isinstance(scenario_id, str) or scenario_id not in expected_scenarios:
            errors.append(f"{prefix}.id is not one of H01–H11")
            continue
        if scenario_id in seen:
            errors.append(f"duplicate scenario id: {scenario_id}")
            continue
        seen.add(scenario_id)
        scenario_error_count = len(errors)
        errors.extend(_key_errors(scenario, _SCENARIO_KEYS, prefix))
        for key in ("name", "instruction"):
            if scenario.get(key) != expected_scenarios[scenario_id][key]:
                errors.append(f"{prefix}.{key} must remain repository-controlled")
        status = scenario.get("status")
        if status not in _STATUSES:
            errors.append(f"{scenario_id}.status must be one of {sorted(_STATUSES)}")
            continue
        try:
            observed = _text(scenario.get("observedResult"), f"{scenario_id}.observedResult", 2000)
            evidence = _opaque_reference(scenario.get("evidence"), f"{scenario_id}.evidence", 500)
            observed_at = _text(scenario.get("observedAt"), f"{scenario_id}.observedAt", 80,
                                allow_newlines=False)
            owner = _text(scenario.get("ownerRole"), f"{scenario_id}.ownerRole", 160,
                          allow_newlines=False)
            reviewer = _text(scenario.get("reviewerRole"), f"{scenario_id}.reviewerRole", 160,
                             allow_newlines=False)
        except ValueError as error:
            errors.append(str(error))
            continue
        if status == "OPEN":
            open_scenarios.append(scenario_id)
        elif None in (observed, evidence, observed_at, owner, reviewer):
            errors.append(f"{scenario_id} needs result, evidence, timestamp, ownerRole, and reviewerRole")
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
