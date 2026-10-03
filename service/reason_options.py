"""Exact preserved workbook options, not a clinical eligibility rules engine."""

from functools import lru_cache
import hashlib
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

TEMPLATE = Path(__file__).resolve().parents[1] / "tests/fixtures/official/smis/template.xlsx"
TEMPLATE_SHA256 = "a9e5a1390805d38dfdc1ee7ada22e38eec009cc9c1f00a84f7e562c49684d517"


@lru_cache(maxsize=1)
def reason_options() -> tuple[str, ...]:
    if hashlib.sha256(TEMPLATE.read_bytes()).hexdigest() != TEMPLATE_SHA256:
        raise RuntimeError("Official template integrity check failed")
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(TEMPLATE) as book:
        shared = ElementTree.fromstring(book.read("xl/sharedStrings.xml"))
        strings = ["".join(node.itertext()) for node in shared.findall("m:si", ns)]
        sheet = ElementTree.fromstring(book.read("xl/worksheets/sheet2.xml"))
    values = []
    for cell in sheet.findall("m:sheetData/m:row/m:c", ns):
        reference = cell.attrib["r"]
        if reference.startswith("E") and reference != "E1" and cell.attrib.get("t") == "s":
            value = cell.find("m:v", ns)
            if value is not None and value.text:
                values.append(strings[int(value.text)])
    if len(values) != 37 or len(set(values)) != 37:
        raise RuntimeError("Unexpected official reason option range")
    return tuple(values)
