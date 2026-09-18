from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from pydantic import ValidationError
from app.servicios.decision_fabricacion import PeticionDecision, decidir

AHORA = datetime(2026,9,18,8,tzinfo=timezone.utc)


def ejemplo():
    maquina = dict(procesos=['fresado'],materiales=['F-114'],envolvente_util_mm=[500,400,300],
        coste_hora_integral=60,referencia_tarifa='tarifa-sintetica',tarifa_desde='2026-01-01',
        minutos_cola=960,carga_leida_en=AHORA.isoformat(),horas_dia=8,disponibilidad=1)
    a=dict(maquina='M1',envolvente_amarre_mm=[200,100,80],preparacion_min=20,ciclo_min=4,
           origen_tiempo='manual',referencia_tiempo='estimacion-sintetica',validacion_tecnica='revision-sintetica')
    return dict(expediente_sha256='a'*64,revision='A',material='F-114',cantidad=10,
        revision_tecnica='revision-sintetica',desde='2026-09-18',
        maquinas=[dict(maquina,codigo='M1'),dict(maquina,codigo='M2',coste_hora_integral=120,minutos_cola=0)],
        operaciones=[dict(id='OP1',proceso='fresado',evidencia='STEP cara sintética 1',
                         alternativas=[a,dict(a,maquina='M2')])],
        economia=dict(peso_bruto_kg=2,precio_kg=3,programacion_lote=10,herramientas_lote=5,
            calidad_lote=5,subcontrata_lote=0,transporte_lote=0,otros_lote=0,
            indirectos_pct=10,margen_pct=20,politica='recargo_coste'))


def ejecutar(p):
    return decidir(PeticionDecision.model_validate(p),AHORA)


def test_coste_y_plazo_eligen_distintas_maquinas():
    r=ejecutar(ejemplo())
    barata,rapida=r['propuestas']
    assert barata['ruta'][0]['maquina']=='M1'
    assert rapida['ruta'][0]['maquina']=='M2'
    assert rapida['fecha_estimada'] < barata['fecha_estimada']
    assert barata['presupuesto']['coste_lote']==Decimal('154.00')
    assert barata['presupuesto']['precio_lote']==Decimal('184.80')
    assert not r['despacho_automatico']


@pytest.mark.parametrize('cambio',[
    {'activa':False},{'envolvente_util_mm':[100,100,100]}, {'materiales':['ALUMINIO']},
    {'procesos':['torneado']},{'minutos_cola':None},{'coste_hora_integral':None},
    {'carga_leida_en':'2026-09-10T08:00:00Z'}, {'carga_leida_en':'2026-09-19T08:00:00Z'},
    {'tarifa_hasta':'2026-09-18'}, {'referencia_tarifa':None},
])
def test_descarta_maquina_aunque_sea_barata(cambio):
    p=ejemplo(); p['maquinas'][0].update(cambio)
    r=ejecutar(p)
    assert r['descartes'][0]['maquina']=='M1'
    assert all(x['ruta'][0]['maquina']=='M2' for x in r['propuestas'])


def test_ruta_incompleta_bloquea():
    p=ejemplo(); p['revision_tecnica']=None
    assert ejecutar(p)['propuestas']==[]
    p=ejemplo(); p['bloqueos_documentales']=['Revisiones diferentes']
    assert ejecutar(p)['propuestas']==[]


def test_economia_incompleta_no_da_presupuesto():
    p=ejemplo(); p['economia']['calidad_lote']=None
    r=ejecutar(p)['propuestas'][0]
    assert r['presupuesto'] is None
    assert 'calidad_lote' in r['datos_economicos_pendientes']


def test_precedencias_y_repeticion_maquina():
    p=ejemplo(); paso=deepcopy(p['operaciones'][0]);paso['id']='OP2'
    p['operaciones'].append(paso)
    r=ejecutar(p)['propuestas'][0]['ruta']
    assert r[1]['inicio_dia_laborable']>=r[0]['fin_dia_laborable']
    assert r[1]['fin_dia_laborable']>r[0]['fin_dia_laborable']


@pytest.mark.parametrize('valor',['NaN','Infinity',-1])
def test_rechaza_tiempos_invalidos(valor):
    p=ejemplo();p['operaciones'][0]['alternativas'][0]['ciclo_min']=valor
    with pytest.raises(ValidationError): ejecutar(p)


def test_horizonte_excesivo_no_desborda_fecha():
    p=ejemplo()
    for m in p['maquinas']: m['minutos_cola']=100000000
    assert ejecutar(p)['propuestas'][0]['presupuesto'] is None


def test_margen_sobre_venta():
    p=ejemplo();p['economia']['politica']='margen_venta'
    assert ejecutar(p)['propuestas'][0]['presupuesto']['precio_lote']==Decimal('192.50')
