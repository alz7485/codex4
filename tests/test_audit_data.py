"""Adversarial data-import regression tests; never accesses Outlook."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook

from bulk_mailer.core import (
    AddressBook, Contact, FIELDS, InputError, Settings, load_settings,
    parse_contracts, prepare_mails, read_address_book, read_text_file,
    render_body, validate_address, validate_body,
)
from bulk_mailer.outlook import execute_batch


def record(number="K-001", name="山田 太郎"):
    return "\n\n".join([
        number, "2026/11/01 - 2027/03/31", "東京事業所", "開発部", "システム開発",
        "第一チーム", name, "サンプル派遣株式会社", "承認済み\n不要行1", "不要行2",
    ])


def make_workbook(path, rows):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    workbook.save(path)
    workbook.close()


def change_sheet_xml(path, transform):
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    sheet = "xl/worksheets/sheet1.xml"
    entries[sheet] = transform(entries[sheet])
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


class AdversarialDataTests(unittest.TestCase):
    def test_preparation_keeps_nfkc_and_whitespace_name_collisions_ambiguous(self):
        book = AddressBook([Contact("ﾔﾏﾀﾞ 太郎", "a@example.com"),
                            Contact("ヤマダ\u3000太郎", "b@example.com")])
        mail = prepare_mails(parse_contracts(record(name="ヤマダ太郎")),
                             Settings(subject="共通件名"), book)[0]
        self.assertEqual(mail.to, "")
        self.assertIn("重複", mail.issue)

    def test_preparation_rebuilds_name_index_after_address_book_mutations(self):
        contracts = parse_contracts(record())
        settings = Settings(subject="共通件名")
        book = AddressBook([Contact("山田 太郎", "first@example.com")])
        self.assertEqual(prepare_mails(contracts, settings, book)[0].to, "first@example.com")
        book.contacts[:] = [Contact("山田　太郎", "second@example.com")]
        self.assertEqual(prepare_mails(contracts, settings, book)[0].to, "second@example.com")
        book.contacts.append(Contact("山田太郎", "third@example.com"))
        ambiguous = prepare_mails(contracts, settings, book)[0]
        self.assertEqual(ambiguous.to, "")
        self.assertIn("重複", ambiguous.issue)
        book.contacts.clear()
        missing = prepare_mails(contracts, settings, book)[0]
        self.assertEqual(missing.to, "")
        self.assertIn("未登録", missing.issue)

    def test_edited_body_validation_handles_type_blank_and_controls(self):
        for invalid in (None, 123, [], "", " \r\n\t", "本文\x00", "本文\ud800", "本文\u202e"):
            with self.subTest(body=repr(invalid)), self.assertRaises(InputError):
                validate_body(invalid)
        validate_body("正常な本文\r\n二行目\t補足")

    def test_manual_mail_edits_cannot_reach_outlook_with_unsafe_data(self):
        for changes in ({"to": "a@example.com\x00evil"},
                        {"cc": ("a@example.com\u202eevil",)},
                        {"subject": "題名\x00"}, {"subject": "題名\r\n別行"},
                        {"body": "本文\x00"}, {"body": "本文\ud800"}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                item = prepare_mails(parse_contracts(record()), Settings(subject="共通件名"),
                                     AddressBook([Contact("山田 太郎", "a@example.com")]))[0]
                item.reviewed = True
                for attribute, value in changes.items():
                    setattr(item, attribute, value)
                factory = MagicMock()
                with self.assertRaises(InputError):
                    execute_batch([item], "send", Path(directory) / "run.jsonl",
                                  lambda *_: None, factory=factory)
                factory.assert_not_called()
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_text_size_limits_reject_instead_of_truncating(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.txt"
            path.write_bytes(b"123456")
            with patch("bulk_mailer.core.MAX_TEXT_BYTES", 5), self.assertRaises(InputError):
                read_text_file(path)
        with patch("bulk_mailer.core.MAX_TEXT_CHARACTERS", 5), self.assertRaises(InputError):
            parse_contracts(record())

    def test_excel_size_and_row_limits_reject_instead_of_truncating(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.xlsx"
            make_workbook(path, [["氏名", "メールアドレス"], ["山田", "a@example.com"],
                                 ["佐藤", "b@example.com"]])
            with patch("bulk_mailer.core.MAX_EXCEL_XML_BYTES", 10), self.assertRaises(InputError):
                read_address_book(path)
            with patch("bulk_mailer.core.MAX_ADDRESS_ROWS", 1), self.assertRaises(InputError):
                read_address_book(path)

    def test_sparse_excel_missing_email_reports_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sparse.xlsx"
            make_workbook(path, [["氏名", "メールアドレス", "備考"], ["山田"]])
            with self.assertRaisesRegex(InputError, "2行目"):
                read_address_book(path)

    def test_sparse_billionth_excel_row_is_rejected_before_expanding_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sparse.xlsx"
            make_workbook(path, [["氏名", "メールアドレス"], ["山田", "a@example.com"]])
            change_sheet_xml(path, lambda xml: xml.replace(b'r="2"', b'r="1000000000"')
                             .replace(b'r="A2"', b'r="A1000000000"')
                             .replace(b'r="B2"', b'r="B1000000000"'))
            with self.assertRaisesRegex(InputError, "行数"):
                read_address_book(path)

    def test_nul_surrogate_and_bidi_in_contract_values_are_rejected(self):
        for control in ("\x00", "\ud800", "\u202e"):
            with self.subTest(control=repr(control)), self.assertRaises(InputError):
                parse_contracts(record(number="K" + control + "-001"))

    def test_subject_and_template_controls_are_rejected(self):
        for settings in (Settings(subject="題名\x00"), Settings(template="本文\ud800"),
                         Settings(subject="題名\u202e"), Settings(subject=None)):
            with self.subTest(settings=settings), self.assertRaises(InputError):
                settings.validate()

    def test_invalid_utf16_is_a_user_input_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.txt"
            for payload in (b"\xff\xfeA", b"\xfe\xffA", b"\xff\xfe\x00\xd8"):
                with self.subTest(payload=payload):
                    path.write_bytes(payload)
                    with self.assertRaises(InputError):
                        read_text_file(path)

    def test_corrupt_lazy_sheet_xml_is_a_user_input_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.xlsx"
            make_workbook(path, [["氏名", "メールアドレス"], ["山田 太郎", "a@example.com"]])
            change_sheet_xml(path, lambda xml: xml.replace(b"</sheetData>", b"<row>"))
            with self.assertRaises(InputError):
                read_address_book(path)

    def test_incorrect_excel_dimension_cannot_hide_duplicate_recipient(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dimensions.xlsx"
            make_workbook(path, [["氏名", "メールアドレス"],
                                 ["山田 太郎", "first@example.com"],
                                 ["山田 太郎", "other@example.com"]])
            change_sheet_xml(path, lambda xml: xml.replace(b'ref="A1:B3"', b'ref="A1:B2"'))
            contacts = read_address_book(path)
            self.assertEqual(len(contacts.contacts), 2)
            with self.assertRaisesRegex(InputError, "重複"):
                contacts.resolve("山田 太郎")

    def test_address_rejects_invisible_control_and_bidi_characters(self):
        for address in ("a\x00@example.com", "a@example.com\x00evil",
                        "a\x01@example.com", "a@example.com\x7f", "a@example.com\u202eevil"):
            with self.subTest(address=address), self.assertRaises(InputError):
                validate_address(address)

    def test_each_missing_required_data_block_is_rejected(self):
        source = record()
        for block in source.split("\n\n"):
            with self.subTest(block=block), self.assertRaises(InputError):
                parse_contracts(source.replace(block, "", 1))

    def test_extra_nonblank_lines_are_rejected(self):
        source = record()
        for line in range(len(source.splitlines())):
            lines = source.splitlines()
            lines.insert(line, "余分な行")
            with self.subTest(line=line), self.assertRaises(InputError):
                parse_contracts("\n".join(lines))

    def test_valid_utf16_big_endian_and_cp932_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "valid.txt"
            source = record()
            for payload in (b"\xfe\xff" + source.encode("utf-16-be"), source.encode("cp932")):
                path.write_bytes(payload)
                self.assertEqual(parse_contracts(read_text_file(path))[0].values["氏名"], "山田 太郎")

    def test_whitespace_normalized_duplicate_names_are_not_guessed(self):
        book = AddressBook([Contact("山田 太郎", "a@example.com"),
                            Contact("山田\u3000太郎", "b@example.com")])
        mail = prepare_mails(parse_contracts(record()), Settings(subject="共通件名"), book)[0]
        self.assertIn("重複", mail.issue)
        self.assertEqual(mail.to, "")

    def test_broken_excel_container_is_a_user_input_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.xlsx"
            for payload in (b"", b"this is not excel", b"PK\x03\x04"):
                path.write_bytes(payload)
                with self.subTest(payload=payload), self.assertRaises(InputError):
                    read_address_book(path)

    def test_missing_and_formula_addresses_are_not_silently_dropped(self):
        for row in (["山田 太郎", None], ["山田 太郎", '=CONCAT("a","@example.com")'],
                    [None, "a@example.com"], ["=A2", "a@example.com"]):
            with self.subTest(row=row), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "input.xlsx"
                make_workbook(path, [["氏名", "メールアドレス"], row])
                with self.assertRaisesRegex(InputError, "2行目"):
                    read_address_book(path)

    def test_corrupt_setting_types_and_encoding_are_user_input_errors(self):
        payloads = [b'null', b'[]', b'{"cc":null}', b'{"mode":true}', b'{"template":[]}',
                    b'{"address_book_path":12}', b'\xff\xfe', b'{"subject":"x",']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            for payload in payloads:
                with self.subTest(payload=payload):
                    path.write_bytes(payload)
                    with self.assertRaises(InputError):
                        load_settings(path)

    def test_nested_and_recursive_format_templates_are_rejected(self):
        values = dict.fromkeys(FIELDS, "確認")
        for template in ("{}", "{氏名[0]}", "{氏名.__class__}", "{氏名:{管理番号}}",
                         "{氏名!s}", "{氏名:1000000000}", "{", "}"):
            with self.subTest(template=template), self.assertRaises(InputError):
                render_body(template, values)


if __name__ == "__main__":
    unittest.main()
