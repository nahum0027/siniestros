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
    """A dónde mandar a cada quien después del login."""
    if request.user.has_perm("siniestros.capturar_siniestro") and not sv.puede_revisar(request.user):
        return redirect("formulario")
    return redirect("lista")


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
        "estados": estados, "total": base.count(), "revisor": revisor,
        "puede_capturar": request.user.has_perm("siniestros.capturar_siniestro"),
    })


@login_required
def detalle(request, folio):
    s = get_object_or_404(Siniestro.objects.select_related("capturado_por", "validado_por"), folio=folio)
    if not sv.puede_ver(request.user, s):
        raise Http404
    imagenes = [(n, sv.etiqueta(n)) for n in sv.IMAGENES if sv.ruta_imagen(s, n)]
    return render(request, "siniestros/detalle.html", {
        "s": s, "d": s.datos, "imagenes": imagenes,
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
def descargar(request, folio, archivo):
    s = get_object_or_404(Siniestro, folio=folio)
    if not sv.puede_ver(request.user, s) or archivo not in s.documentos():
        raise Http404
    return FileResponse(open(s.carpeta / archivo, "rb"), as_attachment=True, filename=f"{folio}_{archivo}")


# ------------------------------------------------------------------ edición (revisor)
@login_required
def editar(request, folio):
    s = get_object_or_404(Siniestro, folio=folio)
    if not sv.puede_editar(request.user, s):
        messages.error(request, "Este reporte está validado y ya no se puede editar." if s.bloqueado
                       else "No tienes permiso para editar reportes.")
        return redirect("detalle", folio=folio)
    datos = dict(s.datos)
    for n in sv.IMAGENES:
        url = sv.imagen_como_data_url(s, n)
        if url:
            datos[n] = url
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
