from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Perfil

User = get_user_model()


@receiver(post_save, sender=User)
def crear_o_actualizar_perfil_usuario(sender, instance, created, **kwargs):
    """Crea automáticamente un Perfil cuando se registra un nuevo usuario."""
    if created:
        Perfil.objects.get_or_create(usuario=instance)
    else:
        Perfil.objects.get_or_create(usuario=instance)

