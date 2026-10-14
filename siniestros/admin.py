from django.contrib import admin

from .models import Cambio, Siniestro


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
