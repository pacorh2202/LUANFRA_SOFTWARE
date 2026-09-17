#!/usr/bin/env python3
"""
Explorador del ERP QGIS (SQL Server) — SOLO LECTURA.

Se conecta a una copia de la base del ERP, levanta el mapa completo del esquema
y deja un informe listo para hacer el mapeo campo a campo contra core.*

REGLAS QUE ESTE SCRIPT SE IMPONE A SÍ MISMO
  1. Solo ejecuta SELECT. Cualquier otra sentencia se rechaza antes de enviarse.
  2. Nunca hace COUNT(*) sobre tablas grandes: lee sys.partitions, que es instantáneo.
  3. Trabaja en READ UNCOMMITTED con LOCK_TIMEOUT, para no bloquear a nadie.
  4. Avisa si detecta que se está ejecutando en horario de taller (7:00-15:00).
  5. Si una tabla da error de permisos, lo anota y sigue. No aborta.

USO
    python scripts/explorar_erp.py                       # lee credenciales de .env
    python scripts/explorar_erp.py --simular             # sin servidor, para ver la salida
    python scripts/explorar_erp.py --buscar "4237,50"    # ¿en qué tabla está este valor?
    python scripts/explorar_erp.py --muestras            # incluye 3 filas de ejemplo por tabla

SALIDA
    salida/erp/esquema.json     mapa completo, para procesar
    salida/erp/informe.md       informe legible, para leer y decidir
    salida/erp/muestras.json    filas de ejemplo (solo con --muestras; va a .gitignore)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RAIZ_SALIDA = Path("salida/erp")

# --------------------------------------------------------------------------
# Heurísticas: qué buscamos en un ERP industrial español
# --------------------------------------------------------------------------

FAMILIAS: dict[str, dict[str, list[str]]] = {
    "clientes": {
        "tabla": ["cliente", "clien", "customer", "cli_", "tercero"],
        "columna": ["nif", "cif", "razon", "direccion"],
    },
    "presupuestos": {
        "tabla": ["presupuesto", "ppto", "oferta", "propuesta", "budget", "presup"],
        "columna": ["fecha", "importe", "total", "cliente"],
    },
    "pedidos": {
        "tabla": ["pedido", "ped_", "pedcli", "orden_venta"],
        "columna": ["fecha", "cliente", "cantidad"],
    },
    "albaranes": {
        "tabla": ["albaran", "alb_", "albcli", "entrega"],
        "columna": ["fecha", "cantidad", "cliente"],
    },
    "facturas": {
        "tabla": ["factura", "fac_", "faccli", "invoice"],
        "columna": ["fecha", "base", "iva", "total"],
    },
    "articulos": {
        "tabla": ["articulo", "art_", "pieza", "producto", "item", "referencia"],
        "columna": ["descripcion", "referencia", "peso", "material"],
    },
    "ordenes_fabricacion": {
        "tabla": ["orden", "fabricacion", "_of", "of_", "produccion", "lanzamiento"],
        "columna": ["cantidad", "fecha", "articulo", "estado"],
    },
    "partes_trabajo": {
        "tabla": ["parte", "imputacion", "tiempo", "fichaje", "operacion"],
        "columna": ["hora", "minutos", "operario", "maquina", "inicio", "fin"],
    },
    "maquinas": {
        "tabla": ["maquina", "centro", "seccion", "recurso", "puesto"],
        "columna": ["descripcion", "tarifa", "coste"],
    },
    "rutas": {
        "tabla": ["ruta", "escandallo", "fase", "operacion", "proceso"],
        "columna": ["secuencia", "tiempo", "maquina", "preparacion"],
    },
    "proveedores": {
        "tabla": ["proveedor", "prov_", "suministrador"],
        "columna": ["nif", "cif", "razon"],
    },
    "personal": {
        "tabla": ["operario", "empleado", "trabajador", "personal"],
        "columna": ["nombre", "categoria"],
    },
}

# Tablas que casi seguro son ruido en un ERP: configuración, logs, temporales
RUIDO = re.compile(
    r"(^|_)(tmp|temp|aux|log|backup|bak|copia|test|prueba|w_|z_|sys|config|param)",
    re.IGNORECASE,
)

PISTAS_LINEA = ("linea", "lin_", "_lin", "detalle", "det_", "_det", "pos_")

TIPOS_FECHA = {"date", "datetime", "datetime2", "smalldatetime", "datetimeoffset"}
TIPOS_NUM = {"decimal", "numeric", "money", "smallmoney", "float", "real",
             "int", "bigint", "smallint", "tinyint"}
TIPOS_TEXTO = {"varchar", "nvarchar", "char", "nchar", "text", "ntext"}


# --------------------------------------------------------------------------
# Funciones puras: se prueban sin servidor
# --------------------------------------------------------------------------

def mil(n) -> str:
    """Separador de miles a la española: 128.944. Nunca aplicar a una línea entera."""
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def normalizar(texto: str) -> str:
    """Minúsculas y sin acentos, para comparar nombres de tabla."""
    t = texto.lower()
    for a, b in zip("áéíóúüñ", "aeiouun"):
        t = t.replace(a, b)
    return t


def clasificar_tabla(nombre: str, columnas: list[dict], filas: int) -> tuple[str | None, int]:
    """
    Devuelve (familia, puntuación). Puntuación alta = candidata firme.

    Se puntúa por tres vías: el nombre de la tabla, las columnas que tiene
    y el volumen. Ninguna por separado es fiable; juntas aciertan bastante.
    """
    n = normalizar(nombre)
    nombres_col = [normalizar(c["nombre"]) for c in columnas]

    mejor_familia, mejor_punt = None, 0
    for familia, pistas in FAMILIAS.items():
        punt = 0
        if any(p in n for p in pistas["tabla"]):
            punt += 50
        coincidencias = sum(
            1 for pc in pistas["columna"] if any(pc in nc for nc in nombres_col)
        )
        punt += coincidencias * 8
        if punt and filas > 1000:
            punt += 10
        if punt and filas == 0:
            punt -= 25
        if punt > mejor_punt:
            mejor_familia, mejor_punt = familia, punt

    if RUIDO.search(n):
        mejor_punt -= 40
    return (mejor_familia, max(0, mejor_punt)) if mejor_punt > 0 else (None, 0)


def es_tabla_de_lineas(nombre: str) -> bool:
    n = normalizar(nombre)
    return any(p in n for p in PISTAS_LINEA)


def columnas_por_tipo(columnas: list[dict], grupo: set[str]) -> list[str]:
    return [c["nombre"] for c in columnas if c["tipo"].lower() in grupo]


def resumen_calidad(tabla: dict) -> list[str]:
    """Señales de aviso que conviene ver antes de fiarse de una tabla."""
    avisos = []
    if tabla["filas"] == 0:
        avisos.append("vacía")
    if not tabla.get("clave_primaria"):
        avisos.append("sin clave primaria")
    if not columnas_por_tipo(tabla["columnas"], TIPOS_FECHA):
        avisos.append("sin columnas de fecha")
    if tabla.get("error"):
        avisos.append(f"error: {tabla['error']}")
    return avisos


def construir_informe(datos: dict) -> str:
    """Genera el informe en markdown a partir del esquema ya leído."""
    srv = datos["servidor"]
    tablas = datos["tablas"]
    por_familia: dict[str, list[dict]] = defaultdict(list)
    for t in tablas:
        if t["familia"]:
            por_familia[t["familia"]].append(t)

    L: list[str] = []
    add = L.append

    add("# Exploración del ERP QGIS\n")
    add(f"Generado el {datos['generado']}.\n")
    add("Lectura sin escritura. No se ha modificado nada en el servidor.\n")

    add("## Servidor\n")
    add(f"- Base de datos: `{srv.get('base_datos','?')}`")
    add(f"- Versión: {srv.get('version','?')}")
    add(f"- Compatibilidad: {srv.get('nivel_compatibilidad','?')}")
    add(f"- Intercalación: {srv.get('intercalacion','?')}")
    add(f"- Tamaño aproximado: {srv.get('tamano_mb','?')} MB")
    if srv.get("fuera_de_soporte"):
        add("\n> **Aviso:** esta versión de SQL Server está fuera de soporte de Microsoft. "
            "Es un asunto de seguridad independiente de este proyecto y conviene comentarlo.")
    add("")

    add("## Resumen\n")
    add(f"- Tablas encontradas: **{len(tablas)}**")
    add(f"- Con datos: **{sum(1 for t in tablas if t['filas'] > 0)}**")
    add(f"- Filas totales: **{mil(sum(t['filas'] for t in tablas))}**")
    add(f"- Vistas: **{datos.get('n_vistas', 0)}**  ·  "
        f"Procedimientos: **{datos.get('n_procedimientos', 0)}**")
    add(f"- Tablas clasificadas en alguna familia: **{sum(len(v) for v in por_familia.values())}**")
    add("")

    add("## Lo que buscamos, y dónde parece estar\n")
    add("Ordenado por confianza. Estas son las tablas a mapear primero.\n")
    for familia in FAMILIAS:
        candidatas = sorted(por_familia.get(familia, []),
                            key=lambda t: (-t["puntuacion"], -t["filas"]))[:4]
        add(f"### {familia.replace('_', ' ').capitalize()}\n")
        if not candidatas:
            add("_Nada encontrado. Puede estar con otro nombre: revisar el listado completo._\n")
            continue
        add("| Tabla | Filas | Confianza | Rango de fechas | Notas |")
        add("|---|---:|---:|---|---|")
        for t in candidatas:
            rango = t.get("rango_fechas") or "—"
            notas = ", ".join(
                (["líneas de detalle"] if es_tabla_de_lineas(t["nombre"]) else [])
                + resumen_calidad(t)
            ) or "—"
            add(f"| `{t['esquema']}.{t['nombre']}` | {mil(t['filas'])} "
                f"| {t['puntuacion']} | {rango} | {notas} |")
        add("")

    add("## Cobertura temporal\n")
    add("Responde a la pregunta de desde qué año hay datos de verdad.\n")
    con_fechas = [t for t in tablas if t.get("rango_fechas") and t["filas"] > 100]
    con_fechas.sort(key=lambda t: -t["filas"])
    if con_fechas:
        add("| Tabla | Filas | Columna de fecha | Desde | Hasta |")
        add("|---|---:|---|---|---|")
        for t in con_fechas[:25]:
            add(f"| `{t['nombre']}` | {mil(t['filas'])} | {t.get('columna_fecha','—')} "
                f"| {t.get('fecha_min','—')} | {t.get('fecha_max','—')} |")
    else:
        add("_No se han podido leer rangos de fechas._")
    add("")

    add("## Relaciones detectadas\n")
    rel = datos.get("relaciones", [])
    if rel:
        add("Las claves ajenas dibujan el modelo real sin necesidad de documentación.\n")
        add("| Desde | Hacia |")
        add("|---|---|")
        for r in rel[:60]:
            add(f"| `{r['tabla_origen']}.{r['columna_origen']}` | "
                f"`{r['tabla_destino']}.{r['columna_destino']}` |")
        if len(rel) > 60:
            add(f"\n_… y {len(rel) - 60} más en `esquema.json`._")
    else:
        add("**No hay claves ajenas declaradas.** Es habitual en ERP antiguos: "
            "la integridad la mantiene la aplicación, no la base. "
            "El mapeo habrá que hacerlo comparando nombres y valores.")
    add("")

    add("## Las 30 tablas más grandes\n")
    add("| Tabla | Filas | Columnas | Familia |")
    add("|---|---:|---:|---|")
    for t in sorted(tablas, key=lambda t: -t["filas"])[:30]:
        add(f"| `{t['esquema']}.{t['nombre']}` | {mil(t['filas'])} | {len(t['columnas'])} "
            f"| {t['familia'] or '—'} |")
    add("")

    if datos.get("busqueda"):
        b = datos["busqueda"]
        add(f"## Búsqueda del valor `{b['valor']}`\n")
        if b["resultados"]:
            add("| Tabla | Columna | Coincidencias |")
            add("|---|---|---:|")
            for r in b["resultados"]:
                add(f"| `{r['tabla']}` | `{r['columna']}` | {r['coincidencias']} |")
        else:
            add("_No aparece en ninguna columna de texto o numérica revisada._")
        add("")

    errores = [t for t in tablas if t.get("error")]
    if errores:
        add("## Tablas que no se pudieron leer\n")
        for t in errores:
            add(f"- `{t['esquema']}.{t['nombre']}`: {t['error']}")
        add("")

    add("---\n")
    add("### Siguiente paso\n")
    add("Con este informe delante, el mapeo campo a campo contra `core.*`: "
        "clientes, artículos, presupuestos y sus líneas, y partes de trabajo. "
        "Empezar por presupuestos: si están estructurados, el histórico de ofertas "
        "está servido y la fase 1 se acorta mucho.")
    return "\n".join(L)


# --------------------------------------------------------------------------
# Acceso a SQL Server: la única parte que toca la red
# --------------------------------------------------------------------------

class ErrorConexion(RuntimeError):
    pass


def _solo_lectura(sql: str) -> str:
    """Puerta de seguridad: nada que no sea SELECT sale de este script."""
    limpio = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    limpio = re.sub(r"--[^\n]*", " ", limpio).strip()
    if not re.match(r"^(select|with|set\s+(transaction|lock_timeout|nocount))",
                    limpio, re.IGNORECASE):
        raise ValueError(f"Sentencia no permitida (solo lectura): {limpio[:60]}…")
    if re.search(r"\b(insert|update|delete|drop|alter|create|truncate|exec|merge)\b",
                 limpio, re.IGNORECASE):
        raise ValueError("La sentencia contiene una palabra de escritura. Abortado.")
    return sql


def conectar(host: str, base: str, usuario: str, password: str, timeout: int = 30):
    """
    Conexión de solo lectura. Prueba pyodbc y, si no está, pymssql.
    Se importan aquí dentro para que --simular funcione sin nada instalado.
    """
    try:
        import pyodbc

        drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
        if not drivers:
            raise ErrorConexion(
                "No hay driver ODBC de SQL Server instalado.\n"
                "  Windows: instala 'ODBC Driver 18 for SQL Server' de Microsoft.\n"
                "  Linux:   apt install msodbcsql18\n"
                "  O bien:  pip install pymssql (alternativa sin ODBC)."
            )
        # El driver más reciente primero
        driver = sorted(drivers, reverse=True)[0]
        cadena = (
            f"DRIVER={{{driver}}};SERVER={host};DATABASE={base};"
            f"UID={usuario};PWD={password};TrustServerCertificate=yes;"
            f"ApplicationIntent=ReadOnly;Connection Timeout={timeout};"
        )
        cn = pyodbc.connect(cadena, readonly=True, timeout=timeout)
        print(f"  Conectado con pyodbc ({driver})")
        return cn
    except ImportError:
        pass
    except Exception as e:  # driver presente pero fallo de conexión
        if "pyodbc" in str(type(e)).lower() or "ODBC" in str(e):
            raise ErrorConexion(f"pyodbc no pudo conectar: {e}") from e
        raise

    try:
        import pymssql

        cn = pymssql.connect(server=host, database=base, user=usuario,
                             password=password, timeout=timeout, login_timeout=timeout)
        print("  Conectado con pymssql")
        return cn
    except ImportError as e:
        raise ErrorConexion(
            "No hay ningún cliente de SQL Server instalado.\n"
            "  pip install pyodbc   (recomendado, necesita driver ODBC)\n"
            "  pip install pymssql  (alternativa autocontenida)"
        ) from e


class LectorSQLServer:
    """Envuelve la conexión y garantiza que solo se lee."""

    def __init__(self, conexion):
        self.cn = conexion
        cur = self.cn.cursor()
        # No bloquear al ERP y no esperar indefinidamente por un candado
        for pragma in ("SET NOCOUNT ON",
                       "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED",
                       "SET LOCK_TIMEOUT 5000"):
            cur.execute(pragma)
        cur.close()

    def consultar(self, sql: str, params: tuple = ()) -> list[dict]:
        _solo_lectura(sql)
        cur = self.cn.cursor()
        try:
            cur.execute(sql, params) if params else cur.execute(sql)
            if cur.description is None:
                return []
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, fila)) for fila in cur.fetchall()]
        finally:
            cur.close()


# --- Consultas concretas ---------------------------------------------------

SQL_SERVIDOR = """
SELECT SERVERPROPERTY('ProductVersion') AS version_producto,
       SERVERPROPERTY('ProductLevel')   AS nivel,
       SERVERPROPERTY('Edition')        AS edicion,
       DB_NAME()                        AS base_datos,
       DATABASEPROPERTYEX(DB_NAME(),'Collation')     AS intercalacion,
       (SELECT compatibility_level FROM sys.databases WHERE name = DB_NAME())
                                        AS nivel_compatibilidad,
       (SELECT CAST(SUM(size) * 8.0 / 1024 AS DECIMAL(12,1)) FROM sys.database_files)
                                        AS tamano_mb
