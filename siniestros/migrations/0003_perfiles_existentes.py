from django.conf import settings
from django.db import migrations


def crear_perfiles(apps, schema_editor):
    """Usuarios que ya existían antes de esta función: se les pide cambiar su contraseña
    la próxima vez que entren (menos a los superusuarios, que ya pusieron la suya)."""
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Perfil = apps.get_model("siniestros", "Perfil")
    for u in User.objects.all():
        Perfil.objects.get_or_create(usuario=u, defaults={"debe_cambiar_contrasena": not u.is_superuser})


class Migration(migrations.Migration):
    dependencies = [
        ("siniestros", "0002_perfil"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.RunPython(crear_perfiles, migrations.RunPython.noop)]
