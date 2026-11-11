from django.conf import settings
from django.shortcuts import get_object_or_404
from blog.models import Comentario, Notificacion, Post, ReporteComentario
from blog.notificaciones import (
    notificar,
    notificar_menciones_comentario,
    notificar_respuesta_y_menciones_comentario,
)
from cuentas.models import Perfil


def elementos_pendientes(autor, filtro='todos'):
    """
    Retorna los elementos de moderación pendientes para los artículos del autor.
    Soporta los filtros:
    - 'todos': comentarios por aprobar y comentarios con reportes pendientes
    - 'por_aprobar': solo comentarios no aprobados
    - 'reportados': solo reportes pendientes
    """
    perfil = autor if isinstance(autor, Perfil) else getattr(autor, 'perfil', None)
    if not perfil:
        return []

    items = []

    # 1. Comentarios por aprobar
    if filtro in ('todos', 'por_aprobar'):
        comentarios_qs = (
            Comentario.objects.filter(
                post__autor=perfil,
                aprobado=False,
                eliminado=False,
            )
            .select_related('post', 'autor', 'autor__perfil', 'padre', 'padre__autor')
            .order_by('-creado')
        )
        for c in comentarios_qs:
            items.append({
                'id': f'comentario-{c.pk}',
                'pk': c.pk,
                'tipo': 'comentario',
                'comentario': c,
                'post': c.post,
                'autor_comentario': c.autor,
                'autor_nombre': c.autor.perfil.nombre_mostrar if (c.autor and hasattr(c.autor, 'perfil')) else (c.autor.username if c.autor else 'Anónimo'),
                'texto': c.texto,
                'fecha': c.creado,
                'motivo_reporte': None,
                'reporte_pk': None,
            })

    # 2. Reportes pendientes
    if filtro in ('todos', 'reportados'):
        reportes_qs = (
            ReporteComentario.objects.filter(
                comentario__post__autor=perfil,
                estado=ReporteComentario.Estado.PENDIENTE,
                comentario__eliminado=False,
            )
            .select_related('comentario', 'comentario__post', 'comentario__autor', 'reportante')
            .order_by('-creado')
        )
        for r in reportes_qs:
            c = r.comentario
            items.append({
                'id': f'reporte-{r.pk}',
                'pk': c.pk,
                'tipo': 'reporte',
                'comentario': c,
                'post': c.post,
                'autor_comentario': c.autor,
                'autor_nombre': c.autor.perfil.nombre_mostrar if (c.autor and hasattr(c.autor, 'perfil')) else (c.autor.username if c.autor else 'Anónimo'),
                'texto': c.texto,
                'fecha': r.creado,
                'motivo_reporte': r.get_motivo_display(),
                'detalle_reporte': r.detalle,
                'reportante': r.reportante,
                'reporte_pk': r.pk,
            })

    if filtro == 'todos':
        items.sort(key=lambda x: x['fecha'], reverse=True)

    return items


def aprobar_comentario(comentario_pk, usuario):
    """Aprueba un comentario y envía las notificaciones pertinentes."""
    perfil = getattr(usuario, 'perfil', None)
    comentario = get_object_or_404(
        Comentario.objects.select_related('post', 'post__autor', 'autor', 'padre', 'padre__autor'),
        pk=comentario_pk,
        post__autor=perfil,
    )
    comentario.aprobado = True
    comentario.save(update_fields=['aprobado'])

    if comentario.autor:
        notificar(
            destinatario=comentario.autor,
            tipo=Notificacion.Tipo.COMENTARIO_APROBADO,
            actor=usuario,
            post=comentario.post,
            comentario=comentario,
        )

    if comentario.padre:
        notificar_respuesta_y_menciones_comentario(comentario)
    else:
        notificar_respuesta_y_menciones_comentario(comentario)

    return comentario


def rechazar_comentario(comentario_pk, usuario):
    """Elimina de forma segura un comentario rechazado."""
    perfil = getattr(usuario, 'perfil', None)
    comentario = get_object_or_404(
        Comentario.objects.select_related('post', 'post__autor'),
        pk=comentario_pk,
        post__autor=perfil,
    )
    comentario.borrar_seguro()
    return comentario


def descartar_reporte(reporte_pk, usuario):
    """Descarta un reporte sobre un comentario."""
    perfil = getattr(usuario, 'perfil', None)
    reporte = get_object_or_404(
        ReporteComentario.objects.select_related('comentario', 'comentario__post'),
        pk=reporte_pk,
        comentario__post__autor=perfil,
    )
    reporte.estado = ReporteComentario.Estado.DESCARTADO
    reporte.revisado_por = usuario
    reporte.save(update_fields=['estado', 'revisado_por'])

    umbral = getattr(settings, 'REPORTES_PARA_OCULTAR', 3)
    pendientes = reporte.comentario.reportes.filter(
        estado=ReporteComentario.Estado.PENDIENTE
    ).count()
    if pendientes < umbral and reporte.comentario.oculto_por_reportes:
        reporte.comentario.oculto_por_reportes = False
        reporte.comentario.save(update_fields=['oculto_por_reportes'])

    return reporte
