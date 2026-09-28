"""
Django-гийн нууц үгийн validator-ууд — мессежийг монголоор (docs/rules.md — AUTH-07).
Django-гийн өөрийн "mn" орчуулга дутуу тул энд давхар бичив; дүрэм нь өөрчлөгдөөгүй.
"""
from django.contrib.auth import password_validation as django_validation
from django.utils.translation import gettext as _


class MinimumLengthValidator(django_validation.MinimumLengthValidator):
    def get_error_message(self):
        return _("Нууц үг хэт богино байна. Дор хаяж %(min_length)s тэмдэгт байх ёстой.") % {
            "min_length": self.min_length
        }

    def get_help_text(self):
        return _("Нууц үг дор хаяж %(min_length)s тэмдэгт байна.") % {"min_length": self.min_length}


class UserAttributeSimilarityValidator(django_validation.UserAttributeSimilarityValidator):
    def get_error_message(self):
        return _("Нууц үг таны %(verbose_name)s-тэй хэт төстэй байна.")

    def get_help_text(self):
        return _("Нууц үг таны нэр, и-мэйл зэрэг хувийн мэдээлэлтэй төстэй байж болохгүй.")


class CommonPasswordValidator(django_validation.CommonPasswordValidator):
    def get_error_message(self):
        return _("Энэ нууц үг хэт түгээмэл байна.")

    def get_help_text(self):
        return _("Түгээмэл хэрэглэгддэг нууц үг байж болохгүй.")


class NumericPasswordValidator(django_validation.NumericPasswordValidator):
    def get_error_message(self):
        return _("Нууц үг зөвхөн тооноос бүрдэж болохгүй.")

    def get_help_text(self):
        return _("Нууц үг зөвхөн тооноос бүрдэж болохгүй.")
