import json
import logging
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DeleteView, ListView

from blog.models import Categoria, Etiqueta, Perfil, Post, RevisionPost
from blog.plantillas_post import listar_plantillas, obtener_plantilla
from blog.templatetags.blog_extras import generar_toc_html
from .forms import PostEditorForm

logger = logging.getLogger(__name__)


class AutorPropietarioMixin(LoginRequiredMixin):
    """Garantiza que solo el autor propietario del post pueda acceder. Devuelve 404 para cualquier otro usuario."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        obj = self.get_object()
        if obj.autor.usuario_id != request.user.id:
            raise Http404('Post no encontrado.')
        return super().dispatch(request, *args, **kwargs)


class PostEditorView(LoginRequiredMixin, View):
    """
    Vista única del Estudio de Escritura para crear y editar posts.
    - Si se pasa slug, carga el post existente (solo autor propietario, 404 si es ajeno).
    - Si no se pasa slug, inicializa el lienzo (con plantilla opcional ?plantilla=<clave>).
    """
    template_name = 'blog/panel/editor/editor.html'

    def get(self, request, slug=None, *args, **kwargs):
        perfil, _ = Perfil.objects.get_or_create(usuario=request.user)

        post = None
        plantilla_datos = None
        revision_sin_publicar = None

        if slug:
            post = get_object_or_404(
                Post.objects.select_related('autor__usuario', 'categoria').prefetch_related('etiquetas'),
                slug=slug,
            )
            if post.autor.usuario_id != request.user.id:
                raise Http404('Post no encontrado.')

            # Comprobar si hay una revisión de autoguardado posterior en posts publicados o programados
            if post.estado in (Post.Estado.PUBLICADO, Post.Estado.PROGRAMADO):
                ultima_auto = (
                    RevisionPost.objects.filter(post=post, origen=RevisionPost.Origen.AUTO)
                    .order_by('-creado')
                    .first()
                )
                if ultima_auto and (ultima_auto.titulo != post.titulo or ultima_auto.contenido != post.contenido):
                    revision_sin_publicar = ultima_auto
        else:
            # Creación con posible plantilla o categoría
            plantilla_clave = (request.GET.get('plantilla') or '').strip()
            if plantilla_clave:
                plantilla_datos = obtener_plantilla(plantilla_clave)

        # Categoría preseleccionada por query param si es nuevo post
        categoria_id_inicial = None
        if not post:
            cat_param = (request.GET.get('categoria') or '').strip()
            if cat_param:
                cat = Categoria.objects.filter(slug=cat_param).first()
                if not cat and cat_param.isdigit():
                    cat = Categoria.objects.filter(pk=int(cat_param)).first()
                if cat:
                    categoria_id_inicial = cat.pk

        form = PostEditorForm(instance=post) if post else PostEditorForm(initial={
            'titulo': plantilla_datos['titulo_sugerido'] if plantilla_datos else '',
            'contenido': plantilla_datos['contenido_html'] if plantilla_datos else '',
            'categoria': categoria_id_inicial,
        })

        editor_config = {
            'post_id': post.pk if post else None,
            'slug': post.slug if post else '',
            'is_new': post is None,
            'estado': post.estado if post else 'borrador',
            'version': post.actualizado.isoformat() if post else None,
            'publicado_en': post.publicado_en.isoformat() if (post and post.publicado_en) else None,
            'programado_para': post.programado_para.isoformat() if (post and post.programado_para) else None,
            'slug_inmutable': bool(post and post.publicado_en is not None),
            'revision_sin_publicar_id': revision_sin_publicar.pk if revision_sin_publicar else None,
            'endpoints': {
                'autoguardar': reverse('blog:panel_api_autoguardar'),
                'vista_previa': reverse('blog:panel_api_vista_previa'),
                'historial': reverse('blog:panel_api_historial', kwargs={'pk': post.pk}) if post else '',
                'restaurar': reverse('blog:panel_api_restaurar', kwargs={'pk': post.pk}) if post else '',
                'portada_subir': reverse('blog:panel_api_portada_subir', kwargs={'pk': post.pk}) if post else '',
                'portada_quitar': reverse('blog:panel_api_portada_quitar', kwargs={'pk': post.pk}) if post else '',
                'publicar': reverse('blog:panel_api_publicar', kwargs={'pk': post.pk}) if post else '',
                'programar': reverse('blog:panel_api_programar', kwargs={'pk': post.pk}) if post else '',
                'despublicar': reverse('blog:panel_api_despublicar', kwargs={'pk': post.pk}) if post else '',
                'duplicar': reverse('blog:panel_api_duplicar', kwargs={'pk': post.pk}) if post else '',
                'destinatarios': reverse('blog:panel_api_destinatarios', kwargs={'pk': post.pk}) if post else '',
                'etiqueta_crear_ajax': reverse('blog:etiqueta_crear_ajax'),
            },
            'urls': {
                'panel': reverse('blog:panel_dashboard'),
                'mis_posts': reverse('blog:panel_post_list'),
                'nuevo_post': reverse('blog:panel_post_create'),
            },
        }

        # Etiquetas activas del post para chips interactivos
        etiquetas_post = list(post.etiquetas.values('id', 'nombre', 'slug')) if post else []

        context = {
            'post': post,
            'form': form,
            'categorias': Categoria.objects.all().order_by('nombre'),
            'todas_etiquetas': Etiqueta.objects.all().order_by('nombre'),
            'etiquetas': Etiqueta.objects.all().order_by('nombre'),
            'etiquetas_post_json': json.dumps(etiquetas_post),
            'editor_config': editor_config,
            'editor_config_json': json.dumps(editor_config),
            'plantilla_datos': plantilla_datos,
            'revision_sin_publicar': revision_sin_publicar,
            'es_modo_edicion': post is not None,
        }
        return render(request, self.template_name, context)


class PanelNuevoSelectorView(LoginRequiredMixin, View):
    """
    Página `/panel/nuevo/`: selector de plantillas de inicio antes de abrir el editor.
    Permite elegir entre plantillas predefinidas o empezar en blanco.
    """
    template_name = 'blog/panel/plantillas_selector.html'

    def get(self, request, *args, **kwargs):
        plantillas = listar_plantillas()
        categoria_param = (request.GET.get('categoria') or '').strip()
        context = {
            'plantillas': plantillas,
            'categoria_param': categoria_param,
        }
        return render(request, self.template_name, context)


class PostBorradorPreviewView(LoginRequiredMixin, View):
    """
    Vista previa de un post existente (borrador, publicado o programado)
    alimentada por el parcial `templates/blog/includes/_articulo.html`.
    """
    template_name = 'blog/panel/editor/borrador_preview.html'

    def get(self, request, slug, *args, **kwargs):
        post = get_object_or_404(
            Post.objects.select_related('autor__usuario', 'categoria').prefetch_related('etiquetas'),
            slug=slug,
        )
        if post.autor.usuario_id != request.user.id and not request.user.is_staff:
            raise Http404('Post no encontrado.')

        toc_items = generar_toc_html(post.contenido or '')
        context = {
            'post': post,
            'toc_items': toc_items,
            'es_vista_previa': True,
        }
        return render(request, self.template_name, context)


class PanelPostListView(LoginRequiredMixin, ListView):
    """
    Lista renovada «Mis posts» en el Panel de Autor:
    - Pestañas con contadores en tiempo real (Todos, Borradores, Publicados, Programados).
    - Búsqueda por título o contenido, filtro por categoría y ordenación.
    - Miniatura de portada, métricas rápidas (vistas, likes, comentarios).
    - Acciones rápidas (editar, vista previa, duplicar, publicar/despublicar, eliminar).
    - Consulta optimizada sin N+1.
    """
    model = Post
    template_name = 'blog/panel/post_list.html'
    context_object_name = 'posts'
    paginate_by = 12

    def get_queryset(self):
        perfil, _ = Perfil.objects.get_or_create(usuario=self.request.user)
        qs = (
            Post.objects.filter(autor=perfil)
            .select_related('categoria', 'autor__usuario')
            .prefetch_related('etiquetas')
            .annotate(
                total_likes_count=Count('likes', distinct=True),
                total_comentarios_count=Count('comentarios', filter=Q(comentarios__aprobado=True), distinct=True),
            )
        )

        # Filtro de búsqueda
        q = (self.request.GET.get('q') or '').strip()
        if q:
            qs = qs.filter(Q(titulo__icontains=q) | Q(contenido__icontains=q))

        # Filtro de categoría
        cat_slug = (self.request.GET.get('categoria') or '').strip()
        if cat_slug:
            qs = qs.filter(categoria__slug=cat_slug)

        # Filtro por pestaña de estado
        estado = (self.request.GET.get('estado') or 'todos').lower()
        if estado == 'borradores':
            qs = qs.filter(estado=Post.Estado.BORRADOR)
        elif estado == 'publicados':
            qs = qs.filter(estado=Post.Estado.PUBLICADO)
        elif estado == 'programados':
            qs = qs.filter(estado=Post.Estado.PROGRAMADO)

        # Ordenación
        orden = self.request.GET.get('orden', 'recientes')
        if orden == 'antiguos':
            qs = qs.order_by('creado')
        elif orden == 'mas_likes':
            qs = qs.order_by('-total_likes_count', '-creado')
        else:
            qs = qs.order_by('-actualizado', '-creado')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        perfil, _ = Perfil.objects.get_or_create(usuario=self.request.user)
        mis_posts_base = Post.objects.filter(autor=perfil)

        context['total_todos'] = mis_posts_base.count()
        context['total_borradores'] = mis_posts_base.filter(estado=Post.Estado.BORRADOR).count()
        context['total_publicados'] = mis_posts_base.filter(estado=Post.Estado.PUBLICADO).count()
        context['total_programados'] = mis_posts_base.filter(estado=Post.Estado.PROGRAMADO).count()

        context['categorias'] = Categoria.objects.all().order_by('nombre')
        context['estado_actual'] = self.request.GET.get('estado', 'todos').lower()
        context['q_actual'] = self.request.GET.get('q', '').strip()
        context['categoria_actual'] = self.request.GET.get('categoria', '').strip()
        context['orden_actual'] = self.request.GET.get('orden', 'recientes')

        return context


class PanelPostDeleteView(AutorPropietarioMixin, DeleteView):
    """Eliminación de posts propios con confirmación."""
    model = Post
    template_name = 'blog/panel/post_confirm_delete.html'
    slug_url_kwarg = 'slug'
    success_url = reverse_lazy('blog:panel_post_list')

    def get_object(self, queryset=None):
        return get_object_or_404(Post, slug=self.kwargs['slug'])

    def form_valid(self, form):
        titulo = self.object.titulo
        response = super().form_valid(form)
        messages.success(self.request, f'El post "{titulo}" ha sido eliminado.')
        return response
