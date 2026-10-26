"""
Vistas de la app de siniestros.

Campo (celular):
  /                               formulario de captura (requiere permiso capturar)
  /api/enviar/                    recibe un siniestro nuevo
Oficina:
  /reportes/                      lista (agente: solo los suyos; revisor: todos)
  /reportes/<folio>/              detalle + historial
  /reportes/<folio>/editar/       mismo formulario, con los datos cargados (revisor)
  /api/reportes/<folio>/          guarda la edición
  /reportes/<folio>/estado/       validar / reabrir
  /descargar/<folio>/<archivo>    descarga un formato
"""
import json
import re
import uuid
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from pathlib import Path

from . import servicios as sv
from .models import Cambio, Siniestro

STATIC = Path(__file__).resolve().parent / "static" / "siniestros"


def _json_401(view):
    """Para la API: si la sesión expiró regresa 401 en JSON (no redirige al login),
    así la cola del celular sabe que debe pedir que inicien sesión."""
    def envuelta(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"ok": False, "error": "sesion", "mensaje": "Tu sesión expiró"}, status=401)
        return view(request, *args, **kwargs)
    return envuelta


def _cfg_usuario(user):
    return {
        "usuario": user.username,
        "nombre": user.get_full_name() or user.username,
        "puede_revisar": sv.puede_revisar(user),
    }


# ------------------------------------------------------------------ inicio
@login_required
def inicio(request):
    """Pantalla de inicio con los módulos. Los agentes de campo (un solo módulo) van directo a capturar."""
    u = request.user
    puede_capturar, revisor = u.has_perm("siniestros.capturar_siniestro"), sv.puede_revisar(u)
    if puede_capturar and not revisor:
        return redirect("formulario")
    base = Siniestro.objects.all() if revisor else Siniestro.objects.filter(capturado_por=u)
    pendientes = [Siniestro.Estado.ENVIADO, Siniestro.Estado.REVISION]
    hoy = timezone.localdate()
    S, L = Siniestro.Tipo.SINIESTRO, Siniestro.Tipo.LIBERACION
    return render(request, "siniestros/inicio.html", {
        "puede_capturar": puede_capturar, "revisor": revisor,
        "sin_pend": base.filter(tipo=S, estado__in=pendientes).count(),
        "sin_hoy": base.filter(tipo=S, creado__date=hoy).count(),
        "lib_pend": base.filter(tipo=L, estado__in=pendientes).count(),
        "lib_hoy": base.filter(tipo=L, creado__date=hoy).count(),
        "total": base.count(), "pendientes": base.filter(estado__in=pendientes).count(),
        "recientes": base.select_related("capturado_por")[:5],
    })


# ------------------------------------------------------------------ captura en campo
@login_required
@permission_required("siniestros.capturar_siniestro", raise_exception=True)
def formulario(request):
    cfg = {"modo": "captura", "usuario": _cfg_usuario(request.user), "url_guardar": "/api/enviar/"}
    return render(request, "siniestros/formulario.html", {"cfg": cfg})


@require_POST
@_json_401
def enviar(request):
    if not request.user.has_perm("siniestros.capturar_siniestro"):
        return JsonResponse({"ok": False, "error": "permiso"}, status=403)
    try:
        j = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    id_cliente = str(j.get("id_cliente") or uuid.uuid4())[:64]
    previo = Siniestro.objects.filter(id_cliente=id_cliente).first()
    if previo:  # el celular reintentó un envío que sí había llegado
        return JsonResponse(_respuesta(request, previo))

    ahora = datetime.now()
    sufijo = re.sub(r"[^A-Za-z0-9]", "", id_cliente)[-4:].upper() or "0000"
    try:
        with transaction.atomic():
            s = Siniestro(folio=f"SIN-{ahora:%Y%m%d-%H%M%S}-{sufijo}", id_cliente=id_cliente,
                          datos=sv.limpiar(j), capturado_por=request.user)
            s.copiar_resumen()
            s.save()
            sv.guardar_imagenes(s, j)
            s.datos["fotos"], _ = sv.guardar_fotos(s, j)
            s.save(update_fields=["datos"])
            sv.regenerar_documentos(s)
            Cambio.objects.create(siniestro=s, usuario=request.user, tipo=Cambio.Tipo.CREADO,
                                  descripcion="Capturado en campo")
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status=500)

    sv.enviar_correo(s, request)
    return JsonResponse(_respuesta(request, s))


def _respuesta(request, s):
    return {
        "ok": True,
        "folio": s.folio,
        "url_reporte": f"/reportes/{s.folio}/",
        "archivos": [{"nombre": a, "url": f"/descargar/{s.folio}/{a}"} for a in s.documentos()],
    }


