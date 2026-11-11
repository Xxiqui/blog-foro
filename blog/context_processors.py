from django.conf import settings
from cuentas.adapters import obtener_proveedores_sociales_activos
from .models import Categoria, ListaLectura, Notificacion


def notificaciones_context(request):
    """
    Context processor para la campana de notificaciones (con un solo COUNT de no leídas),
    nombre unificado de la marca (`marca` y `site_name`), categorías del pie de página, listas de lectura
    y estado de proveedores sociales configurados.
    """
    categorias_footer = Categoria.objects.all()
    comunidades_nav = Categoria.objects.all()[:8]
    marca = getattr(settings, 'MARCA', 'Blog')
    marca_corta = getattr(settings, 'MARCA_CORTA', 'Blog')
    marca_descripcion = getattr(
        settings,
        'MARCA_DESCRIPCION',
        'Comunidad de lectura técnica, debate constructivo y desarrollo en Django. Comparte tus conocimientos con autores y lectores.'
    )
    site_name = marca_corta
    social_ctx = obtener_proveedores_sociales_activos()

    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {
            'marca': marca,
            'marca_corta': marca_corta,
            'marca_descripcion': marca_descripcion,
            'site_name': site_name,
            'notificaciones_no_leidas_count': 0,
            'ultimas_notificaciones': (),
            'mis_listas_lectura': (),
            'categorias_footer': categorias_footer,
            'comunidades_nav': comunidades_nav,
            **social_ctx,
        }

    no_leidas_count = Notificacion.objects.filter(
        destinatario=request.user,
        leida=False,
    ).count()

    ultimas_5 = Notificacion.objects.filter(
        destinatario=request.user,
    ).select_related('actor', 'post')[:5]

    mis_listas = ListaLectura.objects.filter(usuario=request.user).order_by('-es_predeterminada', 'nombre')

    # Comunidades a las que pertenece el usuario (o generales si aún no se ha unido a ninguna)
    comunidades_usuario = Categoria.objects.filter(miembros__usuario=request.user)[:8]
    if not comunidades_usuario.exists():
        comunidades_usuario = comunidades_nav

    return {
        'marca': marca,
        'marca_corta': marca_corta,
        'marca_descripcion': marca_descripcion,
        'site_name': site_name,
        'notificaciones_no_leidas_count': no_leidas_count,
        'ultimas_notificaciones': ultimas_5,
        'mis_listas_lectura': mis_listas,
        'categorias_footer': categorias_footer,
        'comunidades_nav': comunidades_usuario,
        **social_ctx,
    }
