from django import forms
from django.urls import reverse_lazy
from django_ckeditor_5.widgets import CKEditor5Widget

from cuentas.forms import BootstrapFormMixin
from .models import (
    Categoria,
    Comentario,
    Etiqueta,
    ListaLectura,
    Post,
    ReporteComentario,
    Suscripcion,
)


class PostForm(BootstrapFormMixin, forms.ModelForm):
    extracto_manual = forms.CharField(
        max_length=160,
        required=False,
        label='Extracto manual (opcional)',
        help_text='Breve resumen para tarjetas y buscadores (máximo 160 caracteres). Si lo dejas vacío, se extraerá automáticamente del contenido.',
        widget=forms.Textarea(attrs={
            'rows': 2,
            'maxlength': 160,
            'placeholder': 'Escribe un resumen breve y atractivo...',
            'id': 'id_extracto_manual',
        }),
    )
    imagen_portada = forms.ImageField(
        required=False,
        label='Imagen de portada',
        help_text='Dimensiones recomendadas: 1200x630 px. Formatos: JPG, PNG, WebP (máx. 5 MB).',
        widget=forms.ClearableFileInput(attrs={
            'accept': 'image/jpeg,image/png,image/webp',
            'id': 'id_imagen_portada',
        }),
    )

    class Meta:
        model = Post
        fields = ('titulo', 'categoria', 'etiquetas', 'contenido', 'extracto_manual', 'imagen_portada', 'estado')
        widgets = {
            'titulo': forms.TextInput(attrs={'placeholder': 'Escribe un título atractivo (mínimo 5 caracteres)'}),
            'contenido': CKEditor5Widget(
                attrs={'class': 'django_ckeditor_5'},
                config_name='default',
            ),
            'etiquetas': forms.SelectMultiple(attrs={'size': 5, 'id': 'id_etiquetas'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['contenido'].required = False
        if 'categoria' in self.fields:
            self.fields['categoria'].empty_label = 'Selecciona una categoría'
        self._aplicar_estilos_bootstrap()

    def clean_imagen_portada(self):
        imagen = self.cleaned_data.get('imagen_portada')
        if imagen and hasattr(imagen, 'size'):
            if imagen.size > 5 * 1024 * 1024:
                raise forms.ValidationError('La imagen de portada no debe superar los 5 MB.')
            content_type = getattr(imagen, 'content_type', '')
            if content_type and content_type not in ('image/jpeg', 'image/png', 'image/webp', 'image/pjpeg'):
                raise forms.ValidationError('Formato no permitido. Utiliza JPG, PNG o WebP.')
        return imagen

    def clean_titulo(self):
        titulo = (self.cleaned_data.get('titulo') or '').strip()
        if len(titulo) < 5:
            raise forms.ValidationError('El título debe tener al menos 5 caracteres.')
        return titulo

    def clean_contenido(self):
        contenido = (self.cleaned_data.get('contenido') or '').strip()
        if not contenido:
            raise forms.ValidationError('El contenido del post no puede estar vacío.')
        return contenido


class ComentarioForm(BootstrapFormMixin, forms.ModelForm):
    padre_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    sitio_web = forms.CharField(
        required=False,
        label='No completar este campo',
        widget=forms.TextInput(
            attrs={
                'tabindex': '-1',
                'autocomplete': 'off',
                'style': 'position:absolute;left:-9999px;height:0;width:0;opacity:0;',
            }
        ),
    )

    class Meta:
        model = Comentario
        fields = ('nombre', 'email', 'texto')
        widgets = {
            'nombre': forms.TextInput(attrs={'placeholder': 'Tu nombre'}),
            'email': forms.EmailInput(attrs={'placeholder': 'tu@email.com'}),
            'texto': forms.Textarea(
                attrs={
                    'rows': 4,
                    'maxlength': 1000,
                    'placeholder': 'Escribe tu comentario (máximo 1000 caracteres). Puedes mencionar usuarios con @usuario...',
                    'data-mention-autocomplete': 'true',
                    'data-mention-url': reverse_lazy('blog:buscar_usuarios_mencion'),
                }
            ),
        }

    def __init__(self, *args, user=None, post=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user if (user and getattr(user, 'is_authenticated', False)) else None
        self.post = post
        self._aplicar_estilos_bootstrap()

        if self.user:
            nombre_usuario = self.user.get_full_name() or self.user.username
            email_usuario = self.user.email or f"{self.user.username}@ejemplo.com"
            self.fields['nombre'].initial = nombre_usuario
            self.fields['email'].initial = email_usuario
            self.fields['nombre'].required = False
            self.fields['email'].required = False
            self.fields['nombre'].widget.attrs['readonly'] = 'readonly'
            self.fields['email'].widget.attrs['readonly'] = 'readonly'

    def clean_sitio_web(self):
        valor = (self.cleaned_data.get('sitio_web') or '').strip()
        if valor:
            raise forms.ValidationError('Detección anti-spam activada.')
        return valor

    def clean_nombre(self):
        if self.user:
            return self.user.get_full_name() or self.user.username
        nombre = (self.cleaned_data.get('nombre') or '').strip()
        if not nombre:
            raise forms.ValidationError('Este campo es obligatorio.')
        return nombre

    def clean_email(self):
        if self.user:
            return self.user.email or f"{self.user.username}@ejemplo.com"
        email = (self.cleaned_data.get('email') or '').strip()
        if not email:
            raise forms.ValidationError('Este campo es obligatorio.')
        return email

    def clean_texto(self):
        texto = (self.cleaned_data.get('texto') or '').strip()
        if len(texto) > 1000:
            raise forms.ValidationError('El comentario no puede superar los 1000 caracteres.')
        return texto

    def clean(self):
        from django.conf import settings
        cleaned_data = super().clean()
        padre_id = cleaned_data.get('padre_id')
        cleaned_data['padre_resuelto'] = None

        if padre_id:
            padre = (
                Comentario.objects.select_related('padre', 'padre__padre', 'padre__padre__padre')
                .filter(pk=padre_id)
                .first()
            )
            if not padre:
                raise forms.ValidationError('El comentario al que intentas responder no existe.')
            if self.post and padre.post_id != self.post.pk:
                raise forms.ValidationError('El comentario padre pertenece a otro artículo.')
            if not padre.aprobado or padre.eliminado or padre.oculto_por_reportes:
                raise forms.ValidationError('Solo se puede responder a comentarios aprobados y visibles.')

            max_prof = getattr(settings, 'COMENTARIO_PROFUNDIDAD_MAX', 4)
            ancestros = []
            cursor = padre
            while cursor is not None and len(ancestros) <= max_prof + 4:
                ancestros.append(cursor)
                cursor = cursor.padre
            ancestros.reverse()  # [nivel_1, nivel_2, ...]

            # Si el comentario padre ya está en el nivel máximo (ej. 4), la respuesta
            # cuelga del mismo padre (nivel max_prof - 1) para quedar también en nivel 4.
            if len(ancestros) >= max_prof and max_prof >= 2:
                padre_efectivo = ancestros[max_prof - 2]
            else:
                padre_efectivo = padre

            cleaned_data['padre_resuelto'] = padre_efectivo

        return cleaned_data


class ComentarioEdicionForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Comentario
        fields = ('texto',)
        widgets = {
            'texto': forms.Textarea(
                attrs={
                    'rows': 4,
                    'maxlength': 1000,
                    'placeholder': 'Edita tu comentario (máximo 1000 caracteres)...',
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aplicar_estilos_bootstrap()

    def clean_texto(self):
        texto = (self.cleaned_data.get('texto') or '').strip()
        if not texto:
            raise forms.ValidationError('El comentario no puede estar vacío.')
        if len(texto) > 1000:
            raise forms.ValidationError('El comentario no puede superar los 1000 caracteres.')
        return texto


class ReporteComentarioForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ReporteComentario
        fields = ('motivo', 'detalle')
        widgets = {
            'detalle': forms.Textarea(
                attrs={
                    'rows': 3,
                    'maxlength': 300,
                    'placeholder': 'Explica brevemente el motivo del reporte (opcional, máx. 300 caracteres)...',
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aplicar_estilos_bootstrap()


class CategoriaForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ('nombre', 'descripcion', 'avatar', 'banner')
        widgets = {
            'nombre': forms.TextInput(attrs={'placeholder': 'Ej. Desarrollo Web'}),
            'descripcion': forms.Textarea(
                attrs={
                    'rows': 2,
                    'maxlength': 240,
                    'placeholder': 'Descripción breve de la comunidad (máx. 240 caracteres)...',
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aplicar_estilos_bootstrap()


class EtiquetaForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Etiqueta
        fields = ('nombre',)
        widgets = {
            'nombre': forms.TextInput(attrs={'placeholder': 'Ej. Python'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aplicar_estilos_bootstrap()


class SuscripcionForm(BootstrapFormMixin, forms.Form):
    """
    Formulario de suscripción por correo con campo honeypot (`sitio_web`)
    y precarga de email si el usuario está autenticado.
    """
    email = forms.EmailField(
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={'placeholder': 'tu@correo.com'}),
    )
    autor_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    categoria_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    # Campo honeypot anti-bots (debe permanecer vacío)
    sitio_web = forms.CharField(
        required=False,
        label='No completar este campo',
        widget=forms.TextInput(
            attrs={
                'tabindex': '-1',
                'autocomplete': 'off',
                'style': 'position:absolute;left:-9999px;height:0;width:0;opacity:0;',
            }
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._aplicar_estilos_bootstrap()
        if user and getattr(user, 'is_authenticated', False) and user.email:
            self.fields['email'].initial = user.email

    def clean_sitio_web(self):
        valor = (self.cleaned_data.get('sitio_web') or '').strip()
        if valor:
            raise forms.ValidationError('Detección anti-spam activada.')
        return valor

    def clean_email(self):
        return (self.cleaned_data.get('email') or '').strip().lower()


class ListaLecturaForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ListaLectura
        fields = ('nombre', 'descripcion', 'publica')
        widgets = {
            'nombre': forms.TextInput(attrs={'placeholder': 'Ej. Lecturas de arquitectura'}),
            'descripcion': forms.TextInput(attrs={'placeholder': 'Descripción breve (opcional)...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aplicar_estilos_bootstrap()

    def clean_nombre(self):
        nombre = (self.cleaned_data.get('nombre') or '').strip()
        if not nombre:
            raise forms.ValidationError('El nombre de la lista es obligatorio.')
        if nombre.lower() == ListaLectura.NOMBRE_GUARDADOS.lower():
            if not (self.instance and self.instance.pk and self.instance.es_guardados):
                raise forms.ValidationError('El nombre "Guardados" está reservado para la lista predeterminada.')
        return nombre


class ContactoForm(BootstrapFormMixin, forms.Form):
    """
    Formulario de contacto hacia los administradores con campo honeypot (`sitio_web`).
    """
    nombre = forms.CharField(
        max_length=100,
        label='Nombre',
        widget=forms.TextInput(attrs={'placeholder': 'Tu nombre completo'}),
    )
    email = forms.EmailField(
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={'placeholder': 'tu@correo.com'}),
    )
    mensaje = forms.CharField(
        max_length=2000,
        label='Mensaje',
        widget=forms.Textarea(
            attrs={
                'rows': 5,
                'placeholder': 'Escribe aquí tu consulta, sugerencia o comentario...',
            }
        ),
    )
    sitio_web = forms.CharField(
        required=False,
        label='No completar este campo',
        widget=forms.TextInput(
            attrs={
                'tabindex': '-1',
                'autocomplete': 'off',
                'style': 'position:absolute;left:-9999px;height:0;width:0;opacity:0;',
            }
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._aplicar_estilos_bootstrap()
        if user and getattr(user, 'is_authenticated', False):
            self.fields['nombre'].initial = user.get_full_name() or user.username
            if user.email:
                self.fields['email'].initial = user.email

    def clean_sitio_web(self):
        valor = (self.cleaned_data.get('sitio_web') or '').strip()
        if valor:
            raise forms.ValidationError('Detección anti-spam activada.')
        return valor


