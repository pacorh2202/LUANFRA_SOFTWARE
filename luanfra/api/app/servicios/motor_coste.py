"""
Motor de coste: LÓGICA PURA, sin base de datos y sin IA.

Este módulo es el corazón del sistema y el único sitio donde se decide un precio.
Recibe datos, devuelve un resultado. No consulta nada, no escribe nada.

Por qué así: se puede probar entero sin levantar la base, y cuando alguien
pregunte dentro de dos años por qué una oferta salió a un precio, la respuesta
está en 150 líneas legibles, no repartida por toda la aplicación.

REGLA INNEGOCIABLE: la IA nunca produce un número que salga de aquí.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal


def _eur(valor) -> Decimal:
    """Redondeo a céntimo. Decimal siempre; float nunca para dinero."""
    return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Operacion:
    centro: str
    minutos_preparacion: int
    minutos_unitario: int
    tarifa_minuto: Decimal
    es_subcontrata: bool = False
    importe_externo: Decimal = Decimal("0")


@dataclass(frozen=True)
class EntradaCoste:
    cantidad: int
    peso_bruto_kg: Decimal
    precio_kg: Decimal
    merma_pct: Decimal
    operaciones: list[Operacion]
    indirectos_pct: Decimal
    margen_pct: Decimal


@dataclass
class ResultadoCoste:
    coste_material: Decimal = Decimal("0")
    coste_maquina: Decimal = Decimal("0")
    coste_preparacion: Decimal = Decimal("0")
    coste_externo: Decimal = Decimal("0")
    coste_indirecto: Decimal = Decimal("0")
    coste_total: Decimal = Decimal("0")
    precio_total: Decimal = Decimal("0")
    precio_unitario: Decimal = Decimal("0")
    minutos_totales: int = 0
    desglose: dict = field(default_factory=dict)


class ErrorDeCoste(ValueError):
    """Datos insuficientes o incoherentes: no se puede presupuestar."""


def calcular(entrada: EntradaCoste) -> ResultadoCoste:
    if entrada.cantidad <= 0:
        raise ErrorDeCoste("La cantidad debe ser mayor que cero.")
    if entrada.peso_bruto_kg <= 0 or entrada.precio_kg <= 0:
        raise ErrorDeCoste("Falta peso o precio de material: no se puede presupuestar.")
    if not entrada.operaciones:
        raise ErrorDeCoste("Sin ruta de fabricación no hay coste de máquina.")

    r = ResultadoCoste()

    # --- Material ---
    kg_totales = entrada.peso_bruto_kg * entrada.cantidad
    factor_merma = Decimal("1") + (entrada.merma_pct / Decimal("100"))
    r.coste_material = _eur(kg_totales * entrada.precio_kg * factor_merma)

    # --- Máquina y preparación ---
    # La preparación se reparte entre el lote: por eso 10 piezas no cuestan
    # diez veces lo que una.
    for op in entrada.operaciones:
        if op.es_subcontrata:
            r.coste_externo += op.importe_externo * entrada.cantidad
            continue
        minutos_op = op.minutos_unitario * entrada.cantidad
        r.minutos_totales += minutos_op + op.minutos_preparacion
        r.coste_maquina += Decimal(minutos_op) * op.tarifa_minuto
        r.coste_preparacion += Decimal(op.minutos_preparacion) * op.tarifa_minuto

    r.coste_maquina = _eur(r.coste_maquina)
    r.coste_preparacion = _eur(r.coste_preparacion)
    r.coste_externo = _eur(r.coste_externo)

    # --- Indirectos y precio ---
    subtotal = r.coste_material + r.coste_maquina + r.coste_preparacion + r.coste_externo
    r.coste_indirecto = _eur(subtotal * entrada.indirectos_pct / Decimal("100"))
    r.coste_total = _eur(subtotal + r.coste_indirecto)
    r.precio_total = _eur(r.coste_total * (Decimal("1") + entrada.margen_pct / Decimal("100")))
    r.precio_unitario = _eur(r.precio_total / entrada.cantidad)

    # REGLA DURA: nunca por debajo de coste. También está en la base de datos.
    if r.precio_total < r.coste_total:
        raise ErrorDeCoste("El precio calculado queda por debajo del coste.")

    r.desglose = {
        "material": str(r.coste_material),
        "maquina": str(r.coste_maquina),
        "preparacion": str(r.coste_preparacion),
        "externo": str(r.coste_externo),
        "indirectos": str(r.coste_indirecto),
        "coste_total": str(r.coste_total),
        "margen_pct": str(entrada.margen_pct),
        "minutos_totales": r.minutos_totales,
    }
    return r


def banda(precio: Decimal, confianza: Decimal) -> tuple[Decimal, Decimal]:
    """
    Banda de precio en función de la confianza.
    Confianza alta = banda estrecha. Confianza baja = banda ancha y visible.
    Devolver un número exacto cuando no lo sabes es la peor forma de mentir.
    """
    if not (Decimal("0") <= confianza <= Decimal("1")):
        raise ErrorDeCoste("La confianza debe estar entre 0 y 1.")
    amplitud = (Decimal("1") - confianza) * Decimal("0.30")
    return _eur(precio * (1 - amplitud)), _eur(precio * (1 + amplitud))
