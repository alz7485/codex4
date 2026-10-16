"""Company insertion and EOF-only optional footer regression tests."""
import unittest

from bulk_mailer.core import AddressBook, Contact, InputError, Settings, parse_contracts, prepare_mails
from test_core import record


def required_record(number="K-001", name="山田 太郎"):
    return record(number=number, name=name).split("\n不要行1", 1)[0]


class TextFormatTests(unittest.TestCase):
    def test_company_precedes_office_without_shifting_other_fields(self):
        values = parse_contracts(required_record())[0].values
        self.assertEqual(values["会社名"], "サンプル受入株式会社")
        self.assertEqual(values["事業所名"], "東京事業所")
        self.assertEqual(values["部署名"], "開発部")
        self.assertEqual(values["氏名"], "山田 太郎")
        self.assertEqual(values["派遣元"], "サンプル派遣株式会社")
        self.assertEqual(values["契約承認状態"], "承認済み")

    def test_final_record_accepts_each_truncated_footer_prefix(self):
        footer = "\n不要行1\n\n不要行2"
        for length in range(len(footer) + 1):
            for ending in ("", "\n", "\n\n　\n"):
                with self.subTest(length=length, ending=ending):
                    parsed = parse_contracts(required_record() + footer[:length] + ending)
                    self.assertEqual(len(parsed), 1)
                    self.assertEqual(parsed[0].values["契約承認状態"], "承認済み")

    def test_only_final_person_may_omit_footer_in_multiple_records(self):
        source = record() + "\n\n" + required_record("K-002", "佐藤 花子")
        source = "\ufeff\n\n" + source.replace("\n", "\r\n") + "\r\n　\r\n"
        parsed = parse_contracts(source)
        self.assertEqual([item.values["管理番号"] for item in parsed], ["K-001", "K-002"])
        self.assertEqual([item.values["氏名"] for item in parsed], ["山田 太郎", "佐藤 花子"])

    def test_intermediate_missing_footer_is_rejected(self):
        for tail in ("", "\n不要行1", "\n不要行1\n", "\n不要行1\n\n"):
            with self.subTest(tail=tail), self.assertRaises(InputError):
                parse_contracts(required_record() + tail + "\n\n" + required_record("K-002", "佐藤 花子"))

    def test_final_used_fields_are_still_required(self):
        source = required_record()
        blocks = source.split("\n\n")
        for count in range(1, len(blocks)):
            with self.subTest(count=count), self.assertRaises(InputError):
                parse_contracts("\n\n".join(blocks[:count]))

    def test_extra_blanks_cannot_mask_a_missing_final_required_field(self):
        # The remaining unused line must not become an approval status after
        # deleting the approval-status block and its immediately following line.
        source = record().replace("承認済み\n不要行1", "")
        with self.assertRaises(InputError):
            parse_contracts(source)

    def test_company_can_be_inserted_into_mail_body(self):
        settings = Settings(subject="共通件名", template="{会社名}\n{事業所名}\n{氏名}")
        items = prepare_mails(parse_contracts(required_record()), settings,
                              AddressBook([Contact("山田太郎", "yamada@example.com")]))
        self.assertEqual(items[0].body, "サンプル受入株式会社\n東京事業所\n山田 太郎")

    def test_final_footer_exemption_does_not_allow_extra_trailing_records(self):
        for suffix in ("\n\nK-002", "\n\nK-002\n\n2026/11/01 - 2027/03/31"):
            with self.subTest(suffix=suffix), self.assertRaises(InputError):
                parse_contracts(record() + suffix)
