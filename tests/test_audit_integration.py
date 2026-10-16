"""Verify durable execution history at the GUI boundary; Outlook is a mock."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from openpyxl import Workbook

from bulk_mailer.core import Settings, save_settings
from bulk_mailer.gui import Application
from bulk_mailer.outlook import execute_batch
from test_core import record


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt", "GUI requires a display")
class HistoryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name)
        book = Workbook()
        book.active.append(["氏名", "メールアドレス"])
        book.active.append(["山田 太郎", "yamada@example.com"])
        book.save(self.path / "contacts.xlsx")
        book.close()
        save_settings(Settings(subject="監査用件名", address_book_path=str(self.path / "contacts.xlsx")),
                      self.path / "settings.json")
        self.errors = []
        self.app = self.make_app()

    def make_app(self):
        app = Application(self.path, preview_mode=True)
        app.report_callback_exception = lambda *error: self.errors.append(error)
        app.source.insert("1.0", record())
        app.create_list()
        app.update()
        return app

    def tearDown(self):
        self.app.destroy()
        self.temporary.cleanup()
        self.assertEqual(self.errors, [])

    def save_draft_with_fake_outlook(self):
        client = Mock()
        client.create.return_value = "下書き保存済み"
        execute_batch(self.app.items, "draft", self.path / "logs" / "first.jsonl",
                      lambda *_: None, lambda: client)
        client.create.assert_called_once()

    def recreate_list(self):
        with patch("bulk_mailer.gui.messagebox.askyesno", return_value=True):
            self.app.create_list()

    def test_regenerated_list_excludes_already_created_mail(self):
        self.save_draft_with_fake_outlook()
        self.recreate_list()
        self.assertEqual(self.app.items[0].status, "履歴あり（下書き保存済み）")
        self.assertFalse(self.app.items[0].included)
        self.app.toggle_included()
        self.assertFalse(self.app.items[0].included)
        self.assertIn("作成対象 0件", self.app.summary.get())

    def test_restarted_app_excludes_already_created_mail(self):
        self.save_draft_with_fake_outlook()
        self.app.destroy()
        self.app = self.make_app()
        self.assertIn("履歴あり", self.app.items[0].status)
        self.assertFalse(self.app.items[0].included)

    def test_mode_change_can_send_after_draft_history(self):
        self.save_draft_with_fake_outlook()
        self.recreate_list()
        self.app.mode_var.set("send")
        self.app.save_config()
        self.assertEqual(self.app.items[0].status, "未実行")
        self.assertTrue(self.app.items[0].included)

    def test_corrupt_history_preserves_old_list_and_settings(self):
        previous = self.app.items[0]
        (self.path / "logs" / "corrupt.jsonl").write_text("{broken", encoding="utf-8")
        with patch("bulk_mailer.gui.messagebox.showerror") as error:
            self.app.create_list()
            self.assertIs(self.app.items[0], previous)
            self.app.subject_var.set("保存すべきでない件名")
            self.app.save_config()
        self.assertEqual(error.call_count, 2)
        self.assertEqual(self.app.settings.subject, "監査用件名")

    def test_invalid_body_edit_is_rejected_without_changing_existing_mail(self):
        self.app.edit_mail()
        import tkinter as tk
        from tkinter import ttk
        window = next(child for child in self.app.winfo_children()
                      if isinstance(child, tk.Toplevel) and child.title().startswith("メールを編集"))

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        widgets = list(descendants(window))
        body = next(child for child in widgets if isinstance(child, tk.Text))
        button = next(child for child in widgets if isinstance(child, ttk.Button))
        original = self.app.items[0].body
        body.delete("1.0", "end")
        body.insert("1.0", "不正\x00本文")
        with patch("bulk_mailer.gui.messagebox.showerror") as error:
            button.invoke()
        error.assert_called_once()
        self.assertEqual(self.app.items[0].body, original)
        window.destroy()
