from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.static import serve
from django_ckeditor_5.views import upload_file

def health_check(request):
    try:
        connection.cursor()
        return HttpResponse('OK', content_type='text/plain')
    except Exception as e:
        return HttpResponse(f'DB unavailable: {e}', status=503, content_type='text/plain')

admin.site.site_header = 'Administración del Blog'
admin.site.site_title = 'Blog'
admin.site.index_title = 'Gestión de Contenidos y Usuarios'

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('admin/', admin.site.urls),
    path('cuentas/', include('cuentas.urls', namespace='cuentas')),
    *(
        [path('oauth/', include('allauth.urls'))]
        if getattr(settings, 'ALLAUTH_INSTALLED', False)
        else []
    ),
    # Subida de imágenes de CKEditor 5 restringida a usuarios autenticados
    path('ckeditor5/image_upload/', login_required(upload_file), name='ck_editor_5_upload_file'),
    path('ckeditor5/', include('django_ckeditor_5.urls')),
    path('', include('blog.urls', namespace='blog')),
]

# Servir archivos multimedia (avatares e imágenes del editor) desde MEDIA_ROOT
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
