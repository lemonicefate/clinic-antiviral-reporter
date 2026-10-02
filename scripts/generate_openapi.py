"""Export the versioned API contract without opening any state/source directory."""

import json
from pathlib import Path

from service.app import create_app
from service.settings import Settings


def main() -> None:
    settings = Settings.from_environment({
        "CLINIC_REPORTER_STATE_DIR": r"C:\SyntheticReporter",
        "CLINIC_REPORTER_HIS_SOURCE_PATH": r"\\synthetic.invalid\source",
        "CLINIC_REPORTER_BACKUP_ROOT": r"\\synthetic.invalid\backup",
    })
    destination = Path(__file__).resolve().parents[1] / "service" / "openapi" / "v1.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(create_app(settings).openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
