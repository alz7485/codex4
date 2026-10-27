"""Missing runtime packages must produce actionable help before the GUI loads."""
import io
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import main as launcher


class StartupTests(unittest.TestCase):
    def test_runtime_check_includes_dnd_and_windows_com(self):
        with patch.object(launcher.sys, "platform", "win32"), \
                patch.object(launcher.importlib, "import_module") as load:
            launcher.check_dependencies()
        self.assertEqual([call.args[0] for call in load.call_args_list],
                         ["tkinter", "tkinterdnd2", "openpyxl", "pythoncom", "win32com.client"])

    def test_missing_dnd_is_detected_before_gui_import(self):
        def load(name):
            if name == "tkinterdnd2":
                raise ModuleNotFoundError("No module named 'tkinterdnd2'", name=name)
        with patch.object(launcher.sys, "argv", ["main.py", "--check-dependencies"]), \
                patch.object(launcher.sys, "stderr", io.StringIO()) as output, \
                patch.object(launcher.importlib, "import_module", side_effect=load), \
                patch.dict(sys.modules, {"bulk_mailer.gui": None}):
            self.assertEqual(launcher.main(), 1)
        self.assertIn("tkinterdnd2", output.getvalue())
        self.assertIn("setup.bat", output.getvalue())
        self.assertIn("start.bat", output.getvalue())
        self.assertIn(launcher.sys.executable, output.getvalue())
        self.assertIn("-m pip install -r", output.getvalue())

    def test_successful_check_does_not_open_gui(self):
        with patch.object(launcher.sys, "argv", ["main.py", "--check-dependencies"]), \
                patch.object(launcher, "check_dependencies"), \
                patch.dict(sys.modules, {"bulk_mailer.gui": None}):
            self.assertEqual(launcher.main(), 0)

    def test_successful_launch_calls_gui_once(self):
        gui = ModuleType("bulk_mailer.gui")
        gui.main = Mock()
        with patch.object(launcher.sys, "argv", ["main.py"]), \
                patch.object(launcher, "check_dependencies"), \
                patch.dict(sys.modules, {"bulk_mailer.gui": gui}):
            self.assertEqual(launcher.main(), 0)
        gui.main.assert_called_once_with()

    def test_exe_help_refers_to_full_distribution_instead_of_pip(self):
        with patch.object(launcher.sys, "frozen", True, create=True):
            message = launcher.dependency_message(ImportError("tkinterdnd2"))
        self.assertIn("_internal", message)
        self.assertIn("build_exe.bat", message)
        self.assertNotIn("pip install", message)

    def test_windowed_exe_with_no_stderr_displays_error_dialog(self):
        import ctypes
        dialog = Mock()
        with patch.object(launcher.sys, "platform", "win32"), \
                patch.object(launcher.sys, "argv", ["app.exe"]), \
                patch.object(launcher.sys, "stderr", None), \
                patch.object(launcher, "check_dependencies", side_effect=ImportError("tkinterdnd2")), \
                patch.object(ctypes, "windll", dialog, create=True):
            self.assertEqual(launcher.main(), 1)
        dialog.user32.MessageBoxW.assert_called_once()

    def test_unexpected_gui_failure_is_not_disguised_as_missing_package(self):
        gui = ModuleType("bulk_mailer.gui")
        gui.main = Mock(side_effect=RuntimeError("unexpected GUI failure"))
        with patch.object(launcher.sys, "argv", ["main.py"]), \
                patch.object(launcher, "check_dependencies"), \
                patch.dict(sys.modules, {"bulk_mailer.gui": gui}), \
                self.assertRaisesRegex(RuntimeError, "unexpected GUI failure"):
            launcher.main()
