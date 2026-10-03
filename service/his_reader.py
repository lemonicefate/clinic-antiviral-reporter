"""Clean-room, uncached read-only DBF adapter for the explicit synthetic dialect.

No production activation: live identity, encoding, date representation and locking
still need M0 evidence. All paths are supplied internally, never through the API.
"""

from dataclasses import dataclass, field
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import struct

from dbfread import DBF  # type: ignore[import-untyped]
from service.synthetic_paths import fixture_root

TABLES = {
    "PD011M1": ("NUM", "NAME", "BIRTH"),
    "RG011M1": ("NUM", "RELKEY", "TREAT"),
    "CH011M1": ("NUM", "RELKEY", "DOC", "SDATE"),
    "CH012M1": ("RELKEY", "SYS_2015", "MED1", "PRICE1", "USE_TAMT"),
    "H_INV": ("ITEMN", "LABNUM"),
}
NAMESPACE = "synthetic-dbf-v1:"


class ReadFailure(Exception):
    """Carries only an allowlisted diagnostic code, never paths or source bytes."""


@dataclass
class ReadBatch:
    observations: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    problems: list[tuple[str, dict[str, str], str]] = field(default_factory=list)


def identity(relkey: str, order: str) -> str:
    return NAMESPACE + hashlib.sha256(json.dumps([relkey, order]).encode()).hexdigest()


def signature(paths: list[Path]) -> list[tuple[int, int]]:
    return [(p.stat().st_size, p.stat().st_mtime_ns) for p in paths]


def read_tables(root: Path) -> dict[str, list[dict[str, bytes]]]:
    paths = [root / (name + ".DBF") for name in TABLES]
    try:
        if fixture_root(root.parent) != root:
            raise ReadFailure("synthetic_path_required")
        if (root / "SYNTHETIC_ONLY.txt").read_text(encoding="ascii") != "clinic-synthetic-dbf-v1":
            raise ReadFailure("synthetic_marker_required")
        before = signature(paths)
        tables = {}
        for (name, required), path in zip(TABLES.items(), paths):
            # Validate framing as dbfread otherwise tolerates short/unknown rows.
            with path.open("rb") as stream:
                raw = stream.read(16_000_001)
            if len(raw) < 33 or len(raw) > 16_000_000:
                raise ReadFailure("invalid_or_oversized_table")
            count, header_length, record_length = struct.unpack_from("<IHH", raw, 4)
            end = header_length + count * record_length
            if (raw[0] != 3 or raw[14] or raw[15] or record_length < 2 or
                    header_length < 33 or raw[header_length - 1:header_length] != b"\r" or
                    end > len(raw) or raw[end:] not in (b"", b"\x1a") or
                    any(raw[offset:offset+1] not in (b" ", b"*")
                        for offset in range(header_length, end, record_length))):
                raise ReadFailure("partial_or_unsupported_table")
            table = DBF(str(path), raw=True, encoding="cp950", ignorecase=False, load=False)
            if (len(set(table.field_names)) != len(table.field_names) or
                    not set(required) <= set(table.field_names) or
                    1 + sum(f.length for f in table.fields) != record_length or
                    any(f.type not in ("C", "N", "D") for f in table.fields if f.name in required)):
                raise ReadFailure("unsupported_schema")
            tables[name] = [{key: row[key] for key in required} for row in table]
        if signature(paths) != before:
            raise ReadFailure("source_changed_during_read")
        return tables
    except ReadFailure:
        raise
    except PermissionError:
        raise ReadFailure("sharing_or_access_denied") from None
    except FileNotFoundError:
        raise ReadFailure("source_unavailable") from None
    except (OSError, ValueError, struct.error, LookupError):
        raise ReadFailure("invalid_source_file") from None


def read_sources(root: Path) -> ReadBatch:
    tables = read_tables(root)
    result = ReadBatch()
    decoded: dict[str, list[dict[str, str]]] = {}
    for name, rows in tables.items():
        decoded[name] = []
        for raw_row in rows:
            try:
                decoded[name].append({key: value.decode("cp950", errors="strict") for key, value in raw_row.items()})
            except UnicodeDecodeError:
                # A corrupt parent cannot be silently omitted and mistaken for a
                # valid association. No partial batch is published.
                raise ReadFailure("decoding_error") from None

    def index(name, field):
        grouped: dict[str, list[dict[str, str]]] = {}
        for row in decoded[name]:
            grouped.setdefault(row[field].strip(), []).append(row)
        return grouped

    patients, registrations = index("PD011M1", "NUM"), index("RG011M1", "RELKEY")
    encounters, items = index("CH011M1", "RELKEY"), index("H_INV", "ITEMN")
    orders = decoded["CH012M1"]
    counts: dict[str, int] = {}
    for row in orders:
        key = identity(row["RELKEY"], row["SYS_2015"])
        counts[key] = counts.get(key, 0) + 1
    for position, row in enumerate(orders):
        relkey, order = row["RELKEY"].strip(), row["SYS_2015"].strip()
        key = identity(row["RELKEY"], row["SYS_2015"]) if relkey and order else NAMESPACE + "invalid-row-" + str(position)
        raw = {"raw.CH012M1." + k: v for k, v in row.items()}
        def problem(code):
            result.problems.append((key, raw, code))
        if not relkey or not order:
            problem("missing_key")
            continue
        if counts[key] != 1:
            problem("ambiguous_key")
            continue
        if row["MED1"].strip() != "ERA":
            continue
        joined = {}
        invalid = False
        for name, matches in (("CH011M1", encounters.get(relkey, [])),
                              ("RG011M1", registrations.get(relkey, [])), ("H_INV", items.get("ERA", []))):
            if len(matches) != 1:
                problem("orphan_join" if not matches else "ambiguous_join")
                invalid = True
                break
            joined[name] = matches[0]
        if invalid:
            continue
        chart = joined["CH011M1"]["NUM"].strip()
        parents = patients.get(chart, [])
        if len(parents) != 1 or joined["RG011M1"]["NUM"].strip() != chart:
            problem("patient_join_mismatch")
            continue
        joined["PD011M1"] = parents[0]
        joined["CH012M1"] = row
        raw = {"raw." + name + "." + field: value for name, record in joined.items() for field, value in record.items()}
        facts = {name + "." + field: value.strip() for name, record in joined.items() for field, value in record.items()}
        if not (chart.startswith("SYN-") and order.startswith("SYN-") and relkey.startswith("SYN")):
            problem("synthetic_identity_required")
            continue
        if facts["H_INV.LABNUM"] != "A059653100" or facts["CH012M1.PRICE1"][-10:] != facts["H_INV.LABNUM"]:
            problem("code_mismatch")
            continue
        try:
            for name in ("CH011M1.SDATE", "PD011M1.BIRTH"):
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", facts[name]):
                    raise ValueError()
                date.fromisoformat(facts[name])
            quantity = facts["CH012M1.USE_TAMT"]
            if not re.fullmatch(r"[0-9]+(?:\.0+)?", quantity) or int(quantity.split(".")[0]) < 1:
                raise ValueError()
            facts["CH012M1.USE_TAMT"] = str(int(quantity.split(".")[0]))
            if not facts["PD011M1.NAME"] or not facts["CH011M1.DOC"] or facts["RG011M1.TREAT"] not in ("Y", "C", "N"):
                raise ValueError()
        except ValueError:
            problem("invalid_required_field")
            continue
        result.observations.append((key, facts | raw))
    return result