# ------------------------------------------------------------------ consulta
@login_required
def lista(request):
    qs = Siniestro.objects.select_related("capturado_por")
    revisor = sv.puede_revisar(request.user)
    if not revisor:
        qs = qs.filter(capturado_por=request.user)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(folio__icontains=q) | Q(ruta__icontains=q) | Q(economico__icontains=q)
                       | Q(ejecutivo__icontains=q) | Q(lugar__icontains=q))
    tipo = request.GET.get("tipo", "")
    if tipo in Siniestro.Tipo.values:
        qs = qs.filter(tipo=tipo)
    estado = request.GET.get("estado", "")
    if estado in Siniestro.Estado.values:
        qs = qs.filter(estado=estado)
    desde, hasta = request.GET.get("desde", ""), request.GET.get("hasta", "")
    if desde:
        qs = qs.filter(fecha_hecho__gte=desde)
    if hasta:
        qs = qs.filter(fecha_hecho__lte=hasta)

    pagina = Paginator(qs, 25).get_page(request.GET.get("p"))
    base = Siniestro.objects.all() if revisor else Siniestro.objects.filter(capturado_por=request.user)
    cortos = {"ENVIADO": "Por revisar", "REVISION": "En revisión", "VALIDADO": "Validados"}
    estados = [(e, cortos[e], base.filter(estado=e).count()) for e in Siniestro.Estado.values]
    return render(request, "siniestros/lista.html", {
        "pagina": pagina, "q": q, "estado": estado, "desde": desde, "hasta": hasta,
        "estados": estados, "total": base.count(), "revisor": revisor, "tipo": tipo,
        "tipos": [(t, n, base.filter(tipo=t).count()) for t, n in (("SINIESTRO", "Siniestros"), ("LIBERACION", "Liberaciones exprés"))],
        "puede_capturar": request.user.has_perm("siniestros.capturar_siniestro"),
    })


@login_required
def detalle(request, folio):
    s = get_object_or_404(Siniestro.objects.select_related("capturado_por", "validado_por"), folio=folio)
    if not sv.puede_ver(request.user, s):
        raise Http404
    imagenes = [(n, sv.etiqueta(n)) for n in sv.IMAGENES if sv.ruta_imagen(s, n)]
    return render(request, "siniestros/detalle.html", {
        "s": s, "d": s.datos, "imagenes": imagenes, "fotos": sv.fotos_para_mostrar(s),
        "danos": [n.capitalize() for n in sv.lista_danos(s.datos)],
        "cambios": s.cambios.select_related("usuario"),
        "revisor": sv.puede_revisar(request.user),
        "puede_editar": sv.puede_editar(request.user, s),
        "puede_reabrir": request.user.has_perm("siniestros.reabrir_siniestro") and s.bloqueado,
        "guardado": request.GET.get("guardado"), "sin_cambios": request.GET.get("sin_cambios"),
    })


@login_required
def imagen(request, folio, nombre):
    s = get_object_or_404(Siniestro, folio=folio)
    if not sv.puede_ver(request.user, s) or nombre not in sv.IMAGENES:
        raise Http404
    p = sv.ruta_imagen(s, nombre)
    if not p:
        raise Http404
    return FileResponse(open(p, "rb"))


@login_required
def foto(request, folio, nombre):
    s = get_object_or_404(Siniestro, folio=folio)
    p = sv.ruta_foto(s, nombre) if sv.puede_ver(request.user, s) else None
    if not p:
        raise Http404
    return FileResponse(open(p, "rb"))


@login_required
def descargar(request, folio, archivo):
    s = get_object_or_404(Siniestro, folio=folio)
    if not sv.puede_ver(request.user, s) or archivo not in s.documentos():
        raise Http404
    return FileResponse(open(s.carpeta / archivo, "rb"), as_attachment=True, filename=f"{folio}_{archivo}")


# ------------------------------------------------------------------ edición (revisor)
@login_required
def editar(request, folio):
    s = get_object_or_404(Siniestro, folio=folio)
    if s.es_liberacion:
        return redirect("liberacion_editar", folio=folio)
    if not sv.puede_editar(request.user, s):
        messages.error(request, "Este reporte está validado y ya no se puede editar." if s.bloqueado
                       else "No tienes permiso para editar reportes.")
        return redirect("detalle", folio=folio)
    datos = dict(s.datos)
    for n in sv.IMAGENES:
        url = sv.imagen_como_data_url(s, n)
        if url:
            datos[n] = url
    datos["fotos"] = {c: [f"srv:{n}" for n in lista] for c, lista in (s.datos.get("fotos") or {}).items()}
    cfg = {"modo": "editar", "folio": s.folio, "version": s.actualizado.isoformat(),
           "usuario": _cfg_usuario(request.user), "datos": datos,
           "url_guardar": f"/api/reportes/{s.folio}/", "url_volver": f"/reportes/{s.folio}/"}
    return render(request, "siniestros/formulario.html", {"cfg": cfg})


