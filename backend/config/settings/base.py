"""
Бүх орчинд нийтлэг Django тохиргоо.
Орчноос хамааралтай утгуудыг .env файлаас уншина (django-environ ашиглана).
"""
from pathlib import Path

import environ

# backend/ -г BASE_DIR болгоно (config/settings/base.py -> 3 түвшин дээш)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="django-insecure-change-me-in-production")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Local apps
    "apps.core",
    "apps.accounts",
    "apps.categories",
    "apps.projects",
    "apps.tickets",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.user_roles_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database ---
# .env дотор DATABASE_URL=postgres://user:pass@host:5432/dbname гэж заана.
# Заагаагүй бол sqlite-аар локал дээр шууд ажиллана.
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "mn"
LANGUAGES = [
    ("mn", "Монгол"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Asia/Ulaanbaatar"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth ---
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "tickets:dashboard"
LOGOUT_REDIRECT_URL = "login"

# --- Email (жагсаалт: dev дээр console, prod дээр smtp) ---
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@ticket-system.local")

# --- SLA (Service Level Agreement) ---
# Jira Service Management-ийн загварчлалтай адил 2 тусдаа SLA metric ашиглана:
#   1. Time to First Response  — эхний хариу өгөх дээд хугацаа
#   2. Time to Resolution      — бүрэн шийдвэрлэх дээд хугацаа
# Хоёулаа Priority-с хамаарч ticket үүсэх мөчид автоматаар тооцоологдоно
# (apps.tickets.models.Ticket.save()).
SLA_HOURS_BY_PRIORITY = {  # Time to Resolution
    "critical": 4,     # 4 цаг
    "high": 24,        # 1 өдөр
    "medium": 72,      # 3 өдөр
    "low": 168,        # 7 өдөр
}
SLA_FIRST_RESPONSE_HOURS_BY_PRIORITY = {  # Time to First Response
    "critical": 1,     # 1 цаг
    "high": 4,         # 4 цаг
    "medium": 8,       # 8 цаг
    "low": 24,         # 1 өдөр
}

# SLA хугацааны хэдэн хувь нь өнгөрөхөд "анхааруулга" мэдэгдэл илгээхийг заана
# (жишээ нь 0.8 = хугацааны 80% өнгөрөхөд, эцсийн хугацаанаас өмнө сануулна).
# Хоёр metric-т аль алинд нь адилхан хамаарна.
# apps.tickets.management.commands.check_sla_deadlines-ээр ашиглагдана.
SLA_WARNING_THRESHOLD = 0.8

# --- Automation rule: идэвхгүй (stale) ticket-д давтан сануулга ---
# Ticket дээр сүүлийн идэвх (comment/attachment/status шилжилт)-ээс хойш энэ
# хэдэн цагийн турш юу ч болоогүй бол хариуцагчид (эсвэл байхгүй бол Team
# Lead-д) сануулга илгээнэ; идэвх гарахгүй л бол ижил хугацаа тутамд ДАХИН
# давтан илгээгдэнэ (Zendesk/Jira-ийн "time-based automation"-той адил).
# apps.tickets.management.commands.check_stale_tickets-ээр ашиглагдана.
STALE_TICKET_REMINDER_HOURS = 48
