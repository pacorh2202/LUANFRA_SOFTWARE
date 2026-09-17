"""Diagnóstico conservador de exportaciones ERP; nunca escribe en la BD.

El export esperado contiene una fila física por orden. Filas multilínea,
desplazadas o con caracteres inválidos se apartan, nunca se reparan a ciegas.
Los valores económicos se conservan como campos sin asumir su significado.
"""
import csv
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

CAMPOS = ["AGP", "Orden", "Unidades", "Cliente", "Fecha Inicio", "Fecha Entrega",
          "Referencia", "S/pedido", "Tipo", "Descripcion del trabajo",
          "Descripcion del articulo", "Valoración", "CosteUnidad", "BATCH"]


def diagnosticar(ruta: str | Path) -> dict:
    contenido = Path(ruta).read_bytes()
    codificacion = "utf-8-sig"
    try:
        texto = contenido.decode(codificacion)
    except UnicodeDecodeError:
        codificacion = "cp1252"
        texto = contenido.decode(codificacion, errors="replace")
    aceptadas = []
    incidencias = []
    cabecera = False
    for numero, linea in enumerate(texto.splitlines(), 1):
        if not linea.strip():
            continue
        try:
            fila = next(csv.reader([linea], delimiter=";", strict=True))
        except csv.Error:
            incidencias.append({"linea": numero, "motivo": "comillas o fila multilínea"})
            continue
        if fila[:14] == CAMPOS:
            cabecera = True
            continue
        if not cabecera:
            if numero == 1 and fila[0] == "Listado de Ordenes":
                continue
            raise ValueError("Cabecera no reconocida; no importar")
        motivo = None
        if "\ufffd" in linea:
            motivo = "codificación inválida"
        elif len(fila) < 14 or any(fila[14:]):
            motivo = "columnas desplazadas"
        else:
            dato = dict(zip(CAMPOS, fila))
            try:
                if not dato["Orden"].isdigit() or not dato["Cliente"].strip():
                    raise ValueError()
                if dato["Tipo"] not in ("Producción", "Interna", "Fabricación"):
                    raise ValueError()
                for campo in ("Fecha Inicio", "Fecha Entrega"):
                    if dato[campo]:
                        fecha = datetime.strptime(dato[campo].split()[0], "%d/%m/%Y")
                        if not 1990 <= fecha.year <= datetime.now().year + 1:
                            raise ValueError()
                    elif campo == "Fecha Inicio":
                        raise ValueError()
                for campo in ("Unidades", "Valoración", "CosteUnidad"):
                    if not dato[campo] and campo != "Unidades":
                        continue
                    n = Decimal(dato[campo].replace(",", "."))
                    if not n.is_finite() or n < 0 or (campo == "Unidades" and n <= 0):
                        raise ValueError()
            except (ValueError, InvalidOperation):
                motivo = "identidad, fecha, tipo o número incoherente"
        if motivo:
            incidencias.append({"linea": numero, "motivo": motivo})
        else:
            aceptadas.append((numero, dato))
    if not cabecera:
        raise ValueError("Falta cabecera")
    frecuencias = Counter(d["Orden"] for _, d in aceptadas)
    unicas = []
    for numero, dato in aceptadas:
        if frecuencias[dato["Orden"]] > 1:
            incidencias.append({"linea": numero, "motivo": "orden duplicada; revisar clave ERP"})
        else:
            unicas.append(dato)
    return {
        "codificacion": codificacion,
        "filas_validas_estructuralmente": len(unicas),
        "filas_apartadas": len(incidencias),
        "motivos": dict(Counter(i["motivo"] for i in incidencias)),
        "incidencias": incidencias,
        "campos": CAMPOS,
        "escribe_base_datos": False,
        "pendientes": ["Significado y unidad de Valoración y CosteUnidad",
                       "Fecha Entrega prevista o real", "Relación con partes de fabricación"],
    }
