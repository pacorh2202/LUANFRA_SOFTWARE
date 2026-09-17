"""Pruebas del motor de similares, con piezas reales del histórico."""
import pytest

from app.servicios import normalizador as nz
from app.servicios import similares as sim

N = nz.normalizar


# --- Barreras duras --------------------------------------------------------

def test_familias_distintas_no_son_comparables():
    s, motivos = sim.comparar(N("PIÑON Z18 AISI 304"), N("CASQUILLO Ø40 AISI 304"))
    assert s == 0.0
    assert "familias distintas" in motivos


def test_familias_vecinas_comparan_con_penalizacion():
    s, motivos = sim.comparar(N("EJE Ø50X300 F-114"), N("VASTAGO Ø50X300 F-114"))
    assert 0.6 < s < 1.0
    assert "familia parecida, no igual" in motivos


# --- Escala de parecido ----------------------------------------------------

def test_pieza_identica_da_parecido_maximo():
    a = N("PIÑON Z18 08B-1 AISI 304")
    s, _ = sim.comparar(a, N("PIÑON Z18 08B-1 AISI 304"))
    assert s > 0.98


def test_mismo_pinon_en_otro_material_baja_bastante():
    s, _ = sim.comparar(N("PIÑON Z18 08B-1 AISI 304"), N("PIÑON Z18 08B-1 F-114"))
    assert 0.55 < s < 0.85


def test_el_diametro_manda_en_piezas_de_revolucion():
    cerca, _ = sim.comparar(N("EJE Ø100X1000 F-114"), N("EJE Ø102X1000 F-114"))
    lejos, _ = sim.comparar(N("EJE Ø100X1000 F-114"), N("EJE Ø300X1000 F-114"))
    assert cerca > 0.95
    assert lejos < cerca


def test_el_cromado_cuenta_como_diferencia():
    con, _ = sim.comparar(N("EJE CROMADO Ø100X1885 F-114"), N("EJE CROMADO Ø100X1885 F-114"))
    sin, _ = sim.comparar(N("EJE CROMADO Ø100X1885 F-114"), N("EJE Ø100X1885 F-114"))
    assert con > sin


def test_paso_de_cadena_distinto_penaliza():
    igual, _ = sim.comparar(N("PIÑON Z18 08B-1 F-114"), N("PIÑON Z18 08B-1 F-114"))
    otro, _  = sim.comparar(N("PIÑON Z18 08B-1 F-114"), N("PIÑON Z18 16B-1 F-114"))
    assert igual > otro


# --- Búsqueda --------------------------------------------------------------

HISTORICO = [
    N("PIÑON Z18 08B-1 AISI 304 BI.UNIV.03.007.01"),
    N("PIÑON Z18 08B-1 AISI 304 BI.UNIV.40.003.01"),
    N("PIÑON Z20 08B-1 AISI 304"),
    N("PIÑON Z18 08B-1 F-114"),
    N("PIÑON Z45 16B-2 F-125"),
    N("EJE CROMADO Ø100X1885 F-114"),
    N("EJE Ø80X1200 F-114"),
    N("CASQUILLO Ø40 BRONCE"),
    N("BRIDA Ø200 AISI 316"),
]


def test_encuentra_las_repetidas_primero():
    r = sim.buscar(N("PIÑON Z18 08B-1 AISI 304 BI.UNIV.03.007.01"), HISTORICO)
    assert r
    assert r[0].similitud > 0.95
    assert r[0].pieza.dientes_z == 18
    assert r == sorted(r, key=lambda x: -x.similitud)


def test_respeta_el_tope_de_resultados():
    assert len(sim.buscar(N("PIÑON Z18 08B-1 AISI 304"), HISTORICO, minimo=0.1, tope=3)) == 3


def test_pieza_sin_apoyo_devuelve_lista_vacia():
    assert sim.buscar(N("CREMALLERA M6 2000 F-125"), HISTORICO) == []


