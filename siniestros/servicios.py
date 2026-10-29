"""
Lógica de negocio de siniestros (sin nada de HTTP):
imágenes, generación de formatos, historial de cambios y correo.
"""
import base64
import hashlib
import logging
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from .generar import generar_todo, llenar_liberacion
from .models import Cambio, Siniestro

log = logging.getLogger(__name__)

IMAGENES = ["croquis", "firma_ejecutivo", "firma_agente", "firma_perito", "firma_conv_a", "firma_conv_b"]
NO_COMPARAR = {"id_cliente", "paso", "_version", "fotos"}

# Fotos de documentos y del siniestro: campo -> (etiqueta, máximo)
FOTOS = {
    "tio": ("TIO (tarjetón)", 2),
    "licencia_a": ("Licencia del ejecutivo (A)", 2),
    "licencia_b": ("Licencia del partícipe B", 2),
    "otras": ("Fotos de daños del bus", 10),
}

# Tipos de colisión (catálogo fijo; se guarda en mayúsculas como en los formatos)
COLISIONES = [(n.upper(), n) for n in (
    "Alcance", "Choque crucero", "Choque de frente", "Choque lateral",
    "Salida de la superficie de rodamiento", "Estrellamiento", "Volcadura", "Proyección",
    "Atropello", "Caída de persona", "Choque con móvil de vehículo", "Choques diversos")]

# Liberación exprés: a dónde se envía la unidad liberada
DESTINOS_LIB = [("CONTINÚA EN RUTA", "Continúa en ruta"), ("MANTENIMIENTO", "Mantenimiento"), ("VÍA LÁCTEA", "Vía Láctea"), ("PATIO LA NACIÓN", "Patio La Nación")]

DANOS = (("danos_cristal", "CRISTAL"), ("danos_carroceria", "CARROCERÍA"), ("danos_retrovisor", "RETROVISOR"), ("danos_rack", "RACK"))


def lista_danos(j):
    """Daños marcados en Generalidades (solo si está activada la casilla 'Hay daños')."""
    if not j.get("danos"):
        return []
    return [nombre for campo, nombre in DANOS if j.get(campo)]


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
    # liberación exprés
    "ubicacion": "Ubicación", "ejecutivo": "Ejecutivo(a)", "placa": "Placa", "no_empleado": "No. empleado",
    "telefono": "Teléfono", "descripcion": "Descripción del hecho", "activa_seguro": "¿Se activa seguro HDI?",
    "motivo_activacion": "Motivo de activación", "pase_medico": "Pase médico",
    "alcohol_autoridad": "Autoridad que arriba (alcohol)", "alcohol_conductor": "Conductor con alcohol",
    "alcohol_grados": "Grados de alcohol",
    "seguro_hdi": "¿Se activa seguro HDI?", "enviar_a": "Liberada, enviar a", "hay_participe": "Hubo otro partícipe",
    "danos": "Hay daños", "danos_cristal": "Daño: cristal", "danos_carroceria": "Daño: carrocería",
    "danos_retrovisor": "Daño: retrovisor", "danos_rack": "Daño: rack",
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
    "liberada": "Unidad liberada", "liberada_destino": "Unidad liberada · destino",
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


# ------------------------------------------------------------------ fotos
def carpeta_fotos(siniestro):
    return siniestro.carpeta / "fotos"


def ruta_foto(siniestro, nombre):
    """Ruta de una foto solo si pertenece al siniestro (evita pedir archivos ajenos)."""
    for lista in (siniestro.datos.get("fotos") or {}).values():
        if nombre in lista:
            p = carpeta_fotos(siniestro) / nombre
            return p if p.is_file() else None
    return None


