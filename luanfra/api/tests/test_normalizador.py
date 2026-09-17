"""
Pruebas del normalizador con descripciones REALES sacadas de las capturas
del QGIS. Si estas pasan, el histórico se puede estructurar.
"""
import pytest

from app.servicios import normalizador as nz


# --- Casos reales del ERP --------------------------------------------------

def test_pinon_con_z_paso_material_y_referencia():
    r = nz.normalizar("PIÑON Z18 08B-1 AISI 304 BI.UNIV.03.007.01")
    assert r.familia == "pinon"
    assert r.dientes_z == 18
    assert r.paso_cadena == "08B"
    assert r.ramales == 1
    assert r.material == "AISI 304"
    assert r.referencia_cliente == "BI.UNIV.03.007.01"
    assert r.confianza > 0.8
    assert not r.necesita_revision


def test_eje_cromado_con_dimensiones_y_plano():
    r = nz.normalizar("EJE CROMADO Ø100X1885 S/PLANO T32-1-1 F114")
    assert r.familia == "eje"
    assert "cromado" in r.tratamientos
    assert r.diametro_mm == 100
    assert r.longitud_mm == 1885
    assert r.material == "F-114"
    assert r.segun_plano is True
    assert r.referencia_cliente == "T32-1-1"


def test_apoyo_de_rodillos_sin_material():
    r = nz.normalizar("APOYO DE RODILLOS  BI UNIV.02.004.01")
    assert r.familia == "apoyo_rodillos"
    assert r.material is None
    assert "sin material identificable" in r.dudoso
    assert r.necesita_revision


def test_referencia_alfanumerica_de_cliente():
    r = nz.normalizar("PIÑON Z30 F-125 7SF889P018")
    assert r.referencia_cliente == "7SF889P018"
    assert r.material == "F-125"
    assert r.dientes_z == 30


# --- Diámetros y dimensiones ----------------------------------------------

@pytest.mark.parametrize("texto,diam,lon", [
    ("EJE Ø50X300 F-114",       50, 300),
    ("EJE Ø 50 X 300 F-114",    50, 300),
    ("EJE DIAMETRO 50X300",     50, 300),
    ("EJE DIAM. 50 F-114",      50, None),
    ("EJE ø45x1200",            45, 1200),
])
def test_formatos_de_diametro(texto, diam, lon):
    r = nz.normalizar(texto)
    assert r.diametro_mm == diam
    assert r.longitud_mm == lon


def test_tres_dimensiones():
    r = nz.normalizar("PLETINA 200X100X20 ST52")
    assert (r.diametro_mm, r.longitud_mm, r.ancho_mm) == (200, 100, 20)


def test_decimales_con_coma():
    r = nz.normalizar("CASQUILLO Ø19,05 BRONCE")
    assert r.diametro_mm == 19.05


# --- Materiales ------------------------------------------------------------

@pytest.mark.parametrize("texto,esperado", [
    ("EJE F114",        "F-114"),
    ("EJE F-114",       "F-114"),
    ("EJE C45",         "F-114"),
    ("PIÑON AISI304",   "AISI 304"),
    ("PIÑON INOX 316",  "AISI 316"),
    ("SOPORTE ST52",    "ST-52"),
    ("SOPORTE S355",    "ST-52"),
    ("MATRIZ 1.2379",   "1.2379"),
    ("EJE 42CRMO4",     "F-125"),
])
def test_alias_de_material(texto, esperado):
    assert nz.normalizar(texto).material == esperado


# --- Familia ---------------------------------------------------------------

@pytest.mark.parametrize("texto,familia", [
    ("PIÑON DOBLE Z14 19,05", "pinon_doble"),
    ("CORONA Z90 F-125",      "corona"),
    ("CREMALLERA M4 1000",    "cremallera"),
    ("CASQUILLO Ø40 BRONCE",  "casquillo"),
    ("BRIDA Ø200 AISI 316",   "brida"),
    ("HUSILLO TR40X7",        "husillo"),
])
def test_reconoce_familias(texto, familia):
    assert nz.normalizar(texto).familia == familia


