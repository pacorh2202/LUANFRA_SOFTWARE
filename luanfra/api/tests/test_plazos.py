from datetime import date
from decimal import Decimal

import pytest

from app.servicios import plazos


COLAS = [
    plazos.ColaCentro("TORNO-1", 2400, Decimal("8"), Decimal("0.70")),
    plazos.ColaCentro("FRESA-2", 600, Decimal("16"), Decimal("0.65")),
]


def test_comprometible_siempre_mayor_que_optima():
    r = plazos.calcular(COLAS, [plazos.CargaPedido("TORNO-1", 900)], desde=date(2026, 9, 8))
    assert r.dias_comprometible > r.dias_optimo
    assert r.fecha_comprometible > r.fecha_optima


def test_detecta_el_cuello_de_botella():
    r = plazos.calcular(
        COLAS,
        [plazos.CargaPedido("TORNO-1", 5000), plazos.CargaPedido("FRESA-2", 100)],
        desde=date(2026, 9, 8),
    )
    assert r.centro_cuello_botella == "TORNO-1"


def test_las_fechas_caen_en_laborable():
    r = plazos.calcular(COLAS, [plazos.CargaPedido("TORNO-1", 900)], desde=date(2026, 9, 8))
    assert r.fecha_optima.weekday() < 5
    assert r.fecha_comprometible.weekday() < 5


def test_la_subcontrata_alarga_el_plazo():
    sin = plazos.calcular(COLAS, [plazos.CargaPedido("TORNO-1", 900)])
    con = plazos.calcular(
        COLAS,
        [plazos.CargaPedido("TORNO-1", 900),
         plazos.CargaPedido("TEMPLE", 0, plazo_externo_dias=10)],
    )
    assert con.dias_optimo > sin.dias_optimo


def test_centro_desconocido_falla_en_vez_de_inventar():
    with pytest.raises(ValueError):
        plazos.calcular(COLAS, [plazos.CargaPedido("RECTIFICADORA", 300)])


def test_simulador_de_impacto():
    impacto = plazos.simular_entrada(COLAS, [plazos.CargaPedido("TORNO-1", 3360)])
    assert impacto["TORNO-1"] == pytest.approx(10.0, abs=0.1)
