"""Ruta de fabricación, tiempos estimados y análisis de modelos 3D."""
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bd import obtener_sesion
from app.servicios import mecanizado as mz
from app.servicios import normalizador as nz
from app.servicios import step3d as s3

try:
    from app.servicios import reconocedor3d as r3
    HAY_NUCLEO = True
except ImportError:      # OpenCascade es opcional: sin él sigue el análisis de texto
    HAY_NUCLEO = False

router = APIRouter(prefix="/mecanizado", tags=["mecanizado"])


class PeticionRuta(BaseModel):
    descripcion: str = Field(min_length=1, max_length=500)
    cantidad: int = Field(gt=0, default=1)
    tolerancia_mm: float | None = None
    rugosidad_ra: float | None = None
    modulo: float | None = None
    ancho_mm: float | None = None


@router.post("/ruta")
def ruta(p: PeticionRuta, sesion: Session = Depends(obtener_sesion)):
    """
    De una descripción libre a una ruta de fabricación con tiempos.

    Si faltan datos esenciales, devuelve avisos y confianza baja en lugar de
    un número inventado. Es la señal de que la oferta va por la vía C.
    """
    pieza = nz.normalizar(p.descripcion)

    paso_mm = mz.PASOS_CADENA_MM.get(pieza.paso_cadena or "")

    r = mz.generar_ruta(
        familia=pieza.familia, material=pieza.material,
        diametro_mm=pieza.diametro_mm, longitud_mm=pieza.longitud_mm,
        ancho_mm=p.ancho_mm or pieza.ancho_mm, dientes_z=pieza.dientes_z,
        modulo=p.modulo, tolerancia_mm=p.tolerancia_mm,
        rugosidad_ra=p.rugosidad_ra, tratamientos=pieza.tratamientos,
        paso_cadena_mm=paso_mm)

    # Tarifas vigentes, para traducir minutos a euros
    tarifas = {f["codigo"]: float(f["tarifa_minuto"])
               for f in sesion.execute(text(
                   "SELECT codigo, tarifa_minuto FROM core.v_tarifa_actual")).mappings()}
    tarifa_media = sum(tarifas.values()) / len(tarifas) if tarifas else 0.50

    operaciones, coste_mo = [], 0.0
    for o in r.operaciones:
        tarifa = tarifas.get(o.tipo_maquina.upper(), tarifa_media)
        importe = round((o.minutos_unitario * p.cantidad + o.minutos_preparacion) * tarifa, 2)
        coste_mo += importe
        operaciones.append({**o.__dict__, "tarifa_minuto": round(tarifa, 4),
                            "importe": importe})

    # La geometría deducida (Ø de un piñón a partir del paso y de Z) no está en
    # la descripción original: hay que devolverla para que se vea de dónde sale.
    geometria = dict(pieza.a_dict())
    if geometria.get("diametro_mm") is None and r.operaciones:
        for o in r.operaciones:
            if "→ ø" in o.descripcion:
                geometria["diametro_mm"] = float(o.descripcion.split("→ ø")[1])
                geometria["origen_diametro"] = (
                    "deducido del paso de cadena y del número de dientes"
                    if paso_mm else "deducido del módulo y del número de dientes")
                break
    if paso_mm:
        geometria["paso_mm"] = paso_mm
        geometria["diametro_primitivo"] = round(
            mz.diametro_primitivo_cadena(paso_mm, pieza.dientes_z), 2
        ) if pieza.dientes_z else None

    return {
        "pieza": geometria,
        "cantidad": p.cantidad,
        "operaciones": operaciones,
        "minutos_unitario": r.minutos_unitario,
        "minutos_preparacion": r.minutos_preparacion,
        "minutos_totales": r.minutos_totales(p.cantidad),
        "coste_mano_obra_maquina": round(coste_mo, 2),
        "confianza": r.confianza,
        "avisos": r.avisos,
        "sugerencias": r.sugerencias,
        "nota": ("Tiempos teóricos de corte. Hay que calibrarlos contra los partes "
                 "reales antes de usarlos para poner precio."),
    }


