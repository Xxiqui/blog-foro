from io import BytesIO
import re
import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.validators import MaxLengthValidator, MinLengthValidator
from django.db import connection, models
from PIL import Image, ImageOps
from django.db.models import (
    BooleanField,
    Count,
    Exists,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import slugify
from django_ckeditor_5.fields import CKEditor5Field

from cuentas.models import Perfil

PRIMERA_IMAGEN_HTML_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)

# Compatibilidad de GinIndex cuando se ejecutan migraciones en SQLite (desarrollo/pruebas)
_original_gin_create_sql = GinIndex.create_sql


def _compatible_gin_create_sql(self, model, schema_editor, using="", **kwargs):
    if schema_editor.connection.vendor != 'postgresql':
        return models.Index.create_sql(self, model, schema_editor, using="", **kwargs)
    return _original_gin_create_sql(self, model, schema_editor, using=using, **kwargs)


GinIndex.create_sql = _compatible_gin_create_sql


def generar_slug_unico(instancia, valor_fuente, slug_field_name='slug', max_length=250):
    """
    Genera un slug único para un modelo a partir de `valor_fuente`.
    Si ya existe un registro con el mismo slug, agrega un sufijo numérico (-1, -2, ...).
    """
    slug_base = slugify(valor_fuente)[: max_length - 10] or 'item'
    slug_candidato = slug_base
    Modelo = instancia.__class__
    contador = 1

    qs = Modelo.objects.all()
    if instancia.pk:
        qs = qs.exclude(pk=instancia.pk)

    while qs.filter(**{slug_field_name: slug_candidato}).exists():
        slug_candidato = f"{slug_base}-{contador}"
        contador += 1

    return slug_candidato


class Categoria(models.Model):
    nombre = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='Nombre',
    )
    slug = models.SlugField(
        max_length=120,
        unique=True,
        blank=True,
        verbose_name='Slug',
    )
    descripcion = models.CharField(
        max_length=240,
        blank=True,
        validators=[
            MaxLengthValidator(240, message='La descripción no puede superar los 240 caracteres.')
        ],
        verbose_name='Descripción',
    )
    avatar = models.ImageField(
        upload_to='categorias/avatares/',
        blank=True,
        null=True,
        verbose_name='Avatar de la comunidad',
    )
    banner = models.ImageField(
        upload_to='categorias/banners/',
        blank=True,
        null=True,
        verbose_name='Banner de la comunidad',
    )
    creada = models.DateField(
        default=timezone.localdate,
        verbose_name='Fecha de creación',
    )

    class Meta:
        verbose_name = 'Categoría'
        verbose_name_plural = 'Categorías'
        ordering = ['nombre']

    def _redimensionar_imagen(self, campo, Dimensiones, recortar=False):
        if not campo:
            return
        try:
            campo.open()
            raw = campo.read()
            if not raw:
                return
            with Image.open(BytesIO(raw)) as img:
                if recortar and img.size == Dimensiones:
                    return
                if not recortar and img.width <= Dimensiones[0] and img.height <= Dimensiones[1]:
                    return

                if img.mode not in ('RGB', 'RGBA'):
                    img = img.convert('RGB')
                elif img.mode == 'RGBA':
                    fondo = Image.new('RGB', img.size, (255, 255, 255))
                    fondo.paste(img, mask=img.split()[3])
                    img = fondo

                resample = getattr(Image, 'Resampling', Image).LANCZOS
                if recortar:
                    procesada = ImageOps.fit(img, Dimensiones, method=resample)
                else:
                    procesada = img.copy()
                    procesada.thumbnail(Dimensiones, resample)

                salida = BytesIO()
                procesada.save(salida, format='JPEG', quality=88, optimize=True)
                nombre_base = (campo.name or 'imagen').rsplit('/', 1)[-1].rsplit('.', 1)[0]
                campo.save(f'{nombre_base}.jpg', ContentFile(salida.getvalue()), save=False)
        except Exception:
            pass

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generar_slug_unico(self, self.nombre, max_length=120)
        if self.avatar:
            self._redimensionar_imagen(self.avatar, (256, 256), recortar=True)
        if self.banner:
            self._redimensionar_imagen(self.banner, (1600, 400), recortar=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre

    def get_absolute_url(self):
        return reverse('blog:posts_por_categoria', kwargs={'slug': self.slug})


class Etiqueta(models.Model):
    nombre = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='Nombre',
    )
    slug = models.SlugField(
        max_length=120,
        unique=True,
        blank=True,
        verbose_name='Slug',
    )

    class Meta:
        verbose_name = 'Etiqueta'
        verbose_name_plural = 'Etiquetas'
        ordering = ['nombre']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generar_slug_unico(self, self.nombre, max_length=120)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre

    def get_absolute_url(self):
        return reverse('blog:posts_por_etiqueta', kwargs={'slug': self.slug})


