from django.contrib import admin

from .models import Cambio, ReporteBorrado, Siniestro


class CambioInline(admin.TabularInline):
    model = Cambio
    extra = 0
    can_delete = False
    fields = ("fecha", "usuario", "tipo", "descripcion")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Siniestro)
class SiniestroAdmin(admin.ModelAdmin):
    list_display = ("folio", "fecha_hecho", "ruta", "economico", "ejecutivo", "estado", "capturado_por", "creado")
    list_filter = ("estado", "fecha_hecho")
    search_fields = ("folio", "ruta", "economico", "ejecutivo", "lugar")
    readonly_fields = ("folio", "id_cliente", "capturado_por", "creado", "actualizado", "validado_por",
                       "validado_en", "correo_enviado_en", "correo_error", "datos")
    fields = ("folio", "estado") + readonly_fields[1:]
    inlines = [CambioInline]

    def has_add_permission(self, request):
        return False  # los siniestros solo se capturan desde el formulario


@admin.register(Cambio)
class CambioAdmin(admin.ModelAdmin):
    list_display = ("siniestro", "fecha", "usuario", "tipo", "descripcion")
    list_filter = ("tipo",)
    search_fields = ("siniestro__folio", "usuario__username")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ------------------------------------------------------------------ usuarios
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm

from .models import Perfil

User = get_user_model()


class PerfilInline(admin.StackedInline):
    model = Perfil
    can_delete = False
    fields = ("debe_cambiar_contrasena", "contrasena_cambiada_en")
    readonly_fields = ("contrasena_cambiada_en",)
    verbose_name_plural = "Contraseña"


class ContrasenaTemporalForm(AdminPasswordChangeForm):
    """Cuando un administrador le pone contraseña a alguien, esa contraseña es temporal."""

    def save(self, commit=True):
        user = super().save(commit=commit)
        Perfil.objects.update_or_create(usuario=user, defaults={"debe_cambiar_contrasena": True})
        return user


admin.site.unregister(User)


@admin.register(User)
class UsuarioAdmin(UserAdmin):
    inlines = [PerfilInline]
    change_password_form = ContrasenaTemporalForm
    list_display = ("username", "first_name", "last_name", "grupos", "is_active", "last_login")
    list_filter = ("groups", "is_active", "is_staff")

    @admin.display(description="Roles")
    def grupos(self, obj):
        return ", ".join(g.name for g in obj.groups.all()) or "—"

    def get_inline_instances(self, request, obj=None):
        # Al crear el usuario, el perfil lo crea la señal (obligado a cambiar contraseña)
        return super().get_inline_instances(request, obj) if obj else []


@admin.register(ReporteBorrado)
class ReporteBorradoAdmin(admin.ModelAdmin):
    list_display = ("folio", "tipo", "ejecutivo", "fecha_hecho", "borrado_por", "borrado_en")
    list_filter = ("tipo", "borrado_en")
    search_fields = ("folio", "ejecutivo", "motivo", "borrado_por__username")
    readonly_fields = ("folio", "tipo", "ejecutivo", "fecha_hecho", "capturado_por", "creado", "datos",
                       "motivo", "borrado_por", "borrado_en")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
