from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class OperacionEntrada(BaseModel):
    centro: str
    minutos_preparacion: Decimal = Field(ge=0, default=0)
    minutos_unitario: Decimal = Field(ge=0, default=0)
    tarifa_minuto: Decimal = Field(gt=0)
    es_subcontrata: bool = False
    importe_externo: Decimal = Field(ge=0, default=Decimal("0"))


class PeticionCalculo(BaseModel):
    cantidad: int = Field(gt=0)
    peso_bruto_kg: Decimal = Field(gt=0)
    precio_kg: Decimal = Field(gt=0)
    merma_pct: Decimal = Field(ge=0, default=Decimal("10"))
    indirectos_pct: Decimal = Field(ge=0, default=Decimal("10"))
    margen_pct: Decimal = Field(ge=0, default=Decimal("35"))
    politica_precio: Literal["recargo_coste", "margen_venta"] = "recargo_coste"
    confianza: Decimal = Field(ge=0, le=1, default=Decimal("0.8"))
    operaciones: list[OperacionEntrada]


class RespuestaCalculo(BaseModel):
    precio_total: Decimal
    precio_unitario: Decimal
    precio_min: Decimal
    precio_max: Decimal
    coste_total: Decimal
    minutos_totales: Decimal
    desglose: dict
    version_modelo: str
