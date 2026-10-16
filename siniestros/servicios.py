"""
Lógica de negocio de siniestros (sin nada de HTTP):
imágenes, generación de formatos, historial de cambios y correo.
"""
import base64
import hashlib
import logging
from datetime import datetime

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from .generar import generar_todo
from .models import Cambio, Siniestro

log = logging.getLogger(__name__)

IMAGENES = ["croquis", "firma_ejecutivo", "firma_agente", "firma_perito", "firma_conv_a", "firma_conv_b"]
NO_COMPARAR = {"id_cliente", "paso", "_version"}

# Nombres legibles para el historial
ETIQUETAS = {
    "fecha": "Fecha", "hora": "Hora", "ruta": "Ruta", "economico": "No. económico", "lugar": "Lugar del hecho",
    "colonia": "Colonia", "competencia": "Competencia", "competencia_otro": "Competencia (otro)",
    "reporte_aseguradora": "Reporte de aseguradora", "agente_nombre": "Agente de siniestros",
    "perito_nombre": "Perito HTT", "causal": "Causal", "colision": "Tipo de colisión", "responsable": "Responsable",
    "medio_prueba": "Medio de prueba", "nota": "Nota", "alcohol": "Influjo de alcohol/sustancias",
    "narrativa": "Redacción de hechos", "seguro_activo": "Se activa el seguro", "pases_medicos": "Pases médicos",
    "seguro_garantiza": "Seguro que garantiza", "aplica_convenio": "Convenio", "forma_reparacion": "Forma de reparación",
    "b_no_aplica": "Partícipe B no aplica",
    "alcohol_autoridad": "Autoridad que arriba (alcohol)", "alcohol_conductor": "Conductor con alcohol",
    "alcohol_grados": "Grados de alcohol",
    "croquis": "Croquis", "firma_ejecutivo": "Firma del ejecutivo", "firma_agente": "Firma del agente",
    "firma_perito": "Firma del perito", "firma_conv_a": "Firma convenio (A)", "firma_conv_b": "Firma convenio (B)",
}
CAMPOS_PARTICIPE = {
    "nombre": "Nombre", "no_empleado": "No. empleado", "telefono": "Teléfono", "sexo": "Sexo",
    "nacimiento": "Fecha de nacimiento", "edad": "Edad", "domicilio": "Domicilio", "identificacion": "Identificación",
    "licencia": "Licencia", "vigencia": "Vigencia", "tarjeton": "Tarjetón", "infraccion": "Infracción",
    "garantia": "Garantía", "placas": "Placas", "modelo": "Modelo", "marca": "Marca", "garantiza": "Garantiza",
    "trayectoria": "Trayectoria", "entidad": "Entidad", "tipo_servicio": "Tipo de servicio", "seguro": "Seguro",
    "lesionado": "Lesionado", "fallecido": "Fallecido", "remolcado_por": "Remolcado por",
    "trasladado_a": "Trasladado a", "disposicion": "A disposición de",
}
CAMPOS_LESIONADO = {"nombre": "Nombre", "direccion": "Dirección", "telefono": "Teléfono",
                    "pase_medico": "Pase médico", "trasladado_a": "Trasladado a"}


def etiqueta(campo):
    partes = campo.split(".")
    if partes[0] in ("a", "b") and len(partes) == 2:
        quien = "Ejecutivo (A)" if partes[0] == "a" else "Partícipe B"
        return f"{quien} · {CAMPOS_PARTICIPE.get(partes[1], partes[1])}"
    if partes[0] == "lesionados" and len(partes) == 3:
        return f"Lesionado {int(partes[1]) + 1} · {CAMPOS_LESIONADO.get(partes[2], partes[2])}"
    if partes[0] == "anexos" and len(partes) == 3:
        return f"Anexo {int(partes[1]) + 1} · {dict(aplica='Aplica', art='Artículo', fracc='Fracción').get(partes[2], partes[2])}"
    return ETIQUETAS.get(campo, campo)


# ------------------------------------------------------------------ imágenes
def _decodificar(data_url):
    if not data_url or "," not in str(data_url):
        return None, None
    cabecera, b64 = data_url.split(",", 1)
    return base64.b64decode(b64), ("jpg" if "jpeg" in cabecera else "png")


def ruta_imagen(siniestro, nombre):
    carpeta = siniestro.carpeta / "imagenes"
    for ext in ("png", "jpg"):
        p = carpeta / f"{nombre}.{ext}"
        if p.exists():
            return p
    return None


def imagen_como_data_url(siniestro, nombre):
    p = ruta_imagen(siniestro, nombre)
    if not p:
        return None
    mime = "image/jpeg" if p.suffix == ".jpg" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def guardar_imagenes(siniestro, j):
    """Escribe las imágenes que vienen en el JSON. Regresa la lista de las que cambiaron."""
    carpeta = siniestro.carpeta / "imagenes"
    carpeta.mkdir(parents=True, exist_ok=True)
    cambiaron = []
    for nombre in IMAGENES:
        actual = ruta_imagen(siniestro, nombre)
        antes = hashlib.sha1(actual.read_bytes()).hexdigest() if actual else None
        datos, ext = _decodificar(j.get(nombre))
        despues = hashlib.sha1(datos).hexdigest() if datos else None
        if antes == despues:
            continue
        cambiaron.append(nombre)
        if actual:
            actual.unlink()
        if datos:
            (carpeta / f"{nombre}.{ext}").write_bytes(datos)
    return cambiaron


# ------------------------------------------------------------------ formatos
def _fecha(txt):
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date() if txt else None
    except ValueError:
        return None


