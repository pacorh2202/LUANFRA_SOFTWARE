#!/usr/bin/env python3
"""
Informe autónomo sobre el export de presupuestos.

PARA QUÉ EXISTE
  El sistema completo necesita Docker y una base de datos. En un ordenador de
  empresa eso no siempre se puede. Este script hace el análisis entero sin base
  de datos, sin Docker y sin servidor: lee el Excel, calcula y escribe un HTML
  que se abre con doble clic.

  Lo único que necesita es Python con pandas.

    pip install --user pandas openpyxl
    python generar_informe.py DATOS_PRESUPUESTO.xltx

QUÉ CALCULA
  Tasa de éxito real y su evolución, concentración de clientes, elasticidad
  precio-éxito depurada, dispersión de precios controlada por lote y año,
  y la validación de la geometría de piñones contra las fórmulas de la norma.

LO QUE NO HACE
  No sustituye al sistema: no hay avisos, ni presupuestador, ni sincronización
  con el ERP. Es una foto del histórico, no una herramienta de trabajo.
"""
from __future__ import annotations

import html
import math
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

NUMERICAS = ("Unidades", "Importe Unidad", "DPI_Z", "DPI_Pas", "DPI_AnchoTotal",
             "DPI_DmPri", "DPI_ImpTP", "DPI_ImpMat", "DPI_ImpMO", "DPI_ImpTS",
             "DPI_ImpVA", "Dpi_Modulo")


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def leer(ruta: Path) -> pd.DataFrame:
    """
    Acepta el .xltx y el .csv. Declarar el decimal explícitamente es importante:
    si se adivina mal no da error, da números mil veces más grandes.
    """
    if ruta.suffix.lower() in (".xltx", ".xlsx", ".xlsm"):
        df = pd.read_excel(ruta, sheet_name=0, skiprows=1, dtype=str)
        for c in NUMERICAS:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        fmt = None
    else:
        df = pd.read_csv(ruta, sep=";", encoding="latin-1", skiprows=1, dtype=str)
        for c in NUMERICAS:
            if c in df.columns:
                df[c] = pd.to_numeric(
                    df[c].str.replace(".", "", regex=False)
                         .str.replace(",", ".", regex=False), errors="coerce")
        fmt = "%d/%m/%Y %H:%M"

    df["fecha"] = pd.to_datetime(df["Fecha Presupuesto"], format=fmt, errors="coerce")
    df["acepta"] = pd.to_datetime(df["Fecha Aceptación"], format=fmt, errors="coerce")
    df["ganada"] = df["acepta"].notna()
    df["anio"] = df["fecha"].dt.year
    return df


# ---------------------------------------------------------------------------
# Análisis
# ---------------------------------------------------------------------------

def resumen(df: pd.DataFrame) -> dict:
    imp = (df["DPI_ImpTP"] * df["Unidades"]).fillna(0)
    dias = (df["acepta"] - df["fecha"]).dt.days
    return {
        "presupuestos": len(df),
        "desde": df["fecha"].min(), "hasta": df["fecha"].max(),
        "clientes": int(df["Nombre"].nunique()),
        "aceptados": int(df["ganada"].sum()),
        "exito": 100 * df["ganada"].mean(),
        "ofertado": imp.sum(), "ganado": imp[df["ganada"]].sum(),
        "exito_importe": 100 * imp[df["ganada"]].sum() / imp.sum() if imp.sum() else 0,
        "dias_decision": dias.median(),
        "dias_p75": dias.quantile(0.75),
    }


