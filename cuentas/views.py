from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
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