@router.get("/calibracion")
def calibracion(sesion: Session = Depends(obtener_sesion)):
    """
    Compara los tiempos de ruta con los imputados de verdad, por máquina.
    Devuelve el factor que hay que aplicar al cálculo teórico.
    """
    filas = sesion.execute(text("""
        SELECT ct.codigo AS maquina,
               r.minutos_unitario::numeric AS estimado,
               (p.minutos::numeric / nullif(o.cantidad, 0)) AS real_medido
        FROM core.parte_trabajo p
        JOIN core.orden_fabricacion o ON o.id = p.orden_id
        JOIN core.centro_trabajo ct   ON ct.id = p.centro_trabajo_id
        JOIN core.operacion_ruta r    ON r.id = p.operacion_ruta_id
        WHERE p.minutos > 0 AND o.cantidad > 0 AND r.minutos_unitario > 0
    """)).mappings().all()

    por_maquina: dict[str, list] = {}
    for f in filas:
        por_maquina.setdefault(f["maquina"], []).append(
            (float(f["estimado"]), float(f["real_medido"])))

    resultados = [mz.calibrar_con_historico(m, pares).__dict__
                  for m, pares in por_maquina.items()]
    resultados.sort(key=lambda c: -c["muestras"])
    return {
        "maquinas": len(resultados),
        "fiables": sum(1 for c in resultados if c["fiable"]),
        "resultados": resultados,
        "nota": ("Sin calibrar, los tiempos sirven para comparar piezas entre sí. "
                 "Calibrados, sirven para poner precio."),
    }


@router.post("/analizar-3d")
async def analizar_3d(fichero: UploadFile = File(...),
                      densidad: float = 7.85,
                      sesion: Session = Depends(obtener_sesion)):
    """
    Sube un STEP y devuelve envolvente, peso de partida, tolerancias si las trae
    y qué habría que pedirle al cliente para poder presupuestar sin preguntar.
    """
    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
        tmp.write(await fichero.read())
        ruta = Path(tmp.name)
    try:
        a = s3.analizar_step(ruta)
        resumen = s3.resumen_para_presupuesto(a, densidad)
    finally:
        ruta.unlink(missing_ok=True)

    return {
        "fichero": fichero.filename,
        "protocolo": a.protocolo,
        "nota_protocolo": a.nota_protocolo,
        "origen_cad": a.origen_cad,
        "unidad_original": a.unidad,
        **resumen,
    }


@router.post("/reconocer-3d")
async def reconocer_3d(fichero: UploadFile = File(...), densidad: float = 7.85):
    """
    Reconocimiento de operaciones sobre geometría exacta.

    Devuelve por separado lo MEDIDO (volumen, diámetros, profundidades) y lo
    INTERPRETADO (qué operaciones parecen ser). Lo que no se puede saber por
    geometría, como si un agujero lleva rosca, sale en "dudas" y no se cobra.
    """
    if not HAY_NUCLEO:
        raise HTTPException(501, "Falta el núcleo geométrico: pip install cadquery-ocp")

    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
        tmp.write(await fichero.read())
        ruta = Path(tmp.name)
    try:
        r = r3.reconocer(ruta)
        if r.volumen_mm3 == 0:
            return {"fichero": fichero.filename, "avisos": r.avisos,
                    "reconocido": False}
        ops = r3.a_operaciones(r)
        return {
            "fichero": fichero.filename,
            "reconocido": True,
            "medido": r.exacto,
            "interpretado": r.interpretado,
            "peso_pieza_kg": r3.peso_pieza_kg(r, densidad),
            "peso_bruto_kg": r3.peso_bruto_kg(r, densidad),
            "agujeros": [a.__dict__ for a in r.agujeros],
            "escalones": [e.__dict__ for e in r.escalones],
            "operaciones": ops,
            "avisos": r.avisos,
        }
    except r3.ErrorGeometria as e:
        raise HTTPException(422, str(e)) from e
    finally:
        ruta.unlink(missing_ok=True)
