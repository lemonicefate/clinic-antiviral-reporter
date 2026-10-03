"""Generate deliberately synthetic DBF-family inputs outside Git and HIS shares."""

from datetime import date
from pathlib import Path
import argparse
import struct
from collections.abc import Mapping, Sequence
from service.synthetic_paths import fixture_root


def write_table(path: Path, fields: list[tuple[str, int]], rows: Sequence[Mapping[str, str | bytes]]) -> None:
    if fixture_root(path.parent.parent) != path.parent:
        raise ValueError("DBF fixture must stay in its dedicated synthetic directory")
    header = bytearray(32)
    header[:4] = bytes([3, 126, 10, 3])
    struct.pack_into("<IHH", header, 4, len(rows), 33 + 32 * len(fields), 1 + sum(size for _, size in fields))
    data = bytearray(header)
    for name, size in fields:
        descriptor = bytearray(32)
        descriptor[:len(name)] = name.encode("ascii")
        descriptor[11] = ord("C")
        descriptor[16] = size
        data.extend(descriptor)
    data.extend(b"\r")
    for row in rows:
        data.extend(b"*" if row.get("_deleted") == "true" else b" ")
        for name, size in fields:
            value = row.get(name, "")
            encoded = value if isinstance(value, bytes) else value.encode("cp950")
            if len(encoded) > size:
                raise ValueError("Synthetic field exceeds fixed width")
            data.extend(encoded.ljust(size, b" "))
    path.write_bytes(data + b"\x1a")


def prepare(state_dir: Path, reporting_date: date, scenario: str = "valid") -> Path:
    # This is a fixture author, not a scanner. Never accepts a HIS directory.
    root = fixture_root(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "SYNTHETIC_ONLY.txt").write_text("clinic-synthetic-dbf-v1", encoding="ascii")
    patient = [{"NUM": "SYN-DBF-P1", "NAME": "合成檔案病人", "BIRTH": "1990-01-01"}]
    registration = [{"NUM": "SYN-DBF-P1", "RELKEY": "SYN  ENCOUNTER", "TREAT": "Y"}]
    encounters = [{"NUM": "SYN-DBF-P1", "RELKEY": "SYN  ENCOUNTER", "DOC": "SYN-DR-A", "SDATE": reporting_date.isoformat()}]
    orders: list[dict[str, str | bytes]] = [{"RELKEY": "SYN  ENCOUNTER", "SYS_2015": "SYN-DBF-ORDER-1",
               "MED1": "ERA", "PRICE1": "SYN-A059653100", "USE_TAMT": "10"}]
    items = [{"ITEMN": "ERA", "LABNUM": "A059653100"}]
    if scenario == "orphan": encounters = []
    elif scenario == "mismatch": orders[0]["PRICE1"] = "SYN-0000000000"
    elif scenario == "ambiguous": orders.append(dict(orders[0]))
    elif scenario == "boundary_keys": orders.append(dict(orders[0]) | {"SYS_2015": " SYN-DBF-ORDER-1"})
    elif scenario == "missing_key": orders[0]["SYS_2015"] = ""
    elif scenario == "deleted": orders[0]["_deleted"] = "true"
    elif scenario == "cancelled": registration[0]["TREAT"] = "C"
    elif scenario == "unseen": registration[0]["TREAT"] = "N"
    elif scenario == "quantity": orders[0]["USE_TAMT"] = "5"
    elif scenario == "decode": orders[0]["MED1"] = b"\xff"
    elif scenario not in ("valid", "partial"): raise ValueError("Unknown synthetic scenario")
    write_table(root / "PD011M1.DBF", [("NUM", 20), ("NAME", 40), ("BIRTH", 10)], patient)
    write_table(root / "RG011M1.DBF", [("NUM", 20), ("RELKEY", 30), ("TREAT", 1)], registration)
    write_table(root / "CH011M1.DBF", [("NUM", 20), ("RELKEY", 30), ("DOC", 20), ("SDATE", 10)], encounters)
    write_table(root / "CH012M1.DBF", [("RELKEY", 30), ("SYS_2015", 30), ("MED1", 10), ("PRICE1", 20), ("USE_TAMT", 8)], orders)
    write_table(root / "H_INV.DBF", [("ITEMN", 10), ("LABNUM", 10)], items)
    if scenario == "partial":
        path = root / "CH012M1.DBF"
        path.write_bytes(path.read_bytes()[:-4])
    # Unused memo/index files prove that no auxiliary source writes occur.
    (root / "CH012M1.FPT").write_bytes(b"synthetic-unused-memo")
    (root / "CH012M1.CDX").write_bytes(b"synthetic-unused-index")
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--scenario", default="valid")
    args = parser.parse_args()
    prepare(args.state_dir, args.date, args.scenario)
