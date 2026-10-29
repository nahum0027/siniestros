"""
Borra TODOS los reportes (siniestros y liberaciones exprés), su historial y sus archivos
(formatos, PDF, fotos, firmas). NO toca usuarios, roles ni contraseñas.

Uso:
    python manage.py borrar_reportes            -> solo muestra lo que se borraría
    python manage.py borrar_reportes --confirmar -> borra
"""
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from siniestros.models import Cambio, Siniestro


class Command(BaseCommand):
    help = "Borra todos los reportes, su historial y sus archivos (no toca usuarios)."

    def add_arguments(self, parser):
        parser.add_argument("--confirmar", action="store_true", help="Sin esto solo se muestra el resumen.")

    def handle(self, *args, **opts):
        carpeta = Path(settings.SINIESTROS_DIR)
        n_sin = Siniestro.objects.filter(tipo=Siniestro.Tipo.SINIESTRO).count()
        n_lib = Siniestro.objects.filter(tipo=Siniestro.Tipo.LIBERACION).count()
        n_cam = Cambio.objects.count()
        carpetas = [p for p in carpeta.iterdir() if p.is_dir()] if carpeta.exists() else []
        self.stdout.write(f"Siniestros: {n_sin} | Liberaciones exprés: {n_lib} | "
                          f"Registros de historial: {n_cam} | Carpetas de archivos: {len(carpetas)}")
        self.stdout.write(f"Carpeta de archivos: {carpeta}")
        if not opts["confirmar"]:
            self.stdout.write(self.style.WARNING(
                "No se borró nada. Para borrar de verdad: python manage.py borrar_reportes --confirmar"))
            return
        with transaction.atomic():
            Cambio.objects.all().delete()
            Siniestro.objects.all().delete()
        for p in carpetas:
            shutil.rmtree(p, ignore_errors=True)
        self.stdout.write(self.style.SUCCESS(
            f"Listo: se borraron {n_sin + n_lib} reportes, su historial y sus archivos. Usuarios intactos."))