class PostQuerySet(models.QuerySet):
    def publicados(self):
        return self.filter(estado=Post.Estado.PUBLICADO)

    def borradores(self):
        return self.filter(estado=Post.Estado.BORRADOR)

    def con_relaciones(self):
        return self.select_related('autor', 'autor__usuario', 'categoria').prefetch_related('etiquetas')

    def con_interacciones(self, usuario=None):
        """
        Anota `total_likes`, `total_comentarios_aprobados`, `total_vistas`,
        `ya_dio_like` y `ya_guardado` con subconsultas y `Exists`
        para evitar consultas N+1 y productos cartesianos en listados y detalle.
        """
        sub_likes = (
            LikePost.objects.filter(post=OuterRef('pk'))
            .values('post')
            .annotate(total=Count('id'))
            .values('total')[:1]
        )
        sub_comentarios = (
            Comentario.objects.filter(
                post=OuterRef('pk'),
                aprobado=True,
                oculto_por_reportes=False,
                eliminado=False,
            )
            .values('post')
            .annotate(total=Count('id'))
            .values('total')[:1]
        )
        sub_vistas = (
            VistaDiaria.objects.filter(post=OuterRef('pk'))
            .values('post')
            .annotate(total=Sum('cantidad'))
            .values('total')[:1]
        )
        qs = self.annotate(
            total_likes=Coalesce(Subquery(sub_likes, output_field=IntegerField()), 0),
            total_comentarios_aprobados=Coalesce(Subquery(sub_comentarios, output_field=IntegerField()), 0),
            total_vistas=Coalesce(Subquery(sub_vistas, output_field=IntegerField()), 0),
        )
        if usuario and getattr(usuario, 'is_authenticated', False):
            subquery_like = LikePost.objects.filter(post=OuterRef('pk'), usuario=usuario)
            subquery_guardado = ItemLista.objects.filter(
                post=OuterRef('pk'),
                lista__usuario=usuario,
                lista__nombre=ListaLectura.NOMBRE_GUARDADOS,
            )
            qs = qs.annotate(
                ya_dio_like=Exists(subquery_like),
                ya_guardado=Exists(subquery_guardado),
            )
        else:
            qs = qs.annotate(
                ya_dio_like=Value(False, output_field=BooleanField()),
                ya_guardado=Value(False, output_field=BooleanField()),
            )
        return qs.order_by('-publicado_en', '-creado')


class ExtractoDescriptor:
    """Descriptor para el campo extracto: devuelve el extracto manual si existe, o el extracto plano generado automáticamente."""
    def __init__(self, field_name='extracto'):
        self.field_name = field_name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        val = instance.__dict__.get(self.field_name, '')
        if val and str(val).strip():
            return str(val).strip()
        manual = instance.__dict__.get('extracto_manual', '')
        if manual and str(manual).strip():
            return str(manual).strip()
        from blog.templatetags.blog_extras import extracto_plano
        return extracto_plano(getattr(instance, 'contenido', '') or '', max_chars=160)

    def __set__(self, instance, value):
        instance.__dict__[self.field_name] = (value or '').strip()
        instance.__dict__['extracto_manual'] = (value or '').strip()


class Post(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = 'borrador', 'Borrador'
        PUBLICADO = 'publicado', 'Publicado'
        PROGRAMADO = 'programado', 'Programado'

    titulo = models.CharField(
        max_length=250,
        validators=[
            MinLengthValidator(5, message='El título debe tener al menos 5 caracteres.')
        ],
        verbose_name='Título',
    )
    slug = models.SlugField(
        max_length=270,
        unique=True,
        blank=True,
        verbose_name='Slug',
    )
    autor = models.ForeignKey(
        Perfil,
        on_delete=models.CASCADE,
        related_name='posts',
        verbose_name='Autor',
    )
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posts',
        verbose_name='Categoría',
    )
    etiquetas = models.ManyToManyField(
        Etiqueta,
        blank=True,
        related_name='posts',
        verbose_name='Etiquetas',
    )
    contenido = CKEditor5Field(
        verbose_name='Contenido',
        config_name='default',
    )
    estado = models.CharField(
        max_length=15,
        choices=Estado.choices,
        default=Estado.BORRADOR,
        verbose_name='Estado',
    )
    creado = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación',
    )
    actualizado = models.DateTimeField(
        auto_now=True,
        verbose_name='Última actualización',
    )
    publicado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de publicación',
    )
    notificado = models.BooleanField(
        default=False,
        editable=False,
        verbose_name='Notificado en primera publicación',
    )
    fijado_en_categoria = models.BooleanField(
        default=False,
        verbose_name='Fijado en su categoría',
        help_text='Destaca este post en la cabecera de su categoría (máximo 3 por categoría).',
    )
    buscador = SearchVectorField(
        null=True,
        blank=True,
        editable=False,
        verbose_name='Vector de búsqueda',
    )
    imagen_portada = models.ImageField(
        upload_to='portadas/',
        blank=True,
        null=True,
        verbose_name='Imagen de portada',
        help_text='Dimensiones recomendadas: 1200x630 px. Formatos: JPG, PNG, WebP (máx. 5 MB).',
    )
    extracto_manual = models.CharField(
        max_length=160,
        blank=True,
        default='',
        verbose_name='Extracto manual',
        help_text='Breve resumen para tarjetas y redes (máximo 160 caracteres). Si se deja vacío se genera automáticamente.',
    )
    extracto = models.CharField(
        max_length=160,
        blank=True,
        default='',
        verbose_name='Extracto',
        help_text='Breve resumen para tarjetas y redes (máximo 160 caracteres). Si se deja vacío se genera automáticamente.',
    )
    programado_para = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Programado para',
        help_text='Fecha y hora en la que se publicará automáticamente este post.',
    )

    objects = PostQuerySet.as_manager()

    class Meta:
        verbose_name = 'Post'
        verbose_name_plural = 'Posts'
        ordering = ['-publicado_en', '-creado']
        indexes = [
            GinIndex(fields=['buscador'], name='post_buscador_gin'),
        ]

    def clean(self):
        super().clean()
        if self.fijado_en_categoria and self.categoria_id:
            fijados_qs = Post.objects.filter(
                categoria_id=self.categoria_id,
                fijado_en_categoria=True,
            )
            if self.pk:
                fijados_qs = fijados_qs.exclude(pk=self.pk)
            if fijados_qs.count() >= 3:
                raise ValidationError(
                    {
                        'fijado_en_categoria': (
                            'No se pueden fijar más de 3 posts en una misma categoría.'
                        )
                    }
                )

    def save(self, *args, **kwargs):
        if self.pk:
            original = Post.objects.filter(pk=self.pk).values('slug', 'publicado_en').first()
            if original and original['publicado_en'] is not None:
                # El slug es editable solo mientras el post nunca se haya publicado, y es inmutable después
                if self.slug and self.slug != original['slug']:
                    raise ValidationError({'slug': 'El slug no se puede modificar una vez publicado el artículo.'})
                self.slug = original['slug']
            elif not self.slug:
                self.slug = generar_slug_unico(self, self.titulo, max_length=270)
        elif not self.slug:
            self.slug = generar_slug_unico(self, self.titulo, max_length=270)

        if self.estado == self.Estado.PUBLICADO and not self.publicado_en:
            self.publicado_en = timezone.now()

        debe_notificar_primera_publicacion = (
            self.estado == self.Estado.PUBLICADO and not self.notificado
        )
        if debe_notificar_primera_publicacion:
            self.notificado = True

        super().save(*args, **kwargs)
        self.actualizar_vector_busqueda()

        if debe_notificar_primera_publicacion:
            self._disparar_avisos_primera_publicacion()

    def _disparar_avisos_primera_publicacion(self):
        """
        Envía notificaciones internas POST_NUEVO a los seguidores del autor y
        correos a los suscriptores confirmados (autor y categoría) solo en la primera publicación.
        """
        from .emails import enviar_correos_nuevo_post
        from .notificaciones import notificar

        seguidores_qs = Seguimiento.objects.filter(autor=self.autor).select_related('seguidor')
        for seg in seguidores_qs:
            notificar(
                destinatario=seg.seguidor,
                tipo=Notificacion.Tipo.POST_NUEVO,
                actor=self.autor.usuario,
                post=self,
            )

        enviar_correos_nuevo_post(self)

    def actualizar_vector_busqueda(self):
        """
        Actualiza el campo `buscador` (SearchVectorField) únicamente cuando
        el motor de base de datos activo es PostgreSQL.
        Pondera: título (A), etiquetas (B) y contenido (C) en español.
        """
        if connection.vendor != 'postgresql' or not self.pk:
            return
        etiquetas_texto = ' '.join(self.etiquetas.values_list('nombre', flat=True))
        contenido_plano = strip_tags(self.contenido or '')
        vector = (
            SearchVector(Value(self.titulo or ''), weight='A', config='spanish')
            + SearchVector(Value(etiquetas_texto), weight='B', config='spanish')
            + SearchVector(Value(contenido_plano), weight='C', config='spanish')
        )
        Post.objects.filter(pk=self.pk).update(buscador=vector)

    @property
    def extracto_manual(self):
        """Compatibilidad con código anterior que referenciaba extracto_manual."""
        return self.__dict__.get('extracto') or self.__dict__.get('extracto_manual') or ''

    @extracto_manual.setter
    def extracto_manual(self, val):
        self.extracto = val

    @property
    def tiempo_lectura(self):
        """Calcula el tiempo estimado de lectura en minutos (~200 palabras/minuto, mínimo 1 min)."""
        texto = strip_tags(self.contenido or '').strip()
        if not texto:
            return 1
        palabras = len(texto.split())
        return max(1, round(palabras / 200))

    @property
    def portada_url(self):
        """Devuelve la URL de la portada del post si existe `imagen_portada`/`portada` o primera imagen en el HTML."""
        for attr in ('imagen_portada', 'portada'):
            campo = getattr(self, attr, None)
            if campo:
                if hasattr(campo, 'url'):
                    try:
                        return campo.url
                    except ValueError:
                        pass
                elif isinstance(campo, str) and campo.strip():
                    return campo.strip()
        match = PRIMERA_IMAGEN_HTML_RE.search(self.contenido or '')
        if match:
            return match.group(1)
        return None

    @property
    def portada_srcset(self):
        """Devuelve el atributo srcset con variantes WebP de 640 y 1200 px si existen."""
        from blog.servicios.imagenes import obtener_rutas_variantes_webp
        variantes = obtener_rutas_variantes_webp(self)
        if 640 in variantes and 1200 in variantes:
            return f"{variantes[640]} 640w, {variantes[1200]} 1200w"
        return ""

    @property
    def portada_thumb_webp(self):
        """Devuelve la variante WebP de 192 px si existe, o portada_url como respaldo."""
        from blog.servicios.imagenes import obtener_rutas_variantes_webp
        variantes = obtener_rutas_variantes_webp(self)
        if 192 in variantes:
            return variantes[192]
        return self.portada_url

    def __str__(self):
        return self.titulo

    def get_absolute_url(self):
        return reverse('blog:post_detail', kwargs={'slug': self.slug})


