import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from bulk_mailer.core import AddressBook, Contact, InputError, Settings, parse_contracts, prepare_mails
from bulk_mailer.outlook import OutlookClient, execute_batch
from test_core import record


class OutlookTests(unittest.TestCase):
    def make_items(self, count=1):
        contracts = parse_contracts("\n\n".join(record(f"K-{number:03d}") for number in range(count)))
        items = prepare_mails(contracts, Settings(subject="共通件名", cc="cc@example.com"),
                              AddressBook([Contact("山田 太郎", "yamada@example.com")]))
        return items

    def test_outlook_draft_and_send_paths(self):
        for mode in ("draft", "send"):
            with self.subTest(mode=mode):
                client = OutlookClient.__new__(OutlookClient)
                client.application = Mock()
                mail = client.application.CreateItem.return_value
                mail.Recipients.ResolveAll.return_value = True
                to, cc = Mock(), Mock()
                mail.Recipients.Add.side_effect = [to, cc]
                item = self.make_items()[0]
                client.create(item, mode)
                self.assertEqual(to.Type, 1)
                self.assertEqual(cc.Type, 2)
                self.assertEqual([call.args[0] for call in mail.Recipients.Add.call_args_list],
                                 ["yamada@example.com", "cc@example.com"])
                self.assertEqual(mail.Subject, "共通件名")
                self.assertEqual(mail.Body, item.body)
                if mode == "draft":
                    mail.Save.assert_called_once()
                    mail.Send.assert_not_called()
                else:
                    mail.Send.assert_called_once()
                    mail.Save.assert_not_called()

    def test_unresolved_recipient_never_saves_or_sends(self):
        client = OutlookClient.__new__(OutlookClient)
        client.application = Mock()
        mail = client.application.CreateItem.return_value
        mail.Recipients.ResolveAll.return_value = False
        with self.assertRaises(InputError):
            client.create(self.make_items()[0], "send")
        mail.Save.assert_not_called()
        mail.Send.assert_not_called()

    def test_all_items_prevalidated_before_outlook(self):
        items = self.make_items(2)
        items[1].to = "invalid"
        factory = Mock()
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(InputError):
            execute_batch(items, "send", Path(directory) / "log.jsonl", lambda *_: None, factory)
        factory.assert_not_called()

    def test_success_is_journaled_and_cannot_repeat(self):
        items = self.make_items(2)
        client = Mock()
        client.create.return_value = "下書き保存済み"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.jsonl"
            execute_batch(items, "draft", path, lambda *_: None, lambda: client)
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["status"] for row in records], ["開始", "下書き保存済み", "開始", "下書き保存済み"])
            self.assertEqual(client.create.call_count, 2)
            client.close.assert_called_once()
            with self.assertRaises(InputError):
                execute_batch(items, "draft", path, lambda *_: None, lambda: client)
            self.assertEqual(client.create.call_count, 2)

    def test_failure_stops_and_keeps_remaining_items_unprocessed(self):
        items = self.make_items(3)
        client = Mock()
        client.create.side_effect = ["送信要求済み", RuntimeError("COM通信エラー")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.jsonl"
            with self.assertRaisesRegex(InputError, "処理を停止"):
                execute_batch(items, "send", path, lambda *_: None, lambda: client)
            self.assertEqual([item.status for item in items], ["送信要求済み", "要確認（再実行不可）", "未実行"])
            self.assertEqual(client.create.call_count, 2)
            self.assertIn("要確認", path.read_text(encoding="utf-8"))
            client.close.assert_called_once()
            with self.assertRaises(InputError):
                items[1].validate()

    def test_journal_write_failure_prevents_outlook_operation(self):
        items = self.make_items()
        factory = Mock()
        with tempfile.TemporaryDirectory() as directory:
            # A directory cannot be opened as an append-only journal file.
            with self.assertRaises(OSError):
                execute_batch(items, "send", Path(directory), lambda *_: None, factory)
        factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
