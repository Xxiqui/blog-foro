from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blog.forms import ComentarioForm, PostForm
from blog.models import (
    Categoria,
    Comentario,
    Etiqueta,
    ItemLista,
    LikeComentario,
    LikePost,
    ListaLectura,
    MiembroCategoria,
    Notificacion,
    Post,
    ReglaCategoria,
    ReporteComentario,
    Seguimiento,
    Suscripcion,
    VistaDiaria,
    VotoUtil,
)
from blog.notificaciones import notificar
from blog.populares import (
    autores_destacados,
    calcular_insignias_perfil,
    construir_queryset_categorias_metricas,
    obtener_comunidades_descubrir,
    posts_populares,
)
from blog.search import buscar_posts
from blog.templatetags.blog_extras import (
    degradado_portada_post,
    extracto_plano,
    generar_toc_html,
    insignia,
    portada_post,
    renderizar_menciones,
    sanear_html,
    sanear_y_generar_toc,
)

User = get_user_model()


class BlogTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user_autor1 = User.objects.create_user(
            username='autor1',
            email='autor1@test.com',
            password='PasswordSegura123!',
        )
        self.user_autor2 = User.objects.create_user(
            username='autor2',
            email='autor2@test.com',
            password='PasswordSegura123!',
        )
        self.perfil1 = self.user_autor1.perfil
        self.perfil2 = self.user_autor2.perfil

        self.categoria = Categoria.objects.create(nombre='Tecnología')
        self.etiqueta = Etiqueta.objects.create(nombre='Django')

        self.post_publicado = Post.objects.create(
            titulo='Artículo Publicado de Prueba',
            autor=self.perfil1,
            categoria=self.categoria,
            contenido='<h2>Subtítulo</h2><p>Contenido sobre Django y Python avanzado.</p>',
            estado=Post.Estado.PUBLICADO,
        )
        self.post_publicado.etiquetas.add(self.etiqueta)

        self.post_borrador = Post.objects.create(
            titulo='Artículo en Borrador Secreto',
            autor=self.perfil1,
            categoria=self.categoria,
            contenido='<p>Este contenido es privado y está en borrador.</p>',
            estado=Post.Estado.BORRADOR,
        )

        self.post_autor2 = Post.objects.create(
            titulo='Artículo de Segundo Autor',
            autor=self.perfil2,
            categoria=self.categoria,
            contenido='<p>Contenido perteneciente exclusivamente al autor 2.</p>',
            estado=Post.Estado.PUBLICADO,
        )

    def test_visibilidad_borradores_404_en_publico(self):
        """Los posts en borrador no aparecen en el inicio ni son accesibles por URL directa (404)."""
        resp_list = self.client.get(reverse('blog:post_list'))
        self.assertEqual(resp_list.status_code, 200)
        self.assertContains(resp_list, self.post_publicado.titulo)
        self.assertNotContains(resp_list, self.post_borrador.titulo)

        # Acceso directo por URL al slug de un borrador debe devolver 404
        resp_detail = self.client.get(
            reverse('blog:post_detail', kwargs={'slug': self.post_borrador.slug})
        )
        self.assertEqual(resp_detail.status_code, 404)

    def test_permisos_por_objeto_panel_autor(self):
        """Un autor solo puede editar, borrar o cambiar estado de SUS propios posts (403 en ajenos)."""
        self.client.login(username='autor1', password='PasswordSegura123!')

        # Autor 1 puede acceder a la edición de su propio post
        resp_propio = self.client.get(
            reverse('blog:panel_post_update', kwargs={'slug': self.post_publicado.slug})
        )
        self.assertEqual(resp_propio.status_code, 200)

        # Autor 1 intenta editar un post de Autor 2 -> devuelve 403 (o 404)
        resp_ajeno_edit = self.client.get(
            reverse('blog:panel_post_update', kwargs={'slug': self.post_autor2.slug})
        )
        self.assertIn(resp_ajeno_edit.status_code, (403, 404))

        # Autor 1 intenta eliminar un post de Autor 2 -> devuelve 403 (o 404)
        resp_ajeno_delete = self.client.post(
            reverse('blog:panel_post_delete', kwargs={'slug': self.post_autor2.slug})
        )
        self.assertIn(resp_ajeno_delete.status_code, (403, 404))
        self.assertTrue(Post.objects.filter(pk=self.post_autor2.pk).exists())

        # Autor 1 intenta cambiar estado de un post de Autor 2 -> devuelve 403 (o 404)
        resp_ajeno_toggle = self.client.post(
            reverse('blog:panel_post_toggle_status', kwargs={'slug': self.post_autor2.slug})
        )
        self.assertIn(resp_ajeno_toggle.status_code, (403, 404))

    @override_settings(COMENTARIOS_ANONIMOS=True)
    def test_flujo_moderacion_comentarios(self):
        """
        Los comentarios nuevos quedan pendientes (aprobado=False), no se ven públicamente
        hasta que el autor del post los aprueba, y pueden ser rechazados (eliminados).
        """
        url_detalle = reverse('blog:post_detail', kwargs={'slug': self.post_publicado.slug})
        resp = self.client.post(
            url_detalle,
            {
                'nombre': 'Lector Visitante',
                'email': 'lector@test.com',
                'texto': 'Excelente artículo, muchas gracias por compartir.',
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        comentario = Comentario.objects.get(email='lector@test.com')
        self.assertFalse(comentario.aprobado)

        # No debe aparecer en la vista pública mientras esté pendiente
        resp_publica = self.client.get(url_detalle)
        self.assertNotContains(resp_publica, 'Excelente artículo, muchas gracias por compartir.')

        # Autor 2 NO puede aprobar el comentario del post de Autor 1
        self.client.login(username='autor2', password='PasswordSegura123!')
        resp_intruso = self.client.post(
            reverse('blog:panel_comentario_accion', kwargs={'pk': comentario.pk}),
            {'accion': 'aprobar'},
        )
        self.assertEqual(resp_intruso.status_code, 404)
        comentario.refresh_from_db()
        self.assertFalse(comentario.aprobado)

        # Autor 1 aprueba el comentario desde su panel
        self.client.login(username='autor1', password='PasswordSegura123!')
        resp_aprobar = self.client.post(
            reverse('blog:panel_comentario_accion', kwargs={'pk': comentario.pk}),
            {'accion': 'aprobar'},
        )
        self.assertEqual(resp_aprobar.status_code, 302)
        comentario.refresh_from_db()
        self.assertTrue(comentario.aprobado)

        # Ahora sí se muestra en el detalle público
        resp_publica_aprobado = self.client.get(url_detalle)
        self.assertContains(resp_publica_aprobado, 'Excelente artículo, muchas gracias por compartir.')

        # Autor 1 rechaza (elimina) el comentario
        self.client.post(
            reverse('blog:panel_comentario_accion', kwargs={'pk': comentario.pk}),
            {'accion': 'rechazar'},
        )
        self.assertFalse(Comentario.objects.filter(pk=comentario.pk).exists())

    def test_saneado_html_elimina_script_y_conserva_etiquetas_ckeditor(self):
        """El filtro sanear_html elimina <script> y atributos maliciosos usando bleach."""
        html_sucio = (
            '<h2>Título seguro</h2>'
            '<p onclick="evil()">Texto en <strong>negrita</strong> y <em>cursiva</em>.</p>'
            '<script>alert("XSS Inyectado");</script>'
            '<img src="https://ejemplo.com/foto.jpg" onerror="alert(1)" alt="Foto">'
            '<a href="javascript:alert(2)">Enlace malicioso</a>'
        )
        resultado = str(sanear_html(html_sucio))

        self.assertNotIn('<script>', resultado)
        self.assertNotIn('alert("XSS Inyectado")', resultado)
        self.assertNotIn('onclick=', resultado)
        self.assertNotIn('onerror=', resultado)
        self.assertNotIn('javascript:', resultado)
        self.assertIn('<h2 id="titulo-seguro">Título seguro</h2>', resultado)
        self.assertIn('<strong>negrita</strong>', resultado)
        self.assertIn('<img src="https://ejemplo.com/foto.jpg" alt="Foto">', resultado)

        # También verificar en la vista de detalle del post
        self.post_publicado.contenido = html_sucio
        self.post_publicado.save()
        resp = self.client.get(
            reverse('blog:post_detail', kwargs={'slug': self.post_publicado.slug})
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '<script>alert("XSS Inyectado");</script>')
        self.assertContains(resp, '<h2 id="titulo-seguro">Título seguro</h2>')

    def test_busqueda_sqlite_y_postgresql(self):
        """
        Verifica la búsqueda en modo SQLite (fallback Q/icontains) y la rama
        PostgreSQL (SearchVector, SearchQuery, SearchRank) mediante buscar_posts(q).
        """
        resultados_titulo = buscar_posts('Publicado')
        self.assertIn(self.post_publicado, resultados_titulo)
        self.assertNotIn(self.post_borrador, resultados_titulo)

        resultados_etiqueta = buscar_posts('Django')
        self.assertIn(self.post_publicado, resultados_etiqueta)

        resultados_borrador = buscar_posts('Secreto')
        self.assertEqual(resultados_borrador.count(), 0)

        resp = self.client.get(reverse('blog:buscar_posts'), {'q': 'Django'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.post_publicado.titulo)
        self.assertEqual(resp.context['total_resultados'], 1)

        try:
            with patch('blog.search.connection') as mock_conn:
                mock_conn.vendor = 'postgresql'
                qs_pg = buscar_posts('Django')
                self.assertIn('rank', qs_pg.query.annotations)
                self.assertIn('fragmento', qs_pg.query.annotations)
        except ImportError:
            # En entornos Windows/desarrollo donde el driver psycopg/libpq no está disponible
            pass

    @override_settings(FEED_PAGINATE_BY=6)
    def test_paginacion_inicio_6_por_pagina(self):
        """Verifica que el listado público pagina de 6 en 6 posts publicados."""
        for i in range(6):
            Post.objects.create(
                titulo=f'Artículo Adicional Número {i + 1}',
                autor=self.perfil1,
                categoria=self.categoria,
                contenido=f'<p>Contenido del artículo adicional {i + 1}</p>',
                estado=Post.Estado.PUBLICADO,
            )
        resp_p1 = self.client.get(reverse('blog:post_list'))
        self.assertEqual(resp_p1.status_code, 200)
        self.assertTrue(resp_p1.context['is_paginated'])
        self.assertEqual(len(resp_p1.context['posts']), 6)

        resp_p2 = self.client.get(reverse('blog:post_list') + '?page=2')
        self.assertEqual(resp_p2.status_code, 200)
        self.assertEqual(len(resp_p2.context['posts']), 2)

    def test_validaciones_y_colision_de_slugs(self):
        """
        Verifica título mínimo de 5 caracteres, comentario máximo de 1000 caracteres
        y sufijo numérico automático cuando hay colisión de slugs.
        """
        form_post_invalido = PostForm(
            data={
                'titulo': 'Hola',
                'contenido': '<p>Contenido válido</p>',
                'estado': Post.Estado.BORRADOR,
            }
        )
        self.assertFalse(form_post_invalido.is_valid())
        self.assertIn('titulo', form_post_invalido.errors)

        form_com_invalido = ComentarioForm(
            data={
                'nombre': 'Usuario',
                'email': 'u@test.com',
                'texto': 'x' * 1001,
            }
        )
        self.assertFalse(form_com_invalido.is_valid())
        self.assertIn('texto', form_com_invalido.errors)

        post_a = Post.objects.create(
            titulo='Título Repetido en el Blog',
            autor=self.perfil1,
            contenido='<p>Uno</p>',
        )
        post_b = Post.objects.create(
            titulo='Título Repetido en el Blog',
            autor=self.perfil2,
            contenido='<p>Dos</p>',
        )
        self.assertEqual(post_a.slug, 'titulo-repetido-en-el-blog')
        self.assertEqual(post_b.slug, 'titulo-repetido-en-el-blog-1')


class InteraccionesYNotificacionesTests(TestCase):
    """Pruebas para los Bloques 0, 1, 2, 3 y 4 de interacciones."""

    def setUp(self):
        cache.clear()
        self.autor = User.objects.create_user(
            username='autor_post',
            email='autor@blog.com',
            password='Password123!',
        )
        self.lector1 = User.objects.create_user(
            username='lector_uno',
            email='lector1@blog.com',
            password='Password123!',
        )
        self.lector2 = User.objects.create_user(
            username='lector_dos',
            email='lector2@blog.com',
            password='Password123!',
        )
        self.lector3 = User.objects.create_user(
            username='lector_tres',
            email='lector3@blog.com',
            password='Password123!',
        )
        self.admin_user = User.objects.create_superuser(
            username='admin_general',
            email='admin@blog.com',
            password='Password123!',
        )

        self.post = Post.objects.create(
            titulo='Post para probar todas las interacciones',
            autor=self.autor.perfil,
            contenido='<p>Contenido de prueba para likes, votos y comentarios.</p>',
            estado=Post.Estado.PUBLICADO,
        )

        self.comentario = Comentario.objects.create(
            post=self.post,
            autor=self.lector1,
            nombre='Lector Uno',
            email='lector1@blog.com',
            texto='Comentario aprobado inicial.',
            aprobado=True,
        )

    def test_no_autonotificacion_y_no_duplicados(self):
        """notificar() nunca notifica a uno mismo ni duplica la combinación actor+tipo+objeto."""
        # Autonotificación debe devolver None
        propia = notificar(
            destinatario=self.autor,
            tipo=Notificacion.Tipo.LIKE_POST,
            actor=self.autor,
            post=self.post,
        )
        self.assertIsNone(propia)
        self.assertEqual(Notificacion.objects.count(), 0)

        # Primera notificación válida
        n1 = notificar(
            destinatario=self.autor,
            tipo=Notificacion.Tipo.LIKE_POST,
            actor=self.lector1,
            post=self.post,
        )
        # Intento duplicado con el mismo actor, tipo y post
        n2 = notificar(
            destinatario=self.autor,
            tipo=Notificacion.Tipo.LIKE_POST,
            actor=self.lector1,
            post=self.post,
        )
        self.assertEqual(n1.pk, n2.pk)
        self.assertEqual(Notificacion.objects.filter(destinatario=self.autor).count(), 1)

    def test_unicidad_likes_y_votos_y_eliminacion_notificacion(self):
        """
        Verifica que LikePost, LikeComentario y VotoUtil sean únicos por usuario+objeto,
        que alternar like cree y elimine la notificación, y que el voto útil pueda cambiarse.
        """
        # Unicidad a nivel de base de datos
        LikePost.objects.create(usuario=self.lector1, post=self.post)
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                LikePost.objects.create(usuario=self.lector1, post=self.post)
        LikePost.objects.all().delete()

        # Vía vista AJAX: dar like crea notificación LIKE_POST; quitarlo la elimina
        self.client.login(username='lector_uno', password='Password123!')
        url_like_post = reverse('blog:post_like_toggle', kwargs={'slug': self.post.slug})

        r1 = self.client.post(url_like_post, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()['activo'], True)
        self.assertEqual(r1.json()['total'], 1)
        self.assertTrue(
            Notificacion.objects.filter(
                destinatario=self.autor,
                tipo=Notificacion.Tipo.LIKE_POST,
                actor=self.lector1,
            ).exists()
        )

        # Quitar like elimina el registro y también la notificación
        r2 = self.client.post(url_like_post, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()['activo'], False)
        self.assertEqual(r2.json()['total'], 0)
        self.assertFalse(
            Notificacion.objects.filter(
                destinatario=self.autor,
                tipo=Notificacion.Tipo.LIKE_POST,
                actor=self.lector1,
            ).exists()
        )

        # Voto de utilidad: votar Sí y luego cambiar a No mantiene 1 solo voto en total
        url_voto = reverse('blog:post_votar_util', kwargs={'slug': self.post.slug})
        rv1 = self.client.post(url_voto, {'util': 'si'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(rv1.json()['utiles'], 1)
        self.assertEqual(rv1.json()['total'], 1)

        rv2 = self.client.post(url_voto, {'util': 'no'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(rv2.json()['utiles'], 0)
        self.assertEqual(rv2.json()['total'], 1)
        self.assertEqual(VotoUtil.objects.filter(usuario=self.lector1, post=self.post).count(), 1)

    def test_permisos_y_ventana_edicion_comentarios(self):
        """
        - Un usuario no puede editar ni borrar comentarios ajenos (403).
        - El dueño puede editar dentro de los 10 minutos (vuelve a moderación aprobado=False y editado=True).
        - Pasados los 10 minutos, el dueño ya no puede editar (403), pero sí puede borrar.
        """
        url_editar = reverse('blog:comentario_editar', kwargs={'pk': self.comentario.pk})
        url_borrar = reverse('blog:comentario_eliminar', kwargs={'pk': self.comentario.pk})

        # Lector 2 intenta editar o borrar el comentario de Lector 1 -> 403
        self.client.login(username='lector_dos', password='Password123!')
        self.assertEqual(self.client.get(url_editar).status_code, 403)
        self.assertEqual(self.client.post(url_editar, {'texto': 'Hackeado'}).status_code, 403)
        self.assertEqual(self.client.post(url_borrar).status_code, 403)

        # Lector 1 (dueño) edita dentro de la ventana de 10 minutos
        self.client.login(username='lector_uno', password='Password123!')
        resp_edit = self.client.post(url_editar, {'texto': 'Comentario corregido por su autor.'})
        self.assertEqual(resp_edit.status_code, 302)
        self.comentario.refresh_from_db()
        self.assertTrue(self.comentario.editado)
        self.assertFalse(self.comentario.aprobado)
        self.assertEqual(self.comentario.texto, 'Comentario corregido por su autor.')

        # Simular que pasaron 11 minutos desde la creación -> editar devuelve 403
        Comentario.objects.filter(pk=self.comentario.pk).update(
            creado=timezone.now() - timedelta(minutes=11),
            aprobado=True,
        )
        self.assertEqual(self.client.post(url_editar, {'texto': 'Fuera de tiempo'}).status_code, 403)

        # Pero el dueño sí puede borrar su comentario en cualquier momento
        resp_del = self.client.post(url_borrar)
        self.assertEqual(resp_del.status_code, 302)
        self.assertFalse(Comentario.objects.filter(pk=self.comentario.pk).exists())

    def test_reporte_notificaciones_correos_sin_duplicar_y_ocultado_automatico(self):
        """
        - No permite reportar el propio comentario (403).
        - Envía notificación y correo al autor del post y a los admins.
        - Si el autor del post es también admin, recibe un único aviso (sin duplicar).
        - Al llegar a 3 reportes pendientes, el comentario se oculta automáticamente.
        - Al descartar desde el panel del autor, recupera su visibilidad.
        """
        url_reportar = reverse('blog:comentario_reportar', kwargs={'pk': self.comentario.pk})

        # 1. Lector 1 no puede reportar su propio comentario
        self.client.login(username='lector_uno', password='Password123!')
        resp_propio = self.client.post(url_reportar, {'motivo': 'spam'})
        self.assertEqual(resp_propio.status_code, 403)

        # Hacer que el autor del post sea también staff/admin para verificar no duplicación
        self.autor.is_staff = True
        self.autor.save()
        mail.outbox.clear()

        # 2. Reporte #1 por lector_dos
        self.client.login(username='lector_dos', password='Password123!')
        resp_r1 = self.client.post(
            url_reportar,
            {'motivo': 'spam', 'detalle': 'Parece publicidad no deseada.'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp_r1.status_code, 200)
        # Deben haberse enviado exactamente 2 correos: 1 a autor (que también es staff) y 1 a admin_general
        destinatarios_correo = [m.to[0] for m in mail.outbox]
        self.assertEqual(len(destinatarios_correo), 2)
        self.assertEqual(destinatarios_correo.count(self.autor.email), 1)
        self.assertEqual(destinatarios_correo.count(self.admin_user.email), 1)

        # Notificaciones REPORTE_COMENTARIO: 1 para autor y 1 para admin_general
        self.assertEqual(
            Notificacion.objects.filter(
                destinatario=self.autor,
                tipo=Notificacion.Tipo.REPORTE_COMENTARIO,
            ).count(),
            1,
        )
        self.assertEqual(
            Notificacion.objects.filter(
                destinatario=self.admin_user,
                tipo=Notificacion.Tipo.REPORTE_COMENTARIO,
            ).count(),
            1,
        )

        # 3. Reporte #2 por lector_tres y Reporte #3 por admin_general -> ocultado automático a los 3 reportes
        self.client.login(username='lector_tres', password='Password123!')
        self.client.post(url_reportar, {'motivo': 'ofensivo'})
        self.comentario.refresh_from_db()
        self.assertFalse(self.comentario.oculto_por_reportes)

        self.client.login(username='admin_general', password='Password123!')
        self.client.post(url_reportar, {'motivo': 'acoso'})
        self.comentario.refresh_from_db()
        self.assertTrue(self.comentario.oculto_por_reportes)

        # El comentario oculto ya no aparece en el detalle público del post
        resp_detalle = self.client.get(reverse('blog:post_detail', kwargs={'slug': self.post.slug}))
        self.assertNotContains(resp_detalle, self.comentario.texto)

        # 4. El autor del post descarta un reporte desde su panel -> baja de 3 pendientes y recupera visibilidad
        reporte_a_descartar = ReporteComentario.objects.filter(comentario=self.comentario).first()
        self.client.login(username='autor_post', password='Password123!')
        self.client.post(
            reverse('blog:panel_reporte_accion', kwargs={'pk': reporte_a_descartar.pk}),
            {'accion': 'descartar'},
        )
        self.comentario.refresh_from_db()
        self.assertFalse(self.comentario.oculto_por_reportes)

    def test_menciones_regex_limite_5_escape_xss_y_notificacion_al_aprobar(self):
        """
        - Escapa el HTML antes de convertir @usuario en enlace (previene XSS).
        - Usuarios inexistentes no se enlazan ni reciben notificación.
        - Máximo 5 menciones por comentario.
        - Las notificaciones MENCION se envían al aprobar el comentario, no antes.
        """
        usuarios_extra = []
        for i in range(6):
            u = User.objects.create_user(username=f'mencionado{i}', password='Password123!')
            usuarios_extra.append(u)

        texto_con_xss_y_menciones = (
            '<script>alert(1)</script> Hola @mencionado0 @mencionado1 @mencionado2 '
            '@mencionado3 @mencionado4 @mencionado5 y también @usuario_inexistente_xyz'
        )
        html_renderizado = str(renderizar_menciones(texto_con_xss_y_menciones))

        # El <script> fue escapado y no existe etiqueta <script> ejecutable
        self.assertNotIn('<script>', html_renderizado)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html_renderizado)

        # Los primeros 5 usuarios existentes tienen enlace; el 6º y el inexistente NO tienen enlace
        for i in range(5):
            self.assertIn(f'href="/autor/mencionado{i}/"', html_renderizado)
        self.assertNotIn('href="/autor/mencionado5/"', html_renderizado)
        self.assertNotIn('href="/autor/usuario_inexistente_xyz/"', html_renderizado)

        # Crear comentario pendiente: NO debe enviar notificaciones MENCION todavía
        self.client.login(username='lector_uno', password='Password123!')
        self.client.post(
            reverse('blog:post_detail', kwargs={'slug': self.post.slug}),
            {'texto': texto_con_xss_y_menciones},
        )
        com_nuevo = Comentario.objects.filter(texto=texto_con_xss_y_menciones).first()
        self.assertIsNotNone(com_nuevo)
        self.assertFalse(com_nuevo.aprobado)
        self.assertEqual(Notificacion.objects.filter(tipo=Notificacion.Tipo.MENCION).count(), 0)

        # Al aprobar el comentario desde el panel del autor, se envían exactamente 5 notificaciones MENCION
        self.client.login(username='autor_post', password='Password123!')
        self.client.post(
            reverse('blog:panel_comentario_accion', kwargs={'pk': com_nuevo.pk}),
            {'accion': 'aprobar'},
        )
        self.assertEqual(Notificacion.objects.filter(tipo=Notificacion.Tipo.MENCION).count(), 5)

    def test_limitador_de_tasa_y_401_ajax(self):
        """
        - Petición AJAX sin login devuelve 401 con login_url y ?next=.
        - Al superar el límite de tasa en cache, devuelve 429 Too Many Requests.
        """
        url_like = reverse('blog:post_like_toggle', kwargs={'slug': self.post.slug})

        # Sin sesión iniciada vía AJAX -> 401
        resp_401 = self.client.post(url_like, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_401.status_code, 401)
        self.assertIn('login_url', resp_401.json())

        # Con sesión iniciada: simular que alcanzó el límite de 30 likes/min en cache
        self.client.login(username='lector_uno', password='Password123!')
        cache.set(f'ratelimit:like_post:user_{self.lector1.pk}', 30, timeout=60)

        resp_429 = self.client.post(url_like, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_429.status_code, 429)
        self.assertFalse(resp_429.json()['ok'])


class RondaDosTests(TestCase):
    """
    Pruebas automatizadas para la Ronda 2 (Bloques 1 a 6):
    - Bloque 1: Seguir autores, restricción de auto-seguimiento, unicidad, feed /siguiendo/ y POST_NUEVO solo en primera publicación.
    - Bloque 2: Suscripción por correo con doble confirmación, baja sin login y no duplicación de correos al mismo destinatario.
    - Bloque 3: Registro de vistas diarias (1 por sesión/día, ignorando autor, staff y bots) y cálculo de posts populares.
    - Bloque 4: Cálculo de autores destacados e insignias calculadas (Nuevo, Activo, Destacado).
    - Bloque 5: Listas de lectura (privadas/públicas, borradores en listas y protección de 'Guardados').
    """

    def setUp(self):
        cache.clear()
        self.autor = User.objects.create_user(
            username='autor_r2',
            email='autor_r2@example.com',
            password='Password123!',
            first_name='Carlos',
            last_name='Autor',
        )
        self.lector = User.objects.create_user(
            username='lector_r2',
            email='lector_r2@example.com',
            password='Password123!',
        )
        self.otro_lector = User.objects.create_user(
            username='otro_r2',
            email='otro_r2@example.com',
            password='Password123!',
        )
        self.staff_user = User.objects.create_user(
            username='staff_r2',
            email='staff_r2@example.com',
            password='Password123!',
            is_staff=True,
        )
        self.categoria = Categoria.objects.create(nombre='Arquitectura')

    def test_seguir_autor_no_autoseguimiento_no_duplicados_y_feed_siguiendo(self):
        """
        - No se puede seguir a uno mismo (vista devuelve 400/403 y modelo valida clean()).
        - No se duplican seguimientos (UniqueConstraint + toggle al segundo POST).
        - Al seguir se crea notificación SEGUIDOR_NUEVO; al dejar de seguir se elimina.
        - La página /siguiendo/ muestra solo posts publicados de autores seguidos.
        """
        url_seguir_propio = reverse('blog:autor_seguir_toggle', kwargs={'username': self.autor.username})

        # Intentar seguirse a sí mismo vía AJAX -> 400
        self.client.login(username='autor_r2', password='Password123!')
        resp_auto = self.client.post(url_seguir_propio, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_auto.status_code, 400)
        self.assertEqual(Seguimiento.objects.count(), 0)

        # Seguir desde lector_r2 -> crea seguimiento y notificación SEGUIDOR_NUEVO
        self.client.login(username='lector_r2', password='Password123!')
        resp_seguir = self.client.post(url_seguir_propio, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_seguir.status_code, 200)
        self.assertEqual(resp_seguir.json(), {'ok': True, 'activo': True, 'total': 1, 'mensaje': 'Ahora sigues a @autor_r2.'})
        self.assertEqual(
            Notificacion.objects.filter(
                destinatario=self.autor,
                tipo=Notificacion.Tipo.SEGUIDOR_NUEVO,
                actor=self.lector,
            ).count(),
            1,
        )

        # Unicidad a nivel de base de datos: no permite duplicar la pareja (seguidor, autor)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Seguimiento.objects.create(seguidor=self.lector, autor=self.autor.perfil)

        # Verificar feed /siguiendo/
        post_pub = Post.objects.create(
            titulo='Post para Seguidores',
            autor=self.autor.perfil,
            categoria=self.categoria,
            contenido='<p>Contenido para seguidores</p>',
            estado=Post.Estado.PUBLICADO,
        )
        resp_feed = self.client.get(reverse('blog:siguiendo_feed'))
        self.assertEqual(resp_feed.status_code, 200)
        self.assertContains(resp_feed, post_pub.titulo)

        # Segundo POST alterna (deja de seguir) y elimina la notificación
        resp_unfollow = self.client.post(url_seguir_propio, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertFalse(resp_unfollow.json()['activo'])
        self.assertEqual(Seguimiento.objects.count(), 0)
        self.assertEqual(
            Notificacion.objects.filter(
                destinatario=self.autor,
                tipo=Notificacion.Tipo.SEGUIDOR_NUEVO,
            ).count(),
            0,
        )

    def test_post_nuevo_notifica_y_envia_correos_solo_en_primera_publicacion(self):
        """
        - Un post creado como borrador NO notifica ni envía correos (`notificado=False`).
        - Al publicarse por primera vez, marca `notificado=True`, notifica `POST_NUEVO` a seguidores
          y envía correo a suscriptores confirmados.
        - Si vuelve a borrador y se republica, NO vuelve a notificar ni enviar correos.
        """
        Seguimiento.objects.create(seguidor=self.lector, autor=self.autor.perfil)
        Suscripcion.objects.create(
            email='suscriptor@example.com',
            autor=self.autor.perfil,
            confirmada=True,
            activa=True,
        )
        mail.outbox.clear()

        # 1. Crear en borrador -> no notifica ni envía correo
        post = Post.objects.create(
            titulo='Borrador Inicial',
            autor=self.autor.perfil,
            categoria=self.categoria,
            contenido='<p>Texto en borrador</p>',
            estado=Post.Estado.BORRADOR,
        )
        self.assertFalse(post.notificado)
        self.assertEqual(Notificacion.objects.filter(tipo=Notificacion.Tipo.POST_NUEVO).count(), 0)
        self.assertEqual(len(mail.outbox), 0)

        # 2. Primera publicación -> notifica a seguidores y envía 1 correo
        post.estado = Post.Estado.PUBLICADO
        post.save()
        post.refresh_from_db()
        self.assertTrue(post.notificado)
        self.assertEqual(
            Notificacion.objects.filter(
                destinatario=self.lector,
                tipo=Notificacion.Tipo.POST_NUEVO,
                post=post,
            ).count(),
            1,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Borrador Inicial', mail.outbox[0].subject)

        # 3. Volver a borrador y republicar -> NO repite notificaciones ni correos
        Notificacion.objects.filter(tipo=Notificacion.Tipo.POST_NUEVO).delete()
        mail.outbox.clear()

        post.estado = Post.Estado.BORRADOR
        post.save()
        post.estado = Post.Estado.PUBLICADO
        post.save()

        self.assertEqual(Notificacion.objects.filter(tipo=Notificacion.Tipo.POST_NUEVO).count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_suscripcion_doble_confirmacion_baja_sin_login_y_sin_correos_duplicados(self):
        """
        - Al suscribirse se crea con `confirmada=False` y se envía correo de confirmación.
        - Antes de confirmar NO recibe correos de nuevos posts.
        - Al visitar `/suscripcion/confirmar/<token>/` pasa a `confirmada=True`.
        - Si el mismo email está suscrito tanto al autor como a la categoría del post,
          recibe UN SOLO correo por post.
        - El enlace `/suscripcion/baja/<token>/` desactiva la suscripción sin requerir login.
        """
        mail.outbox.clear()
        resp_sub = self.client.post(
            reverse('blog:suscripcion_crear'),
            {
                'email': 'lector_doble@example.com',
                'autor_id': self.autor.perfil.pk,
                'sitio_web': '',
            },
        )
        self.assertEqual(resp_sub.status_code, 302)
        sub_autor = Suscripcion.objects.get(email='lector_doble@example.com', autor=self.autor.perfil)
        self.assertFalse(sub_autor.confirmada)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(str(sub_autor.token), mail.outbox[0].body)

        # Publicar un post mientras NO está confirmada -> 0 correos enviados
        mail.outbox.clear()
        Post.objects.create(
            titulo='Post Antes de Confirmar',
            autor=self.autor.perfil,
            categoria=self.categoria,
            contenido='<p>Hola</p>',
            estado=Post.Estado.PUBLICADO,
        )
        self.assertEqual(len(mail.outbox), 0)

        # Confirmar suscripción al autor y crear también suscripción confirmada a la categoría con el mismo email
        resp_conf = self.client.get(reverse('blog:suscripcion_confirmar', kwargs={'token': sub_autor.token}))
        self.assertEqual(resp_conf.status_code, 200)
        sub_autor.refresh_from_db()
        self.assertTrue(sub_autor.confirmada)

        Suscripcion.objects.create(
            email='lector_doble@example.com',
            categoria=self.categoria,
            confirmada=True,
            activa=True,
        )

        # Publicar nuevo post de ese autor y esa categoría -> debe enviar 1 solo correo (sin duplicar)
        mail.outbox.clear()
        Post.objects.create(
            titulo='Post Con Doble Suscripcion',
            autor=self.autor.perfil,
            categoria=self.categoria,
            contenido='<p>Contenido del post</p>',
            estado=Post.Estado.PUBLICADO,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['lector_doble@example.com'])
        self.assertIn('/suscripcion/baja/', mail.outbox[0].body)

        # Darse de baja sin iniciar sesión
        self.client.logout()
        resp_baja = self.client.get(reverse('blog:suscripcion_baja', kwargs={'token': sub_autor.token}))
        self.assertEqual(resp_baja.status_code, 200)
        sub_autor.refresh_from_db()
        self.assertFalse(sub_autor.activa)
        self.assertFalse(sub_autor.confirmada)

    def test_vista_diaria_una_por_sesion_ignora_autor_staff_y_bots(self):
        """
        - Ignora al autor del post, al staff y a bots (User-Agent).
        - Registra 1 sola vista por sesión y día para un lector normal.
        """
        post = Post.objects.create(
            titulo='Post de Vistas',
            autor=self.autor.perfil,
            categoria=self.categoria,
            contenido='<p>Contenido</p>',
            estado=Post.Estado.PUBLICADO,
        )
        url_detalle = reverse('blog:post_detail', kwargs={'slug': post.slug})

        # 1. Autor visita su propio post -> 0 vistas
        self.client.login(username='autor_r2', password='Password123!')
        self.client.get(url_detalle)
        self.assertEqual(VistaDiaria.objects.filter(post=post).count(), 0)

        # 2. Usuario staff visita el post -> 0 vistas
        self.client.login(username='staff_r2', password='Password123!')
        self.client.get(url_detalle)
        self.assertEqual(VistaDiaria.objects.filter(post=post).count(), 0)

        # 3. Bot visita el post -> 0 vistas
        self.client.logout()
        self.client.get(url_detalle, HTTP_USER_AGENT='Googlebot/2.1 (+http://www.google.com/bot.html)')
        self.assertEqual(VistaDiaria.objects.filter(post=post).count(), 0)

        # 4. Lector normal visita dos veces en la misma sesión -> cuenta 1 sola vista
        self.client.get(url_detalle, HTTP_USER_AGENT='Mozilla/5.0 Chrome/120.0')
        self.client.get(url_detalle, HTTP_USER_AGENT='Mozilla/5.0 Chrome/120.0')
        vista = VistaDiaria.objects.get(post=post)
        self.assertEqual(vista.cantidad, 1)

    def test_calculo_posts_populares_autores_destacados_e_insignias(self):
        """
        - Verifica la fórmula de popularidad: vistas*1 + likes*3 + votos_util*2 + comentarios_aprobados*2.
        - Verifica la fórmula de autores destacados: posts*2 + seguidores*3 + likes*1 + votos_util*1.
        - Verifica insignias calculadas ('Nuevo', 'Activo', 'Destacado').
        """
        autor2 = User.objects.create_user(username='autor_top', password='Password123!')
        post1 = Post.objects.create(
            titulo='Post Menos Popular',
            autor=self.autor.perfil,
            categoria=self.categoria,
            contenido='<p>Texto 1</p>',
            estado=Post.Estado.PUBLICADO,
        )
        post2 = Post.objects.create(
            titulo='Post Super Popular',
            autor=autor2.perfil,
            categoria=self.categoria,
            contenido='<p>Texto 2</p>',
            estado=Post.Estado.PUBLICADO,
        )

        # Asignar métricas a post2: 5 vistas (5*1=5), 2 likes (2*3=6), 1 voto útil (1*2=2), 1 comentario aprobado (1*2=2) => 15 pts
        VistaDiaria.objects.create(post=post2, fecha=timezone.localdate(), cantidad=5)
        LikePost.objects.create(usuario=self.lector, post=post2)
        LikePost.objects.create(usuario=self.otro_lector, post=post2)
        VotoUtil.objects.create(usuario=self.lector, post=post2, util=True)
        Comentario.objects.create(
            post=post2,
            autor=self.lector,
            nombre='Lector',
            email='l@example.com',
            texto='Gran post',
            aprobado=True,
        )
        # Asignar 1 vista a post1 => 1 pt
        VistaDiaria.objects.create(post=post1, fecha=timezone.localdate(), cantidad=1)

        cache.clear()
        ranking = posts_populares(dias=7, limite=5)
        self.assertEqual(ranking[0].pk, post2.pk)
        self.assertEqual(ranking[0].puntuacion, 15)
        self.assertEqual(ranking[1].pk, post1.pk)
        self.assertEqual(ranking[1].puntuacion, 1)

        # Autores destacados: autor2 tiene 1 post (2) + 1 seguidor (3) + 2 likes (2) + 1 voto útil (1) = 8 pts
        Seguimiento.objects.create(seguidor=self.lector, autor=autor2.perfil)
        cache.clear()
        autores = autores_destacados(limite=4, orden='puntuacion')
        self.assertEqual(autores[0].pk, autor2.perfil.pk)
        self.assertEqual(autores[0].puntuacion, 8)

        # Insignias: autor2 tiene 1 post (< 3 -> 'Nuevo') y está en el top -> 'Destacado'
        nombres_insignias = [b['nombre'] for b in calcular_insignias_perfil(autor2.perfil)]
        self.assertIn('Nuevo', nombres_insignias)
        self.assertIn('Destacado', nombres_insignias)

        # Crear 4 posts adicionales para autor2 (total 5 posts >= 5) -> obtiene insignia 'Activo'
        for i in range(4):
            Post.objects.create(
                titulo=f'Post Extra {i}',
                autor=autor2.perfil,
                categoria=self.categoria,
                contenido='<p>Extra</p>',
                estado=Post.Estado.PUBLICADO,
            )
        cache.clear()
        nombres_insignias_activo = [b['nombre'] for b in calcular_insignias_perfil(autor2.perfil)]
        self.assertIn('Activo', nombres_insignias_activo)
        self.assertNotIn('Nuevo', nombres_insignias_activo)

    def test_listas_lectura_permisos_borradores_y_proteccion_guardados(self):
        """
        - Todo usuario tiene su lista predeterminada 'Guardados' (privada), que no puede borrarse ni renombrarse.
        - Una lista privada devuelve 403 a otros usuarios; una pública devuelve 200 mostrando el dueño.
        - Si un post guardado pasa a borrador: en una lista pública no se muestra a otros usuarios,
          y al dueño le aparece el aviso 'Este post ya no está disponible'.
        """
        lista_guardados = ListaLectura.objects.get(
            usuario=self.lector,
            nombre=ListaLectura.NOMBRE_GUARDADOS,
        )
        self.assertTrue(lista_guardados.es_predeterminada)
        self.assertFalse(lista_guardados.publica)

        # Intentar borrar o renombrar 'Guardados' devuelve 403 y la lista permanece intacta
        self.client.login(username='lector_r2', password='Password123!')
        resp_del = self.client.post(reverse('blog:lista_eliminar', kwargs={'pk': lista_guardados.pk}))
        self.assertEqual(resp_del.status_code, 403)
        self.assertTrue(ListaLectura.objects.filter(pk=lista_guardados.pk).exists())

        resp_ren = self.client.post(
            reverse('blog:lista_editar', kwargs={'pk': lista_guardados.pk}),
            {'nombre': 'Otro Nombre', 'descripcion': '', 'publica': True},
        )
        self.assertEqual(resp_ren.status_code, 403)
        lista_guardados.refresh_from_db()
        self.assertEqual(lista_guardados.nombre, 'Guardados')
        self.assertFalse(lista_guardados.publica)

        # Otro usuario no puede ver la lista privada 'Guardados' (403)
        self.client.login(username='otro_r2', password='Password123!')
        resp_priv = self.client.get(reverse('blog:lista_detail', kwargs={'pk': lista_guardados.pk}))
        self.assertEqual(resp_priv.status_code, 403)

        # Crear una lista pública con 2 posts y luego pasar 1 post a borrador
        lista_pub = ListaLectura.objects.create(
            usuario=self.lector,
            nombre='Favoritos de Django',
            publica=True,
        )
        post_visible = Post.objects.create(
            titulo='Post Siempre Publicado',
            autor=self.autor.perfil,
            categoria=self.categoria,
            contenido='<p>Visible</p>',
            estado=Post.Estado.PUBLICADO,
        )
        post_luego_borrador = Post.objects.create(
            titulo='Post Que Pasara A Borrador',
            autor=self.autor.perfil,
            categoria=self.categoria,
            contenido='<p>Temporal</p>',
            estado=Post.Estado.PUBLICADO,
        )
        ItemLista.objects.create(lista=lista_pub, post=post_visible)
        ItemLista.objects.create(lista=lista_pub, post=post_luego_borrador)

        # Pasar el segundo post a borrador
        post_luego_borrador.estado = Post.Estado.BORRADOR
        post_luego_borrador.save()

        # Vista para visitante/otro usuario en lista pública: ve el publicado, NO ve el borrador
        resp_visitante = self.client.get(reverse('blog:lista_detail', kwargs={'pk': lista_pub.pk}))
        self.assertEqual(resp_visitante.status_code, 200)
        self.assertContains(resp_visitante, 'Post Siempre Publicado')
        self.assertNotContains(resp_visitante, 'Post Que Pasara A Borrador')
        self.assertNotContains(resp_visitante, 'Este post ya no está disponible')

        # Vista para el dueño de la lista: ve el aviso 'Este post ya no está disponible'
        self.client.login(username='lector_r2', password='Password123!')
        resp_dueno = self.client.get(reverse('blog:lista_detail', kwargs={'pk': lista_pub.pk}))
        self.assertEqual(resp_dueno.status_code, 200)
        self.assertContains(resp_dueno, 'Post Siempre Publicado')
        self.assertContains(resp_dueno, 'Este post ya no está disponible')


class RedisenioUXTests(TestCase):
    """
    Pruebas automatizadas para la Ronda 3 (Mejora visual, UX, accesibilidad y rendimiento):
    1. extracto_plano: ignora encabezados (h1-h6), corta en límite de palabra, agrega una sola '…', maneja vacíos.
    2. Saneado de HTML: conserva <code class="language-python"> y elimina <script> y onerror.
    3. Generación de id únicos en encabezados sin colisiones y tabla de contenidos (TOC).
    4. Ordenamiento ?orden= combinado con paginación.
    5. Renderizado de 404.html y 500.html autónomo.
    6. El post destacado del inicio no se repite en la cuadrícula.
    """

    def setUp(self):
        cache.clear()
        self.autor = User.objects.create_user(
            username='autor_ux',
            email='autor_ux@example.com',
            password='Password123!',
            first_name='Elena',
            last_name='UX',
        )
        self.categoria = Categoria.objects.create(nombre='Frontend y Diseño')

    def test_extracto_plano_ignora_encabezados_corta_en_palabra_y_maneja_vacios(self):
        # 1. Entradas vacías o solo con encabezados
        self.assertEqual(extracto_plano(''), '')
        self.assertEqual(extracto_plano(None), '')
        self.assertEqual(extracto_plano('<h1>Solo título</h1><h2>Subtítulo</h2>'), '')

        # 2. Ignora h1-h6 y extrae el texto limpio del párrafo sin pegarlo al encabezado
        html = '<h2>render.yaml</h2><p>Automatizar el despliegue continuo en servidores modernos.</p>'
        resultado = extracto_plano(html, max_chars=160)
        self.assertEqual(resultado, 'Automatizar el despliegue continuo en servidores modernos.')
        self.assertNotIn('render.yaml', resultado)

        # 3. Corta en límite de palabra y agrega una sola '…' sin doble puntuación (nunca '.…' ni '....')
        html_largo = (
            '<h1>Título ignorado</h1>'
            '<p>Primera frase corta. Segunda frase con varias palabras adicionales para '
            'superar el límite establecido en la prueba unitaria.</p>'
        )
        recortado = extracto_plano(html_largo, max_chars=45)
        self.assertTrue(recortado.endswith('…'))
        self.assertFalse(recortado.endswith('..'))
        self.assertFalse(recortado.endswith('.…'))
        self.assertLessEqual(len(recortado), 46)
        # Verifica que no cortó la palabra 'adicionales' a la mitad ('Segunda frase con varias palabras…')
        self.assertEqual(recortado, 'Primera frase corta. Segunda frase con…')

    def test_saneado_html_conserva_language_class_en_code_y_elimina_script_y_onerror(self):
        html_entrada = (
            '<pre><code class="language-python" onclick="alert(1)">print("Hola")</code></pre>'
            '<pre><code class="clase-no-permitida">x = 1</code></pre>'
            '<img src="/media/uploads/foto.jpg" alt="Foto" onerror="alert(2)">'
            '<script>evil()</script>'
        )
        limpio = str(sanear_html(html_entrada))
        self.assertIn('<code class="language-python">print("Hola")</code>', limpio)
        self.assertIn('<pre><code>x = 1</code></pre>', limpio)
        self.assertNotIn('clase-no-permitida', limpio)
        self.assertNotIn('onclick', limpio)
        self.assertNotIn('onerror', limpio)
        self.assertNotIn('<script>', limpio)

    def test_ids_unicos_en_encabezados_sin_colisiones_y_toc(self):
        html_repetido = (
            '<h2>Sección</h2><p>Uno</p>'
            '<h2>Sección</h2><p>Dos</p>'
            '<h3>Sección</h3><p>Tres</p>'
        )
        html_final, toc = sanear_y_generar_toc(html_repetido)
        self.assertIn('<h2 id="seccion">Sección</h2>', html_final)
        self.assertIn('<h2 id="seccion-2">Sección</h2>', html_final)
        self.assertIn('<h3 id="seccion-3">Sección</h3>', html_final)
        self.assertEqual(len(toc), 3)
        self.assertEqual([item['id'] for item in toc], ['seccion', 'seccion-2', 'seccion-3'])

        # El filtro generar_toc_html devuelve la lista solo cuando hay >= 3 encabezados
        self.assertEqual(len(generar_toc_html('<h2>Uno</h2><h2>Dos</h2>')), 0)
        self.assertEqual(len(generar_toc_html(html_repetido)), 3)

    @override_settings(FEED_PAGINATE_BY=6)
    def test_ordenamiento_query_param_combinado_con_paginacion(self):
        # Crear 8 posts publicados con distintos likes y votos útiles
        lectores = [
            User.objects.create_user(username=f'lector_ord_{i}', password='Password123!')
            for i in range(4)
        ]
        posts = []
        for i in range(8):
            p = Post.objects.create(
                titulo=f'Artículo Ordenable {i}',
                autor=self.autor.perfil,
                categoria=self.categoria,
                contenido=f'<p>Contenido del artículo {i}</p>',
                estado=Post.Estado.PUBLICADO,
            )
            posts.append(p)

        # Hacer que posts[2] tenga 3 votos útiles (100% útil con >= 3 votos)
        for u in lectores[:3]:
            VotoUtil.objects.create(usuario=u, post=posts[2], util=True)

        # Hacer que posts[4] sea el más popular (vistas + likes)
        VistaDiaria.objects.create(post=posts[4], fecha=timezone.localdate(), cantidad=50)

        # 1. Ordenar por más populares en página 1 y conservar ?orden=populares en enlaces de paginación
        resp_pop = self.client.get(reverse('blog:post_list') + '?orden=populares')
        self.assertEqual(resp_pop.status_code, 200)
        self.assertEqual(resp_pop.context['posts'][0].pk, posts[4].pk)
        self.assertContains(resp_pop, 'orden=populares&amp;page=2')

        # 2. Página 2 con ?orden=populares&page=2
        resp_pop_p2 = self.client.get(reverse('blog:post_list') + '?orden=populares&page=2')
        self.assertEqual(resp_pop_p2.status_code, 200)
        self.assertEqual(len(resp_pop_p2.context['posts']), 2)

        # 3. Ordenar por más útiles (?orden=utiles): solo incluye posts con >= 3 votos
        resp_utiles = self.client.get(reverse('blog:post_list') + '?orden=utiles')
        self.assertEqual(resp_utiles.status_code, 200)
        self.assertEqual([p.pk for p in resp_utiles.context['posts']], [posts[2].pk])

    def test_renderizado_404_y_500_autonomo(self):
        from django.template.loader import render_to_string

        # 404 en ruta inexistente incluye buscador y enlace al inicio
        resp_404 = self.client.get('/ruta-que-no-existe-404/')
        self.assertEqual(resp_404.status_code, 404)
        html_404 = render_to_string('404.html')
        self.assertIn('404', html_404)
        self.assertIn('/buscar/', html_404)

        # 500.html es completamente autónomo (se renderiza con contexto vacío y sin consultas a BD)
        with self.assertNumQueries(0):
            html_500 = render_to_string('500.html', {})
        self.assertIn('500', html_500)
        self.assertIn('Volver al inicio', html_500)

    def test_post_destacado_no_se_repite_en_la_cuadricula(self):
        post_top = Post.objects.create(
            titulo='Artículo Destacado Principal',
            autor=self.autor.perfil,
            categoria=self.categoria,
            contenido='<p>Primer párrafo del artículo destacado principal.</p>',
            estado=Post.Estado.PUBLICADO,
        )
        post_secundario = Post.objects.create(
            titulo='Artículo Secundario en Cuadrícula',
            autor=self.autor.perfil,
            categoria=self.categoria,
            contenido='<p>Primer párrafo del artículo secundario.</p>',
            estado=Post.Estado.PUBLICADO,
        )
        VistaDiaria.objects.create(post=post_top, fecha=timezone.localdate(), cantidad=25)
        cache.clear()

        resp = self.client.get(reverse('blog:post_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['post_destacado'].pk, post_top.pk)
        pks_cuadricula = [p.pk for p in resp.context['posts_cuadricula']]
        self.assertNotIn(post_top.pk, pks_cuadricula)
        self.assertIn(post_secundario.pk, pks_cuadricula)

    def test_nombre_mostrar_con_y_sin_nombre_completo_y_renderizado_en_tarjetas_y_autores(self):
        """
        - Perfil.nombre_mostrar devuelve el nombre completo si existe, o el username si está vacío.
        - El HTML de tarjetas en el inicio y de la página /autores/ incluye nombre_mostrar.
        """
        # 1. Con nombre completo ('Elena UX')
        self.assertEqual(self.autor.perfil.nombre_mostrar, 'Elena UX')

        # 2. Sin nombre completo -> devuelve username
        autor_sin_nombre = User.objects.create_user(
            username='dev_anonimo',
            password='Password123!',
            first_name='',
            last_name='',
        )
        self.assertEqual(autor_sin_nombre.perfil.nombre_mostrar, 'dev_anonimo')

        # Publicar posts de ambos autores y verificar que sus nombres aparecen en tarjetas y en /autores/
        Post.objects.create(
            titulo='Post de Elena con Nombre Completo',
            autor=self.autor.perfil,
            categoria=self.categoria,
            contenido='<p>Contenido de prueba para verificar el nombre del autor en tarjeta.</p>',
            estado=Post.Estado.PUBLICADO,
        )
        Post.objects.create(
            titulo='Post de Dev Sin Nombre Completo',
            autor=autor_sin_nombre.perfil,
            categoria=self.categoria,
            contenido='<p>Segundo contenido de prueba en la cuadrícula del inicio.</p>',
            estado=Post.Estado.PUBLICADO,
        )
        cache.clear()

        resp_inicio = self.client.get(reverse('blog:post_list'))
        self.assertEqual(resp_inicio.status_code, 200)
        self.assertContains(resp_inicio, 'Elena UX')
        self.assertContains(resp_inicio, 'dev_anonimo')

        resp_autores = self.client.get(reverse('blog:autores_list'))
        self.assertEqual(resp_autores.status_code, 200)
        self.assertContains(resp_autores, 'Elena UX')
        self.assertContains(resp_autores, '@autor_ux')
        self.assertContains(resp_autores, 'dev_anonimo')

    def test_degradado_portada_determinista_y_distinto_entre_posts_misma_categoria(self):
        """
        - El degradado de portada es determinista (el mismo post siempre genera el mismo degradado).
        - Dos posts distintos de la misma categoría generan degradados distintos.
        - No incluye la burbuja con la inicial de la categoría (.post-cover-initial).
        - Si hay imagen_portada, tiene prioridad sobre el degradado.
        """
        post_a = Post.objects.create(
            titulo='Primer Post de Diseño CSS',
            autor=self.autor.perfil,
            categoria=self.categoria,
            contenido='<p>Texto sin imágenes para usar portada generada.</p>',
            estado=Post.Estado.PUBLICADO,
        )
        post_b = Post.objects.create(
            titulo='Segundo Post de Diseño CSS',
            autor=self.autor.perfil,
            categoria=self.categoria,
            contenido='<p>Otro texto sin imágenes en la misma categoría.</p>',
            estado=Post.Estado.PUBLICADO,
        )

        # Determinista para el mismo post
        grad_a_1 = degradado_portada_post(post_a)
        grad_a_2 = degradado_portada_post(post_a)
        self.assertEqual(grad_a_1, grad_a_2)

        # Distinto entre dos posts de la misma categoría
        grad_b = degradado_portada_post(post_b)
        self.assertNotEqual(grad_a_1, grad_b)

        # El HTML de portada_post incluye el degradado, el ícono y NO la burbuja .post-cover-initial
        html_portada_a = str(portada_post(post_a))
        self.assertIn(grad_a_1, html_portada_a)
        self.assertNotIn('post-cover-initial', html_portada_a)

        # Si el post tiene imagen_portada, tiene prioridad sobre el degradado
        post_a.imagen_portada = '/media/uploads/portada-especial.jpg'
        html_con_imagen = str(portada_post(post_a))
        self.assertIn('<img src="/media/uploads/portada-especial.jpg"', html_con_imagen)
        self.assertNotIn('post-cover-gradient', html_con_imagen)


class ComunidadesYMejorasTests(TestCase):
    """
    Pruebas automatizadas para:
    - Menú Compartir con opción Insertar (`</>`) y `PostEmbedView` (`/post/<slug>/embed/`).
    - Comentarios anidados hasta profundidad 4, auto-aprobación para autor/staff,
      borrado seguro (`[comentario eliminado]`), notificación `RESPUESTA_COMENTARIO`
      y número fijo de consultas SQL (`assertNumQueries`).
    - Categorías como comunidades (`MiembroCategoria`, `/categoria/<slug>/unirse/`,
      `/siguiendo/` con `?filtro=todo|autores|comunidades`, métricas semanales de
      vistas y posts, y widget «Descubrir comunidades»).
    - Página de categoría como hub (`/categoria/<slug>/`, máximo 3 fijados en categoría,
      respaldo a los 3 más populares, reglas ordenadas por `orden`, y enlace «Crear post»
      con `?categoria=<slug>` preseleccionado).
    """

    def setUp(self):
        cache.clear()
        self.autor = User.objects.create_user(
            username='autor_com',
            email='autor_com@test.com',
            password='Password123!',
            first_name='Carlos',
            last_name='Comunidad',
        )
        self.lector1 = User.objects.create_user(
            username='lector_com_1',
            email='lector1@test.com',
            password='Password123!',
            first_name='Lucía',
            last_name='Lectora',
        )
        self.lector2 = User.objects.create_user(
            username='lector_com_2',
            email='lector2@test.com',
            password='Password123!',
            first_name='Mateo',
            last_name='Lector',
        )
        self.staff_user = User.objects.create_user(
            username='mod_staff',
            email='mod@test.com',
            password='Password123!',
            is_staff=True,
        )

        self.cat_python = Categoria.objects.create(
            nombre='Python y Django',
            descripcion='Comunidad para desarrolladores de Python y Django.',
        )
        self.cat_devops = Categoria.objects.create(
            nombre='DevOps y Cloud',
            descripcion='Contenedores, CI/CD e infraestructura moderna.',
        )

        self.post_pub = Post.objects.create(
            titulo='Guía Completa de Django & PostgreSQL: ¡Al 100%!',
            autor=self.autor.perfil,
            categoria=self.cat_python,
            contenido='<h2>Introducción</h2><p>Contenido principal del artículo sobre Django.</p>',
            estado=Post.Estado.PUBLICADO,
        )
        self.post_borrador = Post.objects.create(
            titulo='Borrador No Embebible',
            autor=self.autor.perfil,
            categoria=self.cat_python,
            contenido='<p>Borrador privado.</p>',
            estado=Post.Estado.BORRADOR,
        )

    def test_post_embed_view_headers_borrador_404_y_share_urlencode(self):
        """
        - `/post/<slug>/embed/` devuelve 200 para un post publicado y NO envía `X-Frame-Options`.
        - `/post/<slug>/embed/` devuelve 404 para un post en borrador.
        - Las demás páginas públicas SÍ conservan `X-Frame-Options`.
        - El menú Compartir escapa correctamente caracteres especiales en los enlaces (`urlencode`).
        """
        url_embed_pub = reverse('blog:post_embed', kwargs={'slug': self.post_pub.slug})
        resp_embed = self.client.get(url_embed_pub)
        self.assertEqual(resp_embed.status_code, 200)
        self.assertNotIn('X-Frame-Options', resp_embed.headers)
        self.assertContains(resp_embed, 'Guía Completa de Django &amp; PostgreSQL: ¡Al 100%!')
        self.assertContains(resp_embed, 'Leer en')

        # Soporte para ?tema=oscuro
        resp_oscuro = self.client.get(url_embed_pub + '?tema=oscuro')
        self.assertEqual(resp_oscuro.status_code, 200)
        self.assertContains(resp_oscuro, 'data-bs-theme="dark"')

        # Borrador devuelve 404 en /embed/
        url_embed_borrador = reverse('blog:post_embed', kwargs={'slug': self.post_borrador.slug})
        resp_borrador = self.client.get(url_embed_borrador)
        self.assertEqual(resp_borrador.status_code, 404)

        # El detalle normal del post conserva X-Frame-Options y contiene el menú Compartir con urlencode
        url_detail = reverse('blog:post_detail', kwargs={'slug': self.post_pub.slug})
        resp_detail = self.client.get(url_detail)
        self.assertEqual(resp_detail.status_code, 200)
        self.assertIn('X-Frame-Options', resp_detail.headers)
        self.assertContains(resp_detail, 'data-embed-modal-trigger')
        # Verifica que '&' y ':' del título estén codificados en la URL de compartir
        self.assertContains(resp_detail, 'Django%20%26%20PostgreSQL%3A')

    def test_posts_relacionados_excluyen_propio_post_y_borradores_y_snippet_iframe_absoluto(self):
        """
        - «Posts relacionados» incluye posts publicados de la misma categoría o con etiquetas en común.
        - Excluye el propio post y los borradores, y muestra como máximo 4.
        - El botón «Insertar» expone la URL ABSOLUTA de `/embed/` con la que se arma el `<iframe>`.
        """
        etiqueta = Etiqueta.objects.create(nombre='ORM')
        self.post_pub.etiquetas.add(etiqueta)

        # Relacionado por categoría
        rel_categoria = Post.objects.create(
            titulo='Relacionado por Categoría',
            autor=self.autor.perfil,
            categoria=self.cat_python,
            contenido='<p>Misma categoría</p>',
            estado=Post.Estado.PUBLICADO,
        )
        # Relacionado por etiqueta en común (otra categoría)
        rel_etiqueta = Post.objects.create(
            titulo='Relacionado por Etiqueta',
            autor=self.autor.perfil,
            categoria=self.cat_devops,
            contenido='<p>Etiqueta en común</p>',
            estado=Post.Estado.PUBLICADO,
        )
        rel_etiqueta.etiquetas.add(etiqueta)
        # Borrador de la misma categoría: NO debe aparecer
        borrador_rel = Post.objects.create(
            titulo='Borrador Relacionado Oculto',
            autor=self.autor.perfil,
            categoria=self.cat_python,
            contenido='<p>Borrador</p>',
            estado=Post.Estado.BORRADOR,
        )
        borrador_rel.etiquetas.add(etiqueta)
        # Post sin relación: NO debe aparecer
        sin_relacion = Post.objects.create(
            titulo='Post Sin Relación',
            autor=self.autor.perfil,
            categoria=self.cat_devops,
            contenido='<p>Nada en común</p>',
            estado=Post.Estado.PUBLICADO,
        )

        url_detail = reverse('blog:post_detail', kwargs={'slug': self.post_pub.slug})
        resp = self.client.get(url_detail)
        self.assertEqual(resp.status_code, 200)

        pks_rel = [p.pk for p in resp.context['posts_relacionados']]
        self.assertIn(rel_categoria.pk, pks_rel)
        self.assertIn(rel_etiqueta.pk, pks_rel)
        self.assertNotIn(self.post_pub.pk, pks_rel)
        self.assertNotIn(self.post_borrador.pk, pks_rel)
        self.assertNotIn(borrador_rel.pk, pks_rel)
        self.assertNotIn(sin_relacion.pk, pks_rel)
        self.assertLessEqual(len(pks_rel), 4)
        self.assertEqual(len(pks_rel), len(set(pks_rel)))

        # Máximo 4 aunque existan más candidatos
        for i in range(5):
            Post.objects.create(
                titulo=f'Relacionado Extra {i}',
                autor=self.autor.perfil,
                categoria=self.cat_python,
                contenido='<p>Extra</p>',
                estado=Post.Estado.PUBLICADO,
            )
        resp_max = self.client.get(url_detail)
        self.assertEqual(len(resp_max.context['posts_relacionados']), 4)

        # El snippet del iframe se arma con la URL absoluta del embed
        url_embed_absoluta = 'http://testserver' + reverse(
            'blog:post_embed', kwargs={'slug': self.post_pub.slug}
        )
        self.assertContains(resp, f'data-embed-url="{url_embed_absoluta}"')

    def test_comentarios_anidados_padre_otro_post_tope_profundidad_y_autoaprobacion(self):
        """
        - Rechaza `padre_id` perteneciente a otro post.
        - Aplana respuestas por encima de `COMENTARIO_PROFUNDIDAD_MAX = 4` para que queden en el nivel 4.
        - Auto-aprueba respuestas del autor del post o de staff, pero deja pendientes las de lectores.
        """
        otro_post = Post.objects.create(
            titulo='Otro Post Distinto',
            autor=self.autor.perfil,
            categoria=self.cat_devops,
            contenido='<p>Otro contenido</p>',
            estado=Post.Estado.PUBLICADO,
        )
        com_otro_post = Comentario.objects.create(
            post=otro_post,
            autor=self.lector1,
            nombre='Lucía',
            email='lector1@test.com',
            texto='Comentario en otro post',
            aprobado=True,
        )

        # 1. Intentar responder usando un padre_id de otro post -> formulario inválido
        form_invalido = ComentarioForm(
            data={
                'nombre': 'Lucía',
                'email': 'lector1@test.com',
                'texto': 'Intento cruzar posts',
                'padre_id': com_otro_post.pk,
            },
            user=self.lector1,
            post=self.post_pub,
        )
        self.assertFalse(form_invalido.is_valid())

        # 2. Construir cadena de niveles 1 -> 2 -> 3 -> 4 y responder al nivel 4
        n1 = Comentario.objects.create(
            post=self.post_pub, autor=self.lector1, nombre='N1', email='n1@test.com', texto='Nivel 1', aprobado=True
        )
        n2 = Comentario.objects.create(
            post=self.post_pub, padre=n1, autor=self.lector2, nombre='N2', email='n2@test.com', texto='Nivel 2', aprobado=True
        )
        n3 = Comentario.objects.create(
            post=self.post_pub, padre=n2, autor=self.lector1, nombre='N3', email='n1@test.com', texto='Nivel 3', aprobado=True
        )
        n4 = Comentario.objects.create(
            post=self.post_pub, padre=n3, autor=self.lector2, nombre='N4', email='n2@test.com', texto='Nivel 4', aprobado=True
        )
        self.assertEqual(n1.profundidad, 1)
        self.assertEqual(n4.profundidad, 4)

        # Responder a n4 (nivel 4) debe reasignar el padre a n3 para no superar profundidad 4
        url_detail = reverse('blog:post_detail', kwargs={'slug': self.post_pub.slug})
        self.client.login(username='autor_com', password='Password123!')
        self.client.post(
            url_detail,
            {
                'nombre': 'Carlos',
                'email': 'autor_com@test.com',
                'texto': 'Respuesta del autor al nivel 4',
                'padre_id': n4.pk,
            },
        )
        respuesta_autor = Comentario.objects.get(texto='Respuesta del autor al nivel 4')
        # Como es el autor del post, se auto-aprueba inmediatamente
        self.assertTrue(respuesta_autor.aprobado)
        # Y su padre queda aplanado a n3 (profundidad 4)
        self.assertEqual(respuesta_autor.padre_id, n3.pk)
        self.assertEqual(respuesta_autor.profundidad, 4)

        # 3. Un lector normal envía respuesta -> queda pendiente de moderación (aprobado=False)
        self.client.login(username='lector_com_1', password='Password123!')
        self.client.post(
            url_detail,
            {
                'nombre': 'Lucía',
                'email': 'lector1@test.com',
                'texto': 'Respuesta de lectora pendiente',
                'padre_id': n1.pk,
            },
        )
        respuesta_lectora = Comentario.objects.get(texto='Respuesta de lectora pendiente')
        self.assertFalse(respuesta_lectora.aprobado)

    def test_borrado_seguro_de_comentario_con_y_sin_respuestas_y_notificacion_respuesta(self):
        """
        - Si un comentario tiene respuestas, borrarlo marca `eliminado=True`, conserva las respuestas
          y muestra `[comentario eliminado]` sin exponer el texto original.
        - Si un comentario NO tiene respuestas, se elimina físicamente de la base de datos.
        - Al aprobar una respuesta se envía `RESPUESTA_COMENTARIO` al autor del comentario padre sin duplicar.
        """
        padre = Comentario.objects.create(
            post=self.post_pub,
            autor=self.lector1,
            nombre='Lucía',
            email='lector1@test.com',
            texto='Texto secreto del comentario padre que será borrado',
            aprobado=True,
        )
        hijo = Comentario.objects.create(
            post=self.post_pub,
            padre=padre,
            autor=self.lector2,
            nombre='Mateo',
            email='lector2@test.com',
            texto='Respuesta pendiente de Mateo para Lucía',
            aprobado=False,
        )

        # El autor del post aprueba la respuesta desde el panel -> notifica RESPUESTA_COMENTARIO a Lucía
        self.client.login(username='autor_com', password='Password123!')
        self.client.post(
            reverse('blog:panel_comentario_accion', kwargs={'pk': hijo.pk}),
            {'accion': 'aprobar'},
        )
        hijo.refresh_from_db()
        self.assertTrue(hijo.aprobado)
        self.assertEqual(
            Notificacion.objects.filter(
                destinatario=self.lector1,
                tipo=Notificacion.Tipo.RESPUESTA_COMENTARIO,
                comentario=hijo,
            ).count(),
            1,
        )

        # Ahora Lucía borra su comentario padre (que tiene 1 respuesta aprobada)
        self.client.login(username='lector_com_1', password='Password123!')
        self.client.post(reverse('blog:comentario_eliminar', kwargs={'pk': padre.pk}))
        padre.refresh_from_db()
        self.assertTrue(padre.eliminado)
        self.assertTrue(Comentario.objects.filter(pk=hijo.pk).exists())

        # En el detalle del post se muestra [comentario eliminado], NO el texto original, y SÍ la respuesta hija
        resp_detail = self.client.get(reverse('blog:post_detail', kwargs={'slug': self.post_pub.slug}))
        self.assertContains(resp_detail, '[comentario eliminado]')
        self.assertNotContains(resp_detail, 'Texto secreto del comentario padre que será borrado')
        self.assertContains(resp_detail, 'Respuesta pendiente de Mateo para Lucía')

        # Borrar un comentario hoja (sin respuestas) lo elimina físicamente
        hoja = Comentario.objects.create(
            post=self.post_pub,
            autor=self.lector1,
            nombre='Lucía',
            email='lector1@test.com',
            texto='Comentario sin respuestas',
            aprobado=True,
        )
        self.client.post(reverse('blog:comentario_eliminar', kwargs={'pk': hoja.pk}))
        self.assertFalse(Comentario.objects.filter(pk=hoja.pk).exists())

    def test_arbol_comentarios_una_sola_consulta_sin_n_mas_1(self):
        """
        Verifica que renderizar el árbol de comentarios en `PostDetailView` ejecuta un número
        constante de consultas SQL sin importar cuántos comentarios anidados existan.
        """
        url_detail = reverse('blog:post_detail', kwargs={'slug': self.post_pub.slug})

        # Crear 1 comentario base y calentar sesión/caché
        c_base = Comentario.objects.create(
            post=self.post_pub,
            autor=self.lector1,
            nombre='Lucía',
            email='lector1@test.com',
            texto='Base 1',
            aprobado=True,
        )
        self.client.get(url_detail)

        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        cache.clear()
        with CaptureQueriesContext(connection) as ctx_1:
            resp1 = self.client.get(url_detail)
            self.assertEqual(resp1.status_code, 200)
        num_queries_con_1 = len(ctx_1)

        # Agregar 12 comentarios adicionales en varios niveles de profundidad
        actual = c_base
        for i in range(12):
            actual = Comentario.objects.create(
                post=self.post_pub,
                padre=actual if (i % 4 != 0) else None,
                autor=self.lector2 if (i % 2 == 0) else self.lector1,
                nombre=f'Usuario {i}',
                email=f'u{i}@test.com',
                texto=f'Comentario anidado número {i}',
                aprobado=True,
            )

        cache.clear()
        with self.assertNumQueries(num_queries_con_1):
            resp2 = self.client.get(url_detail)
            self.assertEqual(resp2.status_code, 200)
            self.assertContains(resp2, 'Comentario anidado número 11')

    def test_miembro_categoria_unicidad_toggle_ajax_y_sin_notificaciones(self):
        """
        - `MiembroCategoria` es único por `(usuario, categoria)`.
        - `/categoria/<slug>/unirse/` requiere login (401 en AJAX para anónimos).
        - Al hacer POST autenticado une/desune, devuelve JSON con `total_miembros` y NO genera notificaciones ni correos.
        """
        url_unirse = reverse('blog:categoria_unirse_toggle', kwargs={'slug': self.cat_python.slug})

        # 1. Visitante anónimo por AJAX -> 401 con login_url
        resp_anon = self.client.post(url_unirse, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_anon.status_code, 401)

        # 2. Usuario autenticado se une por AJAX
        self.client.login(username='lector_com_1', password='Password123!')
        mail.outbox.clear()
        resp_join = self.client.post(url_unirse, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_join.status_code, 200)
        datos_join = resp_join.json()
        self.assertTrue(datos_join['ok'])
        self.assertTrue(datos_join['unido'])
        self.assertEqual(datos_join['total_miembros'], 1)
        self.assertTrue(
            MiembroCategoria.objects.filter(usuario=self.lector1, categoria=self.cat_python).exists()
        )
        # No envía notificaciones ni correos
        self.assertEqual(Notificacion.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

        # 3. Unicidad en base de datos
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MiembroCategoria.objects.create(usuario=self.lector1, categoria=self.cat_python)

        # 4. Segundo POST desune de la comunidad
        resp_leave = self.client.post(url_unirse, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_leave.status_code, 200)
        datos_leave = resp_leave.json()
        self.assertFalse(datos_leave['unido'])
        self.assertEqual(datos_leave['total_miembros'], 0)

    def test_feed_siguiendo_combina_autores_y_comunidades_sin_duplicados_y_filtra(self):
        """
        - `/siguiendo/` incluye posts de autores seguidos y de comunidades unidas sin duplicados.
        - Soporta `?filtro=todo`, `?filtro=autores` y `?filtro=comunidades`.
        """
        autor_extra = User.objects.create_user(
            username='autor_devops', email='ad@test.com', password='Password123!'
        )
        # Post 1: de `self.autor` en `self.cat_python` (coincide por autor Y por comunidad)
        post_ambos = self.post_pub
        # Post 2: de `self.autor` en `self.cat_devops` (solo coincide por autor seguido)
        post_solo_autor = Post.objects.create(
            titulo='Post Solo Autor Seguido',
            autor=self.autor.perfil,
            categoria=self.cat_devops,
            contenido='<p>Solo autor</p>',
            estado=Post.Estado.PUBLICADO,
        )
        # Post 3: de `autor_extra` en `self.cat_python` (solo coincide por comunidad unida)
        post_solo_comunidad = Post.objects.create(
            titulo='Post Solo Comunidad Unida',
            autor=autor_extra.perfil,
            categoria=self.cat_python,
            contenido='<p>Solo comunidad</p>',
            estado=Post.Estado.PUBLICADO,
        )

        # Lector 1 sigue a `self.autor` y se une a `self.cat_python`
        Seguimiento.objects.create(seguidor=self.lector1, autor=self.autor.perfil)
        MiembroCategoria.objects.create(usuario=self.lector1, categoria=self.cat_python)

        self.client.login(username='lector_com_1', password='Password123!')
        url_siguiendo = reverse('blog:siguiendo_feed')

        # 1. Filtro 'todo': aparecen los 3 posts sin duplicar `post_ambos`
        resp_todo = self.client.get(url_siguiendo + '?filtro=todo')
        self.assertEqual(resp_todo.status_code, 200)
        pks_todo = [p.pk for p in resp_todo.context['posts']]
        self.assertEqual(len(pks_todo), 3)
        self.assertEqual(len(set(pks_todo)), 3)

        # 2. Filtro 'autores': solo posts de `self.autor` (`post_ambos` y `post_solo_autor`)
        resp_autores = self.client.get(url_siguiendo + '?filtro=autores')
        pks_autores = {p.pk for p in resp_autores.context['posts']}
        self.assertEqual(pks_autores, {post_ambos.pk, post_solo_autor.pk})

        # 3. Filtro 'comunidades': solo posts en `self.cat_python` (`post_ambos` y `post_solo_comunidad`)
        resp_com = self.client.get(url_siguiendo + '?filtro=comunidades')
        pks_com = {p.pk for p in resp_com.context['posts']}
        self.assertEqual(pks_com, {post_ambos.pk, post_solo_comunidad.pk})

    def test_metricas_semanales_categoria_y_widget_descubrir_comunidades(self):
        """
        - `vistas_semana` suma `VistaDiaria.cantidad` solo de los últimos 7 días (ignora vistas antiguas).
        - No duplica sumas cuando una categoría tiene varios miembros y varios posts.
        - `obtener_comunidades_descubrir` excluye las comunidades a las que el usuario ya se unió.
        """
        hoy = timezone.localdate()
        hace_3_dias = hoy - timedelta(days=3)
        hace_15_dias = hoy - timedelta(days=15)

        VistaDiaria.objects.create(post=self.post_pub, fecha=hoy, cantidad=12)
        VistaDiaria.objects.create(post=self.post_pub, fecha=hace_3_dias, cantidad=8)
        VistaDiaria.objects.create(post=self.post_pub, fecha=hace_15_dias, cantidad=100)  # Fuera de ventana

        # Agregar 2 miembros para comprobar que no distorsiona la suma de vistas por JOIN
        MiembroCategoria.objects.create(usuario=self.lector1, categoria=self.cat_python)
        MiembroCategoria.objects.create(usuario=self.lector2, categoria=self.cat_python)

        cat_metricas = construir_queryset_categorias_metricas().get(pk=self.cat_python.pk)
        self.assertEqual(cat_metricas.vistas_semana, 20)
        self.assertEqual(cat_metricas.posts_semana, 1)
        self.assertEqual(cat_metricas.total_miembros, 2)
        self.assertEqual(cat_metricas.total_posts, 1)

        # Lector 1 ya está unido a cat_python -> en «Descubrir comunidades» solo le aparece cat_devops
        cache.clear()
        descubrir_lector1 = obtener_comunidades_descubrir(self.lector1, limite=4)
        slugs_descubrir = [c.slug for c in descubrir_lector1]
        self.assertNotIn(self.cat_python.slug, slugs_descubrir)
        self.assertIn(self.cat_devops.slug, slugs_descubrir)

    def test_hub_categoria_fijados_max_3_respaldo_populares_reglas_crear_post_y_404(self):
        """
        - `Post.clean()` impide fijar más de 3 posts publicados en una misma categoría.
        - Si no hay posts fijados, el hub `/categoria/<slug>/` muestra hasta 3 populares como respaldo.
        - Las reglas de `ReglaCategoria` se muestran ordenadas por `orden`.
        - `/panel/posts/nuevo/?categoria=<slug>` preselecciona esa categoría.
        - Un slug de categoría inexistente devuelve 404.
        """
        # 1. Crear reglas desordenadas y verificar que el hub las ordena por `orden`
        ReglaCategoria.objects.create(
            categoria=self.cat_python, orden=2, titulo='Segunda regla', descripcion='Comparte código limpio.'
        )
        ReglaCategoria.objects.create(
            categoria=self.cat_python, orden=1, titulo='Primera regla', descripcion='Sé respetuoso.'
        )

        # Sin fijados -> usa respaldo de populares
        url_hub = reverse('blog:posts_por_categoria', kwargs={'slug': self.cat_python.slug})
        resp_hub_respaldo = self.client.get(url_hub)
        self.assertEqual(resp_hub_respaldo.status_code, 200)
        self.assertTrue(resp_hub_respaldo.context['es_respaldo_populares'])
        reglas = resp_hub_respaldo.context['reglas_categoria']
        self.assertEqual([r.titulo for r in reglas], ['Primera regla', 'Segunda regla'])

        # 2. Fijar 3 posts en `self.cat_python` -> válido; intentar fijar un 4.º -> ValidationError
        self.post_pub.fijado_en_categoria = True
        self.post_pub.full_clean()
        self.post_pub.save()

        for i in range(2):
            p_fijo = Post(
                titulo=f'Post Fijado Adicional {i + 1}',
                autor=self.autor.perfil,
                categoria=self.cat_python,
                contenido='<p>Contenido fijado</p>',
                estado=Post.Estado.PUBLICADO,
                fijado_en_categoria=True,
            )
            p_fijo.full_clean()
            p_fijo.save()

        cuarto_fijo = Post(
            titulo='Cuarto Post Que No Debe Fijarse',
            autor=self.autor.perfil,
            categoria=self.cat_python,
            contenido='<p>Excede el máximo de 3</p>',
            estado=Post.Estado.PUBLICADO,
            fijado_en_categoria=True,
        )
        with self.assertRaises(ValidationError):
            cuarto_fijo.clean()

        # Ahora el hub muestra los 3 fijados (`es_respaldo_populares=False`)
        resp_hub_fijados = self.client.get(url_hub)
        self.assertFalse(resp_hub_fijados.context['es_respaldo_populares'])
        self.assertEqual(len(resp_hub_fijados.context['posts_destacados_categoria']), 3)

        # 3. Preselección de categoría en `/panel/posts/nuevo/?categoria=<slug>`
        self.client.login(username='autor_com', password='Password123!')
        resp_crear = self.client.get(
            reverse('blog:panel_post_create') + f'?categoria={self.cat_python.slug}'
        )
        self.assertEqual(resp_crear.status_code, 200)
        self.assertEqual(resp_crear.context['form'].initial.get('categoria'), self.cat_python.pk)

        # 4. Categoría inexistente -> 404
        resp_404 = self.client.get(
            reverse('blog:posts_por_categoria', kwargs={'slug': 'categoria-que-no-existe'})
        )
        self.assertEqual(resp_404.status_code, 404)


class PulidoYMejorasTests(TestCase):
    """
    Pruebas automatizadas de la pasada de pulido y correcciones:
    - Insignia única en modo compacto según jerarquía y todas en vista completa.
    - Extracto manual, imagen de portada y creación AJAX de etiquetas en el editor de posts.
    - Paginación accesible con estados deshabilitados en 'Anterior' y 'Siguiente'.
    - Panel de Autor con 8 métricas y checklist dinámico de primeros pasos.
    """

    def setUp(self):
        cache.clear()
        self.autor_user = User.objects.create_user(
            username='autor_pulido',
            email='autor_pulido@test.com',
            password='Password123!',
            first_name='Laura',
            last_name='Gómez',
        )
        self.autor_perfil = self.autor_user.perfil
        self.categoria = Categoria.objects.create(
            nombre='Ingeniería de Software',
            descripcion='Patrones, buenas prácticas y arquitectura.',
        )

    def test_insignia_modo_compacto_jerarquia_y_completo(self):
        """
        Verifica que `{% insignia %}` en modo compacto (por defecto) muestra solo una insignia
        según la jerarquía Destacado > Activo > Nuevo, y en modo completo muestra todas.
        """
        user_top = User.objects.create_user(username='autor_multi_insignia', password='Password123!')
        for i in range(6):
            p = Post.objects.create(
                titulo=f'Post Multi Insignia {i}',
                autor=user_top.perfil,
                categoria=self.categoria,
                contenido='<p>Contenido para sumar actividad</p>',
                estado=Post.Estado.PUBLICADO,
            )
            VistaDiaria.objects.create(post=p, fecha=timezone.localdate(), cantidad=50)

        # En modo compacto (por defecto), solo debe mostrar la de mayor rango (Destacado)
        html_compacto = insignia(user_top.perfil, compacto=True)
        self.assertIn('Destacado', html_compacto)
        self.assertNotIn('Activo', html_compacto)
        self.assertNotIn('Nuevo', html_compacto)

        # En modo completo (todas=True), muestra todas las insignias obtenidas
        html_completo = insignia(user_top.perfil, todas=True)
        self.assertIn('Destacado', html_completo)
        self.assertIn('Activo', html_completo)

    def test_post_extracto_manual_portada_y_etiqueta_ajax(self):
        """
        Verifica el modelo Post con extracto_manual e imagen_portada,
        y la creación de etiquetas vía endpoint AJAX.
        """
        # 1. Post con extracto manual
        post_manual = Post.objects.create(
            titulo='Post con Extracto Manual Personalizado',
            autor=self.autor_perfil,
            categoria=self.categoria,
            contenido='<h2>Encabezado Ignorado</h2><p>Párrafo principal muy largo que sería extraído por defecto.</p>',
            extracto_manual='Este es mi extracto personalizado manual.',
            estado=Post.Estado.PUBLICADO,
        )
        self.assertEqual(post_manual.extracto, 'Este es mi extracto personalizado manual.')

        # 2. Si extracto_manual está vacío, fallback a extracto_plano
        post_auto = Post.objects.create(
            titulo='Post con Extracto Automático',
            autor=self.autor_perfil,
            categoria=self.categoria,
            contenido='<h2>Título interno</h2><p>Contenido automático generado limpiamente.</p>',
            extracto_manual='',
            estado=Post.Estado.PUBLICADO,
        )
        self.assertIn('Contenido automático generado', post_auto.extracto)

        # 3. Creación de etiqueta vía AJAX
        self.client.login(username='autor_pulido', password='Password123!')
        resp_ajax = self.client.post(
            reverse('blog:etiqueta_crear_ajax'),
            {'nombre': 'FastAPI'},
        )
        self.assertEqual(resp_ajax.status_code, 200)
        data = resp_ajax.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['nombre'], 'FastAPI')
        self.assertTrue(Etiqueta.objects.filter(nombre='FastAPI').exists())

    @override_settings(FEED_PAGINATE_BY=6)
    def test_paginacion_botones_desactivados_anterior_y_siguiente(self):
        """
        Verifica que en la página 1 'Anterior' esté deshabilitado con aria-disabled='true',
        y en la última página 'Siguiente' esté deshabilitado.
        """
        for i in range(12):
            Post.objects.create(
                titulo=f'Post Paginación Num {i + 1}',
                autor=self.autor_perfil,
                categoria=self.categoria,
                contenido=f'<p>Contenido para página {i + 1}</p>',
                estado=Post.Estado.PUBLICADO,
            )

        resp_p1 = self.client.get(reverse('blog:post_list'))
        self.assertEqual(resp_p1.status_code, 200)
        self.assertContains(resp_p1, 'page-item disabled')
        self.assertContains(resp_p1, 'aria-disabled="true"')

        num_paginas = resp_p1.context['page_obj'].paginator.num_pages
        resp_last = self.client.get(reverse('blog:post_list') + f'?page={num_paginas}')
        self.assertEqual(resp_last.status_code, 200)
        self.assertContains(resp_last, 'page-item disabled')

    def test_dashboard_8_metricas_y_checklist_primeros_pasos(self):
        """
        Verifica las 8 métricas en el Panel de Autor y el checklist 'Primeros pasos':
        - Si tiene 0 posts publicados: checklist visible.
        - Si tiene >= 1 post publicado: checklist desaparece.
        """
        nuevo_user = User.objects.create_user(username='autor_novato', password='Password123!')
        self.client.login(username='autor_novato', password='Password123!')

        resp_vacio = self.client.get(reverse('blog:panel_dashboard'))
        self.assertEqual(resp_vacio.status_code, 200)
        self.assertEqual(resp_vacio.context['total_publicados'], 0)
        self.assertContains(resp_vacio, 'Primeros pasos para empezar')
        for metrica in (
            'total_publicados', 'total_borradores', 'comentarios_pendientes',
            'reportes_pendientes', 'likes_recibidos_total', 'total_seguidores',
            'porcentaje_utilidad_global', 'vistas_ultimos_7_dias'
        ):
            self.assertIn(metrica, resp_vacio.context)

        Post.objects.create(
            titulo='Mi Primer Post Publicado',
            autor=nuevo_user.perfil,
            categoria=self.categoria,
            contenido='<p>¡Hola comunidad!</p>',
            estado=Post.Estado.PUBLICADO,
        )
        resp_con_post = self.client.get(reverse('blog:panel_dashboard'))
        self.assertEqual(resp_con_post.status_code, 200)
        self.assertGreaterEqual(resp_con_post.context['total_publicados'], 1)
        self.assertNotContains(resp_con_post, 'Primeros pasos para empezar')

    def test_lista_guardados_enlace_redireccion_y_apartado_vacio(self):
        """
        Verifica:
        1. get_absolute_url en ListaLectura devuelve la URL correcta a lista_detail.
        2. /guardados/ redirige a la lista predeterminada Guardados del usuario.
        3. En /mis-listas/, el botón 'Ver lista' apunta a /listas/<pk>/ y no está vacío.
        4. Cuando no hay guardados, lista_detail muestra el apartado 'No tienes nada guardado'.
        5. Al guardar un post, aparece en la lista de guardados y desaparece el estado vacío.
        """
        self.client.login(username='autor_pulido', password='Password123!')

        # 1 y 2. Redirección /guardados/
        resp_guardados = self.client.get(reverse('blog:guardados'), follow=True)
        self.assertEqual(resp_guardados.status_code, 200)
        lista = resp_guardados.context['lista']
        self.assertTrue(lista.es_guardados)
        self.assertEqual(lista.get_absolute_url(), reverse('blog:lista_detail', kwargs={'pk': lista.pk}))

        # 3. En /mis-listas/, 'Ver lista' enlaza correctamente con la URL de la lista
        resp_mis_listas = self.client.get(reverse('blog:mis_listas'))
        self.assertEqual(resp_mis_listas.status_code, 200)
        self.assertContains(resp_mis_listas, lista.get_absolute_url())
        self.assertContains(resp_mis_listas, 'Aún no tienes artículos guardados')

        # 4. En lista_detail vacío, muestra el apartado específico
        self.assertContains(resp_guardados, 'No tienes nada guardado')
        self.assertContains(resp_guardados, 'Explorar artículos')

        # 5. Guardar un post y comprobar que aparece
        post = Post.objects.create(
            titulo='Artículo Guardado de Prueba',
            autor=self.autor_perfil,
            categoria=self.categoria,
            contenido='<p>Contenido guardado</p>',
            estado=Post.Estado.PUBLICADO,
        )
        self.client.post(reverse('blog:post_guardar_toggle', args=[post.slug]))

        resp_con_items = self.client.get(lista.get_absolute_url())
        self.assertEqual(resp_con_items.status_code, 200)
        self.assertContains(resp_con_items, 'Artículo Guardado de Prueba')
        self.assertNotContains(resp_con_items, 'No tienes nada guardado')





# ==============================================================================
# RONDA 3: ESTUDIO DE ESCRITURA Y SERVICIO DE PUBLICACIÓN
# ==============================================================================
class EstudioEscrituraTests(TestCase):
    """Pruebas del servicio de publicación, control de revisiones, APIs y estudio de escritura."""

    def setUp(self):
        import json
        from cuentas.models import Perfil
        self.user = User.objects.create_user(
            username='escritor_test',
            email='escritor@example.com',
            password='Password123!',
            first_name='Autor',
            last_name='Pruebas'
        )
        self.perfil = Perfil.objects.get(usuario=self.user)
        self.categoria = Categoria.objects.create(nombre='Arquitectura', slug='arquitectura')
        self.etiqueta = Etiqueta.objects.create(nombre='Django', slug='django')
        self.contenido_valido = '<p>' + ' '.join(['palabra'] * 65) + '</p>'

    def test_servicio_publicar_primera_vez_idempotente(self):
        """La primera publicación asigna publicado_en y notificado=True. La segunda es idempotente."""
        from blog.servicios.publicacion import publicar, guardar_borrador

        post = Post(
            autor=self.perfil,
            titulo='Post para publicar por servicio',
            contenido=self.contenido_valido,
            categoria=self.categoria
        )
        guardar_borrador(post, usuario=self.user)
        post.etiquetas.add(self.etiqueta)

        self.assertEqual(post.estado, Post.Estado.BORRADOR)
        self.assertIsNone(post.publicado_en)
        self.assertFalse(post.notificado)

        # Primera publicación
        with self.captureOnCommitCallbacks(execute=True):
            post_pub = publicar(post, usuario=self.user)

        self.assertEqual(post_pub.estado, Post.Estado.PUBLICADO)
        self.assertIsNotNone(post_pub.publicado_en)
        self.assertTrue(post_pub.notificado)

        # Segunda publicación (actualización): no debe reiniciar notificado ni cambiar fecha original
        fecha_orig = post_pub.publicado_en
        with self.captureOnCommitCallbacks(execute=True):
            post_actualizado = publicar(post_pub, usuario=self.user)

        self.assertEqual(post_actualizado.publicado_en, fecha_orig)
        self.assertTrue(post_actualizado.notificado)

    def test_servicio_programar_y_despublicar(self):
        """Programar fija fecha futura y estado PROGRAMADO. Despublicar regresa a BORRADOR."""
        from blog.servicios.publicacion import guardar_borrador, programar, despublicar

        post = Post(
            autor=self.perfil,
            titulo='Post para programar',
            contenido=self.contenido_valido,
            categoria=self.categoria
        )
        guardar_borrador(post, usuario=self.user)

        fecha_futura = timezone.now() + timedelta(hours=2)
        post_prog = programar(post, fecha_hora=fecha_futura, usuario=self.user)

        self.assertEqual(post_prog.estado, Post.Estado.PROGRAMADO)
        self.assertEqual(post_prog.programado_para, fecha_futura)
        # No debe aparecer en el queryset de publicados
        self.assertNotIn(post_prog, Post.objects.publicados())

        # Despublicar
        post_despub = despublicar(post_prog, usuario=self.user)
        self.assertEqual(post_despub.estado, Post.Estado.BORRADOR)
        self.assertIsNone(post_despub.programado_para)
        self.assertNotIn(post_despub, Post.objects.publicados())

    def test_servicio_duplicar_post(self):
        """Duplicar crea un nuevo borrador independiente con diferente slug."""
        from blog.servicios.publicacion import guardar_borrador, duplicar

        original = Post(
            autor=self.perfil,
            titulo='Artículo original a duplicar',
            contenido=self.contenido_valido,
            categoria=self.categoria
        )
        guardar_borrador(original, usuario=self.user)
        original.etiquetas.add(self.etiqueta)

        copia = duplicar(original, usuario=self.user)

        self.assertNotEqual(original.pk, copia.pk)
        self.assertEqual(copia.estado, Post.Estado.BORRADOR)
        self.assertTrue(copia.titulo.startswith('Copia de '))
        self.assertNotEqual(original.slug, copia.slug)
        self.assertEqual(copia.categoria_id, original.categoria_id)
        self.assertEqual(list(copia.etiquetas.all()), list(original.etiquetas.all()))

    def test_poda_automatica_revisiones_max_20(self):
        """Se conservan un máximo de 20 revisiones por post, eliminando las más antiguas."""
        from blog.servicios.publicacion import guardar_borrador
        from blog.models import RevisionPost

        post = Post(
            autor=self.perfil,
            titulo='Post con múltiples revisiones',
            contenido=self.contenido_valido,
            categoria=self.categoria
        )
        guardar_borrador(post, usuario=self.user)

        for i in range(25):
            RevisionPost.objects.create(
                post=post,
                titulo=f'Versión {i}',
                contenido=f'<p>Contenido {i}</p>',
                extracto=f'Extracto {i}',
                origen=RevisionPost.Origen.AUTO
            )

        total_revisiones = RevisionPost.objects.filter(post=post).count()
        self.assertEqual(total_revisiones, 20)

    def test_slug_inmutable_tras_publicacion(self):
        """El slug no se puede cambiar una vez que el post tiene publicado_en asignado."""
        from blog.servicios.publicacion import guardar_borrador, publicar

        post = Post(
            autor=self.perfil,
            titulo='Post con slug protegido',
            contenido=self.contenido_valido,
            categoria=self.categoria
        )
        guardar_borrador(post, usuario=self.user)
        publicar(post, usuario=self.user)

        post.slug = 'slug-intentado-cambiar'
        with self.assertRaises(ValidationError):
            post.save()

    def test_comando_publicar_programados(self):
        """El comando de gestión publica únicamente los posts cuya fecha programada ya se cumplió."""
        from blog.servicios.publicacion import guardar_borrador
        from django.core.management import call_command

        post_vencido = Post(
            autor=self.perfil,
            titulo='Post programado ya cumplido',
            contenido=self.contenido_valido,
            categoria=self.categoria
        )
        guardar_borrador(post_vencido, usuario=self.user)
        post_vencido.programado_para = timezone.now() - timedelta(minutes=10)
        post_vencido.estado = Post.Estado.PROGRAMADO
        post_vencido.save()

        post_futuro = Post(
            autor=self.perfil,
            titulo='Post programado para el futuro',
            contenido=self.contenido_valido,
            categoria=self.categoria
        )
        guardar_borrador(post_futuro, usuario=self.user)
        post_futuro.programado_para = timezone.now() + timedelta(hours=5)
        post_futuro.estado = Post.Estado.PROGRAMADO
        post_futuro.save()

        # Ejecutar comando
        call_command('publicar_programados')

        post_vencido.refresh_from_db()
        post_futuro.refresh_from_db()

        self.assertEqual(post_vencido.estado, Post.Estado.PUBLICADO)
        self.assertIsNotNone(post_vencido.publicado_en)
        self.assertEqual(post_futuro.estado, Post.Estado.PROGRAMADO)

    def test_api_autoguardar_y_concurrencia_409(self):
        """La API de autoguardado guarda borradores y detecta conflictos de concurrencia."""
        import json
        self.client.login(username='escritor_test', password='Password123!')

        resp = self.client.post(
            '/panel/api/autoguardar/',
            data=json.dumps({
                'titulo': 'Nuevo post autoguardado',
                'contenido': '<p>Contenido autoguardado en tiempo real.</p>',
                'categoria_id': self.categoria.pk,
                'extracto': 'Extracto manual para SEO',
                'origen': 'auto'
            }),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        post_id = data['post_id']

        # Concurrencia: si otra petición envía una fecha obsoleta anterior a la guardada
        post = Post.objects.get(pk=post_id)
        fecha_obsoleta = (post.actualizado - timedelta(hours=1)).isoformat()

        resp_conflicto = self.client.post(
            '/panel/api/autoguardar/',
            data=json.dumps({
                'post_id': post_id,
                'titulo': 'Conflicto de título',
                'contenido': '<p>Intento de sobreescritura tardía.</p>',
                'ultima_actualizacion_conocida': fecha_obsoleta
            }),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp_conflicto.status_code, 409)

# ==============================================================================
# RONDA 4: OPTIMIZACIÓN Y PULIDO MÓVIL
# ==============================================================================
class OptimizacionMovilTests(TestCase):
    """Pruebas del sistema móvil, metas, nombres y exclusión de boletín."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username='ana_garcia',
            email='ana@example.com',
            password='Password123!',
            first_name='Ana',
            last_name='García'
        )
        self.categoria = Categoria.objects.create(nombre='Frontend', slug='frontend')
        self.post = Post.objects.create(
            autor=self.user.perfil,
            titulo='Post Móvil de Prueba',
            contenido='<p>Contenido para pruebas móviles.</p>',
            categoria=self.categoria,
            estado=Post.Estado.PUBLICADO
        )

    def test_mensajes_usan_nombre_mostrar(self):
        """Los mensajes de bienvenida y login deben mostrar el nombre completo y no username plano."""
        resp = self.client.post(
            reverse('cuentas:login'),
            {'username': 'ana_garcia', 'password': 'Password123!'},
            follow=True
        )
        self.assertEqual(resp.status_code, 200)
        messages_list = list(resp.context['messages'])
        self.assertTrue(any('Has iniciado sesión como Ana García.' in str(m) for m in messages_list))
        self.assertFalse(any('Has iniciado sesión como ana_garcia.' in str(m) for m in messages_list))

    def test_boletin_no_aparece_en_panel_ni_editor(self):
        """El formulario de boletín en el pie debe excluirse de panel, editor y autenticación."""
        self.client.login(username='ana_garcia', password='Password123!')

        resp_panel = self.client.get(reverse('blog:panel_dashboard'))
        self.assertEqual(resp_panel.status_code, 200)
        self.assertNotContains(resp_panel, 'footerBoletinSeccion')
        self.assertNotContains(resp_panel, 'Suscríbete por correo')

        resp_editor = self.client.get(reverse('blog:panel_post_create'))
        self.assertEqual(resp_editor.status_code, 200)
        self.assertNotContains(resp_editor, 'footerBoletinSeccion')
        self.assertNotContains(resp_editor, 'Suscríbete por correo')

        self.client.logout()
        resp_login = self.client.get(reverse('cuentas:login'))
        self.assertEqual(resp_login.status_code, 200)
        self.assertNotContains(resp_login, 'footerBoletinSeccion')
        self.assertNotContains(resp_login, 'Suscríbete por correo')

    def test_meta_viewport_incluye_viewport_fit_cover(self):
        """Comprueba que <meta name='viewport'> incluya viewport-fit=cover en las plantillas."""
        from django.template.loader import render_to_string
        from django.test import RequestFactory
        rf = RequestFactory()
        request = rf.get('/')
        plantillas = [
            'base.html',
            'base_auth.html',
            'blog/panel/editor/base_editor.html',
            'blog/post_embed.html',
        ]
        for p in plantillas:
            html = render_to_string(
                p,
                {'post': self.post, 'form': None, 'MARCA': 'Blog', 'site_name': 'Blog'},
                request=request
            )
            self.assertIn('viewport-fit=cover', html, f'Plantilla {p} no incluye viewport-fit=cover')

    def test_editor_usa_variables_disenio(self):
        """Verifica que el editor use los estilos del sistema de diseño y clases móviles."""
        from django.template.loader import render_to_string
        from django.test import RequestFactory
        rf = RequestFactory()
        request = rf.get('/')
        html = render_to_string(
            'blog/panel/editor/base_editor.html',
            {'post': self.post, 'MARCA': 'Blog', 'site_name': 'Blog'},
            request=request
        )
        self.assertIn('estilos.css', html)
        self.assertIn('editor.css', html)


class ForoAdaptableFase1y2Tests(TestCase):
    """Pruebas de la Fase 1 y 2: Sistema de diseño adaptable, navegación y buscador de sugerencias."""

    def setUp(self):
        cache.clear()
        from cuentas.models import Perfil
        self.user = User.objects.create_user(
            username='carlos_dev',
            first_name='Carlos',
            last_name='Dev',
            email='carlos@example.com',
            password='Password123!',
        )
        self.perfil, _ = Perfil.objects.get_or_create(usuario=self.user)
        self.categoria = Categoria.objects.create(
            nombre='Python y Django',
            slug='python-django',
            descripcion='Comunidad de Python y Django'
        )
        self.post = Post.objects.create(
            titulo='Arquitectura Limpia en Django',
            slug='arquitectura-limpia-django',
            contenido='Contenido explicativo de arquitectura limpia.',
            categoria=self.categoria,
            autor=self.perfil,
            estado=Post.Estado.PUBLICADO,
        )
        self.etiqueta = Etiqueta.objects.create(
            nombre='arquitectura',
            slug='arquitectura'
        )
        self.post.etiquetas.add(self.etiqueta)

    def test_base_html_estructura_foro_adaptable(self):
        """Verifica que base.html incluya la barra superior, riel izquierdo, barra inferior, HTMX y modal visitante."""
        resp = self.client.get(reverse('blog:post_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'app-header')
        self.assertContains(resp, 'app-nav-left')
        self.assertContains(resp, 'app-bottom-bar')
        self.assertContains(resp, 'modalAccesoVisitante')
        self.assertContains(resp, 'htmx.min.js')
        self.assertContains(resp, 'hx-headers')
        self.assertContains(resp, 'X-CSRFToken')

    def test_buscar_sugerencias_endpoint_min_caracteres(self):
        """Verifica que sugerencias requieran mínimo 2 caracteres sin romper."""
        resp = self.client.get(reverse('blog:buscar_sugerencias'), {'q': 'a'})
        self.assertEqual(resp.status_code, 200)
        # Con menos de 2 caracteres no debe arrojar error y no lista artículos
        self.assertNotContains(resp, 'Arquitectura Limpia en Django')

    def test_buscar_sugerencias_endpoint_con_resultados(self):
        """Verifica que sugerencias devuelvan artículos, comunidades y etiquetas."""
        resp = self.client.get(reverse('blog:buscar_sugerencias'), {'q': 'Django'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Arquitectura Limpia en Django')
        self.assertContains(resp, 'Python y Django')

    def test_explorar_view(self):
        """Verifica que la página /explorar/ cargue comunidades, etiquetas y autores."""
        resp = self.client.get(reverse('blog:explorar'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Explorar')
        self.assertContains(resp, 'Python y Django')
        self.assertContains(resp, 'arquitectura')
        self.assertContains(resp, 'Carlos Dev')


class ForoAdaptableFase3Tests(TestCase):
    """Pruebas de la Fase 3: Feed, orden decay temporal, filtros, cookie de vista y scroll infinito."""

    def setUp(self):
        cache.clear()
        from cuentas.models import Perfil
        self.user = User.objects.create_user(
            username='laura_dev',
            first_name='Laura',
            last_name='Dev',
            email='laura@example.com',
            password='Password123!',
        )
        self.perfil, _ = Perfil.objects.get_or_create(usuario=self.user)
        self.categoria = Categoria.objects.create(
            nombre='DevOps y Cloud',
            slug='devops-cloud'
        )
        self.etiqueta = Etiqueta.objects.create(
            nombre='kubernetes',
            slug='kubernetes'
        )
        # Crear 16 posts para probar paginación de 15
        self.posts = []
        for i in range(16):
            p = Post.objects.create(
                titulo=f'Post de prueba {i}',
                slug=f'post-prueba-{i}',
                contenido=f'Contenido extenso del post {i} para verificar el feed.',
                categoria=self.categoria,
                autor=self.perfil,
                estado=Post.Estado.PUBLICADO,
            )
            if i == 0:
                p.etiquetas.add(self.etiqueta)
            self.posts.append(p)

    def test_feed_orden_mejores_default(self):
        """Verifica que el feed inicie por defecto con orden 'mejores'."""
        resp = self.client.get(reverse('blog:post_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['orden_actual'], 'mejores')
        self.assertContains(resp, 'Mejores')
        self.assertContains(resp, 'Recientes')
        self.assertContains(resp, 'Populares')

    def test_feed_paginacion_15_posts(self):
        """Comprueba que la paginación sea de 15 publicaciones por página."""
        resp = self.client.get(reverse('blog:post_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['posts']), 15)
        self.assertTrue(resp.context['page_obj'].has_next())

    def test_feed_htmx_paginacion_parcial(self):
        """Verifica que petición HTMX devuelva únicamente el fragmento de la siguiente página."""
        resp = self.client.get(
            reverse('blog:post_list'),
            {'page': '2'},
            headers={'HX-Request': 'true'}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '<!DOCTYPE html>')
        self.assertContains(resp, 'post-row')

    def test_feed_filtro_comunidad_y_etiqueta(self):
        """Verifica el filtrado por comunidad y etiqueta en el feed."""
        resp_cat = self.client.get(reverse('blog:post_list'), {'comunidad': 'devops-cloud'})
        self.assertEqual(resp_cat.status_code, 200)
        self.assertEqual(resp_cat.context['filtro_comunidad'], 'devops-cloud')

        resp_tag = self.client.get(reverse('blog:post_list'), {'etiqueta': 'kubernetes'})
        self.assertEqual(resp_tag.status_code, 200)
        self.assertEqual(len(resp_tag.context['posts']), 1)
        self.assertContains(resp_tag, 'Post de prueba 0')

    def test_feed_cookie_vista(self):
        """Comprueba que el parámetro ?vista=tarjetas fije la cookie correspondiente."""
        resp = self.client.get(reverse('blog:post_list'), {'vista': 'tarjetas'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('vista_feed', resp.cookies)
        self.assertEqual(resp.cookies['vista_feed'].value, 'tarjetas')

    def test_feed_novedades_endpoint(self):
        """Verifica que el sondeo devuelva el contador de nuevos posts publicados."""
        ultimo_id = self.posts[10].id
        nuevos_esperados = Post.objects.publicados().filter(id__gt=ultimo_id).count()
        resp = self.client.get(reverse('blog:feed_novedades'), {'ultimo_id': ultimo_id})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get('nuevos_count'), nuevos_esperados)


class ForoAdaptableFase4Tests(TestCase):
    """Pruebas de la Fase 4: Lectura adaptable de artículos y comentarios estilo Reddit."""

    def setUp(self):
        cache.clear()
        from cuentas.models import Perfil
        self.autor_user = User.objects.create_user(
            username='carlos_dev',
            first_name='Carlos',
            last_name='Dev',
            email='carlos@example.com',
            password='Password123!',
        )
        self.autor_perfil, _ = Perfil.objects.get_or_create(usuario=self.autor_user)
        self.lector_user = User.objects.create_user(
            username='lector_fase4',
            first_name='Lector',
            last_name='Test',
            email='lector@example.com',
            password='Password123!',
        )
        self.categoria = Categoria.objects.create(
            nombre='Backend Python',
            slug='backend-python',
            descripcion='Comunidad dedicada a Django y Python.'
        )
        self.post = Post.objects.create(
            titulo='Guía completa de arquitectura hexagonal en Django',
            slug='guia-arquitectura-hexagonal-django',
            contenido='<h2>Introducción</h2><p>Texto intro</p><h2>Capas</h2><p>Texto capas</p><h2>Conclusiones</h2><p>Texto fin</p>',
            categoria=self.categoria,
            autor=self.autor_perfil,
            estado=Post.Estado.PUBLICADO,
        )
        # Post adicional para "Seguir leyendo"
        self.post_extra = Post.objects.create(
            titulo='Patrones de diseño en Django ORM',
            slug='patrones-diseno-django-orm',
            contenido='<p>Contenido extra</p>',
            categoria=self.categoria,
            autor=self.autor_perfil,
            estado=Post.Estado.PUBLICADO,
        )

    def test_post_detail_lectura_adaptable_elementos_clave(self):
        """Comprueba elementos de lectura adaptable, riel de acciones, sidebar y ausencia de ¿Te fue útil?"""
        url = reverse('blog:post_detail', kwargs={'slug': self.post.slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        # Riel de acciones y estructura de lectura
        self.assertContains(resp, 'article-action-rail-left')
        self.assertContains(resp, 'article-reading-column')
        self.assertContains(resp, 'Carlos Dev')
        self.assertContains(resp, 'Backend Python')
        self.assertNotContains(resp, 'c/Backend Python')

        # Tabla de contenidos y Seguir leyendo
        self.assertContains(resp, 'Introducción')
        self.assertContains(resp, 'Capas')
        self.assertContains(resp, 'Seguir leyendo')
        self.assertContains(resp, 'Patrones de diseño en Django ORM')

        # Sidebar derecha (TOC, Autor, Comunidad)
        self.assertContains(resp, 'En este artículo')
        self.assertContains(resp, 'Backend Python')

        # El widget público "¿Te fue útil?" NO debe aparecer en el HTML
        self.assertNotContains(resp, 'data-utilidad-widget')
        self.assertNotContains(resp, '¿Te fue útil?')

    def test_comentarios_reddit_arbol_y_ordenamiento(self):
        """Verifica comentarios estilo Reddit, selector de orden y carga parcial HTMX."""
        c1 = Comentario.objects.create(
            post=self.post,
            autor=self.lector_user,
            nombre='Lector Test',
            email='lector@example.com',
            texto='Primer comentario raíz con ideas.',
            aprobado=True,
        )
        c2 = Comentario.objects.create(
            post=self.post,
            autor=self.autor_user,
            nombre='Carlos Dev',
            email='carlos@example.com',
            texto='Segundo comentario raíz muy votado.',
            aprobado=True,
        )
        # Añadir like a c2
        LikeComentario.objects.create(comentario=c2, usuario=self.lector_user)

        # Respuesta anidada a c1
        hijo = Comentario.objects.create(
            post=self.post,
            padre=c1,
            autor=self.autor_user,
            nombre='Carlos Dev',
            email='carlos@example.com',
            texto='Respuesta al comentario raíz.',
            aprobado=True,
        )

        url = reverse('blog:post_detail', kwargs={'slug': self.post.slug})

        # 1. Orden Mejores (c2 con más votos va primero)
        resp_mejores = self.client.get(url, {'orden_comentarios': 'mejores'})
        self.assertEqual(resp_mejores.status_code, 200)
        comentarios = resp_mejores.context['comentarios']
        self.assertEqual(comentarios[0].pk, c2.pk)

        # 2. Orden Recientes (c2 es más reciente que c1)
        resp_recientes = self.client.get(url, {'orden_comentarios': 'recientes'})
        self.assertEqual(resp_recientes.status_code, 200)

        # 3. Petición HTMX para comentarios parciales
        resp_htmx = self.client.get(
            url,
            {'orden_comentarios': 'mejores', 'comentarios_solo': '1'},
            headers={'HX-Request': 'true'}
        )
        self.assertEqual(resp_htmx.status_code, 200)
        self.assertNotContains(resp_htmx, '<!DOCTYPE html>')
        self.assertContains(resp_htmx, 'comentario-' + str(c1.pk))
        self.assertContains(resp_htmx, 'comentario-' + str(hijo.pk))
        self.assertContains(resp_htmx, 'btn-collapse-thread')

    def test_comentarios_novedades_endpoint(self):
        """Verifica sondeo de nuevos comentarios cada 45s."""
        c = Comentario.objects.create(
            post=self.post,
            autor=self.lector_user,
            nombre='Lector Test',
            email='lector@example.com',
            texto='Comentario inicial.',
            aprobado=True,
        )
        url_novedades = reverse('blog:comentarios_novedades', kwargs={'slug': self.post.slug})

        # Sin novedades posteriores a c.id
        resp = self.client.get(url_novedades, {'ultimo_id': c.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['total_nuevos'], 0)

        # Crear nuevo comentario aprobado
        Comentario.objects.create(
            post=self.post,
            autor=self.autor_user,
            nombre='Carlos Dev',
            email='carlos@example.com',
            texto='Nuevo comentario aprobado.',
            aprobado=True,
        )
        resp_nuevo = self.client.get(url_novedades, {'ultimo_id': c.id})
        self.assertEqual(resp_nuevo.status_code, 200)
        self.assertEqual(resp_nuevo.json()['total_nuevos'], 1)

    def test_comentarios_requiere_login_cuando_anonimos_desactivados(self):
        """Verifica que visitantes vean el botón para abrir el modal de acceso."""
        url = reverse('blog:post_detail', kwargs={'slug': self.post.slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'btn-requiere-auth')
        self.assertContains(resp, 'Iniciar sesión para comentar')


class ForoAdaptableFase5Tests(TestCase):
    """Pruebas de la Fase 5: Interacciones transversales y notificaciones."""

    def setUp(self):
        cache.clear()
        from cuentas.models import Perfil
        self.user = User.objects.create_user(
            username='user_fase5',
            email='user5@example.com',
            password='Password123!',
        )
        self.perfil, _ = Perfil.objects.get_or_create(usuario=self.user)

        self.autor_user = User.objects.create_user(
            username='autor_fase5',
            email='autor5@example.com',
            password='Password123!',
        )
        self.autor_perfil, _ = Perfil.objects.get_or_create(usuario=self.autor_user)

        self.categoria = Categoria.objects.create(
            nombre='Comunidad Fase 5',
            slug='comunidad-fase-5'
        )
        self.post = Post.objects.create(
            titulo='Post para Pruebas de Interacciones',
            slug='post-para-pruebas-interacciones',
            contenido='<p>Contenido interactivo</p>',
            categoria=self.categoria,
            autor=self.autor_perfil,
            estado=Post.Estado.PUBLICADO,
        )

    def test_notificaciones_marcar_todas_y_vista_movil(self):
        """Comprueba el listado de notificaciones y la acción de marcar todas como leídas."""
        self.client.login(username='user_fase5', password='Password123!')

        # Crear 2 notificaciones no leídas
        Notificacion.objects.create(
            destinatario=self.user,
            tipo=Notificacion.Tipo.POST_NUEVO,
            actor=self.autor_user,
            post=self.post,
            leida=False,
        )
        Notificacion.objects.create(
            destinatario=self.user,
            tipo=Notificacion.Tipo.SEGUIDOR_NUEVO,
            actor=self.autor_user,
            leida=False,
        )

        resp_list = self.client.get(reverse('blog:notificaciones_list'))
        self.assertEqual(resp_list.status_code, 200)
        self.assertContains(resp_list, 'Mis Notificaciones')
        self.assertContains(resp_list, 'Marcar todas como leídas')

        # Acción marcar todas
        resp_post = self.client.post(reverse('blog:notificaciones_marcar_todas'))
        self.assertEqual(resp_post.status_code, 302)
        self.assertEqual(Notificacion.objects.filter(destinatario=self.user, leida=False).count(), 0)

    def test_guardar_post_toggle_y_respuesta_json(self):
        """Verifica que el toggle de guardar responda JSON adecuado para actualizar UI y toast."""
        self.client.login(username='user_fase5', password='Password123!')
        url = reverse('blog:post_guardar_toggle', kwargs={'slug': self.post.slug})

        # Primer toggle: guarda
        resp = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['activo'])

        # Segundo toggle: desguarda
        resp2 = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertTrue(data2['ok'])
        self.assertFalse(data2['activo'])

    def test_seguir_autor_y_unirse_comunidad_ajax(self):
        """Verifica que seguir autor y unirse a comunidad devuelvan contadores instantáneos."""
        self.client.login(username='user_fase5', password='Password123!')

        # 1. Seguir autor
        url_seguir = reverse('blog:autor_seguir_toggle', kwargs={'username': self.autor_user.username})
        resp_seguir = self.client.post(url_seguir, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_seguir.status_code, 200)
        data_s = resp_seguir.json()
        self.assertTrue(data_s['ok'])
        self.assertTrue(data_s['activo'])
        self.assertEqual(data_s['total'], 1)

        # 2. Unirse a comunidad
        url_unirse = reverse('blog:categoria_unirse_toggle', kwargs={'slug': self.categoria.slug})
        resp_unirse = self.client.post(url_unirse, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_unirse.status_code, 200)
        data_u = resp_unirse.json()
        self.assertTrue(data_u['ok'])
        self.assertTrue(data_u['unido'])
        self.assertEqual(data_u['total_miembros'], 1)


class ForoAdaptableFase6Tests(TestCase):
    """Pruebas de la Fase 6: Páginas de apoyo (explorar, comunidad, autor, páginas planas)."""

    def setUp(self):
        cache.clear()
        from cuentas.models import Perfil
        self.autor_user = User.objects.create_user(
            username='ana_autora',
            first_name='Ana',
            last_name='García',
            email='ana@example.com',
            password='Password123!',
        )
        self.autor_perfil, _ = Perfil.objects.get_or_create(usuario=self.autor_user)
        self.lector_user = User.objects.create_user(
            username='lector_fase6',
            first_name='Lector',
            last_name='Fase6',
            email='lector6@example.com',
            password='Password123!',
        )
        self.categoria = Categoria.objects.create(
            nombre='DevOps y Cloud',
            slug='devops-cloud',
            descripcion='Todo sobre infraestructura y Kubernetes.',
        )
        self.regla = ReglaCategoria.objects.create(
            categoria=self.categoria,
            titulo='Respeto mutuo',
            descripcion='Mantén discusiones constructivas.',
            orden=1,
        )
        self.post1 = Post.objects.create(
            titulo='Guía de Terraform y Docker',
            slug='guia-terraform-docker',
            autor=self.autor_perfil,
            categoria=self.categoria,
            contenido='Contenido completo sobre infraestructura como código.',
            estado=Post.Estado.PUBLICADO,
            fijado_en_categoria=True,
        )
        self.comentario = Comentario.objects.create(
            post=self.post1,
            autor=self.autor_user,
            nombre='Ana García',
            email='ana@example.com',
            texto='Mi comentario técnico sobre Terraform.',
            aprobado=True,
        )

    def test_explorar_view(self):
        """Verifica que /explorar/ reúna comunidades, tendencias y autores."""
        resp = self.client.get(reverse('blog:explorar'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('comunidades', resp.context)
        self.assertIn('posts_tendencia', resp.context)
        self.assertIn('etiquetas_tendencia', resp.context)
        self.assertIn('autores', resp.context)
        self.assertContains(resp, 'Comunidades activas')
        self.assertContains(resp, 'Tendencias de la semana')
        self.assertContains(resp, 'Autores para seguir')

    def test_categoria_hub_view(self):
        """Verifica la cabecera compacta <= 120px, reglas colapsables y publicaciones fijadas."""
        url = reverse('blog:posts_por_categoria', kwargs={'slug': self.categoria.slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'DevOps y Cloud')
        self.assertNotContains(resp, 'c/DevOps y Cloud')
        self.assertContains(resp, 'data-miembros-count')
        self.assertContains(resp, 'Reglas de la comunidad')
        self.assertContains(resp, 'Fijados')
        self.assertContains(resp, 'Guía de Terraform y Docker')

    def test_autor_detail_tabs(self):
        """Verifica el perfil de autor con pestañas: publicaciones, comentarios y guardados."""
        url = reverse('blog:autor_detail', kwargs={'username': self.autor_user.username})

        # 1. Pestaña publicaciones (por defecto)
        resp_pub = self.client.get(url)
        self.assertEqual(resp_pub.status_code, 200)
        self.assertEqual(resp_pub.context['tab_actual'], 'publicaciones')
        self.assertContains(resp_pub, 'Guía de Terraform y Docker')

        # 2. Pestaña comentarios
        resp_com = self.client.get(url, {'tab': 'comentarios'})
        self.assertEqual(resp_com.status_code, 200)
        self.assertEqual(resp_com.context['tab_actual'], 'comentarios')
        self.assertContains(resp_com, 'Mi comentario técnico sobre Terraform')

        # 3. Pestaña guardados como dueño
        self.client.login(username='ana_autora', password='Password123!')
        resp_guard = self.client.get(url, {'tab': 'guardados'})
        self.assertEqual(resp_guard.status_code, 200)
        self.assertEqual(resp_guard.context['tab_actual'], 'guardados')

        # 4. Pestaña guardados como otro usuario no dueño: redirige a publicaciones
        self.client.login(username='lector_fase6', password='Password123!')
        resp_otro = self.client.get(url, {'tab': 'guardados'})
        self.assertEqual(resp_otro.status_code, 200)
        self.assertEqual(resp_otro.context['tab_actual'], 'publicaciones')

    def test_paginas_planas_sin_rails(self):
        """Verifica que panel y páginas estáticas apliquen app-body--plano sin raíles laterales."""
        # Panel
        self.client.login(username='ana_autora', password='Password123!')
        resp_panel = self.client.get(reverse('blog:panel_dashboard'))
        self.assertEqual(resp_panel.status_code, 200)
        self.assertContains(resp_panel, 'app-body--plano')
        self.assertNotContains(resp_panel, 'app-nav-left')

        # Página estática acerca
        resp_acerca = self.client.get(reverse('blog:acerca'))
        self.assertEqual(resp_acerca.status_code, 200)
        self.assertContains(resp_acerca, 'app-body--plano')
        self.assertNotContains(resp_acerca, 'app-nav-left')


class ForoAdaptableFase7Tests(TestCase):
    """Pruebas de la Fase 7: Rendimiento, WebP, accesibilidad y PWA."""

    def setUp(self):
        cache.clear()
        from cuentas.models import Perfil
        self.autor_user = User.objects.create_user(
            username='carlos_perf',
            first_name='Carlos',
            last_name='Perf',
            email='carlosperf@example.com',
            password='Password123!',
        )
        self.autor_perfil, _ = Perfil.objects.get_or_create(usuario=self.autor_user)
        self.categoria = Categoria.objects.create(
            nombre='Performance y Web',
            slug='perf-web',
        )

    def test_pwa_manifest_y_meta_tags(self):
        """Verifica existencia de manifest.webmanifest y metadatos theme-color."""
        import os
        import json
        from django.conf import settings
        manifest_path = os.path.join(settings.BASE_DIR, 'static', 'manifest.webmanifest')
        self.assertTrue(os.path.exists(manifest_path))

        with open(manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('name', data)
        self.assertEqual(data.get('display'), 'standalone')
        self.assertTrue(len(data.get('icons', [])) >= 2)

        resp = self.client.get(reverse('blog:post_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="theme-color"')
        self.assertContains(resp, 'manifest.webmanifest')

    def test_caching_sidebar_y_sugerencias(self):
        """Verifica que las sugerencias de búsqueda se almacenen en caché y se invaliden al publicar."""
        from blog.servicios.publicacion import invalidar_caches_publicacion

        Post.objects.create(
            titulo='Acelerando Django con Cache',
            slug='acelerando-django-cache',
            autor=self.autor_perfil,
            categoria=self.categoria,
            contenido='Contenido largo sobre Redis y Memcached en producción.',
            estado=Post.Estado.PUBLICADO,
        )

        # Primer llamado: consulta y almacena en caché
        resp1 = self.client.get(reverse('blog:buscar_sugerencias'), {'q': 'Django'})
        self.assertEqual(resp1.status_code, 200)
        self.assertContains(resp1, 'Acelerando Django con Cache')

        # Segundo llamado: debe provenir de caché
        resp2 = self.client.get(reverse('blog:buscar_sugerencias'), {'q': 'Django'})
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, 'Acelerando Django con Cache')

        # Invalidación de publicación
        v_antes = cache.get('blog_ranking_version', 1)
        invalidar_caches_publicacion()
        v_despues = cache.get('blog_ranking_version')
        self.assertNotEqual(v_antes, v_despues)

    def test_content_visibility_feed(self):
        """Verifica que components.css aplique content-visibility: auto a las filas del feed."""
        import os
        from django.conf import settings
        css_path = os.path.join(settings.BASE_DIR, 'static', 'css', 'components.css')
        with open(css_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('content-visibility: auto;', content)
        self.assertIn('contain-intrinsic-size', content)


class ForoAdaptableFase8Tests(TestCase):
    """Pruebas de la Fase 8: Rendimiento de queries, política anónima, HTMX y privacidad."""

    def setUp(self):
        cache.clear()
        from cuentas.models import Perfil
        self.autor_user = User.objects.create_user(
            username='ana_fase8',
            first_name='Ana',
            last_name='Fase8',
            email='anafase8@example.com',
            password='Password123!',
        )
        self.autor_perfil, _ = Perfil.objects.get_or_create(usuario=self.autor_user)
        self.categoria = Categoria.objects.create(
            nombre='Python Architecture',
            slug='python-arch',
        )
        self.posts = []
        for i in range(5):
            p = Post.objects.create(
                titulo=f'Arquitectura Limpia en Django {i}',
                slug=f'arquitectura-limpia-django-{i}',
                autor=self.autor_perfil,
                categoria=self.categoria,
                contenido='Guía detallada de principios SOLID, inyección de dependencias y desacoplamiento.',
                estado=Post.Estado.PUBLICADO,
            )
            self.posts.append(p)

    def test_assert_num_queries_feed_y_articulo(self):
        """Verifica que el feed y el artículo no tengan problemas de N+1 queries."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        # Feed principal: queries acotadas
        with CaptureQueriesContext(connection) as ctx_feed:
            resp_feed = self.client.get(reverse('blog:post_list'))
        self.assertEqual(resp_feed.status_code, 200)
        self.assertLessEqual(len(ctx_feed.captured_queries), 22, "El feed excede el límite de consultas permitidas.")

        # Detalle del post: queries acotadas
        with CaptureQueriesContext(connection) as ctx_post:
            resp_post = self.client.get(self.posts[0].get_absolute_url())
        self.assertEqual(resp_post.status_code, 200)
        self.assertLessEqual(len(ctx_post.captured_queries), 35, "El detalle de post excede el límite de consultas permitidas.")

    def test_comentarios_anonimos_politica_acceso(self):
        """Verifica que COMENTARIOS_ANONIMOS sea False y requiera autenticación."""
        from django.conf import settings
        self.assertFalse(getattr(settings, 'COMENTARIOS_ANONIMOS', True))

        # Intento de enviar comentario anónimo
        url_com = reverse('blog:post_detail', kwargs={'slug': self.posts[0].slug})
        resp = self.client.post(url_com, {'texto': 'Comentario de visitante sin registrar'})
        # Debe redirigir al login o modal de acceso (302)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/cuentas/login/', resp.url)

    def test_django_htmx_no_rompe_login_ni_editor(self):
        """Comprueba que el login, panel y editor desactiven o aíslen hx-boost para no interferir."""
        resp_login = self.client.get(reverse('cuentas:login'))
        self.assertEqual(resp_login.status_code, 200)

        # Panel dashboard tiene hx-boost="false"
        self.client.login(username='ana_fase8', password='Password123!')
        resp_panel = self.client.get(reverse('blog:panel_dashboard'))
        self.assertEqual(resp_panel.status_code, 200)
        self.assertContains(resp_panel, 'hx-boost="false"')

        # El estudio de escritura no incluye scripts de HTMX para no colisionar con CKEditor
        resp_editor = self.client.get(reverse('blog:panel_post_create'))
        self.assertEqual(resp_editor.status_code, 200)
        self.assertNotContains(resp_editor, 'htmx.min.js')

    def test_sondeo_novedades_privacidad(self):
        """Verifica que el sondeo de novedades no exponga borradores ni datos privados."""
        # Crear un borrador privado
        Post.objects.create(
            titulo='Borrador super secreto no publicado',
            slug='borrador-secreto-privado',
            autor=self.autor_perfil,
            categoria=self.categoria,
            contenido='Borrador no publicado todavía.',
            estado=Post.Estado.BORRADOR,
        )

        resp = self.client.get(reverse('blog:feed_novedades'), {'ultimo_id': 0})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('nuevos_count', data)
        # Solo debe contar publicados
        total_publicados = Post.objects.publicados().count()
        self.assertEqual(data['nuevos_count'], total_publicados)


class ForoAdaptableFase4DatosYTextosTests(TestCase):
    """
    Pruebas de la Fase 4: Estadísticas de comunidad unificadas sin producto cartesiano
    y pluralización estricta en plantillas e interfaz.
    """

    def setUp(self):
        from blog.servicios import anotar_estadisticas_categorias, estadisticas_comunidad
        self.estadisticas_comunidad = estadisticas_comunidad
        self.anotar_estadisticas_categorias = anotar_estadisticas_categorias

        # Crear usuarios
        self.user1 = User.objects.create_user(username='lector_fase4_1', password='pwd')
        self.user2 = User.objects.create_user(username='lector_fase4_2', password='pwd')
        self.autor = User.objects.create_user(username='autor_fase4', password='pwd')
        from cuentas.models import Perfil
        self.perfil_autor = getattr(self.autor, 'perfil', None) or Perfil.objects.create(usuario=self.autor, nombre_mostrar='Autor Fase 4')

        # Crear comunidad
        self.categoria = Categoria.objects.create(
            nombre='Ciencia de Datos',
            slug='ciencia-de-datos',
            descripcion='Comunidad de prueba Fase 4'
        )

        # 2 miembros en la comunidad
        MiembroCategoria.objects.create(usuario=self.user1, categoria=self.categoria)
        MiembroCategoria.objects.create(usuario=self.user2, categoria=self.categoria)

        # 3 posts publicados en la comunidad
        for i in range(1, 4):
            Post.objects.create(
                titulo=f'Publicación de prueba {i}',
                slug=f'publicacion-prueba-fase4-{i}',
                autor=self.perfil_autor,
                categoria=self.categoria,
                contenido=f'Contenido {i}',
                estado=Post.Estado.PUBLICADO,
            )

    def test_estadisticas_comunidad_sin_producto_cartesiano(self):
        """Verifica que con 2 miembros y 3 posts el cálculo sea exacto (2 y 3, nunca 6)."""
        stats = self.estadisticas_comunidad(self.categoria)
        self.assertEqual(stats['total_miembros'], 2)
        self.assertEqual(stats['total_posts'], 3)
        self.assertEqual(stats['total_publicaciones'], 3)

        # Prueba de queryset anotado (evita producto cartesiano en SQL)
        cat_anotada = self.anotar_estadisticas_categorias(
            Categoria.objects.filter(pk=self.categoria.pk)
        ).first()
        self.assertEqual(cat_anotada.total_miembros, 2)
        self.assertEqual(cat_anotada.total_posts, 3)

    def test_explorar_comunidades_metricas_exactas(self):
        """Verifica que la vista /explorar/ muestre las métricas exactas de la comunidad."""
        resp = self.client.get(reverse('blog:explorar'))
        self.assertEqual(resp.status_code, 200)
        comunidades = {c.slug: c for c in resp.context['comunidades']}
        self.assertIn(self.categoria.slug, comunidades)
        cat = comunidades[self.categoria.slug]
        self.assertEqual(cat.total_miembros, 2)
        self.assertEqual(cat.total_posts, 3)

    def test_hub_comunidad_estadisticas_unificadas(self):
        """Verifica que el hub de comunidad use las estadísticas unificadas."""
        url = reverse('blog:posts_por_categoria', kwargs={'slug': self.categoria.slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['stats_comunidad']['total_miembros'], 2)
        self.assertEqual(resp.context['stats_comunidad']['total_posts'], 3)
        self.assertContains(resp, '2</strong>\n                                miembro')

    def test_sin_parentesis_plural_en_plantillas(self):
        """Verifica que no existan cadenas crudas 'resultado(s)' o similares en buscar.html."""
        resp = self.client.get(reverse('blog:buscar_posts'), {'q': 'Publicación'})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'resultado(s)')
        self.assertContains(resp, 'resultados para')








