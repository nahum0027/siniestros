from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    # acceso
    path("entrar/", auth_views.LoginView.as_view(template_name="siniestros/entrar.html",
                                                 redirect_authenticated_user=True), name="entrar"),
    path("salir/", auth_views.LogoutView.as_view(), name="salir"),
    path("inicio/", views.inicio, name="inicio"),
    path("cuenta/contrasena/", views.cambiar_contrasena, name="cambiar_contrasena"),
    # campo
    path("", views.formulario, name="formulario"),
    path("api/enviar/", views.enviar, name="enviar"),
    # oficina
    path("reportes/", views.lista, name="lista"),
    path("reportes/<str:folio>/", views.detalle, name="detalle"),
    path("reportes/<str:folio>/editar/", views.editar, name="editar"),
    path("reportes/<str:folio>/estado/", views.cambiar_estado, name="estado"),
    path("reportes/<str:folio>/imagen/<str:nombre>", views.imagen, name="imagen"),
    path("api/reportes/<str:folio>/", views.guardar_edicion, name="guardar_edicion"),
    path("descargar/<str:folio>/<str:archivo>", views.descargar, name="descargar"),
    # app instalable
    path("sw.js", views.service_worker, name="sw"),
    path("manifest.json", views.manifest, name="manifest"),
]
