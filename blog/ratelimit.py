from functools import wraps
from urllib.parse import quote
from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse


def es_peticion_ajax(request):
    """Detecta si la petición fue realizada vía fetch/AJAX esperando JSON."""
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('Accept', '')
    )


def obtener_ip_cliente(request):
    """Obtiene la IP del cliente considerando cabeceras de proxy."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


def login_requerido_interaccion(view_func):
    """
    Decorador para vistas de interacción:
    - Si el usuario no está autenticado y la petición es AJAX, devuelve 401 con JSON.
    - Si es una petición normal de navegador, redirige al login con ?next=.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            login_url = reverse(settings.LOGIN_URL)
            next_path = request.POST.get('next') or request.META.get('HTTP_REFERER') or request.get_full_path()
            if es_peticion_ajax(request):
                return JsonResponse(
                    {
                        'ok': False,
                        'error': 'Debes iniciar sesión para realizar esta acción.',
                        'login_url': f"{login_url}?next={quote(next_path)}",
                    },
                    status=401,
                )
            return redirect(f"{login_url}?next={quote(next_path)}")
        return view_func(request, *args, **kwargs)

    return _wrapped_view


def limitar_tasa(prefijo, limite, ventana_segundos):
    """
    Decorador reutilizable de limitación de tasa usando el cache de Django.
    Ejemplos:
      - me gusta: @limitar_tasa('like', 30, 60)
      - votos: @limitar_tasa('voto', 30, 60)
      - reportes: @limitar_tasa('reporte', 5, 3600)
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if request.user.is_authenticated:
                identificador = f"user_{request.user.pk}"
            else:
                identificador = f"ip_{obtener_ip_cliente(request)}"

            clave_cache = f"ratelimit:{prefijo}:{identificador}"
            conteo_actual = cache.get(clave_cache, 0)

            if conteo_actual >= limite:
                mensaje = 'Has superado el límite de acciones permitidas. Por favor espera unos momentos.'
                if es_peticion_ajax(request):
                    return JsonResponse({'ok': False, 'error': mensaje}, status=429)
                messages.error(request, mensaje)
                return HttpResponse(mensaje, status=429)

            if conteo_actual == 0:
                cache.set(clave_cache, 1, timeout=ventana_segundos)
            else:
                try:
                    cache.incr(clave_cache)
                except ValueError:
                    cache.set(clave_cache, conteo_actual + 1, timeout=ventana_segundos)

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator

