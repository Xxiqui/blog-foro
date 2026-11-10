import logging
from datetime import timedelta
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from blog.models import Notificacion, Post, RevisionPost, Seguimiento

logger = logging.getLogger(__name__)


def _ejecutar_efectos_primera_publicacion(post_id):
    """
    Efectos ejecutados de forma diferida en transaction.on_commit tras la primera publicación:
    - Notificaciones internas POST_NUEVO a los seguidores del autor.
    - Correos a los suscriptores confirmados de autor y categoría.
    - Invalidación de cachés de posts populares, autores destacados y feeds.
    """
    try:
        post = Post.objects.select_related('autor__usuario', 'categoria').get(pk=post_id)
    except Post.DoesNotExist:
        return

    from blog.emails import enviar_correos_nuevo_post
    from blog.notificaciones import notificar

    # 1. Notificaciones a seguidores
    try:
        seguidores = Seguimiento.objects.filter(autor=post.autor).select_related('seguidor')
        for seg in seguidores:
            notificar(
                destinatario=seg.seguidor,
                tipo=Notificacion.Tipo.POST_NUEVO,
                actor=post.autor.usuario,
                post=post,
            )
    except Exception as e:
        logger.error("Error al notificar seguidores en publicación de post %s: %s", post_id, e)

    # 2. Correos a suscriptores
    try:
        enviar_correos_nuevo_post(post)
    except Exception as e:
        logger.error("Error al enviar correos de boletín en post %s: %s", post_id, e)

    # 3. Variantes WebP de portada
    try:
        from blog.servicios.imagenes import generar_variantes_webp
        generar_variantes_webp(post)
    except Exception as e:
        logger.warning("Error al generar variantes WebP del post %s: %s", post_id, e)

    # 4. Invalidación de caches
    invalidar_caches_publicacion()


def invalidar_caches_publicacion():
    """Invalida cachés compartidos afectados por la publicación o despublicación de artículos."""
    cache.delete('posts_populares_7')
    cache.delete('posts_populares_30')
    cache.delete('posts_populares_0')
    cache.delete('autores_destacados')
    cache.delete('sidebar_comunidades_activas')
    cache.delete('sidebar_descubrir_comunidades')
    try:
        cache.incr('blog_ranking_version')
    except Exception:
        cache.set('blog_ranking_version', 2)


def validar_obligatorios_publicacion(post):
    """
    Valida las reglas estrictas de negocio para publicar o programar un post:
    - Título: entre 5 y 120 caracteres.
    - Contenido: al menos 50 palabras.
    - Categoría: obligatoria.
    Lanza ValidationError con diccionario de errores si alguna regla falla.
    """
    errores = {}
    titulo = (post.titulo or '').strip()
    if len(titulo) < 5:
        errores['titulo'] = 'El título debe tener al menos 5 caracteres para publicarse.'
    elif len(titulo) > 120:
        errores['titulo'] = 'El título no debe superar los 120 caracteres.'

    texto_plano = strip_tags(post.contenido or '').strip()
    palabras = len(texto_plano.split()) if texto_plano else 0
    if palabras < 50:
        errores['contenido'] = f'El contenido debe tener al menos 50 palabras para publicarse (actualmente tiene {palabras}).'

    if not post.categoria_id and not getattr(post, 'categoria', None):
        errores['categoria'] = 'Debes seleccionar una categoría antes de publicar.'

    if errores:
        raise ValidationError(errores)


def guardar_borrador(post, datos=None, usuario=None, origen_revision='auto'):
    """
    Actualiza o inicializa un post en estado Borrador con validación relajada.
    Si el título está vacío, asigna 'Sin título'.
    """
    datos = datos or {}
    if 'titulo' in datos:
        post.titulo = (datos.get('titulo') or '').strip() or 'Sin título'
    if 'contenido' in datos:
        post.contenido = datos.get('contenido') or ''
    if 'extracto' in datos:
        post.extracto = datos.get('extracto') or ''
    if 'categoria' in datos:
        post.categoria = datos.get('categoria')
    if 'categoria_id' in datos:
        post.categoria_id = datos.get('categoria_id') or None
    if 'imagen_portada' in datos:
        post.imagen_portada = datos.get('imagen_portada')

    post.estado = Post.Estado.BORRADOR
    post.programado_para = None
    post.save()

    if 'etiquetas' in datos and datos['etiquetas'] is not None:
        post.etiquetas.set(datos['etiquetas'])

    if origen_revision:
        RevisionPost.objects.create(
            post=post,
            titulo=post.titulo,
            contenido=post.contenido,
            extracto=post.extracto,
            origen=origen_revision,
        )

    return post


