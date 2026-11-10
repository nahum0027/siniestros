"""
Tablero (dashboard) del inicio: números y gráficas de los reportes en un periodo.

La fecha de cada reporte es la fecha del hecho; si no se capturó, la fecha en que se creó.
"""
from collections import Counter
from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Siniestro
from .servicios import CAUSALES, CODIGOS_LESIONADO, MOTIVOS_ACTIVACION, lista_danos

PERIODOS = [("hoy", "Hoy"), ("semana", "7 días"), ("mes", "Este mes"), ("anio", "Este año"), ("todo", "Todo")]
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
                "octubre", "noviembre", "diciembre"]


def _rango(periodo, hoy):
    """(inicio, fin, inicio_anterior, fin_anterior, texto). fin es inclusivo."""
    if periodo == "hoy":
        ayer = hoy - timedelta(days=1)
        return hoy, hoy, ayer, ayer, "hoy", "ayer"
    if periodo == "semana":
        ini = hoy - timedelta(days=6)
        return ini, hoy, ini - timedelta(days=7), ini - timedelta(days=1), "los últimos 7 días", "los 7 días anteriores"
    if periodo == "anio":
        ini = date(hoy.year, 1, 1)
        ant_fin = date(hoy.year - 1, hoy.month, min(hoy.day, 28))
        return ini, hoy, date(hoy.year - 1, 1, 1), ant_fin, f"{hoy.year}", f"el mismo corte de {hoy.year - 1}"
    if periodo == "todo":
        return None, None, None, None, "todo el historial", ""
    # mes (por omisión): del 1 a hoy, contra el mismo corte del mes anterior
    ini = hoy.replace(day=1)
    fin_ant_mes = ini - timedelta(days=1)
    ant_ini = fin_ant_mes.replace(day=1)
    ant_fin = ant_ini.replace(day=min(hoy.day, fin_ant_mes.day))
    return ini, hoy, ant_ini, ant_fin, f"{MESES_LARGOS[hoy.month - 1]} {hoy.year}", "el mismo corte del mes anterior"


def _filtrar(qs, ini, fin):
    if ini is None:
        return qs
    return qs.filter(Q(fecha_hecho__range=(ini, fin))
                     | Q(fecha_hecho__isnull=True, creado__date__range=(ini, fin)))


def _barras(contador, tope=8, otros="Otros"):
    """[(etiqueta, n, %ancho)] ordenado de mayor a menor; lo que pasa del tope se junta en 'Otros'."""
    comunes = contador.most_common()
    filas = comunes[:tope]
    resto = sum(n for _, n in comunes[tope:])
    if resto:
        filas.append((otros, resto))
    mayor = max((n for _, n in filas), default=0) or 1
    return [(etq, n, round(n * 100 / mayor, 1)) for etq, n in filas]


# mismo destino escrito distinto en siniestros y en liberaciones
DESTINOS = {"CONTINÚA EN RUTA": "Continúa en ruta", "CONTINUAR EN RUTA": "Continúa en ruta",
            "MANTENIMIENTO": "Mantenimiento", "AVANCE A MANTENIMIENTO": "Mantenimiento",
            "VÍA LÁCTEA": "Patio Vía Láctea", "AVANCE A PATIO VÍA LÁCTEA": "Patio Vía Láctea",
            "PATIO LA NACIÓN": "Patio La Nación", "AVANCE A PATIO LA NACIÓN": "Patio La Nación"}


def _sin_acentos(texto):
    import unicodedata
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()


def _bonito(texto):
    t = (texto or "").strip()
    return t[:1].upper() + t[1:].lower() if t else ""


def _fecha(s):
    return s.fecha_hecho or timezone.localtime(s.creado).date()


