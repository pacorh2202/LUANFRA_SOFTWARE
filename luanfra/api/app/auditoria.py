"""
Escritura en el registro de auditoría.

La tabla audit.evento solo admite INSERT y encadena por hash en un trigger.
Desde aquí no se puede alterar el pasado ni por error ni a propósito.
"""
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import ajustes

SQL = text("""
    INSERT INTO audit.evento
        (actor, accion, entidad, entidad_id, datos_antes, datos_despues, version_sistema)
    VALUES
        (:actor, :accion, :entidad, :entidad_id,
         CAST(:antes AS jsonb), CAST(:despues AS jsonb), :version)
""")


def registrar(
    sesion: Session,
    accion: str,
    entidad: str,
    entidad_id: str | None = None,
    antes: Any = None,
    despues: Any = None,
    actor: str = "sistema",
) -> None:
    sesion.execute(
        SQL,
        {
            "actor": actor,
            "accion": accion,
            "entidad": entidad,
            "entidad_id": str(entidad_id) if entidad_id is not None else None,
            "antes": json.dumps(antes, default=str) if antes is not None else None,
            "despues": json.dumps(despues, default=str) if despues is not None else None,
            "version": ajustes.version_modelo,
        },
    )