def publicar(post, usuario=None):
    """
    Publica un post de forma idempotente:
    - Valida obligatorios estrictos (título 5-120, >= 50 palabras, categoría).
    - Asigna `publicado_en = timezone.now()` si nunca antes había sido publicado.
    - Si es la primera vez (`not post.notificado`), dispara notificaciones y correos vía `transaction.on_commit`.
    - Si ya había sido publicado antes, actualiza el contenido sin duplicar notificaciones ni correos.
    - Guarda una `RevisionPost` con origen 'publicacion'.
    """
    validar_obligatorios_publicacion(post)

    primera_vez = not post.publicado_en or not post.notificado

    with transaction.atomic():
        post.estado = Post.Estado.PUBLICADO
        post.programado_para = None
        if not post.publicado_en:
            post.publicado_en = timezone.now()

        if primera_vez:
            post.notificado = True

        post.save()

        # Guardar revisión de publicación
        RevisionPost.objects.create(
            post=post,
            titulo=post.titulo,
            contenido=post.contenido,
            extracto=post.extracto,
            origen=RevisionPost.Origen.PUBLICACION,
        )

        if primera_vez:
            transaction.on_commit(lambda: _ejecutar_efectos_primera_publicacion(post.pk))
        else:
            transaction.on_commit(invalidar_caches_publicacion)

    return post


def programar(post, fecha_hora, usuario=None):
    """
    Programa la publicación automática de un post para una fecha y hora futura:
    - Valida obligatorios de publicación.
    - Valida que `fecha_hora` esté en el futuro al menos 5 minutos.
    - Asigna estado PROGRAMADO y guarda la revisión.
    """
    validar_obligatorios_publicacion(post)

    ahora = timezone.now()
    if timezone.is_naive(fecha_hora):
        fecha_hora = timezone.make_aware(fecha_hora, timezone.get_current_timezone())

    minimo_futuro = ahora + timedelta(minutes=5)
    if fecha_hora < minimo_futuro:
        raise ValidationError({
            'programado_para': 'La fecha y hora de programación debe ser al menos 5 minutos en el futuro.'
        })

    with transaction.atomic():
        post.estado = Post.Estado.PROGRAMADO
        post.programado_para = fecha_hora
        post.save()

        RevisionPost.objects.create(
            post=post,
            titulo=post.titulo,
            contenido=post.contenido,
            extracto=post.extracto,
            origen=RevisionPost.Origen.MANUAL,
        )

    return post


def despublicar(post, usuario=None):
    """
    Devuelve un post publicado o programado a estado Borrador y cancela programaciones pendientes.
    """
    with transaction.atomic():
        post.estado = Post.Estado.BORRADOR
        post.programado_para = None
        post.save()

        transaction.on_commit(invalidar_caches_publicacion)

    return post


def duplicar(post, usuario=None):
    """
    Crea un duplicado en borrador del post:
    - Título: 'Copia de {título}'.
    - Nuevo slug único generado automáticamente.
    - Estado Borrador, sin vistas, likes ni comentarios.
    - Copia etiquetas, categoría, contenido y extracto.
    - Retorna el nuevo post en borrador.
    """
    with transaction.atomic():
        nuevo = Post(
            titulo=f"Copia de {post.titulo}"[:250],
            autor=usuario.perfil if usuario and hasattr(usuario, 'perfil') else post.autor,
            categoria=post.categoria,
            contenido=post.contenido,
            extracto=post.extracto,
            imagen_portada=post.imagen_portada,
            estado=Post.Estado.BORRADOR,
            publicado_en=None,
            notificado=False,
            fijado_en_categoria=False,
            programado_para=None,
        )
        nuevo.save()
        if post.pk:
            nuevo.etiquetas.set(post.etiquetas.all())

        RevisionPost.objects.create(
            post=nuevo,
            titulo=nuevo.titulo,
            contenido=nuevo.contenido,
            extracto=nuevo.extracto,
            origen=RevisionPost.Origen.MANUAL,
        )

    return nuevo

