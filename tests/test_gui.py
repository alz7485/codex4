import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bulk_mailer.core import AddressBook, Contact, Settings, save_settings
from bulk_mailer.gui import Application
from test_core import record


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt", "GUI検証にはディスプレイが必要です")
class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        path = Path(self.temporary.name)
        save_settings(Settings(subject="共通の件名"), path / "settings.json")
        self.app = Application(path, preview_mode=True)
        self.app.book = AddressBook([Contact("山田 太郎", "yamada@example.com")])
        self.callback_errors = []
        self.app.report_callback_exception = lambda *error: self.callback_errors.append(error)
        self.app.source.insert("1.0", record())
        self.app.create_list()
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        self.temporary.cleanup()
        self.assertEqual(self.callback_errors, [])

    def test_parsed_data_reaches_table_and_preview(self):
        self.assertEqual(len(self.app.table.get_children()), 1)
        self.assertEqual(self.app.preview_to.get(), "yamada@example.com")
        self.assertEqual(self.app.preview_subject.get(), "共通の件名")
        self.assertIn("山田 太郎", self.app.preview.get("1.0", "end"))
        self.assertIn("第一チーム", self.app.record_preview.get("1.0", "end"))
        self.assertEqual([variable.get() for variable in self.app.metric_vars], ["1", "1", "0", "0"])

    def test_review_and_exclusion_update_metrics(self):
        self.app.review_selected()
        self.assertTrue(self.app.items[0].reviewed)
        self.assertEqual(self.app.metric_vars[2].get(), "1")
        self.app.toggle_included()
        self.assertFalse(self.app.items[0].included)
        self.assertEqual(self.app.metric_vars[1].get(), "0")

    def test_settings_change_rebuilds_pending_mail_and_clears_review(self):
        self.app.review_selected()
        self.app.subject_var.set("新しい共通件名")
        self.app.cc_input.insert("1.0", "cc@example.com")
        self.app.save_config()
        self.assertEqual(self.app.items[0].subject, "新しい共通件名")
        self.assertEqual(self.app.items[0].cc, ("cc@example.com",))
        self.assertFalse(self.app.items[0].reviewed)
        self.assertEqual(self.app.preview_subject.get(), "新しい共通件名")

    def test_mode_save_changes_visible_execution_action(self):
        self.app.mode_var.set("send")
        self.app.save_config()
        self.assertIn("送信", self.app.execute_button.cget("text"))
        self.assertIn("送信", self.app.mode_label.cget("text"))
        self.app.mode_var.set("draft")
        self.app.save_config()
        self.assertIn("下書き", self.app.execute_button.cget("text"))

    def test_busy_state_restores_readonly_and_editable_controls(self):
        self.app.set_busy(True)
        self.assertEqual(str(self.app.source.cget("state")), "disabled")
        self.app.set_busy(False)
        self.assertEqual(str(self.app.source.cget("state")), "normal")
        self.assertEqual(str(self.app.preview.cget("state")), "disabled")

    def test_preview_mode_never_calls_outlook(self):
        with patch("bulk_mailer.gui.messagebox.showinfo"), patch("bulk_mailer.gui.execute_batch") as execute:
            self.app.execute()
            execute.assert_not_called()

    def test_insert_field_edits_actual_template(self):
        self.app.template_input.mark_set("insert", "end-1c")
        self.app.insert_field("チーム名")
        self.assertTrue(self.app.template_input.get("1.0", "end-1c").endswith("{チーム名}"))


if __name__ == "__main__":
    unittest.main()
