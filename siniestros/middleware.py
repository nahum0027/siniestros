from django.http import JsonResponse
from django.shortcuts import redirect

from .senales import perfil_de

# Lo único que se puede abrir mientras no cambie su contraseña
PERMITIDAS = ("/cuenta/contrasena/", "/salir/", "/entrar/", "/static/", "/sw.js", "/manifest.json")


class CambioContrasenaObligatorio:
    """Si el usuario tiene contraseña temporal, lo manda a cambiarla antes de cualquier otra cosa."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        u = request.user
        if u.is_authenticated and not request.path.startswith(PERMITIDAS) and perfil_de(u).debe_cambiar_contrasena:
            if request.path.startswith("/api/"):
                # la cola del celular lo trata como sesión vencida: guarda el reporte y pide entrar
                return JsonResponse({"ok": False, "error": "cambiar_contrasena",
                                     "mensaje": "Debes cambiar tu contraseña antes de enviar"}, status=401)
            return redirect(f"/cuenta/contrasena/?next={request.get_full_path()}")
        return self.get_response(request)
