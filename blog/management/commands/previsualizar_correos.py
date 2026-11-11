import os
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.html import escape


class Command(BaseCommand):
    help = 'Previsualiza las plantillas HTML de correos transaccionales del blog.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--guardar',
            action='store_true',
            help='Guarda las vistas previas HTML en staticfiles/email_previews/ o un directorio temporal.',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('Generando previsualización de correos transaccionales...'))

        marca = getattr(settings, 'MARCA_CORTA', 'Blog')
        url_ejemplo = 'http://localhost:8000/suscripcion/confirmar/token-demo-123/'
        url_baja = 'http://localhost:8000/suscripcion/baja/token-demo-123/'
        url_post = 'http://localhost:8000/post/articulo-demo/'

        # 1. Correo de confirmación de suscripción (doble opt-in)
        correo_confirmacion = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Confirma tu suscripción | {marca}</title>
<style>
  body {{ margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; }}
  table {{ border-collapse: collapse; }}
  .email-container {{ max-width: 600px; margin: 24px auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; border: 1px solid #e2e8f0; }}
  .header {{ padding: 24px; text-align: center; background-color: #ffffff; border-bottom: 1px solid #e2e8f0; }}
  .content {{ padding: 32px 24px; }}
  .btn {{ display: inline-block; padding: 12px 24px; background-color: #2563eb; color: #ffffff !important; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 15px; }}
  .footer {{ padding: 20px 24px; background-color: #f8fafc; font-size: 12px; color: #64748b; text-align: center; border-top: 1px solid #e2e8f0; }}
</style>
</head>
<body>
<table width="100%" cellpadding="0" cellspacing="0" role="presentation">
  <tr>
    <td align="center">
      <table class="email-container" width="100%" cellpadding="0" cellspacing="0" role="presentation">
        <tr>
          <td class="header">
            <h1 style="margin: 0; font-size: 20px; font-weight: 700; color: #0f172a;">{marca}</h1>
          </td>
        </tr>
        <tr>
          <td class="content">
            <h2 style="margin: 0 0 16px; font-size: 18px; color: #0f172a;">Confirma tu suscripción</h2>
            <p style="margin: 0 0 20px; line-height: 1.6; font-size: 15px; color: #334155;">
              Has solicitado recibir notificaciones por correo de la comunidad <strong>Python y Django</strong> en {marca}.
            </p>
            <table cellpadding="0" cellspacing="0" role="presentation" style="margin: 24px 0;">
              <tr>
                <td>
                  <a href="{url_ejemplo}" class="btn">Confirmar suscripción</a>
                </td>
              </tr>
            </table>
            <p style="margin: 0; font-size: 13px; color: #64748b; line-height: 1.5;">
              Hasta que no confirmes este enlace no recibirás ninguna notificación. Si no hiciste esta solicitud, puedes ignorar este correo.
            </p>
          </td>
        </tr>
        <tr>
          <td class="footer">
            <p style="margin: 0 0 8px;">{marca} — Plataforma de lectura y debate.</p>
            <p style="margin: 0;"><a href="{url_baja}" style="color: #64748b; text-decoration: underline;">Cancelar suscripción</a></p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""

        # 2. Correo de nuevo artículo publicado
        correo_nuevo_post = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nuevo artículo | {marca}</title>
<style>
  body {{ margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; }}
  table {{ border-collapse: collapse; }}
  .email-container {{ max-width: 600px; margin: 24px auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; border: 1px solid #e2e8f0; }}
  .header {{ padding: 24px; text-align: center; background-color: #ffffff; border-bottom: 1px solid #e2e8f0; }}
  .content {{ padding: 32px 24px; }}
  .btn {{ display: inline-block; padding: 12px 24px; background-color: #2563eb; color: #ffffff !important; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 15px; }}
  .footer {{ padding: 20px 24px; background-color: #f8fafc; font-size: 12px; color: #64748b; text-align: center; border-top: 1px solid #e2e8f0; }}
</style>
</head>
<body>
<table width="100%" cellpadding="0" cellspacing="0" role="presentation">
  <tr>
    <td align="center">
      <table class="email-container" width="100%" cellpadding="0" cellspacing="0" role="presentation">
        <tr>
          <td class="header">
            <h1 style="margin: 0; font-size: 20px; font-weight: 700; color: #0f172a;">{marca}</h1>
          </td>
        </tr>
        <tr>
          <td class="content">
            <span style="display: inline-block; font-size: 12px; font-weight: 600; text-transform: uppercase; color: #2563eb; margin-bottom: 8px;">
              Nuevo artículo en Python y Django
            </span>
            <h2 style="margin: 0 0 16px; font-size: 20px; color: #0f172a;">Optimización de consultas en Django 5</h2>
            <p style="margin: 0 0 12px; font-size: 13px; color: #64748b;">Por Ana García • hace 5 min</p>
            <p style="margin: 0 0 24px; line-height: 1.6; font-size: 15px; color: #334155;">
              Aprende cómo reducir el número de consultas a la base de datos usando select_related, prefetch_related y subconsultas eficientes.
            </p>
            <table cellpadding="0" cellspacing="0" role="presentation" style="margin: 24px 0;">
              <tr>
                <td>
                  <a href="{url_post}" class="btn">Leer artículo completo</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <tr>
          <td class="footer">
            <p style="margin: 0 0 8px;">Recibes este correo porque sigues a Ana García en {marca}.</p>
            <p style="margin: 0;"><a href="{url_baja}" style="color: #64748b; text-decoration: underline;">Darme de baja de esta suscripción</a></p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""

        if options.get('guardar'):
            out_dir = settings.BASE_DIR / 'staticfiles' / 'email_previews'
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(out_dir / 'confirmacion.html', 'w', encoding='utf-8') as f:
                f.write(correo_confirmacion)
            with open(out_dir / 'nuevo_post.html', 'w', encoding='utf-8') as f:
                f.write(correo_nuevo_post)
            self.stdout.write(self.style.SUCCESS(f'Vistas previas guardadas en {out_dir}'))
        else:
            self.stdout.write(self.style.SUCCESS('Previsualización de correos generada correctamente (2 plantillas analizadas).'))
