import logging
import re
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db.models import Q
from django.urls import reverse

from .models import Notificacion

logger = logging.getLogger(__name__)
User = get_user_model()

MENCION_REGEX = re.compile(r'(?<!\w)@([a-zA-Z0-9_.\-+]{1,150})')


def extraer_usuarios_mencionados(texto, max_menciones=5):
    """
    Detecta menciones @nombredeusuario en `texto` con una expresión regular,
    conservando el orden de aparición, sin duplicados, hasta un máximo de
    `max_menciones` usuarios que realmente existan en la base de datos.
    """
    if not texto:
        return []

    candidatos = []
    vistos = set()
    for coincidencia in MENCION_REGEX.finditer(str(texto)):
        username = coincidencia.group(1)
        clave = username.lower()
        if clave not in vistos:
            vistos.add(clave)
            candidatos.append(username)

    if not candidatos:
        return []

    usuarios_db = {
        u.username.lower(): u
        for u in User.objects.filter(username__in=candidatos, is_active=True)
    }

    encontrados = []
    for username in candidatos:
        usuario = usuarios_db.get(username.lower())
        if usuario:
            encontrados.append(usuario)
            if len(encontrados) >= max_menciones:
                break

    return encontrados


def construir_mensaje_y_url(tipo, actor=None, post=None, comentario=None, url_destino=None, mensaje_extra=None):
    """Construye el mensaje en español y la URL de destino según el tipo de notificación."""
    if actor:
        perfil = getattr(actor, 'perfil', None)
        nombre_actor = perfil.nombre_mostrar if perfil else (actor.get_full_name() or actor.username)
    else:
        nombre_actor = 'Un lector'
    if post is None and comentario is not None:
        post = comentario.post

    titulo_post = f'"{post.titulo}"' if post else 'tu publicación'
    url_por_defecto = post.get_absolute_url() if post else reverse('blog:post_list')

    if tipo == Notificacion.Tipo.COMENTARIO_NUEVO:
        autor_com = comentario.nombre if comentario else nombre_actor
        mensaje = f'{autor_com} dejó un nuevo comentario en {titulo_post} (pendiente de moderación).'
        url = url_destino or f"{reverse('blog:panel_comentario_list')}?estado=pendientes"

    elif tipo == Notificacion.Tipo.COMENTARIO_APROBADO:
        mensaje = f'Tu comentario en {titulo_post} ha sido aprobado y ya es público.'
        ancla = f"#comentario-{comentario.pk}" if comentario else "#comentarios"
        url = url_destino or f"{url_por_defecto}{ancla}"

    elif tipo == Notificacion.Tipo.RESPUESTA_COMENTARIO:
        autor_com = comentario.nombre if (comentario and not actor) else f"@{nombre_actor}"
        mensaje = f'{autor_com} respondió a tu comentario en {titulo_post}.'
        ancla = f"#comentario-{comentario.pk}" if comentario else "#comentarios"
        url = url_destino or f"{url_por_defecto}{ancla}"

    elif tipo == Notificacion.Tipo.MENCION:
        autor_com = comentario.nombre if (comentario and not actor) else f"@{nombre_actor}"
        mensaje = f'{autor_com} te mencionó en un comentario en {titulo_post}.'
        ancla = f"#comentario-{comentario.pk}" if comentario else "#comentarios"
        url = url_destino or f"{url_por_defecto}{ancla}"

    elif tipo == Notificacion.Tipo.LIKE_POST:
        mensaje = f'A @{nombre_actor} le gustó tu artículo {titulo_post}.'
        url = url_destino or url_por_defecto

    elif tipo == Notificacion.Tipo.LIKE_COMENTARIO:
        mensaje = f'A @{nombre_actor} le gustó tu comentario en {titulo_post}.'
        ancla = f"#comentario-{comentario.pk}" if comentario else "#comentarios"
        url = url_destino or f"{url_por_defecto}{ancla}"

    elif tipo == Notificacion.Tipo.SEGUIDOR_NUEVO:
        mensaje = f'@{nombre_actor} comenzó a seguirte.'
        url = url_destino or (reverse('blog:autor_detail', kwargs={'username': actor.username}) if actor else '/')

    elif tipo == Notificacion.Tipo.POST_NUEVO:
        mensaje = f'@{nombre_actor} publicó un nuevo artículo: {titulo_post}.'
        url = url_destino or url_por_defecto

    elif tipo == Notificacion.Tipo.REPORTE_COMENTARIO:
        detalle_motivo = f" ({mensaje_extra})" if mensaje_extra else ""
        mensaje = f'@{nombre_actor} reportó un comentario en {titulo_post}{detalle_motivo}.'
        url = url_destino or reverse('blog:panel_reporte_list')

    else:
        mensaje = mensaje_extra or f'Nueva notificación en {titulo_post}.'
        url = url_destino or url_por_defecto

    return mensaje[:350], url[:350]


