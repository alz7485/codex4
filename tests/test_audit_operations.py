"""Failure-injection audit; all Outlook calls are mocks, never live sends."""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bulk_mailer.core import AddressBook, Contact, InputError, Settings, parse_contracts, prepare_mails
from bulk_mailer.outlook import OperationLock, apply_history, execute_batch
from test_core import record


class OperationsAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.log = self.directory / "run.jsonl"

    def make_items(self, count=1):
        contracts = parse_contracts("\n\n".join(record(f"AUDIT-{i}") for i in range(count)))
        items = prepare_mails(contracts, Settings(subject="監査用件名"),
                              AddressBook([Contact("山田 太郎", "audit@example.com")]))
        return items

    def client(self):
        client = Mock()
        client.create.return_value = "送信要求済み"
        return client

    def test_fsync_failure_before_outlook_never_sends(self):
        client = self.client()
        items = self.make_items(2)
        with tempfile.TemporaryDirectory() as directory:
            with patch("bulk_mailer.outlook.os.fsync", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    execute_batch(items, "send", Path(directory) / "log.jsonl", lambda *_: None, lambda: client)
        client.create.assert_not_called()
        client.close.assert_called_once()
        self.assertEqual([item.status for item in items], ["未実行", "未実行"])

    def test_factory_failure_keeps_all_rows_retryable_and_closes_journal(self):
        items = self.make_items(2)
        journal = Mock()
        with patch("bulk_mailer.outlook.Journal", return_value=journal):
            with self.assertRaisesRegex(RuntimeError, "接続不能"):
                execute_batch(items, "send", self.log, lambda *_: None,
                              Mock(side_effect=RuntimeError("接続不能")))
        journal.close.assert_called_once()
        journal.write.assert_not_called()
        self.assertEqual([item.status for item in items], ["未実行", "未実行"])

    def test_disk_failure_after_first_success_stops_remaining_rows(self):
        items = self.make_items(3)
        client = self.client()
        journal = Mock()
        journal.write.side_effect = [None, OSError("disk full")]
        with patch("bulk_mailer.outlook.Journal", return_value=journal):
            with self.assertRaises(OSError):
                execute_batch(items, "send", self.log, lambda *_: None, lambda: client)
        client.create.assert_called_once()
        self.assertEqual([item.status for item in items], ["送信要求済み", "未実行", "未実行"])

    def test_com_failure_and_disk_failure_preserves_outlook_reconciliation_guidance(self):
        items = self.make_items(2)
        client = self.client()
        client.create.side_effect = RuntimeError("RPC timeout after Send")
        journal = Mock()
        journal.write.side_effect = [None, OSError("disk full")]
        with patch("bulk_mailer.outlook.Journal", return_value=journal):
            with self.assertRaises(InputError) as caught:
                execute_batch(items, "send", self.log, lambda *_: None, lambda: client)
        self.assertIn("RPC timeout", str(caught.exception))
        self.assertIn("Outlook", str(caught.exception))
        self.assertEqual([item.status for item in items], ["要確認（再実行不可）", "未実行"])

    def test_cleanup_failure_cannot_skip_journal_close(self):
        client = self.client()
        client.close.side_effect = RuntimeError("CoUninitialize failed")
        journal = Mock()
        with patch("bulk_mailer.outlook.Journal", return_value=journal):
            with self.assertRaises(RuntimeError):
                execute_batch(self.make_items(), "send", self.log, lambda *_: None, lambda: client)
        journal.close.assert_called_once()

    def test_same_object_twice_in_batch_cannot_send_twice(self):
        client = self.client()
        item = self.make_items()[0]
        with tempfile.TemporaryDirectory() as directory:
            try:
                execute_batch([item, item], "send", Path(directory) / "log.jsonl", lambda *_: None, lambda: client)
            except InputError:
                pass
        self.assertLessEqual(client.create.call_count, 1)

    def test_new_list_after_uncertain_result_must_not_silently_resend(self):
        first = self.client()
        first.create.side_effect = RuntimeError("Send returned RPC failure; actual delivery unknown")
        second = self.client()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.jsonl"
            with self.assertRaises(InputError):
                execute_batch(self.make_items(), "send", path, lambda *_: None, lambda: first)
            rows = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]
            self.assertIn("要確認", rows[-1]["status"])
            try:
                execute_batch(self.make_items(), "send", path, lambda *_: None, lambda: second)
            except InputError:
                pass
        second.create.assert_not_called()

    def write_history(self, status="開始", mode="send", number="AUDIT-0"):
        self.log.write_text(json.dumps({"time": "legacy", "management_number": number,
                                       "to": "audit@example.com", "mode": mode,
                                       "status": status, "detail": ""}, ensure_ascii=False) + "\n",
                            encoding="utf-8")

    def test_apply_history_reflects_legacy_complete_and_uncertain_statuses(self):
        for status, mode, display in (("開始", "send", "要確認"),
                                      ("要確認（再実行不可）", "send", "要確認"),
                                      ("送信要求済み", "send", "送信要求済み"),
                                      ("下書き保存済み", "draft", "下書き保存済み")):
            with self.subTest(status=status):
                self.write_history(status, mode)
                items = self.make_items(2)
                apply_history(items, mode, self.directory)
                self.assertEqual(items[0].status, f"履歴あり（{display}）")
                self.assertFalse(items[0].included)
                self.assertEqual(items[1].status, "未実行")
                with self.assertRaises(InputError):
                    items[0].validate()

    def test_draft_history_allows_send_but_blocks_another_draft(self):
        self.write_history("下書き保存済み", "draft")
        items = self.make_items()
        apply_history(items, "send", self.directory)
        self.assertEqual(items[0].status, "未実行")
        client = self.client()
        execute_batch(items, "send", self.directory / "send.jsonl", lambda *_: None, lambda: client)
        client.create.assert_called_once()
        with self.assertRaises(InputError):
            execute_batch(self.make_items(), "draft", self.directory / "draft.jsonl", lambda *_: None,
                          lambda: client)

    def test_corrupt_history_fails_closed_without_starting_or_mutating_items(self):
        factory = Mock()
        for data in (b"{broken", b"[]\n", b'{}\n', b'\xff\xfe',
                     b'{"management_number":"AUDIT-0","mode":"send","status":"unknown"}\n'):
            with self.subTest(data=data):
                self.log.write_bytes(data)
                items = self.make_items()
                with self.assertRaises(InputError):
                    apply_history(items, "send", self.directory)
                self.assertEqual(items[0].status, "未実行")
                with self.assertRaises(InputError):
                    execute_batch(items, "send", self.directory / "new.jsonl", lambda *_: None, factory)
                self.assertFalse((self.directory / "new.jsonl").exists())
        factory.assert_not_called()

    def test_all_history_validated_before_new_journal_or_outlook(self):
        self.write_history()
        items = self.make_items(2)
        items.reverse()  # unseen contract first; seen contract second
        factory = Mock()
        path = self.directory / "new.jsonl"
        with self.assertRaises(InputError):
            execute_batch(items, "send", path, lambda *_: None, factory)
        self.assertFalse(path.exists())
        factory.assert_not_called()

    def test_process_lock_released_after_failed_operation(self):
        client = self.client()
        client.create.side_effect = RuntimeError("COM failure")
        with self.assertRaises(InputError):
            execute_batch(self.make_items(), "send", self.log, lambda *_: None, lambda: client)
        with OperationLock(self.directory):
            pass

    def test_os_lock_excludes_a_separate_python_process(self):
        script = ("import sys\nfrom pathlib import Path\n"
                  "from bulk_mailer.outlook import OperationLock\n"
                  "with OperationLock(Path(sys.argv[1])):\n"
                  "    print('locked', flush=True)\n"
                  "    sys.stdin.readline()\n")
        process = subprocess.Popen([sys.executable, "-c", script, str(self.directory)],
                                   cwd=Path(__file__).resolve().parents[1],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            with self.assertRaises(InputError):
                apply_history(self.make_items(), "send", self.directory)
            process.communicate("release\n", timeout=5)
            self.assertEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
            process.stdout.close()
            process.stderr.close()
        with OperationLock(self.directory):
            pass

    def test_cleanup_failures_do_not_replace_primary_com_failure(self):
        client = self.client()
        client.create.side_effect = RuntimeError("PRIMARY COM failure")
        client.close.side_effect = RuntimeError("cleanup failure")
        journal = Mock()
        journal.close.side_effect = OSError("journal close failure")
        with patch("bulk_mailer.outlook.Journal", return_value=journal):
            with self.assertRaisesRegex(InputError, "PRIMARY COM failure"):
                execute_batch(self.make_items(), "send", self.log, lambda *_: None, lambda: client)
        journal.close.assert_called_once()

    def test_second_instance_cannot_execute_same_contract_while_first_is_in_flight(self):
        entered, release = threading.Event(), threading.Event()
        first, second = self.client(), self.client()
        errors = []

        def progress(*_):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("audit synchronization timed out")

        with tempfile.TemporaryDirectory() as directory:
            def worker():
                try:
                    execute_batch(self.make_items(), "send", Path(directory) / "first.jsonl", progress,
                                  lambda: first)
                except Exception as error:
                    errors.append(error)

            thread = threading.Thread(target=worker)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                try:
                    execute_batch(self.make_items(), "send", Path(directory) / "second.jsonl",
                                  lambda *_: None, lambda: second)
                except InputError:
                    pass
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
        second.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
