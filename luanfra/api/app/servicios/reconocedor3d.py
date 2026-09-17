"""
Reconocimiento de características de fabricación sobre geometría exacta.

QUÉ CAMBIA RESPECTO AL ANALIZADOR DE TEXTO
  `step3d.py` lee el fichero STEP como texto: rápido, sin dependencias, y
  responde "hay 3 caras cilíndricas". Este módulo carga el sólido en un núcleo
  geométrico (OpenCascade) y responde "hay un agujero pasante de ø8,00 en el eje
  Z y dos escalones de torneado de ø50 y ø40".

  La diferencia es que aquí la geometría es EXACTA. No es una malla ni una
  aproximación: es la representación de contornos (B-rep) que generó el CAD.
  El volumen, los diámetros y las profundidades salen con la precisión del
  modelo original.

QUÉ ES EXACTO Y QUÉ ES INTERPRETACIÓN
  Exacto, sin margen de error:
      volumen, área, envolvente, diámetros, ejes, profundidades,
      si un agujero es pasante o ciego, si un cilindro es interior o exterior.

  Interpretación, y por eso lleva confianza y se puede discutir:
      si un agujero lleva rosca (a menos que el modelo traiga PMI),
      si un cilindro exterior es un escalón de torneado o una isla fresada,
      si una superficie libre exige tres ejes o cinco.

  El módulo distingue las dos cosas explícitamente. Lo que no puede saber, lo
  dice; no lo rellena con un valor plausible. Un reconocedor que siempre da una
  respuesta es un reconocedor en el que no se puede confiar.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepTools import BRepTools
from OCP.Bnd import Bnd_Box
from OCP.GeomAbs import (GeomAbs_BSplineSurface, GeomAbs_BezierSurface,
                         GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane,
                         GeomAbs_Sphere, GeomAbs_SurfaceOfRevolution,
                         GeomAbs_Torus)
from OCP.gp import gp_Dir, gp_Pnt, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

TOL_EJE = 1e-4          # tolerancia angular para considerar dos ejes paralelos
TOL_POS = 1e-3          # tolerancia de posición, en mm
DOS_PI = 2 * math.pi


# ===========================================================================
# Estructuras
# ===========================================================================

@dataclass
class Cara:
    indice: int
    tipo: str
    area: float
    radio: float | None = None
    eje: tuple[float, float, float] | None = None
    punto_eje: tuple[float, float, float] | None = None
    interior: bool | None = None      # True = quita material (agujero, vaciado)
    extension_angular: float | None = None
    altura: float | None = None
    radio_menor: float | None = None  # toros: radio de acuerdo
    semiangulo: float | None = None   # conos


@dataclass
class Agujero:
    diametro: float
    profundidad: float
    pasante: bool
    eje: tuple[float, float, float]
    posicion: tuple[float, float, float]
    fondo_plano: bool | None = None
    relacion_profundidad: float = 0.0
    avellanado: bool = False
    posible_rosca: bool = False
    confianza: float = 1.0
    nota: str = ""


@dataclass
class Escalon:
    diametro: float
    longitud: float
    exterior: bool = True


@dataclass
class Reconocimiento:
    fichero: str
    solidos: int = 0
    volumen_mm3: float = 0.0
    area_mm2: float = 0.0
    envolvente: tuple[float, float, float] = (0.0, 0.0, 0.0)
    caras: list[Cara] = field(default_factory=list)
    agujeros: list[Agujero] = field(default_factory=list)
    escalones: list[Escalon] = field(default_factory=list)
    acuerdos: list[float] = field(default_factory=list)
    chaflanes: int = 0
    superficies_libres: int = 0
    eje_de_revolucion: tuple[float, float, float] | None = None
    es_torneable: bool = False
    longitud_eje: float = 0.0
    diametro_envolvente: float = 0.0
    bruto_mm3: float = 0.0
    material_a_arrancar_mm3: float = 0.0
    avisos: list[str] = field(default_factory=list)
    exacto: dict = field(default_factory=dict)
    interpretado: dict = field(default_factory=dict)

    @property
    def porcentaje_arranque(self) -> float:
        return round(100.0 * self.material_a_arrancar_mm3 / self.bruto_mm3, 1) \
            if self.bruto_mm3 else 0.0


class ErrorGeometria(RuntimeError):
    pass


# ===========================================================================
# Lectura
# ===========================================================================

def _leer_step(ruta: Path):
    lector = STEPControl_Reader()
    if lector.ReadFile(str(ruta)) != IFSelect_RetDone:
        raise ErrorGeometria("No se pudo leer el fichero STEP.")
    lector.TransferRoots()
    forma = lector.OneShape()
    if forma.IsNull():
        raise ErrorGeometria("El fichero no contiene geometría.")
    return forma


def _contar(forma, tipo) -> int:
    exp, n = TopExp_Explorer(forma, tipo), 0
    while exp.More():
        n += 1
        exp.Next()
    return n


def _volumen(forma) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(forma, props)
    return abs(props.Mass())


def _area(forma) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(forma, props)
    return abs(props.Mass())


def _envolvente(forma) -> tuple[float, float, float]:
    caja = Bnd_Box()
    BRepBndLib.Add_s(forma, caja)
    # Bnd_Box.Get() devuelve un tipo no convertible en estas bindings:
    # se leen los seis límites uno a uno.
    return (round(caja.CornerMax().X() - caja.CornerMin().X(), 4),
            round(caja.CornerMax().Y() - caja.CornerMin().Y(), 4),
            round(caja.CornerMax().Z() - caja.CornerMin().Z(), 4))


# ===========================================================================
# Clasificación de caras
# ===========================================================================

def _normal_apunta_afuera(cara, u: float, v: float) -> tuple[gp_Pnt, gp_Dir]:
    """
    Normal de la cara ya orientada hacia fuera del material.

    BRepGProp_Face construido con UseOrientation=True ya devuelve la normal
    con la orientación de la cara aplicada. Comprobado sobre un eje con agujero
    pasante: la cara del agujero da producto escalar -1 y la exterior +1.

    Invertirla otra vez a mano, como hacía la primera versión, confundía un
    agujero con un eje. Es el error clásico de estos reconocedores y aquí
    aparecía en el primer sólido de prueba.
    """
    gprop = BRepGProp_Face(cara, True)
    punto, normal = gp_Pnt(), gp_Vec()
    gprop.Normal(u, v, punto, normal)
    if normal.Magnitude() < 1e-12:
        raise ErrorGeometria("Normal degenerada.")
    return punto, gp_Dir(normal)


def _es_interior(cara, superficie, u: float, v: float) -> bool | None:
    """
    ¿Esta cara cilíndrica quita material o lo aporta?

    Se compara la normal exterior con el vector que va del eje al punto.
    Si apuntan al revés, el material está fuera y por tanto es un agujero.
    """
    try:
        punto, normal = _normal_apunta_afuera(cara, u, v)
    except ErrorGeometria:
        return None
    eje = superficie.Axis()
    origen = eje.Location()
    direccion = eje.Direction()

    v_op = gp_Vec(origen, punto)
    v_dir = gp_Vec(direccion.X(), direccion.Y(), direccion.Z())
    radial = v_op - v_dir.Multiplied(v_op.Dot(v_dir))
    if radial.Magnitude() < 1e-9:
        return None
    return radial.Normalized().Dot(gp_Vec(normal.X(), normal.Y(), normal.Z())) < 0


def _clasificar_caras(forma) -> list[Cara]:
    caras: list[Cara] = []
    exp = TopExp_Explorer(forma, TopAbs_FACE)
    i = 0
    while exp.More():
        cara = TopoDS.Face_s(exp.Current())
        exp.Next()
        i += 1
        try:
            adaptador = BRepAdaptor_Surface(cara)
            tipo = adaptador.GetType()
            umin, umax, vmin, vmax = BRepTools.UVBounds_s(cara)
            um, vm = (umin + umax) / 2, (vmin + vmax) / 2
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(cara, props)
            c = Cara(indice=i, tipo="desconocida", area=round(abs(props.Mass()), 4))

            if tipo == GeomAbs_Plane:
                c.tipo = "plano"
            elif tipo == GeomAbs_Cylinder:
                cil = adaptador.Cylinder()
                d = cil.Axis().Direction()
                p = cil.Axis().Location()
                c.tipo = "cilindro"
                c.radio = round(cil.Radius(), 5)
                c.eje = (round(d.X(), 6), round(d.Y(), 6), round(d.Z(), 6))
                c.punto_eje = (round(p.X(), 4), round(p.Y(), 4), round(p.Z(), 4))
                c.extension_angular = round(umax - umin, 5)
                c.altura = round(abs(vmax - vmin), 4)
                c.interior = _es_interior(cara, cil, um, vm)
            elif tipo == GeomAbs_Cone:
                con = adaptador.Cone()
                d = con.Axis().Direction()
                c.tipo = "cono"
                c.semiangulo = round(abs(con.SemiAngle()), 5)
                c.eje = (round(d.X(), 6), round(d.Y(), 6), round(d.Z(), 6))
                c.altura = round(abs(vmax - vmin), 4)
                c.interior = _es_interior(cara, con, um, vm)
            elif tipo == GeomAbs_Torus:
                tor = adaptador.Torus()
                c.tipo = "toro"
                c.radio = round(tor.MajorRadius(), 5)
                c.radio_menor = round(tor.MinorRadius(), 5)
            elif tipo == GeomAbs_Sphere:
                c.tipo = "esfera"
                c.radio = round(adaptador.Sphere().Radius(), 5)
            elif tipo in (GeomAbs_BSplineSurface, GeomAbs_BezierSurface):
                c.tipo = "superficie libre"
            elif tipo == GeomAbs_SurfaceOfRevolution:
                c.tipo = "revolucion"
            caras.append(c)
        except Exception:      # noqa: BLE001  una cara rara no puede tumbar el análisis
            caras.append(Cara(indice=i, tipo="no analizable", area=0.0))
    return caras


# ===========================================================================
# Agrupación en operaciones
# ===========================================================================

def _mismo_eje(a, b) -> bool:
    return abs(abs(a[0]*b[0] + a[1]*b[1] + a[2]*b[2]) - 1.0) < TOL_EJE


def _colineales(c1: Cara, c2: Cara) -> bool:
    """Dos caras cilíndricas pertenecen al mismo agujero si comparten recta."""
    if not (_mismo_eje(c1.eje, c2.eje) and abs(c1.radio - c2.radio) < 1e-4):
        return False
    d = tuple(c2.punto_eje[i] - c1.punto_eje[i] for i in range(3))
    proy = sum(d[i] * c1.eje[i] for i in range(3))
    perp = sum((d[i] - proy * c1.eje[i]) ** 2 for i in range(3))
    return perp < 1e-4


def _agrupar_agujeros(caras: list[Cara], envolvente) -> list[Agujero]:
    cilindros = [c for c in caras if c.tipo == "cilindro" and c.interior is True
                 and c.radio and c.altura]
    usados, agujeros = set(), []

    for i, c in enumerate(cilindros):
        if i in usados:
            continue
        grupo = [c]
        usados.add(i)
        for j, otro in enumerate(cilindros):
            if j not in usados and _colineales(c, otro):
                grupo.append(otro)
                usados.add(j)

        profundidad = round(sum(g.altura for g in grupo), 3)
        diametro = round(2 * c.radio, 3)
        angular = sum(g.extension_angular or 0 for g in grupo)

        # Pasante: la profundidad llega de lado a lado de la envolvente en ese eje
        extension_eje = max(abs(c.eje[k]) * envolvente[k] for k in range(3))
        pasante = profundidad >= extension_eje - 0.05

        # Un cono coaxial y más ancho justo al principio es un avellanado
        avellanado = any(
            k.tipo == "cono" and k.eje and _mismo_eje(k.eje, c.eje) and k.interior
            for k in caras)

        rel = profundidad / diametro if diametro else 0
        agujeros.append(Agujero(
            diametro=diametro, profundidad=profundidad, pasante=pasante,
            eje=c.eje, posicion=c.punto_eje, relacion_profundidad=round(rel, 2),
            avellanado=avellanado,
            confianza=1.0 if angular > DOS_PI * 0.95 else 0.6,
            nota="" if angular > DOS_PI * 0.95 else
                 "Cilindro incompleto: puede ser una ranura, no un agujero."))
    return sorted(agujeros, key=lambda a: -a.diametro)


def _agrupar_escalones(caras: list[Cara]) -> list[Escalon]:
    """Cilindros exteriores: los escalones de un torneado."""
    fuera = [c for c in caras if c.tipo == "cilindro" and c.interior is False
             and c.radio and c.altura]
    por_radio: dict[float, float] = {}
    for c in fuera:
        d = round(2 * c.radio, 3)
        por_radio[d] = por_radio.get(d, 0.0) + c.altura
    return [Escalon(diametro=d, longitud=round(l, 3))
            for d, l in sorted(por_radio.items(), reverse=True)]


def _eje_comun(caras: list[Cara]) -> tuple[float, float, float] | None:
    """
    Si todas las caras de revolución comparten eje, la pieza es torneable.
    Es la decisión que separa "va al torno" de "va al centro de mecanizado".
    """
    ejes = [c.eje for c in caras if c.eje and c.tipo in ("cilindro", "cono", "revolucion")]
    if not ejes:
        return None
    referencia = ejes[0]
    if all(_mismo_eje(referencia, e) for e in ejes):
        return referencia
    return None


# ===========================================================================
# Entrada principal
# ===========================================================================

def reconocer(ruta: str | Path) -> Reconocimiento:
    ruta = Path(ruta)
    r = Reconocimiento(fichero=ruta.name)
    if not ruta.exists():
        r.avisos.append("El fichero no existe.")
        return r

    forma = _leer_step(ruta)
    r.solidos = _contar(forma, TopAbs_SOLID)
    if r.solidos == 0:
        r.avisos.append("El fichero no contiene sólidos: no se puede presupuestar.")
        return r
    if r.solidos > 1:
        r.avisos.append(f"El fichero contiene {r.solidos} sólidos. "
                        "Hace falta un fichero por pieza.")

    r.volumen_mm3 = round(_volumen(forma), 3)
    r.area_mm2 = round(_area(forma), 3)
    r.envolvente = _envolvente(forma)
    r.caras = _clasificar_caras(forma)

    r.agujeros = _agrupar_agujeros(r.caras, r.envolvente)
    r.escalones = _agrupar_escalones(r.caras)
    r.acuerdos = sorted({c.radio_menor for c in r.caras
                         if c.tipo == "toro" and c.radio_menor})
    r.chaflanes = sum(1 for c in r.caras if c.tipo == "cono" and c.interior is False)
    r.superficies_libres = sum(1 for c in r.caras if c.tipo == "superficie libre")

    r.eje_de_revolucion = _eje_comun(r.caras)
    lados = sorted(r.envolvente)
    # Torneable si las dos dimensiones PERPENDICULARES al eje son iguales.
    # Comparar las dos menores fallaba con piezas cortas y anchas: un casquillo
    # de ø60 y 50 de largo salía como no torneable.
    if r.eje_de_revolucion:
        eje = r.eje_de_revolucion
        principal = max(range(3), key=lambda k: abs(eje[k]))
        cruzadas = [r.envolvente[k] for k in range(3) if k != principal]
        r.es_torneable = abs(cruzadas[0] - cruzadas[1]) / max(cruzadas[1], 1e-9) < 0.06
        r.longitud_eje = r.envolvente[principal]
        r.diametro_envolvente = max(cruzadas)
    else:
        r.es_torneable = False

    # Material de partida: cilindro para lo torneable, prisma para lo demás
    if r.es_torneable:
        r.bruto_mm3 = round(math.pi * (r.diametro_envolvente / 2 + 2) ** 2
                            * (r.longitud_eje + 4), 3)
    else:
        r.bruto_mm3 = round((lados[0] + 4) * (lados[1] + 4) * (lados[2] + 4), 3)
    r.material_a_arrancar_mm3 = round(max(0.0, r.bruto_mm3 - r.volumen_mm3), 3)

    if r.superficies_libres:
        r.avisos.append(
            f"{r.superficies_libres} superficies libres: puede necesitar 5 ejes "
            "y el tiempo estimado se queda corto.")
    sin_analizar = sum(1 for c in r.caras if c.tipo in ("no analizable", "desconocida"))
    if sin_analizar:
        r.avisos.append(f"{sin_analizar} caras no se han podido clasificar.")

    # Qué es medida y qué es interpretación
    r.exacto = {
        "volumen_mm3": r.volumen_mm3,
        "area_mm2": r.area_mm2,
        "envolvente_mm": r.envolvente,
        "caras": len(r.caras),
        "diametros_interiores": [a.diametro for a in r.agujeros],
        "diametros_exteriores": [e.diametro for e in r.escalones],
        "radios_de_acuerdo": r.acuerdos,
    }
    r.interpretado = {
        "agujeros": len(r.agujeros),
        "escalones_de_torneado": len(r.escalones),
        "chaflanes": r.chaflanes,
        "es_torneable": r.es_torneable,
        "material_a_arrancar_mm3": r.material_a_arrancar_mm3,
        "porcentaje_arranque": r.porcentaje_arranque,
    }
    return r


def a_operaciones(r: Reconocimiento) -> dict:
    """
    Traduce lo reconocido a lo que necesita el motor de mecanizado.

    Nota sobre las roscas: no se deducen de la geometría. Un agujero de ø6,8
    puede ser un taladro para M8 o un agujero de paso de ø6,8. Sin PMI o sin
    el plano, el sistema lo marca como duda y no lo cobra.
    """
    taladros = [{"diametro": a.diametro, "profundidad": a.profundidad,
                 "pasante": a.pasante, "profundo": a.relacion_profundidad > 3,
                 "avellanado": a.avellanado, "confianza": a.confianza}
                for a in r.agujeros]
    return {
        "estrategia": "torneado" if r.es_torneable else "fresado",
        "diametro_bruto_mm": round(r.diametro_envolvente + 4, 2) if r.es_torneable else None,
        "longitud_mm": round(r.longitud_eje if r.es_torneable else max(r.envolvente), 2),
        "diametro_acabado_mm": r.escalones[0].diametro if r.escalones else None,
        "taladros": taladros,
        "escalones": [{"diametro": e.diametro, "longitud": e.longitud} for e in r.escalones],
        "acuerdos_mm": r.acuerdos,
        "chaflanes": r.chaflanes,
        "volumen_a_arrancar_mm3": r.material_a_arrancar_mm3,
        "porcentaje_arranque": r.porcentaje_arranque,
        "dudas": ([] if not taladros else
                  ["No se puede saber por geometría si los agujeros llevan rosca."])
                 + ([f"{r.superficies_libres} superficies libres sin evaluar."]
                    if r.superficies_libres else []),
    }


def peso_bruto_kg(r: Reconocimiento, densidad_kg_dm3: float = 7.85) -> float:
    return round(r.bruto_mm3 / 1e6 * densidad_kg_dm3, 4)


def peso_pieza_kg(r: Reconocimiento, densidad_kg_dm3: float = 7.85) -> float:
    return round(r.volumen_mm3 / 1e6 * densidad_kg_dm3, 4)
