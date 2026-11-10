from datetime import timedelta
import json
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import connection
from django.db.models import (
    BooleanField,
    Count,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import cache_control
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from cuentas.models import Perfil
from .emails import enviar_correo_confirmacion_suscripcion
from .forms import (
    CategoriaForm,
    ComentarioEdicionForm,
    ComentarioForm,
    ContactoForm,
    EtiquetaForm,
    ListaLecturaForm,
    PostForm,
    ReporteComentarioForm,
    SuscripcionForm,
)
from .models import (
    Categoria,
    Comentario,
    Etiqueta,
    ItemLista,
    LikeComentario,
    LikePost,
    ListaLectura,
    MiembroCategoria,
    Notificacion,
    Post,
    ReglaCategoria,
    ReporteComentario,
    Seguimiento,
    Suscripcion,
    VistaDiaria,
    VotoUtil,
)
from .notificaciones import (
    eliminar_notificacion,
    notificar,
    notificar_menciones_comentario,
    notificar_reporte_comentario,
    notificar_respuesta_y_menciones_comentario,
)
from .populares import (
    autores_destacados,
    construir_queryset_autores_destacados,
    construir_queryset_categorias_metricas,
    construir_queryset_populares,
    invalidar_cache_ranking,
    obtener_categorias_con_metricas,
    obtener_comunidades_descubrir,
    posts_populares,
    registrar_vista_post,
)
from .ratelimit import es_peticion_ajax, limitar_tasa, login_requerido_interaccion
from .search import buscar_posts
from .templatetags.blog_extras import sanear_y_generar_toc

User = get_user_model()


def anotar_puntuacion_mejores(qs):
    """
    Calcula la puntuación con decaimiento temporal en SQL:
    (votos + 0.5 * comentarios + 1) / (horas + 2)^1.5
    """
    vendor = connection.vendor
    sub_likes_sql = "(SELECT COUNT(id) FROM blog_likepost WHERE blog_likepost.post_id = blog_post.id)"
    sub_comentarios_sql = "(SELECT COUNT(id) FROM blog_comentario WHERE blog_comentario.post_id = blog_post.id AND blog_comentario.aprobado = 1 AND blog_comentario.oculto_por_reportes = 0 AND blog_comentario.eliminado = 0)"
    if vendor == 'sqlite':
        horas_sql = "MAX(0.0, (julianday('now') - julianday(COALESCE(blog_post.publicado_en, blog_post.creado))) * 24.0)"
    else:
        horas_sql = "GREATEST(0.0, EXTRACT(EPOCH FROM (NOW() - COALESCE(blog_post.publicado_en, blog_post.creado))) / 3600.0)"
    formula_sql = f"(COALESCE({sub_likes_sql}, 0) + 0.5 * COALESCE({sub_comentarios_sql}, 0) + 1.0) / (POWER(({horas_sql} + 2.0), 1.5))"
    return qs.extra(select={'puntuacion_mejores': formula_sql}).order_by('-puntuacion_mejores', '-publicado_en', '-id')


def aplicar_orden_posts(qs, orden='mejores', mantener_orden_busqueda=False, periodo=None, usuario=None):
    """
    Aplica el ordenamiento solicitado (`?orden=mejores|recientes|populares|siguiendo|utiles`):
    - `mejores`: puntuación con decaimiento temporal en SQL: (votos + 0.5×comentarios + 1) / (horas + 2)^1.5.
    - `recientes`: por `-publicado_en`, `-creado`.
    - `populares`: por popularidad (vistas×1 + likes×3 + votos_útil×2 + comentarios×2) filtrable por periodo.
    - `siguiendo`: publicaciones de autores seguidos por el usuario autenticado.
    - `utiles`: compatible con votos de utilidad histórica.
    """
    orden_norm = (orden or '').strip().lower()

    if orden_norm == 'mejores':
        return anotar_puntuacion_mejores(qs)

    if orden_norm == 'siguiendo':
        if usuario and usuario.is_authenticated:
            siguiendo_ids = list(usuario.siguiendo_autores.values_list('autor_id', flat=True))
            return qs.filter(autor_id__in=siguiendo_ids).order_by('-publicado_en', '-creado', '-id')
        return qs.order_by('-publicado_en', '-creado', '-id')

    if orden_norm in ('utiles', 'mas_utiles'):
        sub_total_votos = (
            VotoUtil.objects.filter(post=OuterRef('pk'))
            .values('post')
            .annotate(total=Count('id'))
            .values('total')[:1]
        )
        sub_votos_pos = (
            VotoUtil.objects.filter(post=OuterRef('pk'), util=True)
            .values('post')
            .annotate(total=Count('id'))
            .values('total')[:1]
        )
        return (
            qs.annotate(
                total_votos_util=Coalesce(Subquery(sub_total_votos, output_field=IntegerField()), 0),
                votos_util_positivos=Coalesce(Subquery(sub_votos_pos, output_field=IntegerField()), 0),
            )
            .filter(total_votos_util__gte=3)
            .order_by('-votos_util_positivos', '-total_votos_util', '-publicado_en', '-id')
        )

    if orden_norm == 'populares':
        if periodo == 'hoy':
            desde = timezone.now() - timedelta(days=1)
            qs = qs.filter(Q(publicado_en__gte=desde) | Q(creado__gte=desde))
        elif periodo == 'semana':
            desde = timezone.now() - timedelta(days=7)
            qs = qs.filter(Q(publicado_en__gte=desde) | Q(creado__gte=desde))
        elif periodo == 'mes':
            desde = timezone.now() - timedelta(days=30)
            qs = qs.filter(Q(publicado_en__gte=desde) | Q(creado__gte=desde))

        sub_vistas = (
            VistaDiaria.objects.filter(post=OuterRef('pk'))
            .values('post')
            .annotate(total=Sum('cantidad'))
            .values('total')[:1]
        )
        sub_likes = (
            LikePost.objects.filter(post=OuterRef('pk'))
            .values('post')
            .annotate(total=Count('id'))
            .values('total')[:1]
        )
        sub_votos = (
            VotoUtil.objects.filter(post=OuterRef('pk'), util=True)
            .values('post')
            .annotate(total=Count('id'))
            .values('total')[:1]
        )
        sub_coms = (
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
        return (
            qs.annotate(
                vistas_pop=Coalesce(Subquery(sub_vistas, output_field=IntegerField()), 0),
                likes_pop=Coalesce(Subquery(sub_likes, output_field=IntegerField()), 0),
                votos_pop=Coalesce(Subquery(sub_votos, output_field=IntegerField()), 0),
                coms_pop=Coalesce(Subquery(sub_coms, output_field=IntegerField()), 0),
            )
            .annotate(
                puntuacion=(
                    F('vistas_pop') * 1
                    + F('likes_pop') * 3
                    + F('votos_pop') * 2
                    + F('coms_pop') * 2
                )
            )
            .order_by('-puntuacion', '-publicado_en', '-id')
        )

    if mantener_orden_busqueda and not orden_norm:
        return qs

    return qs.order_by('-publicado_en', '-creado', '-id')


def obtener_contexto_sidebar(request):
    """
    Construye los datos compartidos de la barra lateral sin consultas N+1:
    - Categorías con métricas semanales y contador de posts publicados (cacheado 10 min).
    - Comunidades para descubrir (hasta 4 categorías a las que el usuario no se ha unido).
    - Nube de etiquetas con 4 niveles de tamaño según su uso en posts publicados.
    - Más populares de la semana.
    - Autores destacados (top 3-4) con estado `ya_seguido` para el botón Seguir.
    - Formulario de suscripción por correo.
    """
    categorias_qs = obtener_categorias_con_metricas()
    comunidades_descubrir = obtener_comunidades_descubrir(request.user, limite=4)

    etiquetas_lista = list(
        Etiqueta.objects.annotate(
            total_posts=Count(
                'posts',
                filter=Q(posts__estado=Post.Estado.PUBLICADO),
                distinct=True,
            )
        )
        .filter(total_posts__gt=0)
        .order_by('nombre')
    )
    if etiquetas_lista:
        conteos = [t.total_posts for t in etiquetas_lista]
        min_c, max_c = min(conteos), max(conteos)
        rango = max(1, max_c - min_c)
        for tag in etiquetas_lista:
            if max_c == min_c:
                tag.tamanio_nube = 2
            else:
                ratio = (tag.total_posts - min_c) / rango
                if ratio >= 0.75:
                    tag.tamanio_nube = 4
                elif ratio >= 0.45:
                    tag.tamanio_nube = 3
                elif ratio >= 0.2:
                    tag.tamanio_nube = 2
                else:
                    tag.tamanio_nube = 1

    autores_top = list(
        autores_destacados(
            limite=getattr(settings, 'AUTOR_DESTACADO_TOP_N', 3),
            orden='puntuacion',
        )
    )
    seguidos_ids = set()
    if request.user.is_authenticated and autores_top:
        seguidos_ids = set(
            Seguimiento.objects.filter(
                seguidor=request.user,
                autor_id__in=[a.pk for a in autores_top],
            ).values_list('autor_id', flat=True)
        )
    for autor in autores_top:
        autor.ya_seguido = autor.pk in seguidos_ids

    return {
        'categorias': categorias_qs,
        'comunidades_descubrir': comunidades_descubrir,
        'etiquetas': etiquetas_lista,
        'posts_populares_semana': posts_populares(dias=7, limite=5),
        'autores_top': autores_top,
        'form_suscripcion_sidebar': SuscripcionForm(user=request.user),
    }


# ==============================================================================
# VISTAS PÚBLICAS
# ==============================================================================

class FeedNovedadesView(View):
    """
    Endpoint para sondeo de publicaciones nuevas cada 60s:
    /feed/novedades/?ultimo_id=<id>
    Devuelve JSON { 'nuevos_count': n } sin exponer datos privados.
    """
    def get(self, request, *args, **kwargs):
        ultimo_id = request.GET.get('ultimo_id')
        try:
            ultimo_id = int(ultimo_id)
        except (TypeError, ValueError):
            return JsonResponse({'nuevos_count': 0})

        nuevos = Post.objects.publicados().filter(id__gt=ultimo_id).count()
        return JsonResponse({'nuevos_count': nuevos})


class ComentariosNovedadesView(View):
    """
    Endpoint para sondeo de comentarios nuevos en un artículo cada 45s:
    /post/<slug>/comentarios/novedades/?ultimo_id=<id>
    Devuelve JSON { 'nuevos_count': n }.
    """
    def get(self, request, slug, *args, **kwargs):
        ultimo_id = request.GET.get('ultimo_id')
        try:
            ultimo_id = int(ultimo_id)
        except (TypeError, ValueError):
            return JsonResponse({'nuevos_count': 0})

        post = get_object_or_404(Post.objects.publicados(), slug=slug)
        nuevos = post.comentarios.filter(aprobado=True, id__gt=ultimo_id).count()
        return JsonResponse({'nuevos_count': nuevos, 'total_nuevos': nuevos})


class PostListView(ListView):
    model = Post
    template_name = 'blog/post_list.html'
    context_object_name = 'posts'
    paginate_by = 15

    def get_paginate_by(self, queryset):
        return getattr(settings, 'FEED_PAGINATE_BY', self.paginate_by)

    def get_queryset(self):
        self.orden_actual = (self.request.GET.get('orden') or 'mejores').lower()
        if self.orden_actual not in ('mejores', 'recientes', 'populares', 'siguiendo', 'utiles'):
            self.orden_actual = 'mejores'

        self.filtro_comunidad = (self.request.GET.get('comunidad') or '').strip()
        self.filtro_etiqueta = (self.request.GET.get('etiqueta') or '').strip()
        self.filtro_periodo = (self.request.GET.get('periodo') or '').strip().lower()

        # Cache de 60s para anónimos en 'mejores' sin filtros con versión para invalidación instantánea
        ranking_version = cache.get('blog_ranking_version', 1)
        cache_key = f'feed_mejores_anon_ids_v{ranking_version}'
        if (
            not self.request.user.is_authenticated
            and self.orden_actual == 'mejores'
            and not self.filtro_comunidad
            and not self.filtro_etiqueta
            and not self.filtro_periodo
        ):
            cached_ids = cache.get(cache_key)
            if cached_ids is not None:
                from django.db.models import Case, When
                orden_preservado = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(cached_ids)])
                return (
                    Post.objects.filter(id__in=cached_ids)
                    .con_relaciones()
                    .con_interacciones()
                    .order_by(orden_preservado)
                )

        qs = (
            Post.objects.publicados()
            .con_relaciones()
            .con_interacciones(self.request.user)
        )

        if self.filtro_comunidad:
            qs = qs.filter(categoria__slug=self.filtro_comunidad)
        if self.filtro_etiqueta:
            qs = qs.filter(etiquetas__slug=self.filtro_etiqueta)

        qs = aplicar_orden_posts(
            qs,
            orden=self.orden_actual,
            periodo=self.filtro_periodo,
            usuario=self.request.user,
        )

        if (
            not self.request.user.is_authenticated
            and self.orden_actual == 'mejores'
            and not self.filtro_comunidad
            and not self.filtro_etiqueta
            and not self.filtro_periodo
        ):
            ids_a_cachear = list(qs.values_list('id', flat=True)[:150])
            cache.set(cache_key, ids_a_cachear, 60)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(obtener_contexto_sidebar(self.request))

        # Determinar vista: cookie 'vista_feed' o query param 'vista', por defecto 'compacta'
        vista = self.request.GET.get('vista') or self.request.COOKIES.get('vista_feed', 'compacta')
        if vista not in ('compacta', 'tarjetas'):
            vista = 'compacta'

        context['vista_feed'] = vista
        context['orden_actual'] = self.orden_actual
        context['filtro_comunidad'] = self.filtro_comunidad
        context['filtro_etiqueta'] = self.filtro_etiqueta
        context['filtro_periodo'] = self.filtro_periodo
        context['comunidades_filtro'] = Categoria.objects.all()[:12]
        context['etiquetas_filtro'] = Etiqueta.objects.all()[:15]

        # Post destacado: en página 1 si no hay filtros y orden es recientes o mejores
        page_obj = context.get('page_obj')
        es_primera_pagina = (not page_obj) or (page_obj.number == 1)
        sin_filtros = (
            self.orden_actual in ('mejores', 'recientes')
            and not self.request.GET.get('q')
            and not self.filtro_comunidad
            and not self.filtro_etiqueta
        )

        post_destacado = None
        if es_primera_pagina and sin_filtros:
            populares = context.get('posts_populares_semana') or []
            if populares and getattr(populares[0], 'puntuacion', 0) > 0:
                post_destacado = (
                    Post.objects.publicados()
                    .con_relaciones()
                    .con_interacciones(self.request.user)
                    .filter(pk=populares[0].pk)
                    .first()
                )
            if not post_destacado and context['posts']:
                post_destacado = context['posts'][0]

        context['post_destacado'] = post_destacado
        if post_destacado:
            context['posts_cuadricula'] = [
                p for p in context['posts'] if p.pk != post_destacado.pk
            ]
        else:
            context['posts_cuadricula'] = list(context['posts'])
        return context

    def render_to_response(self, context, **response_kwargs):
        if getattr(self.request, 'htmx', False) and self.request.GET.get('page'):
            template = 'blog/includes/_feed_pagina.html'
        else:
            template = self.get_template_names()

        response = self.response_class(
            request=self.request,
            template=template,
            context=context,
            using=self.template_engine,
            **response_kwargs
        )
        if self.request.GET.get('vista') in ('compacta', 'tarjetas'):
            response.set_cookie('vista_feed', self.request.GET['vista'], max_age=365*24*60*60, samesite='Lax')
        return response


