"""Endpoints de análisis. La lógica está en app/servicios/analisis.py."""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bd import obtener_sesion
from app.servicios import analisis as an

router = APIRouter(prefix="/analisis", tags=["análisis"])


@router.get("/dispersion-precios")
def dispersion(sesion: Session = Depends(obtener_sesion), minimo_veces: int = 3,
               limite: int = 30):
    """
    Piezas que hemos ofertado a precios muy distintos.
    Ordenadas por el dinero que se dejó de cobrar.
    """
    filas = sesion.execute(text("""
        SELECT p.referencia_cliente AS referencia,
               p.descripcion_normalizada AS descripcion,
               array_agg(lv.precio_unitario::numeric ORDER BY dv.fecha) AS precios
        FROM core.linea_venta lv
        JOIN core.documento_venta dv ON dv.id = lv.documento_venta_id
        JOIN core.pieza p            ON p.id = lv.pieza_id
        WHERE dv.tipo = 'presupuesto' AND lv.precio_unitario > 0
        GROUP BY p.id, p.referencia_cliente, p.descripcion_normalizada
        HAVING count(*) >= :n
    """), {"n": minimo_veces}).mappings().all()

    resultados = []
    for f in filas:
        d = an.analizar_dispersion(f["referencia"] or "sin referencia",
                                   [float(x) for x in f["precios"]])
        if d and d.gravedad != "baja":
            resultados.append({**d.__dict__, "descripcion": f["descripcion"]})

    resultados.sort(key=lambda r: -r["perdida_estimada"])
    return {
        "piezas_analizadas": len(filas),
        "con_dispersion": len(resultados),
        "perdida_total_estimada": round(sum(r["perdida_estimada"] for r in resultados), 2),
        "resultados": resultados[:limite],
    }


@router.get("/seguimiento-ofertas")
def seguimiento(sesion: Session = Depends(obtener_sesion), limite: int = 25):
    """A quién llamar hoy, por orden."""
    filas = sesion.execute(text("""
        SELECT dv.id, dv.fecha, dv.total AS importe, c.nombre AS cliente,
               coalesce(v.tasa_exito_pct, 50) / 100.0 AS tasa_exito
        FROM core.documento_venta dv
        JOIN core.cliente c ON c.id = dv.cliente_id
        LEFT JOIN ops.v_acierto_por_cliente v ON v.cliente_id = c.id
        WHERE dv.tipo = 'presupuesto'
          AND dv.fecha_aceptacion IS NULL
          AND coalesce(dv.resultado, '') NOT IN ('ganada', 'perdida')
    """)).mappings().all()

    r = an.ordenar_seguimiento([dict(f) for f in filas])
    return {
        "abiertas": len(r),
        "importe_abierto": round(sum(s.importe for s in r), 2),
        "para_llamar_hoy": [s.__dict__ for s in r if "bueno" in s.accion][:limite],
        "todas": [s.__dict__ for s in r[:limite]],
    }


@router.get("/riesgo-plazos")
def riesgo(sesion: Session = Depends(obtener_sesion), horas_utiles_dia: float = 8.0):
    """
    Cuánto trabajo va tarde, agregado.
    El ERP lo enseña máquina a máquina; esta es la cifra que nadie tiene.
    """
    filas = sesion.execute(text("""
        SELECT o.numero AS orden, coalesce(c.nombre, '—') AS cliente,
               o.fecha_prevista AS fecha_entrega,
               coalesce(sum(r.minutos_unitario * o.cantidad
                            + r.minutos_preparacion) / 60.0, 0) AS horas
        FROM core.orden_fabricacion o
        LEFT JOIN core.cliente c        ON c.id = o.cliente_id
        LEFT JOIN core.operacion_ruta r ON r.pieza_id = o.pieza_id
        WHERE o.fecha_cierre IS NULL AND o.fecha_prevista IS NOT NULL
        GROUP BY o.id, o.numero, c.nombre, o.fecha_prevista
    """)).mappings().all()

    ordenes = []
    for f in filas:
        x = an.clasificar_riesgo(f["fecha_entrega"], float(f["horas"]), horas_utiles_dia)
        x.orden, x.cliente = f["orden"] or "—", f["cliente"]
        ordenes.append(x)

    ordenes.sort(key=lambda o: (o.estado != "vencida", o.dias))
    return {
        "resumen": an.resumen_retrasos(ordenes),
        "ordenes": [o.__dict__ for o in ordenes[:50]],
    }


@router.get("/deriva-clientes")
def deriva(sesion: Session = Depends(obtener_sesion), trimestres: int = 8):
    """Clientes cuyo margen se erosiona. Se ve con meses de antelación."""
    filas = sesion.execute(text("""
        WITH por_trimestre AS (
          SELECT c.nombre AS cliente,
                 date_trunc('quarter', dv.fecha) AS periodo,
                 sum(lv.importe) AS facturado,
                 sum(lv.cantidad * coalesce(p.peso_bruto_kg, 0)) AS kg
          FROM core.documento_venta dv
          JOIN core.cliente c      ON c.id = dv.cliente_id
          JOIN core.linea_venta lv ON lv.documento_venta_id = dv.id
          LEFT JOIN core.pieza p   ON p.id = lv.pieza_id
          WHERE dv.tipo = 'factura'
          GROUP BY 1, 2
        )
        SELECT cliente, periodo, facturado, kg
        FROM por_trimestre ORDER BY cliente, periodo
    """)).mappings().all()

    series: dict[str, list[float]] = {}
    for f in filas:
        if f["kg"] and f["kg"] > 0:
            series.setdefault(f["cliente"], []).append(float(f["facturado"]) / float(f["kg"]))

    salida = []
    for cliente, serie in series.items():
        d = an.analizar_deriva(cliente, serie[-trimestres:])
        if d:
            salida.append(d.__dict__)

    salida.sort(key=lambda d: d["pendiente"])
    return {
        "clientes_analizados": len(series),
        "en_caida": sum(1 for d in salida if d["tendencia"] == "cae"),
        "resultados": salida,
        "nota": ("Indicador aproximado: euros por kilo facturado. Sirve para "
                 "detectar tendencias, no para calcular márgenes reales."),
    }