def test_nunca_cruza_familias_en_la_busqueda():
    for c in sim.buscar(N("EJE Ø90X1500 F-114"), HISTORICO, minimo=0.3):
        assert c.pieza.familia in {"eje", "vastago", "husillo"}


# --- Decisión de vía -------------------------------------------------------

def test_pieza_repetida_va_por_la_via_a():
    obj = N("PIÑON Z18 08B-1 AISI 304 BI.UNIV.03.007.01")
    via, conf = sim.decidir_via(obj, sim.buscar(obj, HISTORICO))
    assert via == "A_repetida"
    assert conf > 0.75


def test_pieza_parecida_va_por_la_via_b():
    obj = N("PIÑON Z22 08B-1 AISI 304")
    via, conf = sim.decidir_via(obj, sim.buscar(obj, HISTORICO))
    assert via == "B_similar"
    assert 0.4 < conf < 0.95


def test_pieza_nueva_va_por_la_via_c_y_con_poca_confianza():
    obj = N("CREMALLERA M6 2000 F-125")
    via, conf = sim.decidir_via(obj, sim.buscar(obj, HISTORICO))
    assert via == "C_nueva"
    assert conf < 0.4


def test_descripcion_ininteligible_va_a_la_via_c():
    obj = N("VARIOS SEGUN PRESUPUESTO")
    via, _ = sim.decidir_via(obj, sim.buscar(obj, HISTORICO))
    assert via == "C_nueva"


# --- Explicaciones ---------------------------------------------------------

def test_las_explicaciones_son_legibles():
    obj = N("PIÑON Z18 08B-1 F-114")
    frases = sim.explicar(sim.buscar(obj, HISTORICO, minimo=0.5))
    assert frases
    assert all("% de parecido" in f for f in frases)
    assert any("material" in f or "dientes" in f or "paso" in f or "todo" in f for f in frases)


# --- Grupos de material ----------------------------------------------------

def test_materiales_del_mismo_grupo_penalizan_menos_que_de_grupos_distintos():
    mismo, _   = sim.comparar(N("EJE Ø50X300 F-114"), N("EJE Ø50X300 ST52"))
    distinto, _ = sim.comparar(N("EJE Ø50X300 F-114"), N("EJE Ø50X300 BRONCE"))
    identico, _ = sim.comparar(N("EJE Ø50X300 F-114"), N("EJE Ø50X300 F-114"))
    assert identico > mismo > distinto


def test_el_motivo_explica_el_grupo():
    _, motivos = sim.comparar(N("EJE Ø50 F-114"), N("EJE Ø50 ST52"))
    assert any("mismo grupo" in m for m in motivos)


def test_inox_frente_a_acero_al_carbono_es_cambio_de_grupo():
    _, motivos = sim.comparar(N("PIÑON Z18 AISI 304"), N("PIÑON Z18 F-114"))
    assert any("material distinto" in m for m in motivos)


def test_dos_ejes_iguales_con_material_distinto_no_dan_parecido_maximo():
    """
    Fallo encontrado probando contra la base: 'AISI-316' con guion no se
    reconocía como material y el motor devolvía 100% de parecido frente a F-114.
    """
    s, motivos = sim.comparar(
        N("Eje de transmisión ø35 F-114"), N("Eje de transmisión ø35 AISI-316"))
    assert s < 0.9
    assert any("material" in m for m in motivos)


def test_dos_pinones_con_paso_distinto_no_son_la_misma_pieza():
    """
    Fallo encontrado con los datos reales: 'Z18 paso 12.7' y 'Z18 paso 25.4'
    daban 100% de parecido porque el paso en milímetros no se reconocía.
    """
    s, motivos = sim.comparar(N("Piñon Especial Z18 paso 12.7"),
                              N("Piñon 2 Cubos Z18 paso 25.4"))
    assert s < 0.85
    assert any("paso" in m for m in motivos)


def test_dos_pinones_con_el_mismo_paso_si_lo_son():
    s, _ = sim.comparar(N("Piñon Especial Z18 paso 12.7"),
                        N("Piñon Especial Z18 paso 12.7"))
    assert s > 0.98
