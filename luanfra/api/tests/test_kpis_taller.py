"""Pruebas de los indicadores de taller."""
from datetime import date

import pytest

from app.servicios import kpis_taller as kt


# --- OEE -------------------------------------------------------------------

def test_oee_es_el_producto_de_los_tres_factores():
    r = kt.oee(minutos_produciendo=400, minutos_planificados=480,
               piezas_buenas=98, piezas_totales=100, minutos_ideales=340)
    assert r["disponibilidad"] == pytest.approx(83.33, abs=0.01)
    assert r["rendimiento"] == pytest.approx(85.0, abs=0.01)
    assert r["calidad"] == 98.0
    assert r["oee"] == pytest.approx(83.33*85.0*98.0/10000, abs=0.05)


def test_los_tres_factores_se_devuelven_por_separado():
    """Un OEE del 45% no dice nada; saber cuál de los tres falla, sí."""
    r = kt.oee(240, 480, 100, 100, 230)
    assert r["disponibilidad"] == 50.0
    assert r["calidad"] == 100.0
    assert r["oee"] < r["rendimiento"]


def test_ningun_factor_pasa_del_cien_por_cien():
    r = kt.oee(minutos_produciendo=500, minutos_planificados=480,
               piezas_buenas=10, piezas_totales=10, minutos_ideales=600)
    assert r["disponibilidad"] == 100.0
    assert r["rendimiento"] == 100.0


def test_sin_datos_el_oee_falla_en_vez_de_devolver_cero():
    with pytest.raises(ValueError):
        kt.oee(100, 0, 10, 10, 90)
    with pytest.raises(ValueError):
        kt.oee(100, 480, 0, 0, 90)


def test_la_lectura_del_oee_es_realista_para_un_taller():
    assert "Excelente" in kt.clasificar_oee(72)
    assert "mayoría de talleres" in kt.clasificar_oee(58)
    assert "imputando" in kt.clasificar_oee(20)


# --- Eficiencia de flujo ---------------------------------------------------

def test_la_eficiencia_de_flujo_revela_la_espera():
    """Seis horas de mecanizado en tres semanas de plazo: alrededor del 2%."""
    e = kt.eficiencia_flujo(minutos_trabajados=360, dias_plazo=21)
    assert e < 5
    assert e == pytest.approx(360/(21*8*60)*100, abs=0.01)


def test_acortar_el_plazo_sube_la_eficiencia_de_flujo():
    largo = kt.eficiencia_flujo(360, 21)
    corto = kt.eficiencia_flujo(360, 3)
    assert corto > largo * 5


def test_no_pasa_del_cien():
    assert kt.eficiencia_flujo(100000, 1) == 100.0


def test_un_plazo_cero_es_un_error():
    with pytest.raises(ValueError):
        kt.eficiencia_flujo(100, 0)


# --- Preparación -----------------------------------------------------------

def test_el_ratio_de_preparacion_se_dispara_en_lotes_pequenos():
    lote_grande = kt.ratio_preparacion(60, 1200)
    lote_pequeno = kt.ratio_preparacion(60, 24)
    assert lote_pequeno > 60
    assert lote_grande < 10


def test_sin_minutos_no_hay_ratio():
    with pytest.raises(ValueError):
        kt.ratio_preparacion(0, 0)


# --- Desviación y fiabilidad ----------------------------------------------

def test_la_desviacion_positiva_significa_que_se_tardo_mas():
    assert kt.desviacion(100, 130) == 30.0
    assert kt.desviacion(100, 80) == -20.0


def test_la_fiabilidad_cuenta_las_que_caen_dentro_del_margen():
    pares = [(100, 105), (100, 110), (100, 150), (100, 95), (100, 200)]
    r = kt.fiabilidad(pares, margen_pct=15)
    assert r["muestras"] == 5
    assert r["dentro"] == 60.0


def test_la_fiabilidad_detecta_el_sesgo():
    """Si siempre se tarda más, el sesgo lo dice y las tarifas están mal."""
    r = kt.fiabilidad([(100, 140), (200, 275), (50, 72), (80, 110)])
    assert r["sesgo"] > 30
    assert r["dentro"] == 0.0


