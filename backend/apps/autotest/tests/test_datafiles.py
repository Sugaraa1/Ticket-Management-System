from django.test import SimpleTestCase, override_settings

from apps.autotest.datafiles import (
    DataFileError, fill_placeholders, judge, parse_expected, placeholder_values, read_rows, suggest_mapping,
)

from .helpers import csv_upload, xlsx_upload


class ReadRowsTests(SimpleTestCase):
    def test_xlsx_rows_keep_excel_line_numbers_and_skip_blank_rows(self):
        upload = xlsx_upload([
            ["email", "phone"],
            ["a@mail.mn", 99112233],
            [None, None],
            ["b@mail.mn", None],
        ])
        columns, rows = read_rows(upload, upload.name)
        self.assertEqual(columns, ["email", "phone"])
        self.assertEqual(rows, [
            (2, {"email": "a@mail.mn", "phone": "99112233"}),
            (4, {"email": "b@mail.mn", "phone": ""}),
        ])

    def test_csv_with_semicolon_and_bom(self):
        upload = csv_upload("﻿email;password\nbat@mail.mn;Pass1\n")
        columns, rows = read_rows(upload, upload.name)
        self.assertEqual(columns, ["email", "password"])
        self.assertEqual(rows[0][1]["password"], "Pass1")

    def test_duplicate_columns_rejected(self):
        upload = csv_upload("email,email\na,b\n")
        with self.assertRaisesMessage(DataFileError, "Давхардсан"):
            read_rows(upload, upload.name)

    def test_header_only_rejected(self):
        upload = csv_upload("email,password\n")
        with self.assertRaises(DataFileError):
            read_rows(upload, upload.name)

    def test_other_extensions_rejected(self):
        upload = csv_upload("email\na\n", name="users.txt")
        with self.assertRaises(DataFileError):
            read_rows(upload, upload.name)

    @override_settings(AUTOTEST_MAX_ROWS=2)
    def test_row_limit(self):
        upload = csv_upload("email\na\nb\nc\n")
        with self.assertRaisesMessage(DataFileError, "хамгийн ихдээ 2"):
            read_rows(upload, upload.name)


class ExpectedTests(SimpleTestCase):
    def test_parse_expected(self):
        self.assertEqual(parse_expected("амжилттай"), ("success", ""))
        self.assertEqual(parse_expected("Алдаа: И-мэйл буруу"), ("error", "И-мэйл буруу"))
        self.assertEqual(parse_expected("fail"), ("error", ""))
        self.assertEqual(parse_expected(""), ("", ""))
        self.assertEqual(parse_expected("Тавтай морил"), (None, "Тавтай морил"))

    def test_judge(self):
        self.assertEqual(judge("", "", "success", ""), "recorded")
        self.assertEqual(judge("success", "", "success", ""), "pass")
        self.assertEqual(judge("error", "", "success", ""), "fail")
        self.assertEqual(judge("success", "", "unknown", ""), "fail")
        self.assertEqual(judge("error", "буруу", "error", "И-мэйл  БУРУУ байна"), "pass")
        self.assertEqual(judge("error", "буруу", "error", "Нууц үг богино"), "fail")

    def test_placeholders(self):
        first = fill_placeholders("test{{random}}@mail.mn", 3)
        second = fill_placeholders("test{{ random }}@mail.mn", 3)
        self.assertRegex(first, r"^test[0-9a-f]{6}@mail\.mn$")
        self.assertNotEqual(first, second)
        self.assertEqual(fill_placeholders("row{{row}}", 7), "row7")

    def test_placeholders_are_shared_within_a_row(self):
        """Нэг мөрийн "нууц үг" ба "нууц үг давтах" нүдэнд {{random}} ижил утгатай байна."""
        values = placeholder_values(3)
        self.assertEqual(fill_placeholders("P{{random}}", 3, values), fill_placeholders("P{{random}}", 3, values))


class SuggestMappingTests(SimpleTestCase):
    def test_matches_by_label_synonym_and_name(self):
        fields = [
            {"label": "Имэйл хаяг", "name": "user_email", "kind": "email"},
            {"label": "Нууц үг", "name": "pwd", "kind": "password"},
            {"label": "Гар утас", "name": "mobile", "kind": "text"},
            {"label": "Үйлчилгээний нөхцөл", "kind": "checkbox", "required": True},
            {"label": "Хот", "kind": "select"},
        ]
        mapped = suggest_mapping(fields, ["Тайлбар", "email", "password", "phone"])
        self.assertEqual([(f["source"], f["value"]) for f in mapped], [
            ("column", "email"),
            ("column", "password"),
            ("column", "phone"),
            ("check", ""),
            ("skip", ""),
        ])

    def test_column_is_used_once(self):
        fields = [{"label": "Нууц үг"}, {"label": "password"}]
        mapped = suggest_mapping(fields, ["password"])
        self.assertEqual([f["source"] for f in mapped], ["column", "skip"])


class BaseUrlValidatorTests(SimpleTestCase):
    def test_accepts_single_label_hosts_like_docker_services(self):
        from apps.autotest.models import validate_base_url
        for url in ["http://web:8000", "http://web", "https://staging.shop.mn", "http://localhost:8000/x"]:
            validate_base_url(url)

    def test_rejects_bad_urls(self):
        from django.core.exceptions import ValidationError

        from apps.autotest.models import validate_base_url
        for url in ["web:8000", "ftp://web", "http://", "http://web:99999", "http://-web-"]:
            with self.assertRaises(ValidationError, msg=url):
                validate_base_url(url)
