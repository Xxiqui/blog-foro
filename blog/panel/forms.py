from django import forms
from django_ckeditor_5.widgets import CKEditor5Widget
from PIL import Image

from blog.models import Categoria, Etiqueta, Post
from cuentas.forms import BootstrapFormMixin


class PostEditorForm(BootstrapFormMixin, forms.ModelForm):
    """
    Formulario base del editor de artículos utilizado en el Estudio de Escritura.
    """
    categoria = forms.ModelChoiceField(
        queryset=Categoria.objects.all().order_by('nombre'),
        required=False,
        empty_label='Selecciona una categoría',
        label='Categoría',
    )
    extracto = forms.CharField(
        max_length=160,
        required=False,
        label='Extracto manual (máx. 160 caracteres)',
        help_text='Breve resumen para buscadores y redes sociales. Si lo dejas vacío se genera automáticamente.',
        widget=forms.Textarea(attrs={
            'rows': 3,
            'maxlength': 160,
            'placeholder': 'Escribe una síntesis concisa y atractiva...',
            'id': 'id_extracto',
        }),
    )

    class Meta:
        model = Post
        fields = ('titulo', 'categoria', 'etiquetas', 'contenido', 'extracto', 'imagen_portada', 'slug')
        widgets = {
            'titulo': forms.Textarea(attrs={
                'rows': 1,
                'maxlength': 250,
                'placeholder': 'Título de tu artículo...',
                'id': 'id_titulo',
                'class': 'editor-title-textarea',
            }),
            'contenido': CKEditor5Widget(
                attrs={'class': 'django_ckeditor_5'},
                config_name='default',
            ),
            'slug': forms.TextInput(attrs={
                'id': 'id_slug',
                'placeholder': 'url-amigable-del-post',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['contenido'].required = False
        if self.instance and self.instance.pk and self.instance.publicado_en is not None:
            # Slug inmutable tras la primera publicación
            self.fields['slug'].disabled = True
            self.fields['slug'].help_text = 'El slug no puede modificarse después de haber sido publicado.'
        self._aplicar_estilos_bootstrap()

    def clean_imagen_portada(self):
        imagen = self.cleaned_data.get('imagen_portada')
        if not imagen or not hasattr(imagen, 'file'):
            return imagen

        max_mb = 5
        if imagen.size > max_mb * 1024 * 1024:
            raise forms.ValidationError(f'La imagen no debe superar {max_mb} MB.')

        nombre = (imagen.name or '').lower()
        if not nombre.endswith(('.jpg', '.jpeg', '.png', '.webp')):
            raise forms.ValidationError('Solo se admiten formatos JPG, PNG o WebP.')

        try:
            imagen.file.seek(0)
            img = Image.open(imagen.file)
            img.verify()
            if img.format.lower() not in ('jpeg', 'png', 'webp'):
                raise forms.ValidationError('El archivo no contiene una imagen válida.')
            imagen.file.seek(0)
        except Exception:
            raise forms.ValidationError('El archivo no es una imagen válida o está dañado.')

        return imagen

