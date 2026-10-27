"""Check runtime packages before importing the GUI, including windowed builds."""
import importlib
from pathlib import Path
import sys


def check_dependencies() -> None:
    modules = ["tkinter", "tkinterdnd2", "openpyxl"]
    if sys.platform == "win32":
        modules += ["pythoncom", "win32com.client"]
    for name in modules:
        importlib.import_module(name)


def dependency_message(error: ImportError) -> str:
    detail = f"必要なライブラリを読み込めません。\n{error}\n\n"
    if getattr(sys, "frozen", False):
        return detail + ("ZIPを展開し直し、EXEと _internal フォルダーを一緒に配置してください。\n"
                         "解消しない場合は、ソース版の build_exe.bat でEXEを作り直してください。")
    requirements = Path(__file__).resolve().parent / "requirements.txt"
    return detail + ("アプリのフォルダーで setup.bat を実行し、start.bat から起動してください。\n\n"
                     f"今回起動したPython: {sys.executable}\n"
                     "このPythonを使う場合は、コマンドプロンプトで次を実行してください。\n"
                     f'"{sys.executable}" -m pip install -r "{requirements}"')


def main() -> int:
    check_only = "--check-dependencies" in sys.argv[1:]
    try:
        check_dependencies()
    except ImportError as error:
        message = dependency_message(error)
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        if sys.platform == "win32" and not check_only:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "契約通知アシスト：起動エラー", 0x10)
        return 1
    if not check_only:
        from bulk_mailer.gui import main as run_gui
        run_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
