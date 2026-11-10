from django.conf import settings
from django.db import migrations


def fijar_site_marca(apps, schema_editor):
    Site = apps.get_model('sites', 'Site')
    site_id = getattr(settings, 'SITE_ID', 1)
    marca = getattr(settings, 'MARCA', getattr(settings, 'SITE_NAME', 'Blog con Panel de Autor')).strip()
    dominio = getattr(settings, 'SITE_DOMAIN', 'localhost:8000').strip()

    site, _ = Site.objects.get_or_create(id=site_id)
    site.domain = dominio
    site.name = marca
    site.save()


def revertir_site_marca(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0005_post_extracto_manual_post_imagen_portada'),
        ('sites', '0002_alter_domain_unique'),
    ]

    operations = [
        migrations.RunPython(fijar_site_marca, revertir_site_marca),
    ]