def guardar_fotos(siniestro, j):
    """Recibe {"campo": [dataURL nueva | {"ref": nombre_existente}, ...]}.
    Guarda las nuevas, conserva las referenciadas y borra las que ya no vienen.
    Regresa (fotos_resultantes, cambios_para_historial)."""
    import uuid
    entrada = j.get("fotos") or {}
    previas = (siniestro.datos or {}).get("fotos") or {}
    carpeta = carpeta_fotos(siniestro)
    carpeta.mkdir(parents=True, exist_ok=True)
    resultado, cambios = {}, []
    for campo, (etq, maximo) in FOTOS.items():
        antes = list(previas.get(campo) or [])
        lista = []
        for item in (entrada.get(campo) or [])[:maximo]:
            if isinstance(item, dict) and item.get("ref") in antes:
                lista.append(item["ref"])
            elif isinstance(item, str):
                datos, ext = _decodificar(item)
                if datos:
                    nombre = f"{campo}_{uuid.uuid4().hex[:8]}.{ext}"
                    (carpeta / nombre).write_bytes(datos)
                    lista.append(nombre)
        for viejo in set(antes) - set(lista):
            (carpeta / viejo).unlink(missing_ok=True)
        agregadas, quitadas = len(set(lista) - set(antes)), len(set(antes) - set(lista))
        if agregadas or quitadas:
            cambios.append({"campo": f"fotos.{campo}", "etiqueta": f"Fotos · {etq}",
                            "antes": f"{len(antes)} foto(s)",
                            "despues": f"{len(lista)} foto(s) ("
                                       + ", ".join(x for x in (f"+{agregadas} nueva(s)" if agregadas else "",
                                                               f"−{quitadas} quitada(s)" if quitadas else "") if x) + ")"})
        if lista:
            resultado[campo] = lista
    return resultado, cambios


def fotos_para_mostrar(siniestro):
    """[(etiqueta, [nombres])] en el orden de FOTOS, solo los grupos con fotos."""
    fotos = (siniestro.datos or {}).get("fotos") or {}
    if siniestro.es_liberacion:  # la liberación solo tiene un grupo de fotos
        return [("Fotos del hecho", fotos["otras"])] if fotos.get("otras") else []
    return [(etq, fotos[c]) for c, (etq, _) in FOTOS.items() if fotos.get(c)]


# ------------------------------------------------------------------ formatos
def _fecha(txt):
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date() if txt else None
    except ValueError:
        return None


def regenerar_documentos(siniestro):
    """Vuelve a llenar los formatos con los datos actuales del siniestro."""
    if siniestro.es_liberacion:
        return regenerar_liberacion(siniestro)
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
    # unidad liberada: tampoco hay casilla, va en la NOTA
    a_j = j.get("a") or {}
    if a_j.get("liberada"):
        txt = f"UNIDAD LIBERADA: {a_j.get('liberada_destino') or 'SIN DESTINO'}"
        datos["nota"] = f"{(datos.get('nota') or '').strip()} · {txt}".strip(" ·")
    # daños: tampoco hay casilla en el formato, van en la NOTA del hecho de tránsito
    danos = lista_danos(j)
    if danos:
        datos["nota"] = f"{(datos.get('nota') or '').strip()} · DAÑOS: {', '.join(danos)}".strip(" ·")
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
def resumen_generalidades_lib(d):
    """Renglón corto con las generalidades de una liberación exprés, para el Word (no tiene casillas)."""
    partes = []
    if d.get("enviar_a"):
        partes.append(f"Liberada, enviar a: {d['enviar_a']}")
    if d.get("colision"):
        partes.append(f"Colisión: {d['colision']}")
    if d.get("responsable") in ("SI", "NO"):
        partes.append(f"Unidad responsable: {'Sí' if d['responsable'] == 'SI' else 'No'}")
    if d.get("medio_prueba"):
        partes.append(f"Medio de prueba: {d['medio_prueba']}")
    danos = lista_danos(d)
    if d.get("danos"):
        partes.append(f"Daños: {', '.join(danos) or 'sí'}")
    if d.get("alcohol"):
        conductor = {"A": "ejecutivo", "B": "otro conductor"}.get(d.get("alcohol_conductor"), "conductor")
        txt = f"Alcohol/sustancias: {conductor}"
        if str(d.get("alcohol_grados") or "").strip():
            txt += f", {d['alcohol_grados']} grados"
        if d.get("alcohol_autoridad"):
            txt += f", arribó {d['alcohol_autoridad']}"
        partes.append(txt)
    a, b = d.get("a") or {}, d.get("b") or {}
    if a.get("garantiza"):
        partes.append(f"HDI garantiza: {a['garantiza']}")
    if b.get("seguro") or b.get("garantiza"):
        partes.append(f"Seguro del otro partícipe: {b.get('seguro') or '—'}" + (f" (garantiza {b['garantiza']})" if b.get("garantiza") else ""))
    if d.get("nota"):
        partes.append(f"Nota: {d['nota']}")
    return " · ".join(partes)


