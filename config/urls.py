from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path, re_path
from django.views.static import serve
from django_ckeditor_5.views import upload_file

admin.site.site_header = 'Administración del Blog'
admin.site.site_title = 'Blog con Panel de Autor'
admin.site.index_title = 'Gestión de Contenidos y Usuarios'

urlpatterns = [
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
