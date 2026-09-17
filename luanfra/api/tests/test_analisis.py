from datetime import date

import pytest

from app.servicios import analisis as an


# --- Dispersión de precios -------------------------------------------------

def test_pocas_ofertas_no_dan_conclusion():
    assert an.analizar_dispersion("X", [100, 110]) is None


def test_precio_estable_no_genera_alarma():
    d = an.analizar_dispersion("EJE-1", [1000, 1020, 990, 1010])
    assert d.gravedad == "baja"
    assert d.perdida_estimada < 60


def test_detecta_una_dispersion_grave():
    d = an.analizar_dispersion("PIN-18", [800, 1500, 900, 1600, 850])
    assert d.gravedad == "alta"
    assert d.perdida_estimada > 0
    assert "diferencia" in d.motivo


def test_la_perdida_se_mide_contra_la_mediana_no_contra_el_maximo():
    """Un caso raro carísimo no debe inflar la cifra hasta volverla inútil."""
    d = an.analizar_dispersion("X", [100, 100, 100, 100, 5000])
    assert d.mediana == 100
    assert d.perdida_estimada == 0        # nada por debajo de la mediana


def test_solo_cuenta_lo_ofertado_por_debajo():
    d = an.analizar_dispersion("X", [50, 100, 100, 100, 150])
    assert d.perdida_estimada == 50


def test_ignora_precios_invalidos():
    d = an.analizar_dispersion("X", [100, 0, None, 120, 110])
    assert d.veces == 3


# --- Seguimiento de ofertas ------------------------------------------------

def test_no_se_insiste_el_primer_dia():
    p, accion = an.prioridad_seguimiento(10_000, 2)
    assert "pronto" in accion
    assert p < 0.3


def test_la_ventana_buena_es_entre_la_segunda_y_la_cuarta_semana():
    pronto, _ = an.prioridad_seguimiento(10_000, 2)
    bueno,  _ = an.prioridad_seguimiento(10_000, 20)
    frio,   _ = an.prioridad_seguimiento(10_000, 60)
    tarde,  _ = an.prioridad_seguimiento(10_000, 200)
    assert bueno > frio > tarde
    assert bueno > pronto


def test_una_oferta_caducada_se_da_por_perdida():
    _, accion = an.prioridad_seguimiento(5_000, 200)
    assert "perdida" in accion


def test_a_igual_antiguedad_manda_el_importe():
    grande, _ = an.prioridad_seguimiento(20_000, 20)
    pequena, _ = an.prioridad_seguimiento(500, 20)
    assert grande > pequena


def test_un_cliente_que_suele_aceptar_sube_de_prioridad():
    bueno, _ = an.prioridad_seguimiento(5_000, 20, tasa_exito_cliente=0.9)
    malo,  _ = an.prioridad_seguimiento(5_000, 20, tasa_exito_cliente=0.1)
    assert bueno > malo


def test_la_lista_sale_ordenada_por_prioridad():
    hoy = date(2026, 9, 9)
    r = an.ordenar_seguimiento([
        {"id": 1, "cliente": "A", "importe": 500,    "fecha": date(2026, 8, 20)},
        {"id": 2, "cliente": "B", "importe": 18_000, "fecha": date(2026, 8, 20)},
        {"id": 3, "cliente": "C", "importe": 9_000,  "fecha": date(2026, 9, 8)},
    ], hoy=hoy)
    assert [s.oferta_id for s in r][0] == 2
    assert r == sorted(r, key=lambda s: -s.prioridad)


# --- Riesgo de retraso -----------------------------------------------------

HOY = date(2026, 9, 9)          # miércoles


def test_una_orden_pasada_de_fecha_esta_vencida():
    r = an.clasificar_riesgo(date(2026, 9, 1), 10, hoy=HOY)
    assert r.estado == "vencida"
    assert r.dias < 0
    assert "Vencida" in r.mensaje


def test_no_cabe_el_trabajo_en_el_tiempo_que_queda():
    r = an.clasificar_riesgo(date(2026, 9, 11), 40, hoy=HOY)   # 2 días, 16 h
    assert r.estado == "critica"
    assert "solo caben" in r.mensaje


def test_llega_pero_sin_margen():
    r = an.clasificar_riesgo(date(2026, 9, 16), 35, hoy=HOY)   # 5 días, 40 h
    assert r.estado == "ajustada"


def test_con_holgura():
    r = an.clasificar_riesgo(date(2026, 10, 9), 20, hoy=HOY)
    assert r.estado == "holgada"


def test_cuenta_dias_laborables_no_naturales():
    """De viernes a lunes hay tres días naturales pero solo uno laborable."""
    viernes = date(2026, 9, 11)
    lunes = date(2026, 9, 14)
    r = an.clasificar_riesgo(lunes, 12, hoy=viernes)
    assert r.dias == 1
    assert r.estado == "critica"


def test_el_resumen_agrega_lo_que_el_erp_no_agrega():
    ordenes = [
        an.clasificar_riesgo(date(2026, 9, 1),  10, hoy=HOY),
        an.clasificar_riesgo(date(2026, 9, 3),  20, hoy=HOY),
        an.clasificar_riesgo(date(2026, 9, 11), 40, hoy=HOY),
        an.clasificar_riesgo(date(2026, 10, 9), 20, hoy=HOY),
    ]
    r = an.resumen_retrasos(ordenes)
    assert r["total"] == 4
    assert r["vencidas"] == 2
    assert r["horas_en_riesgo"] == 70
    assert r["peor_retraso_dias"] < 0


# --- Deriva de cliente -----------------------------------------------------

def test_serie_corta_no_da_conclusion():
    assert an.analizar_deriva("A", [30, 28]) is None


def test_detecta_un_margen_que_se_erosiona():
    d = an.analizar_deriva("Estructuras Murcia", [32, 30, 27, 24, 22])
    assert d.tendencia == "cae"
    assert d.pendiente < 0
    assert "revisar precios" in d.aviso


def test_un_trimestre_malo_aislado_no_es_una_tendencia():
    d = an.analizar_deriva("A", [30, 31, 18, 30, 31])
    assert d.tendencia == "estable"
    assert d.aviso is None


def test_reconoce_una_mejora():
    d = an.analizar_deriva("A", [20, 24, 27, 31])
    assert d.tendencia == "mejora"
    assert d.aviso is None


def test_conserva_la_serie_para_pintarla():
    d = an.analizar_deriva("A", [30, 28, 26])
    assert d.serie == [30.0, 28.0, 26.0]
    assert d.periodos == 3
