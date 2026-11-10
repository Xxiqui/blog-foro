from datetime import timedelta
from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, F, IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from cuentas.models import Perfil
from .models import (
    Categoria,
    Comentario,
    LikePost,
    MiembroCategoria,
    Post,
    Seguimiento,
    VistaDiaria,
    VotoUtil,
)

BOT_USER_AGENTS = (
    'bot',
    'spider',
    'crawler',
    'slurp',
    'curl',
    'wget',
    'headless',
    'python-requests',
    'scrapy',
    'lighthouse',
)


def obtener_version_cache_ranking():
    """Devuelve la versión actual del cache de rankings para invalidación limpia."""
    return cache.get('blog_ranking_version', 1)


def invalidar_cache_ranking():
    """Incrementa la versión del cache cuando cambian vistas, likes, votos, posts o seguidores."""
    actual = cache.get('blog_ranking_version', 1)
    cache.set('blog_ranking_version', actual + 1, timeout=86400)


def es_user_agent_bot(request):
    """Detección simple de bots mediante la cabecera User-Agent."""
    ua = (request.META.get('HTTP_USER_AGENT') or '').lower()
    if not ua:
        return False
    return any(patron in ua for patron in BOT_USER_AGENTS)


def registrar_vista_post(request, post):
    """
    Registra una vista en el detalle del post (una por sesión y día):
    - Ignora al autor del post, al staff/superusuarios y a bots (User-Agent).
    - Actualiza `VistaDiaria.cantidad` de forma atómica con `F()`.
    """
    if post.estado != Post.Estado.PUBLICADO:
        return False

    usuario = getattr(request, 'user', None)
    if usuario and usuario.is_authenticated:
        if usuario.id == post.autor.usuario_id or usuario.is_staff or usuario.is_superuser:
            return False

    if es_user_agent_bot(request):
        return False

    if not hasattr(request, 'session'):
        return False

    hoy = timezone.localdate()
    clave_sesion = f"{post.pk}:{hoy.isoformat()}"
    vistas_sesion = request.session.get('vistas_posts_diarias', {})
    if vistas_sesion.get(clave_sesion):
        return False

    vista_obj, _ = VistaDiaria.objects.get_or_create(
        post=post,
        fecha=hoy,
        defaults={'cantidad': 0},
    )
    VistaDiaria.objects.filter(pk=vista_obj.pk).update(cantidad=F('cantidad') + 1)

    vistas_sesion[clave_sesion] = True
    request.session['vistas_posts_diarias'] = vistas_sesion
    request.session.modified = True
    invalidar_cache_ranking()
    return True


def construir_queryset_populares(dias=7, usuario=None):
    """
    Construye el QuerySet de posts publicados anotados con la puntuación de los últimos N días:
    puntuación = vistas × 1 + likes nuevos × 3 + votos "útil" × 2 + comentarios aprobados × 2.
    Si `dias` es None o <= 0, calcula el histórico completo ("Siempre").
    """
    vistas_qs = VistaDiaria.objects.filter(post=OuterRef('pk'))
    likes_qs = LikePost.objects.filter(post=OuterRef('pk'))
    votos_qs = VotoUtil.objects.filter(post=OuterRef('pk'), util=True)
    comentarios_qs = Comentario.objects.filter(
        post=OuterRef('pk'),
        aprobado=True,
        oculto_por_reportes=False,
        eliminado=False,
    )

    if dias and dias > 0:
        ahora = timezone.now()
        fecha_inicio = timezone.localdate() - timedelta(days=dias - 1)
        dt_inicio = ahora - timedelta(days=dias)
        vistas_qs = vistas_qs.filter(fecha__gte=fecha_inicio)
        likes_qs = likes_qs.filter(creado__gte=dt_inicio)
        votos_qs = votos_qs.filter(creado__gte=dt_inicio)
        comentarios_qs = comentarios_qs.filter(creado__gte=dt_inicio)

    sub_vistas = (
        vistas_qs.values('post')
        .annotate(total=Sum('cantidad'))
        .values('total')[:1]
    )
    sub_likes = (
        likes_qs.values('post')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )
    sub_votos = (
        votos_qs.values('post')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )
    sub_comentarios = (
        comentarios_qs.values('post')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )

    qs = (
        Post.objects.publicados()
        .con_relaciones()
        .con_interacciones(usuario)
        .annotate(
            vistas_periodo=Coalesce(Subquery(sub_vistas, output_field=IntegerField()), 0),
            likes_periodo=Coalesce(Subquery(sub_likes, output_field=IntegerField()), 0),
            votos_utiles_periodo=Coalesce(Subquery(sub_votos, output_field=IntegerField()), 0),
            comentarios_periodo=Coalesce(Subquery(sub_comentarios, output_field=IntegerField()), 0),
        )
        .annotate(
            puntuacion=(
                F('vistas_periodo') * 1
                + F('likes_periodo') * 3
                + F('votos_utiles_periodo') * 2
                + F('comentarios_periodo') * 2
            )
        )
        .order_by('-puntuacion', '-publicado_en', '-id')
    )
    return qs


