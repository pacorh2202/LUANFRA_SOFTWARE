"""Cuadro de indicadores de taller, calculado sobre los datos que haya."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bd import obtener_sesion
from app.servicios import kpis_taller as kt

router = APIRouter(prefix="/kpis/taller", tags=["KPIs"])


def _escalar(sesion, sql, params=None):
    return sesion.execute(text(sql), params or {}).mappings().first()


def _datos_disponibles(sesion: Session) -> set[str]:
    """Comprueba de verdad qué hay en las tablas, no lo que debería haber."""
    d = _escalar(sesion, """
        SELECT
          (SELECT count(*) FROM core.parte_trabajo WHERE fin IS NOT NULL)   AS partes,
          (SELECT count(*) FROM core.parte_trabajo
            WHERE cantidad_ok + cantidad_rechazo > 0)                        AS calidad,
          (SELECT count(*) FROM core.parte_trabajo WHERE trabajador_id IS NOT NULL) AS operarios,
          (SELECT count(*) FROM core.parte_trabajo WHERE causa_incidencia IS NOT NULL) AS incid,
          (SELECT count(*) FROM core.operacion_ruta WHERE minutos_unitario > 0) AS rutas,
          (SELECT count(*) FROM core.orden_fabricacion)                      AS ordenes,
          (SELECT count(*) FROM core.orden_fabricacion WHERE fecha_cierre IS NULL) AS abiertas,
          (SELECT count(*) FROM ops.carga_centro)                            AS colas,
          (SELECT count(*) FROM core.centro_trabajo WHERE activo)            AS centros,
          (SELECT count(*) FROM core.documento_venta WHERE tipo='albaran')   AS albaranes
    """)
    hay: set[str] = set()
    if d["partes"]:    hay |= {"partes con inicio y fin", "partes reales",
                               "partes de trabajo", "minutos de preparación y de mecanizado por parte"}
    if d["calidad"]:   hay |= {"cantidad buena y rechazo", "rechazo",
                               "cantidad buena y rechazo en el parte"}
    if d["operarios"]: hay |= {"partes con operario"}
    if d["incid"]:     hay |= {"causa de incidencia en los partes"}
    if d["rutas"]:     hay |= {"tiempo estimado", "tiempo estimado por pieza",
                               "tiempo estimado en la ruta"}
    if d["ordenes"]:   hay |= {"cantidad por orden", "fecha prevista",
                               "fecha de cierre", "fechas de pedido y entrega"}
    if d["abiertas"]:  hay |= {"órdenes abiertas"}
    if d["colas"]:     hay |= {"cola por máquina"}
    if d["centros"]:   hay |= {"calendario de turnos", "calendario"}
    if d["albaranes"]: hay |= {"fecha de pedido", "fecha de albarán"}
    return hay


@router.get("/diagnostico")
def diagnostico(sesion: Session = Depends(obtener_sesion)):
    """
    Qué se puede medir hoy y qué falta para lo demás.

    Es la primera pantalla que hay que mirar: dice qué dato conviene empezar a
    capturar, en vez de montar un panel lleno de ceros.
    """
    return kt.diagnostico_de_datos(_datos_disponibles(sesion))


@router.get("")
def cuadro(sesion: Session = Depends(obtener_sesion), meses: int = Query(3, ge=1, le=36)):
    disponible = _datos_disponibles(sesion)
    ind: list[kt.Indicador] = []

    def falta(clave: str):
        d = kt._def(clave)
        ind.append(kt._sin_dato(clave, [x for x in d.datos_necesarios
                                        if x not in disponible]))

    # --- Máquina ---
    m = _escalar(sesion, """
        SELECT coalesce(sum(p.minutos), 0) AS producidos,
               coalesce(sum(p.cantidad_ok), 0) AS buenas,
               coalesce(sum(p.cantidad_ok + p.cantidad_rechazo), 0) AS totales,
               coalesce(sum(r.minutos_unitario * p.cantidad_ok), 0) AS ideales,
               count(*) AS partes,
               count(DISTINCT p.centro_trabajo_id) AS centros,
               count(DISTINCT p.inicio::date) AS dias
        FROM core.parte_trabajo p
        LEFT JOIN core.operacion_ruta r ON r.id = p.operacion_ruta_id
        WHERE p.inicio >= current_date - (:m || ' months')::interval
    """, {"m": meses})

    if m["partes"] and m["totales"]:
        planificados = float(m["centros"] or 1) * float(m["dias"] or 1) * 8 * 60
        try:
            r = kt.oee(float(m["producidos"]), planificados,
                       float(m["buenas"]), float(m["totales"]),
                       float(m["ideales"] or m["producidos"]))
            for clave, valor in (("oee", r["oee"]), ("disponibilidad", r["disponibilidad"]),
                                 ("rendimiento", r["rendimiento"]),
                                 ("calidad_oee", r["calidad"])):
                i = kt.Indicador(kt._def(clave), valor, int(m["partes"]))
                if clave == "oee":
                    i.detalle = {"lectura": kt.clasificar_oee(valor), **r}
                ind.append(i)
        except ValueError:
            for c in ("oee", "disponibilidad", "rendimiento", "calidad_oee"):
                falta(c)
    else:
        for c in ("oee", "disponibilidad", "rendimiento", "calidad_oee"):
            falta(c)

    # --- Preparación y lotes ---
    p = _escalar(sesion, """
        SELECT coalesce(sum(r.minutos_preparacion), 0) AS prep,
               coalesce(sum(r.minutos_unitario * o.cantidad), 0) AS mecanizado,
               round(avg(o.cantidad), 1) AS lote, count(*) AS n
        FROM core.orden_fabricacion o
        JOIN core.operacion_ruta r ON r.pieza_id = o.pieza_id
        WHERE o.fecha_apertura >= current_date - (:m || ' months')::interval
    """, {"m": meses})
    if p["n"] and (float(p["prep"]) + float(p["mecanizado"])) > 0:
        ind.append(kt.Indicador(kt._def("ratio_preparacion"),
                   kt.ratio_preparacion(float(p["prep"]), float(p["mecanizado"])),
                   int(p["n"])))
    else:
        falta("ratio_preparacion")

    lote = _escalar(sesion, """
        SELECT round(avg(cantidad), 1) AS lote, count(*) AS n
        FROM core.linea_venta WHERE cantidad > 0""")
    if lote["n"]:
        ind.append(kt.Indicador(kt._def("lote_medio"), float(lote["lote"]), int(lote["n"])))
    else:
        falta("lote_medio")

    # --- Flujo ---
    c = sesion.execute(text("""
        SELECT fecha_prevista, fecha_cierre FROM core.orden_fabricacion
        WHERE fecha_cierre IS NOT NULL AND fecha_prevista IS NOT NULL
          AND fecha_cierre >= current_date - (:m || ' months')::interval
    """), {"m": meses}).all()
    if c:
        r = kt.cumplimiento([(x[0], x[1]) for x in c])
        ind.append(kt.Indicador(kt._def("cumplimiento_plazo"), r["cumplimiento"], r["muestras"]))
        i = kt.Indicador(kt._def("retraso_medio"), r["retraso_medio"], r["muestras"])
        i.detalle = {"peor_retraso_dias": r["peor_retraso"]}
        ind.append(i)
    else:
        falta("cumplimiento_plazo"); falta("retraso_medio")

    for clave in ("plazo_real", "eficiencia_flujo"):
        falta(clave)

    w = _escalar(sesion, "SELECT count(*) AS n FROM core.orden_fabricacion WHERE fecha_cierre IS NULL")
    ind.append(kt.Indicador(kt._def("wip"), float(w["n"]), int(w["n"]))
               if w["n"] else kt._sin_dato("wip", ["órdenes abiertas"]))

    cb = _escalar(sesion, """
        SELECT max(cc.minutos_comprometidos /
                   nullif(ct.horas_turno * ct.turnos_dia * 60 * ct.factor_disponibilidad, 0)) AS dias
        FROM ops.carga_centro cc
        JOIN core.centro_trabajo ct ON ct.id = cc.centro_trabajo_id
        WHERE ct.tipo = 'interno'""")
    if cb and cb["dias"]:
        ind.append(kt.Indicador(kt._def("cola_cuello_botella"), round(float(cb["dias"]), 1)))
    else:
        falta("cola_cuello_botella")
    falta("utilizacion")

    # --- Calidad ---
    if m["totales"]:
        rech = float(m["totales"]) - float(m["buenas"])
        ind.append(kt.Indicador(kt._def("rechazo"),
                                round(100.0 * rech / float(m["totales"]), 2),
                                int(m["partes"])))
    else:
        falta("rechazo")
    falta("coste_no_calidad")

    inc = _escalar(sesion, """
        SELECT count(*) FILTER (WHERE causa_incidencia IS NOT NULL) AS con,
               count(*) AS total FROM core.parte_trabajo
        WHERE inicio >= current_date - (:m || ' months')::interval""", {"m": meses})
    if inc and inc["total"]:
        ind.append(kt.Indicador(kt._def("incidencias"),
                                round(100.0 * inc["con"] / inc["total"], 2), inc["total"]))
    else:
        falta("incidencias")

    # --- Coste y estimación ---
    pares = sesion.execute(text("""
        SELECT r.minutos_unitario::numeric AS est,
               (p.minutos::numeric / nullif(o.cantidad, 0)) AS real_medido
        FROM core.parte_trabajo p
        JOIN core.orden_fabricacion o ON o.id = p.orden_id
        JOIN core.operacion_ruta r    ON r.id = p.operacion_ruta_id
        WHERE p.minutos > 0 AND o.cantidad > 0 AND r.minutos_unitario > 0
    """)).all()
    if pares:
        f = kt.fiabilidad([(float(a), float(b)) for a, b in pares if a and b])
        i = kt.Indicador(kt._def("fiabilidad_estimacion"), f["dentro"], f["muestras"])
        i.detalle = {"sesgo_pct": f["sesgo"]}
        ind.append(i)
        if f["sesgo"] is not None:
            ind.append(kt.Indicador(kt._def("desviacion_tiempos"),
                                    abs(f["sesgo"]), f["muestras"]))
    else:
        falta("fiabilidad_estimacion"); falta("desviacion_tiempos")
    falta("coste_hora_real"); falta("horas_por_operario")

    # --- Agrupado por categoría ---
    bloques = []
    for cat, nombre in kt.CATEGORIAS.items():
        de_cat = [i for i in ind if i.definicion.categoria == cat]
        bloques.append({
            "categoria": cat, "nombre": nombre,
            "calculables": sum(1 for i in de_cat if i.calculable),
            "indicadores": [i.a_dict() for i in de_cat],
        })

    return {
        "periodo_meses": meses,
        "resumen": {
            "total": len(ind),
            "con_dato": sum(1 for i in ind if i.valor is not None),
            "sin_dato": sum(1 for i in ind if i.valor is None),
            "fuera_de_objetivo": sum(1 for i in ind if i.estado == "mal"),
        },
        "bloques": bloques,
        "nota": ("Los indicadores sin dato no son un cero: es que falta el dato "
                 "de partida. Mira /kpis/taller/diagnostico para saber cuál "
                 "conviene empezar a capturar."),
    }
