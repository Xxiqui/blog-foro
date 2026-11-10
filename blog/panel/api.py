from datetime import datetime, timedelta
from io import BytesIO
import json
import logging
import os
import uuid
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.utils.html import strip_tags
from django.views import View
from django.views.decorators.http import require_POST
from PIL import Image, ImageOps

from blog.models import Categoria, Etiqueta, Perfil, Post, RevisionPost, Seguimiento, Suscripcion
from blog.servicios import publicacion as servicio_publicacion
from blog.templatetags.blog_extras import generar_toc_html, limpiar_html_ckeditor
from blog.views import limitar_tasa

logger = logging.getLogger(__name__)

MAX_CONTENIDO_BYTES = 300 * 1024  # 300 KB
MAX_PORTADA_BYTES = 5 * 1024 * 1024  # 5 MB
ANCHO_MAX_PORTADA = 1200


def _obtener_post_propietario(request, pk=None, slug=None):
    """Obtiene el post verificando que pertenezca al usuario autenticado. Lanza 404 si es ajeno."""
    qs = Post.objects.select_related('autor__usuario', 'categoria')
    if pk:
        post = qs.filter(pk=pk).first()
    elif slug:
        post = qs.filter(slug=slug).first()
    else:
        return None

    if not post or post.autor.usuario_id != request.user.id:
        raise Http404('Post no encontrado.')
    return post


