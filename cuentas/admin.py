from django.contrib import admin
from .models import Perfil


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'obtener_email', 'tiene_avatar')
    list_filter = ('usuario__is_active', 'usuario__date_joined')
    search_fields = ('usuario__username', 'usuario__email', 'usuario__first_name', 'usuario__last_name', 'bio')
    raw_id_fields = ('usuario',)

    @admin.display(description='Email', ordering='usuario__email')
    def obtener_email(self, obj):
        return obj.usuario.email

    @admin.display(description='Avatar', boolean=True)
    def tiene_avatar(self, obj):
        return bool(obj.avatar)