def notificar(destinatario, tipo, actor=None, post=None, comentario=None, url_destino=None, mensaje_extra=None):
    """
    Función central para crear notificaciones:
    - No notifica a uno mismo (si actor == destinatario).
    - No duplica la misma combinación destinatario + actor + tipo + post + comentario.
    - Arma el mensaje en español y la URL de destino automáticamente.
    """
    if destinatario is None:
        return None

    if actor is not None and destinatario.pk == actor.pk:
        return None

    if post is None and comentario is not None:
        post = comentario.post

    Existente = Notificacion.objects.filter(
        destinatario=destinatario,
        tipo=tipo,
        actor=actor,
        post=post,
        comentario=comentario,
    ).first()

    if Existente:
        return Existente

    mensaje, url = construir_mensaje_y_url(
        tipo=tipo,
        actor=actor,
        post=post,
        comentario=comentario,
        url_destino=url_destino,
        mensaje_extra=mensaje_extra,
    )

    return Notificacion.objects.create(
        destinatario=destinatario,
        tipo=tipo,
        actor=actor,
        post=post,
        comentario=comentario,
        mensaje=mensaje,
        url=url,
    )


def eliminar_notificacion(destinatario, tipo, actor=None, post=None, comentario=None):
    """Elimina la notificación asociada (por ejemplo, al quitar un 'Me gusta')."""
    if destinatario is None:
        return 0
    if post is None and comentario is not None:
        post = comentario.post
    qs = Notificacion.objects.filter(
        destinatario=destinatario,
        tipo=tipo,
        actor=actor,
        post=post,
        comentario=comentario,
    )
    eliminadas, _ = qs.delete()
    return eliminadas


def notificar_menciones_comentario(comentario, excluir_ids=None):
    """
    Envía notificaciones MENCION a los usuarios mencionados en `comentario.texto`
    (máximo 5 usuarios existentes) únicamente cuando el comentario está aprobado.
    """
    if not comentario or not comentario.aprobado:
        return []

    excluir = set(excluir_ids or ())
    usuarios = extraer_usuarios_mencionados(comentario.texto, max_menciones=5)
    notificaciones_creadas = []
    for usuario in usuarios:
        if usuario.pk in excluir:
            continue
        notif = notificar(
            destinatario=usuario,
            tipo=Notificacion.Tipo.MENCION,
            actor=comentario.autor,
            post=comentario.post,
            comentario=comentario,
        )
        if notif:
            notificaciones_creadas.append(notif)
    return notificaciones_creadas


def notificar_respuesta_y_menciones_comentario(comentario):
    """
    Al aprobarse un comentario (o publicarse auto-aprobado):
    - Si tiene `padre` y el autor del `padre` es usuario registrado (`padre.autor`),
      le envía `RESPUESTA_COMENTARIO` (y si el autor del padre es también el autor del post,
      evita que tenga un segundo aviso `COMENTARIO_NUEVO` duplicado por el mismo comentario).
    - Envía los avisos `MENCION` sin duplicar al destinatario de `RESPUESTA_COMENTARIO`.
    """
    if not comentario or not comentario.aprobado:
        return

    excluir_mencion = set()
    if comentario.padre_id and comentario.padre and comentario.padre.autor_id:
        autor_padre = comentario.padre.autor
        autor_post_id = comentario.post.autor.usuario_id

        # Si el autor del comentario padre es también el autor del post:
        # si ya recibió COMENTARIO_NUEVO por este mismo comentario (cuando estuvo pendiente),
        # no creamos un segundo aviso duplicado; si no tenía aviso previo, recibe RESPUESTA_COMENTARIO.
        ya_notificado_como_autor_post = (
            autor_padre.pk == autor_post_id
            and Notificacion.objects.filter(
                destinatario=autor_padre,
                tipo=Notificacion.Tipo.COMENTARIO_NUEVO,
                comentario=comentario,
            ).exists()
        )
        if not ya_notificado_como_autor_post:
            notificar(
                destinatario=autor_padre,
                tipo=Notificacion.Tipo.RESPUESTA_COMENTARIO,
                actor=comentario.autor,
                post=comentario.post,
                comentario=comentario,
            )
        excluir_mencion.add(autor_padre.pk)

    notificar_menciones_comentario(comentario, excluir_ids=excluir_mencion)


