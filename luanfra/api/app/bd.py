"""Conexión a la base propia. La conexión al ERP es aparte y SIEMPRE de solo lectura."""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import ajustes

motor = create_engine(ajustes.url_bd, pool_pre_ping=True, echo=False)
SesionLocal = sessionmaker(bind=motor, autoflush=False, autocommit=False)


def obtener_sesion() -> Generator[Session, None, None]:
    sesion = SesionLocal()
    try:
        yield sesion
    finally:
        sesion.close()
