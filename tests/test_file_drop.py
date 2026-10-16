"""Exercise file drops through registered Tcl callbacks, with real Tk widgets."""
import os
from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from openpyxl import Workbook
from tkinterdnd2 import COPY, REFUSE_DROP

from bulk_mailer.core import AddressBook, Contact, Settings, load_contacts, save_contacts, save_settings
from bulk_mailer.gui import Application
from test_core import record


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt", "GUI requires a display")
class FileDropTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name)
        save_settings(Settings(subject="共通件名"), self.path / "settings.json")
        save_contacts(AddressBook([Contact("山田 太郎", "old@example.com")]), self.path / "contacts.json")
        self.app = Application(self.path, preview_mode=True)
        self.errors = []
        self.app.report_callback_exception = lambda *error: self.errors.append(error)
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        self.temporary.cleanup()
        self.assertEqual(self.errors, [])

    def drop(self, *paths, widget=None):
        widget = widget if widget is not None else self.app.source
        # Native TkDND supplies a Tcl list, including quoted paths with spaces.
        data = self.app.tk.call("format", "%s", self.app.tk.call("list", *(str(p) for p in paths)))
        callback = widget.dnd_bind("<<Drop>>").split()[0]
        substitutions = (COPY, COPY, "1", "", "", "", "", data, "<<Drop>>",
                         "", "", "", "", "", "", str(widget), "0", "0")
        return self.app.tk.call(callback, *substitutions)

    def make_text(self, name="日本語 空白 入力.TXT"):
        path = self.path / name
        path.write_text(record(), encoding="utf-8-sig")
        return path

    def make_excel(self):
        path = self.path / "宛先 対応表.XLSX"
        book = Workbook()
        book.active.append(["氏名", "メールアドレス"])
        book.active.append(["山田　太郎", "new@example.com"])
        book.save(path)
        book.close()
        return path

    def test_text_drop_with_japanese_spaces_and_uppercase_extension(self):
        self.app.notebook.select(self.app.settings_page)
        with patch("bulk_mailer.gui.filedialog.askopenfilename") as picker:
            self.assertEqual(self.drop(self.make_text(), widget=self.app.template_input), COPY)
        picker.assert_not_called()
        self.assertEqual(self.app.source.get("1.0", "end-1c"), record())
        self.assertTrue(self.app.breadcrumb.get().endswith("テキスト入力"))
        self.assertEqual(self.app.items, [])

    def test_text_overwrite_cancel_preserves_input_and_list(self):
        self.app.source.insert("1.0", record())
        self.app.create_list()
        original = self.app.items
        with patch("bulk_mailer.gui.messagebox.askyesno", return_value=False) as confirm:
            self.assertEqual(self.drop(self.make_text()), REFUSE_DROP)
        confirm.assert_called_once()
        self.assertEqual(self.app.source.get("1.0", "end-1c"), record())
        self.assertIs(self.app.items, original)
        self.assertTrue(self.app.breadcrumb.get().endswith("一覧・内容確認"))

    def test_text_replace_requires_list_recreation_before_execution(self):
        self.app.source.insert("1.0", record())
        self.app.create_list()
        path = self.make_text()
        path.write_text(record().replace("K-001", "K-999"), encoding="utf-8")
        with patch("bulk_mailer.gui.messagebox.askyesno", return_value=True):
            self.assertEqual(self.drop(path), COPY)
        self.assertNotEqual(self.app.source_snapshot, self.app.source.get("1.0", "end-1c"))
        self.app.preview_mode = False
        with patch("bulk_mailer.gui.messagebox.showinfo") as info, patch("bulk_mailer.gui.execute_batch") as execute:
            self.app.execute()
        info.assert_called_once()
        execute.assert_not_called()

    def test_excel_drop_replaces_json_but_requires_settings_save(self):
        self.app.source.insert("1.0", record())
        self.app.create_list()
        self.assertEqual(self.drop(self.make_excel(), widget=self.app.preview_tabs), COPY)
        stored, _ = load_contacts(self.app.contacts_path)
        self.assertEqual(stored.contacts, [Contact("山田　太郎", "new@example.com")])
        self.assertTrue(self.app.breadcrumb.get().endswith("設定"))
        self.assertTrue(self.app.contacts_dirty)
        self.assertEqual(self.app.items[0].to, "old@example.com")
        self.app.save_config()
        self.assertEqual(self.app.items[0].to, "new@example.com")

    def test_broken_excel_drop_preserves_previous_json_and_memory(self):
        previous = self.app.contacts_path.read_bytes()
        broken = self.path / "broken.xlsx"
        broken.write_bytes(b"not a workbook")
        with patch("bulk_mailer.gui.messagebox.showerror") as error:
            self.assertEqual(self.drop(broken), REFUSE_DROP)
        error.assert_called_once()
        self.assertEqual(self.app.contacts_path.read_bytes(), previous)
        self.assertEqual(self.app.book.resolve("山田太郎"), "old@example.com")
        self.assertFalse(self.app.contacts_dirty)

    def test_excel_disk_failure_preserves_previous_json_and_memory(self):
        previous = self.app.contacts_path.read_bytes()
        with patch("bulk_mailer.gui.save_contacts", side_effect=OSError("disk full")), \
             patch("bulk_mailer.gui.messagebox.showerror") as error:
            self.assertEqual(self.drop(self.make_excel()), REFUSE_DROP)
        error.assert_called_once()
        self.assertEqual(self.app.contacts_path.read_bytes(), previous)
        self.assertEqual(self.app.book.resolve("山田太郎"), "old@example.com")

    def test_multiple_files_are_rejected_before_any_import(self):
        previous = self.app.contacts_path.read_bytes()
        with patch("bulk_mailer.gui.messagebox.showwarning") as warning:
            self.assertEqual(self.drop(self.make_text(), self.make_excel()), REFUSE_DROP)
        warning.assert_called_once()
        self.assertEqual(self.app.source.get("1.0", "end-1c"), "")
        self.assertEqual(self.app.contacts_path.read_bytes(), previous)

    def test_unsupported_directory_missing_and_empty_drops_are_rejected(self):
        unsupported = self.path / "input.csv"
        unsupported.write_text("x", encoding="utf-8")
        for paths in ((unsupported,), (self.path,), (self.path / "missing.txt",), ()):
            with self.subTest(paths=paths), patch("bulk_mailer.gui.messagebox.showwarning") as warning:
                self.assertEqual(self.drop(*paths), REFUSE_DROP)
                warning.assert_called_once()
        self.assertEqual(self.app.source.get("1.0", "end-1c"), "")

    def test_busy_drop_refuses_without_dialogs_or_mutation(self):
        path = self.make_text()
        self.app.set_busy(True)
        with patch("bulk_mailer.gui.messagebox.showwarning") as warning:
            self.assertEqual(self.drop(path), REFUSE_DROP)
            self.assertEqual(self.app.allow_file_drop(SimpleNamespace()), REFUSE_DROP)
        warning.assert_not_called()
        self.assertEqual(self.app.source.get("1.0", "end-1c"), "")
        self.app.set_busy(False)
        self.assertEqual(self.app.allow_file_drop(SimpleNamespace()), COPY)

    def test_invalid_tcl_file_list_does_not_crash(self):
        with patch("bulk_mailer.gui.messagebox.showwarning") as warning:
            self.assertEqual(self.app.on_file_drop(SimpleNamespace(data="{broken")), REFUSE_DROP)
        warning.assert_called_once()

    def test_unreadable_text_preserves_existing_input(self):
        self.app.source.insert("1.0", "保持する入力")
        with patch("bulk_mailer.gui.read_text_file", side_effect=OSError("access denied")), \
             patch("bulk_mailer.gui.messagebox.showerror") as error:
            self.assertEqual(self.drop(self.make_text()), REFUSE_DROP)
        error.assert_called_once()
        self.assertEqual(self.app.source.get("1.0", "end-1c"), "保持する入力")

    def test_preview_tabs_keep_bounds_and_content_size_when_selected(self):
        self.app.source.insert("1.0", record())
        self.app.create_list()
        tabs = self.app.preview_tabs

        def rectangles():
            points = {0: [], 1: []}
            # Tab hit regions expose geometry changes that widget bounds alone miss.
            for y in range(min(tabs.winfo_height(), 65)):
                for x in range(min(tabs.winfo_width(), 400)):
                    try:
                        index = tabs.index(f"@{x},{y}")
                    except tk.TclError:
                        continue
                    points[index].append((x, y))
            return {i: (min(x for x, y in p), min(y for x, y in p),
                        max(x for x, y in p), max(y for x, y in p)) for i, p in points.items()}

        for geometry in ("1500x940", "1180x800"):
            with self.subTest(geometry=geometry):
                self.app.geometry(geometry)
                tabs.select(0)
                self.app.update()
                bounds = rectangles()
                dimensions = (self.app.winfo_width(), self.app.winfo_height(),
                              tabs.winfo_width(), tabs.winfo_height(),
                              self.app.preview.winfo_width(), self.app.preview.winfo_height())
                for index in (1, 0, 1, 0):
                    tabs.select(index)
                    self.app.update()
                    text = self.app.record_preview if index else self.app.preview
                    self.assertEqual(rectangles(), bounds)
                    self.assertEqual((self.app.winfo_width(), self.app.winfo_height(),
                                      tabs.winfo_width(), tabs.winfo_height(),
                                      text.winfo_width(), text.winfo_height()), dimensions)