def _leer_payload_json(request):
    """Extrae datos de request.body en formato JSON o de request.POST si es multipart/form-data."""
    if request.content_type and 'application/json' in request.content_type:
        try:
            return json.loads(request.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return {}
    return request.POST.dict()


class ApiAutoguardarView(View):
    """
    Endpoint POST para autoguardado en el servidor:
    - Límite de tasa: 30 por minuto por usuario.
    - Contenido máximo: 300 KB.
    - Validación relajada para borradores (título vacío se guarda como 'Sin título').
    - Si el post aún no existe, lo crea como Borrador y devuelve edit_url para actualizar la barra del navegador.
    - Si el post ya está PUBLICADO o PROGRAMADO, el autoguardado NUNCA modifica la versión pública:
      guarda una RevisionPost con origen 'auto'.
    - Detección de concurrencia: si la versión del cliente es más antigua que la del servidor, responde 409.
    """

    @method_decorator(limitar_tasa('api_autoguardar', 30, 60))
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'ok': False, 'error': 'autenticacion_requerida'}, status=401)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        payload = _leer_payload_json(request)

        contenido = payload.get('contenido', '')
        if len(contenido.encode('utf-8')) > MAX_CONTENIDO_BYTES:
            return JsonResponse({
                'ok': False,
                'error': 'contenido_demasiado_grande',
                'mensaje': 'El contenido supera el límite máximo permitido de 300 KB.',
            }, status=400)

        post_id = payload.get('post_id') or payload.get('id')
        sobrescribir = payload.get('sobrescribir') in (True, 'true', '1', 1)
        version_cliente_raw = payload.get('version') or payload.get('ultima_actualizacion_conocida')

        perfil, _ = Perfil.objects.get_or_create(usuario=request.user)

        titulo = (payload.get('titulo') or '').strip() or 'Sin título'
        extracto = (payload.get('extracto') or '').strip()[:160]
        categoria_id = payload.get('categoria_id') or None
        etiquetas_raw = payload.get('etiquetas', [])

        post = None
        if post_id:
            try:
                post = _obtener_post_propietario(request, pk=int(post_id))
            except (ValueError, TypeError, Http404):
                return JsonResponse({'ok': False, 'error': 'post_no_encontrado'}, status=404)

            # Comprobación de concurrencia
            if version_cliente_raw and not sobrescribir and post.actualizado:
                try:
                    fecha_cliente = parse_datetime(str(version_cliente_raw)) or datetime.fromisoformat(str(version_cliente_raw).replace('Z', '+00:00'))
                    if timezone.is_naive(fecha_cliente):
                        fecha_cliente = timezone.make_aware(fecha_cliente, timezone.get_current_timezone())
                    # Tolerancia de 2 segundos para evitar falsos positivos por desfases mínimos
                    if fecha_cliente < (post.actualizado - timedelta(seconds=2)):
                        return JsonResponse({
                            'ok': False,
                            'error': 'conflicto_concurrencia',
                            'mensaje': 'El artículo fue modificado en otra pestaña o dispositivo.',
                            'version_servidor': post.actualizado.isoformat(),
                            'servidor_titulo': post.titulo,
                        }, status=409)
                except Exception:
                    pass

        # CASO 1: Post ya publicado o programado -> NUNCA modificar versión pública por autoguardado
        if post and post.estado in (Post.Estado.PUBLICADO, Post.Estado.PROGRAMADO):
            # Guardar en una RevisionPost con origen 'auto'
            rev = RevisionPost.objects.create(
                post=post,
                titulo=titulo,
                contenido=contenido,
                extracto=extracto,
                origen=RevisionPost.Origen.AUTO,
            )
            return JsonResponse({
                'ok': True,
                'id': post.pk,
                'post_id': post.pk,
                'slug': post.slug,
                'estado': post.estado,
                'version': post.actualizado.isoformat(),
                'guardado_en': post.actualizado.isoformat(),
                'guardado_en_revision': True,
                'revision_id': rev.pk,
                'mensaje': 'Cambios guardados en borrador interno sin alterar la versión pública.',
            })

        # CASO 2: Borrador nuevo o existente
        es_nuevo = post is None
        if es_nuevo:
            post = Post(
                autor=perfil,
                titulo=titulo,
                contenido=contenido,
                extracto=extracto,
                estado=Post.Estado.BORRADOR,
            )
            if categoria_id:
                post.categoria_id = categoria_id
            post.save()
        else:
            post.titulo = titulo
            post.contenido = contenido
            post.extracto = extracto
            if categoria_id is not None:
                post.categoria_id = categoria_id or None
            post.save()

        # Actualizar etiquetas si se enviaron
        if etiquetas_raw is not None:
            if isinstance(etiquetas_raw, str):
                nombres = [n.strip() for n in etiquetas_raw.split(',') if n.strip()]
            elif isinstance(etiquetas_raw, list):
                nombres = [str(n).strip() for n in etiquetas_raw if str(n).strip()]
            else:
                nombres = []

            if nombres:
                etiquetas_objs = []
                for nom in nombres:
                    if nom.isdigit():
                        e = Etiqueta.objects.filter(pk=int(nom)).first()
                    else:
                        e, _ = Etiqueta.objects.get_or_create(nombre=nom)
                    if e:
                        etiquetas_objs.append(e)
                post.etiquetas.set(etiquetas_objs)

        # Crear revisión si han pasado al menos 2 minutos desde la última o si es nuevo
        ultima_rev = RevisionPost.objects.filter(post=post).order_by('-creado').first()
        debe_crear_rev = (
            es_nuevo
            or not ultima_rev
            or (timezone.now() - ultima_rev.creado).total_seconds() >= 120
        )
        if debe_crear_rev:
            RevisionPost.objects.create(
                post=post,
                titulo=post.titulo,
                contenido=post.contenido,
                extracto=post.extracto,
                origen=RevisionPost.Origen.AUTO,
            )

        return JsonResponse({
            'ok': True,
            'id': post.pk,
            'post_id': post.pk,
            'slug': post.slug,
            'estado': post.estado,
            'version': post.actualizado.isoformat(),
            'guardado_en': post.actualizado.isoformat(),
            'edit_url': reverse('blog:panel_post_update', kwargs={'slug': post.slug}),
            'mensaje': 'Guardado correctamente.',
        })


class ApiVistaPreviaView(View):
    """
    Endpoint POST para renderizar una vista previa fiel sin escribir en la base de datos.
    - Límite de tasa: 30/min.
    - Máximo 300 KB.
    - Utiliza el parcial `_articulo.html` con saneado bleach idéntico al sitio público.
    """

    @method_decorator(limitar_tasa('api_vista_previa', 30, 60))
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'ok': False, 'error': 'autenticacion_requerida'}, status=401)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        payload = _leer_payload_json(request)

        contenido = payload.get('contenido', '')
        if len(contenido.encode('utf-8')) > MAX_CONTENIDO_BYTES:
            return JsonResponse({'ok': False, 'error': 'contenido_demasiado_grande'}, status=400)

        titulo = (payload.get('titulo') or '').strip() or 'Título de tu artículo'
        categoria_id = payload.get('categoria_id')
        categoria = Categoria.objects.filter(pk=categoria_id).first() if categoria_id else None
        extracto = (payload.get('extracto') or '').strip()

        perfil, _ = Perfil.objects.get_or_create(usuario=request.user)

        # Construir post efímero en memoria sin tocar base de datos
        post_efimero = Post(
            titulo=titulo,
            contenido=contenido,
            extracto=extracto,
            categoria=categoria,
            autor=perfil,
            estado=Post.Estado.BORRADOR,
            creado=timezone.now(),
            publicado_en=timezone.now(),
        )

        # Si pasaron post_id existente y tiene portada asignada, conservarla
        post_id = payload.get('post_id')
        if post_id:
            try:
                real = Post.objects.filter(pk=int(post_id)).first()
                if real and real.imagen_portada:
                    post_efimero.imagen_portada = real.imagen_portada
            except (ValueError, TypeError):
                pass

        toc_items = generar_toc_html(contenido)

        html_articulo = render_to_string(
            'blog/includes/_articulo.html',
            {
                'post': post_efimero,
                'toc_items': toc_items,
                'es_vista_previa': True,
                'request': request,
            },
            request=request,
        )

        return JsonResponse({
            'ok': True,
            'html': html_articulo,
            'titulo': titulo,
        })


