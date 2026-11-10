from django.conf import settings
from django.contrib import admin
from django.db.models import Count, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce
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
    notificar,
    notificar_respuesta_y_menciones_comentario,
)


class ReglaCategoriaInline(admin.TabularInline):
    model = ReglaCategoria
    extra = 1
    fields = ('orden', 'titulo', 'descripcion')
    ordering = ('orden', 'id')


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'slug', 'numero_posts', 'numero_miembros', 'creada')
    list_filter = ('creada',)
    search_fields = ('nombre', 'slug', 'descripcion')
    prepopulated_fields = {'slug': ('nombre',)}
    inlines = [ReglaCategoriaInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        sub_posts = (
            Post.objects.filter(categoria=OuterRef('pk'))
            .values('categoria')
            .annotate(total=Count('id'))
            .values('total')[:1]
        )
        sub_miembros = (
            MiembroCategoria.objects.filter(categoria=OuterRef('pk'))
            .values('categoria')
            .annotate(total=Count('id'))
            .values('total')[:1]
        )
        return qs.annotate(
            _posts_count=Coalesce(Subquery(sub_posts, output_field=IntegerField()), 0),
            _miembros_count=Coalesce(Subquery(sub_miembros, output_field=IntegerField()), 0),
        )

    @admin.display(description='N.º de posts', ordering='_posts_count')
    def numero_posts(self, obj):
        return getattr(obj, '_posts_count', 0)

    @admin.display(description='N.º de miembros', ordering='_miembros_count')
    def numero_miembros(self, obj):
        return getattr(obj, '_miembros_count', 0)


@admin.register(MiembroCategoria)
class MiembroCategoriaAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'categoria', 'creado')
    list_filter = ('categoria', 'creado')
    search_fields = ('usuario__username', 'categoria__nombre')
    list_select_related = ('usuario', 'categoria')


@admin.register(Etiqueta)
class EtiquetaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'slug')
    list_filter = ('nombre',)
    search_fields = ('nombre', 'slug')
    prepopulated_fields = {'slug': ('nombre',)}


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = (
        'titulo',
        'slug',
        'autor',
        'categoria',
        'estado',
        'fijado_en_categoria',
        'publicado_en',
        'creado',
    )
    list_filter = ('estado', 'fijado_en_categoria', 'categoria', 'etiquetas', 'publicado_en', 'creado')
    search_fields = ('titulo', 'slug', 'contenido', 'autor__usuario__username')
    prepopulated_fields = {'slug': ('titulo',)}
    filter_horizontal = ('etiquetas',)
    date_hierarchy = 'publicado_en'
    list_select_related = ('autor', 'autor__usuario', 'categoria')