Post.extracto = ExtractoDescriptor('extracto')


class RevisionPost(models.Model):
    class Origen(models.TextChoices):
        AUTO = 'auto', 'Autoguardado'
        MANUAL = 'manual', 'Manual'
        PUBLICACION = 'publicacion', 'Publicación'
        RESTAURACION = 'restauracion', 'Restauración'

    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='revisiones',
        verbose_name='Post',
    )
    titulo = models.CharField(
        max_length=250,
        verbose_name='Título',
    )
    contenido = models.TextField(
        verbose_name='Contenido',
    )
    extracto = models.CharField(
        max_length=160,
        blank=True,
        default='',
        verbose_name='Extracto',
    )
    creado = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación',
    )
    origen = models.CharField(
        max_length=20,
        choices=Origen.choices,
        default=Origen.MANUAL,
        verbose_name='Origen',
    )

    class Meta:
        verbose_name = 'Revisión de post'
        verbose_name_plural = 'Revisiones de post'
        ordering = ['-creado']

    def __str__(self):
        return f"Revisión #{self.id} de «{self.post.titulo}» ({self.get_origen_display()} - {self.creado:%d/%m/%Y %H:%M})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Poda automática a las últimas 20 por post
        ids_a_conservar = list(
            RevisionPost.objects.filter(post=self.post)
            .order_by('-creado')
            .values_list('id', flat=True)[:20]
        )
        if ids_a_conservar:
            RevisionPost.objects.filter(post=self.post).exclude(id__in=ids_a_conservar).delete()


