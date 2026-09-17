"""Pruebas del motor de avisos."""
from datetime import date

import pytest

from app.servicios import avisos as av

HOY = date(2026, 9, 9)   # miércoles


# --- Plazos ----------------------------------------------------------------

def orden(**kw):
    base = {"orden": "OF-100", "cliente": "Industrias YUK",
            "fecha_entrega": date(2026, 9, 30), "horas_pendientes": 10,
            "horas_dia": 8, "importe": 5000}
    base.update(kw)
    return base


def test_avisa_antes_de_incumplir_no_despues():
    """Lo que más vale: detectar que no se llega mientras aún se puede actuar."""
    a = av.avisos_de_plazo([orden(fecha_entrega=date(2026, 9, 11),
                                  horas_pendientes=40)], hoy=HOY)
    assert a[0].codigo == "PLAZO_EN_RIESGO"
    assert a[0].urgencia == "critica"
    assert "Faltan" in a[0].detalle


def test_una_orden_con_margen_no_genera_ruido():
    assert av.avisos_de_plazo([orden()], hoy=HOY) == []


def test_el_aviso_de_riesgo_trae_el_correo_redactado():
    a = av.avisos_de_plazo([orden(fecha_entrega=date(2026, 9, 11),
                                  horas_pendientes=40)], hoy=HOY)[0]
    assert a.borrador
    assert "OF-100" in a.borrador["cuerpo"]
    assert "no vamos a poder cumplir" in a.borrador["cuerpo"]
    assert "prefiero" in a.borrador["cuerpo"].lower()


def test_la_fecha_nueva_del_borrador_cae_en_laborable():
    a = av.avisos_de_plazo([orden(fecha_entrega=date(2026, 9, 11),
                                  horas_pendientes=60)], hoy=HOY)[0]
    fecha = a.borrador["cuerpo"].split("es el ")[1][:10]
    d, m, y = (int(x) for x in fecha.split("/"))
    assert date(y, m, d).weekday() < 5


def test_agrupa_las_vencidas_sin_avisar_en_un_solo_aviso():
    ordenes = [orden(orden=f"OF-{i}", fecha_entrega=date(2026, 8, 20 + i))
               for i in range(5)]
    a = [x for x in av.avisos_de_plazo(ordenes, hoy=HOY)
         if x.codigo == "VENCIDAS_SIN_AVISAR"]
    assert len(a) == 1
    assert a[0].casos == 5
    assert a[0].urgencia == "critica"
    assert a[0].rol == av.DIRECCION


def test_una_vencida_ya_avisada_no_vuelve_a_molestar():
    ordenes = [orden(fecha_entrega=date(2026, 8, 1), cliente_avisado=True)]
    assert av.avisos_de_plazo(ordenes, hoy=HOY) == []


# --- Carga de taller -------------------------------------------------------

def centro(codigo, minutos, disp=0.7, horas=8):
    return {"codigo": codigo, "minutos_cola": minutos,
            "disponibilidad": disp, "horas_dia": horas}


def test_detecta_una_maquina_parada_mientras_otra_se_ahoga():
    a = av.avisos_de_carga([centro("FRESA-1", 40000), centro("TORNO-2", 300)])
    riesgo = [x for x in a if x.codigo == "CARGA_DESEQUILIBRADA"]
    assert riesgo
    assert "FRESA-1" in riesgo[0].titulo and "TORNO-2" in riesgo[0].titulo


def test_no_avisa_si_la_carga_esta_repartida():
    a = av.avisos_de_carga([centro("A", 5000), centro("B", 4800)])
    assert not [x for x in a if x.codigo == "CARGA_DESEQUILIBRADA"]


def test_avisa_de_una_maquina_con_disponibilidad_muy_baja():
    a = av.avisos_de_carga([centro("RECT-1", 2000, disp=0.40), centro("B", 2000)])
    assert any(x.codigo == "DISPONIBILIDAD_BAJA" for x in a)


def test_una_maquina_parada_sin_cola_no_es_un_problema():
    a = av.avisos_de_carga([centro("A", 0, disp=0.3), centro("B", 2000)])
    assert not any(x.codigo == "DISPONIBILIDAD_BAJA" for x in a)


# --- Facturación -----------------------------------------------------------

def albaran(dias, importe=3000, **kw):
    from datetime import timedelta
    base = {"albaran": "ALB-1", "cliente": "Renold Iberia", "importe": importe,
            "fecha_albaran": HOY - timedelta(days=dias)}
    base.update(kw)
    return base


def test_avisa_del_dinero_entregado_y_sin_facturar():
    a = av.avisos_de_facturacion([albaran(60), albaran(20)], hoy=HOY)
    principal = a[0]
    assert principal.codigo == "ENTREGADO_SIN_FACTURAR"
    assert principal.importe == 6000
    assert principal.urgencia == "critica"
    assert principal.rol == av.ADMINISTRACION


def test_lo_entregado_esta_semana_no_alarma():
    assert av.avisos_de_facturacion([albaran(2)], hoy=HOY) == []


def test_avisa_del_corte_de_facturacion_del_cliente():
    """Llegar tarde al corte cuesta un mes entero de cobro."""
    a = av.avisos_de_facturacion([albaran(30, dia_corte=11)], hoy=HOY)
    corte = [x for x in a if x.codigo == "CORTE_DE_FACTURACION"]
    assert corte
    assert "2 días" in corte[0].titulo


