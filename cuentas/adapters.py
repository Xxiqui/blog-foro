from io import BytesIO
import logging
import re
import unicodedata
from urllib.parse import urlparse

try:
    from allauth.account.adapter import DefaultAccountAdapter
    from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
    from allauth.socialaccount.models import SocialApp
    HAS_ALLAUTH = True
except ImportError:  # pragma: no cover - fallback si el contenedor Docker no ha sido reconstruido
    HAS_ALLAUTH = False
    DefaultAccountAdapter = object
    DefaultSocialAccountAdapter = object
    SocialApp = None
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from PIL import Image, ImageOps
try:
    import requests
except ImportError:  # pragma: no cover - fallback si el contenedor Docker no ha sido reconstruido
    requests = None

from .models import Perfil

logger = logging.getLogger(__name__)
User = get_user_model()

ALLOWED_AVATAR_HOSTS = frozenset({
    'lh3.googleusercontent.com',
    'avatars.githubusercontent.com',
})
MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2 MB
AVATAR_TIMEOUT_SECONDS = 5
AVATAR_TARGET_SIZE = (256, 256)

# Mismo patrón que MENCION_REGEX en blog/notificaciones.py: [A-Za-z0-9_.-]{2,30}
USERNAME_VALID_RE = re.compile(r'^[A-Za-z0-9_.-]{2,30}$')


def obtener_credenciales_proveedor(provider_id):
    """
    Devuelve `(client_id, secret)` para 'google' o 'github' leyendo primero
    las configuraciones de `settings` (compatible con `@override_settings`)
    y luego `SOCIALACCOUNT_PROVIDERS`.
    """
    provider_id = (provider_id or '').lower()
    if provider_id == 'google':
        cid = (getattr(settings, 'GOOGLE_CLIENT_ID', '') or '').strip()
        secret = (getattr(settings, 'GOOGLE_CLIENT_SECRET', '') or '').strip()
    elif provider_id == 'github':
        cid = (getattr(settings, 'GITHUB_CLIENT_ID', '') or '').strip()
        secret = (getattr(settings, 'GITHUB_CLIENT_SECRET', '') or '').strip()
    else:
        cid, secret = '', ''

    if cid and secret:
        return cid, secret

    providers_cfg = getattr(settings, 'SOCIALACCOUNT_PROVIDERS', {}) or {}
    app_cfg = (providers_cfg.get(provider_id) or {}).get('APP') or {}
    cid = (app_cfg.get('client_id') or '').strip()
    secret = (app_cfg.get('secret') or '').strip()
    return cid, secret


def obtener_proveedores_sociales_activos():
    """
    Indica qué proveedores OAuth tienen credenciales configuradas:
    `{'google': bool, 'github': bool, 'hay_proveedores_sociales': bool}`.
    """
    if not HAS_ALLAUTH or not getattr(settings, 'ALLAUTH_INSTALLED', True):
        return {
            'social_google_activo': False,
            'social_github_activo': False,
            'hay_proveedores_sociales': False,
        }
    g_id, g_secret = obtener_credenciales_proveedor('google')
    gh_id, gh_secret = obtener_credenciales_proveedor('github')
    google_activo = bool(g_id and g_secret)
    github_activo = bool(gh_id and gh_secret)
    return {
        'social_google_activo': google_activo,
        'social_github_activo': github_activo,
        'hay_proveedores_sociales': google_activo or github_activo,
    }


def generar_username_unico(semilla='', email=''):
    """
    Genera un `username` único a partir del nombre o correo electrónico,
    garantizando que sea válido para la expresión regular de menciones
    `^[A-Za-z0-9_.-]{2,30}$`.
    """
    fuente = (semilla or '').strip()
    if not fuente and email:
        fuente = str(email).split('@')[0].strip()

    # Normalizar acentos a ASCII
    normalizado = (
        unicodedata.normalize('NFKD', fuente)
        .encode('ascii', 'ignore')
        .decode('ascii')
        .lower()
    )
    # Reemplazar caracteres no permitidos por guion bajo
    limpio = re.sub(r'[^a-z0-9_.-]+', '_', normalizado)
    limpio = re.sub(r'[_.-]{2,}', '_', limpio).strip('._-')

    if len(limpio) < 2:
        limpio = 'usuario'

    base = limpio[:22].rstrip('._-') or 'usuario'
    if len(base) < 2:
        base = 'usuario'

    candidato = base
    sufijo = 1
    while (
        not USERNAME_VALID_RE.match(candidato)
        or User.objects.filter(username__iexact=candidato).exists()
    ):
        candidato = f'{base}_{sufijo}'[:30]
        sufijo += 1

    return candidato