class PostPorCategoriaView(ListView):
    model = Post
    template_name = 'blog/categoria_hub.html'
    context_object_name = 'posts'
    paginate_by = 6

    def get_queryset(self):
        self.categoria = get_object_or_404(
            construir_queryset_categorias_metricas(),
            slug=self.kwargs['slug'],
        )
        self.orden_actual = (self.request.GET.get('orden') or 'recientes').lower()
        if self.orden_actual not in ('recientes', 'populares', 'mejores', 'utiles'):
            self.orden_actual = 'recientes'
        qs = (
            Post.objects.publicados()
            .con_relaciones()
            .con_interacciones(self.request.user)
            .filter(categoria=self.categoria)
        )
        return aplicar_orden_posts(qs, self.orden_actual)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(obtener_contexto_sidebar(self.request))
        context['categoria_actual'] = self.categoria
        context['orden_actual'] = self.orden_actual
        context['post_destacado'] = None
        context['posts_cuadricula'] = list(context['posts'])
        context['form_suscripcion'] = SuscripcionForm(
            user=self.request.user,
            initial={'categoria_id': self.categoria.pk},
        )
        if self.request.user.is_authenticated:
            context['es_miembro_categoria'] = MiembroCategoria.objects.filter(
                usuario=self.request.user,
                categoria=self.categoria,
            ).exists()
        else:
            context['es_miembro_categoria'] = False

        context['reglas_categoria'] = list(self.categoria.reglas.order_by('orden', 'id'))

        # Posts fijados en la categoría (máximo 3); si no hay fijados, los 3 más populares
        fijados = list(
            Post.objects.publicados()
            .con_relaciones()
            .con_interacciones(self.request.user)
            .filter(categoria=self.categoria, fijado_en_categoria=True)
            .order_by('-publicado_en', '-id')[:3]
        )
        if fijados:
            context['posts_destacados_categoria'] = fijados
            context['es_respaldo_populares'] = False
        else:
            respaldo = list(
                construir_queryset_populares(dias=None, usuario=self.request.user)
                .filter(categoria=self.categoria)[:3]
            )
            context['posts_destacados_categoria'] = respaldo
            context['es_respaldo_populares'] = True

        return context


class PostPorEtiquetaView(ListView):
    model = Post
    template_name = 'blog/post_list.html'
    context_object_name = 'posts'
    paginate_by = 6

    def get_queryset(self):
        self.etiqueta = get_object_or_404(Etiqueta, slug=self.kwargs['slug'])
        self.orden_actual = (self.request.GET.get('orden') or 'recientes').lower()
        if self.orden_actual not in ('recientes', 'populares', 'utiles'):
            self.orden_actual = 'recientes'
        qs = (
            Post.objects.publicados()
            .con_relaciones()
            .con_interacciones(self.request.user)
            .filter(etiquetas=self.etiqueta)
        )
        return aplicar_orden_posts(qs, self.orden_actual)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(obtener_contexto_sidebar(self.request))
        context['etiqueta_actual'] = self.etiqueta
        context['orden_actual'] = self.orden_actual
        context['post_destacado'] = None
        context['posts_cuadricula'] = list(context['posts'])
        return context


@method_decorator(xframe_options_exempt, name='dispatch')
@method_decorator(cache_control(public=True, max_age=300), name='dispatch')
class PostEmbedView(View):
    """
    Vista embebible (`/post/<slug>/embed/`, solo GET) independiente de `base.html`:
    - Devuelve 200 solo para posts publicados (404 para borradores).
    - Exenta de `X-Frame-Options` mediante `@xframe_options_exempt`.
    - Soporta `?tema=claro|oscuro`.
    """

    template_name = 'blog/post_embed.html'

    def get(self, request, slug, *args, **kwargs):
        post = get_object_or_404(
            Post.objects.publicados().con_relaciones(),
            slug=slug,
        )
        tema_param = (request.GET.get('tema') or 'claro').strip().lower()
        tema_bs = 'dark' if tema_param in ('oscuro', 'dark') else 'light'
        url_post_absoluta = request.build_absolute_uri(post.get_absolute_url())
        return render(
            request,
            self.template_name,
            {
                'post': post,
                'tema_bs': tema_bs,
                'url_post_absoluta': url_post_absoluta,
                'site_name': getattr(settings, 'SITE_NAME', 'Blog con Panel de Autor'),
            },
        )


