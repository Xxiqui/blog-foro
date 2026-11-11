"""
Configuración de Django para el proyecto Blog con Panel de Autor.
Condicionada por entorno (desarrollo y producción) mediante variables de entorno.
"""

import importlib.util
import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ALLAUTH_INSTALLED = importlib.util.find_spec('allauth') is not None

# Cargar variables de entorno desde archivo .env si existe
load_dotenv(BASE_DIR / '.env')

# Seguridad y entorno
SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-dev-only-key-cambiar-en-produccion-9876543210abcdef'
)

DEBUG = os.environ.get('DEBUG', 'True').lower() in ('true', '1', 'yes', 't')

_default_allowed_hosts = 'localhost,127.0.0.1,0.0.0.0,testserver,.railway.app,.up.railway.app,.onrender.com'
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get('ALLOWED_HOSTS', _default_allowed_hosts).split(',')
    if host.strip()
]

_railway_domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '').strip()
if _railway_domain and _railway_domain not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_railway_domain)

_default_csrf = 'http://localhost:8000,http://127.0.0.1:8000,https://*.railway.app,https://*.up.railway.app,https://*.onrender.com'
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CSRF_TRUSTED_ORIGINS', _default_csrf).split(',')
    if origin.strip()
]
if _railway_domain:
    _https_railway = f'https://{_railway_domain}'
    if _https_railway not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_https_railway)

# Permitir acceso desde dispositivos móviles en la red local durante desarrollo
if DEBUG:
    import socket
    try:
        _s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _s.connect(('8.8.8.8', 80))
        _ip_local = _s.getsockname()[0]
        _s.close()
        if _ip_local:
            ALLOWED_HOSTS.append(_ip_local)
            CSRF_TRUSTED_ORIGINS.append(f'http://{_ip_local}:8000')
    except Exception:
        pass
    if '*' not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append('*')

# Definición de aplicaciones
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'django.contrib.sitemaps',
    # Terceros
    'django_ckeditor_5',
    'django_htmx',
    *(
        [
            'allauth',
            'allauth.account',
            'allauth.socialaccount',
            'allauth.socialaccount.providers.google',
            'allauth.socialaccount.providers.github',
        ]
        if ALLAUTH_INSTALLED
        else []
    ),
    # Apps locales
    'cuentas.apps.CuentasConfig',
    'blog.apps.BlogConfig',
]

SITE_ID = int(os.environ.get('SITE_ID', 1))

AUTHENTICATION_BACKENDS = [
    'cuentas.backends.EmailOrUsernameModelBackend',
    'django.contrib.auth.backends.ModelBackend',
    *(
        ['allauth.account.auth_backends.AuthenticationBackend']
        if ALLAUTH_INSTALLED
        else []
    ),
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    *(
        ['allauth.account.middleware.AccountMiddleware']
        if ALLAUTH_INSTALLED
        else []
    ),
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'blog.context_processors.notificaciones_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Base de datos: PostgreSQL en producción/Docker via DATABASE_URL, SQLite por defecto
DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

# `django.contrib.postgres` solo se registra cuando la base de datos es PostgreSQL:
# su AppConfig importa el controlador psycopg, que no es necesario con SQLite.
if 'postgresql' in DATABASES['default'].get('ENGINE', ''):
    INSTALLED_APPS.insert(INSTALLED_APPS.index('django.contrib.sites'), 'django.contrib.postgres')

# Validación de contraseñas
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internacionalización
LANGUAGE_CODE = 'es'
TIME_ZONE = 'America/Bogota'
USE_I18N = True
USE_TZ = True

# Archivos estáticos (CSS, JavaScript, Imágenes)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}
WHITENOISE_MANIFEST_STRICT = False

# Archivos multimedia (subidos por usuarios y CKEditor)
MEDIA_URL = '/media/'
MEDIA_ROOT = Path(os.environ.get('MEDIA_ROOT', BASE_DIR / 'media'))

# Redirecciones de autenticación
LOGIN_URL = 'cuentas:login'
LOGIN_REDIRECT_URL = 'blog:panel_dashboard'
LOGOUT_REDIRECT_URL = 'blog:post_list'

# Cache (utilizado por el limitador de tasa por IP / usuario)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'blog-interacciones-cache',
    }
}

# Correo electrónico (consola por defecto en desarrollo, configurable por entorno)
EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend',
)
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'no-reply@blogautores.local')

# Parámetros de interacción y moderación de comentarios
FEED_PAGINATE_BY = int(os.environ.get('FEED_PAGINATE_BY', 15))
COMENTARIOS_ANONIMOS = os.environ.get('COMENTARIOS_ANONIMOS', 'False').lower() in ('true', '1', 'yes')
COMENTARIO_VENTANA_EDICION_MIN = int(os.environ.get('COMENTARIO_VENTANA_EDICION_MIN', 10))
REPORTES_PARA_OCULTAR = int(os.environ.get('REPORTES_PARA_OCULTAR', 3))
COMENTARIO_PROFUNDIDAD_MAX = int(os.environ.get('COMENTARIO_PROFUNDIDAD_MAX', 4))