class Comentario(models.Model):
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='comentarios',
        verbose_name='Post',
    )
    padre = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='respuestas',
        verbose_name='Comentario padre',
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='comentarios_realizados',
        verbose_name='Autor registrado',
    )
    nombre = models.CharField(
        max_length=100,
        verbose_name='Nombre',
    )
    email = models.EmailField(
        verbose_name='Correo electrónico',
    )
    texto = models.TextField(
        validators=[
            MaxLengthValidator(1000, message='El comentario no puede superar los 1000 caracteres.')
        ],
        verbose_name='Comentario',
    )
    aprobado = models.BooleanField(
        default=False,
        verbose_name='Aprobado',
    )
    editado = models.BooleanField(
        default=False,
        verbose_name='Editado',
    )
    oculto_por_reportes = models.BooleanField(
        default=False,
        verbose_name='Oculto por reportes',
    )
    eliminado = models.BooleanField(
        default=False,
        verbose_name='Eliminado',
    )
    creado = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación',
    )
    actualizado = models.DateTimeField(
        auto_now=True,
        verbose_name='Última actualización',
    )

    class Meta:
        verbose_name = 'Comentario'
        verbose_name_plural = 'Comentarios'
        ordering = ['-creado']

    def clean(self):
        super().clean()
        if self.padre_id:
            if self.post_id and self.padre.post_id != self.post_id:
                raise ValidationError(
                    {'padre': 'El comentario padre debe pertenecer al mismo artículo.'}
                )
            if not self.padre.aprobado or self.padre.eliminado or self.padre.oculto_por_reportes:
                raise ValidationError(
                    {'padre': 'Solo se puede responder a comentarios aprobados y visibles.'}
                )

    def calcular_profundidad(self):
        """
        Devuelve el nivel de profundidad del comentario en el árbol (raíz = 1).
        """
        nivel = 1
        actual = self
        visitados = {self.pk} if self.pk else set()
        while actual.padre_id:
            if actual.padre_id in visitados:
                break
            visitados.add(actual.padre_id)
            nivel += 1
            actual = actual.padre
        return nivel

    @property
    def profundidad(self):
        return self.calcular_profundidad()

    def borrar_seguro(self):
        """
        Si el comentario tiene respuestas, no se elimina físicamente: se marca
        `eliminado=True` para preservar el hilo y mostrar «[comentario eliminado]».
        Si no tiene respuestas, se elimina de la base de datos.
        """
        if self.respuestas.exists():
            self.eliminado = True
            self.save(update_fields=['eliminado', 'actualizado'])
            return 'marcado'
        self.delete()
        return 'eliminado'

    def dentro_de_ventana_edicion(self):
        ventana_min = getattr(settings, 'COMENTARIO_VENTANA_EDICION_MIN', 10)
        limite = self.creado + timedelta(minutes=ventana_min)
        return timezone.now() <= limite

    def puede_editar(self, usuario):
        if self.eliminado:
            return False
        if not usuario or not getattr(usuario, 'is_authenticated', False):
            return False
        if not self.autor_id or self.autor_id != usuario.id:
            return False
        return self.dentro_de_ventana_edicion()

    def puede_borrar(self, usuario):
        if self.eliminado:
            return False
        if not usuario or not getattr(usuario, 'is_authenticated', False):
            return False
        if self.autor_id and self.autor_id == usuario.id:
            return True
        if self.post.autor.usuario_id == usuario.id:
            return True
        if usuario.is_staff or usuario.is_superuser:
            return True
        return False

    def __str__(self):
        estado_str = 'Eliminado' if self.eliminado else ('Aprobado' if self.aprobado else 'Pendiente')
        return f"Comentario de {self.nombre} en {self.post.titulo} ({estado_str})"


