"""
Prueba rápida sin Django (desde la raíz del proyecto):  python prueba.py
Genera los 3 formatos con datos ficticios en la carpeta salida/
"""
from datetime import date
from pathlib import Path
from PIL import Image, ImageDraw

from siniestros import generar

BASE = Path(__file__).resolve().parent
SALIDA = BASE / "salida"
SALIDA.mkdir(exist_ok=True)


def firma_falsa(nombre, texto):
    """Simula una firma dibujada en el celular (PNG transparente)."""
    img = Image.new("RGBA", (400, 120), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    d.line([(20, 90), (90, 30), (150, 85), (220, 25), (300, 80), (380, 40)], fill="navy", width=5)
    d.text((20, 100), texto, fill="navy")
    ruta = SALIDA / f"{nombre}.png"
    img.save(ruta)
    return ruta


def croquis_falso():
    img = Image.new("RGB", (800, 450), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 180, 800, 270], fill="#ddd")
    d.rectangle([380, 0, 470, 450], fill="#ddd")
    d.rectangle([200, 195, 300, 235], outline="blue", width=4); d.text((215, 208), "A (unidad)", fill="blue")
    d.rectangle([395, 120, 455, 175], outline="red", width=4); d.text((405, 140), "B", fill="red")
    d.text((560, 220), "Av. 5 de Febrero", fill="black")
    ruta = SALIDA / "croquis.png"
    img.save(ruta)
    return ruta


datos = {
    "fecha": date(2026, 10, 9), "hora": "13:45",
    "ruta": "L-55", "economico": "1234",
    "lugar": "Av. 5 de Febrero entre Calle Industrias y Av. Universidad",
    "colonia": "Col. Centro", "competencia": "MUNICIPAL",
    "reporte_aseguradora": "HDI-2026-000123",
    "agente_nombre": "Juan Pérez López", "perito_nombre": "María Gómez",
    "narrativa": ("Siendo aproximadamente las 13:45 hrs, la unidad circulaba sobre Av. 5 de Febrero "
                  "con dirección norte cuando el vehículo B invadió el carril al incorporarse..."),
    "seguro_activo": "SÍ", "pases_medicos": "0", "causal": "INVASIÓN DE CARRIL",
    "seguro_garantiza": "HDI SEGUROS", "colision": "LATERAL", "medio_prueba": "VIDEO DE CÁMARA A BORDO",
    "responsable": False, "nota": "Sin lesionados",
    "aplica_convenio": True, "forma_reparacion": "pago en efectivo de $3,500.00 el día 12/10/2026",
    "a": {"nombre": "Pedro Ramírez Soto", "no_empleado": "4521", "sexo": "M", "edad": 41,
          "nacimiento": date(1985, 3, 7), "telefono": "442 123 4567",
          "licencia": "QRO-123456", "vigencia": "2028", "tarjeton": "TIO-7788",
          "placas": "123-ABC", "modelo": 2022, "marca": "M. BENZ", "trayectoria": "De sur a norte",
          "domicilio": "Calle Conocida 1, Querétaro", "identificacion": "INE"},
    "b": {"nombre": "Laura Méndez Ruiz", "sexo": "F", "edad": 33, "nacimiento": date(1993, 11, 21),
          "telefono": "442 765 4321", "domicilio": "Av. Siempre Viva 742, Querétaro",
          "placas": "UAB-123-C", "entidad": "QUERÉTARO", "marca": "Nissan", "tipo_servicio": "PARTICULAR",
          "modelo": 2019, "seguro": "GNP", "garantiza": "—", "trayectoria": "De oriente a poniente",
          "identificacion": "INE"},
    "lesionados": [{"nombre": "Ana Torres (pasajera)", "direccion": "Col. Lomas", "telefono": "442 000 1111",
                    "pase_medico": "HDI-PM-01", "trasladado_a": "Hospital General"}],
    "anexos": [{"aplica": True, "art": "45", "fracc": "III"}, {"aplica": False}, {"aplica": False},
               {"aplica": False}, {"aplica": False}, {"aplica": False}],
    "croquis": croquis_falso(),
    "firma_ejecutivo": firma_falsa("f_ej", "Pedro R."),
    "firma_agente": firma_falsa("f_ag", "Juan P."),
    "firma_perito": firma_falsa("f_pe", "María G."),
    "firma_conv_a": firma_falsa("f_ca", "Pedro R."),
    "firma_conv_b": firma_falsa("f_cb", "Laura M."),
}

for f in generar.generar_todo(datos, SALIDA):
    print("Generado:", f)
