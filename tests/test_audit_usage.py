"""Adversarial GUI workflows. Outlook is always replaced with a mock."""
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from bulk_mailer.core import Settings, save_settings
from bulk_mailer.gui import Application
from test_core import record


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt", "GUI requires a display")
class AuditUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.book_path = self.path / "contacts.xlsx"
        self.write_book("old@example.com")
        save_settings(Settings(subject="共通件名", address_book_path=str(self.book_path)), self.path / "settings.json")
        self.app = Application(self.path)
        self.callback_errors = []
        self.app.report_callback_exception = lambda *error: self.callback_errors.append(error)
        self.app.source.insert("1.0", record())
        self.app.create_list()
        self.app.update()
        self.execute_patch = patch("bulk_mailer.gui.execute_batch")
        self.execute_mock = self.execute_patch.start()
        self.error_patch = patch("bulk_mailer.gui.messagebox.showerror")
        self.errors = self.error_patch.start()
        self.info_patch = patch("bulk_mailer.gui.messagebox.showinfo")
        self.info_patch.start()

    def write_book(self, email):
        from openpyxl import Workbook
        book = Workbook()
        book.active.append(["氏名", "メールアドレス"])
        book.active.append(["山田 太郎", email])
        book.save(self.book_path)
        book.close()

    def tearDown(self):
        if self.app.busy:
            self.app.set_busy(False)
        self.app.destroy()
        self.execute_patch.stop()
        self.error_patch.stop()
        self.info_patch.stop()
        self.temp.cleanup()
        self.assertEqual(self.callback_errors, [])

    def poll_now(self):
        self.app.after_cancel(self.app.poll_job)
        self.app.poll_events()

    def edit_controls(self):
        self.app.edit_mail()
        window = next(widget for widget in self.app.winfo_children() if isinstance(widget, tk.Toplevel))

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        widgets = list(descendants(window))
        entries = [widget for widget in widgets if isinstance(widget, ttk.Entry)]
        body = next(widget for widget in widgets if isinstance(widget, tk.Text))
        save = next(widget for widget in widgets if isinstance(widget, ttk.Button))
        return window, entries, body, save

    def test_unsaved_subject_blocks_execution(self):
        self.app.review_selected()
        self.app.subject_var.set("未保存の件名")
        self.app.execute()
        self.execute_mock.assert_not_called()

    def test_unsaved_cc_blocks_list_regeneration(self):
        original = self.app.items[0]
        self.app.cc_input.insert("1.0", "new@example.com")
        self.app.create_list()
        self.assertIs(self.app.items[0], original)

    def test_invalid_save_keeps_existing_settings_and_review(self):
        self.app.review_selected()
        self.app.cc_input.insert("1.0", "not-an-email")
        self.app.save_config()
        self.assertEqual(self.app.settings.cc, "")
        self.assertTrue(self.app.items[0].reviewed)
        self.errors.assert_called_once()

    def test_save_uses_json_snapshot_until_excel_is_reimported(self):
        self.app.review_selected()
        self.write_book("new@example.com")
        self.app.save_config()
        self.assertEqual(self.app.items[0].to, "old@example.com")
        self.assertFalse(self.app.items[0].reviewed)
        with patch("bulk_mailer.gui.filedialog.askopenfilename", return_value=str(self.book_path)):
            self.app.import_contacts()
        self.app.save_config()
        self.assertEqual(self.app.items[0].to, "new@example.com")

    def test_cancelled_regeneration_preserves_individual_content(self):
        item = self.app.items[0]
        item.body = "個別に修正した本文"
        with patch("bulk_mailer.gui.messagebox.askyesno", return_value=False):
            self.app.create_list()
        self.assertIs(self.app.items[0], item)
        self.assertEqual(item.body, "個別に修正した本文")

    def test_invalid_new_input_preserves_previous_list(self):
        item = self.app.items[0]
        self.app.source.delete("1.0", "end")
        self.app.source.insert("1.0", "壊れたデータ")
        self.app.create_list()
        self.assertIs(self.app.items[0], item)
        self.errors.assert_called_once()

    def test_unreviewed_and_excluded_rows_cannot_execute(self):
        self.app.execute()
        self.execute_mock.assert_not_called()
        self.app.review_selected()
        self.app.toggle_included()
        self.app.execute()
        self.execute_mock.assert_not_called()

    def test_busy_blocks_all_modifying_commands(self):
        item = self.app.items[0]
        self.app.set_busy(True)
        for command in (self.app.create_list, self.app.save_config, self.app.import_contacts,
                        self.app.load_text, self.app.toggle_included, self.app.review_selected,
                        self.app.review_all, self.app.edit_mail, self.app.execute):
            command()
        self.assertIs(self.app.items[0], item)
        self.assertTrue(item.included)
        self.assertFalse(item.reviewed)
        self.execute_mock.assert_not_called()
        self.app.set_busy(False)

    def test_cancelled_execution_never_starts_worker(self):
        self.app.review_selected()
        with patch("bulk_mailer.gui.messagebox.askyesno", return_value=False):
            self.app.execute()
        self.assertFalse(self.app.busy)
        self.execute_mock.assert_not_called()

    def test_individual_long_unicode_edit_roundtrip_resets_review(self):
        self.app.review_selected()
        window, entries, body, save = self.edit_controls()
        entries[0].delete(0, "end")
        entries[0].insert(0, "manual@example.com")
        entries[1].insert(0, "first@example.com; second@example.com")
        content = "契約のご連絡です😀\n" * 1000
        body.delete("1.0", "end")
        body.insert("1.0", content)
        save.invoke()
        item = self.app.items[0]
        self.assertEqual(item.to, "manual@example.com")
        self.assertEqual(item.cc, ("first@example.com", "second@example.com"))
        self.assertEqual(item.body, content)
        self.assertFalse(item.reviewed)

    def test_invalid_individual_edit_does_not_mutate_item(self):
        self.app.review_selected()
        original_body = self.app.items[0].body
        window, entries, body, save = self.edit_controls()
        entries[0].delete(0, "end")
        entries[0].insert(0, "invalid")
        body.delete("1.0", "end")
        body.insert("1.0", "変更を保存してはいけない本文")
        save.invoke()
        item = self.app.items[0]
        self.assertEqual(item.to, "old@example.com")
        self.assertEqual(item.body, original_body)
        self.assertTrue(item.reviewed)
        self.errors.assert_called_once()
        window.destroy()

    def test_cancelled_individual_edit_preserves_original(self):
        original_body = self.app.items[0].body
        window, entries, body, save = self.edit_controls()
        body.delete("1.0", "end")
        body.insert("1.0", "保存しない変更")
        window.destroy()
        self.assertEqual(self.app.items[0].body, original_body)

    def test_finished_rows_are_not_rewritten_by_setting_changes(self):
        item = self.app.items[0]
        item.status = "下書き保存済み"
        self.app.subject_var.set("次回からの件名")
        self.app.save_config()
        self.assertIs(self.app.items[0], item)
        self.assertEqual(item.subject, "共通件名")

    def test_partial_finish_excludes_only_attempted_rows(self):
        item = self.app.items[0]
        item.status = "要確認（再実行不可）"
        self.app.set_busy(True)
        self.app.events.put(("finished", "モック停止", "mock.jsonl"))
        self.poll_now()
        self.assertFalse(self.app.busy)
        self.assertFalse(item.included)

    def test_same_path_excel_reload_exposes_stale_reviewed_recipient(self):
        """Regression probe: contact import must invalidate existing review state."""
        self.app.review_selected()
        self.write_book("new@example.com")
        with patch("bulk_mailer.gui.filedialog.askopenfilename", return_value=str(self.book_path)):
            self.app.import_contacts()
        self.assertEqual(self.app.book.resolve("山田 太郎"), "new@example.com")
        # A same-path reload must require an explicit apply before execution.
        self.assertTrue(self.app.has_unsaved_settings())

    def test_same_path_reload_blocks_execution_until_successful_save_and_recheck(self):
        self.app.review_selected()
        self.write_book("new@example.com")
        with patch("bulk_mailer.gui.filedialog.askopenfilename", return_value=str(self.book_path)):
            self.app.import_contacts()
        with patch("bulk_mailer.gui.threading.Thread") as thread:
            self.app.execute()
        thread.assert_not_called()
        self.app.cc_input.insert("1.0", "invalid")
        self.app.save_config()
        self.assertTrue(self.app.has_unsaved_settings())
        self.assertEqual(self.app.items[0].to, "old@example.com")
        self.app.cc_input.delete("1.0", "end")
        self.app.save_config()
        self.assertFalse(self.app.has_unsaved_settings())
        self.assertEqual(self.app.items[0].to, "new@example.com")
        self.assertFalse(self.app.items[0].reviewed)
        with patch("bulk_mailer.gui.threading.Thread") as thread:
            self.app.execute()
        thread.assert_not_called()

    def test_modified_source_requires_rebuild_before_execution(self):
        """Regression probe: edited input must not execute the stale list."""
        self.app.review_selected()
        self.app.source.insert("end-1c", "\n管理番号の追記")
        with patch("bulk_mailer.gui.messagebox.askyesno", return_value=True), \
             patch("bulk_mailer.gui.threading.Thread") as thread:
            self.app.execute()
        thread.assert_not_called()

    def test_settings_save_does_not_clear_modified_source_guard(self):
        self.app.source.insert("end-1c", "\n変更")
        self.app.subject_var.set("新しい件名")
        self.app.save_config()
        self.app.review_selected()
        with patch("bulk_mailer.gui.messagebox.askyesno", return_value=True), \
             patch("bulk_mailer.gui.threading.Thread") as thread:
            self.app.execute()
        thread.assert_not_called()

    def test_rebuilt_source_updates_snapshot_and_requires_review(self):
        self.app.source.delete("1.0", "end")
        self.app.source.insert("1.0", record(number="K-002"))
        with patch("bulk_mailer.gui.messagebox.askyesno", return_value=True):
            self.app.create_list()
        self.assertEqual(self.app.items[0].contract.values["管理番号"], "K-002")
        self.assertEqual(self.app.source_snapshot, self.app.source.get("1.0", "end-1c"))
        self.assertFalse(self.app.items[0].reviewed)

    def test_progress_burst_coalesces_table_redraws(self):
        """Regression probe: queued progress should not rebuild all rows per event."""
        for index in range(100):
            self.app.events.put(("progress", index, 100, "モック処理中"))
        with patch.object(self.app, "refresh_table") as refresh:
            self.poll_now()
        self.assertLessEqual(refresh.call_count, 2)

    def test_large_progress_burst_yields_then_processes_finish_once(self):
        self.app.set_busy(True)
        for index in range(6000):
            self.app.events.put(("progress", index, 6000, "モック処理中"))
        self.app.events.put(("finished", "", "mock.jsonl"))
        with patch.object(self.app, "refresh_table") as refresh:
            self.poll_now()
            self.assertEqual(self.app.events.qsize(), 1001)
            self.assertTrue(self.app.busy)
            self.assertEqual(refresh.call_count, 1)
            self.poll_now()
            self.assertTrue(self.app.events.empty())
            self.assertFalse(self.app.busy)
            self.assertEqual(refresh.call_count, 2)
        self.assertIn("処理が完了", self.app.status.get())


if __name__ == "__main__":
    unittest.main()
