from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Perfil


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def crear_perfil(sender, instance, created, **kwargs):
    """Todo usuario nuevo nace obligado a cambiar la contraseña que le dieron."""
    if created:
        Perfil.objects.get_or_create(usuario=instance, defaults={"debe_cambiar_contrasena": True})


def perfil_de(user):
    perfil, _ = Perfil.objects.get_or_create(usuario=user, defaults={"debe_cambiar_contrasena": True})
    return perfil