"""

SQL_TABLAS = """
SELECT s.name AS esquema, t.name AS tabla,
       SUM(CASE WHEN p.index_id IN (0,1) THEN p.rows ELSE 0 END) AS filas
FROM sys.tables t
JOIN sys.schemas s    ON s.schema_id = t.schema_id
JOIN sys.partitions p ON p.object_id = t.object_id
GROUP BY s.name, t.name
ORDER BY filas DESC
"""

SQL_COLUMNAS = """
SELECT s.name AS esquema, t.name AS tabla, c.name AS columna,
       ty.name AS tipo, c.max_length, c.precision, c.scale,
       c.is_nullable, c.column_id
FROM sys.columns c
JOIN sys.tables t   ON t.object_id = c.object_id
JOIN sys.schemas s  ON s.schema_id = t.schema_id
JOIN sys.types ty   ON ty.user_type_id = c.user_type_id
ORDER BY s.name, t.name, c.column_id
"""

SQL_CLAVES = """
SELECT s.name AS esquema, t.name AS tabla, c.name AS columna
FROM sys.indexes i
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns c        ON c.object_id = ic.object_id AND c.column_id = ic.column_id
JOIN sys.tables t         ON t.object_id = i.object_id
JOIN sys.schemas s        ON s.schema_id = t.schema_id
WHERE i.is_primary_key = 1
ORDER BY s.name, t.name, ic.key_ordinal
"""

SQL_RELACIONES = """
SELECT tp.name AS tabla_origen,  cp.name AS columna_origen,
       tr.name AS tabla_destino, cr.name AS columna_destino
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.tables tp  ON tp.object_id = fkc.parent_object_id
JOIN sys.columns cp ON cp.object_id = fkc.parent_object_id
                   AND cp.column_id = fkc.parent_column_id
