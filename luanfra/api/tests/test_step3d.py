"""Pruebas del analizador de ficheros STEP."""
from pathlib import Path

import pytest

from app.servicios import step3d as s3

DATOS = Path(__file__).parent / "datos"
EJE = DATOS / "eje_ap242.step"
CONJUNTO = DATOS / "conjunto_ap214.step"
MALLA = DATOS / "malla.step"


# --- Identificación del fichero -------------------------------------------

def test_reconoce_ap242_y_lo_marca_como_el_bueno():
    a = s3.analizar_step(EJE)
    assert a.protocolo == "AP242"
    assert "PMI" in a.nota_protocolo


def test_reconoce_ap214():
    assert s3.analizar_step(CONJUNTO).protocolo == "AP214"


def test_identifica_el_cad_de_origen():
    assert "SOLIDWORKS" in s3.analizar_step(EJE).origen_cad


def test_un_fichero_que_no_es_step_se_rechaza(tmp_path):
    f = tmp_path / "x.step"
    f.write_text("esto no es un step")
    a = s3.analizar_step(f)
    assert "no parece" in a.avisos[0].lower()


def test_un_fichero_inexistente_no_revienta():
    a = s3.analizar_step("/no/existe.step")
    assert a.avisos and a.confianza == 0.0


# --- Geometría -------------------------------------------------------------

def test_mide_la_envolvente_de_un_eje():
    a = s3.analizar_step(EJE)
    largo, ancho, alto = a.envolvente
    assert largo == pytest.approx(50, abs=1)     # ø50
    assert ancho == pytest.approx(50, abs=1)
    assert alto == pytest.approx(300, abs=1)     # longitud


def test_detecta_que_es_una_pieza_de_revolucion():
    assert s3.analizar_step(EJE).es_de_revolucion


def test_cuenta_las_superficies_por_tipo():
    sup = s3.analizar_step(EJE).superficies
    assert sup["cilindros"] == 3
    assert sup["planos"] == 2
    assert sup["toros"] == 1


def test_convierte_las_pulgadas_a_milimetros():
    a = s3.analizar_step(CONJUNTO)
    assert a.unidad == "pulgadas"
    assert a.factor_mm == 25.4
    assert a.largo_mm == pytest.approx(4 * 25.4, abs=0.1)
    assert any("pulgadas" in x for x in a.avisos)


# --- Peso de partida -------------------------------------------------------

def test_el_peso_de_un_eje_usa_el_cilindro_no_el_prisma():
    """Comprar un taco cuadrado para un eje sería pagar de más."""
    a = s3.analizar_step(EJE)
    cilindro = a.peso_bruto_kg()
    prisma = a.largo_mm * a.ancho_mm * a.alto_mm / 1e6 * 7.85
    assert cilindro < prisma
    assert cilindro == pytest.approx(prisma * 3.1416 / 4, rel=0.05)


def test_el_peso_es_plausible_para_un_eje_de_acero():
    """ø50 × 300 de acero pesan unos 4,6 kg."""
    assert s3.analizar_step(EJE).peso_bruto_kg() == pytest.approx(4.6, abs=0.3)


def test_el_material_cambia_el_peso():
    a = s3.analizar_step(EJE)
    assert a.peso_bruto_kg(2.70) < a.peso_bruto_kg(7.85)      # aluminio


# --- PMI -------------------------------------------------------------------

def test_detecta_las_tolerancias_del_modelo():
    a = s3.analizar_step(EJE)
    assert a.tiene_pmi
    assert "DIMENSIONAL_SIZE" in a.pmi_encontrado
    assert "CYLINDRICITY_TOLERANCE" in a.pmi_encontrado
    assert "SURFACE_TEXTURE" in a.pmi_encontrado


def test_avisa_cuando_no_hay_tolerancias():
    a = s3.analizar_step(CONJUNTO)
    assert not a.tiene_pmi
    assert any("tolerancias" in x for x in a.avisos)


# --- Casos que hay que rechazar -------------------------------------------

def test_detecta_un_ensamblaje_y_pide_una_pieza():
    a = s3.analizar_step(CONJUNTO)
    assert a.es_ensamblaje
    assert any("fichero por pieza" in x for x in a.avisos)


def test_un_ensamblaje_baja_mucho_la_confianza():
    assert s3.analizar_step(CONJUNTO).confianza < s3.analizar_step(EJE).confianza / 2


def test_detecta_una_malla_y_avisa_de_que_no_sirve():
    a = s3.analizar_step(MALLA)
    assert any("malla" in x for x in a.avisos)


# --- Confianza y recomendaciones ------------------------------------------

def test_un_ap242_con_pmi_da_confianza_alta():
    assert s3.analizar_step(EJE).confianza >= 0.9


def test_recomienda_ap242_cuando_llega_un_ap214():
    r = s3.recomendaciones(s3.analizar_step(CONJUNTO))
    assert any("AP242" in x for x in r)
    assert any("un fichero por pieza" in x for x in r)


def test_un_fichero_perfecto_no_genera_recomendaciones():
    assert s3.recomendaciones(s3.analizar_step(EJE)) == []


def test_el_resumen_trae_lo_que_necesita_el_presupuestador():
    r = s3.resumen_para_presupuesto(s3.analizar_step(EJE))
    for clave in ("envolvente_mm", "peso_bruto_kg", "caras_cilindricas",
                  "tiene_tolerancias", "confianza"):
        assert clave in r
    assert r["peso_bruto_kg"] > 0
