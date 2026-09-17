"""
Sincronización desde el ERP QGIS.

FILOSOFÍA
  Tiramos (pull), nunca nos empujan. No se instala nada en el servidor del ERP,
  no se crean triggers, no se toca ni una fila. El ERP no se entera de que
  existimos más allá de una conexión de lectura.

TRES CADENCIAS, PORQUE NO TODO CAMBIA IGUAL
  histórico   Una vez, completo. Veinte años de presupuestos y facturas.
              Se repite solo si cambian las reglas de normalización.
  maestros    Cada noche. Clientes, artículos, máquinas, secciones, tarifas.
  operativo   Cada 5-10 minutos. Cola por máquina, estado de máquinas,
              presupuestos y órdenes del día. Es lo que alimenta los plazos.

IDEMPOTENCIA
  Todo se inserta contra `erp_id`. Ejecutar dos veces la misma carga no
  duplica nada: actualiza. Es lo que permite reintentar sin miedo cuando
  se cae la red a media sincronización.

QUÉ HACER SI FALLA
  Una carga fallida no deja `core` a medias: se escribe en `stage` y solo
  cuando la tabla entera ha llegado se promueve. El fallo típico no es
  que reviente: es que lleva cuatro meses fallando en silencio, y por eso
  cada ejecución deja rastro en `stage.carga`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Configuración de tablas
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TablaSincronizada:
    """
    Describe cómo traer una tabla del ERP.

    `origen` y `columnas` se rellenan cuando tengamos el esquema real: el
    explorador (scripts/explorar_erp.py) es el que da los nombres verdaderos.
    Hasta entonces esto documenta la intención y la estructura del proceso.
    """
    nombre: str                     # nombre lógico, p.ej. "clientes"
    origen: str                     # tabla del ERP, p.ej. "dbo.CLIENTES"
    destino: str                    # tabla propia, p.ej. "core.cliente"
    cadencia: str                   # historico | maestros | operativo
    clave_erp: str                  # columna que identifica la fila en el ERP
    columna_incremental: str | None = None   # fecha o rowversion para traer solo lo nuevo
    completa_si_menor_de: int = 5000         # tablas pequeñas: refresco completo
    columnas: tuple[str, ...] = ()

    @property
    def admite_incremental(self) -> bool:
        return self.columna_incremental is not None


CATALOGO: tuple[TablaSincronizada, ...] = (
    # --- maestros: cada noche -------------------------------------------
    TablaSincronizada("clientes",  "dbo.CLIENTES",   "core.cliente",
                      "maestros", "CODCLI", "FECHAMOD"),
    TablaSincronizada("articulos", "dbo.ARTICULOS",  "core.pieza",
                      "maestros", "CODART", "FECHAMOD"),
    TablaSincronizada("secciones", "dbo.SECCIONES",  "core.seccion",
                      "maestros", "CODSECCION"),
    TablaSincronizada("maquinas",  "dbo.MAQUINAS",   "core.centro_trabajo",
                      "maestros", "CODMAQUINA"),
    TablaSincronizada("rutas",     "dbo.RUTAS",      "core.operacion_ruta",
                      "maestros", "ID", "FECHAMOD"),

    # --- histórico: una vez ---------------------------------------------
    TablaSincronizada("presupuestos", "dbo.PRESUPUESTOS", "core.documento_venta",
                      "historico", "NUMPPTO", "FECHA"),
    TablaSincronizada("presupuestos_lin", "dbo.PRESUPUESTOS_LIN", "core.linea_venta",
                      "historico", "ID"),
    TablaSincronizada("facturas",  "dbo.FACTURAS",    "core.documento_venta",
                      "historico", "NUMFAC", "FECHA"),
    TablaSincronizada("facturas_lin", "dbo.FACTURAS_LIN", "core.linea_venta",
                      "historico", "ID"),
    TablaSincronizada("albaranes", "dbo.ALBARANES",   "core.documento_venta",
                      "historico", "NUMALB", "FECHA"),
    TablaSincronizada("partes",    "dbo.PARTES",      "core.parte_trabajo",
                      "historico", "ID", "INICIO"),

    # --- operativo: cada pocos minutos ----------------------------------
    TablaSincronizada("ordenes",   "dbo.ORDENES_FAB", "core.orden_fabricacion",
                      "operativo", "NUMOF", "FECHAMOD"),
    TablaSincronizada("cola",      "dbo.COLA_MAQUINA", "core.cola_maquina",
                      "operativo", "ID"),
    TablaSincronizada("estados",   "dbo.ESTADO_MAQUINA", "core.estado_maquina",
                      "operativo", "CODMAQUINA"),
)


# ---------------------------------------------------------------------------
# Resultado de una ejecución
# ---------------------------------------------------------------------------

@dataclass
class ResultadoCarga:
    tabla: str
    modo: str
    leidas: int = 0
    escritas: int = 0
    error: str | None = None
    segundos: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class ResultadoSincronizacion:
    cadencia: str
    inicio: datetime
    cargas: list[ResultadoCarga] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.cargas)

    def resumen(self) -> dict:
        return {
            "cadencia": self.cadencia,
            "inicio": self.inicio.isoformat(),
            "tablas": len(self.cargas),
            "con_error": sum(1 for c in self.cargas if not c.ok),
            "filas_escritas": sum(c.escritas for c in self.cargas),
            "segundos": round(sum(c.segundos for c in self.cargas), 1),
        }


# ---------------------------------------------------------------------------
# Lógica pura: decidir qué traer
# ---------------------------------------------------------------------------

def decidir_modo(tabla: TablaSincronizada, filas_en_origen: int,
                 ultima_carga: datetime | None) -> str:
    """
    Completa o incremental.

    Una tabla pequeña se trae entera siempre: es más simple y no cuesta nada.
    Una grande solo si nunca se ha traído o si no tiene columna incremental.
    """
    if filas_en_origen <= tabla.completa_si_menor_de:
        return "completa"
    if ultima_carga is None:
        return "completa"
    if not tabla.admite_incremental:
        return "completa"
    return "incremental"


def corte_incremental(ultima_carga: datetime, solape_minutos: int = 15) -> datetime:
    """
    Se retrocede un poco sobre la última carga.

    Motivo: los relojes del servidor y del nuestro no están perfectamente
    sincronizados, y una fila escrita justo durante la carga anterior podría
    quedarse fuera para siempre. Reprocesar quince minutos no cuesta nada
    porque la escritura es idempotente; perder una fila sí cuesta.
    """
    return ultima_carga - timedelta(minutes=solape_minutos)


def construir_consulta(tabla: TablaSincronizada, modo: str,
                       desde: datetime | None = None) -> tuple[str, dict]:
    """Genera el SELECT contra el ERP. Solo lectura, siempre con NOLOCK."""
    columnas = ", ".join(f"[{c}]" for c in tabla.columnas) if tabla.columnas else "*"
    sql = f"SELECT {columnas} FROM {tabla.origen} WITH (NOLOCK)"
    params: dict[str, Any] = {}
    if modo == "incremental" and tabla.columna_incremental and desde:
        sql += f" WHERE [{tabla.columna_incremental}] >= ?"
        params = {"desde": desde}
    return sql, params


def trocear(filas: list, tamano: int = 1000):
    """
    Se escribe por lotes, no fila a fila ni todo de golpe.

    Fila a fila, cuatrocientas mil partes de trabajo tardarían horas.
    Todo de golpe, se come la memoria y un fallo obliga a repetirlo entero.
    """
    for i in range(0, len(filas), tamano):
        yield filas[i:i + tamano]


# ---------------------------------------------------------------------------
# Bitácora
# ---------------------------------------------------------------------------

def abrir_carga(sesion: Session, tabla: TablaSincronizada, modo: str,
                desde: datetime | None) -> int:
    return sesion.execute(text("""
        INSERT INTO stage.carga (tabla_origen, tabla_destino, modo, corte_desde)
        VALUES (:o, :d, :m, :c) RETURNING id"""),
        {"o": tabla.origen, "d": tabla.destino, "m": modo, "c": desde}).scalar()


def cerrar_carga(sesion: Session, carga_id: int, r: ResultadoCarga) -> None:
    sesion.execute(text("""
        UPDATE stage.carga
        SET fin = now(), filas_leidas = :l, filas_escritas = :e,
            estado = :s, error = :err
        WHERE id = :id"""),
        {"id": carga_id, "l": r.leidas, "e": r.escritas,
         "s": "ok" if r.ok else "error", "err": r.error})


def ultima_carga_correcta(sesion: Session, tabla: TablaSincronizada) -> datetime | None:
    return sesion.execute(text("""
        SELECT max(inicio) FROM stage.carga
        WHERE tabla_origen = :o AND estado = 'ok'"""),
        {"o": tabla.origen}).scalar()


def cargas_en_silencio(sesion: Session, horas: int = 36) -> list[dict]:
    """
    Tablas que llevan demasiado tiempo sin una carga correcta.

    Esta consulta existe porque el fallo típico de una sincronización no es
    que reviente con estruendo: es que lleva meses fallando y nadie lo mira.
    """
    filas = sesion.execute(text("""
        SELECT tabla_origen, max(inicio) AS ultima,
               round(EXTRACT(EPOCH FROM (now() - max(inicio))) / 3600) AS horas
        FROM stage.carga
        WHERE estado = 'ok'
        GROUP BY tabla_origen
        HAVING max(inicio) < now() - (:h || ' hours')::interval"""),
        {"h": horas}).mappings().all()
    return [dict(f) for f in filas]


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------

def sincronizar_cadencia(
    sesion: Session,
    cadencia: str,
    leer_erp: Callable[[str, dict], list[dict]],
    contar_erp: Callable[[str], int],
    escribir: Callable[[Session, TablaSincronizada, list[dict]], int],
    catalogo: tuple[TablaSincronizada, ...] = CATALOGO,
) -> ResultadoSincronizacion:
    """
    Ejecuta todas las tablas de una cadencia.

    Las tres funciones se pasan como parámetro para poder probar todo esto
    sin un SQL Server delante: en producción son el lector real; en pruebas,
    funciones que devuelven datos inventados.

    Un fallo en una tabla NO aborta las demás: se anota y se sigue. Es
    preferible tener nueve tablas al día y una vieja, que ninguna.
    """
    resultado = ResultadoSincronizacion(cadencia=cadencia, inicio=datetime.now())

    for tabla in (t for t in catalogo if t.cadencia == cadencia):
        arranque = datetime.now()
        r = ResultadoCarga(tabla=tabla.nombre, modo="completa")
        carga_id = None
        try:
            ultima = ultima_carga_correcta(sesion, tabla)
            total = contar_erp(tabla.origen)
            r.modo = decidir_modo(tabla, total, ultima)
            desde = corte_incremental(ultima) if r.modo == "incremental" and ultima else None

            carga_id = abrir_carga(sesion, tabla, r.modo, desde)
            sesion.commit()

            sql, params = construir_consulta(tabla, r.modo, desde)
            filas = leer_erp(sql, params)
            r.leidas = len(filas)

            for lote in trocear(filas):
                r.escritas += escribir(sesion, tabla, lote)
            sesion.commit()

        except Exception as e:                     # noqa: BLE001
            sesion.rollback()
            r.error = f"{type(e).__name__}: {e}"[:400]
        finally:
            r.segundos = (datetime.now() - arranque).total_seconds()
            if carga_id is not None:
                try:
                    cerrar_carga(sesion, carga_id, r)
                    sesion.commit()
                except Exception:                  # noqa: BLE001
                    sesion.rollback()
            resultado.cargas.append(r)

    return resultado


def escribir_en_stage(sesion: Session, tabla: TablaSincronizada,
                      lote: list[dict]) -> int:
    """
    Escritura por defecto: cada fila del ERP entra en `stage` tal cual, en jsonb.

    Sin transformar. La transformación a `core` es un paso aparte y posterior,
    y por eso podemos reprocesar veinte años cuando mejoren las reglas de
    normalización sin volver a pedir acceso al ERP.
    """
    if not lote:
        return 0
    sesion.execute(text("""
        CREATE TABLE IF NOT EXISTS stage.filas (
          id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          tabla       text NOT NULL,
          clave_erp   text NOT NULL,
          datos       jsonb NOT NULL,
          leido_en    timestamptz NOT NULL DEFAULT now(),
          UNIQUE (tabla, clave_erp)
        )"""))
    filas = [
        {"t": tabla.nombre,
         "k": str(f.get(tabla.clave_erp, "")),
         "d": json.dumps(f, default=str, ensure_ascii=False)}
        for f in lote
    ]
    sesion.execute(text("""
        INSERT INTO stage.filas (tabla, clave_erp, datos)
        VALUES (:t, :k, CAST(:d AS jsonb))
        ON CONFLICT (tabla, clave_erp)
        DO UPDATE SET datos = EXCLUDED.datos, leido_en = now()"""), filas)
    return len(filas)
