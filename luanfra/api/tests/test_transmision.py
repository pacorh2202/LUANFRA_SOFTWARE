"""
Pruebas del conocimiento de elementos de transmisión.

Es el grueso de lo que hace Luanfra, y una descripción de piñón lleva mucha
más información de la que parece: cinco datos donde parecía haber uno.
"""
import pytest

from app.servicios import normalizador as nz

N = nz.normalizar


# --- Paso de cadena: las tres formas de escribir lo mismo ------------------

@pytest.mark.parametrize("texto,desig,mm,ramales", [
    ("PIÑON Z18 08B-1",      "08B",    12.70, 1),
    ("PIÑON Z18 08B-2",      "08B",    12.70, 2),
    ("PIÑON Z18 08B-3",      "08B",    12.70, 3),
    ("PIÑON Z25 16B-1",      "16B",    25.40, 1),
    ("PIÑON Z20 06B",        "06B",     9.525, None),
    ("PIÑON Z25 ASA 40-2",   "ASA 40", 12.70, 2),
    ("PIÑON Z30 ANSI 60",    "ASA 60", 19.05, None),
    ('PIÑON Z14 ISO 3/4"',   'ISO 3/4"', 19.05, None),
    ("PIÑON Z18 PASO 12,7",  "12.7 mm", 12.70, None),
])
def test_reconoce_el_paso_escrito_de_cualquier_forma(texto, desig, mm, ramales):
    r = N(texto)
    assert r.paso_cadena == desig
    assert r.paso_mm == pytest.approx(mm, abs=0.02)
    assert r.ramales == ramales


def test_traduce_los_ramales_a_palabras():
    assert N("PIÑON Z18 08B-2").ramales_txt == "doble"
    assert N("PIÑON Z18 08B-3").ramales_txt == "triple"


def test_avisa_si_no_dice_si_es_simple_o_doble():
    assert any("simple, doble" in d for d in N("PIÑON Z18 08B F-114").dudoso)


# --- Geometría deducida ----------------------------------------------------

def test_el_primitivo_sale_del_paso_y_los_dientes():
    """Dp = p / sen(180°/Z). Comprobado contra la pantalla del ERP."""
    assert N("PIÑON Z14 PASO 19,05").diametro_primitivo == pytest.approx(85.6, abs=0.1)
    assert N("PIÑON Z18 08B-1").diametro_primitivo == pytest.approx(73.14, abs=0.05)


def test_el_exterior_es_mayor_que_el_primitivo():
    r = N("PIÑON Z18 08B-1")
    assert r.diametro_exterior > r.diametro_primitivo


def test_en_un_engranaje_el_primitivo_sale_del_modulo():
    r = N("ENGRANAJE RECTO Z40 MODULO 4")
    assert r.modulo == 4
    assert r.diametro_primitivo == 160        # m · Z
    assert r.diametro_exterior == 168         # m · (Z+2)


def test_en_una_polea_dentada_el_primitivo_sale_del_paso_de_la_correa():
    r = N("POLEA HTD 8M Z32")
    assert r.perfil_correa == "HTD 8M"
    assert r.diametro_primitivo == pytest.approx(81.5, abs=0.5)   # p·Z/π


def test_el_diametro_de_mecanizado_de_una_dentada_es_el_exterior():
    """Nunca el del taladro ni el del cubo: es el que hay que tornear."""
    r = N("PIÑON Z18 08B-1 CUBO Ø45 TALADRO Ø30")
    assert r.diametro_mm == r.diametro_exterior
    assert r.diametro_mm > 70


# --- Módulo frente a rosca métrica ----------------------------------------

@pytest.mark.parametrize("texto,mod", [
    ("ENGRANAJE Z40 MODULO 4", 4.0), ("ENGRANAJE Z40 MOD. 2,5", 2.5),
    ("ENGRANAJE Z40 MÓD 3", 3.0),    ("ENGRANAJE Z40 m=6", 6.0),
])
def test_reconoce_el_modulo(texto, mod):
    assert N(texto).modulo == mod


def test_una_rosca_metrica_no_es_un_modulo():
    """M20x1,5 es rosca. Confundirla con módulo 20 sería absurdo."""
    assert N("EJE Ø50 ROSCA M20x1,5 F-114").modulo is None


# --- Cotas etiquetadas -----------------------------------------------------

def test_separa_los_cuatro_diametros_de_un_pinon():
    r = N("PIÑON Z18 08B-2 CUBO Ø45 ANCHO CUBO 25 TALADRO Ø30")
    assert r.diametro_cubo == 45
    assert r.ancho_cubo == 25
    assert r.diametro_taladro == 30
    assert r.diametro_primitivo == pytest.approx(73.14, abs=0.05)


def test_el_chavetero_no_se_confunde_con_las_cotas():
    """
    Fallo real: el 8x3,3 de un chavetero se tomaba por largo y ancho de pieza.
    """
    r = N("PIÑON Z18 08B-1 CHAVETERO 8x3,3 CUBO Ø45")
    assert r.chavetero == "8x3.3"
    assert r.longitud_mm != 8
    assert r.ancho_mm != 3.3


def test_cuenta_los_prisioneros():
    assert N("PIÑON Z18 08B-1 2 PRISIONEROS").prisioneros == 2
    assert N("PIÑON Z18 08B-1 CON PRISIONERO").prisioneros == 1


def test_reconoce_un_chavetero_sin_medida():
    assert N("PIÑON Z18 08B-1 CON CHAVETERO DIN 6885").chavetero == "sí, sin medida"


# --- Casquillo cónico ------------------------------------------------------

