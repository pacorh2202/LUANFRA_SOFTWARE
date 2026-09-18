import asyncio
import json
from io import BytesIO
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest
PdfWriter = pytest.importorskip("pypdf").PdfWriter
from app.servicios import lectores_industriales as li

STEP=b'ISO-10303-21;\nEND-ISO-10303-21;'


def pdf(paginas=1):
    w=PdfWriter()
    for _ in range(paginas): w.add_blank_page(width=100,height=100)
    b=BytesIO();w.write(b);return b.getvalue()


def informe():
    return {'version':'1','parts':[{'partId':'sintetica','process':'CNC Machining Milling',
        'featureRecognition':{'featureGroups':[{'name':'Hole','subGroups':[
            {'parameters':[{'name':'Diameter','units':'mm','value':'8'}],'features':[{'shapeIDs':['1']}]}]}]},
        'dfm':{'featureGroups':[]}}]}


def test_mtk_sin_licencia_no_finge_resultados(monkeypatch):
    monkeypatch.delenv('CADEX_MTK_CONVERTER',raising=False)
    with pytest.raises(li.LectorNoDisponible): li.leer_step_cadex(STEP,'machining_milling')


def test_mtk_contrato_cli_y_trazabilidad(monkeypatch):
    monkeypatch.setenv('CADEX_MTK_CONVERTER',sys.executable)
    monkeypatch.setenv('CADEX_MTK_VERSION','version-sintetica')
    def run(args,**kw):
        assert kw['timeout']==120 and not kw.get('shell',False)
        assert args[args.index('-p')+1]=='machining_turning'
        assert Path(args[args.index('-i')+1]).read_bytes()==STEP
        out=Path(args[args.index('-e')+1]);out.mkdir()
        (out/'process_data.json').write_text(json.dumps(informe()))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(li.subprocess,'run',run)
    r=li.leer_step_cadex(STEP,'machining_turning')
    assert len(r['archivo_sha256'])==64
    assert r['caracteristicas'][0]['datos']['subGroups'][0]['parameters'][0]['units']=='mm'
    assert not r['cobertura_completa_verificada']


@pytest.mark.parametrize('mal',[{}, {'version':'2','parts':[]}, {'version':'1','parts':[]},
                                  {'version':'1','parts':[{'partId':'x'}]}])
def test_mtk_rechaza_informes_incompletos(mal):
    with pytest.raises(li.ErrorLectura):li.normalizar_mtk(mal)


def test_werk_desactivado_no_importa_ni_envia(monkeypatch):
    monkeypatch.delenv('WERK24_HABILITADO',raising=False)
    with pytest.raises(li.LectorNoDisponible): asyncio.run(li.leer_pdf_werk24(pdf()))


@pytest.mark.parametrize('parcial',[False,True])
def test_werk_sdk_todas_paginas_y_ambos_asks(monkeypatch,parcial):
    werk24 = pytest.importorskip("werk24")
    monkeypatch.setenv('WERK24_HABILITADO','true')
    class Cliente:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def read_drawing_with_hooks(self,datos,hooks,max_pages):
            assert max_pages==2
            assert datos.read(5)==b'%PDF-'
            assert {h.ask.ask_type.value for h in hooks}=={'META_DATA','FEATURES'}
            for pagina in range(1 if parcial else 2):
                for h in hooks:
                    payload={'page_number':pagina,'request_id':'sintetico',
                             'payload_dict':{'ask_type':h.ask.ask_type.value}}
                    msg=SimpleNamespace(is_successful=True,model_dump=lambda **kw:payload)
                    h.function(msg)
    monkeypatch.setattr(werk24,'Werk24Client',Cliente)
    if parcial:
        with pytest.raises(li.ErrorLectura):asyncio.run(li.leer_pdf_werk24(pdf(2)))
    else:
        r=asyncio.run(li.leer_pdf_werk24(pdf(2)))
        assert len(r['mensajes'])==4
        assert not r['cobertura_completa_verificada']


def test_werk_error_no_expone_secretos(monkeypatch):
    werk24 = pytest.importorskip("werk24")
    monkeypatch.setenv('WERK24_HABILITADO','true')
    def falla():raise RuntimeError('SECRET-CREDENTIAL')
    monkeypatch.setattr(werk24,'Werk24Client',falla)
    with pytest.raises(li.ErrorLectura) as error:asyncio.run(li.leer_pdf_werk24(pdf()))
    assert 'SECRET' not in str(error.value)


def test_endpoint_expediente_no_finge_conciliacion(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.rutas.fabricacion import router
    monkeypatch.delenv('CADEX_MTK_CONVERTER',raising=False)
    monkeypatch.delenv('WERK24_HABILITADO',raising=False)
    app=FastAPI();app.include_router(router)
    respuesta=TestClient(app).post('/fabricacion/expediente',data={'proceso':'machining_milling'},
        files={'step':('pieza.step',STEP),'pdf':('plano.pdf',pdf())})
    assert respuesta.status_code==200
    r=respuesta.json()
    assert len(r['bloqueos'])==4 and r['presupuesto'] is None
    assert len(r['expediente_sha256'])==64


@pytest.mark.parametrize('tipo,datos',[('pdf',STEP),('step',b'%PDF-1.0'),('pdf',b''),
                                      ('step',b'x'*(li.MAX_ARCHIVO+1))])
def test_archivos_invalidos(tipo,datos):
    with pytest.raises(li.ErrorLectura):li.validar_archivo(datos,tipo)
