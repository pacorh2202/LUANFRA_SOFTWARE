"""
Normalizador de descripciones de pieza.

El problema central del proyecto: en las líneas de presupuesto del QGIS el código
de artículo suele ir vacío y la pieza vive en una descripción de texto libre.

    "PIÑÓN Z18 08B-1 AISI 304 BI.UNIV.03.007.01"
    "EJE CROMADO Ø100X1885 S/PLANO T32-1-1 F114"
    "APOYO DE RODILLOS  BI UNIV.02.004.01"

Sin convertir eso en campos no hay búsqueda de similares, no hay comparables y no
hay presupuestador. Con ello, veinte años de histórico se vuelven consultables.

CÓMO FUNCIONA
  Reglas deterministas primero. Son rápidas, gratis, auditables y aciertan en la
  mayoría de los casos porque las descripciones siguen convenciones internas.
  Lo que las reglas no resuelven se marca como `dudoso` y se manda a revisión
  (una persona, o un modelo de lenguaje que propone y una persona confirma).

  La IA NUNCA sobreescribe un campo que las reglas hayan resuelto con confianza
  alta. Es el mismo principio de todo el sistema: la máquina propone donde no sabe,
  no corrige donde ya se sabe.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Diccionarios
# ---------------------------------------------------------------------------

# Familia de pieza. El orden importa: lo más específico primero.
FAMILIAS: list[tuple[str, tuple[str, ...]]] = [
    ("pinon_doble",     ("PINON DOBLE", "PINON 2", "PIÑON DOBLE")),
    ("pinon",           ("PINON", "PIÑON", "SPROCKET", "RUEDA CADENA")),
    ("corona",          ("CORONA", "RUEDA DENTADA", "ENGRANAJE")),
    ("cremallera",      ("CREMALLERA",)),
    ("eje_cromado",     ("EJE CROMADO", "VASTAGO CROMADO")),
    ("eje",             ("EJE", "ARBOL")),
    ("vastago",         ("VASTAGO",)),
    ("casquillo",       ("CASQUILLO", "BUJE", "BOCINA")),
    ("brida",           ("BRIDA", "PLATO")),
    ("apoyo_rodillos",  ("APOYO DE RODILLOS", "APOYO RODILLOS", "SOPORTE RODILLO")),
    ("rodillo",         ("RODILLO", "TAMBOR")),
    ("acoplamiento",    ("ACOPLAMIENTO", "MANGUITO")),
    ("polea",           ("POLEA",)),
    ("soporte",         ("SOPORTE", "BANCADA", "ESTRUCTURA")),
    ("tapa",            ("TAPA", "TAPON")),
    ("tuerca",          ("TUERCA",)),
    ("husillo",         ("HUSILLO", "TORNILLO SINFIN", "SINFIN")),
    ("chaveta",         ("CHAVETA", "CHAVETERO")),
    ("pletina",         ("PLETINA", "CHAPA", "PLACA")),
    ("mecanizado",      ("MECANIZADO", "MECANIZAR", "REPARACION", "REPARAR")),
]

# Materiales. Cada entrada: código normalizado -> patrones que lo delatan.
MATERIALES: list[tuple[str, tuple[str, ...]]] = [
    ("AISI 304",  ("AISI 304", "AISI304", "INOX 304", "1.4301")),
    ("AISI 316",  ("AISI 316", "AISI316", "INOX 316", "1.4401", "1.4404")),
    ("AISI 303",  ("AISI 303", "AISI303")),
    ("AISI 420",  ("AISI 420", "AISI420")),
    ("F-114",     ("F-114", "F114", "C45", "1.0503")),
    ("F-125",     ("F-125", "F125", "42CRMO4", "42 CRMO4", "1.7225")),
    ("F-127",     ("F-127", "F127", "34CRNIMO6")),
    ("F-1140",    ("F-1140", "F1140")),
    ("ST-52",     ("ST52", "ST-52", "S355", "1.0570")),
    ("ST-37",     ("ST37", "ST-37", "S235")),
    ("1.2379",    ("1.2379", "X153CRMO12")),
    ("FUNDICION", ("FUNDICION", "GG25", "GGG40", "FUNDIC")),
    ("BRONCE",    ("BRONCE", "CUSN", "RG7")),
    ("ALUMINIO",  ("ALUMINIO", "AL 6082", "AL6082", "7075", "5083")),
    ("NYLON",     ("NYLON", "POLIAMIDA", "PA6")),
    ("POM",       ("POM", "DELRIN")),
]


# ---------------------------------------------------------------------------
# Elementos de transmisión
#
# Es el grueso de lo que hace Luanfra, y una descripción de piñón lleva mucha
# más información de la que parece. "PIÑON Z18 08B-2 CUBO Ø45 CHAV 12x3,3"
# son cinco datos, no uno, y cada uno cambia el precio.
# ---------------------------------------------------------------------------

# Paso en mm. Serie B (DIN 8187, europea) y serie A / ANSI (americana).
PASOS_MM: dict[str, float] = {
    # DIN 8187 — serie B
    "03B": 5.00, "04B": 6.00, "05B": 8.00, "06B": 9.525, "081": 12.70,
    "08B": 12.70, "10B": 15.875, "12B": 19.05, "16B": 25.40, "20B": 31.75,
    "24B": 38.10, "28B": 44.45, "32B": 50.80, "40B": 63.50, "48B": 76.20,
    # ANSI — serie A
    "25A": 6.35, "35A": 9.525, "40A": 12.70, "50A": 15.875, "60A": 19.05,
    "80A": 25.40, "100A": 31.75, "120A": 38.10, "140A": 44.45, "160A": 50.80,
}

# Designación ANSI escrita a la americana: ASA 40, 40-1, 60-2…
PASOS_ANSI = {"25": 6.35, "35": 9.525, "40": 12.70, "50": 15.875, "60": 19.05,
              "80": 25.40, "100": 31.75, "120": 38.10, "140": 44.45, "160": 50.80}

RAMALES_TXT = {1: "simple", 2: "doble", 3: "triple", 4: "cuádruple"}

# Casquillos cónicos Taper Lock
TAPER_LOCK = {"1008","1108","1210","1215","1310","1610","1615","2012","2517",
              "3020","3030","3525","3535","4030","4040","4535","4545","5040","5050"}

# Perfiles de correa trapecial y dentada
PERFILES_CORREA = ("SPZ","SPA","SPB","SPC","SPZX","XPZ","XPA","XPB","XPC",
                   "HTD","STD","T5","T10","AT5","AT10","AT20")

# Normas que aparecen en los pedidos
NORMAS = {
    "DIN 8187": "cadena serie B", "DIN 8188": "cadena serie A",
    "DIN 6885": "chaveta", "DIN 3961": "calidad de dentado",
    "DIN 3962": "calidad de dentado", "ISO 1328": "calidad de dentado",
    "DIN 5480": "estriado", "DIN 5482": "estriado",
    "ISO 606": "cadena de rodillos", "DIN 867": "perfil de diente",
}

# Designación de cadena: 08B-1, 16B-2, 10B… El sufijo son los ramales.
PASO_CADENA = re.compile(r"\b(0[3-9]|1[0-9]|2[0-8]|3[02]|40|48|100|1[24][00]|160)([AB])\s*-?\s*([1-4])?\b")
PASO_ANSI = re.compile(r"\b(?:ASA|ANSI)\s*(\d{2,3})\s*-?\s*([1-4])?\b")

# Tratamientos y acabados
TRATAMIENTOS: list[tuple[str, tuple[str, ...]]] = [
    ("cromado",     ("CROMADO", "CROMAR", "CROMO DURO")),
    ("templado",    ("TEMPLADO", "TEMPLE", "BONIFICADO", "TEMPLAR")),
    ("nitrurado",   ("NITRURADO", "NITRURAR")),
    ("cementado",   ("CEMENTADO", "CEMENTAR")),
    ("zincado",     ("ZINCADO", "CINCADO", "GALVANIZADO")),
    ("pintado",     ("PINTADO", "IMPRIMACION")),
    ("rectificado", ("RECTIFICADO", "RECTIFICAR")),
    ("anodizado",   ("ANODIZADO",)),
]

# Referencias de cliente: bloques punteados tipo BI.UNIV.03.007.01,
# códigos alfanuméricos largos tipo 7SF889P018, o T32-1-1.
PATRONES_REFERENCIA = [
    re.compile(r"\b[A-Z]{2,}[\s.][A-Z]{2,}(?:\.\d{2,3}){2,4}\b"),   # BI.UNIV.03.007.01
    re.compile(r"\b\d[A-Z]{2}\d{3,6}[A-Z]?\d{0,4}\b"),               # 7SF889P018
    re.compile(r"\b[A-Z]{1,3}\d{1,3}(?:-\d{1,3}){1,3}\b"),           # T32-1-1
    re.compile(r"\b[A-Z]{2}\d{3}[A-Z]\d{2}[A-Z]\b"),                 # PE152R70Z
]

RUIDO = ("S/PLANO", "SEGUN PLANO", "S/MUESTRA", "SEGUN MUESTRA",
         "S/PEDIDO", "URGENTE", "REPARACION")


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class PiezaNormalizada:
    descripcion_original: str
    familia: str | None = None
    material: str | None = None
    diametro_mm: float | None = None
    longitud_mm: float | None = None
    ancho_mm: float | None = None
    dientes_z: int | None = None
    paso_cadena: str | None = None
    paso_mm: float | None = None
    ramales: int | None = None
    ramales_txt: str | None = None
    modulo: float | None = None
    angulo_presion: float | None = None
    helicoidal: bool = False
    angulo_helice: float | None = None
    sentido_helice: str | None = None
    diametro_primitivo: float | None = None
    diametro_exterior: float | None = None
    diametro_cubo: float | None = None
    ancho_cubo: float | None = None
    diametro_taladro: float | None = None
    chavetero: str | None = None
    prisioneros: int | None = None
    taper_lock: str | None = None
    perfil_correa: str | None = None
    canales: int | None = None
    dentado_templado: bool = False
    normas: list[str] = field(default_factory=list)
    tratamientos: list[str] = field(default_factory=list)
    referencia_cliente: str | None = None
    segun_plano: bool = False
    confianza: float = 0.0
    dudoso: list[str] = field(default_factory=list)
    restos: str = ""

    def a_dict(self) -> dict:
        return {
            "familia": self.familia,
            "material": self.material,
            "diametro_mm": self.diametro_mm,
            "longitud_mm": self.longitud_mm,
            "ancho_mm": self.ancho_mm,
            "dientes_z": self.dientes_z,
            "paso_cadena": self.paso_cadena,
            "paso_mm": self.paso_mm,
            "ramales": self.ramales,
            "ramales_txt": self.ramales_txt,
            "modulo": self.modulo,
            "angulo_presion": self.angulo_presion,
            "helicoidal": self.helicoidal,
            "angulo_helice": self.angulo_helice,
            "sentido_helice": self.sentido_helice,
            "diametro_primitivo": self.diametro_primitivo,
            "diametro_exterior": self.diametro_exterior,
            "diametro_cubo": self.diametro_cubo,
            "ancho_cubo": self.ancho_cubo,
            "diametro_taladro": self.diametro_taladro,
            "chavetero": self.chavetero,
            "prisioneros": self.prisioneros,
            "taper_lock": self.taper_lock,
            "perfil_correa": self.perfil_correa,
            "canales": self.canales,
            "dentado_templado": self.dentado_templado,
            "normas": self.normas,
            "tratamientos": self.tratamientos,
            "referencia_cliente": self.referencia_cliente,
            "segun_plano": self.segun_plano,
        }

    @property
    def necesita_revision(self) -> bool:
        return self.confianza < 0.55 or self.familia is None


# ---------------------------------------------------------------------------
# Utilidades de texto
# ---------------------------------------------------------------------------

def limpiar(texto: str) -> str:
    """Mayúsculas, sin acentos, con la Ñ preservada y los diámetros unificados."""
    if not texto:
        return ""
    t = texto.upper().replace("Ñ", "\x01")
    t = "".join(c for c in unicodedata.normalize("NFD", t)
                if unicodedata.category(c) != "Mn")
    t = t.replace("\x01", "Ñ")
    # Todas las formas de diámetro a un solo símbolo
    t = re.sub(r"[ØØøΦφ⌀]", "Ø", t)
    t = re.sub(r"\bDIAM(?:ETRO)?\.?\s*", "Ø", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _numero(s: str) -> float:
    return float(s.replace(",", "."))


# ---------------------------------------------------------------------------
# Extractores
# ---------------------------------------------------------------------------

def extraer_familia(t: str) -> str | None:
    for codigo, pistas in FAMILIAS:
        for p in pistas:
            if p in t:
                return codigo
    return None


def _compactar(s: str) -> str:
    """Quita espacios y guiones para que AISI-316, AISI 316 y AISI316 sean lo mismo."""
    return re.sub(r"[\s\-–_]", "", s)


def extraer_material(t: str) -> str | None:
    """
    Se compara sobre el texto compactado: en veinte años de teclear a mano,
    el mismo material aparece escrito de todas las formas posibles.
    """
    tc = _compactar(t)
    for codigo, pistas in MATERIALES:
        for p in pistas:
            if _compactar(p) in tc:
                return codigo
    return None


def extraer_tratamientos(t: str) -> list[str]:
    return [c for c, pistas in TRATAMIENTOS if any(p in t for p in pistas)]


def extraer_dimensiones(t: str) -> tuple[float | None, float | None, float | None]:
    """
    Devuelve (diámetro, longitud, ancho).
    Formatos que aparecen de verdad en el histórico:
        Ø100X1885     Ø 50      100X1885X20      50X30
    """
    diam = lon = anc = None

    m = re.search(r"Ø\s*(\d+(?:[.,]\d+)?)\s*[XX*]\s*(\d+(?:[.,]\d+)?)", t)
    if m:
        return _numero(m.group(1)), _numero(m.group(2)), None

    m = re.search(r"Ø\s*(\d+(?:[.,]\d+)?)", t)
    if m:
        diam = _numero(m.group(1))

    m = re.search(r"\b(\d+(?:[.,]\d+)?)\s*[XX*]\s*(\d+(?:[.,]\d+)?)"
                  r"(?:\s*[XX*]\s*(\d+(?:[.,]\d+)?))?\b", t)
    if m:
        a, b, c = m.group(1), m.group(2), m.group(3)
        if diam is None:
            diam = _numero(a)
            lon = _numero(b)
        else:
            lon = _numero(a)
            anc = _numero(b)
        if c:
            anc = _numero(c)
    return diam, lon, anc


def extraer_dientes(t: str) -> int | None:
    m = re.search(r"\bZ\s*=?\s*(\d{1,3})\b", t)
    if m:
        z = int(m.group(1))
        return z if 5 <= z <= 250 else None
    return None


def extraer_paso(t: str) -> tuple[str | None, int | None]:
    m = PASO_CADENA.search(t)
    if m:
        return f"{m.group(1)}{m.group(2)}", int(m.group(3))
    m = re.search(r'ISO\s*(\d+)\s*/\s*(\d+)\s*"', t)
    if m:
        return f'ISO {m.group(1)}/{m.group(2)}"', None
    # Paso escrito como número: "PASO 12,7". Aparece así en los export del ERP,
    # donde el paso va en milímetros y no como designación de norma.
    m = re.search(r"\bPASO\s*[:=]?\s*(\d{1,3}(?:[.,]\d{1,3})?)\b", t)
    if m:
        valor = float(m.group(1).replace(",", "."))
        if 3.0 <= valor <= 120.0:
            return f"{valor:g} mm", None
    return None, None


def extraer_referencia(t: str) -> str | None:
    """
    La referencia del cliente es lo que permite reconocer una pieza repetida.
    Se prueban los patrones de más específico a menos.
    """
    for patron in PATRONES_REFERENCIA:
        for m in patron.finditer(t):
            cand = m.group(0).strip()
            # Un material no es una referencia
            if extraer_material(cand):
                continue
            if PASO_CADENA.fullmatch(cand):
                continue
            return cand
    return None



# ---------------------------------------------------------------------------
# Extractores de transmisión
# ---------------------------------------------------------------------------

def extraer_paso(t: str) -> tuple[str | None, float | None, int | None]:
    """
    Devuelve (designación, paso en mm, ramales).

    Tres formas de escribir lo mismo conviven en los pedidos:
        08B-2            designación europea DIN 8187
        ASA 40-2         designación americana
        PASO 12,7        el paso en milímetros a secas
    """
    m = PASO_CADENA.search(t)
    if m:
        desig = f"{m.group(1)}{m.group(2)}"
        return desig, PASOS_MM.get(desig), int(m.group(3)) if m.group(3) else None

    m = PASO_ANSI.search(t)
    if m and m.group(1) in PASOS_ANSI:
        return (f"ASA {m.group(1)}", PASOS_ANSI[m.group(1)],
                int(m.group(2)) if m.group(2) else None)

    m = re.search(r'ISO\s*(\d+)\s*/\s*(\d+)\s*"', t)
    if m:
        pulgadas = int(m.group(1)) / int(m.group(2))
        return f'ISO {m.group(1)}/{m.group(2)}"', round(pulgadas * 25.4, 3), None

    m = re.search(r"\bPASO\s*[:=]?\s*(\d{1,3}(?:[.,]\d{1,3})?)", t)
    if m:
        valor = float(m.group(1).replace(",", "."))
        if 3.0 <= valor <= 120.0:
            return f"{valor:g} mm", valor, None
    return None, None, None


def extraer_modulo(t: str) -> float | None:
    """
    Módulo de un engranaje.

    Hay que distinguirlo de una rosca métrica: "M20x1,5" es rosca, "MOD 4" es
    módulo. Por eso solo se acepta con la palabra explícita o con m= .
    """
    m = re.search(r"\bM[OÓ]D(?:ULO)?\.?\s*[:=]?\s*(\d{1,2}(?:[.,]\d{1,2})?)\b", t)
    if not m:
        m = re.search(r"\bM\s*=\s*(\d{1,2}(?:[.,]\d{1,2})?)\b", t)
    if m:
        valor = float(m.group(1).replace(",", "."))
        if 0.3 <= valor <= 40:
            return valor
    return None


def extraer_diametros_marcados(t: str) -> dict[str, float]:
    """
    Diámetros con etiqueta: primitivo, exterior, cubo, taladro.

    En un piñón hay cuatro o cinco diámetros distintos y confundirlos cambia
    el precio. Solo se asignan cuando el texto dice cuál es.
    """
    patrones = {
        "primitivo": r"(?:Ø\s*)?PRIM(?:ITIVO)?\.?\s*[:=]?\s*Ø?\s*(\d{1,4}(?:[.,]\d{1,2})?)",
        "exterior":  r"(?:Ø\s*)?EXT(?:ERIOR)?\.?\s*[:=]?\s*Ø?\s*(\d{1,4}(?:[.,]\d{1,2})?)",
        "cubo":      r"(?:Ø\s*)?CUBO\s*[:=]?\s*Ø?\s*(\d{1,4}(?:[.,]\d{1,2})?)",
        "taladro":   r"(?:TALADRO|Ø\s*INT(?:ERIOR)?|AGUJERO)\s*[:=]?\s*Ø?\s*(\d{1,4}(?:[.,]\d{1,2})?)",
        "ancho_cubo": r"ANCHO\s*(?:DE\s*)?CUBO\s*[:=]?\s*(\d{1,4}(?:[.,]\d{1,2})?)",
    }
    salida = {}
    for clave, patron in patrones.items():
        m = re.search(patron, t)
        if m:
            salida[clave] = float(m.group(1).replace(",", "."))
    return salida


def extraer_chavetero(t: str) -> tuple[str | None, int | None]:
    """Chavetero y número de prisioneros."""
    chav = None
    m = re.search(r"CHAV(?:ETERO|ETA)?\.?\s*[:=]?\s*(\d{1,2}\s*[XX*]\s*\d{1,2}(?:[.,]\d)?)", t)
    if m:
        chav = re.sub(r"\s*[XX*]\s*", "x", m.group(1)).replace(",", ".")
    elif re.search(r"\bCHAVETERO\b|\bDIN\s*6885\b", t):
        chav = "sí, sin medida"

    pris = None
    m = re.search(r"(\d)\s*PRISIONERO", t)
    if m:
        pris = int(m.group(1))
    elif "PRISIONERO" in t:
        pris = 1
    return chav, pris


def extraer_helice(t: str) -> tuple[bool, float | None, str | None]:
    if not re.search(r"HELICOIDAL|H[EÉ]LICE", t):
        return False, None, None
    ang = None
    m = re.search(r"(?:H[EÉ]LICE|BETA|β)\s*[:=]?\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*°?", t)
    if m:
        ang = float(m.group(1).replace(",", "."))
    sentido = None
    if re.search(r"\bDCHA|DERECHA|\bRH\b", t):
        sentido = "derecha"
    elif re.search(r"\bIZDA|IZQUIERDA|\bLH\b", t):
        sentido = "izquierda"
    return True, ang, sentido


def extraer_correa(t: str) -> tuple[str | None, int | None]:
    perfil = None
    m = re.search(r"\bHTD\s*(\d{1,2})\s*M\b", t)
    if m:
        perfil = f"HTD {m.group(1)}M"
    else:
        # Solo los perfiles que existen: T2.5, T5, T10, T20, AT5, AT10, AT20 y
        # la serie SP. Sin acotar, una referencia de cliente como "T32-1-1"
        # se tomaba por un perfil de correa.
        m = re.search(r"\b(SPZ|SPA|SPB|SPC|XPZ|XPA|XPB|XPC|AT(?:5|10|20)|T(?:2[.,]5|5|10|20))\b", t)
        if m:
            perfil = m.group(1).replace(",", ".")
    # En una correa dentada el número que acompaña al perfil es el paso en mm.
    paso_correa = None
    m = re.search(r"\b(?:HTD|STD)\s*(\d{1,2})\s*M\b", t)
    if m:
        paso_correa = float(m.group(1))
    elif perfil and perfil.startswith(("T", "AT")):
        m = re.match(r"A?T(\d+(?:\.\d)?)", perfil)
        if m:
            paso_correa = float(m.group(1))

    canales = None
    m = re.search(r"(\d{1,2})\s*(?:CANALES?|GARGANTAS?|RANURAS?)", t)
    if m:
        canales = int(m.group(1))
    return perfil, canales, paso_correa


def extraer_cantidad(t: str) -> int | None:
    """
    La cantidad viene escrita de mil formas en los pedidos.
    Se prueban de más específica a menos para no confundirla con una cota.
    """
    for patron in (r"\bCANT(?:IDAD)?\.?\s*[:=]?\s*(\d{1,5})\b",
                   r"\b(\d{1,5})\s*(?:UDS?|UNID(?:ADES)?|PZAS?|PIEZAS?|PCS?)\b",
                   r"\bN[ºO°]\s*(?:DE\s*)?(?:UDS?|PIEZAS?)\s*[:=]?\s*(\d{1,5})\b",
                   r"^\s*(\d{1,4})\s*[XX]\s",
                   r"\bX\s*(\d{1,4})\s*$"):
        m = re.search(patron, t, re.MULTILINE)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 99999:
                return n
    return None


def extraer_normas(t: str) -> list[str]:
    return sorted({n for n in NORMAS if n.replace(" ", "") in t.replace(" ", "")})


def extraer_taper(t: str) -> str | None:
    if not re.search(r"TAPER|CASQUILLO\s*C[OÓ]NICO|BUJ[EÉ]\s*C[OÓ]NICO", t):
        return None
    for m in re.finditer(r"\b(\d{4})\b", t):
        if m.group(1) in TAPER_LOCK:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Normalizador
# ---------------------------------------------------------------------------

def normalizar(descripcion: str) -> PiezaNormalizada:
    original = (descripcion or "").strip()
    r = PiezaNormalizada(descripcion_original=original)
    if not original:
        r.dudoso.append("descripción vacía")
        return r

    t = limpiar(original)

    r.familia = extraer_familia(t)
    r.material = extraer_material(t)
    r.tratamientos = extraer_tratamientos(t)
    # Las cotas con etiqueta (cubo, taladro, chavetero, ancho de cubo) se sacan
    # del texto ANTES de buscar las dimensiones generales. Si no, el "8x3,3" de
    # un chavetero acaba tomándose por el largo y el ancho de la pieza, y el Ø
    # del cubo por el diámetro exterior.
    residuo = re.sub(
        r"(?:CHAV(?:ETERO|ETA)?\.?\s*[:=]?\s*\d{1,2}\s*[XX*]\s*\d{1,2}(?:[.,]\d)?)"
        r"|(?:(?:Ø\s*)?(?:PRIM(?:ITIVO)?|EXT(?:ERIOR)?|CUBO|TALADRO|AGUJERO|"
        r"Ø\s*INT(?:ERIOR)?)\.?\s*[:=]?\s*Ø?\s*\d{1,4}(?:[.,]\d{1,2})?)"
        r"|(?:ANCHO\s*(?:DE\s*)?CUBO\s*[:=]?\s*\d{1,4}(?:[.,]\d{1,2})?)",
        " ", t)

    r.diametro_mm, r.longitud_mm, r.ancho_mm = extraer_dimensiones(residuo)
    r.dientes_z = extraer_dientes(t)
    r.paso_cadena, r.paso_mm, r.ramales = extraer_paso(t)
    if r.ramales:
        r.ramales_txt = RAMALES_TXT.get(r.ramales)
    r.modulo = extraer_modulo(t)
    r.referencia_cliente = extraer_referencia(t)
    r.cantidad = extraer_cantidad(t)
    r.normas = extraer_normas(t)
    r.taper_lock = extraer_taper(t)
    r.chavetero, r.prisioneros = extraer_chavetero(t)
    r.helicoidal, r.angulo_helice, r.sentido_helice = extraer_helice(t)
    r.perfil_correa, r.canales, paso_correa = extraer_correa(t)
    if paso_correa and not r.modulo:
        # En una polea dentada el primitivo sale del paso de la correa:
        # Dp = p · Z / π
        r.paso_mm = r.paso_mm or paso_correa
        if r.dientes_z:
            r.diametro_primitivo = r.diametro_primitivo or round(
                paso_correa * r.dientes_z / math.pi, 2)
    r.dentado_templado = bool(re.search(
        r"DENTADO\s+(?:TEMPLADO|CEMENTADO|NITRURADO)|TEMPLE\s+DE\s+(?:DIENTES|DENTADO)", t))

    m = re.search(r"(?:[AÁ]NGULO\s*(?:DE)?\s*PRESI[OÓ]N|ALPHA|α)\s*[:=]?\s*(\d{2}(?:[.,]\d)?)", t)
    if m:
        r.angulo_presion = float(m.group(1).replace(",", "."))
    elif r.modulo or r.dientes_z:
        m = re.search(r"\b(14[.,]5|20|25)\s*°", t)
        if m:
            r.angulo_presion = float(m.group(1).replace(",", "."))

    m = re.search(r"\bANCHO\s*(?:TOTAL)?\s*[:=]?\s*(\d{1,4}(?:[.,]\d{1,2})?)\b", t)
    if m and "CUBO" not in t[max(0, m.start()-12):m.start()]:
        r.ancho_mm = float(m.group(1).replace(",", "."))

    marcados = extraer_diametros_marcados(t)
    r.diametro_primitivo = marcados.get("primitivo")
    r.diametro_exterior = marcados.get("exterior")
    r.diametro_cubo = marcados.get("cubo")
    r.ancho_cubo = marcados.get("ancho_cubo")
    r.diametro_taladro = marcados.get("taladro")

    # Geometría deducida: si no viene el primitivo, sale del paso y de Z,
    # o del módulo y de Z. Es la fórmula de la norma, no una estimación.
    if r.dientes_z and not r.diametro_primitivo:
        if r.paso_mm:
            r.diametro_primitivo = round(
                r.paso_mm / math.sin(math.pi / r.dientes_z), 2)
        elif r.modulo:
            r.diametro_primitivo = round(r.modulo * r.dientes_z, 2)
    if r.dientes_z and not r.diametro_exterior:
        if r.paso_mm:
            r.diametro_exterior = round(
                r.paso_mm * (0.6 + 1 / math.tan(math.pi / r.dientes_z)), 2)
        elif r.modulo:
            r.diametro_exterior = round(r.modulo * (r.dientes_z + 2), 2)
    # En una pieza dentada el diámetro que manda para mecanizar es el exterior,
    # nunca el del taladro ni el del cubo.
    if r.dientes_z and r.diametro_exterior:
        r.diametro_mm = r.diametro_exterior
    elif r.diametro_mm is None and r.diametro_exterior:
        r.diametro_mm = r.diametro_exterior
    r.segun_plano = any(p in t for p in ("S/PLANO", "SEGUN PLANO", "S/ PLANO"))

    # Un piñón cromado es un piñón; el cromado es tratamiento, no familia.
    if r.familia == "eje_cromado":
        r.familia = "eje"
        if "cromado" not in r.tratamientos:
            r.tratamientos.append("cromado")

    # --- Confianza ---
    # Se suma por cada campo resuelto, ponderado por lo que aporta a un precio.
    puntos = 0.0
    if r.familia:            puntos += 0.34
    if r.material:           puntos += 0.24
    if r.referencia_cliente: puntos += 0.18
    if r.diametro_mm:        puntos += 0.12
    if r.dientes_z:          puntos += 0.06
    if r.paso_mm or r.modulo: puntos += 0.06
    if r.diametro_taladro or r.taper_lock: puntos += 0.04
    if r.chavetero:          puntos += 0.02
    if r.longitud_mm:        puntos += 0.02
    r.confianza = round(min(1.0, puntos), 3)

    # --- Qué falta ---
    if not r.familia:
        r.dudoso.append("no se reconoce la familia de la pieza")
    if not r.material:
        r.dudoso.append("sin material identificable")
    if r.familia in ("pinon", "pinon_doble", "corona") and not r.dientes_z:
        r.dudoso.append("pieza dentada sin número de dientes")
    if r.dientes_z and not (r.paso_mm or r.modulo):
        r.dudoso.append("dentado sin paso ni módulo: no se puede calcular la geometría")
    if r.familia in ("pinon", "pinon_doble") and r.ramales is None and r.paso_cadena:
        r.dudoso.append("no indica si es simple, doble o triple")
    if r.familia in ("pinon", "pinon_doble", "corona", "polea") and not (
            r.diametro_taladro or r.taper_lock):
        r.dudoso.append("sin diámetro de taladro ni casquillo cónico")
    if r.familia == "polea" and not r.perfil_correa:
        r.dudoso.append("polea sin perfil de correa")
    if r.familia in ("eje", "vastago", "casquillo") and not r.diametro_mm:
        r.dudoso.append("pieza de revolución sin diámetro")

    # --- Restos: lo que ninguna regla ha consumido ---
    resto = t
    for trozo in filter(None, [
        r.referencia_cliente, r.material, r.paso_cadena,
        *(p for c, ps in FAMILIAS if c == r.familia for p in ps if p in t),
        *(p for c, ps in TRATAMIENTOS if c in r.tratamientos for p in ps if p in t),
        *RUIDO,
    ]):
        resto = resto.replace(trozo, " ")
    resto = re.sub(r"[Ø\d.,X*=Z/\-]+", " ", resto)
    r.restos = re.sub(r"\s+", " ", resto).strip()

    return r


def normalizar_lote(descripciones: list[str]) -> list[PiezaNormalizada]:
    return [normalizar(d) for d in descripciones]


def informe_de_lote(resultados: list[PiezaNormalizada]) -> dict:
    """Resumen de calidad de una carga. Es lo que dice si el histórico sirve."""
    n = len(resultados) or 1
    return {
        "total": len(resultados),
        "con_familia": sum(1 for r in resultados if r.familia),
        "con_material": sum(1 for r in resultados if r.material),
        "con_referencia": sum(1 for r in resultados if r.referencia_cliente),
        "necesitan_revision": sum(1 for r in resultados if r.necesita_revision),
        "confianza_media": round(sum(r.confianza for r in resultados) / n, 3),
        "familias": sorted({r.familia for r in resultados if r.familia}),
    }