class PostDetailView(DetailView):
    model = Post
    template_name = 'blog/post_detail.html'
    context_object_name = 'post'
    slug_url_kwarg = 'slug'

    def get_queryset(self):
        # Los borradores nunca son accesibles públicamente (devuelve 404)
        return (
            Post.objects.publicados()
            .con_relaciones()
            .con_interacciones(self.request.user)
        )

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        registrar_vista_post(request, self.object)
        context = self.get_context_data(object=self.object)
        if request.headers.get('HX-Request') and request.GET.get('comentarios_solo'):
            return render(request, 'blog/includes/_lista_comentarios.html', context)
        return self.render_to_response(context)

    def obtener_arbol_comentarios(self):
        """
        Obtiene todos los comentarios del post en UNA sola consulta SQL
        (`select_related('autor', 'autor__perfil')` y anotaciones de likes)
        y construye el árbol jerárquico en Python hasta `COMENTARIO_PROFUNDIDAD_MAX`.
        """
        qs = (
            self.object.comentarios.filter(aprobado=True)
            .select_related('post', 'post__autor', 'autor', 'autor__perfil')
            .annotate(total_likes=Count('likes', distinct=True))
        )
        if self.request.user.is_authenticated:
            subquery_like = LikeComentario.objects.filter(
                comentario=OuterRef('pk'),
                usuario=self.request.user,
            )
            qs = qs.annotate(ya_dio_like=Exists(subquery_like))
        else:
            qs = qs.annotate(ya_dio_like=Value(False, output_field=BooleanField()))

        todos = list(qs.order_by('creado', 'id'))
        por_id = {}
        hijos_por_padre = {}
        total_visibles = 0

        for com in todos:
            com.puede_editar_actual = com.puede_editar(self.request.user)
            com.puede_borrar_actual = com.puede_borrar(self.request.user)
            com.hijos = []
            por_id[com.pk] = com
            if not com.eliminado and not com.oculto_por_reportes:
                total_visibles += 1

        raices = []
        for com in todos:
            if com.padre_id and com.padre_id in por_id:
                hijos_por_padre.setdefault(com.padre_id, []).append(com)
            elif not com.padre_id:
                raices.append(com)

        max_prof = getattr(settings, 'COMENTARIO_PROFUNDIDAD_MAX', 4)

        def poblar_subarbol(nodo, nivel):
            nodo.nivel = min(nivel, max_prof)
            hijos_directos = hijos_por_padre.get(nodo.pk, [])
            hijos_filtrados = []
            descendientes_visibles = 0

            for hijo in hijos_directos:
                tiene_contenido, desc_hijo = poblar_subarbol(hijo, min(nivel + 1, max_prof))
                if tiene_contenido:
                    hijos_filtrados.append(hijo)
                    es_hijo_visible = not hijo.eliminado and not hijo.oculto_por_reportes
                    descendientes_visibles += (1 if es_hijo_visible else 0) + desc_hijo

            nodo.hijos = hijos_filtrados
            nodo.total_descendientes = descendientes_visibles
            nodo.plegado_por_defecto = (nodo.nivel > 2) or (nodo.total_descendientes > 2)

            es_nodo_visible = not nodo.eliminado and not nodo.oculto_por_reportes
            tiene_contenido_subarbol = es_nodo_visible or bool(hijos_filtrados)
            return tiene_contenido_subarbol, descendientes_visibles

        raices_visibles = []
        for r in raices:
            mostrar, _ = poblar_subarbol(r, 1)
            if mostrar:
                raices_visibles.append(r)

        orden = (self.request.GET.get('orden_comentarios') or 'mejores').lower()
        if orden == 'recientes':
            raices_visibles.sort(key=lambda c: (c.creado, c.id), reverse=True)
        elif orden == 'antiguos':
            raices_visibles.sort(key=lambda c: (c.creado, c.id))
        else:
            orden = 'mejores'
            raices_visibles.sort(key=lambda c: (getattr(c, 'total_likes', 0), c.creado, c.id), reverse=True)

        ultimo_id = max([c.id for c in todos], default=0)
        return raices_visibles, total_visibles, ultimo_id, orden

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        raices_comentarios, total_visibles, ultimo_id, orden_com = self.obtener_arbol_comentarios()
        context['comentarios'] = raices_comentarios
        context['comentarios_raiz'] = raices_comentarios
        context['total_comentarios_visibles'] = total_visibles
        context['ultimo_comentario_id'] = ultimo_id
        context['orden_comentarios'] = orden_com
        context['profundidad_max_comentarios'] = getattr(settings, 'COMENTARIO_PROFUNDIDAD_MAX', 4)

        responder_id = self.request.GET.get('responder')
        context['responder_a_id'] = int(responder_id) if (responder_id and str(responder_id).isdigit()) else None
        context['responder_id'] = context['responder_a_id']

        if 'form_comentario' not in context:
            initial_com = {'padre_id': context['responder_a_id']} if context['responder_a_id'] else {}
            context['form_comentario'] = ComentarioForm(
                user=self.request.user,
                post=self.object,
                initial=initial_com,
            )
        context['form_reporte'] = ReporteComentarioForm()

        # Contenido saneado con IDs en h2/h3 y Tabla de Contenidos (se muestra si hay >= 3 encabezados)
        contenido_saneado, toc_items = sanear_y_generar_toc(self.object.contenido)
        context['contenido_saneado'] = contenido_saneado
        context['toc_items'] = toc_items if len(toc_items) >= 3 else []

        # Artículos relacionados (misma categoría o etiquetas compartidas, máximo 4)
        condicion_rel = Q()
        if self.object.categoria_id:
            condicion_rel |= Q(categoria_id=self.object.categoria_id)
        etiquetas_ids = list(self.object.etiquetas.values_list('id', flat=True))
        if etiquetas_ids:
            condicion_rel |= Q(etiquetas__id__in=etiquetas_ids)

        if condicion_rel:
            context['posts_relacionados'] = list(
                Post.objects.publicados()
                .con_relaciones()
                .con_interacciones(self.request.user)
                .filter(condicion_rel)
                .exclude(pk=self.object.pk)
                .distinct()[:4]
            )
            context['seguir_leyendo_posts'] = list(
                Post.objects.publicados()
                .con_relaciones()
                .con_interacciones(self.request.user)
                .filter(condicion_rel)
                .exclude(pk=self.object.pk)
                .distinct()[:5]
            )
        else:
            context['posts_relacionados'] = []
            context['seguir_leyendo_posts'] = list(
                Post.objects.publicados()
                .con_relaciones()
                .con_interacciones(self.request.user)
                .exclude(pk=self.object.pk)[:5]
            )

        if self.object.categoria_id and self.request.user.is_authenticated:
            context['es_miembro_comunidad'] = MiembroCategoria.objects.filter(
                usuario=self.request.user,
                categoria_id=self.object.categoria_id,
            ).exists()
        else:
            context['es_miembro_comunidad'] = False

        if self.object.categoria:
            context['total_miembros_comunidad'] = self.object.categoria.miembros.count()
        else:
            context['total_miembros_comunidad'] = 0

        # Estadísticas de "¿Te fue útil?"
        votos_qs = self.object.votos_utilidad.all()
        context['total_votos_utilidad'] = votos_qs.count()
        context['votos_utiles'] = votos_qs.filter(util=True).count()
        if self.request.user.is_authenticated:
            voto_usuario = votos_qs.filter(usuario=self.request.user).first()
            context['mi_voto_util'] = voto_usuario.util if voto_usuario else None
        else:
            context['mi_voto_util'] = None

        # Seguimiento al autor y vistas
        context['total_seguidores_autor'] = self.object.autor.seguidores.count()
        if self.request.user.is_authenticated:
            context['siguiendo_autor'] = Seguimiento.objects.filter(
                seguidor=self.request.user,
                autor=self.object.autor,
            ).exists()
        else:
            context['siguiendo_autor'] = False

        context['total_vistas'] = (
            self.object.vistas_diarias.aggregate(total=Sum('cantidad'))['total'] or 0
        )
        context['url_absoluta'] = self.request.build_absolute_uri(self.object.get_absolute_url())
        return context

    @method_decorator(limitar_tasa('crear_comentario', 20, 60))
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = ComentarioForm(request.POST, user=request.user, post=self.object)
        if form.is_valid():
            comentario = form.save(commit=False)
            comentario.post = self.object
            comentario.padre = form.cleaned_data.get('padre_resuelto')
            if request.user.is_authenticated:
                comentario.autor = request.user

            # Excepción: los comentarios/respuestas del autor del post o del staff se aprueban automáticamente
            es_autor_o_staff = (
                request.user.is_authenticated
                and (
                    request.user.id == self.object.autor.usuario_id
                    or request.user.is_staff
                    or request.user.is_superuser
                )
            )
            comentario.aprobado = bool(es_autor_o_staff)
            comentario.save()

            actor_actual = request.user if request.user.is_authenticated else None

            if comentario.aprobado:
                # Si está auto-aprobado, avisar al autor del comentario padre y menciones inmediatamente
                notificar_respuesta_y_menciones_comentario(comentario)
                # Si el autor del post no es el autor del comentario padre (o no hay padre), avisarle una sola vez
                padre_autor_id = comentario.padre.autor_id if (comentario.padre_id and comentario.padre) else None
                if padre_autor_id != self.object.autor.usuario_id:
                    notificar(
                        destinatario=self.object.autor.usuario,
                        tipo=Notificacion.Tipo.COMENTARIO_NUEVO,
                        actor=actor_actual,
                        post=self.object,
                        comentario=comentario,
                    )
                messages.success(
                    request,
                    'Tu comentario ha sido publicado directamente.'
                )
            else:
                # Pendiente de moderación: notificar al autor del post
                notificar(
                    destinatario=self.object.autor.usuario,
                    tipo=Notificacion.Tipo.COMENTARIO_NUEVO,
                    actor=actor_actual,
                    post=self.object,
                    comentario=comentario,
                )
                messages.success(
                    request,
                    'Tu comentario ha sido enviado correctamente y está pendiente de moderación por el autor.'
                )
            return redirect('blog:post_detail', slug=self.object.slug)

        context = self.get_context_data(form_comentario=form)
        return self.render_to_response(context)


class BuscarPostsView(ListView):
    model = Post
    template_name = 'blog/buscar.html'
    context_object_name = 'posts'
    paginate_by = 6

    def get_queryset(self):
        self.query = (self.request.GET.get('q') or '').strip()
        self.orden_actual = (self.request.GET.get('orden') or '').lower()
        if not self.query:
            return Post.objects.none()
        qs = buscar_posts(self.query, usuario=self.request.user)
        if self.orden_actual in ('recientes', 'populares', 'utiles'):
            return aplicar_orden_posts(qs, self.orden_actual)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.query
        context['orden_actual'] = self.orden_actual or 'relevancia'
        if self.query:
            paginator = context.get('paginator')
            context['total_resultados'] = paginator.count if paginator else len(context['posts'])
        else:
            context['total_resultados'] = 0
        return context


@method_decorator(limitar_tasa('buscar_sugerencias', 60, 60), name='dispatch')
class BuscarSugerenciasView(View):
    """
    Endpoint rápido para buscador con sugerencias: /buscar/sugerencias/?q=
    Devuelve un fragmento HTML con hasta 3 artículos, 2 comunidades, 2 autores y 3 etiquetas.
    Requiere mínimo 2 caracteres.
    """
    def get(self, request, *args, **kwargs):
        q = (request.GET.get('q') or '').strip()
        if len(q) < 2:
            return render(request, 'blog/includes/_sugerencias_busqueda.html', {'sin_termino': True, 'query': q})

        articulos = (
            Post.objects.publicados()
            .filter(titulo__icontains=q)
            .select_related('categoria', 'autor__usuario')[:3]
        )
        comunidades = Categoria.objects.filter(nombre__icontains=q)[:2]
        autores = (
            Perfil.objects.filter(
                Q(usuario__first_name__icontains=q)
                | Q(usuario__last_name__icontains=q)
                | Q(usuario__username__icontains=q),
                posts__estado=Post.Estado.PUBLICADO,
            )
            .select_related('usuario')
            .distinct()[:2]
        )
        etiquetas = Etiqueta.objects.filter(nombre__icontains=q)[:3]

        return render(
            request,
            'blog/includes/_sugerencias_busqueda.html',
            {
                'query': q,
                'articulos': articulos,
                'comunidades': comunidades,
                'autores': autores,
                'etiquetas': etiquetas,
                'sin_termino': False,
            },
        )


