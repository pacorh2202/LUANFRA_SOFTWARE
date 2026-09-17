"""Casos industriales sintéticos; nunca históricos ni tarifas de clientes."""
import csv
import hashlib
import io
import json
from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.config import ajustes
from app.main import app
from app.servicios import motor_coste as mc, plazos, mecanizado
from app.servicios.importacion_ordenes import CAMPOS, diagnosticar


@pytest.fixture
def cliente(monkeypatch):
    clave = "clave-sintetica-solo-pruebas-1234567890"
    monkeypatch.setattr(ajustes, "acceso_claves_json", json.dumps({
        hashlib.sha256(clave.encode()).hexdigest(): "revisor_prueba"}))
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {clave}"
        yield c


def entrada(**kw):
    campos = dict(cantidad=1, peso_bruto_kg=D(1), precio_kg=D(50), merma_pct=D(0),
                  operaciones=[mc.Operacion("M", D(0), D(50), D(1))],
                  indirectos_pct=D(0), margen_pct=D(30))
    campos.update(kw)
    return mc.EntradaCoste(**campos)


def test_recargo_y_margen_venta_son_distintos():
    assert mc.calcular(entrada()).precio_total == D("130")
    assert mc.calcular(entrada(politica_precio="margen_venta")).precio_total == D("142.86")


@pytest.mark.parametrize("campo,valor", [
    ("merma_pct", D(-1)), ("indirectos_pct", D(-1)),
    ("precio_kg", D("NaN")), ("margen_pct", D("Infinity")),
])
def test_costes_invalidos_no_generan_precio(campo, valor):
    with pytest.raises(mc.ErrorDeCoste):
        mc.calcular(entrada(**{campo: valor}))


def test_margen_venta_cien_rechazado():
    with pytest.raises(mc.ErrorDeCoste):
        mc.calcular(entrada(politica_precio="margen_venta", margen_pct=D(100)))


def test_ciclo_fraccionario_lote_y_preparacion():
    r = mc.calcular(entrada(cantidad=100, operaciones=[mc.Operacion("M", D(10), D("0.5"), D(1))]))
    assert r.minutos_totales == 60
    assert r.coste_maquina == 50
    assert r.coste_preparacion == 10
    json.dumps(r.desglose)


def test_api_admite_fracciones_y_banda_no_baja_del_coste(cliente):
    r = cliente.post("/calculo/coste", json={"cantidad": 2, "peso_bruto_kg": 1,
        "precio_kg": 1, "margen_pct": 0, "confianza": 0,
        "operaciones": [{"centro": "M", "minutos_unitario": 0.5, "tarifa_minuto": 1}]})
    assert r.status_code == 200
    assert D(r.json()["minutos_totales"]) == 1
    assert D(r.json()["precio_min"]) >= D(r.json()["coste_total"])


def colas():
    return [plazos.ColaCentro(c, 0, D(8), D(1)) for c in ("A", "B")]


def test_dos_operaciones_misma_maquina_acumulan():
    cargas = [plazos.CargaPedido("A", 480), plazos.CargaPedido("A", 480)]
    assert plazos.calcular(colas(), cargas).dias_optimo == 2
    assert plazos.simular_entrada(colas(), cargas)["A"] == 2


def test_lote_completo_respeta_precedencia():
    r = plazos.calcular(colas(), [plazos.CargaPedido("A", 480), plazos.CargaPedido("B", 480)])
    assert r.dias_optimo == 2
    assert r.detalle["operaciones"][1]["inicio_dia"] == 1


def test_no_duplica_cola_preexistente_en_misma_maquina():
    c = [plazos.ColaCentro("A", 480, D(8), D(1))]
    assert plazos.calcular(c, [plazos.CargaPedido("A", 480)] * 2).dias_optimo == 3


def test_fines_semana_y_festivo():
    r = plazos.calcular(colas(), [plazos.CargaPedido("A", 480)],
        desde=date(2026, 9, 18), festivos=frozenset([date(2026, 9, 21)]))
    assert r.fecha_optima == date(2026, 9, 22)


def test_api_plazos(cliente):
    r = cliente.post("/calculo/plazo", json={"desde": "2026-09-17", "colas": [
        {"centro": "A", "minutos_comprometidos": 0, "horas_dia_teoricas": 8,
         "factor_disponibilidad": 1}], "cargas": [{"centro": "A", "minutos": 960}]})
    assert r.status_code == 200
    assert r.json()["dias_optimo"] == 2


