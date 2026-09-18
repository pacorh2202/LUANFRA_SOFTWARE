from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.rutas import fabricacion
from app.config import ajustes
from app.seguridad import autenticar
from app.rutas import (analisis, asistente, avisos, calculo, kpis,
                       kpis_taller, mecanizado, ofertas, panel, piezas, salud)

app = FastAPI(
    title="Luanfra — Sistema de ofertas y plazos",
    version="0.1.0",
    description=(
        "Capa propia sobre el ERP. Solo lectura del ERP, nunca escribe en él. "
        "Sin permisos de envío al exterior."
    ),
)

app.include_router(salud.router)
app.include_router(calculo.router)
app.include_router(panel.router)
app.include_router(ofertas.router)
app.include_router(piezas.router)
app.include_router(analisis.router)
app.include_router(avisos.router)
app.include_router(asistente.router)
app.include_router(kpis.router)
app.include_router(kpis_taller.router)
app.include_router(mecanizado.router)
app.include_router(fabricacion.router)

# CORS fuera de autenticación para permitir el preflight del cliente local.
app.middleware("http")(autenticar)
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5173"] if ajustes.entorno == "desarrollo" else [],
    allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"],
)

@app.get("/sesion")
def sesion(request: Request):
    return {"usuario": request.state.actor, "alcance": "administrador_piloto"}