def descargar_avatar_social_seguro(perfil, url_foto):
    """
    Descarga la foto de perfil del proveedor social si `perfil` no tiene avatar,
    aplicando todas las salvaguardas de seguridad:
    - Solo esquema `https`.
    - Solo dominios en `ALLOWED_AVATAR_HOSTS` (`lh3.googleusercontent.com`, `avatars.githubusercontent.com`).
    - Tiempo máximo de espera de 5 segundos (`AVATAR_TIMEOUT_SECONDS`).
    - Tamaño máximo de 2 MB (`MAX_AVATAR_BYTES`).
    - Validación de imagen real con Pillow (`verify()`).
    - Conversión y recorte a 256×256 px y guardado en `perfil.avatar`.
    - Cualquier error se registra con logging y el registro continúa sin foto.
    """
    if not perfil or getattr(perfil, 'avatar', None):
        return False

    if not url_foto or not isinstance(url_foto, str):
        return False

    try:
        parsed = urlparse(url_foto.strip())
        if parsed.scheme.lower() != 'https':
            logger.warning('Avatar social rechazado por no usar HTTPS: %s', url_foto)
            return False

        hostname = (parsed.hostname or '').lower()
        if hostname not in ALLOWED_AVATAR_HOSTS:
            logger.warning('Avatar social rechazado por host no permitido (%s): %s', hostname, url_foto)
            return False

        respuesta = requests.get(
            url_foto.strip(),
            stream=True,
            timeout=AVATAR_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
        try:
            if respuesta.status_code != 200:
                logger.warning('Avatar social devolvió estado HTTP %s: %s', respuesta.status_code, url_foto)
                return False

            content_length = respuesta.headers.get('Content-Length')
            if content_length:
                try:
                    if int(content_length) > MAX_AVATAR_BYTES:
                        logger.warning(
                            'Avatar social rechazado por Content-Length > 2 MB (%s bytes): %s',
                            content_length,
                            url_foto,
                        )
                        return False
                except ValueError:
                    pass

            fragmentos = []
            total_bytes = 0
            for chunk in respuesta.iter_content(chunk_size=16384):
                if not chunk:
                    continue
                total_bytes += len(chunk)
                if total_bytes > MAX_AVATAR_BYTES:
                    logger.warning(
                        'Avatar social rechazado por superar el límite de 2 MB durante la descarga: %s',
                        url_foto,
                    )
                    return False
                fragmentos.append(chunk)

            raw_bytes = b''.join(fragmentos)
        finally:
            respuesta.close()

        if not raw_bytes:
            logger.warning('Avatar social vacío desde %s', url_foto)
            return False

        # 1. Verificar integridad con Pillow
        with Image.open(BytesIO(raw_bytes)) as img_check:
            img_check.verify()

        # 2. Reabrir, convertir y redimensionar a 256x256
        with Image.open(BytesIO(raw_bytes)) as img:
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
            elif img.mode == 'RGBA':
                fondo = Image.new('RGB', img.size, (255, 255, 255))
                fondo.paste(img, mask=img.split()[3])
                img = fondo

            resample_filter = getattr(Image, 'Resampling', Image).LANCZOS
            img_256 = ImageOps.fit(img, AVATAR_TARGET_SIZE, method=resample_filter)

            salida = BytesIO()
            img_256.save(salida, format='JPEG', quality=88, optimize=True)

        username_limpio = getattr(perfil.usuario, 'username', 'usuario')
        nombre_archivo = f'social_{username_limpio}.jpg'
        perfil.avatar.save(nombre_archivo, ContentFile(salida.getvalue()), save=True)
        return True

    except Exception as exc:
        logger.warning('Fallo al descargar o procesar el avatar social (%s): %s', url_foto, exc)
        return False


class CustomAccountAdapter(DefaultAccountAdapter):
    """Adaptador de cuentas para generar usernames válidos para menciones."""

    def populate_username(self, request, user):
        semilla = user.username or user.get_full_name()
        user.username = generar_username_unico(semilla=semilla, email=user.email)


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Adaptador social para Google y GitHub:
    - Resuelve credenciales dinámicamente desde variables de entorno / settings.
    - Vincula con una cuenta existente por correo ÚNICAMENTE si el proveedor marca
      ese correo como verificado; si no está verificado, NO se vincula automáticamente.
    - Genera un `username` único compatible con la regex de menciones.
    - Descarga de forma segura el avatar inicial si el `Perfil` aún no tiene uno.
    """

    def get_app(self, request, provider, client_id=None):
        cid, secret = obtener_credenciales_proveedor(provider)
        if cid and secret:
            return SocialApp(
                provider=provider,
                name=provider.title(),
                client_id=cid,
                secret=secret,
            )
        return super().get_app(request, provider, client_id=client_id)

    def _extraer_email_verificado(self, sociallogin):
        """
        Devuelve el correo electrónico en minúsculas solo si el proveedor lo marca
        explícitamente como verificado. En caso contrario devuelve `None`.
        """
        for email_obj in getattr(sociallogin, 'email_addresses', []) or []:
            if getattr(email_obj, 'verified', False) and getattr(email_obj, 'email', ''):
                return email_obj.email.strip().lower()

        extra = getattr(getattr(sociallogin, 'account', None), 'extra_data', {}) or {}
        verificado_extra = (
            extra.get('email_verified') is True
            or extra.get('verified_email') is True
            or extra.get('verified') is True
        )
        email_candidato = (
            extra.get('email')
            or getattr(getattr(sociallogin, 'user', None), 'email', '')
            or ''
        ).strip().lower()

        if verificado_extra and email_candidato:
            return email_candidato
        return None

    def pre_social_login(self, request, sociallogin):
        super().pre_social_login(request, sociallogin)
        if sociallogin.is_existing:
            return
        if getattr(request, 'user', None) and request.user.is_authenticated:
            return

        email_verificado = self._extraer_email_verificado(sociallogin)
        if email_verificado:
            usuario_existente = User.objects.filter(email__iexact=email_verificado).first()
            if usuario_existente:
                sociallogin.connect(request, usuario_existente)
        else:
            # Si el correo no está verificado y pertenece a un usuario existente,
            # no vincular automáticamente ni sobrescribir su cuenta.
            email_sin_verificar = (getattr(sociallogin.user, 'email', '') or '').strip()
            if email_sin_verificar and User.objects.filter(email__iexact=email_sin_verificar).exists():
                sociallogin.user.email = ''

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        extra = getattr(getattr(sociallogin, 'account', None), 'extra_data', {}) or {}
        semilla = (
            data.get('username')
            or extra.get('login')
            or data.get('name')
            or extra.get('name')
            or f"{data.get('first_name', '')}_{data.get('last_name', '')}".strip('_')
        )
        email = data.get('email') or user.email or ''
        user.username = generar_username_unico(semilla=semilla, email=email)
        return user

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form=form)
        perfil, _ = Perfil.objects.get_or_create(usuario=user)

        if not perfil.avatar:
            url_foto = None
            account = getattr(sociallogin, 'account', None)
            if account:
                try:
                    url_foto = account.get_avatar_url()
                except Exception:
                    url_foto = None
                if not url_foto:
                    extra = getattr(account, 'extra_data', {}) or {}
                    url_foto = extra.get('picture') or extra.get('avatar_url')

            if url_foto:
                descargar_avatar_social_seguro(perfil, url_foto)

        return user

