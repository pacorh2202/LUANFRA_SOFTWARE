"""Datos para el panel principal. Consultas de solo lectura."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bd import obtener_sesion

router = APIRouter(prefix="/panel", tags=["panel"])


@router.get("/kpis")
def kpis(sesion: Session = Depends(obtener_sesion)):
    q = text("""
        SELECT
          (SELECT count(*) FROM ops.peticion WHERE estado IN ('recibida','clasificada'))     AS peticiones_pendientes,
          (SELECT count(*) FROM ops.oferta   WHERE estado = 'borrador')                      AS ofertas_por_revisar,
          (SELECT coalesce(sum(precio_propuesto),0) FROM ops.oferta WHERE estado='borrador')  AS importe_por_revisar,
          (SELECT count(*) FROM ops.oferta   WHERE via = 'C_nueva' AND estado='borrador')     AS requieren_persona
    """)
    return dict(sesion.execute(q).mappings().one())


@router.get("/ofertas")
def ofertas_pendientes(sesion: Session = Depends(obtener_sesion), limite: int = 25):
    q = text("""
        SELECT o.id, c.nombre AS cliente, p.referencia_cliente AS pieza,
               o.cantidad, o.precio_propuesto, o.precio_min, o.precio_max,
               o.confianza, o.via, o.fecha_entrega_optima,
               o.fecha_entrega_comprometible, o.estado,
               o.creado_en
        FROM ops.oferta o
        LEFT JOIN ops.peticion pe ON pe.id = o.peticion_id
        LEFT JOIN core.cliente  c  ON c.id  = pe.cliente_id
        LEFT JOIN core.pieza    p  ON p.id  = o.pieza_id
        WHERE o.estado = 'borrador'
        ORDER BY o.creado_en DESC
        LIMIT :limite
    """)
    return [dict(f) for f in sesion.execute(q, {"limite": limite}).mappings().all()]
