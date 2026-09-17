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
        precio_min=pmin,
        precio_max=pmax,
        coste_total=r.coste_total,
        minutos_totales=r.minutos_totales,
        desglose=r.desglose,
        version_modelo=ajustes.version_modelo,
    )
