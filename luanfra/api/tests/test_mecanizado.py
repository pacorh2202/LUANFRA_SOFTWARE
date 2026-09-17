"""
Pruebas del motor de mecanizado.

Varias comprueban el resultado contra el cálculo hecho a mano, para que no sea
"lo que salga" sino un número defendible delante de un jefe de taller.
"""
import math

import pytest

from app.servicios import mecanizado as mz


# --- Fórmulas de corte -----------------------------------------------------

def test_revoluciones_formula_conocida():
    """n = 1000·Vc/(π·D). Con Vc=200 y D=100: 636,6 rpm."""
    assert mz.revoluciones(200, 100) == pytest.approx(636.6, abs=0.5)


def test_diametro_cero_es_un_error_no_un_infinito():
    with pytest.raises(ValueError):
        mz.revoluciones(200, 0)


def test_el_material_duro_tarda_mas_que_el_blando():
    acero = mz.tiempo_cilindrado(100, 80, 500, "F-114")
    herram = mz.tiempo_cilindrado(100, 80, 500, "1.2379")
    alu = mz.tiempo_cilindrado(100, 80, 500, "ALUMINIO")
    assert herram > acero > alu


def test_el_inox_tarda_mas_que_el_acero_al_carbono():
    assert mz.tiempo_cilindrado(60, 50, 300, "AISI 316") > \
           mz.tiempo_cilindrado(60, 50, 300, "F-114")


def test_quitar_mas_material_lleva_mas_pasadas_y_mas_tiempo():
    poco = mz.tiempo_cilindrado(60, 55, 300, "F-114")
    mucho = mz.tiempo_cilindrado(120, 40, 300, "F-114")
    assert mucho > poco * 3


def test_el_acabado_es_mas_lento_por_milimetro_que_el_desbaste():
    """Menos avance y menos pasada: para el mismo recorrido, más tiempo."""
    desbaste = mz.tiempo_cilindrado(51, 50, 300, "F-114")
    acabado = mz.tiempo_cilindrado(51, 50, 300, "F-114", acabado=True)
    assert acabado > desbaste


def test_sin_material_que_quitar_el_tiempo_es_cero():
    assert mz.tiempo_cilindrado(50, 50, 300, "F-114") == 0.0
    assert mz.tiempo_cilindrado(50, 60, 300, "F-114") == 0.0


# --- Taladrado -------------------------------------------------------------

def test_el_agujero_profundo_se_penaliza_por_picoteo():
    normal = mz.tiempo_taladrado(20, 40, "F-114")     # 2 diámetros
    profundo = mz.tiempo_taladrado(20, 200, "F-114")  # 10 diámetros
    assert profundo > normal * 5


def test_sin_profundidad_no_hay_taladro():
    assert mz.tiempo_taladrado(10, 0, "F-114") == 0.0


# --- Tronzado --------------------------------------------------------------

def test_el_tronzado_va_por_seccion():
    """El doble de diámetro es cuatro veces la sección, no el doble."""
    d100 = mz.tiempo_tronzado(100, "F-114") - 0.5
    d200 = mz.tiempo_tronzado(200, "F-114") - 0.5
    assert d200 / d100 == pytest.approx(4.0, rel=0.05)


# --- Tallado ---------------------------------------------------------------

def test_el_tiempo_de_tallado_crece_con_el_numero_de_dientes():
    z18 = mz.tiempo_tallado(18, 20, 3, "F-114")
    z90 = mz.tiempo_tallado(90, 20, 3, "F-114")
    assert z90 / z18 == pytest.approx(5.0, rel=0.02)


def test_una_fresa_de_dos_entradas_tarda_la_mitad():
    una = mz.tiempo_tallado(30, 20, 3, "F-114", entradas_fresa=1)
    dos = mz.tiempo_tallado(30, 20, 3, "F-114", entradas_fresa=2)
    assert dos == pytest.approx(una / 2, rel=0.01)


# --- Tolerancias -----------------------------------------------------------

def test_una_tolerancia_apretada_da_una_calidad_it_baja():
    """H7 en ø50 son 25 micras: IT7."""
    assert mz.calidad_it(0.025, 50) == 7


def test_una_tolerancia_amplia_da_una_calidad_it_alta():
    assert mz.calidad_it(0.4, 50) >= 10


def test_it7_obliga_a_rectificar():
    hace_falta, motivo = mz.requiere_rectificado(0.025, 50)
    assert hace_falta
    assert "IT7" in motivo


def test_it9_se_hace_de_torno():
    hace_falta, _ = mz.requiere_rectificado(0.1, 50)
    assert not hace_falta


def test_la_rugosidad_fina_obliga_a_rectificar():
    hace_falta, motivo = mz.requiere_rectificado(0.2, 50, rugosidad_ra=0.4)
    assert hace_falta
    assert "Ra" in motivo


