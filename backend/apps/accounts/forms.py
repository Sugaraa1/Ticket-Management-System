from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group, User
from django.utils.translation import gettext_lazy as _

from apps.tickets.permissions import ROLE_ADMIN, ROLE_DEV, ROLE_PM, ROLE_QA

ROLE_CHOICES = [
    (ROLE_DEV, "Developer"),
    (ROLE_QA, "QA Tester"),
    (ROLE_PM, "Project Manager"),
    (ROLE_ADMIN, "Admin"),
]


class UserCreateForm(UserCreationForm):
    first_name = forms.CharField(label=_("Нэр"), max_length=150, required=False)
    last_name = forms.CharField(label=_("Овог"), max_length=150, required=False)
    email = forms.EmailField(
        label=_("И-мэйл"),
        required=False,
        help_text=_("Заавал биш — гэхдээ мэйл мэдэгдэл болон \"Нууц үгээ мартсан\" ажиллахад хэрэгтэй."),
    )
    role = forms.ChoiceField(label=_("Эрх (role)"), choices=ROLE_CHOICES)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            field.widget.attrs.setdefault("class", css)

    def clean_email(self):
        email = self.cleaned_data["email"]
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("Энэ и-мэйлээр бүртгэлтэй хэрэглэгч байна."))
        return email

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            group, _created = Group.objects.get_or_create(name=self.cleaned_data["role"])
            user.groups.add(group)
        return user


class UserEditForm(forms.ModelForm):
    """Admin хэрэглэгчийн мэдээлэл, эрх, (сонголтоор) нууц үгийг засна."""

    role = forms.ChoiceField(label=_("Эрх (role)"), choices=ROLE_CHOICES)
    new_password1 = forms.CharField(
        label=_("Шинэ нууц үг"), required=False, strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=_("Солихгүй бол хоосон үлдээнэ үү."),
    )
    new_password2 = forms.CharField(
        label=_("Шинэ нууц үг (давтах)"), required=False, strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "is_active")
        labels = {
            "first_name": _("Нэр"), "last_name": _("Овог"), "email": _("И-мэйл"),
            "is_active": _("Идэвхтэй (нэвтрэх эрхтэй)"),
        }
        help_texts = {
            "is_active": _("Идэвхгүй болговол нэвтэрч чадахгүй, ticket оноогдохгүй; түүх нь хадгалагдана."),
        }

    def __init__(self, *args, editor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.editor = editor
        current = [name for name, _label in ROLE_CHOICES
                   if self.instance.groups.filter(name=name).exists()]
        # Олон эрхтэй бол хамгийн өндрийг нь сонгоно (ROLE_CHOICES өсөх дарааллаар).
        if current:
            self.fields["role"].initial = current[-1]
        if editor == self.instance:
            del self.fields["is_active"]  # өөрийгөө идэвхгүй болгож түгжихгүй
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                css = "form-check-input"
                field.widget.attrs.setdefault("role", "switch")
            elif isinstance(field.widget, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            field.widget.attrs.setdefault("class", css)

    def clean_email(self):
        email = self.cleaned_data["email"]
        # И-мэйл заавал биш — хоосон бол давхцал шалгахгүй.
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Энэ и-мэйлээр бүртгэлтэй хэрэглэгч байна."))
        return email

    def clean_role(self):
        role = self.cleaned_data["role"]
        if self.editor == self.instance and role != ROLE_ADMIN and not self.instance.is_superuser:
            raise forms.ValidationError(_("Өөрийнхөө Admin эрхийг хасах боломжгүй."))
        return role

    def clean(self):
        from django.contrib.auth import password_validation

        cleaned = super().clean()
        p1, p2 = cleaned.get("new_password1"), cleaned.get("new_password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("new_password2", _("Нууц үг таарахгүй байна."))
            else:
                try:
                    password_validation.validate_password(p1, self.instance)
                except forms.ValidationError as error:
                    self.add_error("new_password1", error)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("new_password1"):
            user.set_password(self.cleaned_data["new_password1"])
        if commit:
            user.save()
            role_names = [name for name, _label in ROLE_CHOICES]
            user.groups.remove(*Group.objects.filter(name__in=role_names))
            group, _created = Group.objects.get_or_create(name=self.cleaned_data["role"])
            user.groups.add(group)
        return user


AVATAR_MAX_MB = 5
AVATAR_SIZE = 256


class AvatarForm(forms.Form):
    avatar = forms.ImageField(label=_("Профайлын зураг"))

    def clean_avatar(self):
        image = self.cleaned_data["avatar"]
        if image.size > AVATAR_MAX_MB * 1024 * 1024:
            raise forms.ValidationError(
                _("Зургийн хэмжээ %(max)sMB-аас хэтэрсэн байна.") % {"max": AVATAR_MAX_MB}
            )
        return image


def square_avatar(uploaded):
    """Зургийг голоос нь дөрвөлжин тайрч 256x256 PNG болгоно (файл жижиг, үргэлж дугуй)."""
    from io import BytesIO

    from django.core.files.base import ContentFile
    from PIL import Image, ImageOps

    image = ImageOps.exif_transpose(Image.open(uploaded))
    image = ImageOps.fit(image.convert("RGBA"), (AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return ContentFile(buffer.getvalue(), name="avatar.png")