def resumen_secciones(s):
    """El resumen del reporte como [(título, [(etiqueta, valor), ...])], para copiar y pegar.
    Sigue el mismo orden que la pantalla de detalle."""
    d = s.datos or {}
    a, b = d.get("a") or {}, d.get("b") or {}
    v = lambda x: str(x).strip() if x not in (None, "", False) else "—"
    sino = lambda x: {"SI": "Sí", "SÍ": "Sí", "NO": "No"}.get(str(x or "").upper(), "—")
    fecha = s.fecha_hecho.strftime("%d/%m/%Y") if s.fecha_hecho else "—"
    danos = ", ".join(n.capitalize() for n in lista_danos(d)) or "Sí (sin especificar)"

    def alcohol(quien):
        if not d.get("alcohol"):
            return []
        return [("Alcohol / sustancias", "Sí" + (f" — {quien}" if quien else "")),
                ("Grados de alcohol", v(d.get("alcohol_grados"))),
                ("Autoridad que arriba", v(d.get("alcohol_autoridad")))]

    if s.es_liberacion:
        quien = {"A": "ejecutivo", "B": "otro conductor"}.get(d.get("alcohol_conductor"), "")
        gen = [("Liberada, enviar a", v(d.get("enviar_a"))), ("Causal", v(d.get("causal"))),
               ("Colisión", v(d.get("colision"))), ("Unidad responsable", sino(d.get("responsable"))),
               ("Medio de prueba", v(d.get("medio_prueba")))]
        gen += [("Daños", danos)] if d.get("danos") else []
        gen += alcohol(quien)
        gen += [("Nota", v(d.get("nota")))] if d.get("nota") else []
        otro = d.get("hay_participe") or b.get("seguro") or b.get("garantiza")
        seg = [("¿Se activa seguro HDI?", sino(d.get("activa_seguro"))),
               ("Motivo de activación", v(d.get("motivo_activacion"))), ("Pase médico", v(d.get("pase_medico"))),
               ("Otro partícipe", "Sí" if otro else "No")]
        seg += [("Seguro otro partícipe / garantiza", f"{v(b.get('seguro'))} / {v(b.get('garantiza'))}")] if (b.get("seguro") or b.get("garantiza")) else []
        return [
            (f"LIBERACIÓN EXPRÉS {s.folio}", [("Fecha", fecha), ("Ejecutivo(a)", v(d.get("ejecutivo"))),
                                              ("# Empleado", v(d.get("no_empleado"))),
                                              ("Económico / ruta", f"{v(d.get('economico'))} / {v(d.get('ruta'))}")]),
            ("GENERALIDADES", gen), ("SEGUROS", seg)]

    estado = lambda p: "Fallecido" if p.get("fallecido") else "Lesionado" if p.get("lesionado") else "Sin lesiones"
    comp = v(d.get("competencia")) + (f" ({d['competencia_otro']})" if d.get("competencia_otro") else "")
    lugar = v(d.get("lugar")) + (f" · {d['colonia']}" if d.get("colonia") else "")
    secciones = [
        (f"SINIESTRO {s.folio}", [("Fecha y hora", f"{fecha} {d.get('hora') or ''}".strip()),
                                  ("Ruta / económico", f"{v(d.get('ruta'))} / {v(d.get('economico'))}"),
                                  ("Competencia", comp), ("Reporte aseguradora", v(d.get("reporte_aseguradora"))),
                                  ("Lugar", lugar)]),
        ("PARTÍCIPE A · EJECUTIVO(A)", [
            ("Nombre", v(a.get("nombre"))), ("No. empleado", v(a.get("no_empleado"))), ("Teléfono", v(a.get("telefono"))),
            ("Edad / sexo", f"{v(a.get('edad'))} / {v(a.get('sexo'))}"),
            ("Licencia / vigencia", f"{v(a.get('licencia'))} / {v(a.get('vigencia'))}"), ("Tarjetón", v(a.get("tarjeton"))),
            ("Placas / modelo", f"{v(a.get('placas'))} / {v(a.get('modelo'))}"), ("Trayectoria", v(a.get("trayectoria"))),
            ("Estado", estado(a))]),
    ]
    if d.get("b_no_aplica"):
        secciones.append(("PARTÍCIPE B", [("Partícipe B", "No aplica — no hubo segundo partícipe")]))
    else:
        secciones.append(("PARTÍCIPE B", [
            ("Nombre", v(b.get("nombre"))), ("Teléfono", v(b.get("telefono"))),
            ("Edad / sexo", f"{v(b.get('edad'))} / {v(b.get('sexo'))}"),
            ("Vehículo", f"{v(b.get('marca'))} {b.get('modelo') or ''}".strip()),
            ("Placas", f"{v(b.get('placas'))} ({v(b.get('entidad'))})"), ("Estado", estado(b))]))
    les = [l for l in d.get("lesionados") or [] if (l.get("nombre") or "").strip()]
    if les:
        secciones.append(("LESIONADOS", [(f"{i}. {l['nombre']}", " · ".join(x for x in (
            l.get("direccion") or "", l.get("telefono") or "", f"Pase {l['pase_medico']}" if l.get("pase_medico") else "",
            f"Trasladado a {l['trasladado_a']}" if l.get("trasladado_a") else "") if x) or "—") for i, l in enumerate(les, 1)]))
    gen = [("Causal", v(d.get("causal"))), ("Colisión", v(d.get("colision"))), ("Unidad responsable", v(d.get("responsable"))),
           ("Medio de prueba", v(d.get("medio_prueba"))), ("¿Se activa seguro HDI?", sino(d.get("seguro_hdi"))),
           ("Seguro A / garantiza", f"HDI SEGUROS / {v(a.get('garantiza'))}")]
    if not d.get("b_no_aplica"):
        gen.append(("Seguro B / garantiza", f"{v(b.get('seguro'))} / {v(b.get('garantiza'))}"))
    gen.append(("Convenio", f"Sí — {d.get('forma_reparacion') or ''}".strip(" —") if d.get("aplica_convenio") else "No"))
    gen += alcohol(f"conductor {d['alcohol_conductor']}" if d.get("alcohol_conductor") else "")
    if a.get("liberada"):
        gen.append(("Unidad liberada", v(a.get("liberada_destino")) if a.get("liberada_destino") else "Sí (sin destino)"))
    if d.get("danos"):
        gen.append(("Daños", danos))
    if d.get("nota"):
        gen.append(("Nota", v(d.get("nota"))))
    secciones.append(("GENERALIDADES", gen))
    secciones.append(("REDACCIÓN DE HECHOS", [("", v(d.get("narrativa")))]))
    return secciones