def test_brida_con_geometria_supuesta_no_es_confirmada():
    r = mecanizado.generar_ruta(familia="brida", material="F-114", diametro_mm=200,
                               longitud_mm=30, tolerancia_mm=0.1)
    assert r.confianza < 1
    assert any("taladros" in s for s in r.supuestos)
    assert r.avisos


def test_sin_clave_no_accede(cliente):
    cliente.headers.pop("Authorization")
    assert cliente.get("/sesion").status_code == 401
    assert cliente.get("/asistente/puedo-preguntar?rol=direccion").status_code == 401
    assert cliente.post("/ofertas/1/aprobar?usuario=otro").status_code == 401
    assert cliente.get("/vivo").status_code == 200


def test_actor_procede_de_credencial(cliente):
    assert cliente.get("/sesion?usuario=otro").json()["usuario"] == "revisor_prueba"


def test_configuracion_vacia_cierra_acceso(cliente, monkeypatch):
    monkeypatch.setattr(ajustes, "acceso_claves_json", "{}")
    assert cliente.get("/sesion").status_code == 503


def escribir_csv(tmp_path, filas):
    p = tmp_path / "sintetico.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(CAMPOS)
        w.writerows(filas)
    return p


def fila(orden="1"):
    return ["", orden, "2", "Cliente ficticio", "01/09/2026", "", "REF", "",
            "Producción", 'Piñón 1/2"; especial', "", "12,50", "8,25", ""]


def test_importacion_preserva_entrecomillado_y_no_escribe(tmp_path):
    r = diagnosticar(escribir_csv(tmp_path, [fila()]))
    assert r["filas_validas_estructuralmente"] == 1
    assert r["filas_apartadas"] == 0
    assert r["escribe_base_datos"] is False
    assert "Cliente ficticio" not in json.dumps(r)


def test_duplicados_se_apartan_todos(tmp_path):
    r = diagnosticar(escribir_csv(tmp_path, [fila(), fila()]))
    assert r["filas_validas_estructuralmente"] == 0
    assert r["filas_apartadas"] == 2


def test_columna_extra_no_se_importa(tmp_path):
    r = diagnosticar(escribir_csv(tmp_path, [fila() + ["dato desplazado"]]))
    assert r["filas_apartadas"] == 1


def test_comillas_rotas_se_apartan(tmp_path):
    p = escribir_csv(tmp_path, [])
    with p.open("a") as f:
        f.write(';1;2;Cliente;01/09/2026;;;"texto sin cerrar\n')
    assert diagnosticar(p)["filas_apartadas"] == 1


def test_no_mezclar_subcontrata_y_minutos():
    with pytest.raises(ValueError):
        plazos.calcular(colas(), [plazos.CargaPedido("A", 60, 2)])


class ResultadoFalso:
    def __init__(self, valor):
        self.valor = valor

    def mappings(self):
        return self

    def first(self):
        return self.valor

    def scalar(self):
        return self.valor


class SesionFalsa:
    def __init__(self, valores):
        self.valores = iter(valores)
        self.commit_llamado = False

    def execute(self, *args):
        return ResultadoFalso(next(self.valores))

    def commit(self):
        self.commit_llamado = True


def test_aprobacion_bloqueada_por_plano():
    from fastapi import HTTPException
    from app.rutas.ofertas import aprobar
    s = SesionFalsa([{"estado": "borrador", "precio_propuesto": D(100), "via": "B_similar"}, 1])
    with pytest.raises(HTTPException) as error:
        aprobar(1, "revisor", s)
    assert error.value.status_code == 422
    assert not s.commit_llamado


def test_corregir_oferta_revisada_no_muta():
    from fastapi import HTTPException
    from app.rutas.ofertas import corregir, Correccion
    s = SesionFalsa([{"estado": "revisada", "precio_propuesto": D(100),
                     "coste_calculado": D(80), "fecha_entrega_comprometible": None}])
    with pytest.raises(HTTPException) as error:
        corregir(1, Correccion(precio=D(110), motivo="nuevo precio"), s, "revisor")
    assert error.value.status_code == 409
    assert not s.commit_llamado
