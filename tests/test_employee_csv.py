"""Employee CSV projects A/B/C/J only and preserves both string IDs."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bulk_mailer.core import (
    AddressBook, Contact, InputError, Settings, load_contacts, read_address_book,
    save_contacts, save_settings,
)
from test_core import record


HEADER = ["スタッフID", "派遣元スタッフコード", "氏名", "未使用D", "未使用E",
          "未使用F", "未使用G", "未使用H", "未使用I", "メールアドレス", "未使用K"]


def employee_row(name="山田 太郎", email="yamada@example.com", staff_id="000001", employee_id="000070"):
    return [staff_id, employee_id, name, "discard@example.com", "不要な住所", "不要な情報",
            "備考,引用あり\r\n複数行", "", "", email, "保存しない末尾列"]


def write_csv(path, rows=None, *, encoding="utf-8-sig", header=None):
    content = io.StringIO(newline="")
    writer = csv.writer(content)
    writer.writerow(HEADER if header is None else header)
    writer.writerows([employee_row()] if rows is None else rows)
    path.write_bytes(content.getvalue().encode(encoding))


class EmployeeCsvTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "社員情報.CSV"
        self.cache = self.path.parent / "contacts.json"

    def test_fixed_columns_preserve_leading_zero_ids_and_ignore_other_data(self):
        write_csv(self.path)
        book = read_address_book(self.path)
        self.assertEqual(book.contacts, [Contact("山田 太郎", "yamada@example.com", "000001", "000070")])
        self.assertEqual(book.resolve("山　田\t太郎"), "yamada@example.com")

    def test_csv_encodings_and_quoted_unused_fields(self):
        for encoding in ("utf-8-sig", "utf-8", "cp932", "utf-16"):
            with self.subTest(encoding=encoding):
                write_csv(self.path, encoding=encoding)
                self.assertEqual(read_address_book(self.path).contacts[0].staff_id, "000001")

    def test_json_contains_exactly_four_employee_fields_and_restores_ids(self):
        write_csv(self.path)
        book = read_address_book(self.path)
        save_contacts(book, self.cache, str(self.path))
        payload = json.loads(self.cache.read_text(encoding="utf-8"))
        self.assertEqual(set(payload["employees"][0]), {"staff_id", "employee_id", "name", "email"})
        self.assertNotIn("不要", self.cache.read_text(encoding="utf-8"))
        self.assertNotIn("discard@example.com", self.cache.read_text(encoding="utf-8"))
        self.path.unlink()
        self.assertEqual(load_contacts(self.cache), (book, str(self.path)))

    def test_reimport_replaces_all_four_fields_and_removes_previous_employee(self):
        write_csv(self.path)
        save_contacts(read_address_book(self.path), self.cache)
        write_csv(self.path, [employee_row("佐藤 花子", "new@example.com", "009999", "ABC0008")])
        save_contacts(read_address_book(self.path), self.cache)
        restored, _ = load_contacts(self.cache)
        self.assertEqual(restored.contacts, [Contact("佐藤 花子", "new@example.com", "009999", "ABC0008")])
        with self.assertRaises(InputError):
            restored.resolve("山田太郎")

    def test_legacy_v1_json_remains_readable_and_can_be_saved_as_v2(self):
        self.cache.write_text(json.dumps({"version": 1, "source_excel": "old.xlsx",
                                         "contacts": [{"name": "山田 太郎", "email": "old@example.com"}]}), encoding="utf-8")
        book, source = load_contacts(self.cache)
        self.assertEqual(book.contacts[0], Contact("山田 太郎", "old@example.com"))
        self.assertEqual(source, "old.xlsx")
        save_contacts(book, self.cache, source)
        self.assertEqual(json.loads(self.cache.read_text())["version"], 2)
        self.assertEqual(load_contacts(self.cache)[0], book)

    def test_duplicate_names_remain_ambiguous_even_with_distinct_ids(self):
        write_csv(self.path, [employee_row(), employee_row("山田　太郎", "other@example.com", "000002", "000071")])
        save_contacts(read_address_book(self.path), self.cache)
        with self.assertRaisesRegex(InputError, "重複"):
            load_contacts(self.cache)[0].resolve("山田太郎")

    def test_invalid_header_short_row_name_or_email_is_rejected(self):
        invalid_header = HEADER.copy()
        invalid_header[1] = "間違った列"
        cases = ((invalid_header, [employee_row()]), (HEADER[:9], [employee_row()]),
                 (HEADER, [employee_row()[:9]]), (HEADER, [employee_row(name="")]),
                 (HEADER, [employee_row(email="invalid")]))
        for header, rows in cases:
            with self.subTest(header=header, rows=rows):
                write_csv(self.path, rows, header=header)
                with self.assertRaises(InputError):
                    read_address_book(self.path)

    def test_empty_selected_columns_skip_unused_only_rows_but_not_real_employees(self):
        unused = [""] * 11
        unused[4] = "保存しない不要データ"
        write_csv(self.path, [[], unused, employee_row(staff_id="", employee_id="")])
        self.assertEqual(read_address_book(self.path).contacts, [Contact("山田 太郎", "yamada@example.com")])

    def test_malformed_csv_and_oversized_or_excessive_rows_fail_as_a_whole(self):
        write_csv(self.path)
        self.path.write_bytes(self.path.read_bytes() + b'"unterminated')
        with self.assertRaises(InputError):
            read_address_book(self.path)
        write_csv(self.path, [employee_row(), employee_row("佐藤 花子")])
        with patch("bulk_mailer.core.MAX_ADDRESS_ROWS", 1), self.assertRaises(InputError):
            read_address_book(self.path)
        with patch("bulk_mailer.core.MAX_CONTACTS_JSON_BYTES", 64), self.assertRaises(InputError):
            read_address_book(self.path)

    def test_invalid_json_ids_are_rejected_without_replacing_existing_cache(self):
        write_csv(self.path)
        book = read_address_book(self.path)
        save_contacts(book, self.cache)
        previous = self.cache.read_bytes()
        for invalid in (12, None, "ID\x00bad"):
            with self.subTest(invalid=invalid):
                broken = AddressBook([Contact("山田 太郎", "yamada@example.com", invalid, "000070")])
                with self.assertRaises(InputError):
                    save_contacts(broken, self.cache)
                self.assertEqual(self.cache.read_bytes(), previous)


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt", "GUI requires a display")
class EmployeeCsvGuiTests(unittest.TestCase):
    def setUp(self):
        from bulk_mailer.gui import Application
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.csv = self.path / "社員 情報.CSV"
        write_csv(self.csv)
        save_settings(Settings(subject="共通件名"), self.path / "settings.json")
        self.app = Application(self.path, preview_mode=True)
        self.errors = []
        self.app.report_callback_exception = lambda *error: self.errors.append(error)
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        self.temp.cleanup()
        self.assertEqual(self.errors, [])

    def test_csv_drop_persists_four_fields_and_employee_screen_displays_them(self):
        from tkinterdnd2 import COPY
        data = self.app.tk.call("format", "%s", self.app.tk.call("list", str(self.csv)))
        self.assertEqual(self.app.on_file_drop(SimpleNamespace(data=data)), COPY)
        self.app.show_contacts()
        self.app.update()
        table = self.app.employee_window.employee_table
        self.assertEqual(table.columns, ("staff_id", "employee_id", "name", "email"))
        self.assertEqual(table.rows[0].values, ("000001", "000070", "山田 太郎", "yamada@example.com"))
        self.assertEqual(len(table.find_withtag("cell_text")), 4)
        self.assertEqual(load_contacts(self.app.contacts_path)[0].contacts, self.app.book.contacts)
        self.app.employee_window.destroy()
        self.app.save_config()
        self.app.source.insert("1.0", record(name="山田　太郎"))
        self.app.create_list()
        self.assertEqual(self.app.items[0].to, "yamada@example.com")

    def test_restart_without_csv_restores_both_ids_from_json(self):
        self.assertTrue(self.app.import_contacts(self.csv))
        self.app.destroy()
        self.csv.unlink()
        from bulk_mailer.gui import Application
        self.app = Application(self.path, preview_mode=True)
        self.app.report_callback_exception = lambda *error: self.errors.append(error)
        self.app.show_contacts()
        self.app.update()
        self.assertEqual(self.app.employee_window.employee_table.rows[0].values[:2], ("000001", "000070"))

    def test_invalid_csv_or_save_failure_keeps_previous_four_field_cache(self):
        self.app.import_contacts(self.csv)
        self.app.save_config()
        previous = self.app.contacts_path.read_bytes()
        original = self.app.book
        write_csv(self.csv, [employee_row(email="invalid")])
        with patch("bulk_mailer.gui.messagebox.showerror") as error:
            self.assertFalse(self.app.import_contacts(self.csv))
        error.assert_called_once()
        self.assertIs(self.app.book, original)
        self.assertEqual(self.app.contacts_path.read_bytes(), previous)
        write_csv(self.csv, [employee_row("佐藤 花子", "new@example.com", "99", "88")])
        with patch("bulk_mailer.gui.save_contacts", side_effect=OSError("disk full")), \
             patch("bulk_mailer.gui.messagebox.showerror"):
            self.assertFalse(self.app.import_contacts(self.csv))
        self.assertIs(self.app.book, original)
        self.assertEqual(self.app.contacts_path.read_bytes(), previous)

    def test_employee_list_marks_ambiguous_names_but_does_not_hide_ids(self):
        write_csv(self.csv, [employee_row(), employee_row("山田　太郎", "other@example.com", "000002", "000071")])
        self.app.import_contacts(self.csv)
        self.app.show_contacts()
        self.app.update()
        table = self.app.employee_window.employee_table
        self.assertEqual([row.values[0] for row in table.rows], ["000001", "000002"])
        self.assertTrue(all(row.problem for row in table.rows))
        self.assertEqual(table.rows[1].values[1], "000071")