def regenerar_documentos(siniestro):
    """Vuelve a llenar los formatos con los datos actuales del siniestro."""
    j = siniestro.datos
    datos = dict(j)
    datos["fecha"] = _fecha(j.get("fecha")) or siniestro.creado.date()
    datos["responsable"] = {"SI": True, "NO": False}.get(j.get("responsable"))
    for k in ("a", "b"):
        p = dict(j.get(k) or {})
        p["nacimiento"] = _fecha(p.get("nacimiento"))
        datos[k] = p
    datos["anexos"] = [{**a, "aplica": {"SI": True, "NO": False}.get(a.get("aplica"))} for a in j.get("anexos", [])]
    datos["lesionados"] = [l for l in j.get("lesionados", []) if (l.get("nombre") or "").strip()]
    datos["aplica_convenio"] = bool(j.get("aplica_convenio"))
    # alcohol: no hay casilla en el formato, se deja constancia en la NOTA del hecho de tránsito
    if j.get("alcohol"):
        conductor = {"A": "conductor A (ejecutivo)", "B": "conductor B"}.get(j.get("alcohol_conductor"), "conductor")
        partes = [f"ALCOHOL: {conductor}"]
        if str(j.get("alcohol_grados") or "").strip():
            partes.append(f"{j['alcohol_grados']} grados")
        if j.get("alcohol_autoridad"):
            partes.append(f"arribó {j['alcohol_autoridad']}")
        nota_alcohol = ", ".join(partes)
        datos["nota"] = f"{j.get('nota', '').strip()} · {nota_alcohol}".strip(" ·")
    if j.get("b_no_aplica"):
        # sin segundo partícipe: se deja constancia en el formato y no hay convenio
        datos["b"] = {"nombre": "NO APLICA"}
        datos["aplica_convenio"] = False
    for nombre in IMAGENES:
        datos[nombre] = ruta_imagen(siniestro, nombre)
    # se borran los formatos anteriores (p. ej. si ya no aplica convenio)
    for viejo in siniestro.carpeta.glob("*.*"):
        if viejo.suffix in (".docx", ".xlsx", ".pdf"):
            viejo.unlink()
    return generar_todo(datos, siniestro.carpeta)


# ------------------------------------------------------------------ historial
def _aplanar(d, prefijo=""):
    plano = {}
    if isinstance(d, dict):
        for k, v in d.items():
            plano.update(_aplanar(v, f"{prefijo}{k}."))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            plano.update(_aplanar(v, f"{prefijo}{i}."))
    else:
        plano[prefijo[:-1]] = d
    return plano


def _normal(v):
    if v is None or v is False:
        return ""
    if v is True:
        return "Sí"
    return str(v).strip()


def diferencias(antes, despues):
    a, d = _aplanar(antes), _aplanar(despues)
    cambios = []
    for campo in sorted(set(a) | set(d)):
        if campo.split(".")[0] in NO_COMPARAR:
            continue
        va, vd = _normal(a.get(campo)), _normal(d.get(campo))
        if va != vd:
            cambios.append({"campo": campo, "etiqueta": etiqueta(campo), "antes": va, "despues": vd})
    return cambios


def limpiar(j):
    """Quita imágenes y campos internos del JSON antes de guardarlo en la BD."""
    return {k: v for k, v in j.items() if k not in IMAGENES and k not in NO_COMPARAR}


# ------------------------------------------------------------------ correo
def enviar_correo(siniestro, request=None):
    destinatarios = getattr(settings, "SINIESTROS_CORREOS", [])
    if not destinatarios:
        return False
    d = siniestro.datos
    asunto = f"Siniestro {siniestro.folio} · Ruta {d.get('ruta') or 's/r'} · {d.get('fecha', '')}"
    enlace = request.build_absolute_uri(f"/reportes/{siniestro.folio}/") if request else ""
    cuerpo = "\n".join([
        f"Se registró un siniestro desde campo.",
        "",
        f"Folio: {siniestro.folio}",
        f"Fecha y hora: {d.get('fecha', '')} {d.get('hora', '')}",
        f"Ruta / económico: {d.get('ruta', '')} / {d.get('economico', '')}",
        f"Lugar: {d.get('lugar', '')}",
        f"Ejecutivo(a): {(d.get('a') or {}).get('nombre', '')}",
        f"Capturó: {siniestro.capturado_por.get_full_name() or siniestro.capturado_por.username}",
        "",
        f"Ver y revisar en la plataforma: {enlace}" if enlace else "",
        "",
        "Se adjuntan los formatos tal como se capturaron en campo; la versión vigente es la de la plataforma.",
    ])
    msg = EmailMessage(asunto, cuerpo, to=destinatarios)
    for nombre in siniestro.documentos():
        msg.attach_file(str(siniestro.carpeta / nombre))
    try:
        msg.send()
        siniestro.correo_enviado_en, siniestro.correo_error = timezone.now(), ""
        Cambio.objects.create(siniestro=siniestro, tipo=Cambio.Tipo.CORREO,
                              descripcion=f"Correo enviado a {', '.join(destinatarios)}")
        ok = True
    except Exception as e:  # el reporte ya quedó guardado; el correo no debe tumbar el envío
        log.exception("No se pudo enviar el correo de %s", siniestro.folio)
        siniestro.correo_error = f"{type(e).__name__}: {e}"[:1000]
        Cambio.objects.create(siniestro=siniestro, tipo=Cambio.Tipo.CORREO, descripcion="Falló el envío del correo")
        ok = False
    siniestro.save(update_fields=["correo_enviado_en", "correo_error"])
    return ok


# ------------------------------------------------------------------ permisos
def puede_revisar(user):
    return user.has_perm("siniestros.revisar_siniestro")


def puede_ver(user, siniestro):
    return puede_revisar(user) or siniestro.capturado_por_id == user.id


def puede_editar(user, siniestro):
    return puede_revisar(user) and not siniestro.bloqueado
