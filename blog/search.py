import re
from django.contrib.postgres.search import (
    SearchHeadline,
    SearchQuery,
    SearchRank,
    SearchVector,
)
from django.db import connection
from django.db.models import F, Q
from django.db.models.functions import Coalesce
from django.utils.html import escape, strip_tags
from django.utils.safestring import mark_safe

from .models import Post


def generar_fragmento_sqlite(texto_html, consulta, max_chars=220):
    """
    Genera un fragmento de texto plano con los términos de búsqueda resaltados
    mediante <mark> para motores distintos de PostgreSQL (como SQLite).
    """
    texto_plano = strip_tags(texto_html or '').strip()
    if not texto_plano:
        return ''
    palabras = [re.escape(p) for p in consulta.split() if len(p) >= 2]
    if not palabras:
        return escape(texto_plano[:max_chars])

    patron = re.compile(f"({'|'.join(palabras)})", re.IGNORECASE)
    coincidencia = patron.search(texto_plano)
    if coincidencia:
        inicio = max(0, coincidencia.start() - 60)
        fin = min(len(texto_plano), coincidencia.end() + 140)
        recorte = texto_plano[inicio:fin]
        if inicio > 0:
            recorte = '...' + recorte
        if fin < len(texto_plano):
            recorte = recorte + '...'
    else:
        recorte = texto_plano[:max_chars]
        if len(texto_plano) > max_chars:
            recorte += '...'

    recorte_escapado = escape(recorte)
    resaltado = patron.sub(r'<mark>\1</mark>', recorte_escapado)
    return mark_safe(resaltado)


def buscar_posts(q, usuario=None):
    """
    Busca posts publicados según el motor de base de datos activo (`connection.vendor`):
    - En PostgreSQL: usa SearchVector, SearchQuery, SearchRank y SearchHeadline
      con configuración 'spanish', ponderando título (A), etiquetas (B) y contenido (C),
      y ordenando por relevancia (-rank).
    - En SQLite (fallback): usa objetos Q con icontains sobre título, contenido y etiquetas.
    """
    if not q or not q.strip():
        return Post.objects.none()

    termino = q.strip()
    base_qs = Post.objects.publicados().con_relaciones().con_interacciones(usuario)

    if connection.vendor == 'postgresql':
        search_query = SearchQuery(termino, config='spanish')
        vector_respaldo = (
            SearchVector('titulo', weight='A', config='spanish')
            + SearchVector('contenido', weight='C', config='spanish')
        )
        vector_efectivo = Coalesce(F('buscador'), vector_respaldo)

        return (
            base_qs.annotate(
                vector_busqueda=vector_efectivo,
                rank=SearchRank(vector_efectivo, search_query),
                fragmento=SearchHeadline(
                    'contenido',
                    search_query,
                    config='spanish',
                    start_sel='<mark>',
                    stop_sel='</mark>',
                    max_words=35,
                    min_words=15,
                ),
            )
            .filter(Q(buscador=search_query) | Q(vector_busqueda=search_query))
            .order_by('-rank', '-publicado_en')
        )

    # Fallback para SQLite y otros motores
    return (
        base_qs.filter(
            Q(titulo__icontains=termino)
            | Q(contenido__icontains=termino)
            | Q(etiquetas__nombre__icontains=termino)
        )
        .distinct()
        .order_by('-publicado_en', '-creado')
    )