@require_POST
@_json_401
def guardar_edicion(request, folio):
    s = get_object_or_404(Siniestro, folio=folio)
    if not sv.puede_editar(request.user, s):
        return JsonResponse({"ok": False, "error": "Este reporte está validado o no tienes permiso."}, status=403)
    try:
        j = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    nuevos = sv.limpiar(j)
    cambios = sv.diferencias(s.datos, nuevos)
    with transaction.atomic():
        imgs = sv.guardar_imagenes(s, j)
        cambios += [{"campo": n, "etiqueta": sv.etiqueta(n), "antes": "(imagen)", "despues": "(imagen nueva)"} for n in imgs]
        fotos, cambios_fotos = sv.guardar_fotos(s, j)
        cambios += cambios_fotos
        nuevos["fotos"] = fotos
        if not cambios:
            return JsonResponse({"ok": True, "sin_cambios": True, "url_reporte": f"/reportes/{s.folio}/"})
        s.datos = nuevos
        s.copiar_resumen()
        if s.estado == Siniestro.Estado.ENVIADO:
            s.estado = Siniestro.Estado.REVISION
        s.save()
        sv.regenerar_documentos(s)
        Cambio.objects.create(siniestro=s, usuario=request.user, tipo=Cambio.Tipo.EDITADO,
                              descripcion=f"{len(cambios)} campo(s) corregido(s)", detalle=cambios)
    return JsonResponse({"ok": True, "cambios": len(cambios), "url_reporte": f"/reportes/{s.folio}/"})


@login_required
@require_POST
def cambiar_estado(request, folio):
    s = get_object_or_404(Siniestro, folio=folio)
    accion = request.POST.get("accion")
    if accion == "validar" and sv.puede_editar(request.user, s):
        s.estado, s.validado_por, s.validado_en = Siniestro.Estado.VALIDADO, request.user, timezone.now()
        s.save()
        Cambio.objects.create(siniestro=s, usuario=request.user, tipo=Cambio.Tipo.ESTADO, descripcion="Validado (bloqueado)")
        messages.success(request, "Reporte validado. Ya no se puede editar.")
    elif accion == "revision" and sv.puede_editar(request.user, s) and s.estado == Siniestro.Estado.ENVIADO:
        s.estado = Siniestro.Estado.REVISION
        s.save()
        Cambio.objects.create(siniestro=s, usuario=request.user, tipo=Cambio.Tipo.ESTADO, descripcion="Tomado en revisión")
    elif accion == "reabrir" and s.bloqueado and request.user.has_perm("siniestros.reabrir_siniestro"):
        motivo = request.POST.get("motivo", "").strip()[:200]
        s.estado, s.validado_por, s.validado_en = Siniestro.Estado.REVISION, None, None
        s.save()
        Cambio.objects.create(siniestro=s, usuario=request.user, tipo=Cambio.Tipo.ESTADO,
                              descripcion=f"Reabierto{': ' + motivo if motivo else ''}")
        messages.success(request, "Reporte reabierto; ya se puede corregir.")
    else:
        messages.error(request, "No tienes permiso para esa acción.")
    return redirect("detalle", folio=folio)


# ------------------------------------------------------------------ PWA
def service_worker(request):
    resp = HttpResponse((STATIC / "sw.js").read_text(encoding="utf-8"), content_type="application/javascript")
    resp["Cache-Control"] = "no-cache"
    return resp


def manifest(request):
    return HttpResponse((STATIC / "manifest.json").read_text(encoding="utf-8"),
                        content_type="application/manifest+json")


# ------------------------------------------------------------------ cuenta
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.utils.http import url_has_allowed_host_and_scheme

from .senales import perfil_de


@login_required
def cambiar_contrasena(request):
    perfil = perfil_de(request.user)
    destino = request.GET.get("next") or request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}) or destino.startswith("/cuenta/"):
        destino = "/inicio/"
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["new_password1"] == form.cleaned_data["old_password"]:
            form.add_error("new_password1", "La contraseña nueva debe ser distinta a la actual.")
        else:
            user = form.save()
            update_session_auth_hash(request, user)  # no lo saca de la sesión
            perfil.debe_cambiar_contrasena = False
            perfil.contrasena_cambiada_en = timezone.now()
            perfil.save()
            messages.success(request, "Contraseña actualizada.")
            return redirect(destino)
    return render(request, "siniestros/cambiar_contrasena.html", {
        "form": form, "forzado": perfil.debe_cambiar_contrasena, "next": destino,
    })


