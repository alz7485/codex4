import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from bulk_mailer.core import InputError, Settings, AddressBook, Contact, parse_contracts, prepare_mails
from bulk_mailer.outlook import OutlookClient
from test_core import record

class SenderTests(unittest.TestCase):
    def test_setting_reaches_mail(self):
        items=prepare_mails(parse_contracts(record()),Settings(subject='通知',sender='from@example.com'),AddressBook())
        self.assertEqual(items[0].sender,'from@example.com')

    def test_account_match_and_draft(self):
        account=SimpleNamespace(SmtpAddress='FROM@example.com')
        client=OutlookClient.__new__(OutlookClient)
        client.application=Mock()
        client.application.Session.Accounts=[account]
        client.select_sender('from@example.com')
        item=Mock(sender='from@example.com',to='to@example.com',cc=(),subject='通知',body='本文')
        client.create(item,'draft')
        mail=client.application.CreateItem.return_value
        self.assertIs(mail.SendUsingAccount,account)
        mail.Save.assert_called_once()
        mail.Send.assert_not_called()

    def test_missing_or_duplicate_account_stops(self):
        client=OutlookClient.__new__(OutlookClient)
        account=SimpleNamespace(SmtpAddress='from@example.com')
        for accounts in ([],[account,account]):
            client.application=Mock()
            client.application.Session.Accounts=accounts
            with self.assertRaises(InputError):client.select_sender('from@example.com')
            client.application.CreateItem.assert_not_called()

    def test_invalid_sender_setting(self):
        with self.assertRaises(InputError):Settings(sender='bad').validate()
