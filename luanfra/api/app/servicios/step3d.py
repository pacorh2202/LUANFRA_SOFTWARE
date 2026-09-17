"""
Analizador de ficheros STEP (ISO 10303).

POR QUÉ UN ANALIZADOR PROPIO Y NO UNA LIBRERÍA DE CAD
  Una librería de núcleo geométrico (OpenCascade y compañía) pesa cientos de
  megas, es un infierno de instalar y hace mucho más de lo que necesitamos.
  Un STEP es un fichero de texto con una gramática sencilla, y para presupuestar
  no hace falta reconstruir el sólido: hace falta saber qué tipo de fichero es,
  qué envolvente tiene, de qué está hecho y si trae tolerancias.

  Cuando llegue el momento de reconocer operaciones de verdad (roscas, ranuras,
  vaciados), entonces sí habrá que meter un núcleo geométrico. Mientras tanto,
  esto responde el 80% de las preguntas con el 2% del esfuerzo.

LO QUE SÍ SACA
  - Protocolo (AP203, AP214, AP242) y de qué CAD salió
  - Unidades del modelo
  - Envolvente real, calculada de los puntos cartesianos del fichero
  - Recuento de superficies por tipo: cilindros, planos, conos, toros
  - Si el fichero trae PMI: tolerancias, acabados y referencias legibles
  - Aviso cuando el fichero es una malla o un ensamblaje

LO QUE NO SACA, Y NO HAY QUE FINGIR QUE SÍ
  No reconoce operaciones. Sabe que hay 14 caras cilíndricas, no que sean
  ocho agujeros pasantes M8 y tres escalones de torneado. Para eso hace falta
  reconocimiento de características, que es otro problema.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# --- Protocolos de aplicación ---------------------------------------------

PROTOCOLOS = {
    "AUTOMOTIVE_DESIGN": ("AP214", "Geometría y color. Sin tolerancias legibles."),
    "CONFIG_CONTROL_DESIGN": ("AP203", "Solo geometría. Es el más antiguo."),
    "AP203_CONFIGURATION_CONTROLLED_3D_DESIGN": ("AP203", "Solo geometría."),
    "MANAGED_MODEL_BASED_3D_ENGINEERING": ("AP242", "El bueno: admite PMI, "
                                           "es decir tolerancias y acabados legibles por máquina."),
    "STRUCTURAL_FRAME_SCHEMA": ("AP227", "Tuberías y estructuras, no piezas mecanizadas."),
}

# Entidades que delatan información de fabricación (PMI)
ENTIDADES_PMI = (
    "DIMENSIONAL_SIZE", "DIMENSIONAL_LOCATION", "GEOMETRIC_TOLERANCE",
    "PLUS_MINUS_TOLERANCE", "DATUM", "SURFACE_TEXTURE", "TOLERANCE_ZONE",
    "ANGULARITY_TOLERANCE", "POSITION_TOLERANCE", "FLATNESS_TOLERANCE",
    "CYLINDRICITY_TOLERANCE", "PERPENDICULARITY_TOLERANCE", "RUNOUT_TOLERANCE",
)

SUPERFICIES = {
    "CYLINDRICAL_SURFACE": "cilindros",
    "PLANE": "planos",
    "CONICAL_SURFACE": "conos",
    "TOROIDAL_SURFACE": "toros",
    "SPHERICAL_SURFACE": "esferas",
    "B_SPLINE_SURFACE": "superficies libres",
}

UNIDADES = {
    "MILLI.*METRE": ("mm", 1.0),
    "CENTI.*METRE": ("cm", 10.0),
    r"\bMETRE": ("m", 1000.0),
    "INCH": ("pulgadas", 25.4),
}


@dataclass
class AnalisisStep:
    fichero: str
    protocolo: str | None = None
    nota_protocolo: str = ""
    origen_cad: str | None = None
    unidad: str = "mm"
    factor_mm: float = 1.0
    solidos: int = 0
    es_ensamblaje: bool = False
    superficies: dict[str, int] = field(default_factory=dict)
    tiene_pmi: bool = False
    pmi_encontrado: list[str] = field(default_factory=list)
    largo_mm: float | None = None
    ancho_mm: float | None = None
    alto_mm: float | None = None
    puntos: int = 0
    avisos: list[str] = field(default_factory=list)
    confianza: float = 0.0

    @property
    def envolvente(self) -> tuple[float, float, float] | None:
        if None in (self.largo_mm, self.ancho_mm, self.alto_mm):
            return None
        return (self.largo_mm, self.ancho_mm, self.alto_mm)

    @property
    def es_de_revolucion(self) -> bool:
        """
        Heurística: si la envolvente tiene dos lados casi iguales y hay
        cilindros, casi seguro que es una pieza de torno.
        """
        e = self.envolvente
        if not e or not self.superficies.get("cilindros"):
            return False
        a, b, c = sorted(e)
        return abs(a - b) / max(b, 1e-9) < 0.08

    def volumen_envolvente_cm3(self) -> float | None:
        e = self.envolvente
        return round(e[0] * e[1] * e[2] / 1000.0, 2) if e else None

    def peso_bruto_kg(self, densidad_kg_dm3: float = 7.85) -> float | None:
        """
        Peso del taco de partida, no de la pieza acabada.

        Es lo que hay que comprar, así que para presupuestar material es más
        útil que el volumen real de la pieza. Para una pieza de revolución se
        usa el cilindro circunscrito, no el prisma: si no, se compraría de más.
        """
        e = self.envolvente
        if not e:
            return None
        if self.es_de_revolucion:
            a, b, c = sorted(e)
            volumen_mm3 = math.pi * (b / 2) ** 2 * c
        else:
            volumen_mm3 = e[0] * e[1] * e[2]
        return round(volumen_mm3 / 1e6 * densidad_kg_dm3, 3)


def analizar_step(ruta: str | Path, max_bytes: int = 200_000_000) -> AnalisisStep:
    ruta = Path(ruta)
    r = AnalisisStep(fichero=ruta.name)

    if not ruta.exists():
        r.avisos.append("El fichero no existe.")
        return r
    if ruta.stat().st_size > max_bytes:
        r.avisos.append("Fichero demasiado grande para analizar entero.")
        return r

    texto = ruta.read_text(encoding="utf-8", errors="ignore")

    if "ISO-10303" not in texto[:400]:
        r.avisos.append("No parece un fichero STEP válido.")
        return r

    cabecera = texto.split("DATA;")[0] if "DATA;" in texto else texto[:4000]

    # --- Protocolo ---
    for clave, (nombre, nota) in PROTOCOLOS.items():
        if re.search(clave, cabecera):
            r.protocolo, r.nota_protocolo = nombre, nota
            break
    if r.protocolo is None:
        r.avisos.append("Protocolo STEP no reconocido.")

    # --- CAD de origen ---
    m = re.search(r"FILE_NAME\s*\((.*?)\)\s*;", cabecera, re.S)
    if m:
        cadenas = re.findall(r"'([^']*)'", m.group(1))
        origen = next((c for c in cadenas if any(
            x in c.upper() for x in ("SOLIDWORKS", "CATIA", "INVENTOR", "NX",
                                     "CREO", "FUSION", "FREECAD", "SOLID EDGE",
                                     "AUTOCAD", "RHINO"))), None)
        r.origen_cad = origen

    # --- Unidades ---
    for patron, (nombre, factor) in UNIDADES.items():
        if re.search(patron, texto[:20000]):
            r.unidad, r.factor_mm = nombre, factor
            break
    if r.unidad != "mm":
        r.avisos.append(f"El modelo está en {r.unidad}: se convierte a milímetros.")

    # --- Recuento de entidades ---
    conteo = Counter()
    for entidad in SUPERFICIES:
        conteo[SUPERFICIES[entidad]] = len(re.findall(rf"=\s*{entidad}\b", texto))
    r.superficies = {k: v for k, v in conteo.items() if v}

    r.solidos = len(re.findall(r"=\s*MANIFOLD_SOLID_BREP\b", texto)) or \
                len(re.findall(r"=\s*ADVANCED_BREP_SHAPE_REPRESENTATION\b", texto))
    productos = len(re.findall(r"=\s*PRODUCT\s*\(", texto))
    r.es_ensamblaje = productos > 1 or r.solidos > 1
    if r.es_ensamblaje:
        r.avisos.append(
            f"El fichero contiene {max(productos, r.solidos)} piezas. "
            "Para presupuestar hace falta un fichero por pieza.")

    if len(re.findall(r"=\s*TRIANGULATED_FACE_SET\b", texto)) or \
       len(re.findall(r"=\s*TESSELLATED_", texto)):
        r.avisos.append(
            "El fichero es una malla, no un sólido exacto. Sirve para verlo, "
            "no para medir ni presupuestar.")

    # --- PMI ---
    encontrado = [e for e in ENTIDADES_PMI if re.search(rf"=\s*{e}\b", texto)]
    r.pmi_encontrado = encontrado
    r.tiene_pmi = len(encontrado) > 0
    if not r.tiene_pmi:
        r.avisos.append(
            "El fichero no trae tolerancias ni acabados. Habrá que sacarlos "
            "del plano en PDF o preguntarlos al cliente.")

    # --- Envolvente, a partir de los puntos cartesianos ---
    puntos = re.findall(
        r"CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(\s*"
        r"(-?[\d.EFB+-]+)\s*,\s*(-?[\d.EFB+-]+)\s*,\s*(-?[\d.EFB+-]+)\s*\)", texto)
    if puntos:
        xs, ys, zs = [], [], []
        for x, y, z in puntos:
            try:
                xs.append(float(x)); ys.append(float(y)); zs.append(float(z))
            except ValueError:
                continue
        if xs:
            r.puntos = len(xs)
            r.largo_mm = round((max(xs) - min(xs)) * r.factor_mm, 2)
            r.ancho_mm = round((max(ys) - min(ys)) * r.factor_mm, 2)
            r.alto_mm = round((max(zs) - min(zs)) * r.factor_mm, 2)
            if max(r.largo_mm, r.ancho_mm, r.alto_mm) == 0:
                r.avisos.append("La envolvente sale a cero: el fichero está vacío o corrupto.")
    else:
        r.avisos.append("No se han encontrado puntos: no se puede medir la envolvente.")

    # --- Confianza ---
    puntuacion = 0.0
    if r.protocolo:            puntuacion += 0.20
    if r.protocolo == "AP242": puntuacion += 0.10
    if r.envolvente:           puntuacion += 0.25
    if r.solidos == 1:         puntuacion += 0.20
    if r.tiene_pmi:            puntuacion += 0.25
    if r.superficies:          puntuacion += 0.10
    if r.es_ensamblaje:        puntuacion *= 0.5
    r.confianza = round(min(1.0, puntuacion), 3)

    return r


def recomendaciones(a: AnalisisStep) -> list[str]:
    """Qué pedirle al cliente para que el presupuesto salga bien."""
    faltas = []
    if a.protocolo and a.protocolo != "AP242":
        faltas.append(
            f"El fichero es {a.protocolo}. Pidiendo AP242 vendrían las tolerancias "
            "dentro del propio modelo y no habría que leerlas del plano.")
    if not a.tiene_pmi:
        faltas.append("Sin PMI: hay que adjuntar el plano en PDF con las tolerancias.")
    if a.es_ensamblaje:
        faltas.append("Enviar un fichero por pieza, no el conjunto.")
    if a.unidad != "mm":
        faltas.append(f"El modelo viene en {a.unidad}: mejor en milímetros.")
    if a.confianza < 0.5:
        faltas.append("Con este fichero no se puede presupuestar solo: hace falta el plano.")
    return faltas


def resumen_para_presupuesto(a: AnalisisStep, densidad: float = 7.85) -> dict:
    """Lo que el presupuestador necesita saber del modelo."""
    return {
        "envolvente_mm": a.envolvente,
        "es_de_revolucion": a.es_de_revolucion,
        "volumen_envolvente_cm3": a.volumen_envolvente_cm3(),
        "peso_bruto_kg": a.peso_bruto_kg(densidad),
        "caras_cilindricas": a.superficies.get("cilindros", 0),
        "caras_planas": a.superficies.get("planos", 0),
        "superficies_libres": a.superficies.get("superficies libres", 0),
        "tiene_tolerancias": a.tiene_pmi,
        "confianza": a.confianza,
        "avisos": a.avisos,
        "recomendaciones": recomendaciones(a),
    }