class AutorDetailView(ListView):
    model = Post
    template_name = 'blog/autor_detail.html'
    context_object_name = 'items'
    paginate_by = 10

    def get_queryset(self):
        usuario = get_object_or_404(User, username=self.kwargs['username'])
        self.perfil_autor, _ = Perfil.objects.get_or_create(usuario=usuario)
        self.tab = (self.request.GET.get('tab') or 'publicaciones').lower()

        if self.tab == 'comentarios':
            return (
                Comentario.objects.filter(autor=self.perfil_autor.usuario, aprobado=True)
                .select_related('post', 'post__autor', 'post__categoria')
                .order_by('-creado')
            )
        elif self.tab == 'guardados':
            if self.request.user.is_authenticated and self.request.user == self.perfil_autor.usuario:
                lista_g = obtener_lista_guardados_usuario(self.request.user)
                post_ids = list(lista_g.items.order_by('-agregado').values_list('post_id', flat=True))
                return (
                    Post.objects.publicados()
                    .con_relaciones()
                    .con_interacciones(self.request.user)
                    .filter(id__in=post_ids)
                )
            self.tab = 'publicaciones'

        return (
            Post.objects.publicados()
            .con_relaciones()
            .con_interacciones(self.request.user)
            .filter(autor=self.perfil_autor)
            .order_by('-publicado_en', '-id')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['perfil_autor'] = self.perfil_autor
        context['tab_actual'] = self.tab
        context['total_seguidores'] = self.perfil_autor.seguidores.count()
        context['total_publicaciones'] = Post.objects.publicados().filter(autor=self.perfil_autor).count()
        context['total_comentarios'] = Comentario.objects.filter(autor=self.perfil_autor.usuario, aprobado=True).count()
        es_dueno = (self.request.user.is_authenticated and self.request.user == self.perfil_autor.usuario)
        context['es_dueno'] = es_dueno
        if es_dueno:
            context['total_guardados'] = obtener_lista_guardados_usuario(self.request.user).items.count()
        else:
            context['total_guardados'] = 0

        # Para compatibilidad con templates y tests que esperan 'posts'
        if self.tab in ('publicaciones', 'guardados'):
            context['posts'] = context['items']
        else:
            context['comentarios'] = context['items']
            context['posts'] = list(Post.objects.publicados().filter(autor=self.perfil_autor)[:6])

        if self.request.user.is_authenticated:
            context['siguiendo_autor'] = Seguimiento.objects.filter(
                seguidor=self.request.user,
                autor=self.perfil_autor,
            ).exists()
        else:
            context['siguiendo_autor'] = False

        context['form_suscripcion'] = SuscripcionForm(
            user=self.request.user,
            initial={'autor_id': self.perfil_autor.pk},
        )
        return context


# ==============================================================================
# BLOQUE 1: VISTAS DE NOTIFICACIONES
# ==============================================================================

class NotificacionListView(LoginRequiredMixin, ListView):
    model = Notificacion
    template_name = 'blog/notificaciones.html'
    context_object_name = 'notificaciones'
    paginate_by = 15

    def get_queryset(self):
        return (
            Notificacion.objects.filter(destinatario=self.request.user)
            .select_related('actor', 'post', 'comentario')
            .order_by('-creado')
        )


class NotificacionIrView(LoginRequiredMixin, View):
    """Marca una notificación como leída al hacer clic y redirige a su URL de destino."""

    def get(self, request, pk, *args, **kwargs):
        notificacion = get_object_or_404(Notificacion, pk=pk, destinatario=request.user)
        if not notificacion.leida:
            notificacion.leida = True
            notificacion.save(update_fields=['leida'])
        return redirect(notificacion.url or reverse('blog:post_list'))

    def post(self, request, pk, *args, **kwargs):
        return self.get(request, pk, *args, **kwargs)


class NotificacionMarcarLeidaView(LoginRequiredMixin, View):
    """Marca una notificación individual como leída vía POST."""

    def post(self, request, pk, *args, **kwargs):
        notificacion = get_object_or_404(Notificacion, pk=pk, destinatario=request.user)
        if not notificacion.leida:
            notificacion.leida = True
            notificacion.save(update_fields=['leida'])

        no_leidas = Notificacion.objects.filter(destinatario=request.user, leida=False).count()
        if es_peticion_ajax(request):
            return JsonResponse({'ok': True, 'activo': True, 'total': no_leidas})

        next_url = request.POST.get('next') or reverse('blog:notificaciones_list')
        return redirect(next_url)


class NotificacionMarcarTodasLeidasView(LoginRequiredMixin, View):
    """Marca todas las notificaciones del usuario actual como leídas."""

    def post(self, request, *args, **kwargs):
        Notificacion.objects.filter(destinatario=request.user, leida=False).update(leida=True)
        if es_peticion_ajax(request):
            return JsonResponse({'ok': True, 'activo': False, 'total': 0})

        messages.success(request, 'Todas las notificaciones se han marcado como leídas.')
        next_url = request.POST.get('next') or reverse('blog:notificaciones_list')
        return redirect(next_url)


class NotificacionContadorView(LoginRequiredMixin, View):
    """Devuelve el conteo de notificaciones no leídas en JSON para el refresco cada 60s."""

    def get(self, request, *args, **kwargs):
        no_leidas = Notificacion.objects.filter(destinatario=request.user, leida=False).count()
        return JsonResponse({'ok': True, 'no_leidas': no_leidas})


# ==============================================================================
# BLOQUE 2: INTERACCIÓN CON EL POST (ME GUSTA Y ¿TE FUE ÚTIL?)
# ==============================================================================

@method_decorator(login_requerido_interaccion, name='dispatch')
@method_decorator(limitar_tasa('like_post', 30, 60), name='dispatch')
class ToggleLikePostView(View):
    """Alterna el 'Me gusta' en un post publicado (límite 30/min)."""

    def post(self, request, slug, *args, **kwargs):
        post = get_object_or_404(Post.objects.publicados(), slug=slug)
        like_existente = LikePost.objects.filter(usuario=request.user, post=post).first()

        if like_existente:
            like_existente.delete()
            activo = False
            eliminar_notificacion(
                destinatario=post.autor.usuario,
                tipo=Notificacion.Tipo.LIKE_POST,
                actor=request.user,
                post=post,
            )
            mensaje = 'Has quitado tu me gusta del artículo.'
        else:
            LikePost.objects.create(usuario=request.user, post=post)
            activo = True
            notificar(
                destinatario=post.autor.usuario,
                tipo=Notificacion.Tipo.LIKE_POST,
                actor=request.user,
                post=post,
            )
            mensaje = '¡Te gusta este artículo!'

        total = post.likes.count()
        if es_peticion_ajax(request):
            return JsonResponse({'ok': True, 'activo': activo, 'total': total, 'mensaje': mensaje})

        next_url = request.POST.get('next') or post.get_absolute_url()
        return redirect(next_url)


@method_decorator(login_requerido_interaccion, name='dispatch')
@method_decorator(limitar_tasa('voto_util', 30, 60), name='dispatch')
class VotarUtilPostView(View):
    """Registra o cambia el voto '¿Te fue útil?' (Sí/No) en un post publicado (límite 30/min)."""

    def post(self, request, slug, *args, **kwargs):
        post = get_object_or_404(Post.objects.publicados(), slug=slug)
        valor_raw = (request.POST.get('util') or '').strip().lower()
        es_util = valor_raw in ('si', 'sí', 'true', '1', 'yes')

        VotoUtil.objects.update_or_create(
            usuario=request.user,
            post=post,
            defaults={'util': es_util},
        )

        total = post.votos_utilidad.count()
        utiles = post.votos_utilidad.filter(util=True).count()
        mensaje = '¡Gracias por indicar que te fue útil!' if es_util else 'Gracias por tu valoración.'

        if es_peticion_ajax(request):
            return JsonResponse(
                {
                    'ok': True,
                    'activo': es_util,
                    'voto_actual': es_util,
                    'utiles': utiles,
                    'total': total,
                    'mensaje': mensaje,
                }
            )

        messages.success(request, mensaje)
        next_url = request.POST.get('next') or post.get_absolute_url()
        return redirect(next_url)


# ==============================================================================
# BLOQUE 3: INTERACCIÓN CON COMENTARIOS (LIKE, EDITAR, BORRAR, REPORTAR, MENCIONES)
# ==============================================================================

@method_decorator(login_requerido_interaccion, name='dispatch')
@method_decorator(limitar_tasa('like_comentario', 30, 60), name='dispatch')
class ToggleLikeComentarioView(View):
    """Alterna el 'Me gusta' sobre un comentario aprobado (límite 30/min)."""

    def post(self, request, pk, *args, **kwargs):
        comentario = get_object_or_404(
            Comentario.objects.select_related('post', 'autor'),
            pk=pk,
            aprobado=True,
            oculto_por_reportes=False,
            eliminado=False,
        )
        like_existente = LikeComentario.objects.filter(
            usuario=request.user,
            comentario=comentario,
        ).first()

        if like_existente:
            like_existente.delete()
            activo = False
            if comentario.autor:
                eliminar_notificacion(
                    destinatario=comentario.autor,
                    tipo=Notificacion.Tipo.LIKE_COMENTARIO,
                    actor=request.user,
                    post=comentario.post,
                    comentario=comentario,
                )
            mensaje = 'Has quitado tu me gusta del comentario.'
        else:
            LikeComentario.objects.create(usuario=request.user, comentario=comentario)
            activo = True
            if comentario.autor:
                notificar(
                    destinatario=comentario.autor,
                    tipo=Notificacion.Tipo.LIKE_COMENTARIO,
                    actor=request.user,
                    post=comentario.post,
                    comentario=comentario,
                )
            mensaje = '¡Te gusta este comentario!'

        total = comentario.likes.count()
        if es_peticion_ajax(request):
            return JsonResponse({'ok': True, 'activo': activo, 'total': total, 'mensaje': mensaje})

        next_url = request.POST.get('next') or f"{comentario.post.get_absolute_url()}#comentario-{comentario.pk}"
        return redirect(next_url)


class EditarComentarioView(LoginRequiredMixin, View):
    """
    Permite al dueño editar su comentario dentro de COMENTARIO_VENTANA_EDICION_MIN minutos.
    El comentario queda marcado como `editado=True` y vuelve a moderación (`aprobado=False`).
    """

    template_name = 'blog/comentario_editar.html'

    def obtener_comentario(self, pk):
        return get_object_or_404(Comentario.objects.select_related('post', 'post__autor__usuario'), pk=pk)

    def get(self, request, pk, *args, **kwargs):
        comentario = self.obtener_comentario(pk)
        if comentario.autor_id != request.user.id:
            return HttpResponseForbidden('No tienes permiso para editar un comentario ajeno.')
        if not comentario.dentro_de_ventana_edicion():
            return HttpResponseForbidden('El tiempo límite para editar este comentario ha expirado.')

        form = ComentarioEdicionForm(instance=comentario)
        return render(request, self.template_name, {'form': form, 'comentario': comentario})

    def post(self, request, pk, *args, **kwargs):
        comentario = self.obtener_comentario(pk)
        if comentario.autor_id != request.user.id:
            return HttpResponseForbidden('No tienes permiso para editar un comentario ajeno.')
        if not comentario.dentro_de_ventana_edicion():
            return HttpResponseForbidden('El tiempo límite para editar este comentario ha expirado.')

        form = ComentarioEdicionForm(request.POST, instance=comentario)
        if form.is_valid():
            comentario_editado = form.save(commit=False)
            comentario_editado.editado = True
            comentario_editado.aprobado = False
            comentario_editado.save()

            notificar(
                destinatario=comentario.post.autor.usuario,
                tipo=Notificacion.Tipo.COMENTARIO_NUEVO,
                actor=request.user,
                post=comentario.post,
                comentario=comentario_editado,
            )

            messages.info(
                request,
                'Tu comentario ha sido editado y enviado nuevamente a moderación.'
            )
            return redirect('blog:post_detail', slug=comentario.post.slug)

        return render(request, self.template_name, {'form': form, 'comentario': comentario})


class BorrarComentarioView(LoginRequiredMixin, View):
    """
    Permite borrar un comentario:
    - Al autor del comentario en cualquier momento.
    - Al autor del post o a los administradores sobre cualquier comentario.
    """

    def post(self, request, pk, *args, **kwargs):
        comentario = get_object_or_404(
            Comentario.objects.select_related('post', 'post__autor__usuario'),
            pk=pk,
        )
        if not comentario.puede_borrar(request.user):
            return HttpResponseForbidden('No tienes permiso para eliminar este comentario.')

        post_slug = comentario.post.slug
        comentario.borrar_seguro()
        messages.success(request, 'El comentario ha sido eliminado.')
        next_url = request.POST.get('next') or reverse('blog:post_detail', kwargs={'slug': post_slug})
        return redirect(next_url)


@method_decorator(login_requerido_interaccion, name='dispatch')
@method_decorator(limitar_tasa('reporte_comentario', 5, 3600), name='dispatch')
class ReportarComentarioView(View):
    """
    Crea un reporte sobre un comentario aprobado (límite 5/hora).
    - No permite reportar el propio comentario.
    - Único por comentario y reportante.
    - Notifica por web y correo tanto al autor del post como a todos los administradores.
    - Si acumula REPORTES_PARA_OCULTAR (3) reportes pendientes, oculta automáticamente el comentario.
    """

    def post(self, request, pk, *args, **kwargs):
        comentario = get_object_or_404(
            Comentario.objects.select_related('post', 'post__autor__usuario', 'autor'),
            pk=pk,
            aprobado=True,
        )

        if comentario.autor_id and comentario.autor_id == request.user.id:
            mensaje = 'No puedes reportar tu propio comentario.'
            if es_peticion_ajax(request):
                return JsonResponse({'ok': False, 'error': mensaje}, status=403)
            messages.error(request, mensaje)
            return HttpResponseForbidden(mensaje)

        if ReporteComentario.objects.filter(comentario=comentario, reportante=request.user).exists():
            mensaje = 'Ya has enviado un reporte para este comentario anteriormente.'
            if es_peticion_ajax(request):
                return JsonResponse({'ok': False, 'error': mensaje}, status=400)
            messages.warning(request, mensaje)
            return redirect('blog:post_detail', slug=comentario.post.slug)

        form = ReporteComentarioForm(request.POST)
        if form.is_valid():
            reporte = form.save(commit=False)
            reporte.comentario = comentario
            reporte.reportante = request.user
            reporte.save()

            umbral = getattr(settings, 'REPORTES_PARA_OCULTAR', 3)
            pendientes_count = comentario.reportes.filter(
                estado=ReporteComentario.Estado.PENDIENTE
            ).count()
            if pendientes_count >= umbral and not comentario.oculto_por_reportes:
                comentario.oculto_por_reportes = True
                comentario.save(update_fields=['oculto_por_reportes'])

            notificar_reporte_comentario(reporte, request=request)

            mensaje_ok = 'Reporte enviado. El autor y los administradores lo revisarán pronto.'
            if es_peticion_ajax(request):
                return JsonResponse(
                    {
                        'ok': True,
                        'activo': True,
                        'total': pendientes_count,
                        'oculto': comentario.oculto_por_reportes,
                        'mensaje': mensaje_ok,
                    }
                )
            messages.success(request, mensaje_ok)
        else:
            error_msg = 'Datos de reporte inválidos. Verifica el motivo y el detalle (máx. 300 caracteres).'
            if es_peticion_ajax(request):
                return JsonResponse({'ok': False, 'error': error_msg}, status=400)
            messages.error(request, error_msg)

        next_url = request.POST.get('next') or reverse('blog:post_detail', kwargs={'slug': comentario.post.slug})
        return redirect(next_url)


@method_decorator(login_requerido_interaccion, name='dispatch')
@method_decorator(limitar_tasa('buscar_usuarios', 60, 60), name='dispatch')
class BuscarUsuariosMencionView(View):
    """
    Endpoint `/usuarios/buscar/?q=` para autocompletado de `@menciones`:
    - Solo para usuarios autenticados y con límite de tasa.
    - Mínimo 2 caracteres, máximo 5 resultados.
    """

    def get(self, request, *args, **kwargs):
        q = (request.GET.get('q') or '').strip()
        if len(q) < 2:
            return JsonResponse({'usuarios': []})

        usuarios = (
            User.objects.filter(is_active=True, username__icontains=q)
            .order_by('username')[:5]
        )
        resultados = [
            {
                'username': u.username,
                'nombre': u.get_full_name() or u.username,
            }
            for u in usuarios
        ]
        return JsonResponse({'usuarios': resultados})


# ==============================================================================
# RONDA 2 - BLOQUE 1: SEGUIR AUTORES Y FEED /SIGUIENDO/
# ==============================================================================

@method_decorator(login_requerido_interaccion, name='dispatch')
@method_decorator(limitar_tasa('seguir_autor', 30, 60), name='dispatch')
class ToggleSeguirAutorView(View):
    """
    Permite seguir o dejar de seguir a un autor.
    - No se puede seguir a uno mismo.
    - Al seguir notifica SEGUIDOR_NUEVO al autor; al dejar de seguir elimina esa notificación.
    """

    def post(self, request, username, *args, **kwargs):
        usuario_autor = get_object_or_404(User, username=username)
        perfil_autor, _ = Perfil.objects.get_or_create(usuario=usuario_autor)

        if usuario_autor.pk == request.user.pk:
            mensaje_err = 'No puedes seguirte a ti mismo.'
            if es_peticion_ajax(request):
                return JsonResponse({'ok': False, 'error': mensaje_err}, status=400)
            messages.error(request, mensaje_err)
            return HttpResponseForbidden(mensaje_err)

        seg_existente = Seguimiento.objects.filter(
            seguidor=request.user,
            autor=perfil_autor,
        ).first()

        if seg_existente:
            seg_existente.delete()
            activo = False
            eliminar_notificacion(
                destinatario=usuario_autor,
                tipo=Notificacion.Tipo.SEGUIDOR_NUEVO,
                actor=request.user,
            )
            mensaje = f'Has dejado de seguir a @{usuario_autor.username}.'
        else:
            Seguimiento.objects.create(seguidor=request.user, autor=perfil_autor)
            activo = True
            notificar(
                destinatario=usuario_autor,
                tipo=Notificacion.Tipo.SEGUIDOR_NUEVO,
                actor=request.user,
            )
            mensaje = f'Ahora sigues a @{usuario_autor.username}.'

        total = perfil_autor.seguidores.count()
        if es_peticion_ajax(request):
            return JsonResponse({'ok': True, 'activo': activo, 'total': total, 'mensaje': mensaje})

        messages.success(request, mensaje)
        next_url = request.POST.get('next') or reverse('blog:autor_detail', kwargs={'username': username})
        return redirect(next_url)


@method_decorator(login_requerido_interaccion, name='dispatch')
@method_decorator(limitar_tasa('unirse_categoria', 30, 60), name='dispatch')
class ToggleUnirseCategoriaView(View):
    """
    Alterna la membresía del usuario autenticado en una categoría (`/categoria/<slug>/unirse/`):
    - Devuelve `{ok, activo, total, mensaje}` en peticiones AJAX.
    - Sin JavaScript redirige de vuelta a `next` o a la página de la categoría.
    - NO envía notificaciones ni correos (para eso existe la suscripción por correo).
    """

    def post(self, request, slug, *args, **kwargs):
        categoria = get_object_or_404(Categoria, slug=slug)
        membresia_existente = MiembroCategoria.objects.filter(
            usuario=request.user,
            categoria=categoria,
        ).first()

        if membresia_existente:
            membresia_existente.delete()
            activo = False
            mensaje = f'Has salido de la comunidad {categoria.nombre}.'
        else:
            MiembroCategoria.objects.create(usuario=request.user, categoria=categoria)
            activo = True
            mensaje = f'Te has unido a la comunidad {categoria.nombre}.'

        invalidar_cache_ranking()
        total = categoria.miembros.count()
        if es_peticion_ajax(request):
            return JsonResponse(
                {
                    'ok': True,
                    'activo': activo,
                    'unido': activo,
                    'total': total,
                    'total_miembros': total,
                    'mensaje': mensaje,
                }
            )

        messages.success(request, mensaje)
        next_url = request.POST.get('next') or categoria.get_absolute_url()
        return redirect(next_url)


class SiguiendoFeedView(LoginRequiredMixin, ListView):
    """
    Página `/siguiendo/`:
    - Incluye los posts publicados de los autores seguidos y de las comunidades (categorías)
      a las que el usuario se ha unido, sin duplicados y ordenados por fecha.
    - Soporta el filtro `?filtro=todo|autores|comunidades`.
    """

    model = Post
    template_name = 'blog/siguiendo.html'
    context_object_name = 'posts'
    paginate_by = 6

    def get_queryset(self):
        self.filtro_actual = (self.request.GET.get('filtro') or 'todo').strip().lower()
        if self.filtro_actual not in ('todo', 'autores', 'comunidades'):
            self.filtro_actual = 'todo'

        qs = Post.objects.publicados().con_relaciones().con_interacciones(self.request.user)
        if self.filtro_actual == 'autores':
            qs = qs.filter(autor__seguidores__seguidor=self.request.user)
        elif self.filtro_actual == 'comunidades':
            qs = qs.filter(categoria__miembros__usuario=self.request.user)
        else:
            qs = qs.filter(
                Q(autor__seguidores__seguidor=self.request.user)
                | Q(categoria__miembros__usuario=self.request.user)
            )
        return qs.distinct().order_by('-publicado_en', '-creado', '-id')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filtro_actual'] = self.filtro_actual
        context['autores_seguidos'] = list(
            Perfil.objects.filter(seguidores__seguidor=self.request.user)
            .select_related('usuario')
            .annotate(total_seguidores=Count('seguidores', distinct=True))
            .order_by('usuario__username')
        )
        context['comunidades_unidas'] = list(
            Categoria.objects.filter(miembros__usuario=self.request.user)
            .annotate(total_miembros=Count('miembros', distinct=True))
            .order_by('nombre')
        )
        context['tiene_suscripciones_feed'] = bool(
            context['autores_seguidos'] or context['comunidades_unidas']
        )
        return context


# ==============================================================================
# RONDA 2 - BLOQUE 2: SUSCRIPCIÓN POR CORREO (DOBLE CONFIRMACIÓN Y BAJA)
# ==============================================================================

@method_decorator(limitar_tasa('suscripcion_correo', 3, 3600), name='dispatch')
class CrearSuscripcionView(View):
    """
    Procesa el formulario de suscripción por correo a un autor o una categoría:
    - Incluye honeypot (`sitio_web`) y límite de tasa de 3 por hora por IP/usuario.
    - Doble confirmación: envía correo con enlace de confirmación; hasta confirmar no envía boletines.
    """

    def post(self, request, *args, **kwargs):
        form = SuscripcionForm(request.POST, user=request.user)
        next_url = request.POST.get('next') or reverse('blog:post_list')

        if not form.is_valid():
            messages.error(request, 'No se pudo procesar la suscripción. Verifica el correo ingresado.')
            return redirect(next_url)

        email = form.cleaned_data['email']
        autor_id = form.cleaned_data.get('autor_id')
        categoria_id = form.cleaned_data.get('categoria_id')

        if bool(autor_id) == bool(categoria_id):
            messages.error(request, 'Debes elegir un autor o una categoría para suscribirte.')
            return redirect(next_url)

        autor = get_object_or_404(Perfil, pk=autor_id) if autor_id else None
        categoria = get_object_or_404(Categoria, pk=categoria_id) if categoria_id else None

        filtro_destino = {'autor': autor} if autor else {'categoria': categoria}
        suscripcion, created = Suscripcion.objects.get_or_create(
            email=email,
            **filtro_destino,
            defaults={
                'usuario': request.user if request.user.is_authenticated else None,
                'confirmada': False,
                'activa': True,
            },
        )

        if not created:
            if request.user.is_authenticated and not suscripcion.usuario_id:
                suscripcion.usuario = request.user
            suscripcion.activa = True
            suscripcion.save()

        if suscripcion.confirmada and suscripcion.activa:
            messages.info(request, f'Tu correo ({email}) ya se encuentra suscrito y confirmado en {suscripcion.destino_nombre}.')
        else:
            enviar_correo_confirmacion_suscripcion(suscripcion, request=request)
            messages.success(
                request,
                f'Te hemos enviado un correo de confirmación a {email}. Confirma el enlace para activar la suscripción.'
            )

        return redirect(next_url)


class ConfirmarSuscripcionView(View):
    """Activa una suscripción al visitar el enlace de doble confirmación `/suscripcion/confirmar/<token>/`."""

    template_name = 'blog/suscripcion_estado.html'

    def get(self, request, token, *args, **kwargs):
        suscripcion = get_object_or_404(Suscripcion, token=token)
        suscripcion.confirmada = True
        suscripcion.activa = True
        if request.user.is_authenticated and not suscripcion.usuario_id:
            suscripcion.usuario = request.user
        suscripcion.save()
        messages.success(request, f'¡Suscripción confirmada! Recibirás por correo las novedades de {suscripcion.destino_nombre}.')
        return render(
            request,
            self.template_name,
            {'suscripcion': suscripcion, 'accion': 'confirmada'},
        )


class BajaSuscripcionView(View):
    """
    Cancela una suscripción mediante su token único `/suscripcion/baja/<token>/`.
    Funciona sin necesidad de iniciar sesión.
    """

    template_name = 'blog/suscripcion_estado.html'

    def dar_de_baja(self, request, token):
        suscripcion = get_object_or_404(Suscripcion, token=token)
        suscripcion.activa = False
        suscripcion.confirmada = False
        suscripcion.save(update_fields=['activa', 'confirmada'])
        messages.info(request, f'Te has dado de baja correctamente de {suscripcion.destino_nombre}.')
        return suscripcion

    def get(self, request, token, *args, **kwargs):
        suscripcion = self.dar_de_baja(request, token)
        return render(
            request,
            self.template_name,
            {'suscripcion': suscripcion, 'accion': 'baja'},
        )

    def post(self, request, token, *args, **kwargs):
        self.dar_de_baja(request, token)
        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)
        return redirect('blog:post_list')


