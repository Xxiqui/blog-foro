from datetime import timedelta
from django.db.models import Count, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone
from blog.models import Categoria, Comentario, MiembroCategoria, Post


def estadisticas_comunidad(categoria):
    """
    Calcula de forma exacta (sin producto cartesiano) las estadísticas de una comunidad.
    Retorna un diccionario con:
    - total_miembros: número de miembros registrados en la comunidad
    - total_posts: número de posts publicados
    - total_publicaciones: sinónimo de total_posts
    - total_comentarios: número de comentarios aprobados en posts publicados de esta comunidad
    - publicaciones_semana: número de posts publicados en los últimos 7 días
    """
    if not categoria:
        return {
            'total_miembros': 0,
            'total_posts': 0,
            'total_publicaciones': 0,
            'total_comentarios': 0,
            'publicaciones_semana': 0,
        }

    cat_id = categoria.pk if hasattr(categoria, 'pk') else categoria

    total_miembros = MiembroCategoria.objects.filter(categoria_id=cat_id).count()

    posts_qs = Post.objects.filter(categoria_id=cat_id, estado=Post.Estado.PUBLICADO)
    total_posts = posts_qs.count()

    total_comentarios = Comentario.objects.filter(
        post__categoria_id=cat_id,
        post__estado=Post.Estado.PUBLICADO,
        aprobado=True
    ).count()

    hace_una_semana = timezone.now() - timedelta(days=7)
    publicaciones_semana = posts_qs.filter(publicado_en__gte=hace_una_semana).count()

    return {
        'total_miembros': total_miembros,
        'total_posts': total_posts,
        'total_publicaciones': total_posts,
        'total_comentarios': total_comentarios,
        'publicaciones_semana': publicaciones_semana,
    }


def anotar_estadisticas_categorias(queryset=None):
    """
    Anota de forma segura y eficiente (mediante subconsultas separadas)
    las métricas de miembros y posts para un QuerySet de categorías.
    Evita estrictamente el producto cartesiano entre miembros y posts.
    """
    if queryset is None:
        queryset = Categoria.objects.all()

    sub_miembros = (
        MiembroCategoria.objects.filter(categoria=OuterRef('pk'))
        .values('categoria')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )

    sub_posts = (
        Post.objects.filter(categoria=OuterRef('pk'), estado=Post.Estado.PUBLICADO)
        .values('categoria')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )

    return queryset.annotate(
        total_miembros=Coalesce(Subquery(sub_miembros, output_field=IntegerField()), 0),
        total_posts=Coalesce(Subquery(sub_posts, output_field=IntegerField()), 0),
    )
