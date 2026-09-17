"""
Motor de plazos. También lógica pura.

Devuelve SIEMPRE dos fechas:
  - óptima: si todo sale bien
  - comprometible: estimación con colchón configurable, sin garantía estadística

Al cliente se le da la comprometible. Prometer la óptima es cómo se pierde
la confianza de un cliente.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil, isfinite
from decimal import Decimal


@dataclass(frozen=True)
class ColaCentro:
    centro: str
    minutos_comprometidos: int
    horas_dia_teoricas: Decimal
    factor_disponibilidad: Decimal  # horas reales / horas teóricas


@dataclass(frozen=True)
class CargaPedido:
    centro: str
    minutos: int
    plazo_externo_dias: int = 0


@dataclass
class ResultadoPlazo:
    dias_optimo: int
    dias_comprometible: int
    fecha_optima: date
    fecha_comprometible: date
    centro_cuello_botella: str
    detalle: dict


def _dias_laborables_a_fecha(inicio: date, dias: int, festivos: frozenset[date] = frozenset()) -> date:
    """Salta sábados y domingos. Los festivos se añadirán con un calendario real."""
    fecha, restantes = inicio, dias
    while restantes > 0:
        fecha += timedelta(days=1)
        if fecha.weekday() < 5 and fecha not in festivos:
            restantes -= 1
    return fecha


def calcular(
    colas: list[ColaCentro],
    cargas: list[CargaPedido],
    desde: date | None = None,
    colchon_pct: Decimal = Decimal("50"),
    festivos: frozenset[date] = frozenset(),
) -> ResultadoPlazo:
    desde = desde or date.today()
    if not isfinite(float(colchon_pct)) or colchon_pct < 0:
        raise ValueError("Colchón no negativo requerido")
    indice = {c.centro: c for c in colas}
    if len(indice) != len(colas):
        raise ValueError("Centros duplicados")
    capacidades, disponibles = {}, {}
    for cola in colas:
        capacidad = float(cola.horas_dia_teoricas) * 60 * float(cola.factor_disponibilidad)
        if (not isfinite(capacidad) or capacidad <= 0
                or not 0 < cola.factor_disponibilidad <= 1
                or not isfinite(float(cola.minutos_comprometidos))
                or cola.minutos_comprometidos < 0):
            raise ValueError(f"Capacidad o cola inválida en {cola.centro}")
        capacidades[cola.centro] = capacidad
        disponibles[cola.centro] = cola.minutos_comprometidos / capacidad
    if not cargas:
        raise ValueError("Sin cargas que planificar")
    # La lista representa la secuencia del lote completo. No hay transferencia
    # parcial ni búsqueda de huecos: es un estimador conservador de cola.
    fin = 0.0
    externos = 0
    dias_por_centro = {}
    operaciones = []
    for carga in cargas:
        if (not isfinite(float(carga.minutos)) or carga.minutos < 0
                or not isfinite(float(carga.plazo_externo_dias))
                or carga.plazo_externo_dias < 0):
            raise ValueError("Carga negativa o no finita")
        if carga.plazo_externo_dias and carga.minutos:
            raise ValueError("Separe la operación interna de la subcontrata")
        if carga.plazo_externo_dias:
            externos += carga.plazo_externo_dias
            fin += carga.plazo_externo_dias
            operaciones.append({"centro": carga.centro, "fin_dia": fin, "externa": True})
            continue
        if carga.centro not in indice:
            raise ValueError(f"Centro sin datos de capacidad: {carga.centro}")
        inicio = max(fin, disponibles[carga.centro])
        fin = inicio + carga.minutos / capacidades[carga.centro]
        disponibles[carga.centro] = fin
        dias_por_centro[carga.centro] = dias_por_centro.get(carga.centro, 0) + carga.minutos / capacidades[carga.centro]
        operaciones.append({"centro": carga.centro, "inicio_dia": inicio, "fin_dia": fin})
    cuello = max(dias_por_centro, key=lambda c: indice[c].minutos_comprometidos / capacidades[c] + dias_por_centro[c]) if dias_por_centro else "subcontrata"
    dias_optimo = max(1, ceil(fin))
    dias_comprometible = max(dias_optimo + 1, ceil(dias_optimo * (1 + float(colchon_pct) / 100)))

    return ResultadoPlazo(
        dias_optimo=dias_optimo,
        dias_comprometible=dias_comprometible,
        fecha_optima=_dias_laborables_a_fecha(desde, dias_optimo, festivos),
        fecha_comprometible=_dias_laborables_a_fecha(desde, dias_comprometible, festivos),
        centro_cuello_botella=cuello,
        detalle={
            "metodo": "secuencia_lote_completo",
            "operaciones": operaciones,
            "advertencia": "Estimación sin garantía estadística; no es un APS por intervalos",
            "dias_por_centro": {k: round(v, 2) for k, v in dias_por_centro.items()},
            "dias_subcontrata": externos,
            "colchon_pct": str(colchon_pct),
        },
    )


def simular_entrada(
    colas: list[ColaCentro], cargas: list[CargaPedido]
) -> dict[str, float]:
    """
    "Si acepto este pedido, ¿a quién retraso?"
    Devuelve los días que se desplaza cada centro.
    """
    calcular(colas, cargas)  # valida datos antes de simular
    impacto = {}
    for carga in cargas:
        cola = next((c for c in colas if c.centro == carga.centro), None)
        if not cola:
            continue
        minutos_dia = float(cola.horas_dia_teoricas) * 60 * float(cola.factor_disponibilidad)
        impacto[carga.centro] = impacto.get(carga.centro, 0.0) + carga.minutos / minutos_dia
    return {c: round(d, 2) for c, d in impacto.items()}
