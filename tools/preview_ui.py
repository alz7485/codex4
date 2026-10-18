"""Capture the actual Tk UI using sample data; requires a display and Pillow.

Usage: python tools/preview_ui.py
Outlook actions are disabled, and settings are written to a temporary directory.
"""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import ImageGrab
from bulk_mailer.core import Settings, read_text_file, save_settings
from bulk_mailer.gui import Application


def main():
    output = ROOT / "docs" / "previews"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(subject="契約締結完了のお知らせ", cc="jinji@example.com",
                            address_book_path=str(ROOT / "samples" / "社員情報サンプル.csv"))
        save_settings(settings, Path(directory) / "settings.json")
        app = Application(Path(directory), preview_mode=True)
        errors = []
        app.report_callback_exception = lambda *error: errors.append(error)
        app.geometry("1500x940+0+0")
        text = read_text_file(ROOT / "samples" / "入力サンプル.txt")
        third = text.strip().split("\n\nK-002")[0].replace("K-001", "K-003").replace("山田 太郎", "鈴木 一郎")
        app.source.insert("1.0", text.rstrip() + "\n\n" + third + "\n")
        app.source_info.set("入力サンプル.txt  ·  サンプルデータ 3件")
        app.update()

        def capture(name, widget=None):
            app.update()
            widget = app if widget is None else widget
            box = (widget.winfo_rootx(), widget.winfo_rooty(), widget.winfo_rootx() + widget.winfo_width(),
                   widget.winfo_rooty() + widget.winfo_height())
            ImageGrab.grab(bbox=box).save(output / name)

        capture("input.png")
        app.create_list()
        assert len(app.items) == 3
        app.table.selection_set("0")
        app.show_preview()
        app.status.set("サンプルデータ 3件を表示しています。")
        capture("review.png")
        app.notebook.select(app.settings_page)
        capture("settings.png")
        app.show_contacts()
        capture("employees.png", app.employee_window)
        assert not errors, errors
        app.destroy()
    print(f"Captured actual application screens: {output}")


if __name__ == "__main__":
    main()
