import json
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, UpdateView

from .forms import (
    CambioPasswordForm,
    LoginForm,
    PasswordResetBootstrapForm,
    PerfilForm,
    RegistroUsuarioForm,
    SetPasswordBootstrapForm,
)
from .models import Perfil


class RegistroView(CreateView):
    form_class = RegistroUsuarioForm
    template_name = 'cuentas/registro.html'
    success_url = reverse_lazy('blog:panel_dashboard')

    def form_valid(self, form):
        response = super().form_valid(form)
        login(
            self.request,
            self.object,
            backend='django.contrib.auth.backends.ModelBackend',
        )
        user = self.object
        perfil = getattr(user, 'perfil', None)
        nombre = (perfil.nombre_mostrar if perfil else '') or user.get_full_name() or user.username
        messages.success(
            self.request,
            f'¡Bienvenido/a, {nombre}! Tu cuenta y perfil de autor han sido creados.'
        )
        return response


class CustomLoginView(auth_views.LoginView):
    form_class = LoginForm
    template_name = 'cuentas/login.html'
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        perfil = getattr(user, 'perfil', None)
        nombre = (perfil.nombre_mostrar if perfil else '') or user.get_full_name() or user.username
        messages.success(self.request, f'Has iniciado sesión como {nombre}.')
        return super().form_valid(form)


class CustomLogoutView(auth_views.LogoutView):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            messages.info(request, 'Has cerrado sesión correctamente.')
        return super().dispatch(request, *args, **kwargs)


class CustomPasswordChangeView(LoginRequiredMixin, auth_views.PasswordChangeView):
    form_class = CambioPasswordForm
    template_name = 'cuentas/password_change_form.html'
    success_url = reverse_lazy('cuentas:password_change_done')

    def form_valid(self, form):
        messages.success(self.request, 'Tu contraseña ha sido actualizada exitosamente.')
        return super().form_valid(form)


class CustomPasswordChangeDoneView(LoginRequiredMixin, auth_views.PasswordChangeDoneView):
    template_name = 'cuentas/password_change_done.html'


class EditarPerfilView(LoginRequiredMixin, UpdateView):
    model = Perfil
    form_class = PerfilForm
    template_name = 'cuentas/perfil_form.html'
    success_url = reverse_lazy('cuentas:editar_perfil')

    def get_object(self, queryset=None):
        perfil, _ = Perfil.objects.get_or_create(usuario=self.request.user)
        return perfil

    def form_valid(self, form):
        messages.success(self.request, 'Tu perfil de autor se ha actualizado correctamente.')
        return super().form_valid(form)


class CustomPasswordResetView(auth_views.PasswordResetView):
    form_class = PasswordResetBootstrapForm
    template_name = 'cuentas/password_reset_form.html'
    email_template_name = 'cuentas/password_reset_email.html'
    subject_template_name = 'cuentas/password_reset_subject.txt'
    success_url = reverse_lazy('cuentas:password_reset_done')


class CustomPasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = 'cuentas/password_reset_done.html'


class CustomPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    form_class = SetPasswordBootstrapForm
    template_name = 'cuentas/password_reset_confirm.html'
    success_url = reverse_lazy('cuentas:password_reset_complete')


class CustomPasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'cuentas/password_reset_complete.html'