def test_sin_pares_validos_no_inventa():
    r = kt.fiabilidad([(0, 10), (None, 5)])
    assert r["muestras"] == 0
    assert r["sesgo"] is None


# --- Cumplimiento de plazo -------------------------------------------------

def test_calcula_cumplimiento_y_retraso_medio():
    r = kt.cumplimiento([
        (date(2026, 9, 1), date(2026, 8, 30)),
        (date(2026, 9, 1), date(2026, 9, 1)),
        (date(2026, 9, 1), date(2026, 9, 5)),
        (date(2026, 9, 1), date(2026, 9, 9)),
    ])
    assert r["cumplimiento"] == 50.0
    assert r["retraso_medio"] == 6.0
    assert r["peor_retraso"] == 8


def test_entregar_el_mismo_dia_cuenta_como_a_tiempo():
    r = kt.cumplimiento([(date(2026, 9, 1), date(2026, 9, 1))])
    assert r["cumplimiento"] == 100.0
    assert r["retraso_medio"] == 0.0


def test_sin_entregas_no_hay_cumplimiento():
    assert kt.cumplimiento([])["cumplimiento"] is None


# --- Catálogo --------------------------------------------------------------

def test_el_catalogo_cubre_las_cinco_categorias():
    assert {d.categoria for d in kt.CATALOGO} == set(kt.CATEGORIAS)


def test_todos_los_indicadores_tienen_formula_y_proposito():
    for d in kt.CATALOGO:
        assert d.formula and len(d.formula) > 5
        assert d.para_que and len(d.para_que) > 15
        assert d.datos_necesarios
        assert d.sentido in ("mayor_mejor", "menor_mejor")


def test_las_claves_no_se_repiten():
    claves = [d.clave for d in kt.CATALOGO]
    assert len(claves) == len(set(claves))


def test_el_objetivo_de_oee_es_realista_para_un_taller_por_encargo():
    """85% es de línea de serie. Poner eso solo consigue que nadie lo mire."""
    assert kt._def("oee").objetivo <= 65


# --- Estado ----------------------------------------------------------------

def test_el_estado_respeta_el_sentido_del_indicador():
    bueno = kt.Indicador(kt._def("cumplimiento_plazo"), 95.0)
    malo = kt.Indicador(kt._def("cumplimiento_plazo"), 50.0)
    assert bueno.estado == "bien" and malo.estado == "mal"

    plazo_corto = kt.Indicador(kt._def("plazo_real"), 15.0)
    plazo_largo = kt.Indicador(kt._def("plazo_real"), 60.0)
    assert plazo_corto.estado == "bien" and plazo_largo.estado == "mal"


def test_un_indicador_sin_objetivo_es_informativo():
    assert kt.Indicador(kt._def("wip"), 42).estado == "informativo"


def test_un_indicador_sin_valor_no_finge_tenerlo():
    assert kt.Indicador(kt._def("oee")).estado == "sin_dato"


# --- Diagnóstico de datos --------------------------------------------------

def test_dice_que_se_puede_medir_hoy_y_que_no():
    d = kt.diagnostico_de_datos({"cantidad buena y rechazo", "órdenes abiertas"})
    assert d["total"] == len(kt.CATALOGO)
    assert d["calculables"] >= 1
    assert d["bloqueados"] >= 1
    assert any(x["clave"] == "rechazo" for x in d["listos"])


def test_senala_el_dato_que_mas_desbloquea():
    """Sirve para decidir qué empezar a capturar primero."""
    d = kt.diagnostico_de_datos(set())
    assert d["calculables"] == 0
    assert d["dato_que_mas_desbloquea"]["desbloquea"] >= 2


def test_con_todos_los_datos_no_queda_nada_bloqueado():
    todos = {x for d in kt.CATALOGO for x in d.datos_necesarios}
    assert kt.diagnostico_de_datos(todos)["bloqueados"] == 0