def test_reconoce_el_casquillo_conico():
    assert N("PIÑON Z25 16B-1 TAPER LOCK 2517").taper_lock == "2517"
    assert N("POLEA SPB CASQUILLO CONICO 3020").taper_lock == "3020"


def test_un_numero_de_cuatro_cifras_suelto_no_es_un_taper():
    assert N("PIÑON Z18 08B-1 PEDIDO 2517").taper_lock is None


# --- Dentado helicoidal ----------------------------------------------------

def test_reconoce_el_dentado_helicoidal_con_su_angulo_y_sentido():
    r = N("CORONA HELICOIDAL Z90 MOD 3 HELICE 15° DCHA")
    assert r.helicoidal
    assert r.angulo_helice == 15
    assert r.sentido_helice == "derecha"


def test_un_dentado_recto_no_es_helicoidal():
    assert not N("ENGRANAJE RECTO Z40 MODULO 4").helicoidal


def test_reconoce_el_angulo_de_presion():
    assert N("ENGRANAJE Z40 MODULO 4 ANGULO DE PRESION 20°").angulo_presion == 20
    assert N("ENGRANAJE Z40 MODULO 4 14,5°").angulo_presion == 14.5


# --- Poleas ----------------------------------------------------------------

@pytest.mark.parametrize("texto,perfil", [
    ("POLEA SPB 3 CANALES", "SPB"), ("POLEA SPZ 2 GARGANTAS", "SPZ"),
    ("POLEA HTD 14M Z44", "HTD 14M"), ("POLEA AT10 Z30", "AT10"),
])
def test_reconoce_el_perfil_de_correa(texto, perfil):
    assert N(texto).perfil_correa == perfil


def test_cuenta_los_canales():
    assert N("POLEA SPB 3 CANALES").canales == 3
    assert N("POLEA SPA 5 GARGANTAS").canales == 5


def test_una_referencia_de_cliente_no_es_un_perfil_de_correa():
    """Fallo real: 'T32-1-1' se tomaba por el perfil T32, que no existe."""
    r = N("EJE CROMADO Ø100X1885 S/PLANO T32-1-1 F114")
    assert r.perfil_correa is None
    assert r.referencia_cliente == "T32-1-1"


def test_avisa_de_una_polea_sin_perfil():
    assert any("perfil de correa" in d for d in N("POLEA Ø250 FUNDICION").dudoso)


# --- Tratamiento del dentado ----------------------------------------------

def test_distingue_el_temple_del_dentado():
    assert N("ENGRANAJE Z40 MOD 4 DENTADO TEMPLADO").dentado_templado
    assert not N("ENGRANAJE Z40 MOD 4 F-125").dentado_templado


# --- Cantidad --------------------------------------------------------------

@pytest.mark.parametrize("texto,n", [
    ("PIÑON Z18 08B-1 CANT: 250 UDS", 250),
    ("PIÑON Z18 08B-1 250 uds", 250),
    ("PIÑON Z18 08B-1 CANTIDAD 30", 30),
    ("PIÑON Z18 08B-1 12 PIEZAS", 12),
    ("PIÑON Z18 08B-1 Nº UDS: 8", 8),
])
def test_reconoce_la_cantidad_escrita_de_varias_formas(texto, n):
    assert N(texto).cantidad == n


def test_una_cota_no_se_confunde_con_la_cantidad():
    assert N("EJE Ø100X1885 F-114").cantidad is None


# --- Normas ----------------------------------------------------------------

def test_reconoce_las_normas_citadas():
    r = N("CORONA Z90 MOD 3 DIN 3962 CALIDAD 8 CHAVETERO DIN 6885")
    assert "DIN 3962" in r.normas
    assert "DIN 6885" in r.normas


# --- Dudas -----------------------------------------------------------------

def test_avisa_de_un_dentado_sin_paso_ni_modulo():
    assert any("paso ni módulo" in d for d in N("PIÑON Z18 F-114").dudoso)


def test_avisa_si_no_hay_forma_de_sujetar_la_pieza():
    assert any("taladro ni casquillo" in d for d in N("PIÑON Z18 08B-1 F-114").dudoso)


def test_una_descripcion_completa_no_deja_dudas():
    r = N("PIÑON Z18 08B-2 AISI 304 CUBO Ø45 ANCHO CUBO 25 TALADRO Ø30 "
          "CHAVETERO 8x3,3 1 PRISIONERO CANT: 250 UDS")
    assert r.dudoso == []
    assert r.confianza > 0.85


# --- Comparación entre piezas de transmisión ------------------------------

from app.servicios import similares as sim   # noqa: E402


def test_mismo_z_distinto_modulo_no_es_la_misma_pieza():
    """Cambia el diámetro, la fresa madre y el tiempo de tallado."""
    s, motivos = sim.comparar(N("CORONA Z90 MODULO 3 F-125"),
                              N("CORONA Z90 MODULO 4 F-125"))
    assert s < 0.85
    assert any("módulo distinto" in m for m in motivos)


def test_mismo_z_mismo_modulo_si_lo_es():
    s, _ = sim.comparar(N("CORONA Z90 MODULO 3 F-125"),
                        N("CORONA Z90 MOD 3 F-125"))
    assert s > 0.95


def test_un_pinon_doble_no_se_compara_con_uno_simple_al_mismo_nivel():
    igual, _  = sim.comparar(N("PIÑON Z18 08B-2 F-114"), N("PIÑON Z18 08B-2 F-114"))
    otro, mot = sim.comparar(N("PIÑON Z18 08B-2 F-114"), N("PIÑON Z18 08B-1 F-114"))
    assert igual > otro
    assert any("ramales distintos" in m for m in mot)