class AjustesView(LoginRequiredMixin, View):
    """
    Panel centralizado de ajustes con 4 pestañas:
    - perfil: Nombre, apellidos, biografía, avatar (recorte inteligente 256x256).
    - apariencia: Tema visual, tamaño de fuente y orden de feed.
    - notificaciones: Preferencias de avisos en la web y boletines.
    - seguridad: Cambio de contraseña, datos de sesión y exportación de datos.
    """
    template_name = 'cuentas/ajustes.html'

    def get_perfil(self, user):
        perfil, _ = Perfil.objects.get_or_create(usuario=user)
        return perfil

    def get(self, request, tab='perfil', *args, **kwargs):
        tab_valida = tab if tab in ('perfil', 'apariencia', 'feed', 'notificaciones', 'seguridad') else 'perfil'
        perfil = self.get_perfil(request.user)

        perfil_form = PerfilForm(instance=perfil)
        password_form = CambioPasswordForm(user=request.user)

        context = {
            'tab_activa': tab_valida,
            'perfil': perfil,
            'perfil_form': perfil_form,
            'password_form': password_form,
            'seccion_gestion': 'ajustes',
        }
        return render(request, self.template_name, context)

    def post(self, request, tab='perfil', *args, **kwargs):
        tab_post = request.POST.get('tab_destino', tab)
        tab_valida = tab_post if tab_post in ('perfil', 'apariencia', 'feed', 'notificaciones', 'seguridad') else 'perfil'
        perfil = self.get_perfil(request.user)

        perfil_form = PerfilForm(instance=perfil)
        password_form = CambioPasswordForm(user=request.user)

        if tab_valida == 'perfil':
            form = PerfilForm(request.POST, request.FILES, instance=perfil)
            if form.is_valid():
                form.save()
                messages.success(request, 'Tu perfil e información pública han sido actualizados.')
                return redirect(reverse('cuentas:ajustes_tab', kwargs={'tab': 'perfil'}))
            perfil_form = form

        elif tab_valida == 'seguridad':
            form = CambioPasswordForm(user=request.user, data=request.POST)
            if form.is_valid():
                form.save()
                update_session_auth_hash(request, form.user)
                messages.success(request, 'Tu contraseña ha sido cambiada correctamente.')
                return redirect(reverse('cuentas:ajustes_tab', kwargs={'tab': 'seguridad'}))
            password_form = form

        elif tab_valida == 'apariencia':
            tema = request.POST.get('tema', 'dark')
            acento = request.POST.get('acento', 'indigo')
            fuente = request.POST.get('tamano_fuente', 'md')
            tipografia = request.POST.get('tipografia', 'inter')
            ancho = request.POST.get('ancho_lectura', 'normal')

            messages.success(request, 'Preferencias de lectura y apariencia guardadas.')
            response = redirect(reverse('cuentas:ajustes_tab', kwargs={'tab': 'apariencia'}))
            response.set_cookie('foro_tema', tema, max_age=365*24*60*60, samesite='Lax')
            response.set_cookie('foro_acento', acento, max_age=365*24*60*60, samesite='Lax')
            response.set_cookie('foro_fuente', fuente, max_age=365*24*60*60, samesite='Lax')
            response.set_cookie('foro_tipografia', tipografia, max_age=365*24*60*60, samesite='Lax')
            response.set_cookie('foro_ancho', ancho, max_age=365*24*60*60, samesite='Lax')
            return response

        elif tab_valida == 'feed':
            orden_inicio = request.POST.get('orden_inicio', 'mejores')
            etiquetas_silenciadas = request.POST.get('etiquetas_silenciadas', '')
            messages.success(request, 'Tus preferencias de feed han sido guardadas.')
            response = redirect(reverse('cuentas:ajustes_tab', kwargs={'tab': 'feed'}))
            response.set_cookie('foro_orden_inicio', orden_inicio, max_age=365*24*60*60, samesite='Lax')
            response.set_cookie('foro_silenciadas', etiquetas_silenciadas, max_age=365*24*60*60, samesite='Lax')
            return response

        elif tab_valida == 'notificaciones':
            messages.success(request, 'Tus preferencias de notificaciones han sido actualizadas.')
            return redirect(reverse('cuentas:ajustes_tab', kwargs={'tab': 'notificaciones'}))

        context = {
            'tab_activa': tab_valida,
            'perfil': perfil,
            'perfil_form': perfil_form,
            'password_form': password_form,
            'seccion_gestion': 'ajustes',
        }
        return render(request, self.template_name, context)


class ExportarMisDatosView(LoginRequiredMixin, View):
    """Genera un archivo JSON con toda la actividad pública y privada del usuario para portabilidad de datos."""

    def get(self, request, *args, **kwargs):
        user = request.user
        perfil = getattr(user, 'perfil', None)

        posts_data = []
        if perfil and hasattr(perfil, 'posts'):
            for p in perfil.posts.all().order_by('-creado'):
                posts_data.append({
                    'id': p.id,
                    'titulo': p.titulo,
                    'slug': p.slug,
                    'estado': p.estado,
                    'creado': p.creado.isoformat() if p.creado else None,
                    'publicado_en': p.publicado_en.isoformat() if p.publicado_en else None,
                    'total_likes': p.total_likes,
                    'total_comentarios': getattr(p, 'total_comentarios_aprobados', 0),
                })

        comentarios_data = []
        if hasattr(user, 'comentarios_realizados'):
            for c in user.comentarios_realizados.all().order_by('-creado'):
                comentarios_data.append({
                    'id': c.id,
                    'post_titulo': c.post.titulo,
                    'post_slug': c.post.slug,
                    'creado': c.creado.isoformat() if c.creado else None,
                    'contenido': c.contenido,
                })

        datos = {
            'usuario': {
                'username': user.username,
                'email': user.email,
                'nombre': user.first_name,
                'apellidos': user.last_name,
                'fecha_registro': user.date_joined.isoformat() if user.date_joined else None,
                'biografia': perfil.bio if perfil else '',
            },
            'publicaciones': posts_data,
            'comentarios': comentarios_data,
        }

        contenido_json = json.dumps(datos, ensure_ascii=False, indent=2)
        response = HttpResponse(contenido_json, content_type='application/json; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="mis_datos_foro_{user.username}.json"'
        return response

