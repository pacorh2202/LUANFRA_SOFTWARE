"""
Ofertas: listado y ficha de decisión.

Nada de lo que hay aquí envía un correo. Aprobar cambia un estado interno
y deja rastro en auditoría; el envío al cliente lo hace siempre una persona.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auditoria import registrar
from app.bd import obtener_sesion

router = APIRouter(prefix="/ofertas", tags=["ofertas"])

_LISTADO = """
    SELECT o.id, o.estado, o.via, o.cantidad,
           o.precio_propuesto, o.precio_min, o.precio_max, o.coste_calculado,
           o.confianza, o.fecha_entrega_optima, o.fecha_entrega_comprometible,
           o.creado_en,
           c.nombre                AS cliente,
           p.referencia_cliente    AS pieza_ref,
           p.descripcion_normalizada AS pieza_desc,
           coalesce(a.bloqueantes, 0) AS bloqueantes
    FROM ops.oferta o
    LEFT JOIN ops.peticion pe ON pe.id = o.peticion_id
    LEFT JOIN core.cliente  c  ON c.id  = pe.cliente_id
    LEFT JOIN core.pieza    p  ON p.id  = o.pieza_id
    LEFT JOIN LATERAL (
        SELECT ap.bloqueantes
        FROM ops.peticion_documento pd
        JOIN ops.analisis_plano ap ON ap.documento_id = pd.documento_id
        WHERE pd.peticion_id = pe.id
        ORDER BY ap.creado_en DESC LIMIT 1
    ) a ON true
