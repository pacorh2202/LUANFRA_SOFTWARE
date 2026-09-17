"""
Conocimiento de mecanizado.

Este módulo es el que decide QUÉ operaciones lleva una pieza y CUÁNTO tardan.
Es la parte del presupuesto que hoy vive en la cabeza de quien oferta.

CÓMO FUNCIONA, Y POR QUÉ ASÍ
  El tiempo de mecanizado no se adivina: se calcula con las fórmulas de corte
  de toda la vida. Velocidad de corte, avance, profundidad de pasada, número de
  pasadas. Son las mismas que se enseñan en cualquier escuela de fabricación y
  las mismas que aplica el programador de CNC.

  Los valores de corte de este módulo son una REFERENCIA DE PARTIDA, no una
  verdad. Cada taller tiene sus máquinas, sus herramientas y sus costumbres, y
  la diferencia entre el tiempo teórico y el real puede ser del 40%. Por eso
  existe `calibrar_con_historico()`: el modelo teórico da la forma de la curva
  y vuestros partes de trabajo dan las constantes.

  Sin calibrar, esto sirve para comparar piezas entre sí. Calibrado, sirve
  para presupuestar.

LO QUE ESTE MÓDULO NO HACE
  No sustituye al programador. No calcula trayectorias, no elige herramienta
  concreta, no contempla utillajes especiales. Estima el tiempo de una pieza
  normal hecha de la forma normal. Cuando la pieza no es normal, el sistema
  debe decir que no sabe, no inventar un número.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# ===========================================================================
# DATOS DE CORTE POR MATERIAL
# Vc en m/min con plaquita de metal duro recubierto, condiciones normales.
# `maquinabilidad`: 1,0 = acero al carbono de referencia. Menor = más difícil.
# ===========================================================================

@dataclass(frozen=True)
class DatosCorte:
    vc_desbaste: float          # m/min
    vc_acabado: float
    avance_desbaste: float      # mm/vuelta en torneado
    avance_acabado: float
    profundidad_max: float      # mm de pasada en desbaste
    maquinabilidad: float
    notas: str = ""


CORTE: dict[str, DatosCorte] = {
    "acero_carbono": DatosCorte(200, 260, 0.35, 0.15, 4.0, 1.00,
        "F-114, ST-52. Referencia del taller."),
    "acero_aleado": DatosCorte(160, 210, 0.30, 0.12, 3.0, 0.80,
        "F-125, 42CrMo4. Más duro, más desgaste de plaquita."),
    "acero_herramienta": DatosCorte(75, 100, 0.20, 0.08, 1.5, 0.40,
        "1.2379 y similares. Si viene templado, solo rectificado."),
    "inox": DatosCorte(140, 180, 0.25, 0.12, 2.5, 0.60,
        "AISI 304/316. Acritud: hay que entrar con avance, nunca rozar."),
    "fundicion": DatosCorte(150, 200, 0.40, 0.20, 5.0, 1.20,
        "Corta bien pero es abrasiva. En seco."),
    "no_ferrico": DatosCorte(500, 800, 0.30, 0.10, 6.0, 2.50,
        "Aluminio y bronce. Limita la máquina, no el material."),
    "plastico": DatosCorte(400, 600, 0.30, 0.10, 5.0, 2.00,
        "Ojo al calor: se dilata y se sale de cota."),
}

# De material concreto a grupo de corte
GRUPO_CORTE: dict[str, str] = {
    "F-114": "acero_carbono", "F-1140": "acero_carbono",
    "ST-52": "acero_carbono", "ST-37": "acero_carbono",
    "F-125": "acero_aleado", "F-127": "acero_aleado",
    "1.2379": "acero_herramienta",
    "AISI 304": "inox", "AISI 316": "inox", "AISI 303": "inox", "AISI 420": "inox",
    "FUNDICION": "fundicion",
    "BRONCE": "no_ferrico", "ALUMINIO": "no_ferrico",
    "NYLON": "plastico", "POM": "plastico",
}

DEFECTO = "acero_carbono"


def datos_corte(material: str | None) -> DatosCorte:
    return CORTE[GRUPO_CORTE.get(material or "", DEFECTO)]


# ===========================================================================
# TIEMPOS DE PREPARACIÓN POR TIPO DE MÁQUINA (minutos)
# El setup no depende de la pieza sino de la máquina y del utillaje.
# ===========================================================================

PREPARACION: dict[str, int] = {
    "sierra": 10,
    "torno_paralelo": 30,
    "torno_cnc": 45,
    "centro_mecanizado": 60,
    "fresadora": 50,
    "taladro": 15,
    "talladora": 90,        # el más caro: montar la fresa madre y centrar
    "rectificadora": 40,
    "mortajadora": 35,
    "laser": 20,
    "roscadora": 25,
    "externo": 0,
}


# ===========================================================================
# FÓRMULAS DE CORTE
# ===========================================================================

def revoluciones(vc_m_min: float, diametro_mm: float) -> float:
    """n = 1000·Vc / (π·D). La fórmula de la que sale todo lo demás."""
    if diametro_mm <= 0:
        raise ValueError("El diámetro debe ser mayor que cero.")
    return 1000.0 * vc_m_min / (math.pi * diametro_mm)


def tiempo_cilindrado(diametro_ini: float, diametro_fin: float, longitud: float,
                      material: str | None, acabado: bool = False) -> float:
    """
    Minutos de torneado exterior.

    Se calcula pasada a pasada porque el diámetro cambia y con él las
    revoluciones: cilindrar de 100 a 40 no es una sola condición de corte.
    """
    if longitud <= 0 or diametro_ini <= diametro_fin:
        return 0.0
    d = datos_corte(material)
    vc = d.vc_acabado if acabado else d.vc_desbaste
    avance = d.avance_acabado if acabado else d.avance_desbaste
    ap = 0.5 if acabado else d.profundidad_max

    material_radial = (diametro_ini - diametro_fin) / 2.0
    pasadas = max(1, math.ceil(material_radial / ap))

    minutos, diam = 0.0, diametro_ini
    for _ in range(pasadas):
        diam = max(diametro_fin, diam - 2 * ap)
        n = revoluciones(vc, max(diam, 1.0))
        minutos += longitud / (avance * n)
    return minutos


def tiempo_refrentado(diametro: float, material: str | None,
                      acabado: bool = False) -> float:
    """
    Minutos de refrentado (planear la cara).

    Se usa el diámetro medio: la herramienta va del exterior al centro y la
    velocidad de corte cae hasta cero en el eje. Tomar el diámetro exterior
    daría un tiempo optimista.
    """
    if diametro <= 0:
        return 0.0
    d = datos_corte(material)
    vc = d.vc_acabado if acabado else d.vc_desbaste
    avance = d.avance_acabado if acabado else d.avance_desbaste
    n = revoluciones(vc, max(diametro / 2.0, 1.0))
    return (diametro / 2.0) / (avance * n)


def tiempo_taladrado(diametro: float, profundidad: float,
                     material: str | None) -> float:
    """
    Minutos de taladrado, con penalización por agujero profundo.

    A partir de 3 diámetros de profundidad hay que picotear para evacuar viruta,
    y el tiempo real se dispara. Es un detalle que se olvida al presupuestar
    y que luego aparece en el taller.
    """
    if diametro <= 0 or profundidad <= 0:
        return 0.0
    d = datos_corte(material)
    vc = d.vc_desbaste * 0.55                 # el taladro corta más lento que el torno
    avance = min(0.25, 0.02 * diametro)       # mm/vuelta, crece con el diámetro
    n = revoluciones(vc, diametro)
    recorrido = profundidad + 0.3 * diametro  # aproximación y punta de broca
    minutos = recorrido / (avance * n)

    relacion = profundidad / diametro
    if relacion > 3:
        minutos *= 1.0 + 0.25 * (relacion - 3)   # picoteo
    return minutos


def tiempo_fresado_plano(largo: float, ancho: float, espesor: float,
                         material: str | None, diametro_fresa: float = 63.0,
                         dientes: int = 5) -> float:
    """Minutos de planeado con fresa de plaquitas."""
    if largo <= 0 or ancho <= 0 or espesor <= 0:
        return 0.0
    d = datos_corte(material)
    n = revoluciones(d.vc_desbaste, diametro_fresa)
    avance_diente = 0.12 * min(1.5, d.maquinabilidad)
    vf = avance_diente * dientes * n                    # mm/min
    pasadas_z = max(1, math.ceil(espesor / d.profundidad_max))
    pasadas_xy = max(1, math.ceil(ancho / (diametro_fresa * 0.7)))
    recorrido = (largo + diametro_fresa) * pasadas_xy * pasadas_z
    return recorrido / vf


def tiempo_tronzado(diametro: float, material: str | None) -> float:
    """Minutos de corte en sierra de cinta. Va por sección, no por diámetro."""
    if diametro <= 0:
        return 0.0
    d = datos_corte(material)
    area_cm2 = math.pi * (diametro / 20.0) ** 2
    cm2_por_minuto = 22.0 * min(1.6, d.maquinabilidad)
    return area_cm2 / cm2_por_minuto + 0.5              # medio minuto de amarre


def tiempo_tallado(dientes: int, ancho_diente: float, modulo: float,
                   material: str | None, entradas_fresa: int = 1) -> float:
    """
    Minutos de tallado por fresa madre.

    t = Z · L / (fa · n_fresa · entradas)

    La pieza da una vuelta completa por cada Z vueltas de la fresa madre: por eso
    el número de dientes multiplica el tiempo directamente. Es lo que hace que un
    piñón de 90 dientes no cueste lo mismo que uno de 18 aunque midan parecido.
    """
    if dientes <= 0 or ancho_diente <= 0 or modulo <= 0:
        return 0.0
    d = datos_corte(material)
    # Fresa madre real: ø70-100 para módulos corrientes, y velocidad de corte
    # de acero rápido (~60 m/min en acero), no de plaquita. Con los valores de
    # plaquita salían tiempos de tallado tres veces más rápidos de lo posible.
    diametro_fresa = max(70.0, 20.0 * modulo)
    n_fresa = revoluciones(d.vc_desbaste * 0.30, diametro_fresa)
    avance_axial = 1.8 * min(1.3, d.maquinabilidad)     # mm por vuelta de pieza
    recorrido = ancho_diente + 2.5 * modulo            # entrada y salida
    return dientes * recorrido / (avance_axial * n_fresa * entradas_fresa)


def tiempo_rectificado(diametro: float, longitud: float, sobremedida: float = 0.3) -> float:
    """
    Minutos de rectificado cilíndrico.
    Va por volumen arrancado y es lento: por eso una tolerancia apretada es cara.
    """
    if diametro <= 0 or longitud <= 0:
        return 0.0
    volumen_mm3 = math.pi * diametro * longitud * sobremedida
    caudal_mm3_min = 1800.0        # rectificado cilíndrico en pasadas, acero
    return volumen_mm3 / caudal_mm3_min + 3.0          # 3 min de centrado


# ===========================================================================
# GEOMETRÍA DE PIÑONES DE CADENA
# ===========================================================================

# Paso en mm por designación (DIN 8187 serie B, ANSI serie A)
PASOS_CADENA_MM: dict[str, float] = {
    "04B": 6.00, "05B": 8.00, "06B": 9.525, "08B": 12.70, "10B": 15.875,
    "12B": 19.05, "16B": 25.40, "20B": 31.75, "24B": 38.10, "28B": 44.45,
    "32B": 50.80, "40B": 63.50,
    "40A": 12.70, "50A": 15.875, "60A": 19.05, "80A": 25.40, "100A": 31.75,
}


def diametro_primitivo_cadena(paso_mm: float, dientes: int) -> float:
    """
    Dp = p / sen(180°/Z). Es la fórmula de la norma.

    Comprobación contra el propio módulo de piñones del ERP: paso 19,05 con
    Z14 da 85,6 mm, exactamente el valor que muestra su pantalla.
    """
    if paso_mm <= 0 or dientes < 3:
        raise ValueError("Paso o número de dientes fuera de rango.")
    return paso_mm / math.sin(math.pi / dientes)


def diametro_exterior_cadena(paso_mm: float, dientes: int) -> float:
    """De ≈ p · (0,6 + cotg(180°/Z)). Es el diámetro que hay que tornear."""
    if dientes < 3:
        raise ValueError("Número de dientes fuera de rango.")
    return paso_mm * (0.6 + 1.0 / math.tan(math.pi / dientes))


def modulo_desde_paso(paso_mm: float) -> float:
    """Módulo equivalente de un piñón de cadena: m = p / π."""
    return paso_mm / math.pi


# ===========================================================================
# TOLERANCIAS: qué operación exige cada exigencia
# ===========================================================================

# Calidad IT alcanzable por proceso (norma ISO 286, valores habituales)
CALIDAD_ALCANZABLE: dict[str, tuple[int, int]] = {
    "torneado_desbaste":  (11, 13),
    "torneado_acabado":   (8, 9),
    "torneado_fino":      (7, 8),
    "fresado":            (9, 11),
    "taladrado":          (11, 13),
    "escariado":          (7, 8),
    "mandrinado":         (7, 8),
    "rectificado":        (5, 6),
    "lapeado":            (3, 4),
}

# Rugosidad Ra habitual por proceso, en micras
RUGOSIDAD: dict[str, float] = {
    "torneado_desbaste": 6.3,
    "torneado_acabado": 1.6,
    "torneado_fino": 0.8,
    "fresado": 3.2,
    "rectificado": 0.4,
    "lapeado": 0.1,
}


def calidad_it(tolerancia_mm: float, diametro_mm: float) -> int:
    """
    Traduce una tolerancia en milímetros a calidad IT aproximada.

    Se usa la relación de la norma: la unidad de tolerancia crece con la raíz
    cúbica del diámetro. No es exacto, pero acierta el escalón, que es lo que
    decide si hace falta rectificadora o no.
    """
    if tolerancia_mm <= 0 or diametro_mm <= 0:
        return 12
    d = max(diametro_mm, 3.0)
    i = 0.45 * d ** (1 / 3) + 0.001 * d          # micras
    factor = (tolerancia_mm * 1000.0) / i
    escala = {6: 10, 7: 16, 8: 25, 9: 40, 10: 64, 11: 100, 12: 160, 13: 250}
    for it, valor in escala.items():
        if factor <= valor:
            return it
    return 14


def requiere_rectificado(tolerancia_mm: float | None, diametro_mm: float | None,
                         rugosidad_ra: float | None = None,
                         templado: bool = False) -> tuple[bool, str]:
    """
    La pregunta que más dinero mueve en un presupuesto.

    Si la pieza va templada y lleva cotas de ajuste, el rectificado no es
    opcional: después del temple la pieza se mueve y hay que recuperar la cota.
    """
    if templado and tolerancia_mm and diametro_mm and calidad_it(tolerancia_mm, diametro_mm) <= 9:
        return True, "Va templada y lleva cota de ajuste: hay que rectificar después del temple."
    if rugosidad_ra is not None and rugosidad_ra < 0.8:
        return True, f"Rugosidad Ra {rugosidad_ra} no se alcanza torneando."
    if tolerancia_mm and diametro_mm:
        it = calidad_it(tolerancia_mm, diametro_mm)
        if it <= 6:
            return True, f"Calidad IT{it}: solo se alcanza rectificando."
        if it == 7:
            return True, f"Calidad IT{it}: al límite del torneado fino, más seguro rectificar."
    return False, "Se alcanza con torneado de acabado."


def sugerencia_abaratar(tolerancia_mm: float | None, diametro_mm: float | None,
                        precio_estimado: float | None = None) -> str | None:
    """
    Lo que un buen jefe de taller le diría al cliente por teléfono.
    Puesto por escrito y de forma sistemática, es un arma comercial.
    """
    if not tolerancia_mm or not diametro_mm:
        return None
    it = calidad_it(tolerancia_mm, diametro_mm)
    if it <= 7:
        ahorro = "entre un 15% y un 25%"
        if precio_estimado:
            ahorro = f"unos {precio_estimado * 0.20:,.0f} €".replace(",", ".")
        return (f"La cota de ø{diametro_mm:.0f} pide calidad IT{it} y obliga a rectificar. "
                f"Si la función admite IT9, se puede hacer de torno y ahorrar {ahorro}. "
                f"¿Se puede consultar al cliente?")
    return None


# ===========================================================================
# GENERACIÓN DE RUTA
# ===========================================================================

@dataclass
class Operacion:
    secuencia: int
    tipo_maquina: str
    descripcion: str
    minutos_unitario: float
    minutos_preparacion: int
    es_externa: bool = False
    plazo_externo_dias: int = 0
    motivo: str = ""


@dataclass
class Ruta:
    operaciones: list[Operacion] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    confianza: float = 0.0
    sugerencias: list[str] = field(default_factory=list)

    @property
    def minutos_unitario(self) -> float:
        return round(sum(o.minutos_unitario for o in self.operaciones), 2)

    @property
    def minutos_preparacion(self) -> int:
        return sum(o.minutos_preparacion for o in self.operaciones)

    def minutos_totales(self, cantidad: int) -> float:
        return round(self.minutos_unitario * cantidad + self.minutos_preparacion, 2)


def generar_ruta(*, familia: str | None, material: str | None,
                 diametro_mm: float | None = None, longitud_mm: float | None = None,
                 ancho_mm: float | None = None, dientes_z: int | None = None,
                 modulo: float | None = None, tolerancia_mm: float | None = None,
                 rugosidad_ra: float | None = None,
                 tratamientos: list[str] | None = None,
                 diametro_bruto_mm: float | None = None,
                 paso_cadena_mm: float | None = None) -> Ruta:
    """
    Decide las operaciones de una pieza y estima sus tiempos.

    Si faltan datos esenciales, la ruta sale con avisos y confianza baja: es la
    señal para que el presupuesto vaya por la vía C y lo mire una persona.
    """
    tratamientos = tratamientos or []
    ruta = Ruta()
    seq = 0

    def añadir(tipo: str, desc: str, minutos: float, motivo: str = "",
               externa: bool = False, plazo: int = 0):
        nonlocal seq
        seq += 1
        ruta.operaciones.append(Operacion(
            secuencia=seq, tipo_maquina=tipo, descripcion=desc,
            minutos_unitario=round(minutos, 2),
            minutos_preparacion=PREPARACION.get(tipo, 30),
            es_externa=externa, plazo_externo_dias=plazo, motivo=motivo))

    if familia is None:
        ruta.avisos.append("No se reconoce la familia de la pieza: no se puede generar ruta.")
        return ruta

    revolucion = familia in ("eje", "vastago", "casquillo", "rodillo", "husillo",
                             "pinon", "pinon_doble", "corona", "brida", "tapa",
                             "acoplamiento", "polea")
    dentada = familia in ("pinon", "pinon_doble", "corona")

    # En una pieza dentada la geometría se deduce: no hace falta que el diámetro
    # venga escrito en la descripción. Con el paso de cadena y Z, o con el módulo
    # y Z, sale el diámetro exacto. Es lo que hace el módulo de piñones del ERP.
    if dentada and dientes_z and not diametro_mm:
        if paso_cadena_mm:
            diametro_mm = round(diametro_exterior_cadena(paso_cadena_mm, dientes_z), 2)
            modulo = modulo or modulo_desde_paso(paso_cadena_mm)
        elif modulo:
            diametro_mm = round(modulo * (dientes_z + 2), 2)

    if revolucion and not diametro_mm:
        ruta.avisos.append("Pieza de revolución sin diámetro: el tiempo no se puede estimar.")
        return ruta

    templado = any(t in tratamientos for t in ("templado", "cementado", "nitrurado"))
    bruto = diametro_bruto_mm or (diametro_mm * 1.08 + 4 if diametro_mm else None)

    # --- 1. Preparar el material -------------------------------------------
    if revolucion and bruto:
        añadir("sierra", f"Tronzar redondo ø{bruto:.0f}",
               tiempo_tronzado(bruto, material))
    elif familia in ("pletina", "soporte", "chapa"):
        añadir("laser", "Corte láser del desarrollo", 2.5,
               "Chapa: entra por láser, no por sierra")

    # --- 2. Mecanizado principal -------------------------------------------
    if revolucion and diametro_mm and bruto:
        largo = longitud_mm or diametro_mm
        t = tiempo_refrentado(bruto, material)
        t += tiempo_cilindrado(bruto, diametro_mm, largo, material)
        añadir("torno_cnc", f"Torneado de desbaste ø{bruto:.0f} → ø{diametro_mm:.0f}", t)

        añadir("torno_cnc", "Torneado de acabado",
               tiempo_cilindrado(diametro_mm + 1.0, diametro_mm, largo, material, acabado=True)
               + tiempo_refrentado(diametro_mm, material, acabado=True))

    if familia in ("casquillo", "acoplamiento") and diametro_mm:
        interior = diametro_mm * 0.6
        añadir("torno_cnc", f"Taladrar y mandrinar ø{interior:.0f}",
               tiempo_taladrado(interior * 0.7, longitud_mm or diametro_mm, material)
               + tiempo_cilindrado(interior * 0.7, interior, longitud_mm or diametro_mm,
                                   material, acabado=True) * 0.6)

    if familia in ("brida", "tapa") and diametro_mm:
        n_taladros = 8 if diametro_mm > 150 else 4
        d_taladro = max(8.0, diametro_mm * 0.06)
        añadir("centro_mecanizado", f"{n_taladros} taladros ø{d_taladro:.0f}",
               n_taladros * tiempo_taladrado(d_taladro, (ancho_mm or 20), material))

    if familia in ("pletina", "soporte") and longitud_mm and ancho_mm:
        añadir("centro_mecanizado", "Planeado y contornos",
               tiempo_fresado_plano(longitud_mm, ancho_mm, 3.0, material))

    # --- 3. Dentado ---------------------------------------------------------
    if familia in ("pinon", "pinon_doble", "corona"):
        if not dientes_z:
            ruta.avisos.append("Pieza dentada sin número de dientes: el tallado no se puede estimar.")
        else:
            m = modulo or (diametro_mm / (dientes_z + 2) if diametro_mm else 3.0)
            ancho = ancho_mm or max(8.0, (diametro_mm or 60) * 0.2)
            t = tiempo_tallado(dientes_z, ancho, m, material)
            if familia == "pinon_doble":
                t *= 2
            añadir("talladora", f"Tallado Z{dientes_z}, módulo {m:.2f}", t,
                   "El tiempo crece con el número de dientes, no con el diámetro")

    # --- 4. Chavetero -------------------------------------------------------
    if familia in ("pinon", "pinon_doble", "corona", "polea", "acoplamiento") and diametro_mm:
        añadir("mortajadora", "Chavetero interior",
               max(6.0, (longitud_mm or diametro_mm * 0.5) * 0.08), "")

    # --- 5. Tratamiento externo --------------------------------------------
    for t_ext, plazo in (("templado", 8), ("cementado", 10), ("nitrurado", 12),
                         ("cromado", 10), ("zincado", 5), ("anodizado", 6)):
        if t_ext in tratamientos:
            añadir("externo", f"{t_ext.capitalize()} (subcontrata)", 0.0,
                   "Subcontratado: el plazo suele mandar sobre el interno",
                   externa=True, plazo=plazo)

    # --- 6. Rectificado -----------------------------------------------------
    hace_falta, motivo = requiere_rectificado(tolerancia_mm, diametro_mm,
                                              rugosidad_ra, templado)
    if hace_falta and diametro_mm:
        añadir("rectificadora", "Rectificado cilíndrico",
               tiempo_rectificado(diametro_mm, longitud_mm or diametro_mm), motivo)

    # --- Confianza y sugerencias -------------------------------------------
    datos = [familia is not None, material is not None, diametro_mm is not None,
             longitud_mm is not None or not revolucion,
             tolerancia_mm is not None]
    ruta.confianza = round(sum(datos) / len(datos), 3)

    if material is None:
        ruta.avisos.append("Sin material: los tiempos usan acero al carbono como referencia.")
        ruta.confianza *= 0.75
    if tolerancia_mm is None:
        ruta.avisos.append("Sin tolerancia declarada: no se sabe si lleva rectificado.")
        ruta.confianza *= 0.80

    sug = sugerencia_abaratar(tolerancia_mm, diametro_mm)
    if sug:
        ruta.sugerencias.append(sug)
    if material in ("AISI 304", "AISI 316") and (longitud_mm or 0) > 500:
        ruta.sugerencias.append(
            "Inox largo: conviene prever puntos y luneta, y contar más tiempo de amarre.")

    ruta.confianza = round(ruta.confianza, 3)
    return ruta


# ===========================================================================
# CALIBRACIÓN CONTRA EL HISTÓRICO
# ===========================================================================

@dataclass
class Calibracion:
    tipo_maquina: str
    muestras: int
    factor: float               # real / estimado
    dispersion: float
    fiable: bool
    mensaje: str


def calibrar_con_historico(tipo_maquina: str,
                           pares: list[tuple[float, float]]) -> Calibracion:
    """
    Compara el tiempo estimado con el tiempo real imputado en los partes.

    Devuelve el factor por el que hay que multiplicar la estimación teórica
    para que se parezca a lo que pasa de verdad en vuestro taller.

    Es lo que convierte este módulo de "interesante" en "utilizable". Sin
    calibrar, los números sirven para comparar piezas entre sí. Calibrados,
    sirven para poner un precio.
    """
    validos = [(e, r) for e, r in pares if e and r and e > 0 and r > 0]
    if len(validos) < 5:
        return Calibracion(tipo_maquina, len(validos), 1.0, 0.0, False,
                           "Faltan muestras para calibrar: se usa el tiempo teórico.")

    factores = sorted(r / e for e, r in validos)
    n = len(factores)
    mediana = factores[n // 2] if n % 2 else (factores[n // 2 - 1] + factores[n // 2]) / 2
    q1, q3 = factores[n // 4], factores[(3 * n) // 4]
    dispersion = (q3 - q1) / mediana if mediana else 0.0

    fiable = dispersion < 0.45
    if not fiable:
        mensaje = (f"Los tiempos reales varían demasiado (dispersión {dispersion:.0%}) "
                   f"para fiarse del factor. Suele significar que el parte de trabajo "
                   f"mezcla operaciones distintas.")
    elif mediana > 1.35:
        mensaje = (f"El taller tarda un {(mediana-1):.0%} más que el cálculo teórico. "
                   f"Normal: incluye amarres, cambios de herramienta y mediciones.")
    elif mediana < 0.8:
        mensaje = ("El taller va más rápido que el cálculo teórico. Merece la pena mirar "
                   "si el parte se está imputando incompleto.")
    else:
        mensaje = "El cálculo teórico se ajusta bien a la realidad."

    return Calibracion(tipo_maquina, len(validos), round(mediana, 3),
                       round(dispersion, 3), fiable, mensaje)


def aplicar_calibracion(ruta: Ruta, factores: dict[str, float]) -> Ruta:
    """Aplica el factor medido de cada máquina a los tiempos teóricos."""
    for op in ruta.operaciones:
        f = factores.get(op.tipo_maquina, 1.0)
        op.minutos_unitario = round(op.minutos_unitario * f, 2)
    return ruta
