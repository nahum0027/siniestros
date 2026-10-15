from django.apps import AppConfig
from django.db.models.signals import post_migrate

# Roles de la plataforma -> permisos que tiene cada uno
ROLES = {
    "Agente de campo": ["capturar_siniestro"],
    "Revisor": ["capturar_siniestro", "revisar_siniestro"],
    "Administrador de siniestros": ["capturar_siniestro", "revisar_siniestro", "reabrir_siniestro"],
}


def crear_roles(sender, **kwargs):
    """Crea (o completa) los grupos cada vez que se corre `migrate`."""
    from django.contrib.auth.models import Group, Permission

    for nombre, codigos in ROLES.items():
        grupo, _ = Group.objects.get_or_create(name=nombre)
        perms = Permission.objects.filter(content_type__app_label="siniestros", codename__in=codigos)
        grupo.permissions.add(*perms)


class SiniestrosConfig(AppConfig):
    name = "siniestros"
    verbose_name = "Siniestros"

    def ready(self):
        from . import senales  # noqa: F401  (registra la señal que crea el perfil)
        post_migrate.connect(crear_roles, sender=self)