class MisSuscripcionesView(LoginRequiredMixin, ListView):
    """Página `/mis-suscripciones/` para usuarios autenticados con opción de darse de baja."""

    model = Suscripcion
    template_name = 'blog/mis_suscripciones.html'
    context_object_name = 'suscripciones'

    def get_queryset(self):
        condicion = Q(usuario=self.request.user)
        if self.request.user.email:
            condicion = condicion | Q(email__iexact=self.request.user.email)
        return (
            Suscripcion.objects.filter(condicion, activa=True)
            .select_related('autor__usuario', 'categoria')
            .order_by('-creado')
        )


# ==============================================================================
# RONDA 2 - BLOQUE 3 Y 4: MÁS POPULARES Y AUTORES DESTACADOS
# ==============================================================================

class ExplorarView(TemplateView):
    """
    Página `/explorar/`: Comunidades, tendencias de la semana (etiquetas y publicaciones)
    y autores para seguir. Fusiona Autores y Comunidades.
    """
    template_name = 'blog/explorar.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        comunidades = Categoria.objects.all().annotate(
            total_posts=Count('posts', filter=Q(posts__estado=Post.Estado.PUBLICADO)),
            total_miembros=Count('miembros')
        ).order_by('-total_miembros', '-total_posts')

        if user.is_authenticated:
            miembro_ids = set(user.membresias_categoria.values_list('categoria_id', flat=True))
            for c in comunidades:
                c.es_miembro = c.pk in miembro_ids
        else:
            for c in comunidades:
                c.es_miembro = False

        etiquetas_tendencia = Etiqueta.objects.annotate(
            total_posts=Count('posts', filter=Q(posts__estado=Post.Estado.PUBLICADO))
        ).filter(total_posts__gt=0).order_by('-total_posts')[:12]

        una_semana_atras = timezone.now() - timedelta(days=7)
        posts_tendencia_qs = (
            Post.objects.publicados()
            .con_relaciones()
            .con_interacciones(user)
            .filter(publicado_en__gte=una_semana_atras)
            .order_by('-total_likes', '-total_comentarios_aprobados')[:6]
        )
        posts_tendencia = list(posts_tendencia_qs)
        if not posts_tendencia:
            posts_tendencia = list(
                Post.objects.publicados()
                .con_relaciones()
                .con_interacciones(user)
                .order_by('-total_likes', '-total_comentarios_aprobados')[:6]
            )

        autores = list(construir_queryset_autores_destacados(orden='puntuacion')[:8])
        if user.is_authenticated:
            siguiendo_ids = set(user.siguiendo_autores.values_list('autor_id', flat=True))
            for a in autores:
                a.siguiendo_usuario = a.pk in siguiendo_ids
        else:
            for a in autores:
                a.siguiendo_usuario = False

        context.update({
            'comunidades': comunidades,
            'etiquetas_tendencia': etiquetas_tendencia,
            'posts_tendencia': posts_tendencia,
            'autores': autores,
        })
        return context


