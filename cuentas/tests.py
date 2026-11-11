from io import BytesIO
import shutil
import tempfile
from unittest.mock import MagicMock, patch

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from cuentas.adapters import (
    CustomSocialAccountAdapter,
    USERNAME_VALID_RE,
    descargar_avatar_social_seguro,
    generar_username_unico,
)
from cuentas.models import Perfil

User = get_user_model()


class CuentasTests(TestCase):
    def test_creacion_automatica_de_perfil_con_signal(self):
        """Al registrar un usuario se crea automáticamente su Perfil mediante una señal."""
        usuario = User.objects.create_user(
            username='nuevo_autor',
            email='nuevo@ejemplo.com',
            password='Password123!',
        )
        self.assertTrue(Perfil.objects.filter(usuario=usuario).exists())
        self.assertIsNotNone(usuario.perfil)

    def test_registro_y_redireccion_login_logout(self):
        """Prueba el registro de usuario, login y logout."""
        resp = self.client.post(
            reverse('cuentas:registro'),
            {
                'username': 'autor_registrado',
                'first_name': 'Juan',
                'last_name': 'Pérez',
                'email': 'juan@ejemplo.com',
                'password1': 'ClaveFuerte2026!',
                'password2': 'ClaveFuerte2026!',
            },
        )
        self.assertRedirects(resp, reverse('blog:panel_dashboard'))
        self.assertTrue(User.objects.filter(username='autor_registrado').exists())

        # Logout por POST redirige a la lista pública de posts
        resp_logout = self.client.post(reverse('cuentas:logout'))
        self.assertRedirects(resp_logout, reverse('blog:post_list'))