class Notificacion(models.Model):
    class Tipo(models.TextChoices):
        COMENTARIO_NUEVO = 'COMENTARIO_NUEVO', 'Comentario nuevo'
        COMENTARIO_APROBADO = 'COMENTARIO_APROBADO', 'Comentario aprobado'
        RESPUESTA_COMENTARIO = 'RESPUESTA_COMENTARIO', 'Respuesta a comentario'
        MENCION = 'MENCION', 'Mención en comentario'
        LIKE_POST = 'LIKE_POST', 'Me gusta en post'
        LIKE_COMENTARIO = 'LIKE_COMENTARIO', 'Me gusta en comentario'
        SEGUIDOR_NUEVO = 'SEGUIDOR_NUEVO', 'Nuevo seguidor'
        POST_NUEVO = 'POST_NUEVO', 'Nuevo post'
        REPORTE_COMENTARIO = 'REPORTE_COMENTARIO', 'Reporte de comentario'

    destinatario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notificaciones',
        verbose_name='Destinatario',
    )
    tipo = models.CharField(
        max_length=30,
        choices=Tipo.choices,
        verbose_name='Tipo',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notificaciones_emitidas',
        verbose_name='Actor',
    )
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notificaciones',
        verbose_name='Post',
    )
    comentario = models.ForeignKey(
        Comentario,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notificaciones',
        verbose_name='Comentario',
    )
    mensaje = models.CharField(
        max_length=350,
        verbose_name='Mensaje',
    )
    url = models.CharField(
        max_length=350,
        verbose_name='URL de destino',
    )
    leida = models.BooleanField(
        default=False,
        verbose_name='Leída',
    )
    creado = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación',
    )

    class Meta:
        verbose_name = 'Notificación'
        verbose_name_plural = 'Notificaciones'
        ordering = ['-creado']

    def __str__(self):
        return f"[{self.tipo}] Para {self.destinatario}: {self.mensaje}"


class LikePost(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='likes_posts',
        verbose_name='Usuario',
    )
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='likes',
        verbose_name='Post',
    )
    creado = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación',
    )

    class Meta:
        verbose_name = 'Me gusta en Post'
        verbose_name_plural = 'Me gusta en Posts'
        constraints = [
            models.UniqueConstraint(fields=['usuario', 'post'], name='unique_like_usuario_post'),
        ]
        ordering = ['-creado']

    def __str__(self):
        return f"{self.usuario} -> {self.post}"


class VotoUtil(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='votos_utilidad',
        verbose_name='Usuario',
    )
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='votos_utilidad',
        verbose_name='Post',
    )
    util = models.BooleanField(
        verbose_name='¿Fue útil?',
    )
    creado = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación',
    )

    class Meta:
        verbose_name = 'Voto de utilidad'
        verbose_name_plural = 'Votos de utilidad'
        constraints = [
            models.UniqueConstraint(fields=['usuario', 'post'], name='unique_voto_util_usuario_post'),
        ]
        ordering = ['-creado']

    def __str__(self):
        valor = 'Sí' if self.util else 'No'
        return f"{self.usuario} votó {valor} en {self.post}"


class LikeComentario(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='likes_comentarios',
        verbose_name='Usuario',
    )
    comentario = models.ForeignKey(
        Comentario,
        on_delete=models.CASCADE,
        related_name='likes',
        verbose_name='Comentario',
    )
    creado = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación',
    )

    class Meta:
        verbose_name = 'Me gusta en Comentario'
        verbose_name_plural = 'Me gusta en Comentarios'
        constraints = [
            models.UniqueConstraint(
                fields=['usuario', 'comentario'],
                name='unique_like_usuario_comentario',
            ),
        ]
        ordering = ['-creado']

    def __str__(self):
        return f"{self.usuario} -> Comentario #{self.comentario_id}"