def posts_populares(dias=7, limite=5):
    """
    Devuelve la lista de los `limite` posts publicados más populares de los últimos `dias` días,
    con cache de 10 minutos (600 segundos).
    """
    version = obtener_version_cache_ranking()
    clave_cache = f"posts_populares:v{version}:dias_{dias}:lim_{limite}"
    resultado = cache.get(clave_cache)
    if resultado is not None:
        return resultado

    qs = construir_queryset_populares(dias=dias)
    if limite:
        qs = qs[:limite]
    resultado = list(qs)
    cache.set(clave_cache, resultado, timeout=600)
    return resultado


def construir_queryset_autores_destacados(orden='puntuacion'):
    """
    Calcula con `annotate` sin consultas N+1 la puntuación de cada autor:
    puntuación = posts publicados × 2 + seguidores × 3 + likes recibidos × 1 + votos "útil" × 1.
    Filtra autores con al menos 1 post publicado.
    """
    sub_posts = (
        Post.objects.filter(autor=OuterRef('pk'), estado=Post.Estado.PUBLICADO)
        .values('autor')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )
    sub_seguidores = (
        Seguimiento.objects.filter(autor=OuterRef('pk'))
        .values('autor')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )
    sub_likes = (
        LikePost.objects.filter(post__autor=OuterRef('pk'), post__estado=Post.Estado.PUBLICADO)
        .values('post__autor')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )
    sub_votos = (
        VotoUtil.objects.filter(
            post__autor=OuterRef('pk'),
            post__estado=Post.Estado.PUBLICADO,
            util=True,
        )
        .values('post__autor')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )

    qs = (
        Perfil.objects.select_related('usuario')
        .annotate(
            posts_publicados_count=Coalesce(Subquery(sub_posts, output_field=IntegerField()), 0),
            seguidores_count=Coalesce(Subquery(sub_seguidores, output_field=IntegerField()), 0),
            likes_recibidos_count=Coalesce(Subquery(sub_likes, output_field=IntegerField()), 0),
            votos_utiles_count=Coalesce(Subquery(sub_votos, output_field=IntegerField()), 0),
        )
        .filter(posts_publicados_count__gte=1)
        .annotate(
            puntuacion=(
                F('posts_publicados_count') * 2
                + F('seguidores_count') * 3
                + F('likes_recibidos_count') * 1
                + F('votos_utiles_count') * 1
            )
        )
    )

    if orden == 'posts':
        qs = qs.order_by('-posts_publicados_count', '-puntuacion', 'usuario__username')
    elif orden == 'seguidores':
        qs = qs.order_by('-seguidores_count', '-puntuacion', 'usuario__username')
    else:
        qs = qs.order_by('-puntuacion', '-posts_publicados_count', 'usuario__username')

    return qs


