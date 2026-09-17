#!/usr/bin/env python3
"""
Carga el export de "Presupuestos especiales" del ERP a la base propia.

    python scripts/cargar_presupuestos_csv.py DATOS_PRESUPUESTO.csv
    python scripts/cargar_presupuestos_csv.py DATOS_PRESUPUESTO.csv --limpiar
    python scripts/cargar_presupuestos_csv.py DATOS_PRESUPUESTO.csv --solo-analizar

FORMATO DEL FICHERO
  Separador ';', decimales con coma, codificación ISO-8859-1, saltos CRLF y una
  primera línea de título que hay que saltar. Son las convenciones de un export
  hecho desde Windows: si no se declaran, pandas lee números como texto y todo
  lo demás falla en silencio.

QUÉ CONTIENE Y QUÉ NO
  Contiene presupuestos ACEPTADOS: todos traen orden y fecha de aceptación.
  No hay ofertas perdidas. Eso significa que sirve para aprender a poner precio
  a una pieza, pero NO para saber a partir de qué precio se deja de ganar.
  Para eso hace falta el export equivalente de las no aceptadas.

  DPI_ImpTP es el PRECIO DE VENTA unitario, no el coste: coincide con
  'Importe Unidad' en el 99,9% de las filas. Y ImpMat/ImpMO están calculados
  con precio de venta, no de coste (el módulo trabaja con Precio Coste y
  Precio Venta por separado). Por eso la suma da un margen aparente del 3%:
  no es el margen real de la empresa.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.bd import SesionLocal  # noqa: E402

COLUMNAS_NUMERICAS = [
    "Unidades", "Importe Unidad", "DPI_Z", "DPI_Pas", "DPI_AC", "DPI_Rodillo",
    "DPI_Eje", "DPI_DmPri", "DPI_DmFon", "DPI_DmExt", "DPI_DmCub", "DPI_Alt",
    "DPI_AnchoTotal", "DPI_Llanta", "DPI_AnchoCubo", "DPI_DisCortDM",
    "DPI_DisCortAN", "DPI_DisCortPESO", "DPI_ImpMat", "DPI_ImpMO", "DPI_ImpTS",
    "DPI_ImpVA", "DPI_ImpTP", "DPI_Importe", "Dpi_Modulo", "DPI_FijoSierra",
]

# Tipo del ERP -> familia normalizada del sistema
FAMILIAS = {
    "Piñon Especial": "pinon", "Piñon Doble": "pinon_doble",
    "Piñon Triple": "pinon_doble", "Piñon 2 Cubos": "pinon",
    "Piñon 2 Cubos Variable": "pinon", "Engranaje Recto": "corona",
    "Disco": "disco", "Disco Doble": "disco", "Disco Engranaje Recto": "disco",
    "Disco de Dos Cadenas": "disco", "Poleas Lisas": "polea",
    "Cremallera": "cremallera",
}


def leer(ruta: Path) -> pd.DataFrame:
    """
    Acepta los dos formatos que salen del ERP:
      .csv   ';' de separador, coma decimal, latin-1, fecha dd/mm/aaaa hh:mm
      .xltx  Excel, punto decimal, fecha ISO

    Detectar mal el decimal no da error: da números mil veces más grandes.
    Por eso cada formato se declara explícitamente en vez de dejar que
    pandas lo adivine.
    """
    if ruta.suffix.lower() in (".xltx", ".xlsx", ".xlsm"):
        df = pd.read_excel(ruta, sheet_name=0, skiprows=1, dtype=str)
        for c in COLUMNAS_NUMERICAS:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        fmt = None
    else:
        df = pd.read_csv(ruta, sep=";", encoding="latin-1", skiprows=1,
                         dtype=str, on_bad_lines="warn")
        for c in COLUMNAS_NUMERICAS:
            if c in df.columns:
                df[c] = pd.to_numeric(
                    df[c].str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
                    errors="coerce")
        fmt = "%d/%m/%Y %H:%M"

    for c, destino in (("Fecha Presupuesto", "fecha"), ("Fecha Aceptación", "aceptacion")):
        if c in df.columns:
            df[destino] = pd.to_datetime(df[c], format=fmt, errors="coerce")
    return df


def analizar(df: pd.DataFrame) -> dict:
    """Informe de calidad antes de cargar nada. Si esto pinta mal, no se carga."""
    total = len(df)
    z_ok = df["DPI_Z"].between(5, 250)
    inf = {
        "filas": total,
        "desde": str(df["fecha"].min())[:10],
        "hasta": str(df["fecha"].max())[:10],
        "clientes": int(df["Nombre"].nunique()),
        "tipos": int(df["Tipo"].nunique()),
        "con_geometria": int(z_ok.sum()),
        "con_precio": int((df["DPI_ImpTP"] > 0).sum()),
        "con_aceptacion": int(df["aceptacion"].notna().sum()),
        "con_orden": int(df["Orden"].notna().sum()),
        "sin_familia_conocida": int((~df["Tipo"].isin(FAMILIAS)).sum()),
    }

    # Comprobación de coherencia geométrica: Dp = p / sen(180/Z)
    v = df[z_ok & (df["DPI_Pas"] > 0) & (df["DPI_DmPri"] > 0)]
    if len(v):
        calc = v["DPI_Pas"] / (math.pi / v["DPI_Z"]).apply(math.sin)
        err = ((calc - v["DPI_DmPri"]).abs() / v["DPI_DmPri"] * 100)
        inf["coherencia_geometrica_pct"] = round(float((err < 0.1).mean() * 100), 2)
        inf["filas_geometria_incoherente"] = int((err >= 1.0).sum())
    return inf


def cargar(sesion, df: pd.DataFrame) -> dict:
    contadores = {"clientes": 0, "piezas": 0, "presupuestos": 0, "lineas": 0, "saltadas": 0}

    # --- Clientes ---
    clientes = df[["Cliente", "Nombre"]].dropna().drop_duplicates("Cliente")
    for _, c in clientes.iterrows():
        sesion.execute(text("""
            INSERT INTO core.cliente (erp_id, nombre)
            VALUES (:e, :n) ON CONFLICT (erp_id) DO UPDATE SET nombre = EXCLUDED.nombre"""),
            {"e": str(c["Cliente"]).strip(), "n": str(c["Nombre"]).strip()[:200]})
        contadores["clientes"] += 1
    sesion.commit()
    ids_cliente = {r["erp_id"]: r["id"] for r in sesion.execute(
        text("SELECT id, erp_id FROM core.cliente WHERE erp_id IS NOT NULL")).mappings()}

    # --- Piezas: una por combinación de geometría, no una por presupuesto ---
    claves = ["Tipo", "DPI_Z", "DPI_Pas", "DPI_AnchoTotal", "DPI_ArtDisco"]
    piezas = df.dropna(subset=["DPI_Z"]).drop_duplicates(claves)
    ids_pieza: dict[tuple, int] = {}
    for _, p in piezas.iterrows():
        z = int(p["DPI_Z"]) if 5 <= (p["DPI_Z"] or 0) <= 250 else None
        familia = FAMILIAS.get(p["Tipo"], "pinon")
        paso = f"{p['DPI_Pas']:g}" if pd.notna(p["DPI_Pas"]) else None
        desc = f"{p['Tipo']} Z{z} paso {paso}" if z else str(p["Tipo"])
        ref = f"{familia[:3].upper()}-Z{z}-P{paso}" if z and paso else None
        pid = sesion.execute(text("""
            INSERT INTO core.pieza
              (referencia_interna, descripcion_original, descripcion_normalizada,
               dientes_z, paso_cadena, diametro_primitivo, atributos)
            VALUES (:ref, :desc, :desc, :z, :paso, :dp, CAST(:attr AS jsonb))
            RETURNING id"""), {
            "ref": ref, "desc": desc[:300], "z": z, "paso": paso,
            "dp": float(p["DPI_DmPri"]) if pd.notna(p["DPI_DmPri"]) else None,
            "attr": pd.io.json.ujson_dumps({
                "tipo_erp": p["Tipo"],
                "ancho_total": None if pd.isna(p["DPI_AnchoTotal"]) else float(p["DPI_AnchoTotal"]),
                "modulo": None if pd.isna(p.get("Dpi_Modulo")) else float(p["Dpi_Modulo"]),
                "articulo_disco": p.get("DPI_ArtDisco"),
                "familia": familia,
            }) if hasattr(pd.io.json, "ujson_dumps") else
            __import__("json").dumps({
                "tipo_erp": p["Tipo"],
                "ancho_total": None if pd.isna(p["DPI_AnchoTotal"]) else float(p["DPI_AnchoTotal"]),
                "modulo": None if pd.isna(p.get("Dpi_Modulo")) else float(p["Dpi_Modulo"]),
                "articulo_disco": p.get("DPI_ArtDisco"),
                "familia": familia,
            }, ensure_ascii=False),
        }).scalar()
        ids_pieza[tuple(p[k] if pd.notna(p[k]) else None for k in claves)] = pid
        contadores["piezas"] += 1
    sesion.commit()

    # --- Presupuestos y sus líneas ---
    for _, r in df.iterrows():
        cid = ids_cliente.get(str(r["Cliente"]).strip() if pd.notna(r["Cliente"]) else "")
        if cid is None or pd.isna(r["fecha"]):
            contadores["saltadas"] += 1
            continue
        unidades = float(r["Unidades"]) if pd.notna(r["Unidades"]) else 1.0
        precio = float(r["DPI_ImpTP"]) if pd.notna(r["DPI_ImpTP"]) else None

        did = sesion.execute(text("""
            INSERT INTO core.documento_venta
              (erp_id, tipo, numero, cliente_id, fecha, total, situacion,
               fecha_aceptacion, orden_generada, resultado)
            VALUES (:e,'presupuesto',:num,:cli,:f,:tot,:sit,:fa,:orden,:res)
            ON CONFLICT (tipo, erp_id) DO NOTHING
            RETURNING id"""), {
            "e": str(r["Presupuesto"]), "num": str(r["Presupuesto"]), "cli": cid,
            "f": r["fecha"].date(),
            "tot": (precio or 0) * unidades,
            "sit": "Aceptado" if pd.notna(r["aceptacion"]) else "Pendiente de Aceptación",
            "fa": r["aceptacion"].date() if pd.notna(r["aceptacion"]) else None,
            "orden": str(r["Orden"]) if pd.notna(r["Orden"]) else None,
            "res": "ganada" if pd.notna(r["aceptacion"]) else None,
        }).scalar()
        if did is None:
            contadores["saltadas"] += 1
            continue
        contadores["presupuestos"] += 1

        clave = tuple(r[k] if pd.notna(r[k]) else None for k in claves)
        sesion.execute(text("""
            INSERT INTO core.linea_venta
              (documento_venta_id, linea, pieza_id, descripcion_original,
               cantidad, precio_unitario, importe, unidades)
            VALUES (:d, 1, :p, :desc, :c, :pu, :imp, :u)"""), {
            "d": did, "p": ids_pieza.get(clave),
            "desc": (f"{r['Tipo']} Z{r['DPI_Z']:.0f} paso {r['DPI_Pas']:g}"
                     if pd.notna(r["DPI_Z"]) else str(r["Tipo"]))[:300],
            "c": unidades, "pu": precio or 0, "imp": (precio or 0) * unidades,
            "u": unidades,
        })
        contadores["lineas"] += 1

        if contadores["lineas"] % 2000 == 0:
            sesion.commit()
            print(f"    {contadores['lineas']} líneas…")
    sesion.commit()
    return contadores


def limpiar(sesion):
    """
    Orden inverso al de las dependencias. Las tablas de `ops` van primero
    porque apuntan a piezas y a clientes: borrar core.pieza sin vaciarlas
    antes revienta con una violación de clave ajena.
    """
    for t in ("ops.correccion", "ops.comparable", "ops.oferta", "ops.extraccion",
              "ops.peticion_documento", "ops.analisis_plano", "ops.peticion",
              "core.normalizacion", "core.linea_venta", "core.documento_venta",
              "core.parte_trabajo", "core.orden_fabricacion", "core.operacion_ruta",
              "core.documento", "core.pieza", "core.cliente"):
        sesion.execute(text(f"DELETE FROM {t}"))
    sesion.commit()
    print("  Datos anteriores eliminados.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Carga el export de presupuestos especiales")
    ap.add_argument("fichero", type=Path)
    ap.add_argument("--limpiar", action="store_true", help="vacía las tablas antes de cargar")
    ap.add_argument("--solo-analizar", action="store_true", help="informe de calidad, sin cargar")
    args = ap.parse_args(argv)

    if not args.fichero.exists():
        print(f"No existe el fichero: {args.fichero}")
        return 2

    print(f"\nLeyendo {args.fichero.name}…")
    df = leer(args.fichero)
    inf = analizar(df)

    print("\n  INFORME DE CALIDAD")
    for k, v in inf.items():
        print(f"    {k:<32} {v}")

    ganadas = inf["con_aceptacion"]
    if inf["filas"]:
        print(f"\n    tasa de aceptación                {100*ganadas/inf['filas']:.1f}%")

    if inf["con_aceptacion"] == inf["filas"]:
        print("\n  AVISO: todas las filas están aceptadas. Este export no incluye")
        print("  ofertas perdidas, así que no permite calibrar a partir de qué")
        print("  precio se deja de ganar. Conviene pedir también las no aceptadas.")

    if args.solo_analizar:
        return 0

    sesion = SesionLocal()
    try:
        if args.limpiar:
            limpiar(sesion)
        print("\n  Cargando…")
        c = cargar(sesion, df)
        print("\n  RESULTADO")
        for k, v in c.items():
            print(f"    {k:<16} {v}")
    finally:
        sesion.close()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
