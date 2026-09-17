"""
Normalización de descripciones y búsqueda de comparables.

Es el circuito que convierte una línea de texto libre del histórico en algo
consultable, y luego en una decisión de vía.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bd import obtener_sesion
from app.servicios import normalizador as nz
from app.servicios import similares as sim

router = APIRouter(prefix="/piezas", tags=["piezas"])

VERSION_REGLAS = "reglas-2026.09"


class TextoLibre(BaseModel):
    descripcion: str = Field(min_length=1, max_length=500)


class Lote(BaseModel):
    descripciones: list[str] = Field(min_length=1, max_length=500)


@router.post("/normalizar")
def normalizar(p: TextoLibre):
    """De 'PIÑON Z18 08B-1 AISI 304 BI.UNIV.03.007.01' a campos."""
    r = nz.normalizar(p.descripcion)
    return {
        "descripcion_original": r.descripcion_original,
        "campos": r.a_dict(),
        "confianza": r.confianza,
        "dudoso": r.dudoso,
        "restos": r.restos,
        "necesita_revision": r.necesita_revision,
        "version_reglas": VERSION_REGLAS,
    }


@router.post("/normalizar-lote")
def normalizar_lote(p: Lote):
    """Para medir la calidad del histórico antes de cargarlo."""
    res = nz.normalizar_lote(p.descripciones)
    return {
        "informe": nz.informe_de_lote(res),
        "resultados": [
            {"descripcion": r.descripcion_original, "campos": r.a_dict(),
             "confianza": r.confianza, "dudoso": r.dudoso}
            for r in res
        ],
    }


@router.post("/similares")
def similares(p: TextoLibre, minimo: float = 0.55, tope: int = 5,
              sesion: Session = Depends(obtener_sesion)):
    """
    Normaliza la petición, busca comparables en el histórico y decide la vía.

    Es exactamente lo que el módulo de piñones especiales hace filtrando por
    Paso, Z y Ø, extendido a cualquier familia de pieza.
    """
    objetivo = nz.normalizar(p.descripcion)

    filas = sesion.execute(text("""
        SELECT p.id, p.referencia_cliente, p.descripcion_normalizada,
               p.descripcion_original, m.codigo AS material,
               (SELECT round(avg(lv.precio_unitario), 2)
                  FROM core.linea_venta lv WHERE lv.pieza_id = p.id) AS precio_medio,
               (SELECT count(*) FROM core.linea_venta lv WHERE lv.pieza_id = p.id) AS veces
        FROM core.pieza p
        LEFT JOIN core.material m ON m.id = p.material_id
        WHERE p.anulado_en IS NULL
        LIMIT 4000
    """)).mappings().all()

    candidatas, indice = [], {}
    for f in filas:
        texto = f["descripcion_normalizada"] or f["descripcion_original"] or ""
        if f["material"] and f["material"] not in texto:
            texto = f"{texto} {f['material']}"
        n = nz.normalizar(texto)
        candidatas.append(n)
        indice[id(n)] = f

    encontrados = sim.buscar(objetivo, candidatas, minimo=minimo, tope=tope)
    via, confianza = sim.decidir_via(objetivo, encontrados)

    return {
        "objetivo": {"campos": objetivo.a_dict(), "confianza": objetivo.confianza,
                     "dudoso": objetivo.dudoso},
        "via": via,
        "confianza": confianza,
        "propone_precio": via != "C_nueva",
        "comparables": [
            {
                "pieza_id": indice[id(c.pieza)]["id"],
                "referencia": indice[id(c.pieza)]["referencia_cliente"],
                "descripcion": indice[id(c.pieza)]["descripcion_normalizada"],
                "precio_medio": indice[id(c.pieza)]["precio_medio"],
                "veces_ofertada": indice[id(c.pieza)]["veces"],
                "similitud": c.similitud,
                "motivos": c.motivos,
            }
            for c in encontrados
        ],
        "explicaciones": sim.explicar(encontrados),
        "version_reglas": VERSION_REGLAS,
    }
