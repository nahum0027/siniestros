from pathlib import Path

from django.conf import settings
from django.db import models


class Siniestro(models.Model):
    class Estado(models.TextChoices):
        ENVIADO = "ENVIADO", "Enviado desde campo"
        REVISION = "REVISION", "En revisión"
        VALIDADO = "VALIDADO", "Validado"

    class Tipo(models.TextChoices):
        SINIESTRO = "SINIESTRO", "Siniestro (campo)"
        LIBERACION = "LIBERACION", "Liberación exprés"

    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.SINIESTRO, db_index=True)
    folio = models.CharField(max_length=40, unique=True)
    id_cliente = models.CharField(max_length=64, unique=True,
                                  help_text="Id que genera el celular; evita duplicados si se reintenta el envío")
    datos = models.JSONField(default=dict, help_text="Todo lo capturado (sin imágenes; esas van en archivos)")
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ENVIADO, db_index=True)

    capturado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="siniestros_capturados")
    creado = models.DateTimeField(auto_now_add=True, db_index=True)
    actualizado = models.DateTimeField(auto_now=True)
    validado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                     related_name="siniestros_validados")
    validado_en = models.DateTimeField(null=True, blank=True)

    correo_enviado_en = models.DateTimeField(null=True, blank=True)
    correo_error = models.TextField(blank=True)

    # Campos copiados de `datos` para poder buscar y ordenar rápido
    fecha_hecho = models.DateField(null=True, blank=True, db_index=True)
    ruta = models.CharField(max_length=40, blank=True, db_index=True)
    economico = models.CharField(max_length=40, blank=True)
    ejecutivo = models.CharField(max_length=150, blank=True)
    lugar = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ["-creado"]
        permissions = [
            ("capturar_siniestro", "Puede capturar siniestros en campo"),
            ("revisar_siniestro", "Puede consultar, editar y validar todos los siniestros"),
            ("reabrir_siniestro", "Puede reabrir siniestros validados"),
        ]

    def __str__(self):
        return self.folio

    @property
    def carpeta(self) -> Path:
        return Path(settings.SINIESTROS_DIR) / self.folio

    @property
    def es_liberacion(self):
        return self.tipo == self.Tipo.LIBERACION

    @property
    def estado_texto(self):
        if self.es_liberacion and self.estado == self.Estado.ENVIADO:
            return "Por revisar"
        return self.get_estado_display()

    @property
    def bloqueado(self):
        return self.estado == self.Estado.VALIDADO

    def documentos(self):
        if not self.carpeta.exists():
            return []
        return sorted(p.name for p in self.carpeta.iterdir() if p.suffix in (".docx", ".xlsx", ".pdf"))

    def copiar_resumen(self):
        """Actualiza los campos de búsqueda a partir de `datos`."""
        from datetime import date
        d = self.datos or {}
        try:
            self.fecha_hecho = date.fromisoformat(d.get("fecha") or "")
        except ValueError:
            self.fecha_hecho = None
        self.ruta = (d.get("ruta") or "")[:40]
        self.economico = (d.get("economico") or "")[:40]
        self.ejecutivo = ((d.get("a") or {}).get("nombre") or d.get("ejecutivo") or "")[:150]
        self.lugar = (d.get("lugar") or d.get("ubicacion") or "")[:250]


class Cambio(models.Model):
    """Historial: quién hizo qué y cuándo. Nunca se edita ni se borra."""

    class Tipo(models.TextChoices):
        CREADO = "CREADO", "Capturado en campo"
        EDITADO = "EDITADO", "Editado"
        ESTADO = "ESTADO", "Cambio de estado"
        CORREO = "CORREO", "Correo"

    siniestro = models.ForeignKey(Siniestro, on_delete=models.CASCADE, related_name="cambios")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    fecha = models.DateTimeField(auto_now_add=True)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    descripcion = models.CharField(max_length=250, blank=True)
    detalle = models.JSONField(default=list, blank=True,
                               help_text="Lista de {campo, etiqueta, antes, despues}")

    class Meta:
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return f"{self.siniestro} · {self.get_tipo_display()} · {self.fecha:%d/%m/%Y %H:%M}"


class Perfil(models.Model):
    """Datos extra de cada usuario de la plataforma."""
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil")
    debe_cambiar_contrasena = models.BooleanField(
        "Debe cambiar su contraseña al entrar", default=True,
        help_text="Se marca solo al crear el usuario o cuando un administrador le pone una contraseña nueva.")
    contrasena_cambiada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "perfil"
        verbose_name_plural = "perfiles"

    def __str__(self):
        return f"Perfil de {self.usuario}"
