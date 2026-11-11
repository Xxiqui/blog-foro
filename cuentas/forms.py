from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)

from .models import Perfil

User = get_user_model()


class BootstrapFormMixin:
    """Agrega clases de Bootstrap 5 a todos los campos del formulario."""

    def _aplicar_estilos_bootstrap(self):
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = widget.attrs.get('class', '') + ' form-check-input'
            elif isinstance(widget, forms.Select) or isinstance(widget, forms.SelectMultiple):
                widget.attrs['class'] = (widget.attrs.get('class', '') + ' form-select').strip()
            else:
                clases_actuales = widget.attrs.get('class', '')
                if 'django_ckeditor_5' not in clases_actuales:
                    widget.attrs['class'] = (clases_actuales + ' form-control').strip()


class RegistroUsuarioForm(BootstrapFormMixin, UserCreationForm):
    first_name = forms.CharField(
        max_length=150,
        required=False,
        label='Nombre',
        widget=forms.TextInput(attrs={'placeholder': 'Ej. Ana', 'autocomplete': 'given-name'}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        label='Apellidos',
        widget=forms.TextInput(attrs={'placeholder': 'Ej. García', 'autocomplete': 'family-name'}),
    )
    username = forms.CharField(
        max_length=150,
        required=True,
        label='Nombre de usuario',
        help_text='Letras, números y guiones (_ o -). Mínimo 3 caracteres.',
        widget=forms.TextInput(attrs={'placeholder': 'ana_garcia', 'autocomplete': 'username'}),
    )
    email = forms.EmailField(
        required=True,
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={'placeholder': 'correo@ejemplo.com', 'autocomplete': 'email'}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('first_name', 'last_name', 'username', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'password1' in self.fields:
            self.fields['password1'].label = 'Contraseña'
            self.fields['password1'].widget.attrs.update({
                'placeholder': 'Mínimo 8 caracteres',
                'autocomplete': 'new-password',
            })
        if 'password2' in self.fields:
            self.fields['password2'].label = 'Confirmar contraseña'
            self.fields['password2'].widget.attrs.update({
                'placeholder': 'Repite la contraseña',
                'autocomplete': 'new-password',
            })
        self._aplicar_estilos_bootstrap()

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Ya existe un usuario registrado con este correo electrónico.')
        return email


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Usuario o correo electrónico'
        self.fields['username'].widget.attrs.update({
            'placeholder': 'usuario o correo@ejemplo.com',
            'autocomplete': 'username',
        })
        self.fields['password'].widget.attrs.update({
            'placeholder': '••••••••',
            'autocomplete': 'current-password',
        })
        self._aplicar_estilos_bootstrap()


class PasswordResetBootstrapForm(BootstrapFormMixin, PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs.update({
            'placeholder': 'correo@ejemplo.com',
            'autocomplete': 'email',
        })
        self._aplicar_estilos_bootstrap()


class SetPasswordBootstrapForm(BootstrapFormMixin, SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aplicar_estilos_bootstrap()


class CambioPasswordForm(BootstrapFormMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aplicar_estilos_bootstrap()


class PerfilForm(BootstrapFormMixin, forms.ModelForm):
    first_name = forms.CharField(
        max_length=150,
        required=False,
        label='Nombre',
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        label='Apellidos',
    )
    email = forms.EmailField(
        required=True,
        label='Correo electrónico',
    )

    class Meta:
        model = Perfil
        fields = ('bio', 'avatar')
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Escribe una breve biografía profesional...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.usuario_id:
            self.fields['first_name'].initial = self.instance.usuario.first_name
            self.fields['last_name'].initial = self.instance.usuario.last_name
            self.fields['email'].initial = self.instance.usuario.email
        self._aplicar_estilos_bootstrap()

    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')
        if avatar and hasattr(avatar, 'file'):
            try:
                import io
                import os
                from django.core.files.uploadedfile import InMemoryUploadedFile
                from PIL import Image, ImageOps

                with Image.open(avatar) as img:
                    img_rgb = img.convert('RGB')
                    img_recortada = ImageOps.fit(img_rgb, (256, 256), method=Image.Resampling.LANCZOS)
                    salida = io.BytesIO()
                    img_recortada.save(salida, format='JPEG', quality=90, optimize=True)
                    salida.seek(0)
                    nombre = f"avatar_{self.instance.usuario_id or 'user'}.jpg"
                    avatar = InMemoryUploadedFile(
                        salida,
                        'ImageField',
                        nombre,
                        'image/jpeg',
                        salida.getbuffer().nbytes,
                        None,
                    )
            except Exception:
                pass
        return avatar

    def save(self, commit=True):
        perfil = super().save(commit=False)
        usuario = perfil.usuario
        usuario.first_name = self.cleaned_data.get('first_name', '')
        usuario.last_name = self.cleaned_data.get('last_name', '')
        usuario.email = self.cleaned_data.get('email', '')
        if commit:
            usuario.save()
            perfil.save()
        return perfil