def autores_destacados(limite=None, orden='puntuacion'):
    """
    Devuelve la lista de autores con al menos 1 post publicado ordenados por `orden`,
    con cache de 30 minutos (1800 segundos).
    """
    if limite is None:
        limite = getattr(settings, 'AUTOR_DESTACADO_TOP_N', 4)

    version = obtener_version_cache_ranking()
    clave_cache = f"autores_destacados:v{version}:orden_{orden}:lim_{limite}"
    resultado = cache.get(clave_cache)
    if resultado is not None:
        return resultado

    qs = construir_queryset_autores_destacados(orden=orden)
    if limite:
        qs = qs[:limite]
    resultado = list(qs)
    cache.set(clave_cache, resultado, timeout=1800)
    return resultado


def obtener_mapa_insignias_autores():
    """
    Calcula y almacena en cache por 30 minutos las métricas e insignias de todos los perfiles
    para evitar consultas N+1 al invocar el template tag `{% insignia perfil %}`.
    """
    version = obtener_version_cache_ranking()
    clave_cache = f"mapa_insignias_autores:v{version}"
    mapa = cache.get(clave_cache)
    if mapa is not None:
        return mapa

    top_n = getattr(settings, 'AUTOR_DESTACADO_TOP_N', 3)
    umbral_puntos = getattr(settings, 'AUTOR_DESTACADO_UMBRAL_PUNTOS', 8)
    max_nuevo = getattr(settings, 'AUTOR_INSIGNIA_NUEVO_MAX_POSTS', 3)
    min_activo = getattr(settings, 'AUTOR_INSIGNIA_ACTIVO_MIN_POSTS', 5)

    # Autores con al menos 1 post ordenados por puntuación
    autores_con_posts = list(construir_queryset_autores_destacados(orden='puntuacion'))
    ids_top = {a.pk for a in autores_con_posts[:top_n]}

    mapa = {}
    for autor in autores_con_posts:
        insignias = []
        posts_count = autor.posts_publicados_count
        puntos = autor.puntuacion

        if posts_count < max_nuevo:
            insignias.append({'nombre': 'Nuevo', 'clase': 'badge-insignia badge-insignia-nuevo bg-info-subtle text-info-emphasis border-info-subtle'})
        elif posts_count >= min_activo or posts_count >= max_nuevo:
            insignias.append({'nombre': 'Activo', 'clase': 'badge-insignia badge-insignia-activo bg-success-subtle text-success-emphasis border-success-subtle'})
        # "Destacado" solo se otorga a los mejores: dentro del top N (3) Y superando el umbral mínimo de puntuación
        if autor.pk in ids_top and puntos >= umbral_puntos:
            insignias.append({'nombre': 'Destacado', 'clase': 'badge-insignia badge-insignia-destacado bg-warning-subtle text-warning-emphasis border-warning-subtle'})

        mapa[autor.pk] = {
            'posts_publicados': posts_count,
            'seguidores': autor.seguidores_count,
            'puntuacion': puntos,
            'insignias': insignias,
        }

    cache.set(clave_cache, mapa, timeout=1800)
    return mapa


def calcular_insignias_perfil(perfil):
    """
    Devuelve la lista de insignias calculadas (no guardadas) para un `Perfil`:
    - "Nuevo": menos de AUTOR_INSIGNIA_NUEVO_MAX_POSTS (3) posts publicados.
    - "Activo": AUTOR_INSIGNIA_ACTIVO_MIN_POSTS (5) o más posts publicados.
    - "Destacado": al menos 1 post publicado y dentro del top configurado o sobre el umbral de puntos.
    """
    if not perfil or not perfil.pk:
        return []

    mapa = obtener_mapa_insignias_autores()
    if perfil.pk in mapa:
        return mapa[perfil.pk]['insignias']

    # Si el autor tiene 0 posts publicados, recibe la insignia "Nuevo" (< 3 posts)
    max_nuevo = getattr(settings, 'AUTOR_INSIGNIA_NUEVO_MAX_POSTS', 3)
    if max_nuevo > 0:
        return [{'nombre': 'Nuevo', 'clase': 'bg-info-subtle text-info-emphasis border-info-subtle'}]
    return []