def calcular(base, periodo, hoy=None):
    hoy = hoy or timezone.localdate()
    if periodo not in dict(PERIODOS):
        periodo = "mes"
    ini, fin, ant_ini, ant_fin, texto, texto_ant = _rango(periodo, hoy)
    qs = list(_filtrar(base, ini, fin).select_related("capturado_por"))
    anterior = _filtrar(base, ant_ini, ant_fin).count() if ini is not None else None

    S, L = Siniestro.Tipo.SINIESTRO, Siniestro.Tipo.LIBERACION
    total = len(qs)
    sin = [s for s in qs if s.tipo == S]
    lib = [s for s in qs if s.tipo == L]

    resp = Counter()
    colisiones, rutas, danos, destinos, capturistas = Counter(), Counter(), Counter(), Counter(), Counter()
    alcohol = hdi = con_lesionados = lesionados = danos_total = 0
    no_dimensionar = se_retiran = 0
    causales, motivos, codigos = Counter(), Counter(), Counter()
    nombres_causal = dict(CAUSALES)
    semanas = {}  # lunes -> contadores, como la tabla "SEMANA / DEL / AL" del Excel de indicadores
    for s in qs:
        d = s.datos or {}
        r = str(d.get("responsable") or "").upper()
        resp["SI" if r in ("SI", "SÍ") else "NO" if r == "NO" else "SD"] += 1
        if d.get("colision"):
            colisiones[_bonito(d["colision"])] += 1
        if (s.ruta or "").strip():
            rutas[s.ruta.strip().upper()] += 1
        if d.get("danos"):
            danos_total += 1
        for n in lista_danos(d):
            danos[_bonito(n)] += 1
        if d.get("alcohol"):
            alcohol += 1
        if str(d.get("seguro_hdi") or d.get("activa_seguro") or "").upper() in ("SI", "SÍ"):
            hdi += 1
        # causal: catálogo fijo; lo que no está en la lista (o "Otros") cuenta como Otros
        causal = (d.get("causal") or "").strip().upper()
        if causal:
            causales[nombres_causal.get(causal, "Otros") if causal != "OTROS" else "Otros"] += 1
        es_no_dim = causal == "NO DIMENSIONA"  # igual que el Excel: solo "No dimensiona" (no "Tercero no dimensiona")
        no_dimensionar += es_no_dim
        motivo = (d.get("motivo_activacion") or "").strip().upper()
        if motivo:
            motivos[dict(MOTIVOS_ACTIVACION).get(motivo, _bonito(motivo))] += 1
        les = [x for x in d.get("lesionados") or [] if (x.get("nombre") or "").strip()]
        if les:
            con_lesionados += 1
            lesionados += len(les)
        retiran = sum(1 for x in les if x.get("se_retira"))
        se_retiran += retiran
        cod_reporte = Counter((x.get("codigo") or "SIN").upper() for x in les)
        codigos.update(cod_reporte)
        activa = str(d.get("seguro_hdi") or d.get("activa_seguro") or "").upper() in ("SI", "SÍ")
        # renglón semanal
        f = _fecha(s)
        lunes = f - timedelta(days=f.weekday())
        w = semanas.setdefault(lunes, Counter())
        w["total"] += 1
        w["resp"] += r in ("SI", "SÍ")
        w["no_resp"] += r == "NO"
        w["no_dim"] += es_no_dim
        for c, _ in CODIGOS_LESIONADO:
            w[c] += cod_reporte.get(c, 0)
        w["activa"] += activa
        w["garantizan"] += motivo == "NOS GARANTIZAN"
        w["pases"] += motivo == "PASES MÉDICOS"
        w["retira"] += retiran
        destino = d.get("enviar_a") if s.tipo == L else ((d.get("a") or {}).get("liberada_destino")
                                                          if (d.get("a") or {}).get("liberada") else "")
        if destino:
            destinos[DESTINOS.get(destino.strip().upper(), _bonito(destino))] += 1
        cap = s.capturado_por
        capturistas[(cap.get_full_name() or cap.username) if cap else "—"] += 1

    con_resp = resp["SI"] + resp["NO"]
    pct = lambda n, d: round(n * 100 / d) if d else 0

    # tendencia: por día (hoy, 7 días, mes) o por mes (año, todo)
    por_fecha = Counter(_fecha(s) for s in qs)
    tendencia = []
    if periodo in ("hoy", "semana"):
        for i in range(6, -1, -1):
            dia = hoy - timedelta(days=i)
            tendencia.append((f"{dia.day} {MESES[dia.month - 1]}", por_fecha.get(dia, 0), dia == hoy))
        titulo_tend = "Reportes por día · últimos 7 días"
    elif periodo == "mes":
        for dia_n in range(1, hoy.day + 1):
            dia = hoy.replace(day=dia_n)
            tendencia.append((str(dia_n), por_fecha.get(dia, 0), dia == hoy))
        titulo_tend = f"Reportes por día · {texto}"
    else:
        meses = Counter((f.year, f.month) for f in por_fecha.elements())
        if periodo == "anio":
            claves = [(hoy.year, m) for m in range(1, hoy.month + 1)]
            titulo_tend = f"Reportes por mes · {hoy.year}"
        else:
            claves = []
            y, m = hoy.year, hoy.month
            for _ in range(12):
                claves.append((y, m))
                y, m = (y, m - 1) if m > 1 else (y - 1, 12)
            claves.reverse()
            titulo_tend = "Reportes por mes · últimos 12 meses"
        for (y, m) in claves:
            etq = MESES[m - 1] + (f" {str(y)[2:]}" if periodo == "todo" else "")
            tendencia.append((etq, meses.get((y, m), 0), (y, m) == (hoy.year, hoy.month)))
    mayor_t = max((n for _, n, _ in tendencia), default=0) or 1
    tendencia = [(etq, n, round(n * 100 / mayor_t, 1), actual) for etq, n, actual in tendencia]
    # etiqueta del eje: todas si caben, si no una de cada tantas
    paso = 1 if len(tendencia) <= 12 else 5
    tendencia = [(etq if (i % paso == 0 or i == len(tendencia) - 1) else "", etq, n, h, act)
                 for i, (etq, n, h, act) in enumerate(tendencia)]

    # comparación con el periodo anterior: en % si hay base suficiente; con pocos reportes, en número
    delta = delta_txt = None
    if anterior is not None and (total or anterior):
        dif = total - anterior
        if anterior >= 5:
            delta = round(dif * 100 / anterior)
            delta_txt = f"{'▲ +' if delta > 0 else '▼ ' if delta < 0 else '= '}{delta}%"
        else:
            delta = dif
            delta_txt = f"{'▲ +' if dif > 0 else '▼ ' if dif < 0 else '= '}{dif}"

    return {
        "periodo": periodo, "periodos": PERIODOS, "texto": texto, "texto_ant": texto_ant,
        "total": total, "anterior": anterior, "delta": delta, "delta_txt": delta_txt,
        "siniestros": len(sin), "liberaciones": len(lib),
        "resp_si": resp["SI"], "resp_no": resp["NO"], "resp_sd": resp["SD"],
        "resp_pct": pct(resp["SI"], con_resp), "con_resp": con_resp,
        "resp_barra": [("Sí", resp["SI"], pct(resp["SI"], total), "si"), ("No", resp["NO"], pct(resp["NO"], total), "no"),
                       ("Sin dato", resp["SD"], pct(resp["SD"], total), "sd")],
        "alcohol": alcohol, "hdi": hdi, "danos_total": danos_total,
        "no_dimensionar": no_dimensionar, "se_retiran": se_retiran,
        "pases": motivos.get("Pases médicos", 0), "garantizan": motivos.get("Nos garantizan", 0),
        "cristal": motivos.get("Orden de cristal", 0), "garantizamos": motivos.get("Garantizamos a tercero", 0),
        "codigos": [(n, codigos.get(c, 0), c.lower()) for c, n in CODIGOS_LESIONADO],
        "sin_codigo": codigos.get("SIN", 0),
        "causales": _barras(causales, tope=14), "motivos": _barras(motivos),
        "semanas": [(lunes, lunes + timedelta(days=6), w) for lunes, w in sorted(semanas.items(), reverse=True)][:26], "hdi_pct": pct(hdi, total),
        "con_lesionados": con_lesionados, "lesionados": lesionados,
        "colisiones": _barras(colisiones), "rutas": _barras(rutas), "danos": _barras(danos),
        "destinos": _barras(destinos), "capturistas": _barras(capturistas, tope=6),
        "tendencia": tendencia, "titulo_tend": titulo_tend,
        "sin_datos": total == 0,
    }
