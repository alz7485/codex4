"""Independent GUI regressions for pointer gestures and the two-line contract grid.

All records and addresses below are generated examples; Outlook is never invoked.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bulk_mailer.core import AddressBook, Contact, Settings, parse_contracts, prepare_mails, save_settings
from bulk_mailer.gui import Application
from test_core import record


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt", "GUI requires a display")
class ReauditGridTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        directory = Path(self.temp.name)
        save_settings(Settings(subject="監査用共通件名"), directory / "settings.json")
        self.app = Application(directory, preview_mode=True)
        self.app.book = AddressBook([Contact("山田 太郎", "synthetic@example.com")])
        self.errors = []
        self.app.report_callback_exception = lambda *error: self.errors.append(error)
        self.fill_records(3)

    def tearDown(self):
        self.app.destroy()
        self.temp.cleanup()
        self.assertEqual(self.errors, [], "Tk callback exceptions must be reported")

    def fill_records(self, count, prefix="AUDIT"):
        source = "\n\n".join(record(f"{prefix}-{index:04d}") for index in range(count))
        self.app.source.delete("1.0", "end")
        self.app.source.insert("1.0", source)
        self.app.items = prepare_mails(parse_contracts(source), self.app.settings, self.app.book)
        self.app.source_snapshot = source
        self.app.refresh_table()
        self.app.notebook.select(self.app.review_page)
        self.app.table.selection_set("0")
        self.app.update()

    def row_y(self, position):
        table = self.app.table
        return int(table.header_height + position * table.row_height + table.row_height / 2 - table.canvasy(0))

    def drag(self, press_x, press_y, release_x, release_y):
        table = self.app.table
        table.event_generate("<ButtonPress-1>", x=press_x, y=press_y)
        table.event_generate("<B1-Motion>", x=release_x, y=release_y)
        table.event_generate("<ButtonRelease-1>", x=release_x, y=release_y)
        self.app.update()

    def test_drag_from_data_cell_to_target_column_does_not_exclude_record(self):
        table = self.app.table
        worker_x = sum(table.display_widths()[:2]) + 20
        self.drag(worker_x, self.row_y(0), 20, self.row_y(1))
        self.assertTrue(all(item.included for item in self.app.items),
                        "Dragging across cells must not change the mail recipient set")

    def test_press_one_target_and_release_another_does_not_toggle_either(self):
        self.drag(20, self.row_y(0), 20, self.row_y(1))
        self.assertTrue(all(item.included for item in self.app.items),
                        "Only a complete click within one target cell may toggle it")

    def test_drag_away_and_back_to_same_target_does_not_toggle_it(self):
        table = self.app.table
        y = self.row_y(0)
        table.event_generate("<ButtonPress-1>", x=20, y=y)
        table.event_generate("<B1-Motion>", x=120, y=y)
        table.event_generate("<B1-Motion>", x=20, y=y)
        table.event_generate("<ButtonRelease-1>", x=20, y=y)
        self.app.update()
        self.assertTrue(self.app.items[0].included,
                        "A completed drag must not become a click after returning to its origin")

    def test_list_refresh_between_press_and_release_cancels_target_change(self):
        table = self.app.table
        y = self.row_y(0)
        table.event_generate("<ButtonPress-1>", x=20, y=y)
        self.app.refresh_table()
        table.event_generate("<ButtonRelease-1>", x=20, y=y)
        self.app.update()
        self.assertTrue(self.app.items[0].included,
                        "Replacing the displayed rows must invalidate the previous pointer gesture")

    def test_recreating_list_starts_at_first_record_instead_of_old_scroll_position(self):
        self.fill_records(70)
        self.app.table.select_position(69)
        self.app.update()
        self.assertGreater(self.app.table.yview()[0], .5)
        replacement = "\n\n".join(record(f"REPLACED-{index:04d}") for index in range(70))
        self.app.source.delete("1.0", "end")
        self.app.source.insert("1.0", replacement)
        with patch("bulk_mailer.gui.messagebox.askyesno", return_value=True):
            self.app.create_list()
        self.app.update()
        self.assertEqual(self.app.table.selection(), ("0",))
        self.assertLess(self.app.table.yview()[0], .001,
                        "A fresh list should present its first record for full-list review")
        visible = {self.app.table.gettags(item)[1] for item in self.app.table.find_withtag("cell_text")}
        self.assertIn("0", visible)

    def test_keyboard_navigation_scrolls_selection_and_keeps_preview_in_sync(self):
        self.fill_records(70)
        table = self.app.table
        table.focus_force()
        self.app.update()
        for key, expected in (("End", 69), ("Up", 68), ("Home", 0), ("Down", 1)):
            with self.subTest(key=key):
                table.event_generate(f"<KeyPress-{key}>")
                self.app.update()
                self.assertEqual(table.selection(), (str(expected),))
                self.assertIn(f"AUDIT-{expected:04d}", self.app.preview_person.get())
                y = self.row_y(expected)
                self.assertGreaterEqual(y, table.header_height)
                self.assertLess(y, table.winfo_height())
        table.event_generate("<KeyPress-Next>")
        self.app.update()
        self.assertGreater(int(table.selection()[0]), 1)
        table.event_generate("<KeyPress-Prior>")
        self.app.update()
        self.assertEqual(table.selection(), ("1",))

    def test_horizontal_scroll_hit_testing_does_not_toggle_hidden_target_column(self):
        table = self.app.table
        self.app.items[0].contract.values["業務名"] = "横スクロール確認" * 100
        self.app.refresh_table()
        table.xview_moveto(1)
        self.app.update()
        self.assertEqual(table.identify_column(20), "#5")
        self.drag(20, self.row_y(0), 20, self.row_y(0))
        self.assertTrue(self.app.items[0].included)
        self.assertEqual(table.selection(), ("0",))

    def test_wheel_and_scrollbar_keep_header_pinned_and_header_click_is_inert(self):
        self.fill_records(70)
        table = self.app.table
        before = [item.included for item in self.app.items]
        table.event_generate("<MouseWheel>", delta=-360)
        self.app.update()
        self.assertGreater(table.yview()[0], 0)
        table.yview("moveto", .75)
        self.app.update()
        self.assertGreater(table.yview()[0], .6)
        self.assertLessEqual(abs(table.bbox("header")[1] - table.canvasy(0)), 1)
        self.drag(20, 10, 20, 10)
        self.assertEqual([item.included for item in self.app.items], before)
        self.assertEqual(table.identify_row(10), "")

    def test_busy_pointer_and_space_do_not_change_target_set(self):
        table = self.app.table
        self.app.set_busy(True)
        self.drag(20, self.row_y(0), 20, self.row_y(0))
        table.focus_force()
        self.app.update()
        table.event_generate("<KeyPress-space>")
        self.app.update()
        self.assertTrue(all(item.included for item in self.app.items))
        self.app.set_busy(False)

    def test_detail_window_follows_selection_and_reopens_without_resize(self):
        table = self.app.table
        self.app.toggle_details()
        self.app.update()
        size = self.app.details_window.winfo_geometry().split("+")[0]
        table.select_position(2)
        self.app.update()
        self.assertIn("AUDIT-0002", self.app.record_preview.get("1.0", "end-1c"))
        self.app.preview_tabs.select(1)
        self.app.update()
        self.app.toggle_details()
        self.app.update()
        self.app.toggle_details()
        self.app.update()
        self.assertEqual(self.app.details_window.winfo_geometry().split("+")[0], size)
        self.assertEqual(self.app.preview_tabs.index("current"), 1)
        self.assertTrue(self.app.details_visible)

    def test_resizing_scrolled_table_preserves_selected_record_and_two_line_cells(self):
        self.fill_records(70)
        table = self.app.table
        table.select_position(35)
        for geometry in ("1500x940", "1120x700", "1350x800"):
            with self.subTest(geometry=geometry):
                self.app.geometry(geometry)
                self.app.update()
                self.assertEqual(table.selection(), ("35",))
                self.assertEqual(len(table.rows[35].values), 5)
                self.assertTrue(all(value.count("\n") == 1 for value in table.rows[35].values))
                self.assertLess(len(table.find_withtag("cell_text")), 150)
                self.assertLessEqual(abs(table.bbox("header")[1] - table.canvasy(0)), 1)
                self.assertIn("AUDIT-0035", self.app.preview_person.get())


if __name__ == "__main__":
    unittest.main()