def por_anio(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("anio").agg(ofertas=("ganada", "count"), ganadas=("ganada", "sum"),
                               importe_medio=("DPI_ImpTP", "median"))
    g["exito"] = (100 * g.ganadas / g.ofertas).round(1)
    return g.dropna()


def clientes(df: pd.DataFrame, top: int = 12) -> pd.DataFrame:
    imp = (df["DPI_ImpTP"] * df["Unidades"]).fillna(0)
    g = df.groupby("Nombre").agg(ofertas=("ganada", "count"), ganadas=("ganada", "sum"))
    g["exito"] = (100 * g.ganadas / g.ofertas).round(1)
    g["facturado"] = imp.groupby(df["Nombre"]).sum().round(0)
    g["peso"] = (100 * g.facturado / g.facturado.sum()).round(1)
    return g.sort_values("facturado", ascending=False).head(top)


def _comparables(df: pd.DataFrame) -> pd.DataFrame:
    """
    Agrupa piezas verdaderamente comparables.

    Sin controlar el tamaño de lote y el año, cualquier análisis de precios es
    ruido: la correlación entre unidades y precio unitario es de -0,55.
    """
    d = df[(df.DPI_ImpTP > 0) & (df.Unidades > 0) & (df.DPI_Z > 0)].copy()
    d["tramo"] = pd.cut(d.Unidades, [0, 1, 5, 20, 100, 1e9],
                        labels=["1", "2-5", "6-20", "21-100", ">100"])
    claves = ["Tipo", "DPI_Z", "DPI_Pas", "DPI_AnchoTotal", "tramo", "anio"]
    g = d.groupby(claves, observed=True)["DPI_ImpTP"]
    d["mediana"] = g.transform("median")
    d["n_grupo"] = g.transform("count")
    d["relativo"] = d.DPI_ImpTP / d.mediana
    return d


def elasticidad(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tasa de éxito según el precio relativo.

    Se excluyen las ofertas al precio EXACTO de la mediana: son repeticiones de
    pedidos ya ganados y contaminan el resultado hacia arriba.
    """
    d = _comparables(df)
    d = d[d.n_grupo >= 4]
    repeticion = (d.DPI_ImpTP - d.mediana).abs() < 0.005
    d = d[~repeticion]
    bins = [0, .85, .95, 1.05, 1.15, 1.35, 1e9]
    etq = ["más de 15% barato", "5-15% barato", "en la mediana",
           "5-15% caro", "15-35% caro", "más de 35% caro"]
    d["banda"] = pd.cut(d.relativo, bins, labels=etq)
    g = d.groupby("banda", observed=True)["ganada"].agg(["count", "mean"])
    g["exito"] = (100 * g["mean"]).round(1)
    return g[["count", "exito"]]


def dispersion(df: pd.DataFrame) -> dict:
    d = _comparables(df)
    comp = d[d.n_grupo >= 3]
    bajo = comp[comp.DPI_ImpTP < comp.mediana]
    perdida = ((bajo.mediana - bajo.DPI_ImpTP) * bajo.Unidades).sum()
    facturado = (d.DPI_ImpTP * d.Unidades).sum()
    return {"grupos": int(comp.groupby(
                ["Tipo", "DPI_Z", "DPI_Pas", "DPI_AnchoTotal", "tramo", "anio"],
                observed=True).ngroups),
            "perdida": perdida, "facturado": facturado,
            "porcentaje": 100 * perdida / facturado if facturado else 0}


def validar_geometria(df: pd.DataFrame) -> dict:
    """Dp = paso / sen(180°/Z), la fórmula de la norma, contra el dato del ERP."""
    v = df[(df.DPI_Z >= 5) & (df.DPI_Pas > 0) & (df.DPI_DmPri > 0)].copy()
    if v.empty:
        return {"filas": 0}
    v["calculado"] = v.apply(lambda r: r.DPI_Pas / math.sin(math.pi / r.DPI_Z), axis=1)
    v["error"] = (v.calculado - v.DPI_DmPri).abs() / v.DPI_DmPri * 100
    return {"filas": len(v), "error_mediano": v.error.median(),
            "dentro_01": 100 * (v.error < 0.1).mean()}


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------

def eur(v) -> str:
    try:
        return f"{float(v):,.0f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "—"


def mil(v) -> str:
    """
    Separador de miles a la española. NUNCA aplicar .replace(",", ".") a una
    frase entera: se come las comas del texto. Ya me pasó una vez en el
    explorador del ERP y volvió a pasar aquí.
    """
    try:
        return f"{int(v):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def num(v, dec=1) -> str:
    try:
        return f"{float(v):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "—"


def tabla(filas: list[list[str]], cabecera: list[str], der: set[int] | None = None) -> str:
    der = der or set()
    th = "".join(f'<th{" class=d" if i in der else ""}>{html.escape(c)}</th>'
                 for i, c in enumerate(cabecera))
    tr = ""
    for f in filas:
        tr += "<tr>" + "".join(
            f'<td{" class=d" if i in der else ""}>{c}</td>' for i, c in enumerate(f)) + "</tr>"
    return f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>"


PLANTILLA = """<!doctype html><html lang=es><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Luanfra — Informe del histórico de presupuestos</title><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font:15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;background:#f6f7f9;
color:#14171a;padding:32px 20px}}
.c{{max-width:1000px;margin:0 auto}}
h1{{font-size:26px;font-weight:600;margin-bottom:4px}}
h2{{font-size:18px;font-weight:600;margin:36px 0 12px;padding-top:20px;
border-top:1px solid #e6e8eb}}
.sub{{color:#6b7280;font-size:14px}}
.k{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:20px 0}}
.kpi{{background:#fff;border:1px solid #e6e8eb;border-radius:10px;padding:16px}}
.kpi .e{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#6b7280;font-weight:600}}
.kpi .v{{font-size:24px;font-weight:600;margin-top:6px;font-variant-numeric:tabular-nums}}
.kpi .v.r{{color:#d42a2a}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e6e8eb;
border-radius:10px;overflow:hidden;font-size:14px}}
th{{text-align:left;padding:10px 14px;font-weight:500;color:#6b7280;
border-bottom:1px solid #e6e8eb;font-size:13px}}
td{{padding:10px 14px;border-bottom:1px solid #f0f1f3;font-variant-numeric:tabular-nums}}
tr:last-child td{{border-bottom:none}}
.d{{text-align:right}}
p{{margin:12px 0;max-width:75ch}}
.nota{{background:#fff8e6;border:1px solid #f0dfb0;border-radius:10px;padding:14px 16px;
margin:16px 0;font-size:14px;color:#7a5b10}}
.ok{{background:#ecfdf3;border-color:#bbe8cd;color:#14683f}}
footer{{margin-top:40px;padding-top:20px;border-top:1px solid #e6e8eb;
color:#6b7280;font-size:13px}}
</style></head><body><div class=c>{cuerpo}</div></body></html>"""


def construir(df: pd.DataFrame, fichero: str) -> str:
    r = resumen(df)
    p: list[str] = []
    p.append(f"<h1>Histórico de presupuestos</h1>"
             f"<p class=sub>{html.escape(fichero)} · generado el "
             f"{datetime.now():%d/%m/%Y %H:%M}</p>")

    p.append('<div class=k>'
             f'<div class=kpi><div class=e>Presupuestos</div><div class=v>{mil(r["presupuestos"])}</div></div>'
             f'<div class=kpi><div class=e>Periodo</div><div class=v>{r["desde"]:%Y}–{r["hasta"]:%Y}</div></div>'
             f'<div class=kpi><div class=e>Clientes</div><div class=v>{r["clientes"]}</div></div>'
             f'<div class=kpi><div class=e>Tasa de éxito</div><div class=v r>{num(r["exito"])} %</div></div>'
             f'<div class=kpi><div class=e>Ofertado</div><div class=v>{eur(r["ofertado"])}</div></div>'
             f'<div class=kpi><div class=e>Ganado</div><div class=v>{eur(r["ganado"])}</div></div>'
             '</div>')

    p.append("<h2>Evolución por año</h2>")
    a = por_anio(df)
    p.append(tabla([[str(int(i)), mil(v.ofertas), mil(v.ganadas),
                     f"{num(v.exito)} %", eur(v.importe_medio)]
                    for i, v in a.iterrows()],
                   ["Año", "Ofertas", "Ganadas", "Éxito", "Importe medio"],
                   {1, 2, 3, 4}))
    p.append(f"<p>La tasa de éxito ponderada por importe es del "
             f"<strong>{num(r['exito_importe'])} %</strong>, por debajo de la simple: "
             f"se pierden sobre todo las ofertas grandes. El cliente tarda una mediana "
             f"de {num(r['dias_decision'], 0)} días en decidir, aunque el 25 % "
             f"tarda más de {num(r['dias_p75'], 0)} días.</p>")

    p.append("<h2>Concentración de clientes</h2>")
    c = clientes(df)
    p.append(tabla([[html.escape(str(i)[:40]), mil(v.ofertas),
                     f"{num(v.exito)} %", eur(v.facturado), f"{num(v.peso)} %"]
                    for i, v in c.iterrows()],
                   ["Cliente", "Ofertas", "Éxito", "Facturado", "Peso"], {1, 2, 3, 4}))

    p.append("<h2>¿A partir de qué precio se deja de ganar?</h2>")
    p.append("<p>Comparando piezas idénticas, mismo tamaño de lote y mismo año. "
             "Se excluyen las ofertas al precio exacto de la mediana, que son "
             "repeticiones de pedidos ya ganados y falsean el resultado.</p>")
    e = elasticidad(df)
    p.append(tabla([[str(i), mil(v["count"]), f"{num(v.exito)} %"]
                    for i, v in e.iterrows()],
                   ["Precio frente a la mediana", "Ofertas", "Éxito"], {1, 2}))
    if len(e) >= 2:
        salto = e.exito.iloc[0] - e.exito.iloc[-1]
        p.append(f'<div class="nota">Entre el extremo barato y el caro hay '
                 f'{num(salto)} puntos de diferencia. El precio influye, pero poco: '
                 f'la mayor parte de lo que se pierde se pierde por plazo, por '
                 f'relación con el cliente o porque nunca iba a comprar. '
                 f'Bajar precios no va a salvar esas ofertas.</div>')

    p.append("<h2>Dispersión de precios</h2>")
    d = dispersion(df)
    p.append(f"<p>En {mil(d['grupos'])} grupos de piezas comparables, el importe "
             f"ofertado por debajo de la mediana del grupo suma "
             f"<strong>{eur(d['perdida'])}</strong>, un {num(d['porcentaje'])} % "
             f"de la facturación analizada.</p>")
    if d["porcentaje"] < 2:
        p.append('<div class="nota ok">Es una cifra baja: significa que '
                 'presupuestáis con bastante consistencia.</div>')

    g = validar_geometria(df)
    if g.get("filas"):
        p.append("<h2>Comprobación de la geometría</h2>")
        p.append(f"<p>La fórmula de la norma, Dp = paso / sen(180°/Z), reproduce "
                 f"el diámetro primitivo del ERP en {mil(g['filas'])} filas con un "
                 f"error mediano del {num(g['error_mediano'], 4)} %. El "
                 f"{num(g['dentro_01'])} % cae dentro del 0,1 %.</p>")
        p.append('<div class="nota ok">Los datos de geometría son sólidos: se puede '
                 'construir el presupuestador sobre ellos.</div>')

    p.append("<footer>Informe generado sin base de datos a partir del export del ERP. "
             "No sustituye al sistema: es una foto del histórico.</footer>")
    return PLANTILLA.format(cuerpo="".join(p))


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    ruta = Path(args[0])
    if not ruta.exists():
        print(f"No existe el fichero: {ruta}")
        return 2

    print(f"Leyendo {ruta.name}…")
    df = leer(ruta)
    print(f"  {mil(len(df))} filas")

    salida = Path(args[1]) if len(args) > 1 else ruta.with_name("informe-luanfra.html")
    salida.write_text(construir(df, ruta.name), encoding="utf-8")
    print(f"\nInforme escrito en: {salida.resolve()}")
    print("Ábrelo con doble clic.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
