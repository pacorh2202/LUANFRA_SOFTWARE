from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bd import obtener_sesion
from app.config import ajustes

router = APIRouter(tags=["salud"])


@router.get("/salud")
def salud(sesion: Session = Depends(obtener_sesion)):
    tablas = sesion.execute(
        text("""SELECT count(*) FROM information_schema.tables
                WHERE table_schema IN ('core','ops','audit','stage')""")
    ).scalar()
    eventos = sesion.execute(text("SELECT count(*) FROM audit.evento")).scalar()
    return {
        "estado": "ok",
        "entorno": ajustes.entorno,
        "version_modelo": ajustes.version_modelo,
        "tablas": tablas,
        "eventos_auditoria": eventos,
    }


@router.get("/salud/auditoria")
def integridad_auditoria(sesion: Session = Depends(obtener_sesion)):
    """Verifica que nadie ha tocado el pasado. Lista vacía = cadena intacta."""
    filas = sesion.execute(text("SELECT * FROM audit.verificar_cadena()")).mappings().all()
    return {"intacta": len(filas) == 0, "problemas": [dict(f) for f in filas]}