class ApiHistorialView(View):
    """Devuelve la lista de revisiones del post ordenadas de más reciente a más antigua."""

    def get(self, request, pk, *args, **kwargs):
        post = _obtener_post_propietario(request, pk=pk)
        revisiones = (
            RevisionPost.objects.filter(post=post)
            .order_by('-creado')[:20]
        )

        data = []
        for r in revisiones:
            texto = strip_tags(r.contenido or '').strip()
            palabras = len(texto.split()) if texto else 0
            data.append({
                'id': r.pk,
                'creado': r.creado.isoformat(),
                'creado_relativo': naturaltime(r.creado),
                'origen': r.get_origen_display(),
                'origen_clave': r.origen,
                'palabras': palabras,
                'titulo': r.titulo,
                'extracto': r.extracto,
            })

        return JsonResponse({'ok': True, 'revisiones': data})


class ApiRevisionDetalleView(View):
    """Devuelve los datos y el contenido saneado de una revisión para vista previa en el modal."""

    def get(self, request, pk, *args, **kwargs):
        rev = get_object_or_404(RevisionPost.objects.select_related('post__autor__usuario'), pk=pk)
        if rev.post.autor.usuario_id != request.user.id:
            raise Http404('Revisión no encontrada.')

        return JsonResponse({
            'ok': True,
            'id': rev.pk,
            'titulo': rev.titulo,
            'extracto': rev.extracto,
            'contenido_html': limpiar_html_ckeditor(rev.contenido),
            'creado_relativo': naturaltime(rev.creado),
            'origen': rev.get_origen_display(),
        })


class ApiRestaurarView(View):
    """Restaura el contenido de una revisión en el post (creando primero una revisión de respaldo)."""

    def post(self, request, pk, *args, **kwargs):
        post = _obtener_post_propietario(request, pk=pk)
        payload = _leer_payload_json(request)
        revision_id = payload.get('revision_id')

        rev = get_object_or_404(RevisionPost, pk=revision_id, post=post)

        # Guardar respaldo del estado actual antes de restaurar
        RevisionPost.objects.create(
            post=post,
            titulo=post.titulo,
            contenido=post.contenido,
            extracto=post.extracto,
            origen=RevisionPost.Origen.MANUAL,
        )

        # Aplicar datos de la revisión
        post.titulo = rev.titulo
        post.contenido = rev.contenido
        post.extracto = rev.extracto
        post.save()

        # Registrar la restauración
        RevisionPost.objects.create(
            post=post,
            titulo=post.titulo,
            contenido=post.contenido,
            extracto=post.extracto,
            origen=RevisionPost.Origen.RESTAURACION,
        )

        return JsonResponse({
            'ok': True,
            'titulo': post.titulo,
            'contenido': post.contenido,
            'extracto': post.extracto,
            'version': post.actualizado.isoformat(),
            'mensaje': 'Versión restaurada correctamente.',
        })


