"""Adaptadores de proveedores. Sin licencias ni planos embebidos en el código.

MTKConverter: interfaz CLI publicada por CADEX (2026).
Werk24: SDK oficial v2, AskMetaData + AskFeatures.
Las salidas son evidencias pendientes de revisión, no rutas CNC ejecutables.
"""
import asyncio
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

MAX_ARCHIVO = 20 * 1024 * 1024


class LectorNoDisponible(RuntimeError):
    pass


class ErrorLectura(ValueError):
    pass


def validar_archivo(datos: bytes, tipo: str):
    if not datos or len(datos) > MAX_ARCHIVO:
        raise ErrorLectura("Archivo vacío o superior a 20 MiB")
    cabecera = datos[:1024].lstrip()
    if tipo == 'pdf' and not cabecera.startswith(b'%PDF-'):
        raise ErrorLectura("El fichero no tiene cabecera PDF")
    if tipo == 'step' and not cabecera.startswith(b'ISO-10303-21;'):
        raise ErrorLectura("Se requiere un STEP Part 21 sin comprimir")


def normalizar_mtk(informe: dict) -> dict:
    if not isinstance(informe, dict) or str(informe.get('version')) != '1':
        raise ErrorLectura("Versión de informe MTK no soportada")
    partes = informe.get('parts')
    if not isinstance(partes, list) or not partes:
        raise ErrorLectura("MTK no devolvió piezas mecanizables")
    caracteristicas, dfm = [], []
    for parte in partes:
        if not isinstance(parte, dict) or not parte.get('partId'):
            raise ErrorLectura("Parte MTK sin identificador")
        if parte.get('process') not in ('CNC Machining Milling','CNC Machining Lathe+Milling'):
            raise ErrorLectura('Informe MTK de proceso no soportado')
        reconocimiento = parte.get('featureRecognition')
        if not isinstance(reconocimiento, dict) or not isinstance(reconocimiento.get('featureGroups'), list):
            raise ErrorLectura("MTK no devolvió reconocimiento de mecanizado")
        for grupo in reconocimiento['featureGroups']:
            if not isinstance(grupo, dict) or not grupo.get('name'):
                raise ErrorLectura("Grupo MTK inválido")
            caracteristicas.append({'pieza_id':parte['partId'], 'tipo_proveedor':grupo['name'],
                                    'datos':grupo})
        # No interpretar ausencia de incidencias como certificación de fabricabilidad.
        dfm.append({'pieza_id':parte['partId'], 'datos':parte.get('dfm')})
    return {'caracteristicas':caracteristicas,'dfm':dfm,'numero_partes':len(partes),
            'informe_original':informe,'cobertura_completa_verificada':False}


def leer_step_cadex(datos: bytes, proceso: str) -> dict:
    validar_archivo(datos,'step')
    if proceso not in ('machining_milling','machining_turning'):
        raise ErrorLectura("Proceso CADEX no permitido")
    ejecutable = os.environ.get('CADEX_MTK_CONVERTER','')
    version = os.environ.get('CADEX_MTK_VERSION','')
    if not ejecutable or not Path(ejecutable).is_absolute() or not Path(ejecutable).is_file() or not version:
        raise LectorNoDisponible("Configure MTKConverter, su versión y licencias CADEX en el servidor")
    with TemporaryDirectory(prefix='luanfra-mtk-') as carpeta:
        entrada = Path(carpeta)/'pieza.step'
        destino = Path(carpeta)/'resultado'
        entrada.write_bytes(datos)
        try:
            resultado = subprocess.run([ejecutable,'-i',str(entrada),'-p',proceso,
                '-e',str(destino),'--no-screenshot'], timeout=120,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                cwd=str(Path(ejecutable).parent))
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise ErrorLectura("MTK no pudo completar la lectura; revise servicio y licencia") from exc
        archivo = destino/'process_data.json'
        if resultado.returncode != 0 or not archivo.is_file() or archivo.stat().st_size > MAX_ARCHIVO:
            raise ErrorLectura("MTK no generó un informe válido dentro del límite")
        try:
            informe = json.loads(archivo.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc:
            raise ErrorLectura("Informe MTK ilegible") from exc
    return {'proveedor':'cadex_mtk','version_proveedor':version,'proceso':proceso,
            'archivo_sha256':sha256(datos).hexdigest(),**normalizar_mtk(informe)}


async def leer_pdf_werk24(datos: bytes) -> dict:
    validar_archivo(datos,'pdf')
    if os.environ.get('WERK24_HABILITADO','').lower() != 'true':
        raise LectorNoDisponible("Werk24 desactivado: configure cuenta y autorización de tratamiento antes de habilitar")
    try:
        from werk24 import Werk24Client, AskMetaData, AskFeatures, Hook
        from importlib.metadata import version
    except ImportError as exc:
        raise LectorNoDisponible("Instale el extra lectores con el SDK oficial Werk24") from exc
    try:
        from pypdf import PdfReader
        lector = PdfReader(BytesIO(datos))
        if lector.is_encrypted:
            raise ErrorLectura("PDF cifrado: entregue una copia autorizada sin cifrar")
        paginas = len(lector.pages)
        if not 1 <= paginas <= 20:
            raise ErrorLectura("El piloto admite de 1 a 20 páginas por plano")
    except ErrorLectura:
        raise
    except Exception as exc:
        raise ErrorLectura("No se pudo validar la estructura del PDF") from exc
    mensajes, fallos = [], []

    def recibir(mensaje):
        if not mensaje.is_successful:
            fallos.append('Proveedor devolvió un error de extracción')
        else:
            # Conservar página, referencias, unidades y confianza sin reinterpretarlas.
            mensajes.append(mensaje.model_dump(mode='json', include={'page_number','payload_dict','request_id'}))

    try:
        async with asyncio.timeout(120):
            async with Werk24Client() as cliente:
                await cliente.read_drawing_with_hooks(BytesIO(datos), [
                    Hook(ask=AskMetaData(),function=recibir),
                    Hook(ask=AskFeatures(),function=recibir)], max_pages=paginas)
    except Exception as exc:
        # No devolver excepciones del SDK: pueden contener credenciales o rutas.
        raise ErrorLectura("Werk24 no completó la extracción; revise cuenta, licencia y conectividad") from exc
    cobertura = {(m['page_number'], (m.get('payload_dict') or {}).get('ask_type')) for m in mensajes}
    completas = {pagina for pagina,tipo in cobertura
                 if (pagina,'META_DATA') in cobertura and (pagina,'FEATURES') in cobertura}
    if fallos or len(completas) != paginas:
        raise ErrorLectura("Werk24 devolvió una extracción vacía o con errores")
    return {'proveedor':'werk24','version_proveedor':version('werk24'),
            'archivo_sha256':sha256(datos).hexdigest(),'mensajes':mensajes,
            'cobertura_completa_verificada':False}