def regenerar_liberacion(siniestro):
    datos = dict(siniestro.datos)
    datos["fecha"] = _fecha(datos.get("fecha")) or siniestro.creado.date()
    datos["firma_ejecutivo"] = ruta_imagen(siniestro, "firma_ejecutivo")
    datos["generalidades"] = resumen_generalidades_lib(datos)
    for viejo in siniestro.carpeta.glob("*.*"):
        if viejo.suffix in (".docx", ".xlsx", ".pdf"):
            viejo.unlink()
    siniestro.carpeta.mkdir(parents=True, exist_ok=True)
    return [llenar_liberacion(datos, siniestro.carpeta)]


def enviar_correo(siniestro, request=None):
    destinatarios = getattr(settings, "SINIESTROS_CORREOS", [])
    if not destinatarios:
        return False
    d = siniestro.datos
    enlace = request.build_absolute_uri(f"/reportes/{siniestro.folio}/") if request else ""
    capturo = siniestro.capturado_por.get_full_name() or siniestro.capturado_por.username
    if siniestro.es_liberacion:
        asunto = f"Liberación exprés {siniestro.folio} · {d.get('ejecutivo') or ''} · Eco {d.get('economico') or 's/n'}"
        cuerpo = "\n".join([
            "Se registró una liberación exprés desde oficina.", "",
            f"Folio: {siniestro.folio}",
            f"Fecha: {d.get('fecha', '')}",
            f"Ejecutivo(a): {d.get('ejecutivo', '')} (empleado {d.get('no_empleado', '')})",
            f"Económico / ruta: {d.get('economico', '')} / {d.get('ruta', '')}",
            f"Liberada, enviar a: {d.get('enviar_a') or 'sin capturar'}",
            f"¿Se activa seguro HDI?: {d.get('activa_seguro') or 'sin capturar'}",
            f"Capturó: {capturo}", "",
            f"Ver en la plataforma: {enlace}" if enlace else "",
        ])
        return _mandar(siniestro, asunto, cuerpo, destinatarios)
    asunto = f"Siniestro {siniestro.folio} · Ruta {d.get('ruta') or 's/r'} · {d.get('fecha', '')}"
    cuerpo = "\n".join([
        f"Se registró un siniestro desde campo.",
        "",
        f"Folio: {siniestro.folio}",
        f"Fecha y hora: {d.get('fecha', '')} {d.get('hora', '')}",
        f"Ruta / económico: {d.get('ruta', '')} / {d.get('economico', '')}",
        f"Lugar: {d.get('lugar', '')}",
        f"Ejecutivo(a): {(d.get('a') or {}).get('nombre', '')}",
        f"¿Se activa seguro HDI?: {({'SI': 'Sí', 'NO': 'No'}).get(d.get('seguro_hdi'), 'sin capturar')}",
        f"Capturó: {capturo}",
        "",
        f"Ver y revisar en la plataforma: {enlace}" if enlace else "",
        "",
        "Se adjuntan los formatos tal como se capturaron en campo; la versión vigente es la de la plataforma.",
    ])
    return _mandar(siniestro, asunto, cuerpo, destinatarios)


