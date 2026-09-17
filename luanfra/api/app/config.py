"""Configuración leída de variables de entorno. Nada de credenciales en el código."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Ajustes(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bd_host: str = "localhost"
    bd_puerto: int = 5432
    bd_nombre: str = "luanfra"
    bd_usuario: str = "luanfra"
    bd_password: str = ""

    erp_host: str = ""
    erp_bd: str = "QGIS"
    erp_usuario: str = ""
    erp_password: str = ""

    ruta_almacen: str = "./almacen"
    anthropic_api_key: str = ""
    entorno: str = "desarrollo"
    acceso_claves_json: str = "{}"

    # Versión del modelo de cálculo. Toda oferta guarda con cuál se calculó.
    version_modelo: str = "2026.09-b"

    @property
    def url_bd(self) -> str:
        return (
            f"postgresql+psycopg://{self.bd_usuario}:{self.bd_password}"
            f"@{self.bd_host}:{self.bd_puerto}/{self.bd_nombre}"
        )


ajustes = Ajustes()
