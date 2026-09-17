"""Bandeja de avisos: qué hay que hacer hoy y a quién le toca."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bd import obtener_sesion
from app.servicios import avisos as av

router = APIRouter(prefix="/avisos", tags=["avisos"])

ROLES = (av.TALLER, av.ADMINISTRACION, av.COMERCIAL, av.DIRECCION, av.OFICINA_TECNICA)


def _fuentes(sesion: Session) -> dict:
    ordenes = [dict(f) for f in sesion.execute(text("""
        SELECT o.numero AS orden, coalesce(c.nombre,'—') AS cliente,
               o.fecha_prevista AS fecha_entrega,
               coalesce(sum(r.minutos_unitario * o.cantidad
                            + r.minutos_preparacion)/60.0, 0) AS horas_pendientes,
               8 AS horas_dia, 0 AS importe, false AS cliente_avisado
        FROM core.orden_fabricacion o
        LEFT JOIN core.cliente c        ON c.id = o.cliente_id
        LEFT JOIN core.operacion_ruta r ON r.pieza_id = o.pieza_id
        WHERE o.fecha_cierre IS NULL AND o.fecha_prevista IS NOT NULL
        GROUP BY o.id, o.numero, c.nombre, o.fecha_prevista
    """)).mappings()]

    centros = [dict(f) for f in sesion.execute(text("""
        SELECT ct.codigo,
               coalesce((SELECT cc.minutos_comprometidos FROM ops.carga_centro cc
                          WHERE cc.centro_trabajo_id = ct.id
                          ORDER BY cc.calculado_en DESC LIMIT 1), 0) AS minutos_cola,
               ct.factor_disponibilidad AS disponibilidad,
               ct.horas_turno * ct.turnos_dia AS horas_dia,
               (ct.tipo = 'subcontrata') AS externo
        FROM core.centro_trabajo ct WHERE ct.activo
    """)).mappings()]

    entregas = [dict(f) for f in sesion.execute(text("""
        SELECT dv.numero AS albaran, c.nombre AS cliente, dv.total AS importe,
               dv.fecha AS fecha_albaran,
               (SELECT r.valor FROM ops.regla_cliente r
                 WHERE r.cliente_id = c.id AND r.clave = 'dia_corte') AS dia_corte
        FROM core.documento_venta dv
        JOIN core.cliente c ON c.id = dv.cliente_id
        WHERE dv.tipo = 'albaran'
          AND NOT EXISTS (SELECT 1 FROM core.documento_venta f
                           WHERE f.tipo='factura' AND f.cliente_id = dv.cliente_id
                             AND f.fecha >= dv.fecha)
    """)).mappings()]

    ofertas = [dict(f) for f in sesion.execute(text("""
        SELECT c.nombre AS cliente, dv.total AS importe, dv.fecha,
               (dv.fecha_aceptacion IS NOT NULL) AS ganada, false AS seguimiento
        FROM core.documento_venta dv
        JOIN core.cliente c ON c.id = dv.cliente_id
        WHERE dv.tipo = 'presupuesto'
          AND dv.fecha >= current_date - interval '24 months'
    """)).mappings()]

    peticiones = [dict(f) for f in sesion.execute(text("""
        SELECT p.id AS referencia, coalesce(ap.bloqueantes,0) AS bloqueantes,
               p.recibido_en::date AS recibida, false AS consulta_enviada
        FROM ops.peticion p
        LEFT JOIN ops.peticion_documento pd ON pd.peticion_id = p.id
        LEFT JOIN ops.analisis_plano ap     ON ap.documento_id = pd.documento_id
        WHERE p.estado NOT IN ('ofertada','descartada')
    """)).mappings()]

    return {"ordenes": ordenes, "centros": centros,
            "entregas_sin_factura": entregas, "ofertas": ofertas,
            "peticiones": peticiones}


@router.get("")
def todos(sesion: Session = Depends(obtener_sesion)):
    lista = av.recopilar(**_fuentes(sesion))
    return {"resumen": av.resumen_diario(lista),
            "avisos": [a.__dict__ for a in lista]}


@router.get("/resumen")
def resumen(sesion: Session = Depends(obtener_sesion)):
    """El parte de la mañana. Una línea: por dónde empezar."""
    return av.resumen_diario(av.recopilar(**_fuentes(sesion)))


@router.get("/{rol}")
def por_rol(rol: str, sesion: Session = Depends(obtener_sesion)):
    """
    La bandeja de una persona. Solo lo que puede resolver ella.

    Una bandeja con treinta avisos de los que veintisiete no te tocan es
    una bandeja que se deja de mirar a la semana.
    """
    if rol not in ROLES:
        raise HTTPException(404, f"Rol desconocido. Opciones: {', '.join(ROLES)}")
    lista = av.bandeja(av.recopilar(**_fuentes(sesion)), rol)
    return {"rol": rol, "pendientes": len(lista),
            "criticos": sum(1 for a in lista if a.urgencia == "critica"),
            "avisos": [a.__dict__ for a in lista]}
