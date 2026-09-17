from decimal import Decimal

import pytest

from app.servicios import motor_coste as mc


def _op(**kw):
    base = dict(centro="TORNO-1", minutos_preparacion=60,
                minutos_unitario=5, tarifa_minuto=Decimal("0.45"))
    base.update(kw)
    return mc.Operacion(**base)


def entrada(**kw):
    base = dict(
        cantidad=100,
        peso_bruto_kg=Decimal("1.2"),
        precio_kg=Decimal("2.50"),
        merma_pct=Decimal("10"),
        operaciones=[_op()],
        indirectos_pct=Decimal("10"),
        margen_pct=Decimal("35"),
    )
    base.update(kw)
    return mc.EntradaCoste(**base)


def test_calculo_basico():
    r = mc.calcular(entrada())
    # material: 1,2 * 100 * 2,50 * 1,10 = 330
    assert r.coste_material == Decimal("330.00")
    # máquina: 5 * 100 * 0,45 = 225
    assert r.coste_maquina == Decimal("225.00")
    # preparación: 60 * 0,45 = 27
    assert r.coste_preparacion == Decimal("27.00")
    assert r.precio_total > r.coste_total


def test_la_preparacion_se_reparte_en_el_lote():
    """10 piezas no cuestan 10 veces lo que una: el setup se diluye."""
    unitario_1 = mc.calcular(entrada(cantidad=1)).precio_unitario
    unitario_100 = mc.calcular(entrada(cantidad=100)).precio_unitario
    assert unitario_100 < unitario_1


def test_nunca_por_debajo_de_coste():
    r = mc.calcular(entrada(margen_pct=Decimal("0")))
    assert r.precio_total >= r.coste_total


def test_sin_material_no_presupuesta():
    with pytest.raises(mc.ErrorDeCoste):
        mc.calcular(entrada(precio_kg=Decimal("0")))


def test_sin_ruta_no_presupuesta():
    with pytest.raises(mc.ErrorDeCoste):
        mc.calcular(entrada(operaciones=[]))


def test_subcontrata_suma_aparte():
    r = mc.calcular(entrada(operaciones=[
        _op(),
        _op(centro="TEMPLE", es_subcontrata=True, importe_externo=Decimal("1.80")),
    ]))
    assert r.coste_externo == Decimal("180.00")


def test_banda_se_ensancha_con_poca_confianza():
    p = Decimal("1000.00")
    min_alta, max_alta = mc.banda(p, Decimal("0.95"))
    min_baja, max_baja = mc.banda(p, Decimal("0.40"))
    assert (max_alta - min_alta) < (max_baja - min_baja)


def test_dinero_sin_errores_de_coma_flotante():
    r = mc.calcular(entrada(cantidad=3, peso_bruto_kg=Decimal("0.1"),
                            precio_kg=Decimal("0.10")))
    assert r.precio_total.as_tuple().exponent == -2
