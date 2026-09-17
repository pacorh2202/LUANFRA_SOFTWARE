"""
Pruebas del reconocedor sobre sólidos B-rep reales.

Las piezas se generan con OpenCascade en tests/datos/generar_piezas.py, así que
las dimensiones son conocidas y los volúmenes se pueden comprobar a mano.
"""
import math
from pathlib import Path

import pytest

from app.servicios import reconocedor3d as rc

DATOS = Path(__file__).parent / "datos"
EJE = DATOS / "eje_escalonado.step"      # ø50×120 + ø40×80, agujero pasante ø10
PLACA = DATOS / "placa_agujeros.step"    # 200×100×20, 4 pasantes ø12, 1 ciego ø20
CASQUILLO = DATOS / "casquillo.step"     # ø60 ext, ø40 int, 50 largo


# --- Exactitud del volumen: se compara con el cálculo a mano ---------------

def test_el_volumen_del_eje_es_exacto():
    esperado = math.pi*25**2*120 + math.pi*20**2*80 - math.pi*5**2*200
    assert rc.reconocer(EJE).volumen_mm3 == pytest.approx(esperado, rel=1e-6)


def test_el_volumen_de_la_placa_es_exacto():
    esperado = 200*100*20 - 4*math.pi*6**2*20 - math.pi*10**2*12
    assert rc.reconocer(PLACA).volumen_mm3 == pytest.approx(esperado, rel=1e-6)


def test_el_volumen_del_casquillo_es_exacto():
    esperado = math.pi*(30**2 - 20**2)*50
    assert rc.reconocer(CASQUILLO).volumen_mm3 == pytest.approx(esperado, rel=1e-6)


def test_la_envolvente_es_exacta():
    assert rc.reconocer(EJE).envolvente == (50.0, 50.0, 200.0)
    assert rc.reconocer(PLACA).envolvente == (200.0, 100.0, 20.0)


# --- Agujeros --------------------------------------------------------------

def test_encuentra_el_agujero_pasante_del_eje():
    a = rc.reconocer(EJE).agujeros
    assert len(a) == 1
    assert a[0].diametro == 10.0
    assert a[0].profundidad == 200.0
    assert a[0].pasante


def test_un_agujero_no_se_confunde_con_un_eje():
    """
    Fallo real de la primera versión: invertía dos veces la normal y el
    agujero ø10 salía como un escalón de torneado de ø10.
    """
    r = rc.reconocer(EJE)
    assert 10.0 not in [e.diametro for e in r.escalones]
    assert 10.0 in [a.diametro for a in r.agujeros]


def test_encuentra_los_cinco_agujeros_de_la_placa():
    a = rc.reconocer(PLACA).agujeros
    assert len(a) == 5
    assert sum(1 for x in a if x.diametro == 12.0) == 4
    assert sum(1 for x in a if x.diametro == 20.0) == 1


def test_distingue_pasante_de_ciego():
    a = rc.reconocer(PLACA).agujeros
    ciego = next(x for x in a if x.diametro == 20.0)
    pasantes = [x for x in a if x.diametro == 12.0]
    assert not ciego.pasante
    assert ciego.profundidad == 12.0
    assert all(p.pasante for p in pasantes)


def test_marca_los_agujeros_profundos():
    """L/D 20 en el eje: hay que picotear y eso cambia el tiempo."""
    a = rc.reconocer(EJE).agujeros[0]
    assert a.relacion_profundidad == 20.0
    assert rc.a_operaciones(rc.reconocer(EJE))["taladros"][0]["profundo"]


def test_el_interior_del_casquillo_es_un_agujero():
    r = rc.reconocer(CASQUILLO)
    assert [a.diametro for a in r.agujeros] == [40.0]
    assert [e.diametro for e in r.escalones] == [60.0]


# --- Escalones y torneabilidad --------------------------------------------

def test_encuentra_los_dos_escalones_del_eje():
    e = rc.reconocer(EJE).escalones
    assert [(x.diametro, x.longitud) for x in e] == [(50.0, 120.0), (40.0, 80.0)]


def test_reconoce_una_pieza_torneable():
    r = rc.reconocer(EJE)
    assert r.es_torneable
    assert r.eje_de_revolucion == (0.0, 0.0, 1.0)
    assert rc.a_operaciones(r)["estrategia"] == "torneado"


def test_un_casquillo_corto_y_ancho_tambien_es_torneable():
    """
    Fallo real: comparaba las dos dimensiones menores y un casquillo de
    ø60 × 50 salía como no torneable.
    """
    assert rc.reconocer(CASQUILLO).es_torneable


def test_una_placa_no_es_torneable():
    r = rc.reconocer(PLACA)
    assert not r.es_torneable
    assert rc.a_operaciones(r)["estrategia"] == "fresado"


# --- Material de partida ---------------------------------------------------

def test_el_bruto_de_una_pieza_torneable_es_un_cilindro():
    r = rc.reconocer(EJE)
    prisma = 54 * 54 * 204
    assert r.bruto_mm3 < prisma
    assert r.bruto_mm3 == pytest.approx(math.pi*27**2*204, rel=0.01)


def test_el_bruto_de_una_placa_es_un_prisma():
    r = rc.reconocer(PLACA)
    assert r.bruto_mm3 == pytest.approx(204*104*24, rel=0.01)


def test_el_material_a_arrancar_es_bruto_menos_pieza():
    r = rc.reconocer(EJE)
    assert r.material_a_arrancar_mm3 == pytest.approx(r.bruto_mm3 - r.volumen_mm3, rel=1e-9)
    assert 0 < r.porcentaje_arranque < 100


def test_el_peso_sale_de_la_densidad():
    r = rc.reconocer(EJE)
    assert rc.peso_pieza_kg(r) == pytest.approx(r.volumen_mm3/1e6*7.85, abs=1e-4)
    assert rc.peso_pieza_kg(r, 2.70) < rc.peso_pieza_kg(r, 7.85)
    assert rc.peso_bruto_kg(r) > rc.peso_pieza_kg(r)


# --- Separación entre lo medido y lo interpretado -------------------------

def test_distingue_lo_exacto_de_lo_interpretado():
    r = rc.reconocer(EJE)
    assert "volumen_mm3" in r.exacto
    assert "diametros_interiores" in r.exacto
    assert "es_torneable" in r.interpretado
    assert "volumen_mm3" not in r.interpretado


def test_no_afirma_que_un_agujero_lleva_rosca():
    """Por geometría no se puede saber. El sistema lo dice, no lo adivina."""
    dudas = rc.a_operaciones(rc.reconocer(PLACA))["dudas"]
    assert any("rosca" in d for d in dudas)


# --- Robustez --------------------------------------------------------------

def test_un_fichero_inexistente_no_revienta():
    r = rc.reconocer("/no/existe.step")
    assert r.avisos and r.volumen_mm3 == 0.0


def test_un_fichero_que_no_es_step_da_error_controlado(tmp_path):
    f = tmp_path / "x.step"
    f.write_text("basura")
    with pytest.raises(rc.ErrorGeometria):
        rc.reconocer(f)