class TipoComentarioFilter(admin.SimpleListFilter):
    title = 'Nivel del comentario'
    parameter_name = 'nivel_comentario'

    def lookups(self, request, model_admin):
        return (
            ('principales', 'Comentarios principales'),
            ('respuestas', 'Respuestas (en hilo)'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'principales':
            return queryset.filter(padre__isnull=True)
        if self.value() == 'respuestas':
            return queryset.filter(padre__isnull=False)
        return queryset


@admin.register(Comentario)
class ComentarioAdmin(admin.ModelAdmin):
    list_display = (
        'nombre',
        'email',
        'autor',
        'post',
        'en_respuesta_a',
        'aprobado',
        'eliminado',
        'editado',
        'oculto_por_reportes',
        'creado',
    )
    list_filter = (TipoComentarioFilter, 'aprobado', 'eliminado', 'editado', 'oculto_por_reportes', 'creado')
    search_fields = ('nombre', 'email', 'texto', 'post__titulo', 'autor__username')
    actions = ['aprobar_comentarios', 'desaprobar_comentarios']
    list_select_related = ('post', 'autor', 'padre')

    @admin.display(description='En respuesta a')
    def en_respuesta_a(self, obj):
        if obj.padre_id and obj.padre:
            return f"#{obj.padre_id} ({obj.padre.nombre})"
        return "—"

    def delete_model(self, request, obj):
        obj.borrar_seguro()

    def delete_queryset(self, request, queryset):
        for com in queryset:
            com.borrar_seguro()

    @admin.action(description='Aprobar comentarios seleccionados')
    def aprobar_comentarios(self, request, queryset):
        comentarios = list(
            queryset.select_related('post', 'post__autor__usuario', 'autor', 'padre', 'padre__autor')
        )
        actualizados = queryset.update(aprobado=True)
        for com in comentarios:
            com.aprobado = True
            if com.autor:
                notificar(
                    destinatario=com.autor,
                    tipo=Notificacion.Tipo.COMENTARIO_APROBADO,
                    actor=request.user,
                    post=com.post,
                    comentario=com,
                )
            notificar_respuesta_y_menciones_comentario(com)
        self.message_user(request, f"{actualizados} comentario(s) aprobado(s) correctamente.")

    @admin.action(description='Desaprobar comentarios seleccionados')
    def desaprobar_comentarios(self, request, queryset):
        actualizados = queryset.update(aprobado=False)
        self.message_user(request, f"{actualizados} comentario(s) marcado(s) como pendiente(s).")


@admin.register(ReporteComentario)
class ReporteComentarioAdmin(admin.ModelAdmin):
    list_display = ('id', 'comentario', 'motivo', 'reportante', 'estado', 'revisado_por', 'creado')
    list_filter = ('estado', 'motivo', 'creado')
    search_fields = ('comentario__texto', 'detalle', 'reportante__username', 'comentario__post__titulo')
    list_select_related = ('comentario', 'comentario__post', 'reportante', 'revisado_por')
    actions = ['marcar_revisado', 'descartar_reportes', 'eliminar_comentario_reportado']

    @admin.action(description='Marcar reportes seleccionados como revisados')
    def marcar_revisado(self, request, queryset):
        actualizados = queryset.update(
            estado=ReporteComentario.Estado.REVISADO,
            revisado_por=request.user,
        )
        self.message_user(request, f"{actualizados} reporte(s) marcado(s) como revisado(s).")

    @admin.action(description='Descartar reportes seleccionados (restaura visibilidad del comentario)')
    def descartar_reportes(self, request, queryset):
        comentarios_ids = set(queryset.values_list('comentario_id', flat=True))
        actualizados = queryset.update(
            estado=ReporteComentario.Estado.DESCARTADO,
            revisado_por=request.user,
        )
        umbral = getattr(settings, 'REPORTES_PARA_OCULTAR', 3)
        for com_id in comentarios_ids:
            pendientes = ReporteComentario.objects.filter(
                comentario_id=com_id,
                estado=ReporteComentario.Estado.PENDIENTE,
            ).count()
            if pendientes < umbral:
                Comentario.objects.filter(pk=com_id, oculto_por_reportes=True).update(oculto_por_reportes=False)
        self.message_user(request, f"{actualizados} reporte(s) descartado(s) y visibilidad actualizada.")

    @admin.action(description='Eliminar comentario asociado a los reportes seleccionados')
    def eliminar_comentario_reportado(self, request, queryset):
        comentarios_ids = set(queryset.values_list('comentario_id', flat=True))
        for com in Comentario.objects.filter(pk__in=comentarios_ids):
            com.borrar_seguro()
        self.message_user(request, f"Se procesó el borrado seguro de los comentarios asociados ({len(comentarios_ids)}).")


@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ('destinatario', 'tipo', 'actor', 'leida', 'creado')
    list_filter = ('tipo', 'leida', 'creado')
    search_fields = ('destinatario__username', 'mensaje')


@admin.register(LikePost)
class LikePostAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'post', 'creado')
    list_filter = ('creado',)
    search_fields = ('usuario__username', 'post__titulo')


@admin.register(VotoUtil)
class VotoUtilAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'post', 'util', 'creado')
    list_filter = ('util', 'creado')
    search_fields = ('usuario__username', 'post__titulo')


@admin.register(LikeComentario)
class LikeComentarioAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'comentario', 'creado')
    list_filter = ('creado',)
    search_fields = ('usuario__username', 'comentario__texto')


@admin.register(Seguimiento)
class SeguimientoAdmin(admin.ModelAdmin):
    list_display = ('seguidor', 'autor', 'creado')
    list_filter = ('creado',)
    search_fields = ('seguidor__username', 'autor__usuario__username')


@admin.register(Suscripcion)
class SuscripcionAdmin(admin.ModelAdmin):
    list_display = ('email', 'usuario', 'autor', 'categoria', 'confirmada', 'activa', 'creado')
    list_filter = ('confirmada', 'activa', 'creado')
    search_fields = ('email', 'usuario__username', 'autor__usuario__username', 'categoria__nombre')


@admin.register(VistaDiaria)
class VistaDiariaAdmin(admin.ModelAdmin):
    list_display = ('post', 'fecha', 'cantidad')
    list_filter = ('fecha',)
    search_fields = ('post__titulo',)


@admin.register(ListaLectura)
class ListaLecturaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'usuario', 'publica', 'es_predeterminada', 'creado')
    list_filter = ('publica', 'es_predeterminada', 'creado')
    search_fields = ('nombre', 'usuario__username', 'descripcion')


@admin.register(ItemLista)
class ItemListaAdmin(admin.ModelAdmin):
    list_display = ('lista', 'post', 'agregado')
    list_filter = ('agregado',)
    search_fields = ('lista__nombre', 'post__titulo')