def construir_queryset_categorias_metricas():
    """
    Anota en una sola consulta sin distorsión por JOINs:
    - `vistas_semana`: suma de `VistaDiaria.cantidad` en los últimos 7 días.
    - `publicaciones_semana`: posts publicados en los últimos 7 días.
    - `total_posts`: total de posts publicados en la categoría.
    - `total_miembros`: total de miembros en `MiembroCategoria`.
    """
    hoy = timezone.localdate()
    fecha_inicio = hoy - timedelta(days=6)
    dt_inicio = timezone.now() - timedelta(days=7)

    sub_vistas_semana = (
        VistaDiaria.objects.filter(
            post__categoria=OuterRef('pk'),
            post__estado=Post.Estado.PUBLICADO,
            fecha__gte=fecha_inicio,
        )
        .values('post__categoria')
        .annotate(total=Sum('cantidad'))
        .values('total')[:1]
    )
    sub_posts_semana = (
        Post.objects.filter(
            categoria=OuterRef('pk'),
            estado=Post.Estado.PUBLICADO,
            publicado_en__gte=dt_inicio,
        )
        .values('categoria')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )
    sub_total_posts = (
        Post.objects.filter(
            categoria=OuterRef('pk'),
            estado=Post.Estado.PUBLICADO,
        )
        .values('categoria')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )
    sub_total_miembros = (
        MiembroCategoria.objects.filter(categoria=OuterRef('pk'))
        .values('categoria')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )

    return Categoria.objects.annotate(
        vistas_semana=Coalesce(Subquery(sub_vistas_semana, output_field=IntegerField()), 0),
        publicaciones_semana=Coalesce(Subquery(sub_posts_semana, output_field=IntegerField()), 0),
        posts_semana=Coalesce(Subquery(sub_posts_semana, output_field=IntegerField()), 0),
        total_posts=Coalesce(Subquery(sub_total_posts, output_field=IntegerField()), 0),
        total_miembros=Coalesce(Subquery(sub_total_miembros, output_field=IntegerField()), 0),
    ).order_by('nombre')


def obtener_categorias_con_metricas():
    """
    Devuelve la lista de categorías anotadas con métricas semanales y totales,
    cacheada durante 10 minutos (600 segundos).
    """
    version = obtener_version_cache_ranking()
    clave_cache = f"categorias_metricas:v{version}"
    resultado = cache.get(clave_cache)
    if resultado is not None:
        return resultado

    resultado = list(construir_queryset_categorias_metricas())
    cache.set(clave_cache, resultado, timeout=600)
    return resultado


def obtener_comunidades_descubrir(usuario=None, limite=4):
    """
    Devuelve hasta `limite` (4) categorías a las que el usuario aún no se ha unido
    (o todas si es visitante), ordenadas por vistas semanales, miembros y nombre.
    """
    categorias = obtener_categorias_con_metricas()
    unidas_ids = set()
    if usuario and getattr(usuario, 'is_authenticated', False):
        unidas_ids = set(
            MiembroCategoria.objects.filter(usuario=usuario).values_list('categoria_id', flat=True)
        )

    candidatas = []
    for cat in categorias:
        cat.ya_unido = cat.pk in unidas_ids
        if not cat.ya_unido:
            candidatas.append(cat)

    candidatas.sort(
        key=lambda c: (-getattr(c, 'vistas_semana', 0), -getattr(c, 'total_miembros', 0), c.nombre)
    )
    return candidatas[:limite]


