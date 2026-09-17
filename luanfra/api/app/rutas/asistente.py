"""Asistente conversacional sobre los datos de la empresa."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bd import obtener_sesion
from app.config import ajustes
from app.servicios import asistente as asis
from app.servicios import ia

router = APIRouter(prefix="/asistente", tags=["asistente"])

ROLES = ("direccion", "comercial", "administracion", "taller", "oficina_tecnica")


class Pregunta(BaseModel):
    texto: str = Field(min_length=1, max_length=500)
    rol: str = "direccion"


def _ejecutor(sesion: Session):
    """
    Solo ejecuta SQL que venga del catálogo. La comprobación se repite aquí
    aunque ya se haga antes: es la última puerta antes de la base de datos.
    """
    permitido = {c.sql for c in asis.CATALOGO}

    def ejecutar(sql: str, params: dict) -> list[dict]:
        if sql not in permitido:
            raise ValueError("Consulta fuera del catálogo.")
        return [dict(f) for f in sesion.execute(text(sql), params).mappings().all()]

    return ejecutar


@router.get("/puedo-preguntar")
def puedo_preguntar(rol: str = "direccion"):
    """Qué sabe responder el asistente a esta persona."""
    if rol not in ROLES:
        raise HTTPException(404, f"Rol desconocido. Opciones: {', '.join(ROLES)}")
    return {"rol": rol, "consultas": asis.catalogo_para(rol),
            "tambien": "Dudas técnicas de mecanizado, materiales y tolerancias.",
            "no_responde": "Cualquier otra cosa. Lo dirá en vez de inventarla."}


@router.post("")
def preguntar(p: Pregunta, sesion: Session = Depends(obtener_sesion)):
    if p.rol not in ROLES:
        raise HTTPException(404, f"Rol desconocido. Opciones: {', '.join(ROLES)}")
    if not ajustes.anthropic_api_key:
        raise HTTPException(
            503, "Falta ANTHROPIC_API_KEY en el .env. El asistente necesita IA "
                 "para entender la pregunta; el resto del sistema no.")

    llamar = ia.crear_cliente(ajustes.anthropic_api_key)
    r = asis.preguntar(p.texto, p.rol, llamar, _ejecutor(sesion))
    return r.a_dict()
