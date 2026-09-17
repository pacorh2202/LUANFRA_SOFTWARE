"""
Pruebas del explorador del ERP.

La parte que toca la red es deliberadamente fina; todo lo demás son funciones
puras que se comprueban aquí sin necesidad de un SQL Server.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import explorar_erp as ex  # noqa: E402


def col(nombre, tipo="varchar"):
    return {"nombre": nombre, "tipo": tipo, "longitud": 50,
            "precision": 0, "escala": 0, "nulo": True}


# --- Puerta de seguridad: lo más importante del script ---------------------

@pytest.mark.parametrize("sql", [
    "SELECT * FROM CLIENTES",
    "select top 10 * from dbo.FACTURAS",
    "WITH x AS (SELECT 1 AS a) SELECT * FROM x",
    "SET NOCOUNT ON",
    "SET LOCK_TIMEOUT 5000",
    "-- comentario\nSELECT 1",
    "/* bloque */ SELECT 1",
])
def test_permite_solo_lectura(sql):
    assert ex._solo_lectura(sql) == sql


@pytest.mark.parametrize("sql", [
    "DELETE FROM CLIENTES",
    "UPDATE FACTURAS SET TOTAL = 0",
    "INSERT INTO X VALUES (1)",
    "DROP TABLE CLIENTES",
    "TRUNCATE TABLE PARTES",
    "EXEC sp_quien_sea",
    "ALTER TABLE X ADD Y INT",
    "CREATE INDEX ix ON t(c)",
    "SELECT 1; DELETE FROM CLIENTES",          # sentencia encadenada
    "-- SELECT\nDELETE FROM CLIENTES",          # escritura camuflada tras comentario
    "/* SELECT */ UPDATE t SET a=1",
])
def test_rechaza_cualquier_escritura(sql):
    with pytest.raises(ValueError):
        ex._solo_lectura(sql)


# --- Clasificación de tablas ----------------------------------------------

def test_reconoce_presupuestos():
    cols = [col("NUMPPTO", "int"), col("FECHA", "datetime"),
            col("CODCLI"), col("TOTAL", "decimal")]
    familia, punt = ex.clasificar_tabla("PRESUPUESTOS", cols, 18000)
    assert familia == "presupuestos"
    assert punt >= 50


def test_reconoce_partes_de_trabajo():
    cols = [col("NUMOF", "int"), col("CODOPERARIO"), col("CODMAQUINA"),
            col("INICIO", "datetime"), col("MINUTOS", "decimal")]
    familia, _ = ex.clasificar_tabla("PARTES", cols, 400000)
    assert familia == "partes_trabajo"


def test_penaliza_tablas_de_ruido():
    cols = [col("ID", "int"), col("VALOR")]
    _, punt_log = ex.clasificar_tabla("W_LOG_ACCESOS", cols, 90000)
    _, punt_tmp = ex.clasificar_tabla("TMP_CALCULO", cols, 0)
    assert punt_log == 0
    assert punt_tmp == 0


def test_una_tabla_vacia_puntua_menos_que_la_misma_con_datos():
    cols = [col("NUMFAC", "int"), col("FECHA", "datetime"), col("TOTAL", "decimal")]
    _, con = ex.clasificar_tabla("FACTURAS", cols, 30000)
    _, sin = ex.clasificar_tabla("FACTURAS", cols, 0)
    assert con > sin


def test_detecta_tablas_de_lineas():
    assert ex.es_tabla_de_lineas("PRESUPUESTOS_LIN")
    assert ex.es_tabla_de_lineas("FAC_DETALLE")
    assert not ex.es_tabla_de_lineas("CLIENTES")


def test_normalizar_quita_acentos():
    assert ex.normalizar("ARTÍCULOS_Ñ") == "articulos_n"


def test_columnas_por_tipo():
    cols = [col("A", "datetime"), col("B", "varchar"), col("C", "decimal")]
    assert ex.columnas_por_tipo(cols, ex.TIPOS_FECHA) == ["A"]
    assert ex.columnas_por_tipo(cols, ex.TIPOS_NUM) == ["C"]


def test_avisos_de_calidad():
    t = {"filas": 0, "clave_primaria": [], "columnas": [col("A")]}
    avisos = ex.resumen_calidad(t)
    assert "vacía" in avisos
    assert "sin clave primaria" in avisos
    assert "sin columnas de fecha" in avisos


# --- Informe ---------------------------------------------------------------

def test_el_informe_se_genera_completo():
    datos = ex.esquema_simulado()
    md = ex.construir_informe(datos)
    for esperado in ["# Exploración del ERP QGIS", "## Servidor", "## Resumen",
                     "## Cobertura temporal", "## Relaciones detectadas",
                     "PRESUPUESTOS", "PARTES", "Siguiente paso"]:
        assert esperado in md
    assert "None" not in md          # ningún valor sin formatear
    assert "{" not in md             # ninguna plantilla sin sustituir


def test_el_informe_aguanta_datos_incompletos():
    """Un ERP antiguo puede no tener claves ajenas ni fechas legibles."""
    datos = {
        "generado": "01/01/2026 10:00",
        "servidor": {},
        "tablas": [{"esquema": "dbo", "nombre": "X", "filas": 0, "columnas": [],
                    "clave_primaria": [], "familia": None, "puntuacion": 0}],
        "relaciones": [],
    }
    md = ex.construir_informe(datos)
    assert "No hay claves ajenas declaradas" in md
    assert "Nada encontrado" in md


def test_avisa_de_version_fuera_de_soporte():
    datos = ex.esquema_simulado()
    datos["servidor"]["fuera_de_soporte"] = True
    assert "fuera de soporte" in ex.construir_informe(datos)


def test_el_informe_incluye_la_busqueda():
    datos = ex.esquema_simulado()
    datos["busqueda"] = {"valor": "4237,50", "resultados": [
        {"tabla": "dbo.PRESUPUESTOS", "columna": "TOTAL", "coincidencias": 1}]}
    md = ex.construir_informe(datos)
    assert "4237,50" in md and "PRESUPUESTOS" in md


# --- Ejecución completa en modo simulado -----------------------------------

def test_modo_simulado_de_principio_a_fin(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ex, "RAIZ_SALIDA", tmp_path / "salida/erp")

    assert ex.main(["--simular"]) == 0

    esquema = tmp_path / "salida/erp/esquema.json"
    informe = tmp_path / "salida/erp/informe.md"
    assert esquema.exists() and informe.exists()

    datos = json.loads(esquema.read_text(encoding="utf-8"))
    assert len(datos["tablas"]) == 13
    familias = {t["familia"] for t in datos["tablas"] if t["familia"]}
    assert {"presupuestos", "facturas", "partes_trabajo", "articulos"} <= familias
    assert informe.read_text(encoding="utf-8").startswith("# Exploración")


# --- Formato de números ----------------------------------------------------

def test_separador_de_miles():
    assert ex.mil(128944) == "128.944"
    assert ex.mil(0) == "0"
    assert ex.mil(None) == "—"


def test_las_comas_del_texto_sobreviven_al_formato():
    """
    Fallo real detectado: el separador de miles se aplicaba a la línea entera
    y convertía las comas de las notas en puntos.
    """
    datos = ex.esquema_simulado()
    md = ex.construir_informe(datos)
    assert "líneas de detalle, sin columnas de fecha" in md
    assert "líneas de detalle. sin" not in md
    assert "128.944" in md          # el número sí lleva punto