class ReporteComentario(models.Model):
    class Motivo(models.TextChoices):
        SPAM = 'spam', 'Spam'
        OFENSIVO = 'ofensivo', 'Contenido ofensivo'
        ACOSO = 'acoso', 'Acoso'
        DESINFORMACION = 'desinformacion', 'Desinformación'
        OTRO = 'otro', 'Otro'

    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        REVISADO = 'revisado', 'Revisado'
        DESCARTADO = 'descartado', 'Descartado'

    comentario = models.ForeignKey(
        Comentario,
        on_delete=models.CASCADE,
        related_name='reportes',
        verbose_name='Comentario',
    )
    reportante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reportes_enviados',
        verbose_name='Reportante',
    )
    motivo = models.CharField(
        max_length=25,
        choices=Motivo.choices,
        verbose_name='Motivo',
    )
    detalle = models.CharField(
        max_length=300,
        blank=True,
        validators=[
            MaxLengthValidator(300, message='El detalle no puede superar los 300 caracteres.')
        ],
        verbose_name='Detalle adicional',
    )
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
        verbose_name='Estado',
    )
    creado = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación',
    )
    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reportes_revisados',
        verbose_name='Revisado por',
    )

    class Meta:
        verbose_name = 'Reporte de Comentario'
        verbose_name_plural = 'Reportes de Comentarios'
        constraints = [
            models.UniqueConstraint(
                fields=['comentario', 'reportante'],
                name='unique_reporte_comentario_usuario',
            ),
        ]
        ordering = ['-creado']

    def __str__(self):
        return f"Reporte ({self.get_motivo_display()}) en comentario #{self.comentario_id} por {self.reportante}"


# ==============================================================================
# BLOQUE 1 (RONDA 2): SEGUIMIENTO DE AUTORES
# ==============================================================================

class Seguimiento(models.Model):
    seguidor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='siguiendo',
        verbose_name='Seguidor',
    )
    autor = models.ForeignKey(
        Perfil,
        on_delete=models.CASCADE,
        related_name='seguidores',
        verbose_name='Autor seguido',
    )
    creado = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de seguimiento',
    )

    class Meta:
        verbose_name = 'Seguimiento'
        verbose_name_plural = 'Seguimientos'
        constraints = [
            models.UniqueConstraint(fields=['seguidor', 'autor'], name='unique_seguidor_autor'),
        ]
        ordering = ['-creado']

    def clean(self):
        if self.seguidor_id and self.autor_id and self.seguidor_id == self.autor.usuario_id:
            raise ValidationError('No puedes seguirte a ti mismo.')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"@{self.seguidor.username} sigue a @{self.autor.usuario.username}"


# ==============================================================================
# BLOQUE 2 (RONDA 2): SUSCRIPCIÓN POR CORREO (DOBLE CONFIRMACIÓN)
# ==============================================================================

class Suscripcion(models.Model):
    email = models.EmailField(
        verbose_name='Correo electrónico',
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='suscripciones',
        verbose_name='Usuario',
    )
    autor = models.ForeignKey(
        Perfil,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='suscripciones_correo',
        verbose_name='Autor suscrito',
    )
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='suscripciones_correo',
        verbose_name='Categoría suscrita',
    )
    token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name='Token único',
    )
    confirmada = models.BooleanField(
        default=False,
        verbose_name='Confirmada',
    )
    activa = models.BooleanField(
        default=True,
        verbose_name='Activa',
    )
    creado = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación',
    )

    class Meta:
        verbose_name = 'Suscripción por correo'
        verbose_name_plural = 'Suscripciones por correo'
        constraints = [
            models.UniqueConstraint(
                fields=['email', 'autor'],
                condition=Q(autor__isnull=False),
                name='unique_suscripcion_email_autor',
            ),
            models.UniqueConstraint(
                fields=['email', 'categoria'],
                condition=Q(categoria__isnull=False),
                name='unique_suscripcion_email_categoria',
            ),
        ]
        ordering = ['-creado']

    def clean(self):
        tiene_autor = bool(self.autor_id)
        tiene_categoria = bool(self.categoria_id)
        if tiene_autor == tiene_categoria:
            raise ValidationError(
                'La suscripción debe apuntar exactamente a un autor o a una categoría (no a ambos ni a ninguno).'
            )

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        self.clean()
        super().save(*args, **kwargs)

    @property
    def destino_nombre(self):
        if self.autor_id:
            return f"Autor: {self.autor.usuario.get_full_name() or self.autor.usuario.username}"
        if self.categoria_id:
            return f"Categoría: {self.categoria.nombre}"
        return "General"

    def __str__(self):
        estado = 'Confirmada' if (self.confirmada and self.activa) else 'Pendiente/Inactiva'
        return f"{self.email} -> {self.destino_nombre} ({estado})"


# ==============================================================================
# BLOQUE 3 (RONDA 2): VISTAS DIARIAS Y MÁS POPULARES
# ==============================================================================