class ApiPortadaSubirView(View):
    """
    Subida y validación de imagen de portada por endpoint AJAX:
    - Formatos: JPG, PNG, WebP.
    - Tamaño máximo: 5 MB.
    - Redimensiona con Pillow a un ancho máximo de 1200 px manteniendo proporción.
    - Renombra con hash aleatorio por seguridad.
    """

    def post(self, request, pk=None, *args, **kwargs):
        post_id = pk or request.POST.get('post_id')
        post = _obtener_post_propietario(request, pk=post_id) if post_id else None
        archivo = request.FILES.get('imagen_portada') or request.FILES.get('portada')
        if not archivo:
            return JsonResponse({'ok': False, 'error': 'sin_archivo', 'mensaje': 'No se adjuntó ningún archivo.'}, status=400)

        if archivo.size > MAX_PORTADA_BYTES:
            return JsonResponse({'ok': False, 'error': 'archivo_demasiado_grande', 'mensaje': 'La imagen supera los 5 MB permitidos.'}, status=400)

        nombre_original = (archivo.name or '').lower()
        if not nombre_original.endswith(('.jpg', '.jpeg', '.png', '.webp')):
            return JsonResponse({'ok': False, 'error': 'formato_no_permitido', 'mensaje': 'Solo se admiten imágenes JPG, PNG o WebP.'}, status=400)

        try:
            archivo.seek(0)
            img = Image.open(archivo)
            img.verify()
            formato_detectado = img.format.lower()
            if formato_detectado not in ('jpeg', 'png', 'webp'):
                return JsonResponse({'ok': False, 'error': 'imagen_invalida', 'mensaje': 'El archivo no es una imagen válida.'}, status=400)

            # Reabrir tras verify() y auto-rotar según orientación EXIF
            archivo.seek(0)
            img = Image.open(archivo)
            img = ImageOps.exif_transpose(img)

            # Redimensionar si supera el ancho máximo de 1200 px
            if img.width > ANCHO_MAX_PORTADA:
                nuevo_alto = round((ANCHO_MAX_PORTADA / img.width) * img.height)
                img = img.resize((ANCHO_MAX_PORTADA, nuevo_alto), Image.Resampling.LANCZOS)

            buffer = BytesIO()
            salida_formato = 'WEBP' if formato_detectado == 'webp' else ('PNG' if formato_detectado == 'png' else 'JPEG')
            img.save(buffer, format=salida_formato, quality=88, optimize=True)
            buffer.seek(0)

            nombre_seguro = f"portada_{uuid.uuid4().hex[:12]}.{salida_formato.lower()}"
            if post:
                post.imagen_portada.save(nombre_seguro, ContentFile(buffer.read()), save=True)
                url = post.imagen_portada.url
            else:
                from django.core.files.storage import default_storage
                ruta = default_storage.save(f"portadas/{nombre_seguro}", ContentFile(buffer.read()))
                url = default_storage.url(ruta)

            return JsonResponse({
                'ok': True,
                'url': url,
                'mensaje': 'Imagen de portada actualizada.',
            })
        except Exception as e:
            logger.error("Error al procesar portada en post %s: %s", pk, e)
            return JsonResponse({'ok': False, 'error': 'procesamiento_fallido', 'mensaje': 'No se pudo procesar la imagen.'}, status=400)


class ApiPortadaQuitarView(View):
    """Elimina la imagen de portada del post."""

    def post(self, request, pk=None, *args, **kwargs):
        payload = _leer_payload_json(request)
        post_id = pk or payload.get('post_id')
        post = _obtener_post_propietario(request, pk=post_id) if post_id else None
        if post and post.imagen_portada:
            post.imagen_portada.delete(save=False)
            post.imagen_portada = None
            post.save(update_fields=['imagen_portada', 'actualizado'])

        return JsonResponse({'ok': True, 'mensaje': 'Portada eliminada.'})


class ApiPublicarView(View):
    """Publica el post llamando al servicio de publicación consolidado."""

    def post(self, request, pk=None, *args, **kwargs):
        payload = _leer_payload_json(request)
        post_id = pk or payload.get('post_id')
        post = _obtener_post_propietario(request, pk=post_id)

        # Si el post publicado/programado tenía una revisión de autoguardado pendiente, aplicarla primero
        if post.estado in (Post.Estado.PUBLICADO, Post.Estado.PROGRAMADO):
            ultima_auto = (
                RevisionPost.objects.filter(post=post, origen=RevisionPost.Origen.AUTO)
                .order_by('-creado')
                .first()
            )
            if ultima_auto:
                post.titulo = ultima_auto.titulo
                post.contenido = ultima_auto.contenido
                post.extracto = ultima_auto.extracto

        try:
            primera_vez = not post.publicado_en or not post.notificado
            servicio_publicacion.publicar(post, usuario=request.user)
            return JsonResponse({
                'ok': True,
                'url': post.get_absolute_url(),
                'estado': post.estado,
                'slug': post.slug,
                'primera_vez': primera_vez,
                'mensaje': '¡Artículo publicado con éxito!',
            })
        except ValidationError as e:
            return JsonResponse({
                'ok': False,
                'error': 'validacion',
                'errores': e.message_dict if hasattr(e, 'message_dict') else {'general': str(e)},
            }, status=400)