def test_templado_con_cota_de_ajuste_obliga_a_rectificar_despues():
    hace_falta, motivo = mz.requiere_rectificado(0.05, 50, templado=True)
    assert hace_falta
    assert "temple" in motivo


def test_la_sugerencia_comercial_aparece_cuando_hay_margen():
    s = mz.sugerencia_abaratar(0.02, 50, precio_estimado=4000)
    assert s and "IT" in s and "€" in s


def test_no_hay_sugerencia_si_la_tolerancia_ya_es_holgada():
    assert mz.sugerencia_abaratar(0.5, 50) is None


# --- Generación de ruta ----------------------------------------------------

def test_un_eje_lleva_sierra_desbaste_y_acabado():
    r = mz.generar_ruta(familia="eje", material="F-114",
                        diametro_mm=100, longitud_mm=1885, tolerancia_mm=0.2)
    maquinas = [o.tipo_maquina for o in r.operaciones]
    assert "sierra" in maquinas
    assert maquinas.count("torno_cnc") == 2
    assert "rectificadora" not in maquinas
    assert r.minutos_unitario > 0


def test_un_eje_con_h7_lleva_rectificado():
    r = mz.generar_ruta(familia="eje", material="F-114",
                        diametro_mm=50, longitud_mm=300, tolerancia_mm=0.025)
    assert "rectificadora" in [o.tipo_maquina for o in r.operaciones]


def test_un_pinon_lleva_talladora_y_chavetero():
    r = mz.generar_ruta(familia="pinon", material="AISI 304",
                        diametro_mm=93.8, ancho_mm=50, dientes_z=18, modulo=3)
    maquinas = [o.tipo_maquina for o in r.operaciones]
    assert "talladora" in maquinas
    assert "mortajadora" in maquinas


def test_un_pinon_de_90_dientes_tarda_mucho_mas_en_tallar_que_uno_de_18():
    """
    Con módulo 3, Z18 da un primitivo de 54 mm y Z90 de 270: hay que comparar
    geometrías coherentes, no el mismo diámetro con distinto número de dientes.
    Lo que se comprueba es la operación de tallado, que es donde está la
    diferencia; el tronzado y el torneado dependen del diámetro, no de Z.
    """
    z18 = mz.generar_ruta(familia="pinon", material="F-114",
                          diametro_mm=60, ancho_mm=30, dientes_z=18, modulo=3)
    z90 = mz.generar_ruta(familia="pinon", material="F-114",
                          diametro_mm=276, ancho_mm=30, dientes_z=90, modulo=3)
    t18 = next(o for o in z18.operaciones if o.tipo_maquina == "talladora")
    t90 = next(o for o in z90.operaciones if o.tipo_maquina == "talladora")
    assert t90.minutos_unitario == pytest.approx(t18.minutos_unitario * 5, rel=0.02)
    assert z90.minutos_unitario > z18.minutos_unitario


def test_el_tiempo_de_tallado_es_realista():
    """
    Un piñón Z18 módulo 3 de 30 mm de ancho no se talla en 40 segundos.
    Con los parámetros de plaquita en vez de los de fresa madre salía así.
    """
    t = mz.tiempo_tallado(18, 30, 3, "F-114")
    assert 1.0 < t < 6.0
    t_grande = mz.tiempo_tallado(90, 50, 6, "F-125")
    assert 10 < t_grande < 90


def test_un_pinon_doble_tarda_mas_en_tallar():
    simple = mz.generar_ruta(familia="pinon", material="F-114", diametro_mm=90,
                             ancho_mm=30, dientes_z=20, modulo=3)
    doble = mz.generar_ruta(familia="pinon_doble", material="F-114", diametro_mm=90,
                            ancho_mm=30, dientes_z=20, modulo=3)
    assert doble.minutos_unitario > simple.minutos_unitario


def test_el_tratamiento_entra_como_subcontrata_con_plazo():
    r = mz.generar_ruta(familia="eje", material="F-114", diametro_mm=100,
                        longitud_mm=1885, tratamientos=["cromado"])
    externas = [o for o in r.operaciones if o.es_externa]
    assert len(externas) == 1
    assert externas[0].plazo_externo_dias > 0
    assert externas[0].minutos_unitario == 0


def test_sin_familia_no_se_genera_ruta():
    r = mz.generar_ruta(familia=None, material="F-114", diametro_mm=50)
    assert r.operaciones == []
    assert "familia" in r.avisos[0]


def test_pieza_de_revolucion_sin_diametro_no_se_estima():
    r = mz.generar_ruta(familia="eje", material="F-114")
    assert r.operaciones == []
    assert any("diámetro" in a for a in r.avisos)