def test_un_corte_lejano_todavia_no_avisa():
    a = av.avisos_de_facturacion([albaran(30, dia_corte=25)], hoy=HOY)
    assert not [x for x in a if x.codigo == "CORTE_DE_FACTURACION"]


# --- Comercial -------------------------------------------------------------

def oferta(dias, importe=5000, **kw):
    from datetime import timedelta
    base = {"cliente": "Mecalux", "importe": importe,
            "fecha": HOY - timedelta(days=dias), "ganada": False}
    base.update(kw)
    return base


def test_avisa_de_las_ofertas_en_el_momento_bueno():
    a = av.avisos_comerciales([oferta(20, 9000), oferta(25, 3000)], hoy=HOY)
    s = [x for x in a if x.codigo == "OFERTAS_PARA_SEGUIR"][0]
    assert s.casos == 2
    assert s.importe == 12000
    assert "9.000" in s.accion or "9000" in s.accion


def test_una_oferta_de_ayer_no_se_persigue():
    a = av.avisos_comerciales([oferta(1)], hoy=HOY)
    assert not [x for x in a if x.codigo == "OFERTAS_PARA_SEGUIR"]


def test_una_oferta_ya_seguida_no_se_repite():
    a = av.avisos_comerciales([oferta(20, seguimiento=True)], hoy=HOY)
    assert not [x for x in a if x.codigo == "OFERTAS_PARA_SEGUIR"]


def test_detecta_al_cliente_que_pide_mucho_y_compra_poco():
    """El caso Chains & Sprockets: 4.647 ofertas y un 8,7% de éxito."""
    ofertas = [oferta(200, 1000, cliente="Chains & Sprockets",
                      ganada=(i % 12 == 0)) for i in range(60)]
    a = av.avisos_comerciales(ofertas, hoy=HOY)
    x = [y for y in a if y.codigo == "CLIENTE_POCO_RENTABLE"]
    assert x and x[0].rol == av.DIRECCION


def test_un_cliente_que_convierte_bien_no_se_marca():
    ofertas = [oferta(200, cliente="Mecalux", ganada=(i % 2 == 0)) for i in range(60)]
    a = av.avisos_comerciales(ofertas, hoy=HOY)
    assert not [x for x in a if x.codigo == "CLIENTE_POCO_RENTABLE"]


# --- Oficina técnica -------------------------------------------------------

def test_avisa_de_los_planos_bloqueantes_sin_consultar():
    from datetime import timedelta
    p = [{"referencia": "X", "bloqueantes": 2, "recibida": HOY - timedelta(days=6)}]
    a = av.avisos_tecnicos(p, hoy=HOY)
    assert a[0].codigo == "PLANOS_SIN_CONSULTAR"
    assert a[0].rol == av.OFICINA_TECNICA
    assert a[0].urgencia == "alta"


def test_si_la_consulta_ya_se_mando_no_hay_aviso():
    p = [{"bloqueantes": 2, "recibida": HOY, "consulta_enviada": True}]
    assert av.avisos_tecnicos(p, hoy=HOY) == []


# --- Bandejas y orden ------------------------------------------------------

def test_cada_rol_ve_solo_lo_suyo():
    todos = av.recopilar(
        ordenes=[orden(fecha_entrega=date(2026, 9, 11), horas_pendientes=40)],
        entregas_sin_factura=[albaran(60)])
    assert all(x.rol == av.TALLER for x in av.bandeja(todos, av.TALLER))
    assert all(x.rol == av.ADMINISTRACION for x in av.bandeja(todos, av.ADMINISTRACION))
    assert av.bandeja(todos, "inventado") == []


def test_lo_critico_va_primero_y_dentro_manda_el_importe():
    todos = av.recopilar(entregas_sin_factura=[albaran(60, 90000)],
                         ofertas=[oferta(20, 500)])
    assert todos[0].urgencia == "critica"
    assert todos == sorted(todos, key=lambda a: a.orden)


def test_el_resumen_diario_dice_por_donde_empezar():
    todos = av.recopilar(entregas_sin_factura=[albaran(60, 90000)])
    r = av.resumen_diario(todos)
    assert r["criticos"] >= 1
    assert r["dinero_en_juego"] >= 90000
    assert "sin facturar" in r["lo_primero"]


def test_un_dia_tranquilo_lo_dice_claramente():
    r = av.resumen_diario([])
    assert r["total"] == 0
    assert "Nada urgente" in r["lo_primero"]


def test_todos_los_avisos_traen_accion_en_imperativo():
    """Un aviso sin acción concreta es ruido."""
    todos = av.recopilar(
        ordenes=[orden(fecha_entrega=date(2026, 9, 11), horas_pendientes=40)],
        centros=[centro("A", 40000), centro("B", 100)],
        entregas_sin_factura=[albaran(60)],
        ofertas=[oferta(20)],
        peticiones=[{"bloqueantes": 1, "recibida": HOY}])
    assert todos
    for a in todos:
        assert a.accion and len(a.accion) > 10
        assert a.rol in (av.TALLER, av.ADMINISTRACION, av.COMERCIAL,
                         av.DIRECCION, av.OFICINA_TECNICA)