class ApiProgramarView(View):
    """Programa el post para una fecha y hora futura."""

    def post(self, request, pk=None, *args, **kwargs):
        payload = _leer_payload_json(request)
        post_id = pk or payload.get('post_id')
        post = _obtener_post_propietario(request, pk=post_id)

        fecha_raw = payload.get('fecha_hora') or payload.get('programado_para')
        if not fecha_raw:
            return JsonResponse({'ok': False, 'error': 'fecha_requerida', 'mensaje': 'Debes especificar una fecha y hora.'}, status=400)

        try:
            fecha_dt = parse_datetime(str(fecha_raw))
            if not fecha_dt:
                fecha_dt = datetime.fromisoformat(str(fecha_raw).replace('Z', '+00:00'))
        except Exception:
            return JsonResponse({'ok': False, 'error': 'fecha_invalida', 'mensaje': 'El formato de fecha no es válido.'}, status=400)

        try:
            servicio_publicacion.programar(post, fecha_dt, usuario=request.user)
            return JsonResponse({
                'ok': True,
                'estado': post.estado,
                'programado_para': post.programado_para.isoformat(),
                'programado_para_humano': post.programado_para.strftime('%d %b %Y, %H:%M'),
                'mensaje': f'Artículo programado para el {post.programado_para.strftime("%d %b %Y a las %H:%M")}.',
            })
        except ValidationError as e:
            return JsonResponse({
                'ok': False,
                'error': 'validacion',
                'errores': e.message_dict if hasattr(e, 'message_dict') else {'general': str(e)},
            }, status=400)


class ApiDespublicarView(View):
    """Devuelve el post a estado Borrador."""

    def post(self, request, pk=None, *args, **kwargs):
        payload = _leer_payload_json(request)
        post_id = pk or payload.get('post_id')
        post = _obtener_post_propietario(request, pk=post_id)
        servicio_publicacion.despublicar(post, usuario=request.user)
        return JsonResponse({
            'ok': True,
            'estado': post.estado,
            'mensaje': 'El artículo se ha despublicado y vuelto a Borrador.',
        })


class ApiDuplicarView(View):
    """Crea una copia del post en estado borrador."""

    def post(self, request, pk=None, *args, **kwargs):
        payload = _leer_payload_json(request)
        post_id = pk or payload.get('post_id')
        post = _obtener_post_propietario(request, pk=post_id)
        nuevo = servicio_publicacion.duplicar(post, usuario=request.user)
        return JsonResponse({
            'ok': True,
            'id': nuevo.pk,
            'slug': nuevo.slug,
            'edit_url': reverse('blog:panel_post_update', kwargs={'slug': nuevo.slug}),
            'url_editor': reverse('blog:panel_post_update', kwargs={'slug': nuevo.slug}),
            'mensaje': f'Se ha creado la copia «{nuevo.titulo}».',
        })


class ApiDestinatariosCountView(View):
    """Devuelve el número de seguidores y suscriptores que recibirán aviso en la primera publicación."""

    def get(self, request, pk=None, *args, **kwargs):
        categoria_id = request.GET.get('categoria_id')
        post_id = pk or request.GET.get('post_id')
        post = None
        if post_id:
            try:
                post = _obtener_post_propietario(request, pk=post_id)
            except Exception:
                pass

        perfil, _ = Perfil.objects.get_or_create(usuario=request.user)
        seguidores_count = Seguimiento.objects.filter(autor=perfil).count()

        # Suscriptores únicos confirmados para autor o categoría
        emails = set()
        subs_autor = Suscripcion.objects.filter(autor=perfil, confirmada=True).values_list('email', flat=True)
        emails.update(subs_autor)
        target_cat = categoria_id or (post.categoria_id if post else None)
        if target_cat:
            subs_cat = Suscripcion.objects.filter(categoria_id=target_cat, confirmada=True).values_list('email', flat=True)
            emails.update(subs_cat)

        return JsonResponse({
            'ok': True,
            'seguidores': seguidores_count,
            'suscriptores': len(emails),
            'primera_vez': not post or not post.publicado_en or not post.notificado,
        })
