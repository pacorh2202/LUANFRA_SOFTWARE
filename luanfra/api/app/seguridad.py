"""Acceso administrativo del piloto. Claves aleatorias, hashes en configuración.

No sustituye SSO/MFA ni permisos por departamento; todos los usuarios aquí
configurados son administradores del piloto. No activar para toda la plantilla.
"""
import hashlib
import hmac
import json
import re

from fastapi import Request
from starlette.responses import JSONResponse

from app.config import ajustes


async def autenticar(request: Request, call_next):
    if request.url.path == "/vivo":
        return JSONResponse({"estado": "ok"})
    try:
        claves = json.loads(ajustes.acceso_claves_json)
        if not isinstance(claves, dict) or not claves or any(
            not re.fullmatch(r"[a-f0-9]{64}", digest)
            or not isinstance(actor, str) or not actor.strip()
            for digest, actor in claves.items()
        ):
            raise ValueError("Configuración inválida")
    except (ValueError, TypeError):
        return JSONResponse({"detail": "Configure las claves de acceso del piloto."}, status_code=503)
    cabecera = request.headers.get("authorization", "")
    esquema, _, clave = cabecera.partition(" ")
    digest = hashlib.sha256(clave.encode()).hexdigest()
    actor = next((a for h, a in claves.items() if hmac.compare_digest(h, digest)), None)
    if esquema.lower() != "bearer" or len(clave) < 32 or actor is None:
        return JSONResponse({"detail": "Acceso no autorizado"}, status_code=401,
                            headers={"WWW-Authenticate": "Bearer"})
    request.state.actor = actor
    return await call_next(request)


def actor_actual(request: Request) -> str:
    return request.state.actor
