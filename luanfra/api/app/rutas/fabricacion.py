"""Expediente STEP/PDF y propuestas de fabricación; autenticación global del piloto."""
from hashlib import sha256
from typing import Literal
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from app.servicios.decision_fabricacion import PeticionDecision, decidir
from app.servicios import lectores_industriales as lectores

router = APIRouter(prefix='/fabricacion',tags=['fabricación'])


@router.post('/decidir')
def proponer(p: PeticionDecision):
    return decidir(p)


async def contenido(archivo: UploadFile, tipo: str):
    try:
        datos = await archivo.read(lectores.MAX_ARCHIVO + 1)
    finally:
        await archivo.close()
    try:
        lectores.validar_archivo(datos,tipo)
    except lectores.ErrorLectura as exc:
        raise HTTPException(422,str(exc)) from exc
    return datos


@router.post('/expediente')
async def expediente(step: UploadFile = File(...), pdf: UploadFile = File(...),
                     proceso: Literal['machining_milling','machining_turning'] = Form(...)):
    """Lee ambos documentos; conserva evidencias independientes, sin conciliación automática."""
    try:
        modelo = await contenido(step,'step')
        plano = await contenido(pdf,'pdf')
    finally:
        await step.close()
        await pdf.close()
    resultados, bloqueos = {}, []
    for nombre in ('step','pdf'):
        try:
            resultados[nombre] = (await run_in_threadpool(lectores.leer_step_cadex,modelo,proceso)
                if nombre == 'step' else await lectores.leer_pdf_werk24(plano))
        except (lectores.LectorNoDisponible,lectores.ErrorLectura) as exc:
            resultados[nombre] = {'estado':'no_disponible' if isinstance(exc,lectores.LectorNoDisponible) else 'error',
                                  'detalle':str(exc)}
            bloqueos.append(f'{nombre}: {exc}')
    bloqueos.extend(['Confirmar misma pieza y revisión en STEP y PDF',
                     'Conciliar características, tolerancias, amarres y operaciones no reconocidas'])
    identificador = sha256((sha256(modelo).hexdigest()+sha256(plano).hexdigest()).encode()).hexdigest()
    return {'expediente_sha256':identificador,'lecturas':resultados,'bloqueos':bloqueos,
            'ruta_completa_verificada':False,'presupuesto':None,'requiere_revision_tecnica':True}
