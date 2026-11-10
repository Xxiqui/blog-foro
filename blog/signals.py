from django.contrib.auth import get_user_model
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from .models import (
    Comentario,
    LikePost,
    ListaLectura,
    Post,
    Seguimiento,
    VistaDiaria,
    VotoUtil,
)
from .populares import invalidar_cache_ranking

User = get_user_model()


@receiver(m2m_changed, sender=Post.etiquetas.through)
def actualizar_vector_al_cambiar_etiquetas(sender, instance, action, **kwargs):
    """
    Mantiene sincronizado el campo `buscador` cuando se agregan, eliminan
    o limpian etiquetas de un Post en PostgreSQL.
    """
    if action in ('post_add', 'post_remove', 'post_clear'):
        instance.actualizar_vector_busqueda()


@receiver(post_save, sender=User)
def crear_lista_guardados_por_defecto(sender, instance, created, **kwargs):
    """
    Crea automáticamente la lista de lectura privada 'Guardados'
    cuando se registra o guarda un usuario.
    """
    ListaLectura.objects.get_or_create(
        usuario=instance,
        nombre=ListaLectura.NOMBRE_GUARDADOS,
        defaults={
            'descripcion': 'Artículos guardados para leer más tarde.',
            'publica': False,
            'es_predeterminada': True,
        },
    )


@receiver([post_save, post_delete], sender=Post)
@receiver([post_save, post_delete], sender=LikePost)
@receiver([post_save, post_delete], sender=VotoUtil)
@receiver([post_save, post_delete], sender=Comentario)
@receiver([post_save, post_delete], sender=Seguimiento)
@receiver([post_save, post_delete], sender=VistaDiaria)
def refrescar_cache_rankings(sender, **kwargs):
    """Invalida la versión del cache de posts populares y autores destacados al cambiar datos."""
    invalidar_cache_ranking()