def _mandar(siniestro, asunto, cuerpo, destinatarios):
    msg = EmailMessage(asunto, cuerpo, to=destinatarios)
    for nombre in siniestro.documentos():
        msg.attach_file(str(siniestro.carpeta / nombre))
    for etq, nombres in fotos_para_mostrar(siniestro):
        for n in nombres:
            p = carpeta_fotos(siniestro) / n
            if p.is_file():
                msg.attach(f"{n}", p.read_bytes(), "image/jpeg" if n.endswith(".jpg") else "image/png")
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


def ve_todo(user):
    """Revisores, administradores y el rol de Consulta ven todos los reportes."""
    return puede_revisar(user) or user.has_perm("siniestros.consultar_siniestro")


def puede_ver(user, siniestro):
    return ve_todo(user) or siniestro.capturado_por_id == user.id


def registrar_descarga(siniestro, user, archivo):
    """Deja constancia de quién descargó qué formato (se ve en el detalle y en Descargas)."""
    Cambio.objects.create(siniestro=siniestro, usuario=user, tipo=Cambio.Tipo.DESCARGA,
                          descripcion=f"Descargó {archivo}")


def puede_descargar(user, siniestro):
    """Descargar en PDF."""
    return user.has_perm("siniestros.descargar_formatos") and puede_ver(user, siniestro)


def puede_descargar_originales(user, siniestro):
    """Descargar los editables (Word/Excel). El rol Consulta no lo tiene: solo PDF."""
    return user.has_perm("siniestros.descargar_originales") and puede_ver(user, siniestro)


# ------------------------------------------------------------------ PDF
def _soffice():
    import shutil
    for nombre in ("soffice", "libreoffice"):
        if shutil.which(nombre):
            return shutil.which(nombre)
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe",
              r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
              "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if Path(p).exists():
            return p
    return None


def pdf_de(siniestro, archivo):
    """Convierte un formato (docx/xlsx) a PDF con LibreOffice. Se guarda en carpeta/pdf y
    solo se vuelve a convertir si el formato cambió. Regresa la ruta o None si no se pudo."""
    import subprocess, tempfile, uuid
    origen = siniestro.carpeta / archivo
    if not origen.is_file():
        return None
    destino_dir = siniestro.carpeta / "pdf"
    destino = destino_dir / (origen.stem + ".pdf")
    if destino.is_file() and destino.stat().st_mtime >= origen.stat().st_mtime:
        return destino
    soffice = _soffice()
    if not soffice:
        log.warning("No está instalado LibreOffice: no se puede convertir a PDF")
        return None
    destino_dir.mkdir(parents=True, exist_ok=True)
    perfil = Path(tempfile.gettempdir()) / f"lo_{uuid.uuid4().hex}"  # perfil propio: permite conversiones simultáneas
    try:
        subprocess.run([soffice, f"-env:UserInstallation={perfil.as_uri()}", "--headless", "--norestore",
                        "--convert-to", "pdf", "--outdir", str(destino_dir), str(origen)],
                       check=True, timeout=75, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        log.exception("Falló la conversión a PDF de %s/%s", siniestro.folio, archivo)
        return None
    finally:
        import shutil
        shutil.rmtree(perfil, ignore_errors=True)
    return destino if destino.is_file() else None


def puede_editar(user, siniestro):
    return puede_revisar(user) and not siniestro.bloqueado