def test_un_pinon_sin_dientes_avisa_y_no_talla():
    r = mz.generar_ruta(familia="pinon", material="F-114", diametro_mm=90)
    assert "talladora" not in [o.tipo_maquina for o in r.operaciones]
    assert any("dientes" in a for a in r.avisos)


def test_faltar_datos_baja_la_confianza():
    completa = mz.generar_ruta(familia="eje", material="F-114", diametro_mm=50,
                               longitud_mm=300, tolerancia_mm=0.1)
    parcial = mz.generar_ruta(familia="eje", material=None, diametro_mm=50)
    assert completa.confianza > parcial.confianza


def test_la_preparacion_no_depende_de_la_cantidad():
    r = mz.generar_ruta(familia="eje", material="F-114", diametro_mm=50, longitud_mm=300)
    assert r.minutos_totales(100) - r.minutos_totales(1) == \
           pytest.approx(r.minutos_unitario * 99, rel=0.01)


def test_la_talladora_es_la_preparacion_mas_cara():
    assert mz.PREPARACION["talladora"] == max(mz.PREPARACION.values())


# --- Calibración -----------------------------------------------------------

def test_sin_muestras_suficientes_no_se_calibra():
    c = mz.calibrar_con_historico("torno_cnc", [(10, 12), (20, 25)])
    assert not c.fiable
    assert c.factor == 1.0


def test_detecta_que_el_taller_tarda_mas_que_la_teoria():
    pares = [(10, 14), (20, 29), (30, 41), (15, 21), (25, 35), (40, 55)]
    c = mz.calibrar_con_historico("torno_cnc", pares)
    assert c.fiable
    assert 1.3 < c.factor < 1.5
    assert "más que el cálculo" in c.mensaje


def test_una_dispersion_enorme_invalida_la_calibracion():
    pares = [(10, 5), (10, 60), (10, 12), (10, 90), (10, 8), (10, 45)]
    c = mz.calibrar_con_historico("torno_cnc", pares)
    assert not c.fiable
    assert "varían demasiado" in c.mensaje


def test_avisa_si_el_taller_va_mas_rapido_que_la_teoria():
    pares = [(20, 12), (30, 19), (10, 6), (40, 25), (25, 16), (15, 9)]
    c = mz.calibrar_con_historico("torno_cnc", pares)
    assert "imputando incompleto" in c.mensaje


def test_aplicar_la_calibracion_cambia_los_tiempos():
    r = mz.generar_ruta(familia="eje", material="F-114", diametro_mm=50, longitud_mm=300)
    antes = r.minutos_unitario
    mz.aplicar_calibracion(r, {"torno_cnc": 1.5})
    assert r.minutos_unitario > antes


# --- Geometría de piñones de cadena ----------------------------------------

def test_el_diametro_primitivo_coincide_con_el_del_erp():
    """
    Comprobación contra la pantalla de Propuestas de Piñones Especiales:
    paso 19,05 con Z14 da un primitivo de 85,6 mm.
    """
    assert mz.diametro_primitivo_cadena(19.05, 14) == pytest.approx(85.6, abs=0.1)


def test_el_diametro_exterior_es_mayor_que_el_primitivo():
    assert mz.diametro_exterior_cadena(12.70, 18) > mz.diametro_primitivo_cadena(12.70, 18)


def test_mas_dientes_mismo_paso_es_mas_diametro():
    assert mz.diametro_primitivo_cadena(12.70, 40) > mz.diametro_primitivo_cadena(12.70, 18)


def test_el_modulo_equivalente_sale_del_paso():
    assert mz.modulo_desde_paso(19.05) == pytest.approx(6.06, abs=0.01)


def test_los_pasos_de_la_norma_estan_recogidos():
    assert mz.PASOS_CADENA_MM["08B"] == 12.70
    assert mz.PASOS_CADENA_MM["16B"] == 25.40


def test_geometria_imposible_es_un_error():
    with pytest.raises(ValueError):
        mz.diametro_primitivo_cadena(12.7, 2)


def test_un_pinon_de_cadena_no_necesita_que_le_den_el_diametro():
    """La descripción del ERP no lleva Ø: se deduce del paso y de Z."""
    r = mz.generar_ruta(familia="pinon", material="AISI 304", dientes_z=18,
                        paso_cadena_mm=12.70, ancho_mm=20)
    assert r.operaciones
    assert "talladora" in [o.tipo_maquina for o in r.operaciones]
    assert r.minutos_unitario > 0


def test_tambien_se_deduce_desde_el_modulo():
    r = mz.generar_ruta(familia="corona", material="F-125", dientes_z=40, modulo=4)
    assert r.operaciones
    assert r.minutos_unitario > 0


def test_el_rectificado_de_un_eje_largo_es_lento_pero_no_absurdo():
    """ø100 × 1885: horas, no minutos, pero tampoco una jornada entera."""
    t = mz.tiempo_rectificado(100, 1885)
    assert 60 < t < 180
