from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from . import views
from .feeds import CategoriaPostsFeed, PostSitemap, UltimosPostsFeed

app_name = 'blog'

sitemaps = {
    'posts': PostSitemap,
}

urlpatterns = [
    # Parte pública
    path('', views.PostListView.as_view(), name='post_list'),
    path('acerca/', views.AcercaDeView.as_view(), name='acerca'),
    path('privacidad/', views.PrivacidadView.as_view(), name='privacidad'),
    path('terminos/', views.TerminosView.as_view(), name='terminos'),
    path('contacto/', views.ContactoView.as_view(), name='contacto'),
    path('feed/', UltimosPostsFeed(), name='rss_feed'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path('feed/novedades/', views.FeedNovedadesView.as_view(), name='feed_novedades'),
    path('explorar/', views.ExplorarView.as_view(), name='explorar'),
    path('buscar/sugerencias/', views.BuscarSugerenciasView.as_view(), name='buscar_sugerencias'),
    path('buscar/', views.BuscarPostsView.as_view(), name='buscar_posts'),
    path('categoria/<slug:slug>/', views.PostPorCategoriaView.as_view(), name='posts_por_categoria'),
    path('categoria/<slug:slug>/unirse/', views.ToggleUnirseCategoriaView.as_view(), name='categoria_unirse_toggle'),
    path('categoria/<slug:slug>/feed/', CategoriaPostsFeed(), name='categoria_rss_feed'),
    path('etiqueta/<slug:slug>/', views.PostPorEtiquetaView.as_view(), name='posts_por_etiqueta'),
    path('autor/<str:username>/', views.AutorDetailView.as_view(), name='autor_detail'),
    path('post/<slug:slug>/', views.PostDetailView.as_view(), name='post_detail'),
    path('post/<slug:slug>/embed/', views.PostEmbedView.as_view(), name='post_embed'),

    # Notificaciones
    path('notificaciones/', views.NotificacionListView.as_view(), name='notificaciones_list'),
    path('notificaciones/contador/', views.NotificacionContadorView.as_view(), name='notificaciones_contador'),
    path('notificaciones/marcar-todas/', views.NotificacionMarcarTodasLeidasView.as_view(), name='notificaciones_marcar_todas'),
    path('notificaciones/<int:pk>/ir/', views.NotificacionIrView.as_view(), name='notificacion_ir'),
    path('notificaciones/<int:pk>/leer/', views.NotificacionMarcarLeidaView.as_view(), name='notificacion_leer'),

    # Interacciones con el post (Likes, Voto útil, Guardar en listas)
    path('post/<slug:slug>/like/', views.ToggleLikePostView.as_view(), name='post_like_toggle'),
    path('post/<slug:slug>/votar-util/', views.VotarUtilPostView.as_view(), name='post_votar_util'),
    path('post/<slug:slug>/guardar/', views.ToggleGuardadoPostView.as_view(), name='post_guardar_toggle'),
    path('post/<slug:slug>/agregar-a-lista/', views.AgregarPostAListaView.as_view(), name='post_agregar_a_lista'),

    # Interacciones con comentarios y autocompletado de menciones
    path('comentario/<int:pk>/like/', views.ToggleLikeComentarioView.as_view(), name='comentario_like_toggle'),
    path('comentario/<int:pk>/editar/', views.EditarComentarioView.as_view(), name='comentario_editar'),
    path('comentario/<int:pk>/eliminar/', views.BorrarComentarioView.as_view(), name='comentario_eliminar'),
    path('comentario/<int:pk>/reportar/', views.ReportarComentarioView.as_view(), name='comentario_reportar'),
    path('usuarios/buscar/', views.BuscarUsuariosMencionView.as_view(), name='buscar_usuarios_mencion'),

    # Ronda 2 - Bloque 1: Seguir autores
    path('autor/<str:username>/seguir/', views.ToggleSeguirAutorView.as_view(), name='autor_seguir_toggle'),
    path('siguiendo/', views.SiguiendoFeedView.as_view(), name='siguiendo_feed'),

    # Ronda 2 - Bloque 2: Suscripciones por correo
    path('suscripcion/crear/', views.CrearSuscripcionView.as_view(), name='suscripcion_crear'),
    path('suscripcion/confirmar/<uuid:token>/', views.ConfirmarSuscripcionView.as_view(), name='suscripcion_confirmar'),
    path('suscripcion/baja/<uuid:token>/', views.BajaSuscripcionView.as_view(), name='suscripcion_baja'),
    path('mis-suscripciones/', views.MisSuscripcionesView.as_view(), name='mis_suscripciones'),

    # Ronda 2 - Bloque 3 y 4: Más populares y Autores destacados
    path('populares/', views.PostsPopularesView.as_view(), name='posts_populares'),
    path('autores/', views.AutoresListView.as_view(), name='autores_list'),

    # Ronda 2 - Bloque 5: Listas de lectura
    path('guardados/', views.GuardadosRedirectView.as_view(), name='guardados'),
    path('mis-listas/', views.MisListasView.as_view(), name='mis_listas'),
    path('listas/<int:pk>/', views.ListaLecturaDetailView.as_view(), name='lista_detail'),
    path('listas/<int:pk>/editar/', views.EditarListaLecturaView.as_view(), name='lista_editar'),
    path('listas/<int:pk>/visibilidad/', views.ToggleVisibilidadListaView.as_view(), name='lista_visibilidad'),
    path('listas/<int:pk>/eliminar/', views.EliminarListaLecturaView.as_view(), name='lista_eliminar'),
    path('listas/<int:pk>/quitar/<int:post_id>/', views.QuitarItemListaView.as_view(), name='lista_quitar_item'),

    # Panel de autor
    path('panel/', views.PanelDashboardView.as_view(), name='panel_dashboard'),
    path('panel/', include('blog.panel.urls')),
    path('panel/posts/<slug:slug>/cambiar-estado/', views.PanelPostCambiarEstadoView.as_view(), name='panel_post_toggle_status'),
    path('panel/comentarios/', views.PanelComentarioListView.as_view(), name='panel_comentario_list'),
    path('panel/comentarios/<int:pk>/accion/', views.PanelComentarioAccionView.as_view(), name='panel_comentario_accion'),
    path('panel/reportes/', views.PanelReporteListView.as_view(), name='panel_reporte_list'),
    path('panel/reportes/<int:pk>/accion/', views.PanelReporteAccionView.as_view(), name='panel_reporte_accion'),
    path('panel/taxonomias/', views.PanelTaxonomiasView.as_view(), name='panel_taxonomias'),
    path('panel/etiquetas/crear-ajax/', views.EtiquetaCrearAjaxView.as_view(), name='etiqueta_crear_ajax'),
]
