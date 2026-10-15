"""Address-book persistence: replacement, restart, validation, and failure safety."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from bulk_mailer.core import (
    AddressBook, Contact, InputError, Settings, load_contacts, save_contacts, save_settings,
)
from bulk_mailer.gui import Application
from test_core import record


class ContactsJsonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "contacts.json"
        self.original = AddressBook([Contact("山田　太郎", "old@example.com"), Contact("佐藤 花子", "sato@example.com")])

    def test_round_trip_preserves_names_and_source_path(self):
        save_contacts(self.original, self.path, "C:/宛先.xlsx")
        book, source = load_contacts(self.path)
        self.assertEqual(book, self.original)
        self.assertEqual(source, "C:/宛先.xlsx")
        self.assertEqual(book.resolve("山田 太郎"), "old@example.com")

    def test_reimport_replaces_all_records_instead_of_merging(self):
        save_contacts(self.original, self.path)
        replacement = AddressBook([Contact("山田 太郎", "new@example.com")])
        save_contacts(replacement, self.path, "new.xlsx")
        book, source = load_contacts(self.path)
        self.assertEqual(book, replacement)
        self.assertEqual(source, "new.xlsx")
        with self.assertRaisesRegex(InputError, "未登録"):
            book.resolve("佐藤花子")

    def test_failed_disk_write_retains_previous_json(self):
        save_contacts(self.original, self.path)
        previous = self.path.read_bytes()
        with patch("bulk_mailer.core.os.fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save_contacts(AddressBook([Contact("変更", "new@example.com")]), self.path)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_invalid_replacement_does_not_overwrite_valid_json(self):
        save_contacts(self.original, self.path)
        previous = self.path.read_bytes()
        for name, email in (("", "a@example.com"), ("山田", "invalid"), ("山\x00田", "a@example.com")):
            with self.subTest(name=name), self.assertRaises(InputError):
                save_contacts(AddressBook([Contact(name, email)]), self.path)
            self.assertEqual(self.path.read_bytes(), previous)

    def test_invalid_schema_and_encoding_are_rejected(self):
        invalid = [b"{broken", b"\xff", b"[]", b'{}',
                   json.dumps({"version": True, "source_excel": "", "contacts": []}).encode(),
                   json.dumps({"version": 1, "source_excel": "", "contacts": [{"name": 12, "email": "a@example.com"}]}).encode()]
        for payload in invalid:
            self.path.write_bytes(payload)
            with self.subTest(payload=payload), self.assertRaises(InputError):
                load_contacts(self.path)

    def test_duplicate_names_remain_ambiguous_after_restart(self):
        book = AddressBook([Contact("山田 太郎", "a@example.com"), Contact("山田　太郎", "b@example.com")])
        save_contacts(book, self.path)
        loaded, _ = load_contacts(self.path)
        self.assertEqual(len(loaded.contacts), 2)
        with self.assertRaisesRegex(InputError, "重複"):
            loaded.resolve("山田太郎")

    def test_size_limit_prevents_saving_unreadable_cache(self):
        save_contacts(self.original, self.path)
        previous = self.path.read_bytes()
        with patch("bulk_mailer.core.MAX_CONTACTS_JSON_BYTES", 100):
            with self.assertRaises(InputError):
                save_contacts(self.original, self.path)
            with self.assertRaises(InputError):
                load_contacts(self.path)
        self.assertEqual(self.path.read_bytes(), previous)


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt", "GUI requires a display")
class ContactsJsonGuiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name)
        self.excel = self.path / "original.xlsx"
        self.write_excel(self.excel, [("山田 太郎", "old@example.com"), ("佐藤 花子", "sato@example.com")])
        save_settings(Settings(subject="共通件名", address_book_path=str(self.excel)), self.path / "settings.json")
        self.callback_errors = []
        self.app = self.open_app()

    def write_excel(self, path, contacts):
        book = Workbook()
        book.active.append(["氏名", "メールアドレス"])
        for row in contacts:
            book.active.append(row)
        book.save(path)
        book.close()

    def open_app(self):
        app = Application(self.path, preview_mode=True)
        app.report_callback_exception = lambda *error: self.callback_errors.append(error)
        app.source.insert("1.0", record())
        app.create_list()
        app.update()
        return app

    def import_excel(self, path):
        with patch("bulk_mailer.gui.filedialog.askopenfilename", return_value=str(path)):
            self.app.import_contacts()

    def tearDown(self):
        self.app.destroy()
        self.temporary.cleanup()
        self.assertEqual(self.callback_errors, [])

    def test_legacy_setting_migrates_to_json_and_survives_missing_excel(self):
        self.assertTrue((self.path / "contacts.json").is_file())
        self.app.destroy()
        self.excel.unlink()
        with patch("bulk_mailer.gui.read_address_book", side_effect=AssertionError("Excel must not be read")):
            self.app = self.open_app()
            self.app.subject_var.set("変更した件名")
            self.app.save_config()
        self.assertEqual(self.app.items[0].to, "old@example.com")
        self.assertFalse(self.app.has_unsaved_settings())

    def test_import_immediately_persists_full_replacement(self):
        self.app.review_selected()
        updated = self.path / "updated.xlsx"
        self.write_excel(updated, [("山田 太郎", "new@example.com")])
        self.import_excel(updated)
        stored, source = load_contacts(self.path / "contacts.json")
        self.assertEqual(stored.contacts, [Contact("山田 太郎", "new@example.com")])
        self.assertEqual(source, str(updated))
        self.assertTrue(self.app.contacts_dirty)
        self.assertEqual(self.app.items[0].to, "old@example.com")
        self.app.save_config()
        self.assertEqual(self.app.items[0].to, "new@example.com")
        self.assertFalse(self.app.items[0].reviewed)

    def test_restart_after_import_without_settings_save_uses_json(self):
        updated = self.path / "updated.xlsx"
        self.write_excel(updated, [("山田 太郎", "new@example.com")])
        self.import_excel(updated)
        self.app.destroy()
        updated.unlink()
        self.excel.unlink()
        self.app = self.open_app()
        self.assertEqual(self.app.items[0].to, "new@example.com")
        self.assertEqual(self.app.path_var.get(), str(updated))

    def test_broken_excel_keeps_json_and_reviewed_list(self):
        self.app.review_selected()
        previous = (self.path / "contacts.json").read_bytes()
        broken = self.path / "broken.xlsx"
        broken.write_bytes(b"broken workbook")
        with patch("bulk_mailer.gui.messagebox.showerror") as error:
            self.import_excel(broken)
        error.assert_called_once()
        self.assertEqual((self.path / "contacts.json").read_bytes(), previous)
        self.assertEqual(self.app.book.resolve("山田太郎"), "old@example.com")
        self.assertTrue(self.app.items[0].reviewed)
        self.assertFalse(self.app.contacts_dirty)

    def test_cache_write_failure_does_not_activate_new_contacts(self):
        previous = (self.path / "contacts.json").read_bytes()
        self.write_excel(self.excel, [("山田 太郎", "new@example.com")])
        with patch("bulk_mailer.gui.save_contacts", side_effect=OSError("disk full")), \
             patch("bulk_mailer.gui.messagebox.showerror") as error:
            self.import_excel(self.excel)
        error.assert_called_once()
        self.assertEqual((self.path / "contacts.json").read_bytes(), previous)
        self.assertEqual(self.app.book.resolve("山田太郎"), "old@example.com")
        self.assertFalse(self.app.contacts_dirty)

    def test_reimported_snapshot_does_not_follow_later_excel_edits(self):
        self.write_excel(self.excel, [("山田 太郎", "snapshot@example.com")])
        self.import_excel(self.excel)
        self.write_excel(self.excel, [("山田 太郎", "later@example.com")])
        self.app.save_config()
        self.assertEqual(self.app.items[0].to, "snapshot@example.com")
        self.assertEqual(load_contacts(self.path / "contacts.json")[0].resolve("山田太郎"), "snapshot@example.com")
