import hashlib
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree


TEMPLATE = Path(__file__).parent / "fixtures" / "official" / "smis" / "template.xlsx"
EXPECTED_SHA256 = "a9e5a1390805d38dfdc1ee7ada22e38eec009cc9c1f00a84f7e562c49684d517"
EXPECTED_SHEETS = ["住院病患", "代碼表"]


class OfficialTemplateIntegrityTest(unittest.TestCase):
    def test_fixture_is_byte_for_byte_original(self) -> None:
        digest = hashlib.sha256(TEMPLATE.read_bytes()).hexdigest()
        self.assertEqual(EXPECTED_SHA256, digest)

    def test_expected_workbook_sheets_are_present(self) -> None:
        namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(TEMPLATE) as workbook:
            document = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
        sheets = [element.attrib["name"] for element in document.findall("main:sheets/main:sheet", namespace)]
        self.assertEqual(EXPECTED_SHEETS, sheets)

    def test_eraflu_smis_material_value_is_present(self) -> None:
        expected = "DDMTR2018090002:易剋冒膠囊(顆)".encode()
        with zipfile.ZipFile(TEMPLATE) as workbook:
            shared_strings = workbook.read("xl/sharedStrings.xml")
        self.assertIn(expected, shared_strings)


if __name__ == "__main__":
    unittest.main()