class PostsPopularesView(ListView):
    """Página `/populares/` con pestañas Semana (7d), Mes (30d) y Siempre."""

    model = Post
    template_name = 'blog/populares.html'
    context_object_name = 'posts'
    paginate_by = 10

    def get_queryset(self):
        self.periodo = (self.request.GET.get('periodo') or 'semana').lower()
        if self.periodo == 'mes':
            dias = 30
        elif self.periodo == 'siempre':
            dias = None
        else:
            self.periodo = 'semana'
            dias = 7
        return construir_queryset_populares(dias=dias, usuario=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['periodo_actual'] = self.periodo
        return context


class AutoresListView(ListView):
    """
    Página `/autores/` con todos los autores con al menos 1 post publicado,
    ordenables por `puntuacion`, `posts` o `seguidores`.
    """

    model = Perfil
    template_name = 'blog/autores.html'
    context_object_name = 'autores'
    paginate_by = 12

    def get_queryset(self):
        self.orden = (self.request.GET.get('orden') or 'puntuacion').lower()
        if self.orden not in ('puntuacion', 'posts', 'seguidores'):
            self.orden = 'puntuacion'
        return construir_queryset_autores_destacados(orden=self.orden)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['orden_actual'] = self.orden
        return context


# ==============================================================================
# RONDA 2 - BLOQUE 5: LISTAS DE LECTURA Y GUARDADOS
# ==============================================================================

def obtener_lista_guardados_usuario(usuario):
    lista, _ = ListaLectura.objects.get_or_create(
        usuario=usuario,
        nombre=ListaLectura.NOMBRE_GUARDADOS,
        defaults={
            'descripcion': 'Artículos guardados para leer más tarde.',
            'publica': False,
            'es_predeterminada': True,
        },
    )
    return lista


@method_decorator(login_requerido_interaccion, name='dispatch')
@method_decorator(limitar_tasa('guardar_post', 30, 60), name='dispatch')
class ToggleGuardadoPostView(View):
    """Añade o quita un post publicado de la lista privada 'Guardados' con un clic."""

    def post(self, request, slug, *args, **kwargs):
        post = get_object_or_404(Post.objects.publicados(), slug=slug)
        lista_guardados = obtener_lista_guardados_usuario(request.user)

        item_existente = ItemLista.objects.filter(lista=lista_guardados, post=post).first()
        if item_existente:
            item_existente.delete()
            activo = False
            mensaje = 'Artículo quitado de tu lista "Guardados".'
        else:
            ItemLista.objects.create(lista=lista_guardados, post=post)
            activo = True
            mensaje = 'Artículo guardado en tu lista "Guardados".'

        total = lista_guardados.items.count()
        if es_peticion_ajax(request):
            return JsonResponse({'ok': True, 'activo': activo, 'total': total, 'mensaje': mensaje})

        messages.success(request, mensaje)
        next_url = request.POST.get('next') or post.get_absolute_url()
        return redirect(next_url)


@method_decorator(login_requerido_interaccion, name='dispatch')
class AgregarPostAListaView(View):
    """
    Añade un post a otra lista de lectura del usuario o crea una lista nueva en el acto.
    """

    def post(self, request, slug, *args, **kwargs):
        post = get_object_or_404(Post.objects.publicados(), slug=slug)
        nuevo_nombre = (request.POST.get('nuevo_nombre') or '').strip()
        lista_id = request.POST.get('lista_id')
        publica = request.POST.get('publica') in ('on', 'true', '1')

        if nuevo_nombre:
            if nuevo_nombre.lower() == ListaLectura.NOMBRE_GUARDADOS.lower():
                lista = obtener_lista_guardados_usuario(request.user)
            else:
                lista, _ = ListaLectura.objects.get_or_create(
                    usuario=request.user,
                    nombre=nuevo_nombre[:120],
                    defaults={'publica': publica},
                )
        elif lista_id:
            lista = get_object_or_404(ListaLectura, pk=lista_id, usuario=request.user)
        else:
            lista = obtener_lista_guardados_usuario(request.user)

        _, creado = ItemLista.objects.get_or_create(lista=lista, post=post)
        if creado:
            mensaje = f'Artículo añadido a la lista "{lista.nombre}".'
        else:
            mensaje = f'El artículo ya estaba en la lista "{lista.nombre}".'

        if es_peticion_ajax(request):
            return JsonResponse(
                {
                    'ok': True,
                    'activo': True,
                    'total': lista.items.count(),
                    'lista_id': lista.pk,
                    'lista_nombre': lista.nombre,
                    'mensaje': mensaje,
                }
            )

        messages.success(request, mensaje)
        next_url = request.POST.get('next') or post.get_absolute_url()
        return redirect(next_url)


class GuardadosRedirectView(LoginRequiredMixin, View):
    """
    Página `/guardados/`:
    Redirige de inmediato al detalle de la lista predeterminada 'Guardados' del usuario.
    Si el usuario aún no la tiene inicializada, la crea en el acto.
    """

    def get(self, request, *args, **kwargs):
        lista_guardados = obtener_lista_guardados_usuario(request.user)
        return redirect('blog:lista_detail', pk=lista_guardados.pk)


class MisListasView(LoginRequiredMixin, View):
    """Página `/mis-listas/`: ver todas las listas propias y crear nuevas listas."""

    template_name = 'blog/mis_listas.html'

    def obtener_contexto(self, request, form=None):
        obtener_lista_guardados_usuario(request.user)
        listas = (
            ListaLectura.objects.filter(usuario=request.user)
            .annotate(total_items=Count('items', distinct=True))
            .order_by('-es_predeterminada', 'nombre')
        )
        return {
            'listas': listas,
            'form_lista': form or ListaLecturaForm(),
        }

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self.obtener_contexto(request))

    def post(self, request, *args, **kwargs):
        form = ListaLecturaForm(request.POST)
        if form.is_valid():
            lista = form.save(commit=False)
            lista.usuario = request.user
            if ListaLectura.objects.filter(usuario=request.user, nombre__iexact=lista.nombre).exists():
                messages.warning(request, f'Ya tienes una lista llamada "{lista.nombre}".')
            else:
                lista.save()
                messages.success(request, f'Lista "{lista.nombre}" creada correctamente.')
            return redirect('blog:mis_listas')
        return render(request, self.template_name, self.obtener_contexto(request, form=form))


class ListaLecturaDetailView(View):
    """
    Página `/listas/<id>/`:
    - Si es privada: solo el dueño puede verla (403 en otro caso).
    - Si es pública: cualquiera con el enlace puede verla, mostrando el nombre del dueño.
    - Si un post pasa a borrador: deja de mostrarse a otros usuarios en listas públicas,
      y el dueño ve "Este post ya no está disponible".
    """

    template_name = 'blog/lista_detail.html'

    def get(self, request, pk, *args, **kwargs):
        lista = get_object_or_404(ListaLectura.objects.select_related('usuario'), pk=pk)
        es_dueno = request.user.is_authenticated and lista.usuario_id == request.user.id

        if not lista.publica and not es_dueno:
            return HttpResponseForbidden('Esta lista de lectura es privada.')

        items_qs = lista.items.select_related(
            'post', 'post__autor', 'post__autor__usuario', 'post__categoria'
        ).order_by('-agregado')

        if not es_dueno:
            items_qs = items_qs.filter(post__estado=Post.Estado.PUBLICADO)

        return render(
            request,
            self.template_name,
            {
                'lista': lista,
                'items': items_qs,
                'es_dueno': es_dueno,
                'form_editar': ListaLecturaForm(instance=lista) if (es_dueno and not lista.es_guardados) else None,
            },
        )


