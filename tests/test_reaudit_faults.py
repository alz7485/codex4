"""Independent fault injection. No real COM client or Outlook is instantiated."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bulk_mailer.core import (
    AddressBook, Contact, InputError, Settings, load_contacts, load_settings,
    parse_contracts, prepare_mails, save_contacts, save_settings,
)
from bulk_mailer.outlook import OperationLock, apply_history, execute_batch
from test_core import record


class FaultReauditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def items(self, number="FAULT-1"):
        return prepare_mails(parse_contracts(record(number)), Settings(subject="障害監査"),
                             AddressBook([Contact("山田 太郎", "audit@example.com")]))

    def test_external_error_unicode_line_separators_preserve_valid_jsonl(self):
        for separator in ("\u2028", "\u2029", "\u0085"):
            with self.subTest(separator=repr(separator)), tempfile.TemporaryDirectory() as directory:
                logs = Path(directory)
                client = Mock()
                client.create.side_effect = RuntimeError("RPC error" + separator + "external detail")
                with self.assertRaisesRegex(InputError, "処理を停止"):
                    execute_batch(self.items(), "draft", logs / "run.jsonl", lambda *_: None,
                                  lambda: client)
                # JSONL records are separated by LF, not all Unicode separators.
                rows = [json.loads(line) for line in (logs / "run.jsonl").read_text().split("\n") if line]
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[-1]["detail"], "RPC error" + separator + "external detail")
                unrelated = self.items("FAULT-NEW")
                apply_history(unrelated, "draft", logs)
                self.assertEqual(unrelated[0].status, "未実行")
                attempted = self.items()
                apply_history(attempted, "draft", logs)
                self.assertFalse(attempted[0].included)
                self.assertIn("要確認", attempted[0].status)

    def test_history_jsonl_physical_line_boundaries_preserve_validation(self):
        row = json.dumps({"management_number": "FAULT-1", "mode": "draft", "status": "開始"})
        cases = (("no-final-newline", row, True), ("crlf", row + "\r\n", True),
                 ("empty-file", "", False), ("lf", row + "\n", True))
        for label, data, attempted in cases:
            with self.subTest(label=label):
                (self.directory / "run.jsonl").write_bytes(data.encode("utf-8"))
                items = self.items()
                apply_history(items, "draft", self.directory)
                self.assertEqual(items[0].included, not attempted)
                self.assertEqual(items[0].status, "履歴あり（要確認）" if attempted else "未実行")
        for data in (row + "\n\n" + row + "\n", row + "\n\n", "\n"):
            with self.subTest(blank_line=repr(data)):
                (self.directory / "run.jsonl").write_text(data, encoding="utf-8")
                items = self.items()
                with self.assertRaises(InputError):
                    apply_history(items, "draft", self.directory)
                self.assertEqual(items[0].status, "未実行")
                factory = Mock()
                with self.assertRaises(InputError):
                    execute_batch(items, "draft", self.directory / "retry.jsonl", lambda *_: None, factory)
                factory.assert_not_called()

    def test_deep_history_json_is_reported_as_input_error_before_com(self):
        payload = ('{"management_number":"FAULT-1","mode":"draft","status":"開始","detail":'
                   + "[" * 10_000 + "0" + "]" * 10_000 + "}\n")
        (self.directory / "run.jsonl").write_text(payload, encoding="utf-8")
        with self.assertRaisesRegex(InputError, "処理記録"):
            apply_history(self.items(), "draft", self.directory)
        factory = Mock()
        with self.assertRaises(InputError):
            execute_batch(self.items(), "draft", self.directory / "retry.jsonl", lambda *_: None, factory)
        factory.assert_not_called()

    def test_forced_process_exit_releases_lock_and_preserves_durable_history(self):
        script = '''
import sys
from pathlib import Path
from bulk_mailer.core import AddressBook, Contact, Settings, parse_contracts, prepare_mails
from bulk_mailer.outlook import execute_batch
from test_core import record
stage, directory = sys.argv[1], Path(sys.argv[2])
items = prepare_mails(parse_contracts(record("FAULT-1")), Settings(subject="fault audit"),
                      AddressBook([Contact("山田 太郎", "audit@example.com")]))
def pause():
    print("checkpoint", flush=True)
    sys.stdin.readline()
class FakeClient:
    def create(self, item, mode):
        if stage == "inside_create": pause()
        return "下書き保存済み"
    def close(self):
        if stage == "after_durable_completion": pause()
def progress(index, status):
    if stage == "before_create" and status == "実行中": pause()
execute_batch(items, "draft", directory / "crash.jsonl", progress, FakeClient)
'''
        for stage in ("before_create", "inside_create", "after_durable_completion"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                root = Path(__file__).resolve().parents[1]
                environment = dict(os.environ)
                # GUI audit runners can append pure-Python dependency paths
                # after interpreter startup. Give the child the same imports.
                import_paths = [str(root / "tests"), str(root), *sys.path,
                                *environment.get("PYTHONPATH", "").split(os.pathsep)]
                environment["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(
                    str(path) for path in import_paths if path))
                process = subprocess.Popen([sys.executable, "-c", script, stage, directory],
                                           cwd=root, env=environment,
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True)
                try:
                    checkpoint = process.stdout.readline().strip()
                    if checkpoint != "checkpoint":
                        if process.poll() is None:
                            process.kill()
                        stdout, stderr = process.communicate(timeout=5)
                        self.fail(f"Child failed before {stage}: exit={process.returncode}; "
                                  f"stdout={checkpoint + stdout!r}; stderr={stderr!r}")
                    process.kill()
                    process.communicate(timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=5)
                    process.stdin.close()
                    process.stdout.close()
                    process.stderr.close()
                logs = Path(directory)
                with OperationLock(logs):
                    pass
                attempted, unrelated = self.items(), self.items("FAULT-NEW")
                apply_history(attempted + unrelated, "draft", logs)
                self.assertFalse(attempted[0].included)
                expected = "下書き保存済み" if stage == "after_durable_completion" else "要確認"
                self.assertIn(expected, attempted[0].status)
                self.assertEqual(unrelated[0].status, "未実行")
                factory = Mock()
                with self.assertRaises(InputError):
                    execute_batch(self.items(), "draft", logs / "retry.jsonl", lambda *_: None, factory)
                factory.assert_not_called()

    def test_progress_failure_before_create_blocks_unsafe_retry_without_calling_com(self):
        client = Mock()
        with self.assertRaisesRegex(RuntimeError, "UI unavailable"):
            execute_batch(self.items(), "draft", self.directory / "run.jsonl",
                          Mock(side_effect=RuntimeError("UI unavailable")), lambda: client)
        client.create.assert_not_called()
        client.close.assert_called_once()
        attempted = self.items()
        apply_history(attempted, "draft", self.directory)
        self.assertFalse(attempted[0].included)
        self.assertIn("要確認", attempted[0].status)

    def test_progress_failure_after_create_does_not_allow_second_outlook_operation(self):
        client = Mock()
        client.create.return_value = "下書き保存済み"
        progress = Mock(side_effect=[None, RuntimeError("UI unavailable after save")])
        with self.assertRaisesRegex(RuntimeError, "after save"):
            execute_batch(self.items(), "draft", self.directory / "run.jsonl", progress, lambda: client)
        client.create.assert_called_once()
        client.close.assert_called_once()
        factory = Mock()
        with self.assertRaises(InputError):
            execute_batch(self.items(), "draft", self.directory / "retry.jsonl", lambda *_: None, factory)
        factory.assert_not_called()

    def test_post_com_fsync_failure_still_prevents_second_operation(self):
        client = Mock()
        client.create.return_value = "下書き保存済み"
        real_fsync = os.fsync
        calls = 0

        def fail_completion(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("completion durability unknown")
            return real_fsync(fd)

        with patch("bulk_mailer.outlook.os.fsync", side_effect=fail_completion):
            with self.assertRaisesRegex(OSError, "durability unknown"):
                execute_batch(self.items(), "draft", self.directory / "run.jsonl", lambda *_: None,
                              lambda: client)
        client.create.assert_called_once()
        factory = Mock()
        with self.assertRaises(InputError):
            execute_batch(self.items(), "draft", self.directory / "retry.jsonl", lambda *_: None, factory)
        factory.assert_not_called()

    def test_contacts_replace_permission_failure_retains_previous_json(self):
        path = self.directory / "contacts.json"
        previous = AddressBook([Contact("旧 氏名", "old@example.com")])
        save_contacts(previous, path, "old.xlsx")
        before = path.read_bytes()
        with patch.object(Path, "replace", side_effect=PermissionError("target opened by another process")):
            with self.assertRaises(PermissionError):
                save_contacts(AddressBook([Contact("新 氏名", "new@example.com")]), path, "new.xlsx")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(load_contacts(path), (previous, "old.xlsx"))
        self.assertEqual(list(self.directory.glob("*.tmp")), [])

    def test_settings_replace_permission_failure_retains_previous_json(self):
        path = self.directory / "settings.json"
        previous = Settings(subject="保存済み")
        save_settings(previous, path)
        before = path.read_bytes()
        with patch.object(Path, "replace", side_effect=PermissionError("target opened by another process")):
            with self.assertRaises(PermissionError):
                save_settings(Settings(subject="保存できない"), path)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(load_settings(path), previous)
        self.assertEqual(list(self.directory.glob("*.tmp")), [])

    def test_windows_lock_branch_locks_first_byte_and_closes_handle(self):
        lock = OperationLock(self.directory)
        calls = []

        def locking(fd, operation, size):
            self.assertEqual(lock.file.tell(), 0)
            self.assertEqual(os.fstat(fd).st_size, 1)
            calls.append((operation, size))

        fake = SimpleNamespace(LK_NBLCK=912, locking=locking)
        with patch.dict(sys.modules, {"msvcrt": fake}), patch("bulk_mailer.outlook.os.name", "nt"):
            with lock:
                handle = lock.file
                self.assertFalse(handle.closed)
        self.assertEqual(calls, [(912, 1)])
        self.assertTrue(handle.closed)
        self.assertIsNone(lock.file)

    def test_windows_lock_conflict_closes_handle_and_never_enters_body(self):
        lock = OperationLock(self.directory)
        fake = SimpleNamespace(LK_NBLCK=912, locking=Mock(side_effect=OSError("sharing violation")))
        with patch.dict(sys.modules, {"msvcrt": fake}), patch("bulk_mailer.outlook.os.name", "nt"):
            with self.assertRaisesRegex(InputError, "ロックできません"):
                with lock:
                    self.fail("Conflicting lock must not enter protected section")
        self.assertIsNone(lock.file)
        with OperationLock(self.directory):
            pass


if __name__ == "__main__":
    unittest.main()