def test_pinon_doble_tiene_prioridad_sobre_pinon():
    assert nz.normalizar("PIÑON DOBLE Z14").familia == "pinon_doble"


# --- Robustez --------------------------------------------------------------

def test_descripcion_vacia_no_revienta():
    r = nz.normalizar("")
    assert r.familia is None
    assert r.confianza == 0.0
    assert r.necesita_revision


def test_descripcion_ininteligible_se_marca():
    r = nz.normalizar("VARIOS SEGUN PRESUPUESTO")
    assert r.necesita_revision
    assert "no se reconoce la familia de la pieza" in r.dudoso


def test_acentos_y_mayusculas_indiferentes():
    a = nz.normalizar("piñón z18 aisi 304")
    b = nz.normalizar("PIÑON Z18 AISI 304")
    assert a.familia == b.familia == "pinon"
    assert a.dientes_z == b.dientes_z == 18


def test_z_fuera_de_rango_se_descarta():
    assert nz.normalizar("PIÑON Z999").dientes_z is None


def test_un_material_no_se_confunde_con_referencia():
    r = nz.normalizar("EJE 1.2379 Ø60")
    assert r.material == "1.2379"
    assert r.referencia_cliente is None


def test_la_confianza_sube_con_los_campos_resueltos():
    poca = nz.normalizar("PIEZA VARIA")
    mucha = nz.normalizar("PIÑON Z18 08B-1 AISI 304 BI.UNIV.03.007.01")
    assert mucha.confianza > poca.confianza


# --- Lote ------------------------------------------------------------------

def test_informe_de_lote():
    lote = nz.normalizar_lote([
        "PIÑON Z18 08B-1 AISI 304 BI.UNIV.03.007.01",
        "EJE CROMADO Ø100X1885 S/PLANO T32-1-1 F114",
        "APOYO DE RODILLOS  BI UNIV.02.004.01",
        "VARIOS",
    ])
    inf = nz.informe_de_lote(lote)
    assert inf["total"] == 4
    assert inf["con_familia"] == 3
    assert inf["con_material"] == 2
    assert inf["necesitan_revision"] >= 2
    assert "pinon" in inf["familias"]


# --- Separadores en el material (fallo encontrado con datos reales) ---------

@pytest.mark.parametrize("texto", [
    "EJE Ø35 AISI-316", "EJE Ø35 AISI 316", "EJE Ø35 AISI316",
    "EJE Ø35 aisi-316", "EJE Ø35 INOX-316",
])
def test_el_material_se_reconoce_con_cualquier_separador(texto):
    assert nz.normalizar(texto).material == "AISI 316"


@pytest.mark.parametrize("texto,esperado", [
    ("SOPORTE ST-52", "ST-52"), ("SOPORTE ST 52", "ST-52"), ("SOPORTE ST52", "ST-52"),
    ("EJE F 114", "F-114"), ("EJE F-114", "F-114"), ("EJE F114", "F-114"),
])
def test_separadores_en_otros_materiales(texto, esperado):
    assert nz.normalizar(texto).material == esperado


# --- Paso escrito como número (formato del export del ERP) ------------------

@pytest.mark.parametrize("texto,esperado", [
    ("Piñon Especial Z18 paso 12.7",   "12.7 mm"),
    ("Piñon Doble Z25 paso 19,05",     "19.05 mm"),
    ("Engranaje Recto Z40 PASO 25.4",  "25.4 mm"),
])
def test_reconoce_el_paso_en_milimetros(texto, esperado):
    assert nz.normalizar(texto).paso_cadena == esperado


def test_la_designacion_de_norma_sigue_teniendo_prioridad():
    assert nz.normalizar("PIÑON Z18 08B-1 paso 12.7").paso_cadena == "08B"


def test_un_paso_absurdo_se_ignora():
    assert nz.normalizar("PIEZA PASO 900").paso_cadena is None
