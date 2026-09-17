from decimal import Decimal

from fastapi import APIRouter, HTTPException

from app.config import ajustes
from app.esquemas.comun import PeticionCalculo, RespuestaCalculo
from app.servicios import motor_coste as mc

router = APIRouter(prefix="/calculo", tags=["cálculo"])


@router.post("/coste", response_model=RespuestaCalculo)
def calcular_coste(p: PeticionCalculo):
    entrada = mc.EntradaCoste(
        cantidad=p.cantidad,
        peso_bruto_kg=p.peso_bruto_kg,
        precio_kg=p.precio_kg,
        merma_pct=p.merma_pct,
        indirectos_pct=p.indirectos_pct,
        margen_pct=p.margen_pct,
        politica_precio=p.politica_precio,
        operaciones=[
            mc.Operacion(
                centro=o.centro,
                minutos_preparacion=o.minutos_preparacion,
                minutos_unitario=o.minutos_unitario,
                tarifa_minuto=o.tarifa_minuto,
                es_subcontrata=o.es_subcontrata,
                importe_externo=o.importe_externo,
            )
            for o in p.operaciones
        ],
    )
    try:
        r = mc.calcular(entrada)
        pmin, pmax = mc.banda(r.precio_total, Decimal(p.confianza))
    except mc.ErrorDeCoste as e:
        # 422: los datos no permiten presupuestar. El sistema dice "no sé".
        raise HTTPException(status_code=422, detail=str(e)) from e

    return RespuestaCalculo(
        precio_total=r.precio_total,
        precio_unitario=r.precio_unitario,
        precio_min=max(pmin, r.coste_total),
        precio_max=pmax,
        coste_total=r.coste_total,
        minutos_totales=r.minutos_totales,
        desglose=r.desglose,
        version_modelo=ajustes.version_modelo,
    )


from dataclasses import asdict
from datetime import date
from pydantic import BaseModel, Field
from app.servicios import plazos


class CapacidadEntrada(BaseModel):
    centro: str = Field(min_length=1)
    minutos_comprometidos: int = Field(ge=0)
    horas_dia_teoricas: Decimal = Field(gt=0, le=24)
    factor_disponibilidad: Decimal = Field(gt=0, le=1)


class CargaEntrada(BaseModel):
    centro: str = Field(min_length=1)
    minutos: int = Field(ge=0)
    plazo_externo_dias: int = Field(default=0, ge=0)


class PeticionPlazo(BaseModel):
    colas: list[CapacidadEntrada]
    cargas: list[CargaEntrada] = Field(min_length=1)
    desde: date
    colchon_pct: Decimal = Field(default=Decimal("50"), ge=0)
    festivos: list[date] = Field(default_factory=list)


@router.post("/plazo")
def calcular_plazo(p: PeticionPlazo):
    """Secuencia del lote completo; capacidad diaria explícita y festivos.

    No presupone horas nocturnas ni apertura de fines de semana.
    """
    try:
        return asdict(plazos.calcular(
            [plazos.ColaCentro(**c.model_dump()) for c in p.colas],
            [plazos.CargaPedido(**c.model_dump()) for c in p.cargas],
            desde=p.desde, colchon_pct=p.colchon_pct, festivos=frozenset(p.festivos),
        ))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
