"""
Хавсралтын бизнес дүрмүүд — "код ажилласан уу" биш "зөв ажилласан уу"-г шалгана.

Дүрэм (settings.ATTACHMENT_*): зөвхөн зөвшөөрөгдсөн өргөтгөлтэй (зураг, баримт, zip),
10MB-аас ихгүй файл хавсаргана. Бусдыг хүлээж авахгүй.
"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.tickets.forms import AttachmentForm
from apps.tickets.models import Attachment, Ticket
from apps.tickets.permissions import ROLE_DEV

from .helpers import make_project, make_routed_category, make_user

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
    b"\x00\x00\x00IEND\xaeB`\x82"
)


def upload(name, content=b"data"):
    return AttachmentForm(files={"file": SimpleUploadedFile(name, content)})


class AttachmentFileTypeTests(TestCase):
    # ------------------------------------------------------------ зөв утга

    def test_images_are_accepted(self):
        """[ATT-01] Images (png, jpg, jpeg, gif, webp) are accepted"""
        for name in ("a.png", "a.jpg", "a.jpeg", "a.gif", "a.webp"):
            with self.subTest(name=name):
                self.assertTrue(upload(name, PNG_BYTES).is_valid())

    def test_documents_are_accepted(self):
        """[ATT-01] Documents (pdf, docx, xlsx, txt, log, zip, ...) are accepted"""
        for name in ("a.pdf", "a.docx", "a.xlsx", "a.pptx", "a.txt", "a.log", "a.csv", "a.zip"):
            with self.subTest(name=name):
                self.assertTrue(upload(name).is_valid())

    def test_extension_is_case_insensitive(self):
        """[ATT-01] Uppercase extension (PHOTO.PNG) is accepted"""
        self.assertTrue(upload("PHOTO.PNG", PNG_BYTES).is_valid())

    # ------------------------------------------------------------ буруу утга

    def test_executables_and_scripts_are_rejected(self):
        """[ATT-02] Executables and scripts (exe, sh, bat, php, js, py) are rejected"""
        for name in ("a.exe", "a.sh", "a.bat", "a.php", "a.js", "a.py", "a.msi", "a.apk"):
            with self.subTest(name=name):
                form = upload(name)
                self.assertFalse(form.is_valid())
                self.assertIn("зөвшөөрөгдөхгүй", str(form.errors))

    def test_html_and_svg_are_rejected(self):
        """[ATT-02] Browser-executable html and svg files are rejected"""
        for name in ("a.html", "a.htm", "a.svg"):
            with self.subTest(name=name):
                self.assertFalse(upload(name).is_valid())

    def test_double_extension_is_judged_by_last_one(self):
        """[ATT-03] Double extension such as photo.png.exe is rejected"""
        self.assertFalse(upload("photo.png.exe").is_valid())

    def test_file_without_extension_is_rejected(self):
        """[ATT-03] File without an extension is rejected"""
        self.assertFalse(upload("Makefile").is_valid())

    def test_file_content_must_match_extension(self):
        """[ATT-04] File named .png whose content is not an image (e.g. HTML) is rejected"""
        self.assertFalse(upload("evil.png", b"<html><script>alert(1)</script></html>").is_valid())


@override_settings(ATTACHMENT_MAX_SIZE_MB=1)
class AttachmentSizeTests(TestCase):
    ONE_MB = 1024 * 1024

    def test_file_at_limit_is_accepted(self):
        """[ATT-05] File exactly at the size limit (1MB) is accepted"""
        self.assertTrue(upload("a.pdf", b"x" * self.ONE_MB).is_valid())

    def test_file_over_limit_is_rejected(self):
        """[ATT-05] File one byte over the size limit is rejected"""
        form = upload("a.pdf", b"x" * (self.ONE_MB + 1))
        self.assertFalse(form.is_valid())
        self.assertIn("хэтэрсэн", str(form.errors))


class AttachmentUploadPageTests(TestCase):
    """Маягтаас гадна тикетийн хуудсаар бодитоор хавсаргахад дүрэм ажиллаж байгааг шалгана."""

    def setUp(self):
        self.dev = make_user("dev", ROLE_DEV)
        category, _ = make_routed_category(members=[self.dev])
        self.ticket = Ticket.objects.create(
            title="x", description="d", ticket_type="bug", category=category,
            project=make_project(), reported_by=self.dev,
        )
        self.url = reverse("tickets:ticket_detail", args=[self.ticket.pk])
        self.client.force_login(self.dev)
        # Хадгалагдсан файлуудыг тестийн дараа дискнээс устгана (private_media-г бохирдуулахгүй).
        self.addCleanup(
            lambda: [a.file.delete(save=False) for a in Attachment.objects.filter(ticket=self.ticket)]
        )

    def _post(self, name, content=b"data"):
        return self.client.post(
            self.url, {"action": "attachment", "file": SimpleUploadedFile(name, content)}
        )

    def test_allowed_file_is_saved_to_ticket(self):
        """[ATT-06] Allowed file is saved to the ticket with the uploader recorded"""
        self._post("screenshot.png", PNG_BYTES)
        attachment = Attachment.objects.get(ticket=self.ticket)
        self.assertEqual(attachment.uploaded_by, self.dev)

    def test_forbidden_file_is_not_saved(self):
        """[ATT-06] Forbidden file submitted via the page is not saved"""
        self._post("virus.exe")
        self.assertFalse(Attachment.objects.filter(ticket=self.ticket).exists())

    def test_malicious_filename_stays_inside_storage(self):
        """[ATT-08] Filename like "../../evil.png" cannot escape the storage folder"""
        self._post("../../evil.png", PNG_BYTES)
        name = Attachment.objects.get(ticket=self.ticket).file.name
        self.assertTrue(name.startswith("attachments/"))
        self.assertNotIn("..", name)

    def test_download_disposition_by_type(self):
        """[ATT-09] Images/PDF open inline; other types (zip, docx) download only"""
        for name, expected in (("a.png", "inline"), ("a.pdf", "inline"), ("a.zip", "attachment")):
            with self.subTest(file=name):
                self._post(name, PNG_BYTES if name.endswith(".png") else b"data")
                attachment = Attachment.objects.filter(ticket=self.ticket).latest("pk")
                response = self.client.get(reverse("tickets:attachment_download", args=[attachment.pk]))
                self.assertTrue(response["Content-Disposition"].startswith(expected))
                # response.close() нь request_finished-ээр DB холболтыг хаачихна. Харин агуулгыг бүрэн
                # уншихад test client файлыг холболтод хүрэлгүй хаадаг.
                b"".join(response.streaming_content)

    def test_anonymous_user_cannot_upload(self):
        """[ATT-07] Anonymous user cannot upload files"""
        self.client.logout()
        self._post("screenshot.png", PNG_BYTES)
        self.assertFalse(Attachment.objects.filter(ticket=self.ticket).exists())
