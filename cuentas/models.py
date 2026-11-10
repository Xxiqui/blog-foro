from django.conf import settings
from django.db import models
from django.urls import reverse


class Perfil(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='perfil',
        verbose_name='Usuario',
    )
    bio = models.TextField(
        blank=True,
        verbose_name='Biografía',
        help_text='Breve descripción sobre el autor.',
    )
    avatar = models.ImageField(
        upload_to='avatares/',
        blank=True,
        null=True,
        verbose_name='Avatar',
    )

    class Meta:
        verbose_name = 'Perfil'
        verbose_name_plural = 'Perfiles'
        ordering = ['usuario__username']

    @property
    def nombre_mostrar(self):
        """Devuelve el nombre completo del autor o, si está vacío, su nombre de usuario."""
        nombre_completo = (self.usuario.get_full_name() or '').strip()
        return nombre_completo if nombre_completo else self.usuario.username

    @property
    def nombre_visible(self):
        """Alias compatible con plantillas y utilidades existentes."""
        return self.nombre_mostrar

    def get_absolute_url(self):
        return reverse('blog:autor_detail', kwargs={'username': self.usuario.username})

    def __str__(self):
        nombre = self.usuario.get_full_name()
        return f"{nombre} ({self.usuario.username})" if nombre else self.usuario.username
