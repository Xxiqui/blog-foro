import hashlib
from html import unescape
import re
import bleach
from django import template
from django.urls import reverse
from django.utils.html import escape, strip_tags
from django.utils.safestring import mark_safe
from django.utils.text import slugify

from blog.notificaciones import MENCION_REGEX, extraer_usuarios_mencionados
from blog.populares import calcular_insignias_perfil
from blog.search import generar_fragmento_sqlite

register = template.Library()

# Expresión regular para validar clases de lenguaje en bloques <code>
LANGUAGE_CLASS_RE = re.compile(r'^language-[a-z0-9+#-]+$', re.IGNORECASE)

# Lista blanca de etiquetas HTML compatibles con CKEditor 5
ALLOWED_TAGS = [
    'p', 'br', 'hr',
    'h2', 'h3', 'h4',
    'strong', 'b', 'em', 'i', 'u', 's',
    'ul', 'ol', 'li',
    'a',
    'blockquote',
    'pre', 'code',
    'img', 'figure', 'figcaption',
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
    'span', 'div',
]


def _filtrar_atributo_code(tag, name, value):
    """Permite el atributo `class` en `<code>` solo si coincide con `language-[a-z0-9+#-]+`."""
    if name == 'class' and value:
        partes = str(value).strip().split()
        return bool(partes) and all(LANGUAGE_CLASS_RE.match(p) for p in partes)
    return False


# Atributos permitidos por etiqueta
ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'target', 'rel'],
    'img': ['src', 'alt', 'title', 'width', 'height', 'class', 'loading'],
    'figure': ['class'],
    'table': ['class'],
    'th': ['colspan', 'rowspan', 'scope'],
    'td': ['colspan', 'rowspan'],
    'code': _filtrar_atributo_code,
    'pre': ['class'],
    'h2': ['id'],
    'h3': ['id'],
    'h4': ['id'],
    'p': ['class'],
    'span': ['class'],
    'div': ['class'],
}

ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']

