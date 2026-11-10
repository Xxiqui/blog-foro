import logging
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from blog.models import Post
from blog.servicios import publicacion as servicio_publicacion

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Publica automáticamente los posts programados cuya fecha y hora ya haya vencido.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra los posts que se publicarían sin aplicar cambios en la base de datos.',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        ahora = timezone.now()

        posts_a_publicar = Post.objects.filter(
            estado=Post.Estado.PROGRAMADO,
            programado_para__lte=ahora,
        ).order_by('programado_para')

        total = posts_a_publicar.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS('No hay posts programados pendientes de publicación.'))
            return

        self.stdout.write(f'Encontrados {total} post(s) programado(s) para publicar (hora corte: {ahora:%Y-%m-%d %H:%M:%S})...')

        if dry_run:
            for p in posts_a_publicar:
                self.stdout.write(f'[DRY-RUN] Se publicaría: «{p.titulo}» (id: {p.pk}, programado: {p.programado_para})')
            return

        soporta_skip_locked = getattr(connection.features, 'has_select_for_update_skip_locked', False)

        publicados_ok = 0
        errores = 0

        # Procesar post a post para aislar fallos
        for p in posts_a_publicar:
            try:
                with transaction.atomic():
                    qs = Post.objects.filter(pk=p.pk)
                    if soporta_skip_locked:
                        qs = qs.select_for_update(skip_locked=True)
                    post_bloqueado = qs.first()

                    if not post_bloqueado or post_bloqueado.estado != Post.Estado.PROGRAMADO:
                        continue  # Ya fue publicado por otro worker concurrente

                    servicio_publicacion.publicar(post_bloqueado)
                    publicados_ok += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'✓ Publicado: «{post_bloqueado.titulo}» (id: {post_bloqueado.pk}, slug: {post_bloqueado.slug})'
                    ))
            except Exception as e:
                errores += 1
                logger.error("Error al publicar post programado #%s: %s", p.pk, e, exc_info=True)
                self.stderr.write(self.style.ERROR(
                    f'✗ Error al publicar post #{p.pk} («{p.titulo}»): {e}'
                ))

        resumen = f'Proceso finalizado: {publicados_ok} publicados correctamente'
        if errores > 0:
            resumen += f', {errores} errores.'
            self.stdout.write(self.style.WARNING(resumen))
        else:
            resumen += '.'
            self.stdout.write(self.style.SUCCESS(resumen))

