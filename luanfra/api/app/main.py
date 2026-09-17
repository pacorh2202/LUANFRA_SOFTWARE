from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ajustes
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"] if ajustes.entorno == "desarrollo" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
