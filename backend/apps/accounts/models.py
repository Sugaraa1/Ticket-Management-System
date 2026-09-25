from django.conf import settings
from django.db import models


def avatar_upload_to(instance, filename):
    # Солих бүрт шинэ нэр → хөтөч хуучин зургийг cache-ээс харуулахгүй.
    from uuid import uuid4

    ext = filename.rsplit(".", 1)[-1].lower()
    return f"avatars/user_{instance.user_id}_{uuid4().hex[:8]}.{ext}"


class Profile(models.Model):
    """Хэрэглэгчийн нэмэлт мэдээлэл (одоогоор профайлын зураг)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name="profile", on_delete=models.CASCADE
    )
    avatar = models.ImageField(upload_to=avatar_upload_to, blank=True)

    def __str__(self):
        return f"Profile of {self.user}"
