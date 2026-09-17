"""
Pruebas del sincronizador SIN un SQL Server delante.

Las funciones de lectura se pasan como parámetro, así que aquí se sustituyen
por otras que devuelven datos inventados. Lo que se comprueba es la lógica:
qué modo elegir, qué consulta construir, y qué pasa cuando algo falla.
"""
from datetime import datetime, timedelta

import pytest

from app.servicios import sincronizador as sc

T_GRANDE = sc.TablaSincronizada("partes", "dbo.PARTES", "core.parte_trabajo",
                                "historico", "ID", "INICIO")
T_PEQUENA = sc.TablaSincronizada("maquinas", "dbo.MAQUINAS", "core.centro_trabajo",
                                 "maestros", "CODMAQUINA")
AYER = datetime(2026, 9, 8, 22, 0)


# --- Elección de modo ------------------------------------------------------

def test_tabla_pequena_siempre_completa():
    assert sc.decidir_modo(T_PEQUENA, 60, AYER) == "completa"


def test_primera_vez_siempre_completa():
    assert sc.decidir_modo(T_GRANDE, 400_000, None) == "completa"


def test_tabla_grande_ya_cargada_va_incremental():
    assert sc.decidir_modo(T_GRANDE, 400_000, AYER) == "incremental"


def test_sin_columna_incremental_no_hay_incremental():
    t = sc.TablaSincronizada("x", "dbo.X", "core.x", "historico", "ID")
    assert sc.decidir_modo(t, 999_999, AYER) == "completa"


# --- Corte con solape ------------------------------------------------------

def test_el_corte_retrocede_para_no_perder_filas():
    corte = sc.corte_incremental(AYER)
    assert corte < AYER
    assert AYER - corte == timedelta(minutes=15)


def test_el_solape_es_configurable():
    assert sc.corte_incremental(AYER, 60) == AYER - timedelta(hours=1)


# --- Consulta --------------------------------------------------------------

def test_la_consulta_es_de_solo_lectura_y_con_nolock():
    sql, _ = sc.construir_consulta(T_GRANDE, "completa")
    assert sql.startswith("SELECT")
    assert "WITH (NOLOCK)" in sql
    for prohibido in ("DELETE", "UPDATE", "INSERT", "DROP"):
        assert prohibido not in sql.upper()


def test_la_consulta_incremental_filtra_por_la_columna_declarada():
    sql, params = sc.construir_consulta(T_GRANDE, "incremental", AYER)
    assert "[INICIO] >=" in sql
    assert params["desde"] == AYER


def test_la_consulta_completa_no_lleva_filtro():
    sql, params = sc.construir_consulta(T_GRANDE, "completa")
    assert "WHERE" not in sql
    assert params == {}


def test_solo_pide_las_columnas_declaradas_si_las_hay():
    t = sc.TablaSincronizada("c", "dbo.C", "core.c", "maestros", "ID",
                             columnas=("ID", "NOMBRE"))
    sql, _ = sc.construir_consulta(t, "completa")
    assert "[ID], [NOMBRE]" in sql
    assert "*" not in sql


# --- Troceado --------------------------------------------------------------

def test_trocea_en_lotes_del_tamano_pedido():
    lotes = list(sc.trocear(list(range(2500)), 1000))
    assert [len(x) for x in lotes] == [1000, 1000, 500]


def test_trocear_lista_vacia_no_produce_lotes():
    assert list(sc.trocear([], 100)) == []


# --- Catálogo --------------------------------------------------------------

def test_el_catalogo_cubre_las_tres_cadencias():
    cadencias = {t.cadencia for t in sc.CATALOGO}
    assert cadencias == {"historico", "maestros", "operativo"}


def test_las_tablas_operativas_son_las_que_alimentan_los_plazos():
    operativas = {t.nombre for t in sc.CATALOGO if t.cadencia == "operativo"}
    assert {"cola", "estados", "ordenes"} <= operativas


def test_ninguna_tabla_del_catalogo_apunta_a_escribir_en_el_erp():
    for t in sc.CATALOGO:
        assert t.origen.startswith("dbo.")
        assert t.destino.startswith(("core.", "ops.", "stage."))


# --- Orquestación con dobles ----------------------------------------------

class SesionFalsa:
    """Sesión mínima: registra lo que se le pide sin tocar ninguna base."""
    def __init__(self, ultima=None):
        self.ultima = ultima
        self.commits = 0
        self.rollbacks = 0
        self.cargas = []

    def execute(self, sql, params=None):
        texto = str(sql)
        self.cargas.append((texto, params))
        return _Resultado(self)

    def commit(self):  self.commits += 1
    def rollback(self): self.rollbacks += 1


class _Resultado:
    def __init__(self, sesion): self.sesion = sesion
    def scalar(self):
        # Devuelve la última carga para ultima_carga_correcta, o un id para insert
        ultimo = self.sesion.cargas[-1][0]
        if "max(inicio)" in ultimo:
            return self.sesion.ultima
        return 1
    def mappings(self): return self
    def all(self): return []


def _leer(filas):
    return lambda sql, params: list(filas)


def test_sincroniza_una_cadencia_completa():
    sesion = SesionFalsa()
    escritas = []

    def escribir(s, tabla, lote):
        escritas.append((tabla.nombre, len(lote)))
        return len(lote)

    r = sc.sincronizar_cadencia(
        sesion, "operativo",
        leer_erp=_leer([{"ID": i} for i in range(1500)]),
        contar_erp=lambda origen: 1500,
        escribir=escribir)

    assert r.ok
    assert len(r.cargas) == 3                       # ordenes, cola, estados
    assert all(c.leidas == 1500 for c in r.cargas)
    assert all(c.escritas == 1500 for c in r.cargas)
    assert [n for n, _ in escritas].count("cola") == 2   # troceado en 1000 + 500


def test_un_fallo_en_una_tabla_no_tumba_las_demas():
    sesion = SesionFalsa()

    def escribir(s, tabla, lote):
        if tabla.nombre == "cola":
            raise RuntimeError("se cayó la red")
        return len(lote)

    r = sc.sincronizar_cadencia(
        sesion, "operativo",
        leer_erp=_leer([{"ID": 1}]),
        contar_erp=lambda o: 10,
        escribir=escribir)

    assert not r.ok
    fallidas = [c for c in r.cargas if not c.ok]
    assert len(fallidas) == 1
    assert fallidas[0].tabla == "cola"
    assert "se cayó la red" in fallidas[0].error
    assert sum(1 for c in r.cargas if c.ok) == 2
    assert sesion.rollbacks >= 1


def test_el_resumen_es_legible():
    sesion = SesionFalsa()
    r = sc.sincronizar_cadencia(
        sesion, "maestros",
        leer_erp=_leer([{"ID": 1}, {"ID": 2}]),
        contar_erp=lambda o: 2,
        escribir=lambda s, t, l: len(l))
    res = r.resumen()
    assert res["cadencia"] == "maestros"
    assert res["con_error"] == 0
    assert res["filas_escritas"] == 10            # 5 tablas × 2 filas
    assert isinstance(res["segundos"], float)


def test_cada_carga_deja_rastro_en_la_bitacora():
    sesion = SesionFalsa()
    sc.sincronizar_cadencia(
        sesion, "operativo",
        leer_erp=_leer([{"ID": 1}]),
        contar_erp=lambda o: 5,
        escribir=lambda s, t, l: len(l))
    consultas = " ".join(c[0] for c in sesion.cargas)
    assert "INSERT INTO stage.carga" in consultas
    assert "UPDATE stage.carga" in consultas
