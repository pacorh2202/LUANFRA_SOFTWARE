"""
Motor de similares.

Extiende al resto del catálogo lo que el módulo de piñones especiales ya hace
para los piñones: buscar en el histórico las piezas comparables y enseñar qué
se cobró y qué costó de verdad.

POR QUÉ SIN EMBEDDINGS, DE MOMENTO
  El módulo de piñones filtra por Paso, Z y Ø iguales. Es una regla, no un modelo,
  y funciona porque las piezas del taller son geometría, no prosa. Un cálculo
  determinista de parecido tiene tres ventajas sobre un vector:
    - es explicable ("mismo material, Ø un 4% mayor, mismo paso")
    - no necesita servicio externo ni GPU
    - se prueba con casos concretos

  Los embeddings entran después, y solo para la parte que las reglas no cubren:
  descripciones raras y piezas sin geometría reconocible.

CÓMO PUNTÚA
  Familia distinta = no comparable, se descarta. Es una barrera dura: un piñón
  y un casquillo nunca son comparables aunque compartan material y diámetro.
  El resto de campos suman según lo que de verdad mueve el precio.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.servicios.normalizador import PiezaNormalizada

# Cuánto pesa cada rasgo. Suman 1.0 sobre los rasgos disponibles en ambas piezas.
PESOS = {
    "material":  0.26,   # cambia el coste de partida y la maquinabilidad
    "diametro":  0.22,   # manda en el tiempo de mecanizado de revolución
    "dientes":   0.16,   # en dentado, define casi todo
    "paso":      0.12,
    "modulo":    0.14,   # mismo Z y distinto módulo no es la misma pieza
    "ramales":   0.08,   # simple, doble o triple cambia el tiempo de tallado
    "longitud":  0.10,
    "tratamiento": 0.08,
    "ancho":     0.06,
}

# Familias que sí admiten comparación cruzada: no son la misma pieza,
# pero el proceso de fabricación se parece lo bastante.
FAMILIAS_VECINAS: list[set[str]] = [
    {"pinon", "pinon_doble"},
    {"eje", "vastago", "husillo"},
    {"casquillo", "rodillo"},
    {"brida", "tapa"},
    {"corona", "cremallera"},
]

PENALIZACION_VECINA = 0.80   # comparar entre vecinas cuesta un 20% de parecido

# Grupos de material. Dos materiales distintos del mismo grupo se mecanizan
# de forma parecida y su precio de partida es del mismo orden: el parecido baja,
# pero no se anula. Un inox y un bronce sí son mundos distintos.
GRUPOS_MATERIAL: dict[str, str] = {
    "F-114": "acero_carbono", "F-1140": "acero_carbono",
    "ST-52": "acero_carbono", "ST-37": "acero_carbono",
    "F-125": "acero_aleado",  "F-127": "acero_aleado", "1.2379": "acero_aleado",
    "AISI 304": "inox", "AISI 316": "inox", "AISI 303": "inox", "AISI 420": "inox",
    "FUNDICION": "fundicion",
    "BRONCE": "no_ferrico", "ALUMINIO": "no_ferrico",
    "NYLON": "plastico", "POM": "plastico",
}
MISMO_GRUPO = 0.55      # mismo grupo, distinto material
GRUPO_DISTINTO = 0.15   # cambia el proceso y el coste de partida


@dataclass
class Comparable:
    pieza: PiezaNormalizada
    similitud: float
    motivos: list[str]
    referencia: object | None = None   # la fila del histórico, si la hay


def _parecido_numerico(a: float, b: float, tolerancia: float = 0.5) -> float:
    """
    1.0 si son iguales, decayendo con la diferencia relativa.
    A partir de `tolerancia` de diferencia relativa el parecido es 0.
    """
    if a is None or b is None or a <= 0 or b <= 0:
        return 0.0
    dif = abs(a - b) / max(a, b)
    return max(0.0, 1.0 - dif / tolerancia)


def _parecido_material(a: str, b: str) -> tuple[float, str]:
    if a == b:
        return 1.0, "mismo material"
    ga, gb = GRUPOS_MATERIAL.get(a), GRUPOS_MATERIAL.get(b)
    if ga and ga == gb:
        return MISMO_GRUPO, f"material del mismo grupo ({a} / {b})"
    return GRUPO_DISTINTO, f"material distinto ({a} / {b})"


def _relacion_familias(a: str | None, b: str | None) -> float | None:
    """Devuelve el factor de familia, o None si no son comparables en absoluto."""
    if a is None or b is None:
        return None
    if a == b:
        return 1.0
    for grupo in FAMILIAS_VECINAS:
        if a in grupo and b in grupo:
            return PENALIZACION_VECINA
    return None


def comparar(a: PiezaNormalizada, b: PiezaNormalizada) -> tuple[float, list[str]]:
    """Devuelve (similitud 0-1, motivos legibles)."""
    factor = _relacion_familias(a.familia, b.familia)
    if factor is None:
        return 0.0, ["familias distintas"]

    motivos: list[str] = []
    if factor < 1.0:
        motivos.append("familia parecida, no igual")

    puntos = 0.0
    disponible = 0.0

    def aporta(clave: str, valor: float, motivo: str | None):
        nonlocal puntos, disponible
        peso = PESOS[clave]
        disponible += peso
        puntos += peso * valor
        if motivo:
            motivos.append(motivo)

    if a.material and b.material:
        aporta("material", *_parecido_material(a.material, b.material))

    if a.diametro_mm and b.diametro_mm:
        v = _parecido_numerico(a.diametro_mm, b.diametro_mm, 0.40)
        dif = abs(a.diametro_mm - b.diametro_mm) / max(a.diametro_mm, b.diametro_mm)
        aporta("diametro", v,
               "mismo diámetro" if dif < 0.02 else f"diámetro {round(dif*100)}% distinto")

    if a.longitud_mm and b.longitud_mm:
        aporta("longitud", _parecido_numerico(a.longitud_mm, b.longitud_mm, 0.60), None)

    if a.ancho_mm and b.ancho_mm:
        aporta("ancho", _parecido_numerico(a.ancho_mm, b.ancho_mm, 0.60), None)

    if a.dientes_z and b.dientes_z:
        v = _parecido_numerico(a.dientes_z, b.dientes_z, 0.35)
        aporta("dientes", v,
               "mismo número de dientes" if a.dientes_z == b.dientes_z
               else f"Z {a.dientes_z} frente a {b.dientes_z}")

    if a.paso_cadena and b.paso_cadena:
        igual = a.paso_cadena == b.paso_cadena
        aporta("paso", 1.0 if igual else 0.0,
               "mismo paso de cadena" if igual else "paso de cadena distinto")

    if a.modulo and b.modulo:
        # Dos coronas con el mismo Z y distinto módulo no son la misma pieza:
        # cambia el diámetro, la fresa madre y el tiempo de tallado.
        v = _parecido_numerico(a.modulo, b.modulo, 0.25)
        aporta("modulo", v,
               "mismo módulo" if abs(a.modulo - b.modulo) < 0.02
               else f"módulo distinto ({a.modulo} / {b.modulo})")

    if a.ramales and b.ramales:
        igual = a.ramales == b.ramales
        aporta("ramales", 1.0 if igual else 0.2,
               None if igual else f"ramales distintos ({a.ramales} / {b.ramales})")

    if a.tratamientos or b.tratamientos:
        sa, sb = set(a.tratamientos), set(b.tratamientos)
        union = sa | sb
        v = len(sa & sb) / len(union) if union else 1.0
        aporta("tratamiento", v,
               None if v == 1.0 else f"tratamientos distintos ({', '.join(sorted(union)) or '—'})")

    if disponible == 0:
        # Solo coincide la familia y nada más: parecido bajo pero no nulo.
        return round(0.30 * factor, 4), motivos + ["solo coincide la familia"]

    return round(puntos / disponible * factor, 4), motivos


def buscar(objetivo: PiezaNormalizada,
           candidatas: list[PiezaNormalizada],
           minimo: float = 0.55,
           tope: int = 5) -> list[Comparable]:
    """
    Devuelve las mejores comparables por encima del umbral.

    Si no llega ninguna al umbral, devuelve lista vacía a propósito: es la señal
    de que la pieza va por la vía C y no se propone precio.
    """
    salida: list[Comparable] = []
    for c in candidatas:
        s, motivos = comparar(objetivo, c)
        if s >= minimo:
            salida.append(Comparable(pieza=c, similitud=s, motivos=motivos))
    salida.sort(key=lambda x: -x.similitud)
    return salida[:tope]


def decidir_via(objetivo: PiezaNormalizada,
                comparables: list[Comparable]) -> tuple[str, float]:
    """
    Traduce el resultado de la búsqueda a una de las tres vías, con su confianza.

    A_repetida  hay una pieza prácticamente idéntica
    B_similar   hay comparables razonables
    C_nueva     no hay apoyo suficiente: el sistema no propone precio
    """
    if objetivo.necesita_revision and not comparables:
        return "C_nueva", 0.20

    if not comparables:
        return "C_nueva", 0.25

    mejor = comparables[0].similitud
    apoyo = min(1.0, len(comparables) / 3)

    if mejor >= 0.93:
        return "A_repetida", round(min(0.95, 0.80 + 0.15 * apoyo), 3)
    if mejor >= 0.70:
        return "B_similar", round(0.45 + 0.30 * mejor * apoyo, 3)
    return "C_nueva", round(0.20 + 0.20 * mejor, 3)


def explicar(comparables: list[Comparable]) -> list[str]:
    """Frases cortas para la ficha de decisión."""
    return [
        f"{round(c.similitud * 100)}% de parecido: " +
        (", ".join(c.motivos) if c.motivos else "coincide en todo lo comparable")
        for c in comparables
    ]