class EditarListaLecturaView(LoginRequiredMixin, View):
    """Renombra o cambia descripción/visibilidad de una lista propia (excepto 'Guardados')."""

    def post(self, request, pk, *args, **kwargs):
        lista = get_object_or_404(ListaLectura, pk=pk)
        if lista.usuario_id != request.user.id:
            return HttpResponseForbidden('No tienes permiso para editar esta lista.')
        if lista.es_guardados:
            return HttpResponseForbidden('La lista predeterminada "Guardados" no se puede renombrar ni hacer pública.')

        form = ListaLecturaForm(request.POST, instance=lista)
        if form.is_valid():
            form.save()
            messages.success(request, f'Lista "{lista.nombre}" actualizada.')
        else:
            messages.error(request, 'No se pudo actualizar la lista. Verifica el nombre.')

        next_url = request.POST.get('next') or reverse('blog:lista_detail', kwargs={'pk': lista.pk})
        return redirect(next_url)


class ToggleVisibilidadListaView(LoginRequiredMixin, View):
    """Alterna entre pública y privada una lista propia (excepto 'Guardados')."""

    def post(self, request, pk, *args, **kwargs):
        lista = get_object_or_404(ListaLectura, pk=pk)
        if lista.usuario_id != request.user.id:
            return HttpResponseForbidden('No tienes permiso para modificar esta lista.')
        if lista.es_guardados:
            return HttpResponseForbidden('La lista "Guardados" es siempre privada.')

        lista.publica = not lista.publica
        lista.save(update_fields=['publica'])
        estado_txt = 'pública' if lista.publica else 'privada'
        messages.success(request, f'La lista "{lista.nombre}" ahora es {estado_txt}.')

        next_url = request.POST.get('next') or reverse('blog:mis_listas')
        return redirect(next_url)


class EliminarListaLecturaView(LoginRequiredMixin, View):
    """Elimina una lista propia (la lista 'Guardados' nunca puede borrarse)."""

    def post(self, request, pk, *args, **kwargs):
        lista = get_object_or_404(ListaLectura, pk=pk)
        if lista.usuario_id != request.user.id:
            return HttpResponseForbidden('No tienes permiso para borrar esta lista.')
        if lista.es_guardados:
            return HttpResponseForbidden('La lista predeterminada "Guardados" no se puede borrar.')

        nombre = lista.nombre
        lista.delete()
        messages.success(request, f'La lista "{nombre}" ha sido eliminada.')
        return redirect('blog:mis_listas')


class QuitarItemListaView(LoginRequiredMixin, View):
    """Quita un post de una lista de lectura propia."""

    def post(self, request, pk, post_id, *args, **kwargs):
        lista = get_object_or_404(ListaLectura, pk=pk)
        if lista.usuario_id != request.user.id:
            return HttpResponseForbidden('No tienes permiso para modificar esta lista.')

        ItemLista.objects.filter(lista=lista, post_id=post_id).delete()
        messages.info(request, 'Artículo quitado de la lista.')
        next_url = request.POST.get('next') or reverse('blog:lista_detail', kwargs={'pk': lista.pk})
        return redirect(next_url)


# ==============================================================================
# PANEL DE AUTOR (REQUIERE LOGIN Y PERMISOS DE PROPIETARIO)
# ==============================================================================

class AutorPropietarioMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Garantiza que un autor autenticado únicamente pueda ver, editar o borrar
    sus propios posts. Si intenta operar sobre un post ajeno devuelve 403/404.
    """

    def obtener_perfil_actual(self):
        perfil, _ = Perfil.objects.get_or_create(usuario=self.request.user)
        return perfil

    def test_func(self):
        obj = self.get_object()
        return obj.autor_id == self.obtener_perfil_actual().id


class PanelDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'blog/panel/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        perfil, _ = Perfil.objects.get_or_create(usuario=self.request.user)
        mis_posts = Post.objects.filter(autor=perfil)
        mis_comentarios = Comentario.objects.filter(post__autor=perfil)
        mis_reportes = ReporteComentario.objects.filter(comentario__post__autor=perfil)

        context['perfil'] = perfil
        context['total_posts'] = mis_posts.count()
        context['total_publicados'] = mis_posts.filter(estado=Post.Estado.PUBLICADO).count()
        context['total_borradores'] = mis_posts.filter(estado=Post.Estado.BORRADOR).count()
        context['comentarios_pendientes'] = mis_comentarios.filter(aprobado=False).count()
        context['comentarios_aprobados'] = mis_comentarios.filter(aprobado=True).count()
        context['reportes_pendientes'] = mis_reportes.filter(
            estado=ReporteComentario.Estado.PENDIENTE
        ).count()
        context['total_seguidores'] = perfil.seguidores.count()

        # Likes recibidos totales y % de utilidad global del autor
        context['likes_recibidos_total'] = LikePost.objects.filter(post__autor=perfil).count()
        votos_autor_qs = VotoUtil.objects.filter(post__autor=perfil)
        total_votos_global = votos_autor_qs.count()
        if total_votos_global > 0:
            positivos_global = votos_autor_qs.filter(util=True).count()
            context['porcentaje_utilidad_global'] = round((positivos_global * 100.0) / total_votos_global)
        else:
            context['porcentaje_utilidad_global'] = None

        # Vistas de los últimos 7 días y gráfica de línea de los últimos 14 días (Chart.js)
        hoy = timezone.localdate()
        hace_7_dias = hoy - timedelta(days=6)
        hace_14_dias = hoy - timedelta(days=13)

        context['vistas_ultimos_7_dias'] = (
            VistaDiaria.objects.filter(post__autor=perfil, fecha__gte=hace_7_dias)
            .aggregate(total=Sum('cantidad'))['total']
            or 0
        )

        vistas_14d_qs = (
            VistaDiaria.objects.filter(post__autor=perfil, fecha__gte=hace_14_dias)
            .values('fecha')
            .annotate(total=Sum('cantidad'))
        )
        mapa_vistas_14d = {item['fecha']: item['total'] for item in vistas_14d_qs}
        labels_14d = []
        datos_14d = []
        for i in range(13, -1, -1):
            dia = hoy - timedelta(days=i)
            labels_14d.append(dia.strftime('%d/%m'))
            datos_14d.append(mapa_vistas_14d.get(dia, 0))

        context['grafica_vistas_labels_json'] = json.dumps(labels_14d)
        context['grafica_vistas_datos_json'] = json.dumps(datos_14d)
        context['total_vistas_14d'] = sum(datos_14d)

        # Checklist "Primeros pasos" para autores nuevos (desaparece con >= 1 post publicado)
        context['primeros_pasos_completar_perfil'] = bool(perfil.bio and perfil.avatar)
        context['primeros_pasos_crear_post'] = mis_posts.exists()
        context['primeros_pasos_publicar_post'] = context['total_publicados'] > 0

        # Subconsultas sin producto cartesiano para métricas por post
        sub_vistas_post = (
            VistaDiaria.objects.filter(post=OuterRef('pk'))
            .values('post')
            .annotate(total=Sum('cantidad'))
            .values('total')[:1]
        )
        sub_likes_post = (
            LikePost.objects.filter(post=OuterRef('pk'))
            .values('post')
            .annotate(total=Count('id'))
            .values('total')[:1]
        )
        sub_votos_total = (
            VotoUtil.objects.filter(post=OuterRef('pk'))
            .values('post')
            .annotate(total=Count('id'))
            .values('total')[:1]
        )
        sub_votos_pos = (
            VotoUtil.objects.filter(post=OuterRef('pk'), util=True)
            .values('post')
            .annotate(total=Count('id'))
            .values('total')[:1]
        )

        posts_anotados_qs = mis_posts.con_relaciones().annotate(
            total_vistas=Coalesce(Subquery(sub_vistas_post, output_field=IntegerField()), 0),
            total_likes=Coalesce(Subquery(sub_likes_post, output_field=IntegerField()), 0),
            total_votos=Coalesce(Subquery(sub_votos_total, output_field=IntegerField()), 0),
            votos_positivos=Coalesce(Subquery(sub_votos_pos, output_field=IntegerField()), 0),
        )

        posts_con_metricas = list(posts_anotados_qs.order_by('-creado')[:5])
        for p in posts_con_metricas:
            if p.total_votos > 0:
                p.porcentaje_utilidad = round((p.votos_positivos * 100.0) / p.total_votos)
            else:
                p.porcentaje_utilidad = None

        posts_mas_leidos = list(
            posts_anotados_qs.filter(estado=Post.Estado.PUBLICADO)
            .order_by('-total_vistas', '-total_likes', '-publicado_en')[:5]
        )
        for p in posts_mas_leidos:
            if p.total_votos > 0:
                p.porcentaje_utilidad = round((p.votos_positivos * 100.0) / p.total_votos)
            else:
                p.porcentaje_utilidad = None

        context['posts_recientes'] = posts_con_metricas
        context['posts_mas_leidos'] = posts_mas_leidos
        context['ultimos_pendientes'] = mis_comentarios.filter(aprobado=False).select_related('post')[:5]
        return context


class PanelPostListView(LoginRequiredMixin, ListView):
    model = Post
    template_name = 'blog/panel/post_list.html'
    context_object_name = 'posts'
    paginate_by = 10

    def get_queryset(self):
        perfil, _ = Perfil.objects.get_or_create(usuario=self.request.user)
        qs = (
            Post.objects.filter(autor=perfil)
            .con_relaciones()
            .con_interacciones(self.request.user)
            .order_by('-creado')
        )
        estado = (self.request.GET.get('estado') or '').strip()
        if estado in (Post.Estado.BORRADOR, Post.Estado.PUBLICADO):
            qs = qs.filter(estado=estado)

        categoria_slug = (self.request.GET.get('categoria') or '').strip()
        if categoria_slug:
            qs = qs.filter(categoria__slug=categoria_slug)

        q = (self.request.GET.get('q') or '').strip()
        if q:
            qs = qs.filter(Q(titulo__icontains=q) | Q(contenido__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['estado_filtro'] = (self.request.GET.get('estado') or '').strip()
        context['categoria_filtro'] = (self.request.GET.get('categoria') or '').strip()
        context['q_filtro'] = (self.request.GET.get('q') or '').strip()
        context['categorias'] = Categoria.objects.order_by('nombre')
        return context


class PanelPostCreateView(LoginRequiredMixin, CreateView):
    model = Post
    form_class = PostForm
    template_name = 'blog/panel/post_form.html'
    success_url = reverse_lazy('blog:panel_post_list')

    def get_initial(self):
        initial = super().get_initial()
        cat_param = (self.request.GET.get('categoria') or '').strip()
        if cat_param:
            cat = Categoria.objects.filter(slug=cat_param).first()
            if not cat and cat_param.isdigit():
                cat = Categoria.objects.filter(pk=int(cat_param)).first()
            if cat:
                initial['categoria'] = cat.pk
        return initial

    def form_valid(self, form):
        perfil, _ = Perfil.objects.get_or_create(usuario=self.request.user)
        form.instance.autor = perfil
        accion = self.request.POST.get('accion_guardar')
        if accion == 'borrador':
            form.instance.estado = Post.Estado.BORRADOR
        elif accion == 'publicado':
            form.instance.estado = Post.Estado.PUBLICADO
        if self.request.POST.get('eliminar_portada') == '1':
            form.instance.imagen_portada = None
        response = super().form_valid(form)
        messages.success(self.request, f'El post "{self.object.titulo}" ha sido creado correctamente.')
        return response


class PanelPostUpdateView(AutorPropietarioMixin, UpdateView):
    model = Post
    form_class = PostForm
    template_name = 'blog/panel/post_form.html'
    slug_url_kwarg = 'slug'
    success_url = reverse_lazy('blog:panel_post_list')

    def form_valid(self, form):
        accion = self.request.POST.get('accion_guardar')
        if accion == 'borrador':
            form.instance.estado = Post.Estado.BORRADOR
        elif accion == 'publicado':
            form.instance.estado = Post.Estado.PUBLICADO
        if self.request.POST.get('eliminar_portada') == '1':
            form.instance.imagen_portada = None
        response = super().form_valid(form)
        messages.success(self.request, f'El post "{self.object.titulo}" ha sido actualizado.')
        return response


class PanelPostDeleteView(AutorPropietarioMixin, DeleteView):
    model = Post
    template_name = 'blog/panel/post_confirm_delete.html'
    slug_url_kwarg = 'slug'
    success_url = reverse_lazy('blog:panel_post_list')

    def form_valid(self, form):
        titulo = self.object.titulo
        response = super().form_valid(form)
        messages.success(self.request, f'El post "{titulo}" ha sido eliminado.')
        return response


class PanelPostCambiarEstadoView(AutorPropietarioMixin, View):
    """Alterna el estado de un post propio entre Publicado y Borrador."""

    def get_object(self):
        return get_object_or_404(Post, slug=self.kwargs['slug'])

    def post(self, request, *args, **kwargs):
        post = self.get_object()
        if post.estado == Post.Estado.PUBLICADO:
            post.estado = Post.Estado.BORRADOR
            mensaje = f'El post "{post.titulo}" se ha pasado a Borrador.'
        else:
            post.estado = Post.Estado.PUBLICADO
            mensaje = f'El post "{post.titulo}" ha sido Publicado.'
        post.save()
        messages.success(request, mensaje)
        return redirect('blog:panel_post_list')


class PanelComentarioListView(LoginRequiredMixin, ListView):
    model = Comentario
    template_name = 'blog/panel/comentario_list.html'
    context_object_name = 'comentarios'
    paginate_by = 15

    def get_queryset(self):
        perfil, _ = Perfil.objects.get_or_create(usuario=self.request.user)
        qs = (
            Comentario.objects.filter(post__autor=perfil, eliminado=False)
            .select_related('post', 'autor', 'padre')
            .order_by('-creado')
        )
        estado = self.request.GET.get('estado', 'pendientes')
        if estado == 'pendientes':
            qs = qs.filter(aprobado=False)
        elif estado == 'aprobados':
            qs = qs.filter(aprobado=True)

        tipo = self.request.GET.get('tipo', '')
        if tipo == 'principales':
            qs = qs.filter(padre__isnull=True)
        elif tipo == 'respuestas':
            qs = qs.filter(padre__isnull=False)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['estado_filtro'] = self.request.GET.get('estado', 'pendientes')
        context['tipo_filtro'] = self.request.GET.get('tipo', '')
        return context


class PanelComentarioAccionView(LoginRequiredMixin, View):
    """
    Permite aprobar o rechazar (eliminar) un comentario recibido en los posts del autor.
    Al aprobar:
    - Notifica COMENTARIO_APROBADO al autor del comentario si es un usuario registrado.
    - Notifica RESPUESTA_COMENTARIO al autor del comentario padre (sin duplicar si es el autor del post).
    - Envía las notificaciones MENCION de los `@usuarios` mencionados en el texto.
    """

    def post(self, request, pk, *args, **kwargs):
        perfil, _ = Perfil.objects.get_or_create(usuario=request.user)
        comentario = get_object_or_404(
            Comentario.objects.select_related('post', 'post__autor__usuario', 'autor', 'padre', 'padre__autor'),
            pk=pk,
            post__autor=perfil,
        )
        accion = request.POST.get('accion')

        if accion == 'aprobar':
            comentario.aprobado = True
            comentario.save(update_fields=['aprobado'])
            if comentario.autor:
                notificar(
                    destinatario=comentario.autor,
                    tipo=Notificacion.Tipo.COMENTARIO_APROBADO,
                    actor=request.user,
                    post=comentario.post,
                    comentario=comentario,
                )
            notificar_respuesta_y_menciones_comentario(comentario)
            messages.success(request, f'Comentario de {comentario.nombre} aprobado.')
        elif accion == 'rechazar':
            autor_comentario = comentario.nombre
            comentario.borrar_seguro()
            messages.warning(request, f'Comentario de {autor_comentario} rechazado y eliminado.')
        else:
            messages.error(request, 'Acción no válida.')

        next_url = request.POST.get('next') or reverse('blog:panel_comentario_list')
        return redirect(next_url)


class PanelReporteListView(LoginRequiredMixin, ListView):
    """Lista los reportes de comentarios en los posts del autor autenticado."""

    model = ReporteComentario
    template_name = 'blog/panel/reporte_list.html'
    context_object_name = 'reportes'
    paginate_by = 15

    def get_queryset(self):
        perfil, _ = Perfil.objects.get_or_create(usuario=self.request.user)
        qs = (
            ReporteComentario.objects.filter(comentario__post__autor=perfil)
            .select_related('comentario', 'comentario__post', 'reportante', 'revisado_por')
            .order_by('-creado')
        )
        estado = self.request.GET.get('estado', 'pendiente')
        if estado in (
            ReporteComentario.Estado.PENDIENTE,
            ReporteComentario.Estado.REVISADO,
            ReporteComentario.Estado.DESCARTADO,
        ):
            qs = qs.filter(estado=estado)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['estado_filtro'] = self.request.GET.get('estado', 'pendiente')
        return context


class PanelReporteAccionView(LoginRequiredMixin, View):
    """
    Resuelve un reporte desde el panel del autor (actualizando el mismo estado que el admin):
    - `descartar`: marca como descartado y restaura la visibilidad si el comentario estaba oculto.
    - `revisado`: marca como revisado.
    - `eliminar_comentario`: elimina el comentario reportado.
    """

    def post(self, request, pk, *args, **kwargs):
        perfil, _ = Perfil.objects.get_or_create(usuario=request.user)
        reporte = get_object_or_404(
            ReporteComentario.objects.select_related('comentario', 'comentario__post'),
            pk=pk,
            comentario__post__autor=perfil,
        )
        accion = request.POST.get('accion')
        comentario = reporte.comentario

        if accion == 'descartar':
            reporte.estado = ReporteComentario.Estado.DESCARTADO
            reporte.revisado_por = request.user
            reporte.save(update_fields=['estado', 'revisado_por'])

            umbral = getattr(settings, 'REPORTES_PARA_OCULTAR', 3)
            pendientes = comentario.reportes.filter(
                estado=ReporteComentario.Estado.PENDIENTE
            ).count()
            if pendientes < umbral and comentario.oculto_por_reportes:
                comentario.oculto_por_reportes = False
                comentario.save(update_fields=['oculto_por_reportes'])
            messages.success(request, 'Reporte descartado y visibilidad del comentario verificada.')

        elif accion == 'revisado':
            reporte.estado = ReporteComentario.Estado.REVISADO
            reporte.revisado_por = request.user
            reporte.save(update_fields=['estado', 'revisado_por'])
            messages.success(request, 'Reporte marcado como revisado.')

        elif accion == 'eliminar_comentario':
            comentario.borrar_seguro()
            messages.warning(request, 'El comentario reportado ha sido eliminado.')

        else:
            messages.error(request, 'Acción no válida.')

        next_url = request.POST.get('next') or reverse('blog:panel_reporte_list')
        return redirect(next_url)


class PanelTaxonomiasView(LoginRequiredMixin, View):
    """Gestión de categorías y etiquetas (crear y listar) desde el panel de autor."""

    template_name = 'blog/panel/taxonomias.html'

    def obtener_contexto(self, form_categoria=None, form_etiqueta=None):
        return {
            'categorias': Categoria.objects.all(),
            'etiquetas': Etiqueta.objects.all(),
            'form_categoria': form_categoria or CategoriaForm(prefix='cat'),
            'form_etiqueta': form_etiqueta or EtiquetaForm(prefix='tag'),
        }

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self.obtener_contexto())

    def post(self, request, *args, **kwargs):
        tipo = request.POST.get('tipo')
        if tipo == 'categoria':
            form_cat = CategoriaForm(request.POST, prefix='cat')
            if form_cat.is_valid():
                categoria = form_cat.save()
                messages.success(request, f'Categoría "{categoria.nombre}" creada correctamente.')
                return redirect('blog:panel_taxonomias')
            return render(request, self.template_name, self.obtener_contexto(form_categoria=form_cat))

        elif tipo == 'etiqueta':
            form_tag = EtiquetaForm(request.POST, prefix='tag')
            if form_tag.is_valid():
                etiqueta = form_tag.save()
                messages.success(request, f'Etiqueta "{etiqueta.nombre}" creada correctamente.')
                return redirect('blog:panel_taxonomias')
            return render(request, self.template_name, self.obtener_contexto(form_etiqueta=form_tag))

        messages.error(request, 'Solicitud inválida.')
        return redirect('blog:panel_taxonomias')


class EtiquetaCrearAjaxView(LoginRequiredMixin, View):
    """Crea una nueva etiqueta vía AJAX desde el editor de posts."""

    def post(self, request, *args, **kwargs):
        nombre = (request.POST.get('nombre') or '').strip()
        if len(nombre) < 2:
            return JsonResponse({'ok': False, 'error': 'El nombre debe tener al menos 2 caracteres.'}, status=400)
        etiqueta, creada = Etiqueta.objects.get_or_create(nombre=nombre)
        return JsonResponse({
            'ok': True,
            'creada': creada,
            'id': etiqueta.pk,
            'nombre': etiqueta.nombre,
            'slug': etiqueta.slug,
        })



# ==============================================================================
# PÁGINAS INFORMATIVAS Y DE CONTACTO (/ACERCA/ Y /CONTACTO/)
# ==============================================================================

class AcercaDeView(TemplateView):
    """Página estática `/acerca/` con información sobre el blog y su arquitectura."""
    template_name = 'blog/acerca.html'


class PrivacidadView(TemplateView):
    """Página estática `/privacidad/` con la política de privacidad de la plataforma."""
    template_name = 'blog/privacidad.html'


class TerminosView(TemplateView):
    """Página estática `/terminos/` con los términos y condiciones de uso."""
    template_name = 'blog/terminos.html'


@method_decorator(limitar_tasa('contacto', 5, 3600), name='dispatch')
class ContactoView(View):
    """
    Página `/contacto/` con formulario (nombre, email, mensaje), honeypot (`sitio_web`)
    y límite de tasa (5/hora por IP) que envía un correo a los administradores.
    """
    template_name = 'blog/contacto.html'

    def get(self, request, *args, **kwargs):
        form = ContactoForm(user=request.user)
        return render(request, self.template_name, {'form': form})

    def post(self, request, *args, **kwargs):
        form = ContactoForm(request.POST, user=request.user)
        if form.is_valid():
            nombre = form.cleaned_data['nombre']
            email = form.cleaned_data['email']
            mensaje = form.cleaned_data['mensaje']

            admins_emails = list(
                User.objects.filter(is_active=True)
                .filter(Q(is_superuser=True) | Q(is_staff=True))
                .exclude(email='')
                .values_list('email', flat=True)
            )
            if not admins_emails:
                admins_emails = [getattr(settings, 'DEFAULT_FROM_EMAIL', 'admin@blogautores.local')]

            asunto = f'[Contacto Blog] Mensaje de {nombre}'
            cuerpo = (
                f'Nuevo mensaje recibido desde el formulario de contacto:\n\n'
                f'Nombre: {nombre}\n'
                f'Correo: {email}\n\n'
                f'Mensaje:\n{mensaje}\n'
            )
            send_mail(
                subject=asunto,
                message=cuerpo,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@blogautores.local'),
                recipient_list=list(dict.fromkeys(admins_emails)),
                fail_silently=True,
            )
            messages.success(
                request,
                '¡Gracias por escribirnos! Tu mensaje ha sido enviado a los administradores.'
            )
            return redirect('blog:contacto')

        return render(request, self.template_name, {'form': form})