def notificar_reporte_comentario(reporte, request=None):
    """
    Envía notificación del sitio (REPORTE_COMENTARIO) y correo electrónico en español
    tanto al autor del post como a todos los administradores activos (`is_staff` o `is_superuser`).
    Si un usuario es a la vez autor del post y administrador, recibe un único aviso.
    Cualquier fallo en el envío de correo se registra en el log sin interrumpir el reporte.
    """
    comentario = reporte.comentario
    post = comentario.post
    autor_post_user = post.autor.usuario
    reportante = reporte.reportante

    admins = list(
        User.objects.filter(
            is_active=True
        ).filter(
            Q(is_staff=True) | Q(is_superuser=True)
        )
    )

    # Diccionario de destinatarios únicos por ID de usuario (sin duplicar si autor es admin)
    destinatarios_map = {}
    if autor_post_user.is_active:
        destinatarios_map[autor_post_user.pk] = (autor_post_user, False)

    for admin_user in admins:
        es_solo_admin = admin_user.pk != autor_post_user.pk
        destinatarios_map[admin_user.pk] = (admin_user, es_solo_admin)

    url_panel = reverse('blog:panel_reporte_list')
    url_admin = reverse('admin:blog_reportecomentario_changelist')

    if request:
        url_panel_abs = request.build_absolute_uri(url_panel)
        url_admin_abs = request.build_absolute_uri(url_admin)
    else:
        url_panel_abs = url_panel
        url_admin_abs = url_admin

    motivo_display = reporte.get_motivo_display()

    for user_id, (destinatario, usar_enlace_admin) in destinatarios_map.items():
        if destinatario.pk == reportante.pk:
            continue

        es_admin = destinatario.is_staff or destinatario.is_superuser
        es_autor = destinatario.pk == autor_post_user.pk

        # Si es el autor del post, el enlace principal lleva a su panel; si es solo admin, al admin de Django
        enlace_relativo = url_panel if es_autor else url_admin
        enlace_correo = url_panel_abs if es_autor else url_admin_abs

        notificar(
            destinatario=destinatario,
            tipo=Notificacion.Tipo.REPORTE_COMENTARIO,
            actor=reportante,
            post=post,
            comentario=comentario,
            url_destino=enlace_relativo,
            mensaje_extra=motivo_display,
        )

        if destinatario.email:
            asunto = f'[Moderación] Reporte de comentario en "{post.titulo}"'
            cuerpo = (
                f"Hola {destinatario.get_full_name() or destinatario.username},\n\n"
                f"Se ha recibido un nuevo reporte sobre un comentario en el blog:\n\n"
                f"- Artículo: {post.titulo}\n"
                f"- Reportado por: @{reportante.username}\n"
                f"- Motivo: {motivo_display}\n"
                f"- Detalle adicional: {reporte.detalle or 'Sin detalle adicional'}\n"
                f"- Texto del comentario ({comentario.nombre}):\n"
                f"  \"{comentario.texto}\"\n\n"
                f"Puedes revisar y resolver este reporte en el siguiente enlace:\n"
                f"{enlace_correo}\n"
            )
            if es_autor and es_admin:
                cuerpo += f"\nEnlace alternativo al Admin de Django: {url_admin_abs}\n"

            try:
                send_mail(
                    subject=asunto,
                    message=cuerpo,
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@blogautores.local'),
                    recipient_list=[destinatario.email],
                    fail_silently=False,
                )
            except Exception as exc:
                logger.error("Error enviando correo de reporte a %s: %s", destinatario.email, exc)

