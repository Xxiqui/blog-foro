import logging
import re
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db.models import Q
from django.urls import reverse
from django.utils.html import escape

from .models import Suscripcion

logger = logging.getLogger(__name__)

PRIMERA_IMAGEN_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def construir_url_absoluta(ruta, request=None):
    """Construye una URL absoluta usando `request` si está disponible o `settings.SITE_URL`."""
    if request is not None:
        return request.build_absolute_uri(ruta)
    base = getattr(settings, 'SITE_URL', 'http://localhost:8000').rstrip('/')
    if not ruta.startswith('/'):
        ruta = '/' + ruta
    return f"{base}{ruta}"


def obtener_imagen_portada_post(post, request=None):
    """Obtiene la URL de portada si existe como campo o primera imagen del contenido."""
    imagen_campo = getattr(post, 'imagen_portada', None)
    if imagen_campo and hasattr(imagen_campo, 'url'):
        return construir_url_absoluta(imagen_campo.url, request=request)
    match = PRIMERA_IMAGEN_RE.search(post.contenido or '')
    if match:
        src = match.group(1)
        if src.startswith('http://') or src.startswith('https://'):
            return src
        return construir_url_absoluta(src, request=request)
    return None


def enviar_correo_confirmacion_suscripcion(suscripcion, request=None):
    """
    Envía el correo de doble confirmación con el enlace `/suscripcion/confirmar/<token>/`.
    Aislado en `blog/emails.py` para facilitar su futura migración a Celery.
    """
    ruta_confirmar = reverse('blog:suscripcion_confirmar', kwargs={'token': suscripcion.token})
    ruta_baja = reverse('blog:suscripcion_baja', kwargs={'token': suscripcion.token})
    url_confirmar = construir_url_absoluta(ruta_confirmar, request=request)
    url_baja = construir_url_absoluta(ruta_baja, request=request)

    destino = suscripcion.destino_nombre
    asunto = f'Confirma tu suscripción a {destino} | Blog con Panel de Autor'

    texto_plano = (
        f"Hola,\n\n"
        f"Has solicitado suscribirte por correo a {destino} en Blog con Panel de Autor.\n"
        f"Para activar tu suscripción (doble confirmación), abre el siguiente enlace:\n"
        f"{url_confirmar}\n\n"
        f"Si no solicitaste esta suscripción o deseas cancelarla en cualquier momento:\n"
        f"{url_baja}\n"
    )

    cuerpo_html = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; color: #1e293b;">
        <h2 style="color: #0d6efd;">Confirma tu suscripción</h2>
        <p>Has solicitado recibir notificaciones por correo electrónico de <strong>{escape(destino)}</strong>.</p>
        <p style="margin: 24px 0;">
            <a href="{escape(url_confirmar)}"
               style="background-color: #0d6efd; color: #ffffff; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold;">
               Confirmar mi suscripción
            </a>
        </p>
        <p style="font-size: 12px; color: #64748b;">
            Hasta que no confirmes este enlace no recibirás ningún boletín.<br>
            Si no realizaste esta solicitud, puedes ignorar este mensaje o
            <a href="{escape(url_baja)}">darte de baja aquí</a>.
        </p>
    </div>
    """

    try:
        with get_connection(fail_silently=True) as conn:
            msg = EmailMultiAlternatives(
                subject=asunto,
                body=texto_plano,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@blogautores.local'),
                to=[suscripcion.email],
                connection=conn,
            )
            msg.attach_alternative(cuerpo_html, 'text/html')
            msg.send(fail_silently=True)
            return True
    except Exception as exc:
        logger.error("Error enviando confirmación de suscripción a %s: %s", suscripcion.email, exc)
        return False


def enviar_correos_nuevo_post(post, request=None):
    """
    Envía un correo (HTML y texto plano, en español) a todos los suscriptores
    confirmados y activos del autor del post y de su categoría.
    - Evita enviar dos correos a la misma dirección por el mismo post.
    - Reutiliza una única conexión SMTP (`get_connection(fail_silently=True)`).
    - Incluye enlace único de baja `/suscripcion/baja/<token>/` en cada correo.
    """
    condicion = Q(autor=post.autor)
    if post.categoria_id:
        condicion = condicion | Q(categoria_id=post.categoria_id)

    suscripciones = (
        Suscripcion.objects.filter(confirmada=True, activa=True)
        .filter(condicion)
        .select_related('autor__usuario', 'categoria')
        .order_by('creado')
    )

    # Deduplicar por dirección de correo (evita enviar 2 correos a la misma persona por el mismo post)
    email_autor = (post.autor.usuario.email or '').strip().lower()
    destinatarios_unicos = []
    emails_vistos = set()

    for sub in suscripciones:
        correo_norm = sub.email.strip().lower()
        if not correo_norm or correo_norm == email_autor:
            continue
        if correo_norm not in emails_vistos:
            emails_vistos.add(correo_norm)
            destinatarios_unicos.append(sub)

    if not destinatarios_unicos:
        return 0

    url_post = construir_url_absoluta(post.get_absolute_url(), request=request)
    url_portada = obtener_imagen_portada_post(post, request=request)
    nombre_autor = post.autor.nombre_mostrar
    extracto = post.extracto
    marca = getattr(settings, 'MARCA', getattr(settings, 'SITE_NAME', 'Blog con Panel de Autor'))
    asunto = f'Nuevo artículo: {post.titulo} | {marca}'

    enviados = 0
    try:
        with get_connection(fail_silently=True) as conn:
            for sub in destinatarios_unicos:
                ruta_baja = reverse('blog:suscripcion_baja', kwargs={'token': sub.token})
                url_baja = construir_url_absoluta(ruta_baja, request=request)

                texto_plano = (
                    f"Nuevo artículo publicado por {nombre_autor}\n"
                    f"========================================\n\n"
                    f"Título: {post.titulo}\n\n"
                    f"Extracto:\n{extracto}\n\n"
                    f"Leer el artículo completo en:\n{url_post}\n\n"
                    f"---\n"
                    f"Recibes este correo por tu suscripción a {sub.destino_nombre}.\n"
                    f"Para darte de baja inmediatamente sin iniciar sesión: {url_baja}\n"
                )

                bloque_portada_html = (
                    f'<p><img src="{escape(url_portada)}" alt="{escape(post.titulo)}" '
                    f'style="max-width:100%;height:auto;border-radius:8px;"></p>'
                    if url_portada
                    else ''
                )

                cuerpo_html = f"""
                <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; color: #1e293b;">
                    <p style="font-size: 13px; color: #64748b; text-transform: uppercase;">
                        Nuevo artículo de {escape(nombre_autor)}
                    </p>
                    <h2 style="margin-top: 4px; color: #0f172a;">{escape(post.titulo)}</h2>
                    {bloque_portada_html}
                    <p style="line-height: 1.6; color: #334155;">{escape(extracto)}</p>
                    <p style="margin: 24px 0;">
                        <a href="{escape(url_post)}"
                           style="background-color: #0d6efd; color: #ffffff; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold;">
                           Leer artículo completo
                        </a>
                    </p>
                    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;">
                    <p style="font-size: 12px; color: #64748b;">
                        Recibes este mensaje porque confirmaste tu suscripción a <strong>{escape(sub.destino_nombre)}</strong>.<br>
                        <a href="{escape(url_baja)}" style="color: #dc2626;">Darme de baja de esta suscripción</a>.
                    </p>
                </div>
                """

                try:
                    msg = EmailMultiAlternatives(
                        subject=asunto,
                        body=texto_plano,
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@blogautores.local'),
                        to=[sub.email],
                        connection=conn,
                    )
                    msg.attach_alternative(cuerpo_html, 'text/html')
                    msg.send(fail_silently=True)
                    enviados += 1
                except Exception as inner_exc:
                    logger.error("Error enviando correo de nuevo post a %s: %s", sub.email, inner_exc)
    except Exception as exc:
        logger.error("Error abriendo conexión SMTP para nuevo post %s: %s", post.pk, exc)

    return enviados