SCRIPT_STYLE_RE = re.compile(
    r'<(script|style|iframe|object|embed)\b[^>]*>.*?</\1>',
    re.IGNORECASE | re.DOTALL,
)
HEADING_BLOCK_RE = re.compile(
    r'<h[1-6]\b[^>]*>.*?</h[1-6]>',
    re.IGNORECASE | re.DOTALL,
)
PARAGRAPH_BLOCK_RE = re.compile(
    r'<p\b[^>]*>(.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)
TOC_HEADING_RE = re.compile(
    r'<(h[23])\b([^>]*)>(.*?)</\1>',
    re.IGNORECASE | re.DOTALL,
)

# Paleta de colores estables para avatares con iniciales (buen contraste con texto blanco)
AVATAR_PALETTE = (
    '#2563eb',  # Azul
    '#7c3aed',  # Violeta
    '#059669',  # Esmeralda
    '#d97706',  # Ámbar oscuro
    '#dc2626',  # Rojo
    '#0891b2',  # Cian oscuro
    '#4f46e5',  # Índigo
    '#be185d',  # Rosa oscuro
)

# Paleta determinista de 6 degradados por categoría y sus íconos
CATEGORIA_ICONOS = {
    'desarrollo-web': 'bi-code-slash',
    'bases-de-datos': 'bi-database-fill-gear',
    'devops-y-seguridad': 'bi-shield-lock-fill',
    'arquitectura': 'bi-diagram-3-fill',
    'python': 'bi-filetype-py',
    'tecnologia': 'bi-cpu-fill',
}


def extracto_plano(html, max_chars=160):
    """
    Genera un extracto en texto plano a partir de HTML:
    - Ignora todos los encabezados (h1-h6) y bloques script/style.
    - Toma el texto del primer párrafo `<p>` con contenido (o los primeros párrafos
      hasta alcanzar `max_chars`). Si no hay etiquetas `<p>`, usa el texto restante.
    - Normaliza espacios en blanco.
    - Si supera `max_chars`, corta en el límite de una palabra y agrega una sola "…"
      (nunca "...." ni doble puntuación como ".…").
    """
    if not html:
        return ''

    texto_fuente = str(html)
    if not texto_fuente.strip():
        return ''

    # 1. Eliminar bloques peligrosos y encabezados h1-h6
    sin_scripts = SCRIPT_STYLE_RE.sub(' ', texto_fuente)
    sin_encabezados = HEADING_BLOCK_RE.sub(' ', sin_scripts)

    # 2. Extraer párrafos <p> con contenido
    parrafos_html = PARAGRAPH_BLOCK_RE.findall(sin_encabezados)
    fragmentos = []
    longitud_acumulada = 0

    for p_html in parrafos_html:
        plano = unescape(strip_tags(p_html))
        plano = re.sub(r'\s+', ' ', plano).strip()
        if plano:
            fragmentos.append(plano)
            longitud_acumulada += len(plano) + 1
            if longitud_acumulada >= max_chars + 40:
                break

    if fragmentos:
        texto = ' '.join(fragmentos)
    else:
        # Fallback si el contenido no estaba envuelto en <p>
        texto = unescape(strip_tags(sin_encabezados))
        texto = re.sub(r'\s+', ' ', texto).strip()

    if not texto:
        return ''

    # Normalizar puntos suspensivos múltiples preexistentes al final
    texto = re.sub(r'\.{3,}$', '…', texto)

    if len(texto) <= max_chars:
        return texto

    # 3. Cortar en el límite de una palabra dejando espacio para "…"
    limite = max(1, max_chars - 1)
    recorte = texto[:limite]

    # Si cortamos en medio de una palabra, retroceder al último espacio
    if len(texto) > limite and not texto[limite].isspace():
        ultimo_espacio = recorte.rfind(' ')
        if ultimo_espacio > 0:
            recorte = recorte[:ultimo_espacio]

    # Limpiar espacios y signos de puntuación finales para evitar ".…" o ",…" o "...."
    recorte = recorte.rstrip(' \t\r\n.,;:!¡?¿…-–—')
    if not recorte:
        recorte = texto[:limite].rstrip(' \t\r\n.,;:!¡?¿…-–—')

    return f'{recorte}…'


def sanear_y_generar_toc(html_texto):
    """
    Sanea el HTML con bleach (conservando `<code class="language-xxx">` válidos y
    eliminando `<script>`, `onerror`, etc.), asigna `id` únicos sin colisiones
    a los encabezados `h2` y `h3`, y devuelve `(html_saneado_safe, toc_items)`.
    """
    if not html_texto:
        return mark_safe(''), []

    sin_bloques_peligrosos = SCRIPT_STYLE_RE.sub('', str(html_texto))
    limpio = bleach.clean(
        sin_bloques_peligrosos,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )

    toc = []
    ids_usados = set()

    def _asignar_id_encabezado(match):
        tag = match.group(1).lower()
        contenido_interno = match.group(3)
        texto_plano = re.sub(r'\s+', ' ', unescape(strip_tags(contenido_interno))).strip()
        base_slug = slugify(texto_plano) or 'seccion'

        slug_unico = base_slug
        contador = 2
        while slug_unico in ids_usados:
            slug_unico = f'{base_slug}-{contador}'
            contador += 1
        ids_usados.add(slug_unico)

        if texto_plano:
            toc.append({
                'id': slug_unico,
                'texto': texto_plano,
                'nivel': 2 if tag == 'h2' else 3,
            })

        return f'<{tag} id="{escape(slug_unico)}">{contenido_interno}</{tag}>'

    html_con_ids = TOC_HEADING_RE.sub(_asignar_id_encabezado, limpio)
    return mark_safe(html_con_ids), toc


def limpiar_html_ckeditor(html_texto):
    """
    Sanea el contenido HTML generado por CKEditor 5 utilizando bleach
    y asigna IDs únicos a los encabezados h2 y h3.
    """
    html_saneado, _ = sanear_y_generar_toc(html_texto)
    return html_saneado


def generar_toc_html(html_texto):
    """Devuelve la lista de encabezados `[{'id', 'texto', 'nivel'}]` cuando hay 3 o más h2/h3."""
    _, toc = sanear_y_generar_toc(html_texto)
    return toc if len(toc) >= 3 else []


@register.filter(name='sanear_html')
def sanear_html(valor):
    """Filtro de plantilla reutilizable para sanear HTML con bleach y añadir IDs a h2/h3."""
    return limpiar_html_ckeditor(valor)


@register.filter(name='extracto_plano')
def filtro_extracto_plano(valor, max_chars=160):
    """Filtro de plantilla para obtener un extracto limpio ignorando h1-h6."""
    try:
        limite = int(max_chars)
    except (TypeError, ValueError):
        limite = 160
    return extracto_plano(valor, max_chars=limite)


@register.filter(name='fragmento_resaltado')
def fragmento_resaltado(post, consulta=''):
    """
    Devuelve el fragmento resaltado de PostgreSQL (`SearchHeadline`) si existe,
    saneado únicamente para permitir `<mark>`, o genera un fragmento resaltado en SQLite.
    """
    fragmento_pg = getattr(post, 'fragmento', None)
    if fragmento_pg:
        limpio = bleach.clean(
            str(fragmento_pg),
            tags=['mark'],
            attributes={},
            strip=True,
        )
        return mark_safe(limpio)
    if consulta:
        return generar_fragmento_sqlite(post.contenido, consulta)
    return extracto_plano(post.contenido, max_chars=160)


@register.filter(name='renderizar_menciones')
def renderizar_menciones(texto):
    """
    Escapa primero todo el HTML del comentario para prevenir XSS y luego
    convierte hasta 5 menciones de usuarios reales (@username) en enlaces
    a su perfil público.
    """
    if not texto:
        return ''

    texto_escapado = escape(str(texto))
    usuarios_validos = extraer_usuarios_mencionados(texto, max_menciones=5)
    mapa_validos = {u.username.lower(): u.username for u in usuarios_validos}

    if mapa_validos:
        def reemplazar(match):
            username_capturado = match.group(1)
            username_real = mapa_validos.get(username_capturado.lower())
            if not username_real:
                return match.group(0)
            url_perfil = reverse('blog:autor_detail', kwargs={'username': username_real})
            return f'<a href="{url_perfil}" class="mention-link">@{escape(username_real)}</a>'

        texto_escapado = MENCION_REGEX.sub(reemplazar, texto_escapado)

    con_saltos = texto_escapado.replace('\r\n', '<br>').replace('\n', '<br>')
    return mark_safe(con_saltos)


JERARQUIA_INSIGNIAS = {
    'Destacado': 3,
    'Activo': 2,
    'Nuevo': 1,
}


@register.simple_tag(name='insignia')
def insignia(perfil, compacto=True, todas=False):
    """
    Renderiza las insignias calculadas para el perfil de un autor.
    - En contextos compactos (tarjetas, listas, barra lateral, por defecto `compacto=True`):
      se muestra una sola insignia, la de mayor rango (Destacado > Activo > Nuevo).
    - En la página pública del autor (o pasando `todas=True` / `compacto=False`):
      se muestran todas las insignias obtenidas.
    """
    insignias = calcular_insignias_perfil(perfil)
    if not insignias:
        return ''

    if compacto and not todas and len(insignias) > 1:
        insignias = [max(insignias, key=lambda x: JERARQUIA_INSIGNIAS.get(x.get('nombre'), 0))]

    badges_html = []
    for item in insignias:
        nombre = escape(item['nombre'])
        clase = escape(item['clase'])
        icono = (
            'bi-award-fill'
            if nombre == 'Destacado'
            else ('bi-lightning-charge-fill' if nombre == 'Activo' else 'bi-stars')
        )
        badges_html.append(
            f'<span class="badge rounded-pill border badge-insignia flex-shrink-0 {clase} ms-1" '
            f'title="Insignia: {nombre}">'
            f'<i class="bi {icono} me-1" aria-hidden="true"></i>{nombre}</span>'
        )
    return mark_safe(''.join(badges_html))


def color_estable_usuario(username):
    """Deriva un color hexadecimal estable a partir del nombre de usuario."""
    semilla = (username or 'autor').encode('utf-8')
    digest = hashlib.md5(semilla).hexdigest()
    indice = int(digest[:8], 16) % len(AVATAR_PALETTE)
    return AVATAR_PALETTE[indice]


@register.simple_tag(name='avatar')
def avatar(perfil, tamano=36, clase_extra=''):
    """
    Template tag `{% avatar perfil tamaño %}`:
    Componente de avatar único (.avatar): círculo (border-radius: 50%, aspect-ratio: 1,
    display: grid; place-items: center, object-fit: cover), tamaños xs 24, sm 32, md 40,
    lg 64 y xl 96, inicial centrada.
    """
    try:
        px = int(tamano)
    except (TypeError, ValueError):
        px = 36

    if not perfil:
        return ''

    usuario = getattr(perfil, 'usuario', None)
    username = getattr(usuario, 'username', 'autor')
    nombre_mostrar = getattr(perfil, 'nombre_mostrar', None) or (
        usuario.get_full_name() if usuario else username
    ) or username
    inicial = (nombre_mostrar.strip()[:1] or username[:1] or 'A').upper()

    if px <= 26:
        size_mod = 'avatar--xs'
    elif px <= 35:
        size_mod = 'avatar--sm'
    elif px <= 50:
        size_mod = 'avatar--md'
    elif px <= 79:
        size_mod = 'avatar--lg'
    else:
        size_mod = 'avatar--xl'

    clases = f'avatar {size_mod} flex-shrink-0 {clase_extra}'.strip()

    if getattr(perfil, 'avatar', None):
        try:
            url_avatar = perfil.avatar.url
            return mark_safe(
                f'<img src="{escape(url_avatar)}" alt="Avatar de {escape(nombre_mostrar)}" '
                f'width="{px}" height="{px}" loading="lazy" decoding="async" '
                f'class="{escape(clases)}" '
                f'style="width:{px}px;height:{px}px;aspect-ratio:1/1;object-fit:cover;border-radius:50% !important;">'
            )
        except ValueError:
            pass

    color_bg = color_estable_usuario(username)
    font_size = max(11, round(px * 0.44))
    return mark_safe(
        f'<span class="{escape(clases)}" '
        f'style="width:{px}px;height:{px}px;background-color:{color_bg};font-size:{font_size}px;border-radius:50% !important;" '
        f'aria-hidden="true" title="{escape(nombre_mostrar)}">{escape(inicial)}</span>'
    )


# Paleta base HSL por categoría: ((h1, s1, l1), (h2, s2, l2))
PALETA_HSL_CATEGORIAS = (
    ((220, 78, 46), (192, 85, 42)),  # 0: Azul -> Cian
    ((158, 76, 35), (174, 80, 38)),  # 1: Esmeralda -> Turquesa
    ((264, 72, 48), (318, 74, 48)),  # 2: Violeta -> Magenta
    ((28, 84, 44), (8, 78, 48)),     # 3: Ámbar -> Coral
    ((222, 60, 26), (236, 72, 46)),  # 4: Pizarra -> Índigo
    ((336, 76, 44), (18, 84, 48)),   # 5: Frambuesa -> Naranja
)


def indice_degradado_categoria(slug):
    """Elige de forma determinista un índice de 0 a 5 a partir del slug de la categoría."""
    if not slug:
        return 0
    digest = hashlib.md5(str(slug).encode('utf-8')).hexdigest()
    return int(digest[:6], 16) % 6


def degradado_portada_post(post):
    """
    Calcula un degradado CSS determinista para un post desplazando el tono (hue),
    la luminosidad y el ángulo a partir de un hash del slug del post dentro de la
    paleta cromática de su categoría.
    """
    categoria = getattr(post, 'categoria', None)
    cat_slug = getattr(categoria, 'slug', '') or 'general'
    grad_idx = indice_degradado_categoria(cat_slug)
    (h1_base, s1, l1_base), (h2_base, s2, l2_base) = PALETA_HSL_CATEGORIAS[grad_idx]

    semilla_post = getattr(post, 'slug', None) or getattr(post, 'titulo', None) or 'post'
    digest = hashlib.sha256(f'{cat_slug}:{semilla_post}'.encode('utf-8')).hexdigest()

    # Desplazamiento determinista del tono (-22° a +22°) y ángulo (118° a 162°)
    shift_h1 = (int(digest[0:4], 16) % 45) - 22
    shift_h2 = (int(digest[4:8], 16) % 45) - 22
    angulo = 118 + (int(digest[8:12], 16) % 45)
    shift_l = (int(digest[12:14], 16) % 9) - 4

    h1 = (h1_base + shift_h1) % 360
    h2 = (h2_base + shift_h2) % 360
    l1 = max(22, min(58, l1_base + shift_l))
    l2 = max(24, min(60, l2_base - shift_l))
    h_mid = ((h1 + h2) // 2) % 360
    s_mid = (s1 + s2) // 2
    l_mid = (l1 + l2) // 2

    return (
        f'linear-gradient({angulo}deg, '
        f'hsl({h1}, {s1}%, {l1}%) 0%, '
        f'hsl({h_mid}, {s_mid}%, {l_mid}%) 54%, '
        f'hsl({h2}, {s2}%, {l2}%) 100%)'
    )


@register.simple_tag(name='portada_post')
def portada_post(post, altura_clase=''):
    """
    Renderiza la portada 16:9 del post:
    - Si tiene `imagen_portada` o `portada_url`, tiene prioridad sobre el degradado y muestra `<img>`.
    - Si no tiene imagen, genera un degradado CSS determinista variado por post dentro de la paleta
      de su categoría y muestra únicamente el ícono de la categoría (sin burbuja de inicial).
    """
    titulo = escape(getattr(post, 'titulo', 'Artículo'))
    url_imagen = None
    imagen_portada = getattr(post, 'imagen_portada', None)
    if imagen_portada:
        if hasattr(imagen_portada, 'url'):
            try:
                url_imagen = imagen_portada.url
                if url_imagen and url_imagen.startswith('/media/media/'):
                    url_imagen = url_imagen[len('/media'):]
            except ValueError:
                url_imagen = None
        elif isinstance(imagen_portada, str) and imagen_portada.strip():
            url_imagen = imagen_portada.strip()
            if url_imagen.startswith('/media/media/'):
                url_imagen = url_imagen[len('/media'):]
    if not url_imagen:
        url_imagen = getattr(post, 'portada_url', None)

    if url_imagen:
        srcset = getattr(post, 'portada_srcset', '')
        srcset_attr = f'srcset="{escape(srcset)}" sizes="(max-width: 768px) 100vw, 640px"' if srcset else ''
        return mark_safe(
            f'<div class="post-cover-wrapper {escape(altura_clase)}">'
            f'<img src="{escape(url_imagen)}" alt="{titulo}" {srcset_attr} '
            f'class="post-cover-img" loading="lazy" decoding="async" width="640" height="360" '
            f'style="aspect-ratio:16/9;object-fit:cover;">'
            f'</div>'
        )

    categoria = getattr(post, 'categoria', None)
    cat_slug = getattr(categoria, 'slug', '') or 'general'
    cat_nombre = getattr(categoria, 'nombre', '') or 'General'
    grad_idx = indice_degradado_categoria(cat_slug)
    icono = CATEGORIA_ICONOS.get(cat_slug, 'bi-journal-richtext')
    grad_css = degradado_portada_post(post)

    return mark_safe(
        f'<div class="post-cover-wrapper post-cover-gradient cat-grad-{grad_idx} {escape(altura_clase)}" '
        f'style="background: {grad_css};" '
        f'role="img" aria-label="Portada ilustrativa de {escape(cat_nombre)}: {titulo}">'
        f'<div class="post-cover-placeholder-content">'
        f'<i class="bi {icono} post-cover-icon" aria-hidden="true"></i>'
        f'</div>'
        f'</div>'
    )


@register.simple_tag(takes_context=True, name='query_transform')
def query_transform(context, **kwargs):
    """
    Conserva los parámetros actuales de la query string (`?q=`, `?orden=`, etc.)
    y actualiza o elimina las claves indicadas al paginar o filtrar.
    """
    request = context.get('request')
    if not request:
        return ''
    updated = request.GET.copy()
    for k, v in kwargs.items():
        if v is None or v == '':
            updated.pop(k, None)
        else:
            updated[k] = str(v)
    encoded = updated.urlencode()
    return f'?{encoded}' if encoded else '?'


def degradado_categoria(categoria):
    """Devuelve el degradado CSS determinista para una categoría."""
    cat_slug = getattr(categoria, 'slug', '') or 'general'
    grad_idx = indice_degradado_categoria(cat_slug)
    (h1, s1, l1), (h2, s2, l2) = PALETA_HSL_CATEGORIAS[grad_idx]
    h_mid = ((h1 + h2) // 2) % 360
    s_mid = (s1 + s2) // 2
    l_mid = (l1 + l2) // 2
    return (
        f'linear-gradient(135deg, '
        f'hsl({h1}, {s1}%, {l1}%) 0%, '
        f'hsl({h_mid}, {s_mid}%, {l_mid}%) 54%, '
        f'hsl({h2}, {s2}%, {l2}%) 100%)'
    )


@register.simple_tag(name='avatar_categoria')
def avatar_categoria(categoria, tamano=40, clase_extra=''):
    """
    Renderiza el avatar circular de una categoría/comunidad:
    - Si tiene `avatar` subido, muestra `<img>`.
    - Si no tiene `avatar`, muestra un círculo con el degradado determinista y el ícono de la categoría.
    """
    try:
        px = int(tamano)
    except (TypeError, ValueError):
        px = 40

    if not categoria:
        return ''

    nombre = getattr(categoria, 'nombre', 'Comunidad')
    slug = getattr(categoria, 'slug', '') or 'general'
    campo_avatar = getattr(categoria, 'avatar', None)
    if campo_avatar:
        try:
            url_avatar = campo_avatar.url
            return mark_safe(
                f'<img src="{escape(url_avatar)}" alt="Avatar de {escape(nombre)}" '
                f'width="{px}" height="{px}" loading="lazy" decoding="async" '
                f'class="rounded-circle object-fit-cover flex-shrink-0 {escape(clase_extra)}" '
                f'style="width:{px}px;height:{px}px;aspect-ratio:1/1;object-fit:cover;">'
            )
        except ValueError:
            pass

    grad_css = degradado_categoria(categoria)
    icono = CATEGORIA_ICONOS.get(slug, 'bi-journal-richtext')
    font_size = max(13, round(px * 0.46))
    return mark_safe(
        f'<span class="avatar-circle flex-shrink-0 {escape(clase_extra)}" '
        f'style="width:{px}px;height:{px}px;background:{grad_css};font-size:{font_size}px;" '
        f'aria-hidden="true" title="{escape(nombre)}">'
        f'<i class="bi {icono}" aria-hidden="true"></i></span>'
    )


@register.simple_tag(name='banner_categoria_style')
def banner_categoria_style(categoria):
    """Devuelve el estilo CSS inline para el banner de la categoría (imagen o degradado determinista)."""
    if not categoria:
        return ''
    campo_banner = getattr(categoria, 'banner', None)
    if campo_banner:
        try:
            url_banner = campo_banner.url
            return mark_safe(
                f"background-image: linear-gradient(180deg, rgba(15,23,42,0.18) 0%, rgba(15,23,42,0.55) 100%), url('{escape(url_banner)}');"
            )
        except ValueError:
            pass
    return mark_safe(f'background: {degradado_categoria(categoria)};')


@register.simple_tag(name='miniatura_post')
def miniatura_post(post, tamano=72):
    """
    Renderiza una miniatura cuadrada (`tamano`×`tamano` px, por defecto 72×72) para un post:
    - Si tiene `portada_url`, muestra `<img width="72" height="72" loading="lazy" alt="" style="object-fit: cover;">`.
    - Si no tiene imagen, muestra un cuadro con el degradado determinista del post y su ícono.
    """
    try:
        px = int(tamano)
    except (TypeError, ValueError):
        px = 72

    url_imagen = getattr(post, 'portada_thumb_webp', None) or getattr(post, 'portada_url', None)
    if url_imagen:
        return mark_safe(
            f'<img src="{escape(url_imagen)}" alt="" width="{px}" height="{px}" '
            f'loading="lazy" decoding="async" class="post-thumb-72 flex-shrink-0" '
            f'style="width:{px}px;height:{px}px;aspect-ratio:1/1;object-fit:cover;">'
        )

    categoria = getattr(post, 'categoria', None)
    cat_slug = getattr(categoria, 'slug', '') or 'general'
    icono = CATEGORIA_ICONOS.get(cat_slug, 'bi-journal-richtext')
    grad_css = degradado_portada_post(post)
    font_size = max(16, round(px * 0.38))
    return mark_safe(
        f'<span class="post-thumb-72 flex-shrink-0" '
        f'style="width:{px}px;height:{px}px;background:{grad_css};font-size:{font_size}px;" '
        f'aria-hidden="true">'
        f'<i class="bi {icono}" aria-hidden="true"></i></span>'
    )


@register.simple_tag(takes_context=True, name='url_absoluta_post')
def url_absoluta_post(context, post):
    """Devuelve la URL absoluta de un post usando `request.build_absolute_uri`."""
    from django.conf import settings
    if not post:
        return ''
    rel_url = post.get_absolute_url()
    request = context.get('request')
    if request:
        return request.build_absolute_uri(rel_url)
    base = getattr(settings, 'SITE_URL', 'http://localhost:8000').rstrip('/')
    return f'{base}{rel_url}'

