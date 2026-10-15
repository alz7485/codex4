"""Settings writes must remain atomic when two application instances save."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from bulk_mailer.core import Settings, load_settings, save_settings


class SettingsConcurrencyTests(unittest.TestCase):
    def test_concurrent_saves_both_finish_with_a_complete_settings_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            barrier = threading.Barrier(2)
            original = Path.replace

            def concurrent_replace(source, target):
                barrier.wait(timeout=5)
                return original(source, target)

            with patch.object(Path, "replace", concurrent_replace), ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(save_settings, Settings(subject=subject), path)
                           for subject in ("件名A", "件名B")]
                for future in futures:
                    future.result(timeout=10)
            self.assertIn(load_settings(path).subject, ("件名A", "件名B"))
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_failed_save_keeps_previous_settings_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_settings(Settings(subject="保存済み"), path)
            with patch("bulk_mailer.core.os.fsync", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    save_settings(Settings(subject="保存失敗"), path)
            self.assertEqual(load_settings(path).subject, "保存済み")
            self.assertEqual(list(path.parent.glob("*.tmp")), [])
