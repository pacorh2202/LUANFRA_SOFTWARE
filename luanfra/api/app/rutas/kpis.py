"""
Cuadro de indicadores.

Cuatro bloques, y ninguno inventado: cada indicador sale de una consulta que se
puede abrir y comprobar. Un panel de KPI en el que no te fías de un número es
un panel que nadie mira a los dos meses.

Los indicadores llevan `objetivo` y `sentido` para poder pintarlos con color
sin que la interfaz tenga que saber si más es mejor o peor.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bd import obtener_sesion

router = APIRouter(prefix="/kpis", tags=["KPIs"])


def _kpi(clave, etiqueta, valor, unidad="", objetivo=None, sentido="mayor_mejor",
         ayuda="", periodo="12 meses"):
    """
    `sentido` dice si un valor alto es bueno o malo. Sin eso, la interfaz
    pintaría de verde un plazo de 90 días.
    """
    estado = "sin_dato"
    if valor is not None and objetivo is not None:
        if sentido == "mayor_mejor":
            estado = "bien" if valor >= objetivo else "regular" if valor >= objetivo * 0.8 else "mal"
        else:
            estado = "bien" if valor <= objetivo else "regular" if valor <= objetivo * 1.5 else "mal"
    return {"clave": clave, "etiqueta": etiqueta, "valor": valor, "unidad": unidad,
            "objetivo": objetivo, "sentido": sentido, "estado": estado,
            "ayuda": ayuda, "periodo": periodo}


def _uno(sesion, sql, params=None):
    return sesion.execute(text(sql), params or {}).mappings().first()


@router.get("/comercial")
def comercial(sesion: Session = Depends(obtener_sesion), meses: int = 12):
    d = _uno(sesion, """
        SELECT count(*) AS ofertados,
               count(*) FILTER (WHERE dv.fecha_aceptacion IS NOT NULL) AS ganados,
               coalesce(sum(dv.total), 0) AS importe_ofertado,
               coalesce(sum(dv.total) FILTER (WHERE dv.fecha_aceptacion IS NOT NULL), 0)
                 AS importe_ganado,
               round(avg(dv.fecha_aceptacion - dv.fecha) FILTER
                     (WHERE dv.fecha_aceptacion IS NOT NULL), 1) AS dias_hasta_aceptar
        FROM core.documento_venta dv
        WHERE dv.tipo = 'presupuesto'
          AND dv.fecha >= current_date - (:m || ' months')::interval
    """, {"m": meses})

    ofertados = d["ofertados"] or 0
    tasa = round(100.0 * (d["ganados"] or 0) / ofertados, 1) if ofertados else None
    tasa_importe = (round(100.0 * float(d["importe_ganado"]) / float(d["importe_ofertado"]), 1)
                    if d["importe_ofertado"] else None)

    return {"bloque": "Comercial", "indicadores": [
        _kpi("ofertas_emitidas", "Ofertas emitidas", ofertados, "ofertas"),
        _kpi("tasa_exito", "Tasa de éxito", tasa, "%", 40, "mayor_mejor",
             "Ofertas aceptadas sobre emitidas. Muy alta puede significar que estáis baratos."),
        _kpi("tasa_exito_importe", "Éxito ponderado por importe", tasa_importe, "%", 40,
             "mayor_mejor", "Si es mucho menor que la tasa simple, se pierden las ofertas grandes."),
        _kpi("importe_ofertado", "Importe ofertado", round(float(d["importe_ofertado"]), 2), "€"),
        _kpi("importe_ganado", "Importe ganado", round(float(d["importe_ganado"]), 2), "€"),
        _kpi("dias_hasta_aceptar", "Días hasta la aceptación", d["dias_hasta_aceptar"], "días",
             21, "menor_mejor", "Cuánto tarda el cliente en decidir."),
    ]}


@router.get("/produccion")
def produccion(sesion: Session = Depends(obtener_sesion), meses: int = 3):
    d = _uno(sesion, """
        SELECT count(*) AS ordenes_cerradas,
               count(*) FILTER (WHERE o.fecha_cierre <= o.fecha_prevista) AS a_tiempo,
               round(avg(o.fecha_cierre - o.fecha_apertura), 1) AS dias_ciclo
        FROM core.orden_fabricacion o
        WHERE o.fecha_cierre IS NOT NULL AND o.fecha_prevista IS NOT NULL
          AND o.fecha_cierre >= current_date - (:m || ' months')::interval
    """, {"m": meses})

    calidad = _uno(sesion, """
        SELECT coalesce(sum(p.cantidad_rechazo), 0) AS rechazo,
               coalesce(sum(p.cantidad_ok), 0) AS bueno
        FROM core.parte_trabajo p
        WHERE p.inicio >= current_date - (:m || ' months')::interval
    """, {"m": meses})

    disp = _uno(sesion, """
        SELECT round(avg(ct.factor_disponibilidad) * 100, 1) AS disponibilidad
        FROM core.centro_trabajo ct WHERE ct.tipo = 'interno' AND ct.activo
    """)

    cerradas = d["ordenes_cerradas"] or 0
    cumplimiento = round(100.0 * (d["a_tiempo"] or 0) / cerradas, 1) if cerradas else None
    total_piezas = float(calidad["bueno"]) + float(calidad["rechazo"])
    rechazo_pct = round(100.0 * float(calidad["rechazo"]) / total_piezas, 2) if total_piezas else None

    return {"bloque": "Producción", "periodo_meses": meses, "indicadores": [
        _kpi("cumplimiento_plazo", "Plazos cumplidos", cumplimiento, "%", 90, "mayor_mejor",
             "Órdenes cerradas en o antes de la fecha prevista.", f"{meses} meses"),
        _kpi("dias_ciclo", "Días de ciclo", d["dias_ciclo"], "días", 15, "menor_mejor",
             "De abrir la orden a cerrarla.", f"{meses} meses"),
        _kpi("rechazo", "Piezas rechazadas", rechazo_pct, "%", 1.5, "menor_mejor",
             "Sobre el total fabricado.", f"{meses} meses"),
        _kpi("disponibilidad", "Disponibilidad media", disp["disponibilidad"], "%", 75,
             "mayor_mejor", "Horas que las máquinas producen sobre las teóricas.", "actual"),
    ]}


@router.get("/financiero")
def financiero(sesion: Session = Depends(obtener_sesion)):
    fact = _uno(sesion, """
        WITH entregas AS (
          SELECT dv.cliente_id, dv.fecha AS fecha_albaran,
                 (SELECT min(f.fecha) FROM core.documento_venta f
                   WHERE f.tipo = 'factura' AND f.cliente_id = dv.cliente_id
                     AND f.fecha >= dv.fecha) AS fecha_factura,
                 dv.total
          FROM core.documento_venta dv
          WHERE dv.tipo = 'albaran'
            AND dv.fecha >= current_date - interval '12 months'
        )
        SELECT round(avg(fecha_factura - fecha_albaran), 1) AS dias_hasta_factura,
               coalesce(sum(total) FILTER (WHERE fecha_factura IS NULL), 0) AS sin_facturar
        FROM entregas
    """)

    abierto = _uno(sesion, """
        SELECT coalesce(sum(total), 0) AS importe, count(*) AS n
        FROM core.documento_venta
        WHERE tipo = 'presupuesto' AND fecha_aceptacion IS NULL
          AND fecha >= current_date - interval '90 days'
    """)

    return {"bloque": "Financiero", "indicadores": [
        _kpi("dias_entrega_factura", "Días de entrega a factura", fact["dias_hasta_factura"],
             "días", 5, "menor_mejor",
             "El indicador que ordena todo el proyecto.", "12 meses"),
        _kpi("entregado_sin_facturar", "Entregado sin facturar",
             round(float(fact["sin_facturar"]), 2), "€", 0, "menor_mejor",
             "Dinero ya trabajado que todavía no se ha reclamado.", "12 meses"),
        _kpi("ofertas_abiertas", "Ofertas vivas sin respuesta", abierto["n"], "ofertas",
             periodo="90 días"),
        _kpi("importe_abierto", "Importe en ofertas vivas",
             round(float(abierto["importe"]), 2), "€", periodo="90 días"),
    ]}


@router.get("/sistema")
def sistema(sesion: Session = Depends(obtener_sesion)):
    """
    Indicadores del propio sistema. Sin esto no se sabe si se puede confiar en él,
    y confiar sin medir es exactamente el error que queremos evitar.
    """
    ofertas = _uno(sesion, """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE via = 'A_repetida') AS via_a,
               count(*) FILTER (WHERE via = 'C_nueva') AS via_c,
               round(avg(confianza) * 100, 1) AS confianza_media
        FROM ops.oferta
    """)
    corr = _uno(sesion, """
        SELECT count(*) AS n,
               count(DISTINCT oferta_id) AS ofertas_corregidas
        FROM ops.correccion WHERE campo = 'precio_propuesto'
    """)
    norm = _uno(sesion, """
        SELECT count(*) AS n, round(avg(confianza) * 100, 1) AS confianza,
               count(*) FILTER (WHERE confianza < 0.55) AS dudosas
        FROM core.normalizacion
    """)
    auditoria = _uno(sesion, "SELECT count(*) AS n FROM audit.verificar_cadena()")

    total = ofertas["total"] or 0
    autonomia = round(100.0 * (1 - (ofertas["via_c"] or 0) / total), 1) if total else None
    tasa_correccion = round(100.0 * (corr["ofertas_corregidas"] or 0) / total, 1) if total else None

    return {"bloque": "Sistema", "indicadores": [
        _kpi("autonomia", "Ofertas que el sistema resuelve", autonomia, "%", 70, "mayor_mejor",
             "Las que no acaban en la vía C. Empezará bajo y subirá al normalizar el histórico."),
        _kpi("confianza_media", "Confianza media", ofertas["confianza_media"], "%", 70,
             "mayor_mejor"),
        _kpi("tasa_correccion", "Ofertas que corriges a mano", tasa_correccion, "%", 30,
             "menor_mejor", "Si baja con el tiempo, el sistema está aprendiendo tu criterio."),
        _kpi("correcciones", "Correcciones registradas", corr["n"], "correcciones", 200,
             "mayor_mejor", "Con doscientas empieza a reproducir tu criterio."),
        _kpi("normalizacion", "Confianza de la normalización", norm["confianza"], "%", 75,
             "mayor_mejor", f"{norm['dudosas'] or 0} descripciones necesitan revisión."),
        _kpi("auditoria", "Cadena de auditoría intacta",
             0 if (auditoria["n"] or 0) == 0 else auditoria["n"], "fallos", 0, "menor_mejor",
             "Cero significa que nadie ha alterado un registro del pasado.", "siempre"),
    ]}


@router.get("")
def todos(sesion: Session = Depends(obtener_sesion)):
    bloques = [comercial(sesion), produccion(sesion), financiero(sesion), sistema(sesion)]
    todos_ind = [i for b in bloques for i in b["indicadores"]]
    return {
        "bloques": bloques,
        "resumen": {
            "indicadores": len(todos_ind),
            "en_objetivo": sum(1 for i in todos_ind if i["estado"] == "bien"),
            "fuera_de_objetivo": sum(1 for i in todos_ind if i["estado"] == "mal"),
            "sin_dato": sum(1 for i in todos_ind if i["estado"] == "sin_dato"),
        },
    }