# Acceso social OAuth2 (django-allauth: solo Google y GitHub por variables de entorno)
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '').strip()
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '').strip()
GITHUB_CLIENT_ID = os.environ.get('GITHUB_CLIENT_ID', '').strip()
GITHUB_CLIENT_SECRET = os.environ.get('GITHUB_CLIENT_SECRET', '').strip()

ACCOUNT_ADAPTER = 'cuentas.adapters.CustomAccountAdapter'
SOCIALACCOUNT_ADAPTER = 'cuentas.adapters.CustomSocialAccountAdapter'
SOCIALACCOUNT_LOGIN_ON_GET = False
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = False
ACCOUNT_EMAIL_VERIFICATION = 'none'

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'FETCH_USERINFO': True,
        **(
            {
                'APP': {
                    'client_id': GOOGLE_CLIENT_ID,
                    'secret': GOOGLE_CLIENT_SECRET,
                    'key': '',
                }
            }
            if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
            else {}
        ),
    },
    'github': {
        'SCOPE': ['read:user', 'user:email'],
        'VERIFIED_EMAIL': True,
        **(
            {
                'APP': {
                    'client_id': GITHUB_CLIENT_ID,
                    'secret': GITHUB_CLIENT_SECRET,
                    'key': '',
                }
            }
            if GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET
            else {}
        ),
    },
}

# Umbrales de insignias y autores destacados (Bloque 4)
AUTOR_INSIGNIA_NUEVO_MAX_POSTS = int(os.environ.get('AUTOR_INSIGNIA_NUEVO_MAX_POSTS', 3))
AUTOR_INSIGNIA_ACTIVO_MIN_POSTS = int(os.environ.get('AUTOR_INSIGNIA_ACTIVO_MIN_POSTS', 5))
AUTOR_DESTACADO_TOP_N = int(os.environ.get('AUTOR_DESTACADO_TOP_N', 3))
AUTOR_DESTACADO_UMBRAL_PUNTOS = int(os.environ.get('AUTOR_DESTACADO_UMBRAL_PUNTOS', 8))

# Nombre unificado de la marca y URL base del sitio
MARCA = os.environ.get('MARCA', 'Blog').strip()
MARCA_CORTA = os.environ.get('MARCA_CORTA', 'Blog').strip()
MARCA_DESCRIPCION = os.environ.get(
    'MARCA_DESCRIPCION',
    'Comunidad de lectura técnica, debate constructivo y desarrollo en Django. Comparte tus conocimientos con autores y lectores.'
).strip()
SITE_NAME = MARCA_CORTA
SITE_DOMAIN = os.environ.get('SITE_DOMAIN', 'localhost:8000').strip()
SITE_URL = os.environ.get('SITE_URL', f'http://{SITE_DOMAIN}').rstrip('/')

# Tipo de clave primaria por defecto
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Configuración de CKEditor 5
CKEDITOR_5_UPLOAD_PATH = 'uploads/'
CKEDITOR_5_FILE_UPLOAD_PERMISSION = 'authenticated'

CKEDITOR_5_CONFIGS = {
    'default': {
        'language': 'es',
        'toolbar': [
            'heading', '|',
            'bold', 'italic', 'link', '|',
            'bulletedList', 'numberedList', '|',
            'blockQuote', 'codeBlock', '|',
            'insertTable', 'imageUpload', '|',
            'undo', 'redo',
        ],
        'image': {
            'toolbar': [
                'imageTextAlternative', '|',
                'imageStyle:alignLeft',
                'imageStyle:alignCenter',
                'imageStyle:alignRight',
            ],
        },
        'table': {
            'contentToolbar': [
                'tableColumn', 'tableRow', 'mergeTableCells',
            ],
        },
        'heading': {
            'options': [
                {'model': 'paragraph', 'title': 'Párrafo', 'class': 'ck-heading_paragraph'},
                {'model': 'heading2', 'view': 'h2', 'title': 'Encabezado 2', 'class': 'ck-heading_heading2'},
                {'model': 'heading3', 'view': 'h3', 'title': 'Encabezado 3', 'class': 'ck-heading_heading3'},
                {'model': 'heading4', 'view': 'h4', 'title': 'Encabezado 4', 'class': 'ck-heading_heading4'},
            ]
        },
    },
}

# Configuración de seguridad adicional para Producción (cuando DEBUG=False)
if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True').lower() in ('true', '1', 'yes', 't')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', 31536000))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