"""


@router.get("")
def listar(
    sesion: Session = Depends(obtener_sesion),
    estado: str | None = None,
    via: str | None = None,
    q: str | None = None,
    limite: int = 100,
):
    filtros, params = [], {"limite": limite}
    if estado:
        filtros.append("o.estado = :estado")
        params["estado"] = estado
    if via:
        filtros.append("o.via = :via")
        params["via"] = via
    if q:
        filtros.append("(c.nombre ILIKE :q OR p.referencia_cliente ILIKE :q)")
        params["q"] = f"%{q}%"

    sql = _LISTADO
    if filtros:
        sql += " WHERE " + " AND ".join(filtros)
    sql += " ORDER BY o.creado_en DESC LIMIT :limite"
    return [dict(f) for f in sesion.execute(text(sql), params).mappings().all()]


@router.get("/{oferta_id}")
def ficha(oferta_id: int, sesion: Session = Depends(obtener_sesion)):
    """Todo lo necesario para decidir en una sola llamada."""
    cab = sesion.execute(
        text(_LISTADO + " WHERE o.id = :id"), {"id": oferta_id}
    ).mappings().first()
    if not cab:
        raise HTTPException(404, "Oferta no encontrada")

    extra = sesion.execute(text("""
        SELECT o.desglose, o.hipotesis, o.version_modelo, o.peticion_id,
               pe.asunto, pe.remitente, pe.recibido_en, pe.mensaje_id,
               p.material_id, m.codigo AS material, p.peso_bruto_kg,
               p.tolerancia_general
        FROM ops.oferta o
        LEFT JOIN ops.peticion pe ON pe.id = o.peticion_id
        LEFT JOIN core.pieza    p  ON p.id  = o.pieza_id
        LEFT JOIN core.material m  ON m.id  = p.material_id
        WHERE o.id = :id"""), {"id": oferta_id}).mappings().one()

    comparables = sesion.execute(text("""
        SELECT cp.similitud, cp.precio_historico, cp.minutos_reales,
               cp.fecha_referencia, p.referencia_cliente AS pieza,
               p.descripcion_normalizada AS descripcion,
               (SELECT dv.resultado
                  FROM core.linea_venta lv
                  JOIN core.documento_venta dv ON dv.id = lv.documento_venta_id
                 WHERE lv.pieza_id = cp.pieza_id AND dv.tipo = 'presupuesto'
                 ORDER BY dv.fecha DESC LIMIT 1) AS resultado
        FROM ops.comparable cp
        JOIN core.pieza p ON p.id = cp.pieza_id
        WHERE cp.oferta_id = :id
        ORDER BY cp.similitud DESC"""), {"id": oferta_id}).mappings().all()

    plano = sesion.execute(text("""
        SELECT d.nombre_original, d.es_vectorial, d.revision,
               ap.hallazgos, ap.metodo, ap.confianza, ap.bloqueantes
        FROM ops.peticion_documento pd
        JOIN core.documento d       ON d.id = pd.documento_id
        LEFT JOIN ops.analisis_plano ap ON ap.documento_id = d.id
        WHERE pd.peticion_id = :pet AND d.tipo = 'plano'
        ORDER BY ap.creado_en DESC NULLS LAST LIMIT 1"""),
        {"pet": extra["peticion_id"]}).mappings().first()

    correcciones = sesion.execute(text("""
        SELECT campo, valor_propuesto, valor_corregido, motivo, usuario, creado_en
        FROM ops.correccion WHERE oferta_id = :id ORDER BY creado_en DESC"""),
        {"id": oferta_id}).mappings().all()

    return {
        **dict(cab),
        "desglose": extra["desglose"],
        "hipotesis": extra["hipotesis"] or [],
        "version_modelo": extra["version_modelo"],
        "peticion": {
            "asunto": extra["asunto"], "remitente": extra["remitente"],
            "recibido_en": extra["recibido_en"], "mensaje_id": extra["mensaje_id"],
        },
        "pieza": {
            "material": extra["material"], "peso_bruto_kg": extra["peso_bruto_kg"],
            "tolerancia_general": extra["tolerancia_general"],
        },
        "comparables": [dict(c) for c in comparables],
        "plano": dict(plano) if plano else None,
        "correcciones": [dict(c) for c in correcciones],
    }


class Correccion(BaseModel):
    precio: float | None = None
    fecha_comprometible: date | None = None
    motivo: str = Field(default="", max_length=500)
    usuario: str = "paco"


@router.post("/{oferta_id}/aprobar")
def aprobar(oferta_id: int, usuario: str = "paco", sesion: Session = Depends(obtener_sesion)):
    fila = sesion.execute(
        text("SELECT estado, precio_propuesto, via FROM ops.oferta WHERE id=:id"),
        {"id": oferta_id}).mappings().first()
    if not fila:
        raise HTTPException(404, "Oferta no encontrada")
    if fila["precio_propuesto"] is None:
        # Vía C: el sistema dijo que no sabía. No se aprueba sin poner precio.
        raise HTTPException(422, "Esta oferta no tiene precio propuesto. Corrígela antes.")
    if fila["estado"] != "borrador":
        raise HTTPException(409, f"La oferta ya está en estado '{fila['estado']}'.")

    sesion.execute(text("UPDATE ops.oferta SET estado='revisada' WHERE id=:id"),
                   {"id": oferta_id})
    registrar(sesion, "aprobar", "oferta", oferta_id,
              antes={"estado": "borrador"}, despues={"estado": "revisada"}, actor=usuario)
    sesion.commit()
    return {"id": oferta_id, "estado": "revisada"}


@router.post("/{oferta_id}/corregir")
def corregir(oferta_id: int, c: Correccion, sesion: Session = Depends(obtener_sesion)):
    """
    Cada corrección se guarda con su valor antes y después.
    Es la señal más valiosa del sistema: con doscientas registradas,
    el modelo empieza a reproducir el criterio real de quien presupuesta.
    """
    antes = sesion.execute(text("""
        SELECT precio_propuesto, fecha_entrega_comprometible, coste_calculado
        FROM ops.oferta WHERE id=:id"""), {"id": oferta_id}).mappings().first()
    if not antes:
        raise HTTPException(404, "Oferta no encontrada")

    if c.precio is not None:
        if antes["coste_calculado"] and c.precio < float(antes["coste_calculado"]):
            raise HTTPException(422, "El precio no puede quedar por debajo del coste calculado.")
        sesion.execute(text("UPDATE ops.oferta SET precio_propuesto=:p WHERE id=:id"),
                       {"p": c.precio, "id": oferta_id})
        sesion.execute(text("""
            INSERT INTO ops.correccion
              (oferta_id, campo, valor_propuesto, valor_corregido, motivo, usuario)
            VALUES (:o,'precio_propuesto',:vp,:vc,:m,:u)"""), {
            "o": oferta_id, "vp": str(antes["precio_propuesto"]),
            "vc": str(c.precio), "m": c.motivo, "u": c.usuario})

    if c.fecha_comprometible is not None:
        sesion.execute(
            text("UPDATE ops.oferta SET fecha_entrega_comprometible=:f WHERE id=:id"),
            {"f": c.fecha_comprometible, "id": oferta_id})
        sesion.execute(text("""
            INSERT INTO ops.correccion
              (oferta_id, campo, valor_propuesto, valor_corregido, motivo, usuario)
            VALUES (:o,'fecha_entrega_comprometible',:vp,:vc,:m,:u)"""), {
            "o": oferta_id, "vp": str(antes["fecha_entrega_comprometible"]),
            "vc": str(c.fecha_comprometible), "m": c.motivo, "u": c.usuario})

    registrar(sesion, "corregir", "oferta", oferta_id,
              antes=dict(antes), despues=c.model_dump(), actor=c.usuario)
    sesion.commit()
    return {"id": oferta_id, "corregida": True}


@router.post("/{oferta_id}/descartar")
def descartar(oferta_id: int, motivo: str = "", usuario: str = "paco",
              sesion: Session = Depends(obtener_sesion)):
    n = sesion.execute(
        text("UPDATE ops.oferta SET estado='descartada' WHERE id=:id AND estado='borrador'"),
        {"id": oferta_id}).rowcount
    if not n:
        raise HTTPException(409, "No se puede descartar: no existe o ya no es un borrador.")
    registrar(sesion, "descartar", "oferta", oferta_id,
              despues={"motivo": motivo}, actor=usuario)
    sesion.commit()
    return {"id": oferta_id, "estado": "descartada"}
