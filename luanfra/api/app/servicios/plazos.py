"""
Motor de plazos. También lógica pura.

Devuelve SIEMPRE dos fechas:
  - óptima: si todo sale bien
  - comprometible: la que se cumple ~8 de cada 10 veces

Al cliente se le da la comprometible. Prometer la óptima es cómo se pierde
la confianza de un cliente.
"""
from dataclasses import dataclass
from datetime import date, timedelta
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


def _dias_laborables_a_fecha(inicio: date, dias: int) -> date:
    """Salta sábados y domingos. Los festivos se añadirán con un calendario real."""
    fecha, restantes = inicio, dias
    while restantes > 0:
        fecha += timedelta(days=1)
        if fecha.weekday() < 5:
            restantes -= 1
    return fecha


def calcular(
    colas: list[ColaCentro],
    cargas: list[CargaPedido],
    desde: date | None = None,
    colchon_pct: Decimal = Decimal("50"),
) -> ResultadoPlazo:
    desde = desde or date.today()
    indice = {c.centro: c for c in colas}
    dias_por_centro: dict[str, float] = {}
    externos = 0

    for carga in cargas:
        if carga.plazo_externo_dias:
            externos += carga.plazo_externo_dias
            continue
        cola = indice.get(carga.centro)
        if cola is None:
            raise ValueError(f"Centro sin datos de capacidad: {carga.centro}")

        # Capacidad NETA, no teórica. Es la diferencia entre un plazo
        # realista y uno inventado.
        minutos_dia = float(cola.horas_dia_teoricas) * 60 * float(cola.factor_disponibilidad)
        if minutos_dia <= 0:
            raise ValueError(f"Capacidad nula en {carga.centro}")
        total = cola.minutos_comprometidos + carga.minutos
        dias_por_centro[carga.centro] = total / minutos_dia

    if not dias_por_centro and externos == 0:
        raise ValueError("Sin cargas que planificar.")

    cuello = max(dias_por_centro, key=dias_por_centro.get) if dias_por_centro else "subcontrata"
    dias_internos = max(dias_por_centro.values()) if dias_por_centro else 0
    dias_optimo = max(1, int(dias_internos + externos + 0.999))
    dias_comprometible = max(
        dias_optimo + 1, int(dias_optimo * (1 + float(colchon_pct) / 100) + 0.999)
    )

    return ResultadoPlazo(
        dias_optimo=dias_optimo,
        dias_comprometible=dias_comprometible,
        fecha_optima=_dias_laborables_a_fecha(desde, dias_optimo),
        fecha_comprometible=_dias_laborables_a_fecha(desde, dias_comprometible),
        centro_cuello_botella=cuello,
        detalle={
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
    impacto = {}
    for carga in cargas:
        cola = next((c for c in colas if c.centro == carga.centro), None)
        if not cola:
            continue
        minutos_dia = float(cola.horas_dia_teoricas) * 60 * float(cola.factor_disponibilidad)
        impacto[carga.centro] = round(carga.minutos / minutos_dia, 2) if minutos_dia else 0.0
    return impacto
