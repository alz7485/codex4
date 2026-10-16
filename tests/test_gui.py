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
        self.assertEqual(self.app.table.columns, ("included", "id", "worker", "period", "receiver"))
        self.assertIn("作成待ち", self.app.table.set("0", "included"))
        values = self.app.items[0].contract.values
        displayed = "\n".join(self.app.table.item("0", "values"))
        for value in values.values():
            self.assertIn(value, displayed)
        self.assertIn("yamada@example.com", displayed)
        self.assertTrue(all(value.count("\n") == 1 for value in self.app.table.item("0", "values")))
        self.assertFalse(self.app.details_visible)
        self.assertEqual(tuple(self.app.table.item("0", "tags")), ())

    def test_exclusion_updates_compact_summary_without_coloring_valid_row(self):
        self.app.toggle_included()
        self.assertFalse(self.app.items[0].included)
        self.assertIn("作成対象 0件", self.app.summary.get())
        self.assertEqual(tuple(self.app.table.item("0", "tags")), ())

    def test_settings_change_rebuilds_pending_mail(self):
        self.app.subject_var.set("新しい共通件名")
        self.app.cc_input.insert("1.0", "cc@example.com")
        self.app.save_config()
        self.assertEqual(self.app.items[0].subject, "新しい共通件名")
        self.assertEqual(self.app.items[0].cc, ("cc@example.com",))
        self.assertEqual(self.app.preview_subject.get(), "新しい共通件名")

    def test_only_problem_rows_are_colored_and_correction_clears_color(self):
        from bulk_mailer.core import parse_contracts, prepare_mails
        self.app.items = prepare_mails(parse_contracts(record() + "\n\n" + record("K-002", "未登録の氏名")),
                                      self.app.settings, self.app.book)
        self.app.refresh_table()
        self.assertEqual(tuple(self.app.table.item("0", "tags")), ())
        self.assertEqual(tuple(self.app.table.item("1", "tags")), ("error",))
        self.assertIn("宛先未登録", self.app.table.set("1", "worker"))
        self.app.items[1].to, self.app.items[1].issue = "fixed@example.com", ""
        self.app.refresh_table()
        self.assertEqual(tuple(self.app.table.item("1", "tags")), ())
        self.assertIn("作成待ち", self.app.table.set("1", "included"))
        self.app.items[0].status = "下書き保存済み"
        self.app.refresh_table()
        self.assertEqual(tuple(self.app.table.item("0", "tags")), ())
        self.app.items[0].status = "要確認（再実行不可）"
        self.app.refresh_table()
        self.assertEqual(tuple(self.app.table.item("0", "tags")), ("error",))

    def test_missing_subject_colors_rows_and_settings_save_clears_color(self):
        self.app.subject_var.set("")
        self.app.save_config()
        self.assertEqual(tuple(self.app.table.item("0", "tags")), ("error",))
        self.assertIn("件名", self.app.table.rows[0].problem)
        self.assertIn("件名", self.app.preview_issue.get())
        self.app.subject_var.set("設定済み件名")
        self.app.save_config()
        self.assertEqual(tuple(self.app.table.item("0", "tags")), ())
        self.assertEqual(self.app.preview_issue.get(), "")

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

    def test_long_two_line_cells_are_not_truncated_and_have_grid_borders(self):
        table = self.app.table
        values = self.app.items[0].contract.values
        values["派遣元"] = "長い名称の派遣元株式会社" * 20
        values["業務名"] = "詳細な業務名\t追加説明" * 20
        self.app.items[0].cc = ("individual@example.com",)
        self.app.refresh_table()
        self.app.update()
        self.assertIn(values["派遣元"], table.set("0", "worker"))
        self.assertIn("individual@example.com", table.set("0", "worker"))
        texts = table.find_withtag("cell_text")
        self.assertEqual(len(texts), 5)
        borders = table.find_withtag("cell")
        self.assertEqual(len(borders), 5)
        x = 0
        for text, border, width in zip(texts, borders, table.display_widths()):
            left, top, right, bottom = table.bbox(text)
            self.assertGreaterEqual(left, x)
            self.assertLessEqual(right, x + width)
            self.assertLessEqual(bottom - top, table.row_height)
            self.assertEqual(table.itemcget(border, "outline"), "#c6cfdb")
            self.assertEqual(table.itemcget(text, "text").count("\n"), 1)
            x += width
        self.assertLess(table.xview()[1], 1.0)

    def test_grid_selection_and_target_toggle_work_on_either_line(self):
        table = self.app.table
        for offset in (16, table.row_height - 8):
            before = self.app.items[0].included
            table.event_generate("<ButtonPress-1>", x=20, y=table.header_height + offset)
            table.event_generate("<ButtonRelease-1>", x=20, y=table.header_height + offset)
            self.app.update()
            self.assertEqual(self.app.items[0].included, not before)
        before = self.app.items[0].included
        table.event_generate("<ButtonRelease-1>", x=20, y=10)
        self.assertEqual(self.app.items[0].included, before)
        self.assertEqual(table.selection(), ("0",))

    def test_large_grid_scrolls_to_last_record_and_keeps_header_visible(self):
        from bulk_mailer.grid_table import GridRow
        table = self.app.table
        prototype = table.rows[0].values
        table.set_rows([GridRow(str(index), prototype) for index in range(1000)])
        self.app.update()
        table.select_position(999)
        self.app.update()
        self.assertEqual(table.selection(), ("999",))
        self.assertLess(len(table.find_withtag("cell_text")), 100)
        visible_ids = set(table.gettags(item)[1] for item in table.find_withtag("cell_text"))
        self.assertIn("999", visible_ids)
        header = table.bbox("header")
        self.assertLessEqual(abs(header[1] - table.canvasy(0)), 1)
        self.assertEqual(table.identify_row(10), "")
        table.select_position(0)
        self.assertEqual(table.selection(), ("0",))
        self.assertLess(table.yview()[0], .001)


if __name__ == "__main__":
    unittest.main()
