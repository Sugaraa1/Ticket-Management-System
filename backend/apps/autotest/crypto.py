"""
Тестийн хэрэглэгчийн нууц үгийг шифрлэх (Fernet). Түлхүүрийг SECRET_KEY-ээс гаргана —
SECRET_KEY солигдвол хадгалсан нууц үгийг тайлж чадахгүй тул дахин оруулна.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class DecryptError(ValueError):
    pass


def _fernet():
    digest = hashlib.sha256(f"autotest-account:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(raw):
    return _fernet().encrypt(raw.encode()).decode()


def decrypt(token):
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        raise DecryptError("cannot decrypt")
