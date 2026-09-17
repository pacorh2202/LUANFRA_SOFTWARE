"""
Indicadores de taller.

POR QUÉ UN CATÁLOGO Y NO UNA LISTA DE CONSULTAS
  Un indicador mal definido es peor que no tenerlo: dos personas miran el mismo
  número y entienden cosas distintas. Aquí cada uno lleva su fórmula escrita,
  su unidad, su objetivo y qué datos necesita para poder calcularse.

  Eso último importa mucho. Buena parte de estos indicadores NO se pueden
  calcular hoy en Luanfra porque falta el dato de partida. El sistema lo dice
  en vez de devolver un cero que parece un dato.

SOBRE LOS OBJETIVOS
  Los valores de referencia son para taller de mecanizado por encargo, que no
  es lo mismo que producción en serie. Un OEE del 85% es "clase mundial" en una
  línea que hace siempre la misma pieza; en un taller con lotes de 1 a 250 y
  sesenta máquinas distintas, entre el 45% y el 65% ya es bueno. Poner el
  objetivo en 85% solo consigue que nadie se lo tome en serio.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

# ===========================================================================
# Catálogo
# ===========================================================================

@dataclass(frozen=True)
class Definicion:
    clave: str
    nombre: str
    formula: str
    unidad: str
    objetivo: float | None
    sentido: str                 # mayor_mejor | menor_mejor
    categoria: str
    para_que: str
    datos_necesarios: tuple[str, ...]


CATALOGO: tuple[Definicion, ...] = (
    # --- Eficiencia de máquina -------------------------------------------
    Definicion("oee", "OEE", "Disponibilidad × Rendimiento × Calidad", "%", 60,
               "mayor_mejor", "maquina",
               "El indicador rey. Si baja, uno de los tres factores lo explica.",
               ("partes con inicio y fin", "cantidad buena y rechazo", "tiempo estimado")),
    Definicion("disponibilidad", "Disponibilidad",
               "Tiempo produciendo / Tiempo planificado", "%", 80, "mayor_mejor",
               "maquina", "Cuánto tiempo la máquina está haciendo algo.",
               ("partes con inicio y fin", "calendario de turnos")),
    Definicion("rendimiento", "Rendimiento",
               "(Piezas × tiempo ideal) / Tiempo produciendo", "%", 85, "mayor_mejor",
               "maquina", "Si va más lenta de lo que debería cuando está en marcha.",
               ("tiempo estimado por pieza", "partes reales")),
    Definicion("calidad_oee", "Calidad",
               "Piezas buenas / Piezas totales", "%", 98.5, "mayor_mejor",
               "maquina", "Qué parte de lo producido vale.",
               ("cantidad buena y rechazo en el parte",)),
    Definicion("utilizacion", "Utilización",
               "Horas cargadas / Horas disponibles", "%", 75, "mayor_mejor",
               "maquina", "Si una máquina sobra o falta.",
               ("cola por máquina", "calendario")),

    # --- Preparación -------------------------------------------------------
    Definicion("ratio_preparacion", "Peso de la preparación",
               "Minutos de preparación / Minutos totales", "%", 20, "menor_mejor",
               "preparacion",
               "En lotes pequeños el setup se come el turno. Bajarlo es la palanca "
               "más grande de un taller por encargo.",
               ("minutos de preparación y de mecanizado por parte",)),
    Definicion("lote_medio", "Tamaño medio de lote", "Media de unidades por orden",
               "uds", None, "mayor_mejor", "preparacion",
               "Explica el ratio de preparación: a menor lote, más peso del setup.",
               ("cantidad por orden",)),

    # --- Flujo y plazos ----------------------------------------------------
    Definicion("plazo_real", "Plazo real de entrega",
               "Días desde el pedido hasta la entrega", "días", 20, "menor_mejor",
               "flujo", "Lo que de verdad tarda un pedido, no lo que se promete.",
               ("fecha de pedido", "fecha de albarán")),
    Definicion("eficiencia_flujo", "Eficiencia de flujo",
               "Tiempo trabajando / Plazo total", "%", 15, "mayor_mejor", "flujo",
               "El más revelador: qué parte del plazo se está mecanizando de "
               "verdad. En un taller típico está entre el 5% y el 15%. El resto "
               "es la pieza esperando.",
               ("partes de trabajo", "fechas de pedido y entrega")),
    Definicion("cumplimiento_plazo", "Plazos cumplidos",
               "Órdenes entregadas a tiempo / Órdenes entregadas", "%", 90,
               "mayor_mejor", "flujo", "La promesa que se le hace al cliente.",
               ("fecha prevista", "fecha de cierre")),
    Definicion("retraso_medio", "Retraso medio",
               "Media de días de retraso de las que llegan tarde", "días", 3,
               "menor_mejor", "flujo",
               "No es lo mismo incumplir un 20% por un día que por tres semanas.",
               ("fecha prevista", "fecha de cierre")),
    Definicion("wip", "Trabajo en curso",
               "Órdenes abiertas sin cerrar", "órdenes", None, "menor_mejor",
               "flujo",
               "Cuanto más trabajo suelto hay en el taller, más largo es el plazo "
               "de todo. Es contraintuitivo y es así.",
               ("órdenes abiertas",)),
    Definicion("cola_cuello_botella", "Cola del cuello de botella",
               "Días de carga del centro más saturado", "días", 12, "menor_mejor",
               "flujo", "El plazo de la casa lo marca la máquina más cargada.",
               ("cola por máquina",)),

    # --- Calidad -----------------------------------------------------------
    Definicion("rechazo", "Rechazo",
               "Piezas rechazadas / Piezas fabricadas", "%", 1.5, "menor_mejor",
               "calidad", "Material y horas tirados.",
               ("cantidad buena y rechazo",)),
    Definicion("coste_no_calidad", "Coste del rechazo",
               "Piezas rechazadas × coste unitario", "€", None, "menor_mejor",
               "calidad", "El rechazo en euros suele sorprender más que en porcentaje.",
               ("rechazo", "coste por pieza")),
    Definicion("incidencias", "Órdenes con incidencia",
               "Órdenes con causa de incidencia / Órdenes", "%", 10, "menor_mejor",
               "calidad", "Dónde se rompe el proceso, aunque la pieza salga bien.",
               ("causa de incidencia en los partes",)),

    # --- Estimación y coste ------------------------------------------------
    Definicion("desviacion_tiempos", "Desviación de tiempos",
               "(Horas reales − Horas estimadas) / Horas estimadas", "%", 10,
               "menor_mejor", "coste",
               "Si es alta y constante, las tarifas están mal y se presupuesta mal.",
               ("tiempo estimado en la ruta", "partes reales")),
    Definicion("fiabilidad_estimacion", "Estimaciones dentro del ±15%",
               "Órdenes dentro del margen / Órdenes", "%", 70, "mayor_mejor",
               "coste", "Mide si se puede confiar en el presupuestador.",
               ("tiempo estimado", "tiempo real")),
    Definicion("coste_hora_real", "Coste hora real",
               "Coste total del centro / Horas producidas", "€/h", None,
               "menor_mejor", "coste",
               "Si difiere de la tarifa aplicada, cada oferta lleva un error dentro.",
               ("costes del centro", "horas producidas")),
    Definicion("horas_por_operario", "Horas imputadas por operario y día",
               "Horas imputadas / (Operarios × días)", "h", 7, "mayor_mejor",
               "coste",
               "No mide a nadie: mide si los partes se están imputando enteros. "
               "Muy por debajo de la jornada significa que falta dato, no que "
               "se trabaje poco.",
               ("partes con operario",)),
)

CATEGORIAS = {
    "maquina": "Eficiencia de máquina",
    "preparacion": "Preparación y lotes",
    "flujo": "Flujo y plazos",
    "calidad": "Calidad",
    "coste": "Estimación y coste",
}


@dataclass
class Indicador:
    definicion: Definicion
    valor: float | None = None
    muestras: int = 0
    calculable: bool = True
    falta: list[str] = field(default_factory=list)
    detalle: dict = field(default_factory=dict)

    @property
    def estado(self) -> str:
        d = self.definicion
        if self.valor is None or d.objetivo is None:
            return "sin_dato" if self.valor is None else "informativo"
        if d.sentido == "mayor_mejor":
            if self.valor >= d.objetivo:
                return "bien"
            return "regular" if self.valor >= d.objetivo * 0.8 else "mal"
        if self.valor <= d.objetivo:
            return "bien"
        return "regular" if self.valor <= d.objetivo * 1.5 else "mal"

    def a_dict(self) -> dict:
        d = self.definicion
        return {"clave": d.clave, "nombre": d.nombre, "valor": self.valor,
                "unidad": d.unidad, "objetivo": d.objetivo, "sentido": d.sentido,
                "categoria": d.categoria, "estado": self.estado,
                "formula": d.formula, "para_que": d.para_que,
                "muestras": self.muestras, "calculable": self.calculable,
                "falta": self.falta, "detalle": self.detalle}


def _def(clave: str) -> Definicion:
    return next(d for d in CATALOGO if d.clave == clave)


def _sin_dato(clave: str, falta: list[str]) -> Indicador:
    return Indicador(_def(clave), None, 0, calculable=False, falta=falta)


# ===========================================================================
# Cálculos — funciones puras
# ===========================================================================

def oee(minutos_produciendo: float, minutos_planificados: float,
        piezas_buenas: float, piezas_totales: float,
        minutos_ideales: float) -> dict:
    """
    OEE = Disponibilidad × Rendimiento × Calidad.

    Los tres factores se devuelven por separado a propósito: un OEE del 45% no
    dice nada, pero saber que viene de una disponibilidad del 55% y no de un
    problema de calidad sí dice qué hay que arreglar.
    """
    if minutos_planificados <= 0 or piezas_totales <= 0:
        raise ValueError("Faltan datos para calcular el OEE.")

    disponibilidad = min(1.0, minutos_produciendo / minutos_planificados)
    rendimiento = (min(1.0, minutos_ideales / minutos_produciendo)
                   if minutos_produciendo > 0 else 0.0)
    calidad = piezas_buenas / piezas_totales
    return {
        "disponibilidad": round(disponibilidad * 100, 2),
        "rendimiento": round(rendimiento * 100, 2),
        "calidad": round(calidad * 100, 2),
        "oee": round(disponibilidad * rendimiento * calidad * 100, 2),
    }


def eficiencia_flujo(minutos_trabajados: float, dias_plazo: float,
                     horas_utiles_dia: float = 8.0) -> float:
    """
    Qué parte del plazo se pasa mecanizando de verdad.

    Es el indicador que más suele sorprender. Una pieza que tarda tres semanas
    en entregarse y lleva seis horas de mecanizado tiene una eficiencia de flujo
    del 5%: el 95% del plazo la pieza está esperando en una estantería.

    Y es una buena noticia: significa que para acortar plazos no hace falta
    comprar máquinas, hace falta que la pieza deje de esperar.
    """
    disponible = dias_plazo * horas_utiles_dia * 60
    if disponible <= 0:
        raise ValueError("El plazo debe ser mayor que cero.")
    return round(min(100.0, minutos_trabajados / disponible * 100), 2)


def ratio_preparacion(minutos_preparacion: float, minutos_mecanizado: float) -> float:
    total = minutos_preparacion + minutos_mecanizado
    if total <= 0:
        raise ValueError("Sin minutos no hay ratio.")
    return round(minutos_preparacion / total * 100, 2)


def desviacion(estimado: float, real: float) -> float:
    if estimado <= 0:
        raise ValueError("El tiempo estimado debe ser mayor que cero.")
    return round((real - estimado) / estimado * 100, 2)


def fiabilidad(pares: list[tuple[float, float]], margen_pct: float = 15.0) -> dict:
    """Qué porcentaje de estimaciones cae dentro del margen. Mide la confianza."""
    validos = [(e, r) for e, r in pares if e and r and e > 0 and r > 0]
    if not validos:
        return {"dentro": 0.0, "muestras": 0, "sesgo": None}
    dentro = sum(1 for e, r in validos if abs(desviacion(e, r)) <= margen_pct)
    desvios = sorted(desviacion(e, r) for e, r in validos)
    n = len(desvios)
    mediana = desvios[n // 2] if n % 2 else (desvios[n // 2 - 1] + desvios[n // 2]) / 2
    return {"dentro": round(100.0 * dentro / n, 2), "muestras": n,
            "sesgo": round(mediana, 2)}


def cumplimiento(entregas: list[tuple[date, date]]) -> dict:
    """(fecha_prevista, fecha_real) por orden."""
    if not entregas:
        return {"cumplimiento": None, "retraso_medio": None, "muestras": 0}
    a_tiempo = sum(1 for p, r in entregas if r <= p)
    retrasos = [(r - p).days for p, r in entregas if r > p]
    return {
        "cumplimiento": round(100.0 * a_tiempo / len(entregas), 2),
        "retraso_medio": round(sum(retrasos) / len(retrasos), 1) if retrasos else 0.0,
        "peor_retraso": max(retrasos) if retrasos else 0,
        "muestras": len(entregas),
    }


def clasificar_oee(valor: float) -> str:
    """
    Lectura honesta para un taller por encargo, no para una línea de serie.
    """
    if valor >= 70:
        return "Excelente para un taller de lotes pequeños."
    if valor >= 55:
        return "Bueno. La mayoría de talleres por encargo están aquí."
    if valor >= 40:
        return "Normal. Hay recorrido, sobre todo en preparación."
    if valor >= 25:
        return "Bajo. Merece la pena mirar dónde se va el tiempo."
    return "Muy bajo, o los partes no se están imputando enteros."


# ===========================================================================
# Qué se puede medir hoy
# ===========================================================================

def diagnostico_de_datos(disponible: set[str]) -> dict:
    """
    Dice qué indicadores se pueden calcular con los datos que hay y cuáles no.

    Es la primera pantalla que hay que mirar: sirve para decidir qué dato
    conviene empezar a capturar, en vez de construir un panel lleno de ceros.
    """
    listos, bloqueados = [], []
    for d in CATALOGO:
        faltan = [x for x in d.datos_necesarios if x not in disponible]
        (listos if not faltan else bloqueados).append(
            {"clave": d.clave, "nombre": d.nombre, "categoria": d.categoria,
             "falta": faltan})

    cuenta: dict[str, int] = {}
    for b in bloqueados:
        for f in b["falta"]:
            cuenta[f] = cuenta.get(f, 0) + 1
    prioridad = sorted(cuenta.items(), key=lambda x: -x[1])

    return {
        "total": len(CATALOGO),
        "calculables": len(listos),
        "bloqueados": len(bloqueados),
        "listos": listos,
        "pendientes": bloqueados,
        "dato_que_mas_desbloquea": (
            {"dato": prioridad[0][0], "desbloquea": prioridad[0][1]}
            if prioridad else None),
    }