# ------------------------------------------------------------------ liberación exprés (oficina)
from django.core.exceptions import PermissionDenied
from datetime import date as _date

CAMPOS_LIB = ["fecha", "ubicacion", "ejecutivo", "no_empleado", "economico", "ruta",
              "descripcion", "activa_seguro", "motivo_activacion", "causal", "pase_medico",
              # generalidades (igual que en el reporte de campo, sin anexos)
              "colision", "responsable", "medio_prueba", "nota",
              "alcohol_autoridad", "alcohol_conductor", "alcohol_grados", "a", "b"]
CASILLAS_LIB = ["danos", "danos_cristal", "danos_carroceria", "danos_retrovisor", "alcohol"]
OBLIGATORIOS_LIB = {"fecha": "Fecha", "ejecutivo": "Ejecutivo(a)", "descripcion": "Descripción del hecho"}


@login_required
def liberacion(request, folio=None):
    """Alta (sin folio) y edición (con folio) de una liberación exprés."""
    if not sv.puede_revisar(request.user):
        raise PermissionDenied
    s = None
    if folio:
        s = get_object_or_404(Siniestro, folio=folio, tipo=Siniestro.Tipo.LIBERACION)
        if not sv.puede_editar(request.user, s):
            messages.error(request, "Este reporte está validado y ya no se puede editar.")
            return redirect("detalle", folio=folio)

    errores = []
    if request.method == "POST":
        datos = {k: request.POST.get(k, "").strip() for k in CAMPOS_LIB}
        datos["a"] = {"garantiza": request.POST.get("a.garantiza", "").strip()}
        datos["b"] = {k: request.POST.get(f"b.{k}", "").strip() for k in ("seguro", "garantiza")}
        datos.update({k: k in request.POST for k in CASILLAS_LIB})
        if s:  # conserva datos viejos que ya no están en la pantalla (p. ej. teléfono y placa)
            datos = {**{k: v for k, v in s.datos.items() if k not in CAMPOS_LIB + CASILLAS_LIB}, **datos}
        firma = request.POST.get("firma_ejecutivo", "")
        errores = [n for k, n in OBLIGATORIOS_LIB.items() if not datos[k]]
        if not errores:
            with transaction.atomic():
                if s is None:
                    ahora = datetime.now()
                    id_cliente = uuid.uuid4().hex
                    s = Siniestro(tipo=Siniestro.Tipo.LIBERACION, folio=f"LIB-{ahora:%Y%m%d-%H%M%S}-{id_cliente[-4:].upper()}",
                                  id_cliente=id_cliente, datos=datos, capturado_por=request.user)
                    s.copiar_resumen()
                    s.save()
                    sv.guardar_imagenes(s, {"firma_ejecutivo": firma})
                    sv.regenerar_documentos(s)
                    Cambio.objects.create(siniestro=s, usuario=request.user, tipo=Cambio.Tipo.CREADO,
                                          descripcion="Capturado en oficina (liberación exprés)")
                    nuevo = True
                else:
                    cambios = sv.diferencias(s.datos, datos)
                    imgs = sv.guardar_imagenes(s, {"firma_ejecutivo": firma})
                    cambios += [{"campo": n, "etiqueta": sv.etiqueta(n), "antes": "(imagen)", "despues": "(imagen nueva)"} for n in imgs]
                    if not cambios:
                        return redirect(f"/reportes/{s.folio}/?sin_cambios=1")
                    s.datos = datos
                    s.copiar_resumen()
                    if s.estado == Siniestro.Estado.ENVIADO:
                        s.estado = Siniestro.Estado.REVISION
                    s.save()
                    sv.regenerar_documentos(s)
                    Cambio.objects.create(siniestro=s, usuario=request.user, tipo=Cambio.Tipo.EDITADO,
                                          descripcion=f"{len(cambios)} campo(s) corregido(s)", detalle=cambios)
                    nuevo = False
            if nuevo:
                sv.enviar_correo(s, request)
                messages.success(request, f"Liberación exprés {s.folio} guardada.")
                return redirect("detalle", folio=s.folio)
            return redirect(f"/reportes/{s.folio}/?guardado={len(cambios)}")
    else:
        datos = dict(s.datos) if s else {"fecha": _date.today().isoformat()}
        firma = (sv.imagen_como_data_url(s, "firma_ejecutivo") if s else "") or ""

    return render(request, "siniestros/liberacion.html", {
        "s": s, "d": datos, "firma": firma, "errores": errores,
    })
