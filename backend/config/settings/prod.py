"""Production орчны тохиргоо."""
from .base import *  # noqa

DEBUG = False

# Production-д аюултай default түлхүүрээр асахыг хориглоно — .env-д заавал тохируулна.
SECRET_KEY = env("SECRET_KEY")
if SECRET_KEY.startswith("django-insecure"):
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Production орчинд SECRET_KEY-г .env-д тохируулна уу.")

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"  # prod-д үргэлж SMTP (EMAIL_* — base.py)

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
