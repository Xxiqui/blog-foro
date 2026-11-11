from django.urls import path
from . import views

app_name = 'cuentas'

urlpatterns = [
    path('registro/', views.RegistroView.as_view(), name='registro'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.CustomLogoutView.as_view(), name='logout'),
    path('password/cambiar/', views.CustomPasswordChangeView.as_view(), name='password_change'),
    path('password/cambiada/', views.CustomPasswordChangeDoneView.as_view(), name='password_change_done'),
    path('password/recuperar/', views.CustomPasswordResetView.as_view(), name='password_reset'),
    path('password/recuperar/enviado/', views.CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password/recuperar/<uidb64>/<token>/', views.CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password/recuperar/completado/', views.CustomPasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path('perfil/', views.EditarPerfilView.as_view(), name='editar_perfil'),
    path('ajustes/', views.AjustesView.as_view(), name='ajustes'),
    path('ajustes/exportar/datos/', views.ExportarMisDatosView.as_view(), name='exportar_datos'),
    path('ajustes/<str:tab>/', views.AjustesView.as_view(), name='ajustes_tab'),
]

