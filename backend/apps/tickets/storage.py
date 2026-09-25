"""
Хавсралт файлуудыг MEDIA_ROOT-оос (нийтэд нээлттэй /media/) гадна хадгална —
зөвхөн нэвтэрсэн хэрэглэгч `tickets:attachment_download` view-ээр татна.
"""
from django.conf import settings
from django.core.files.storage import FileSystemStorage


def private_storage():
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)