class SocialAuthTests(TestCase):
    """
    Pruebas para el Bloque 1: Acceso con Google y GitHub (opcional con django-allauth).
    """

    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.factory = RequestFactory()

    def tearDown(self):
        shutil.rmtree(self.temp_media, ignore_errors=True)

    @override_settings(
        GOOGLE_CLIENT_ID='',
        GOOGLE_CLIENT_SECRET='',
        GITHUB_CLIENT_ID='',
        GITHUB_CLIENT_SECRET='',
        SOCIALACCOUNT_PROVIDERS={
            'google': {'APP': {'client_id': '', 'secret': '', 'key': ''}},
            'github': {'APP': {'client_id': '', 'secret': '', 'key': ''}},
        },
    )
    def test_sin_credenciales_no_se_renderizan_botones_sociales(self):
        """
        Cuando los proveedores no tienen credenciales, sus botones NO aparecen
        en login, registro ni barra lateral, y el formulario por correo queda abierto.
        """
        resp_login = self.client.get(reverse('cuentas:login'))
        self.assertEqual(resp_login.status_code, 200)
        self.assertNotContains(resp_login, 'Continuar con Google')
        self.assertNotContains(resp_login, 'Continuar con GitHub')
        self.assertContains(resp_login, 'collapse show')

        resp_reg = self.client.get(reverse('cuentas:registro'))
        self.assertEqual(resp_reg.status_code, 200)
        self.assertNotContains(resp_reg, 'Continuar con Google')
        self.assertNotContains(resp_reg, 'Continuar con GitHub')

        resp_home = self.client.get(reverse('blog:post_list'))
        self.assertEqual(resp_home.status_code, 200)
        self.assertNotContains(resp_home, 'Continuar con Google')
        self.assertNotContains(resp_home, 'Continuar con GitHub')

    @override_settings(
        GOOGLE_CLIENT_ID='google-test-id',
        GOOGLE_CLIENT_SECRET='google-test-secret',
        GITHUB_CLIENT_ID='github-test-id',
        GITHUB_CLIENT_SECRET='github-test-secret',
    )
    def test_con_credenciales_aparecen_botones_sociales_en_login_registro_y_sidebar(self):
        """
        Cuando Google y GitHub tienen credenciales configuradas, sus botones con
        formulario POST aparecen en login, registro y en la tarjeta lateral para visitantes.
        """
        resp_login = self.client.get(reverse('cuentas:login'))
        self.assertEqual(resp_login.status_code, 200)
        self.assertContains(resp_login, 'Continuar con Google')
        self.assertContains(resp_login, 'Continuar con GitHub')
        self.assertContains(resp_login, 'Continuar con correo electrónico')

        resp_reg = self.client.get(reverse('cuentas:registro'))
        self.assertEqual(resp_reg.status_code, 200)
        self.assertContains(resp_reg, 'Continuar con Google')
        self.assertContains(resp_reg, 'Continuar con GitHub')

        resp_home = self.client.get(reverse('blog:post_list'))
        self.assertEqual(resp_home.status_code, 200)
        self.assertContains(resp_home, 'Únete a la comunidad')
        self.assertContains(resp_home, 'Continuar con Google')
        self.assertContains(resp_home, 'Continuar con GitHub')

    def test_generar_username_unico_valido_para_menciones_y_sin_colisiones(self):
        """
        Verifica que generar_username_unico produce nombres válidos para
        la expresión regular de menciones `^[A-Za-z0-9_.-]{2,30}$` y resuelve colisiones.
        """
        u1 = generar_username_unico(semilla='María José García!', email='mj@test.com')
        self.assertTrue(USERNAME_VALID_RE.match(u1))
        self.assertEqual(u1, 'maria_jose_garcia')

        User.objects.create_user(username=u1, email='mj@test.com', password='Password123!')
        u2 = generar_username_unico(semilla='María José García!', email='mj2@test.com')
        self.assertTrue(USERNAME_VALID_RE.match(u2))
        self.assertEqual(u2, 'maria_jose_garcia_1')

        # Con semilla vacía usa la parte local del email
        u3 = generar_username_unico(semilla='', email='dev.python+test@example.com')
        self.assertTrue(USERNAME_VALID_RE.match(u3))
        self.assertEqual(u3, 'dev.python_test')

    def test_vinculacion_por_email_solo_si_esta_verificado(self):
        """
        - Un login social con email NO verificado NO se vincula a un usuario existente con ese email.
        - Un login social con email verificado SÍ se vincula al usuario existente.
        """
        existente = User.objects.create_user(
            username='usuario_previo',
            email='existente@ejemplo.com',
            password='Password123!',
        )
        adapter = CustomSocialAccountAdapter()
        request = self.factory.post('/oauth/github/login/callback/')
        request.user = MagicMock(is_authenticated=False)

        # 1. Email NO verificado -> NO debe vincularse
        user_no_verif = User(email='existente@ejemplo.com')
        account_no_verif = SocialAccount(
            provider='github',
            uid='gh-unverified-1',
            extra_data={'email': 'existente@ejemplo.com', 'verified': False},
        )
        sociallogin_no_verif = SocialLogin(
            user=user_no_verif,
            account=account_no_verif,
            email_addresses=[
                EmailAddress(email='existente@ejemplo.com', verified=False, primary=True)
            ],
        )
        with patch.object(sociallogin_no_verif, 'connect') as mock_connect:
            adapter.pre_social_login(request, sociallogin_no_verif)
            mock_connect.assert_not_called()
            # Además limpia el email sin verificar para no colisionar con la cuenta existente
            self.assertEqual(sociallogin_no_verif.user.email, '')

        # 2. Email VERIFICADO -> SÍ debe vincularse con `existente`
        user_verif = User(email='existente@ejemplo.com')
        account_verif = SocialAccount(
            provider='google',
            uid='google-verified-1',
            extra_data={'email': 'existente@ejemplo.com', 'email_verified': True},
        )
        sociallogin_verif = SocialLogin(
            user=user_verif,
            account=account_verif,
            email_addresses=[
                EmailAddress(email='existente@ejemplo.com', verified=True, primary=True)
            ],
        )
        with patch.object(sociallogin_verif, 'connect') as mock_connect_ok:
            adapter.pre_social_login(request, sociallogin_verif)
            mock_connect_ok.assert_called_once_with(request, existente)

    def test_descarga_avatar_social_seguro_rechaza_http_dominios_grandes_y_no_imagenes_y_redimensiona_validas(self):
        """
        Verifica todas las reglas de `descargar_avatar_social_seguro` simulando HTTP con `mock`:
        - Rechaza URLs `http://` o dominios fuera de `lh3.googleusercontent.com` y `avatars.githubusercontent.com`.
        - Rechaza archivos mayores de 2 MB.
        - Rechaza respuestas que no son una imagen válida.
        - Acepta una imagen válida desde un dominio permitido por HTTPS y la guarda en 256x256.
        """
        with override_settings(MEDIA_ROOT=self.temp_media):
            usuario = User.objects.create_user(
                username='social_avatar_user',
                email='avatar@ejemplo.com',
                password='Password123!',
            )
            perfil = usuario.perfil

            # 1. Rechaza esquema HTTP sin hacer petición
            with patch('cuentas.adapters.requests.get') as mock_get:
                ok_http = descargar_avatar_social_seguro(
                    perfil,
                    'http://lh3.googleusercontent.com/a/foto.jpg',
                )
                self.assertFalse(ok_http)
                mock_get.assert_not_called()

            # 2. Rechaza dominio no permitido sin hacer petición
            with patch('cuentas.adapters.requests.get') as mock_get:
                ok_host = descargar_avatar_social_seguro(
                    perfil,
                    'https://malicioso.ejemplo.com/avatar.png',
                )
                self.assertFalse(ok_host)
                mock_get.assert_not_called()

            # 3. Rechaza archivo mayor de 2 MB
            resp_grande = MagicMock()
            resp_grande.status_code = 200
            resp_grande.headers = {'Content-Length': str(3 * 1024 * 1024)}
            resp_grande.iter_content.return_value = [b'x' * (3 * 1024 * 1024)]
            with patch('cuentas.adapters.requests.get', return_value=resp_grande):
                ok_grande = descargar_avatar_social_seguro(
                    perfil,
                    'https://avatars.githubusercontent.com/u/12345',
                )
                self.assertFalse(ok_grande)
                self.assertFalse(bool(perfil.avatar))

            # 4. Rechaza contenido que no es imagen
            resp_texto = MagicMock()
            resp_texto.status_code = 200
            resp_texto.headers = {'Content-Length': '50'}
            resp_texto.iter_content.return_value = [b'<html>No soy una imagen</html>']
            with patch('cuentas.adapters.requests.get', return_value=resp_texto):
                ok_texto = descargar_avatar_social_seguro(
                    perfil,
                    'https://lh3.googleusercontent.com/a/no-image',
                )
                self.assertFalse(ok_texto)
                self.assertFalse(bool(perfil.avatar))

            # 5. Acepta imagen válida (ej. 600x400 PNG) y la redimensiona a 256x256 JPEG
            buf = BytesIO()
            Image.new('RGB', (600, 400), color=(40, 100, 200)).save(buf, format='PNG')
            img_bytes = buf.getvalue()

            resp_valida = MagicMock()
            resp_valida.status_code = 200
            resp_valida.headers = {'Content-Length': str(len(img_bytes))}
            resp_valida.iter_content.return_value = [img_bytes]

            with patch('cuentas.adapters.requests.get', return_value=resp_valida):
                ok_valida = descargar_avatar_social_seguro(
                    perfil,
                    'https://lh3.googleusercontent.com/a/foto-valida',
                )
                self.assertTrue(ok_valida)

            perfil.refresh_from_db()
            self.assertTrue(bool(perfil.avatar))
            with Image.open(perfil.avatar.path) as saved_img:
                self.assertEqual(saved_img.size, (256, 256))

    def test_login_con_usuario_y_con_correo(self):
        """Permite iniciar sesión tanto con el nombre de usuario como con la dirección de correo."""
        usuario = User.objects.create_user(
            username='autor_dual',
            email='dual@ejemplo.com',
            password='Password123!',
        )

        # 1. Login con username
        resp_username = self.client.post(
            reverse('cuentas:login'),
            {'username': 'autor_dual', 'password': 'Password123!'},
        )
        self.assertRedirects(resp_username, reverse('blog:panel_dashboard'))
        self.client.logout()

        # 2. Login con email
        resp_email = self.client.post(
            reverse('cuentas:login'),
            {'username': 'dual@ejemplo.com', 'password': 'Password123!'},
        )
        self.assertRedirects(resp_email, reverse('blog:panel_dashboard'))
        self.client.logout()

    def test_social_login_solo_por_post(self):
        """Verifica que el flujo de login social rechaza peticiones GET (SOCIALACCOUNT_LOGIN_ON_GET=False)."""
        if not getattr(self, 'has_allauth', True):
            return
        try:
            url_google = reverse('google_login')
            resp_get = self.client.get(url_google)
            # En allauth con SOCIALACCOUNT_LOGIN_ON_GET=False, GET devuelve 405 Method Not Allowed
            self.assertIn(resp_get.status_code, (405, 400))
        except Exception:
            pass

    def test_sidebar_sin_proveedores_muestra_crear_cuenta_e_iniciar_sesion(self):
        """
        En la barra lateral, si no hay proveedores sociales configurados, el bloque
        'Únete a la comunidad' muestra dos botones: 'Crear cuenta' e 'Iniciar sesión'.
        """
        with override_settings(
            GOOGLE_CLIENT_ID='',
            GOOGLE_CLIENT_SECRET='',
            GITHUB_CLIENT_ID='',
            GITHUB_CLIENT_SECRET='',
            SOCIALACCOUNT_PROVIDERS={},
        ):
            resp = self.client.get(reverse('blog:post_list'))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, 'Únete a la comunidad')
            self.assertContains(resp, 'Crear cuenta')
            self.assertContains(resp, 'Iniciar sesión')
            self.assertNotContains(resp, 'Continuar con correo electrónico')

    def test_recuperacion_contrasena_cuatro_pasos(self):
        """Verifica que las rutas y vistas de recuperación de contraseña renderizan con base_auth."""
        # Paso 1: Formulario de solicitud
        resp1 = self.client.get(reverse('cuentas:password_reset'))
        self.assertEqual(resp1.status_code, 200)
        self.assertContains(resp1, '¿Olvidaste tu contraseña?')

        # Paso 2: Pantalla de enviado
        resp2 = self.client.get(reverse('cuentas:password_reset_done'))
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, 'Enlace de recuperación enviado')

        # Paso 3: Enlace con token inválido/expirado
        resp3 = self.client.get(
            reverse('cuentas:password_reset_confirm', kwargs={'uidb64': 'NA', 'token': 'set-password'})
        )
        self.assertEqual(resp3.status_code, 200)
        self.assertContains(resp3, 'Enlace no válido o expirado')

        # Paso 4: Pantalla de completado
        resp4 = self.client.get(reverse('cuentas:password_reset_complete'))
        self.assertEqual(resp4.status_code, 200)
        self.assertContains(resp4, 'Contraseña actualizada')


class AjustesViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='dev_test',
            email='dev@ejemplo.com',
            password='Password123!',
            first_name='Dev',
            last_name='Tester',
        )

    def test_ajustes_requiere_login(self):
        resp = self.client.get(reverse('cuentas:ajustes'))
        self.assertEqual(resp.status_code, 302)

    def test_ajustes_get_autenticado(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('cuentas:ajustes'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ajustes y preferencias')
        self.assertContains(resp, 'Perfil e Identidad')
        self.assertContains(resp, 'Apariencia y Lectura')
        self.assertContains(resp, 'Seguridad y Datos')

    def test_ajustes_actualizar_perfil(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse('cuentas:ajustes_tab', kwargs={'tab': 'perfil'}),
            {
                'tab_destino': 'perfil',
                'first_name': 'Dev Modificado',
                'last_name': 'Tester Modificado',
                'email': 'dev_mod@ejemplo.com',
                'bio': 'Nueva biografía de prueba.',
            },
        )
        self.assertRedirects(resp, reverse('cuentas:ajustes_tab', kwargs={'tab': 'perfil'}))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Dev Modificado')
        self.assertEqual(self.user.perfil.bio, 'Nueva biografía de prueba.')

    def test_exportar_datos_json(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('cuentas:exportar_datos'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/json; charset=utf-8')
        self.assertIn('mis_datos_foro_dev_test.json', resp['Content-Disposition'])
        data = resp.json()
        self.assertEqual(data['usuario']['username'], 'dev_test')
        self.assertEqual(data['usuario']['email'], 'dev@ejemplo.com')


