from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.contrib.syndication.views import Feed
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy

from .models import Categoria, Post
from .templatetags.blog_extras import extracto_plano


class UltimosPostsFeed(Feed):
    link = reverse_lazy('blog:post_list')

    def title(self):
        marca = getattr(settings, 'SITE_NAME', 'Blog con Panel de Autor')
        return f'{marca} - Últimos Artículos'

    def description(self):
        marca = getattr(settings, 'SITE_NAME', 'Blog con Panel de Autor')
        return f'Artículos recientes publicados en {marca}.'

    def items(self):
        return Post.objects.publicados().con_relaciones()[:15]

    def item_title(self, item):
        return item.titulo

    def item_description(self, item):
        return extracto_plano(item.contenido, max_chars=160)

    def item_pubdate(self, item):
        return item.publicado_en or item.creado

    def item_author_name(self, item):
        return item.autor.nombre_mostrar


class CategoriaPostsFeed(UltimosPostsFeed):
    def get_object(self, request, slug):
        return get_object_or_404(Categoria, slug=slug)

    def title(self, obj):
        marca = getattr(settings, 'SITE_NAME', 'Blog con Panel de Autor')
        return f'{obj.nombre} - {marca}'

    def link(self, obj):
        return obj.get_absolute_url()

    def description(self, obj):
        return obj.descripcion or f'Artículos publicados en la comunidad {obj.nombre}.'

    def items(self, obj):
        return Post.objects.publicados().con_relaciones().filter(categoria=obj)[:15]


class PostSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Post.objects.publicados()

    def lastmod(self, obj):
        return obj.actualizado