class VistaDiaria(models.Model):
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='vistas_diarias',
        verbose_name='Post',
    )
    fecha = models.DateField(
        default=timezone.localdate,
        verbose_name='Fecha',
    )
    cantidad = models.PositiveIntegerField(
        default=0,
        verbose_name='Cantidad de vistas',
    )

    class Meta:
        verbose_name = 'Vista diaria'
        verbose_name_plural = 'Vistas diarias'
        constraints = [
            models.UniqueConstraint(fields=['post', 'fecha'], name='unique_vista_post_fecha'),
        ]
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.post.titulo} ({self.fecha}): {self.cantidad} vista(s)"


# ==============================================================================
# BLOQUE 5 (RONDA 2): LISTAS DE LECTURA Y GUARDADOS
# ==============================================================================

class ListaLectura(models.Model):
    NOMBRE_GUARDADOS = 'Guardados'

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='listas_lectura',
        verbose_name='Usuario',
    )
    nombre = models.CharField(
        max_length=120,
        verbose_name='Nombre',
    )
    descripcion = models.CharField(
        max_length=300,
        blank=True,
        verbose_name='Descripción',
    )
    publica = models.BooleanField(
        default=False,
        verbose_name='Pública',
    )
    es_predeterminada = models.BooleanField(
        default=False,
        editable=False,
        verbose_name='Es lista Guardados',
    )
    creado = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación',
    )

    class Meta:
        verbose_name = 'Lista de lectura'
        verbose_name_plural = 'Listas de lectura'
        constraints = [
            models.UniqueConstraint(fields=['usuario', 'nombre'], name='unique_lista_usuario_nombre'),
        ]
        ordering = ['-es_predeterminada', 'nombre']

    @property
    def es_guardados(self):
        return self.es_predeterminada or self.nombre == self.NOMBRE_GUARDADOS

    def get_absolute_url(self):
        return reverse('blog:lista_detail', kwargs={'pk': self.pk})

    def delete(self, *args, **kwargs):
        if self.es_guardados:
            raise PermissionDenied('La lista predeterminada "Guardados" no se puede eliminar.')
        return super().delete(*args, **kwargs)

    def __str__(self):
        visibilidad = 'Pública' if self.publica else 'Privada'
        return f"{self.nombre} ({self.usuario.username} - {visibilidad})"


class ItemLista(models.Model):
    lista = models.ForeignKey(
        ListaLectura,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Lista de lectura',
    )
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='items_lista',
        verbose_name='Post',
    )
    agregado = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha en que se agregó',
    )

    class Meta:
        verbose_name = 'Ítem de lista de lectura'
        verbose_name_plural = 'Ítems de listas de lectura'
        constraints = [
            models.UniqueConstraint(fields=['lista', 'post'], name='unique_item_lista_post'),
        ]
        ordering = ['-agregado']

    def __str__(self):
        return f"{self.post.titulo} en {self.lista.nombre}"


# ==============================================================================
# CATEGORÍAS COMO COMUNIDADES: MEMBRESÍA Y REGLAS
# ==============================================================================

class MiembroCategoria(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='membresias_categorias',
        verbose_name='Usuario',
    )
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.CASCADE,
        related_name='miembros',
        verbose_name='Categoría',
    )
    creado = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de unión',
    )

    class Meta:
        verbose_name = 'Miembro de categoría'
        verbose_name_plural = 'Miembros de categorías'
        constraints = [
            models.UniqueConstraint(
                fields=['usuario', 'categoria'],
                name='unique_miembro_usuario_categoria',
            ),
        ]
        ordering = ['-creado']

    def __str__(self):
        return f"@{self.usuario.username} en {self.categoria.nombre}"


class ReglaCategoria(models.Model):
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.CASCADE,
        related_name='reglas',
        verbose_name='Categoría',
    )
    orden = models.PositiveSmallIntegerField(
        default=1,
        verbose_name='Orden',
    )
    titulo = models.CharField(
        max_length=120,
        verbose_name='Título',
    )
    descripcion = models.TextField(
        max_length=600,
        blank=True,
        verbose_name='Descripción',
    )

    class Meta:
        verbose_name = 'Regla de la categoría'
        verbose_name_plural = 'Reglas de la categoría'
        ordering = ['orden', 'id']

    def __str__(self):
        return f"{self.categoria.nombre} - Regla {self.orden}: {self.titulo}"