JOIN sys.tables tr  ON tr.object_id = fkc.referenced_object_id
JOIN sys.columns cr ON cr.object_id = fkc.referenced_object_id
                   AND cr.column_id = fkc.referenced_column_id
ORDER BY tp.name
"""

SQL_CONTEOS = """
SELECT (SELECT COUNT(*) FROM sys.views)     AS n_vistas,
       (SELECT COUNT(*) FROM sys.procedures) AS n_procedimientos
"""


def leer_esquema(lector: LectorSQLServer, con_fechas: bool = True) -> dict:
    print("  Leyendo propiedades del servidor…")
    srv = lector.consultar(SQL_SERVIDOR)[0]
    version_mayor = int(str(srv["version_producto"]).split(".")[0] or 0)
    srv["version"] = f"{srv['edicion']} {srv['version_producto']} ({srv['nivel']})"
    srv["fuera_de_soporte"] = version_mayor <= 11  # 2012 y anteriores

    print("  Leyendo tablas y número de filas…")
    tablas_raw = lector.consultar(SQL_TABLAS)

    print("  Leyendo columnas…")
    columnas = defaultdict(list)
    for c in lector.consultar(SQL_COLUMNAS):
        columnas[(c["esquema"], c["tabla"])].append({
            "nombre": c["columna"], "tipo": c["tipo"],
            "longitud": c["max_length"], "precision": c["precision"],
            "escala": c["scale"], "nulo": bool(c["is_nullable"]),
        })

    print("  Leyendo claves primarias…")
    claves = defaultdict(list)
    for k in lector.consultar(SQL_CLAVES):
        claves[(k["esquema"], k["tabla"])].append(k["columna"])

    print("  Leyendo relaciones…")
    relaciones = lector.consultar(SQL_RELACIONES)
    conteos = lector.consultar(SQL_CONTEOS)[0]

    tablas: list[dict] = []
    for t in tablas_raw:
        clave = (t["esquema"], t["tabla"])
        cols = columnas.get(clave, [])
        familia, punt = clasificar_tabla(t["tabla"], cols, t["filas"])
        tablas.append({
            "esquema": t["esquema"], "nombre": t["tabla"], "filas": int(t["filas"]),
            "columnas": cols, "clave_primaria": claves.get(clave, []),
            "familia": familia, "puntuacion": punt,
        })

    if con_fechas:
        print("  Midiendo cobertura temporal de las tablas relevantes…")
        _medir_fechas(lector, tablas)

    return {
        "generado": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "servidor": srv,
        "tablas": tablas,
        "relaciones": relaciones,
        "n_vistas": conteos["n_vistas"],
        "n_procedimientos": conteos["n_procedimientos"],
    }


def _medir_fechas(lector: LectorSQLServer, tablas: list[dict], minimo_filas: int = 100):
    """MIN y MAX de la primera columna de fecha. Solo en tablas que importan."""
    for t in tablas:
        if t["filas"] < minimo_filas or (not t["familia"] and t["filas"] < 5000):
            continue
        fechas = columnas_por_tipo(t["columnas"], TIPOS_FECHA)
        if not fechas:
            continue
        col = fechas[0]
        try:
            r = lector.consultar(
                f"SELECT MIN([{col}]) AS f_min, MAX([{col}]) AS f_max "
                f"FROM [{t['esquema']}].[{t['nombre']}] WITH (NOLOCK)"
            )[0]
            if r["f_min"]:
                t["columna_fecha"] = col
                t["fecha_min"] = str(r["f_min"])[:10]
                t["fecha_max"] = str(r["f_max"])[:10]
                t["rango_fechas"] = f"{t['fecha_min']} → {t['fecha_max']}"
        except Exception as e:
            t["error"] = str(e)[:120]


def buscar_valor(lector: LectorSQLServer, tablas: list[dict], valor: str,
                 max_tablas: int = 40) -> list[dict]:
    """
    Localiza en qué tabla y columna vive un valor concreto.
    El truco práctico: abre una oferta que reconozcas en el ERP, coge su
    importe y búscalo aquí. En minutos sabes dónde están los presupuestos.
    """
    resultados = []
    candidatas = sorted([t for t in tablas if t["filas"] > 0],
                        key=lambda t: (-t["puntuacion"], -t["filas"]))[:max_tablas]
    for t in candidatas:
        for c in t["columnas"]:
            tipo = c["tipo"].lower()
            if tipo not in TIPOS_TEXTO and tipo not in TIPOS_NUM:
                continue
            try:
                sql = (f"SELECT COUNT(*) AS n FROM [{t['esquema']}].[{t['nombre']}] "
                       f"WITH (NOLOCK) WHERE CAST([{c['nombre']}] AS NVARCHAR(200)) LIKE ?")
                n = lector.consultar(sql, (f"%{valor}%",))[0]["n"]
                if n:
                    resultados.append({
                        "tabla": f"{t['esquema']}.{t['nombre']}",
                        "columna": c["nombre"], "coincidencias": int(n),
                    })
            except Exception:
                continue  # tipo incompatible o sin permisos: se ignora
    return sorted(resultados, key=lambda r: -r["coincidencias"])


def tomar_muestras(lector: LectorSQLServer, tablas: list[dict], n: int = 3) -> dict:
    """Tres filas de las tablas candidatas. Va a un fichero aparte, fuera de git."""
    muestras = {}
    for t in sorted(tablas, key=lambda t: -t["puntuacion"])[:30]:
        if t["puntuacion"] == 0 or t["filas"] == 0:
            continue
        try:
            filas = lector.consultar(
                f"SELECT TOP {n} * FROM [{t['esquema']}].[{t['nombre']}] WITH (NOLOCK)")
            muestras[f"{t['esquema']}.{t['nombre']}"] = filas
        except Exception as e:
            muestras[f"{t['esquema']}.{t['nombre']}"] = {"error": str(e)[:120]}
    return muestras


# --------------------------------------------------------------------------
# Modo simulado: permite ver la salida sin servidor
# --------------------------------------------------------------------------

def esquema_simulado() -> dict:
    def col(nombre, tipo="varchar"):
        return {"nombre": nombre, "tipo": tipo, "longitud": 50,
                "precision": 0, "escala": 0, "nulo": True}

    definicion = [
        ("CLIENTES", 412, ["CODCLI", "RAZON", "NIF", "DIRECCION", "FECHAALTA"],
         {"FECHAALTA": ("2004-02-11", "2026-08-30")}),
        ("PRESUPUESTOS", 18422, ["NUMPPTO", "FECHA", "CODCLI", "TOTAL", "ESTADO"],
         {"FECHA": ("2006-01-09", "2026-09-05")}),
        ("PRESUPUESTOS_LIN", 74188, ["NUMPPTO", "LINEA", "CODART", "CANTIDAD", "PRECIO"], {}),
        ("FACTURAS", 31207, ["NUMFAC", "FECHA", "CODCLI", "BASE", "IVA", "TOTAL"],
         {"FECHA": ("2005-01-03", "2026-09-01")}),
        ("FACTURAS_LIN", 128944, ["NUMFAC", "LINEA", "CODART", "CANTIDAD", "PRECIO"], {}),
        ("ALBARANES", 29880, ["NUMALB", "FECHA", "CODCLI"], {"FECHA": ("2005-01-05", "2026-09-04")}),
        ("ARTICULOS", 9310, ["CODART", "DESCRIPCION", "REFERENCIA", "PESO", "MATERIAL"], {}),
        ("ORDENES_FAB", 22105, ["NUMOF", "CODART", "CANTIDAD", "FECHAINI", "ESTADO"],
         {"FECHAINI": ("2007-03-02", "2026-09-06")}),
        ("PARTES", 402331, ["NUMOF", "CODOPERARIO", "CODMAQUINA", "INICIO", "FIN", "MINUTOS"],
         {"INICIO": ("2011-06-01", "2026-09-05")}),
        ("MAQUINAS", 47, ["CODMAQUINA", "DESCRIPCION", "TARIFA"], {}),
        ("RUTAS", 27655, ["CODART", "SECUENCIA", "CODMAQUINA", "TPREPARACION", "TUNITARIO"], {}),
        ("TMP_CALCULO", 0, ["ID", "VALOR"], {}),
        ("W_LOG_ACCESOS", 88210, ["ID", "USUARIO", "FECHA"], {}),
    ]

    tablas = []
    for nombre, filas, cols, rangos in definicion:
        columnas = []
        for c in cols:
            tipo = ("datetime" if c in rangos or c.startswith(("FECHA", "INICIO", "FIN"))
                    else "decimal" if c in ("TOTAL", "BASE", "IVA", "PRECIO", "CANTIDAD",
                                            "PESO", "TARIFA", "MINUTOS", "TPREPARACION",
                                            "TUNITARIO")
                    else "int" if c.startswith(("NUM", "LINEA", "SECUENCIA"))
                    else "varchar")
            columnas.append(col(c, tipo))
        familia, punt = clasificar_tabla(nombre, columnas, filas)
        t = {
            "esquema": "dbo", "nombre": nombre, "filas": filas, "columnas": columnas,
            "clave_primaria": [cols[0]] if filas else [],
            "familia": familia, "puntuacion": punt,
        }
        for c, (fmin, fmax) in rangos.items():
            t.update(columna_fecha=c, fecha_min=fmin, fecha_max=fmax,
                     rango_fechas=f"{fmin} → {fmax}")
        tablas.append(t)

    return {
        "generado": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "servidor": {
            "base_datos": "QGIS", "edicion": "Standard Edition",
            "version_producto": "13.0.5426.0", "nivel": "SP2",
            "version": "Standard Edition 13.0.5426.0 (SP2)",
            "nivel_compatibilidad": 130, "intercalacion": "Modern_Spanish_CI_AS",
            "tamano_mb": 8421.5, "fuera_de_soporte": False,
        },
        "tablas": tablas,
        "relaciones": [
            {"tabla_origen": "PRESUPUESTOS_LIN", "columna_origen": "NUMPPTO",
             "tabla_destino": "PRESUPUESTOS", "columna_destino": "NUMPPTO"},
            {"tabla_origen": "PRESUPUESTOS", "columna_origen": "CODCLI",
             "tabla_destino": "CLIENTES", "columna_destino": "CODCLI"},
        ],
        "n_vistas": 34, "n_procedimientos": 212,
        "simulado": True,
    }


# --------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------

def guardar(datos: dict, muestras: dict | None = None) -> list[Path]:
    RAIZ_SALIDA.mkdir(parents=True, exist_ok=True)
    escritos = []

    p_json = RAIZ_SALIDA / "esquema.json"
    p_json.write_text(json.dumps(datos, indent=2, ensure_ascii=False, default=str),
                      encoding="utf-8")
    escritos.append(p_json)

    p_md = RAIZ_SALIDA / "informe.md"
    p_md.write_text(construir_informe(datos), encoding="utf-8")
    escritos.append(p_md)

    if muestras:
        p_m = RAIZ_SALIDA / "muestras.json"
        p_m.write_text(json.dumps(muestras, indent=2, ensure_ascii=False, default=str),
                       encoding="utf-8")
        escritos.append(p_m)
    return escritos


def aviso_horario(forzar: bool) -> bool:
    """El taller trabaja de 7:00 a 15:00. Mejor no molestar al servidor entonces."""
    ahora = datetime.now()
    laborable = ahora.weekday() < 5 and 7 <= ahora.hour < 15
    if laborable and not forzar:
        print("\n  AVISO: son horas de taller (7:00-15:00) y hay 41 personas usando el ERP.")
        print("  Aunque esto solo lee, conviene lanzarlo fuera de horario.")
        print("  Si vas contra una COPIA restaurada, no hay problema: usa --forzar.\n")
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Explorador de solo lectura del ERP QGIS")
    ap.add_argument("--simular", action="store_true",
                    help="genera el informe con datos de ejemplo, sin conectar")
    ap.add_argument("--buscar", metavar="VALOR",
                    help="localiza en qué tabla y columna aparece un valor")
    ap.add_argument("--muestras", action="store_true",
                    help="incluye 3 filas de ejemplo por tabla candidata")
    ap.add_argument("--sin-fechas", action="store_true",
                    help="omite el cálculo de cobertura temporal (más rápido)")
    ap.add_argument("--forzar", action="store_true",
                    help="ejecuta aunque sea horario de taller")
    args = ap.parse_args(argv)

    print("\nExplorador del ERP QGIS — solo lectura\n" + "-" * 38)

    if args.simular:
        print("  Modo simulado: no se conecta a ningún servidor.")
        datos = esquema_simulado()
        escritos = guardar(datos)
    else:
        from app.config import ajustes

        if not ajustes.erp_host or not ajustes.erp_usuario:
            print("\n  Faltan credenciales del ERP en .env:")
            print("    ERP_HOST, ERP_BD, ERP_USUARIO, ERP_PASSWORD")
            print("\n  Mientras tanto puedes ver la salida con:  --simular\n")
            return 2

        if not aviso_horario(args.forzar):
            return 3

        print(f"  Conectando a {ajustes.erp_host}/{ajustes.erp_bd} como {ajustes.erp_usuario}…")
        try:
            cn = conectar(ajustes.erp_host, ajustes.erp_bd,
                          ajustes.erp_usuario, ajustes.erp_password)
        except ErrorConexion as e:
            print(f"\n  No se pudo conectar:\n  {e}\n")
            return 1

        try:
            lector = LectorSQLServer(cn)
            datos = leer_esquema(lector, con_fechas=not args.sin_fechas)

            if args.buscar:
                print(f"  Buscando el valor «{args.buscar}»…")
                datos["busqueda"] = {
                    "valor": args.buscar,
                    "resultados": buscar_valor(lector, datos["tablas"], args.buscar),
                }

            muestras = None
            if args.muestras:
                print("  Tomando muestras…")
                muestras = tomar_muestras(lector, datos["tablas"])

            escritos = guardar(datos, muestras)
        finally:
            cn.close()

    n_tablas = len(datos["tablas"])
    n_clasificadas = sum(1 for t in datos["tablas"] if t["familia"])
    print(f"\n  {n_tablas} tablas, {n_clasificadas} clasificadas en alguna familia.")
    for p in escritos:
        print(f"  → {p}")
    print("\n  Abre informe.md y hacemos el mapeo campo a campo.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
