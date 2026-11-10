import os
import logging
from django.conf import settings
from PIL import Image

logger = logging.getLogger(__name__)


def generar_variantes_webp(post):
    """
    Genera variantes WebP optimizadas para portadas y miniaturas a partir de `post.imagen_portada`:
    - Miniatura de 192 px (ancho 192, altura proporcional o centrada)
    - Portada de 640 px (ancho 640, altura proporcional)
    - Portada de 1200 px (ancho 1200, altura proporcional)
    Guarda las variantes en media/portadas/variantes/.
    """
    if not post or not post.imagen_portada:
        return {}

    try:
        ruta_origen = post.imagen_portada.path
        if not os.path.exists(ruta_origen):
            return {}
    except (ValueError, AttributeError, NotImplementedError):
        return {}

    directorio_destino = os.path.join(settings.MEDIA_ROOT, 'portadas', 'variantes')
    os.makedirs(directorio_destino, exist_ok=True)

    base_name = f"post_{post.pk}_{post.slug}"
    variantes = {}

    try:
        with Image.open(ruta_origen) as img:
            # Convertir a RGB si está en RGBA o P para optimizar compresión WebP
            if img.mode in ('RGBA', 'LA'):
                fondo = Image.new('RGB', img.size, (255, 255, 255))
                fondo.paste(img, mask=img.split()[-1])
                img_rgb = fondo
            elif img.mode != 'RGB':
                img_rgb = img.convert('RGB')
            else:
                img_rgb = img.copy()

            ancho_orig, alto_orig = img_rgb.size
            if ancho_orig <= 0 or alto_orig <= 0:
                return {}

            aspect_ratio = alto_orig / ancho_orig

            # Tamaños objetivo requeridos
            tamanos = {
                192: (192, max(1, round(192 * aspect_ratio))),
                640: (640, max(1, round(640 * aspect_ratio))),
                1200: (1200, max(1, round(1200 * aspect_ratio))),
            }

            for ancho_target, (w, h) in tamanos.items():
                # Redimensionar con filtro de alta calidad LANCZOS
                img_resized = img_rgb.resize((w, h), Image.Resampling.LANCZOS)
                nombre_archivo = f"{base_name}_{ancho_target}.webp"
                ruta_salida = os.path.join(directorio_destino, nombre_archivo)
                img_resized.save(ruta_salida, 'WEBP', quality=85, method=6)

                rel_url = f"{settings.MEDIA_URL.rstrip('/')}/portadas/variantes/{nombre_archivo}"
                variantes[ancho_target] = rel_url

            logger.info("Variantes WebP generadas exitosamente para post %s: %s", post.pk, list(variantes.keys()))
            return variantes
    except Exception as e:
        logger.warning("No se pudieron generar variantes WebP para post %s: %s", post.pk, e)
        return {}


def obtener_rutas_variantes_webp(post):
    """
    Retorna diccionario con las URLs de las variantes WebP existentes (192, 640, 1200),
    o genera bajo demanda si existen la portada original y la carpeta media.
    """
    if not post or not getattr(post, 'imagen_portada', None):
        return {}

    base_name = f"post_{post.pk}_{post.slug}"
    directorio_destino = os.path.join(settings.MEDIA_ROOT, 'portadas', 'variantes')

    variantes = {}
    for ancho in (192, 640, 1200):
        nombre = f"{base_name}_{ancho}.webp"
        ruta = os.path.join(directorio_destino, nombre)
        if os.path.exists(ruta):
            variantes[ancho] = f"{settings.MEDIA_URL.rstrip('/')}/portadas/variantes/{nombre}"

    if len(variantes) == 3:
        return variantes

    # Si faltan pero hay imagen_portada física, generarlas
    return generar_variantes_webp(post)
