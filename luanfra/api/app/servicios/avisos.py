"""
Motor de avisos.

EL PROBLEMA QUE RESUELVE
  En Luanfra la información ya existe. El ERP sabe que una orden lleva el tiempo
  restante en negativo, sabe que un albarán de hace ochenta días sigue sin
  factura y sabe que una oferta de 25.000 € lleva cuatro meses sin contestar.

  Lo que no existe es el camino entre ese dato y la persona que puede hacer algo.
  Alguien tendría que abrir la pantalla correcta, en el momento correcto, y
  fijarse. Y con 41 personas y sesenta máquinas, eso no pasa.

  Este módulo recorre los datos, detecta situaciones y genera avisos con tres
  cosas que un informe no tiene: A QUIÉN le toca, QUÉ hacer y PARA CUÁNDO.

PRINCIPIOS
  1. Un aviso sin acción concreta es ruido. Todos llevan una acción en
     imperativo, no una descripción del problema.
  2. Un aviso sin destinatario no es de nadie. Cada uno tiene un rol dueño.
  3. Mejor avisar antes de que pase. El aviso de un retraso vale cien veces más
     tres días antes que el día de la entrega.
  4. Lo que se repite se agrupa. Veinte avisos iguales son un aviso con veinte
     casos, o nadie los leerá.
  5. Silenciar es legítimo, olvidar no. Un aviso se puede posponer, y vuelve.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Roles: quién tiene capacidad real de resolver cada cosa
# ---------------------------------------------------------------------------

TALLER = "taller"
ADMINISTRACION = "administracion"
COMERCIAL = "comercial"
DIRECCION = "direccion"
OFICINA_TECNICA = "oficina_tecnica"

URGENCIAS = {"critica": 0, "alta": 1, "media": 2, "baja": 3}


@dataclass
class Aviso:
    codigo: str
    titulo: str
    detalle: str
    accion: str                  # siempre en imperativo
    rol: str
    urgencia: str = "media"
    vence: date | None = None
    importe: float | None = None
    referencias: list[str] = field(default_factory=list)
    casos: int = 1
    borrador: dict | None = None   # correo listo para revisar y enviar

    @property
    def orden(self) -> tuple:
        return (URGENCIAS.get(self.urgencia, 9),
                -(self.importe or 0), self.vence or date.max)


# ===========================================================================
# 1. RETRASOS — avisar antes, no después
# ===========================================================================

def avisos_de_plazo(ordenes: list[dict], hoy: date | None = None,
                    dias_de_aviso: int = 3) -> list[Aviso]:
    """
    Tres situaciones distintas, tres avisos distintos.

    La clave está en la primera: una orden que TODAVÍA no ha incumplido pero
    que no va a llegar. Ahí aún se puede reordenar la cola, meter un turno o
    avisar al cliente con margen. Cuando la fecha ya ha pasado, solo queda
    dar explicaciones.
    """
    hoy = hoy or date.today()
    avisos: list[Aviso] = []
    vencidas_sin_avisar: list[dict] = []

    for o in ordenes:
        entrega = o.get("fecha_entrega")
        if not entrega:
            continue
        horas = float(o.get("horas_pendientes") or 0)
        capacidad = _dias_laborables(hoy, entrega) * float(o.get("horas_dia") or 8)
        cliente = o.get("cliente", "—")
        ref = str(o.get("orden", "—"))

        if entrega < hoy:
            if not o.get("cliente_avisado"):
                vencidas_sin_avisar.append(o)
            continue

        if horas > capacidad:
            faltan = round(horas - capacidad, 1)
            dias_margen = (entrega - hoy).days
            avisos.append(Aviso(
                codigo="PLAZO_EN_RIESGO",
                titulo=f"La orden {ref} no llega a la fecha",
                detalle=(f"Quedan {horas:.0f} h de trabajo y solo caben "
                         f"{capacidad:.0f} h antes del {entrega:%d/%m}. "
                         f"Faltan {faltan} h."),
                accion=("Reordena la cola, mete horas, o avisa al cliente hoy "
                        "con una fecha nueva."),
                rol=TALLER,
                urgencia="critica" if dias_margen <= dias_de_aviso else "alta",
                vence=entrega - timedelta(days=dias_de_aviso),
                referencias=[ref],
                borrador=_borrador_retraso(cliente, ref, entrega, horas, capacidad, hoy),
            ))

    if vencidas_sin_avisar:
        importe = sum(float(o.get("importe") or 0) for o in vencidas_sin_avisar)
        peor = min(vencidas_sin_avisar, key=lambda o: o["fecha_entrega"])
        avisos.append(Aviso(
            codigo="VENCIDAS_SIN_AVISAR",
            titulo=f"{len(vencidas_sin_avisar)} órdenes fuera de plazo sin avisar al cliente",
            detalle=(f"La más antigua lleva {(hoy - peor['fecha_entrega']).days} días "
                     f"de retraso. Ningún cliente ha sido informado."),
            accion="Llama tú antes de que llamen ellos. Empieza por la más antigua.",
            rol=DIRECCION, urgencia="critica", importe=importe,
            referencias=[str(o.get("orden", "—")) for o in vencidas_sin_avisar[:10]],
            casos=len(vencidas_sin_avisar),
        ))
    return avisos


def _borrador_retraso(cliente: str, orden: str, entrega: date,
                      horas: float, capacidad: float, hoy: date) -> dict:
    """
    El correo que casi nadie escribe porque da pereza, y que cambia por completo
    cómo se vive un retraso desde el otro lado.
    """
    dias_extra = max(1, int((horas - capacidad) / 8) + 1)
    nueva = _sumar_laborables(entrega, dias_extra)
    return {
        "asunto": f"Pedido {orden} — ajuste de fecha de entrega",
        "cuerpo": (
            f"Buenos días,\n\n"
            f"Le escribo respecto al pedido {orden}, con entrega prevista el "
            f"{entrega:%d/%m/%Y}.\n\n"
            f"Revisando la carga de taller hemos visto que no vamos a poder "
            f"cumplir esa fecha. La nueva previsión es el {nueva:%d/%m/%Y}.\n\n"
            f"Prefiero decírselo ahora, con margen, a avisarle el mismo día. "
            f"Si esa fecha le supone un problema, dígamelo y vemos qué podemos "
            f"reorganizar.\n\n"
            f"Un saludo"),
        "motivo": "aviso proactivo de retraso",
    }


# ===========================================================================
# 2. TALLER PARADO CON TRABAJO PENDIENTE
# ===========================================================================

def avisos_de_carga(centros: list[dict]) -> list[Aviso]:
    """
    Detecta el desequilibrio: una máquina parada mientras otra va ahogada.

    Es el problema de "hay gente parada y a la vez vamos tarde". Nadie lo ve
    porque el ERP enseña una máquina cada vez, y para verlo hay que comparar.
    """
    avisos: list[Aviso] = []
    internos = [c for c in centros if not c.get("externo")]
    if len(internos) < 2:
        return avisos

    dias = {}
    for c in internos:
        capacidad = float(c.get("horas_dia") or 8) * 60 * float(c.get("disponibilidad") or 0.7)
        dias[c["codigo"]] = (float(c.get("minutos_cola") or 0) / capacidad) if capacidad else 0

    if not dias:
        return avisos
    saturado = max(dias, key=dias.get)
    libre = min(dias, key=dias.get)

    if dias[saturado] > 10 and dias[libre] < 2:
        avisos.append(Aviso(
            codigo="CARGA_DESEQUILIBRADA",
            titulo=f"{libre} vacío mientras {saturado} va ahogado",
            detalle=(f"{saturado} tiene {dias[saturado]:.0f} días de cola y "
                     f"{libre} menos de {max(dias[libre], 0.5):.0f}."),
            accion=f"Mira si algo de la cola de {saturado} puede pasar a {libre}.",
            rol=TALLER, urgencia="alta",
            referencias=[saturado, libre],
        ))

    for c in internos:
        disp = float(c.get("disponibilidad") or 1)
        if disp < 0.55 and float(c.get("minutos_cola") or 0) > 0:
            avisos.append(Aviso(
                codigo="DISPONIBILIDAD_BAJA",
                titulo=f"{c['codigo']} solo produce el {disp*100:.0f}% del tiempo",
                detalle=("Con trabajo en cola, esa máquina está parada más de la "
                         "mitad de su jornada."),
                accion="Averigua por qué: avería, falta de material, o preparación.",
                rol=TALLER, urgencia="media", referencias=[c["codigo"]],
            ))
    return avisos


# ===========================================================================
# 3. DINERO PARADO
# ===========================================================================

def avisos_de_facturacion(entregas_sin_factura: list[dict],
                          hoy: date | None = None,
                          umbral_dias: int = 5) -> list[Aviso]:
    """El problema de los 90 días, convertido en una lista de acciones."""
    hoy = hoy or date.today()
    pendientes = [e for e in entregas_sin_factura
                  if e.get("fecha_albaran")
                  and (hoy - e["fecha_albaran"]).days > umbral_dias]
    if not pendientes:
        return []

    importe = sum(float(e.get("importe") or 0) for e in pendientes)
    mas_antigua = min(pendientes, key=lambda e: e["fecha_albaran"])
    dias = (hoy - mas_antigua["fecha_albaran"]).days

    avisos = [Aviso(
        codigo="ENTREGADO_SIN_FACTURAR",
        titulo=f"{importe:,.0f} € entregados y sin facturar".replace(",", "."),
        detalle=(f"{len(pendientes)} albaranes pendientes. El más antiguo lleva "
                 f"{dias} días esperando."),
        accion="Emite hoy las facturas de los albaranes de más de una semana.",
        rol=ADMINISTRACION,
        urgencia="critica" if dias > 45 else "alta",
        importe=importe, casos=len(pendientes),
        referencias=[str(e.get("albaran", "—")) for e in pendientes[:10]],
    )]

    # Cortes de facturación: llegar tarde al corte cuesta un mes de cobro
    for corte in _cortes_proximos(pendientes, hoy):
        avisos.append(corte)
    return avisos


def _cortes_proximos(pendientes: list[dict], hoy: date,
                     dias_aviso: int = 4) -> list[Aviso]:
    por_cliente: dict[str, list[dict]] = {}
    for e in pendientes:
        if e.get("dia_corte"):
            por_cliente.setdefault(e["cliente"], []).append(e)

    avisos = []
    for cliente, lista in por_cliente.items():
        dia = int(lista[0]["dia_corte"])
        faltan = dia - hoy.day
        if 0 <= faltan <= dias_aviso:
            importe = sum(float(e.get("importe") or 0) for e in lista)
            avisos.append(Aviso(
                codigo="CORTE_DE_FACTURACION",
                titulo=f"Quedan {faltan} días para el corte de {cliente}",
                detalle=(f"{importe:,.0f} € sin facturar. Si no entra antes del día "
                         f"{dia}, se cobra un mes más tarde.").replace(",", "."),
                accion=f"Factura hoy lo de {cliente}.",
                rol=ADMINISTRACION, urgencia="critica" if faltan <= 1 else "alta",
                importe=importe, casos=len(lista),
            ))
    return avisos


# ===========================================================================
# 4. OFERTAS Y COMUNICACIÓN CON EL CLIENTE
# ===========================================================================

def avisos_comerciales(ofertas: list[dict], hoy: date | None = None) -> list[Aviso]:
    """
    Con una tasa de éxito del 27%, cada oferta viva sin seguimiento es dinero
    dormido. Y hay clientes que consumen horas sin comprar nunca.
    """
    hoy = hoy or date.today()
    avisos: list[Aviso] = []

    para_llamar = [o for o in ofertas
                   if o.get("fecha") and 12 <= (hoy - o["fecha"]).days <= 35
                   and not o.get("seguimiento")]
    if para_llamar:
        para_llamar.sort(key=lambda o: -float(o.get("importe") or 0))
        importe = sum(float(o.get("importe") or 0) for o in para_llamar)
        avisos.append(Aviso(
            codigo="OFERTAS_PARA_SEGUIR",
            titulo=f"{len(para_llamar)} ofertas en el momento bueno para llamar",
            detalle=(f"{importe:,.0f} € en juego. Entre la segunda y la cuarta "
                     f"semana es cuando más se convierte.").replace(",", "."),
            accion=f"Empieza por {para_llamar[0].get('cliente','—')}: "
                   f"{float(para_llamar[0].get('importe') or 0):,.0f} €".replace(",", "."),
            rol=COMERCIAL, urgencia="alta", importe=importe, casos=len(para_llamar),
        ))

    # Clientes que piden mucho y compran poco
    por_cliente: dict[str, dict] = {}
    for o in ofertas:
        c = por_cliente.setdefault(o.get("cliente", "—"), {"n": 0, "ganadas": 0})
        c["n"] += 1
        c["ganadas"] += 1 if o.get("ganada") else 0
    for cliente, d in por_cliente.items():
        if d["n"] >= 50:
            tasa = d["ganadas"] / d["n"]
            if tasa < 0.12:
                avisos.append(Aviso(
                    codigo="CLIENTE_POCO_RENTABLE",
                    titulo=f"{cliente} pide mucho y compra poco",
                    detalle=(f"{d['n']} ofertas y solo un {tasa*100:.0f}% aceptadas. "
                             f"Cada una consume tiempo de oficina técnica."),
                    accion=("Decide: precio mínimo para ese cliente, o priorizar "
                            "sus peticiones por detrás del resto."),
                    rol=DIRECCION, urgencia="media", casos=d["n"],
                    referencias=[cliente],
                ))
    return avisos


# ===========================================================================
# 5. PLANOS BLOQUEADOS
# ===========================================================================

def avisos_tecnicos(peticiones: list[dict], hoy: date | None = None) -> list[Aviso]:
    """
    Un plano incompleto detectado y no consultado es peor que no detectarlo:
    el problema estaba visto y aun así llegó al taller.
    """
    hoy = hoy or date.today()
    bloqueadas = [p for p in peticiones
                  if p.get("bloqueantes", 0) > 0 and not p.get("consulta_enviada")]
    if not bloqueadas:
        return []
    mas_vieja = min(bloqueadas, key=lambda p: p.get("recibida", hoy))
    dias = (hoy - mas_vieja.get("recibida", hoy)).days
    return [Aviso(
        codigo="PLANOS_SIN_CONSULTAR",
        titulo=f"{len(bloqueadas)} peticiones paradas por un plano incompleto",
        detalle=(f"La más antigua lleva {dias} días. Cada día de espera es un día "
                 f"que el cliente no sabe nada de nosotros."),
        accion="Manda las consultas técnicas hoy: ya están redactadas.",
        rol=OFICINA_TECNICA, urgencia="alta" if dias > 2 else "media",
        casos=len(bloqueadas),
        referencias=[str(p.get("referencia", "—")) for p in bloqueadas[:10]],
    )]


# ===========================================================================
# Bandejas
# ===========================================================================

def recopilar(**fuentes) -> list[Aviso]:
    """Junta todos los avisos y los ordena por lo que más urge."""
    avisos: list[Aviso] = []
    avisos += avisos_de_plazo(fuentes.get("ordenes", []))
    avisos += avisos_de_carga(fuentes.get("centros", []))
    avisos += avisos_de_facturacion(fuentes.get("entregas_sin_factura", []))
    avisos += avisos_comerciales(fuentes.get("ofertas", []))
    avisos += avisos_tecnicos(fuentes.get("peticiones", []))
    return sorted(avisos, key=lambda a: a.orden)


def bandeja(avisos: list[Aviso], rol: str) -> list[Aviso]:
    """
    Cada uno ve solo lo suyo.

    Una bandeja con treinta avisos de los que veintisiete no te tocan es una
    bandeja que se deja de mirar a la semana.
    """
    return [a for a in avisos if a.rol == rol]


def resumen_diario(avisos: list[Aviso]) -> dict:
    """El parte de la mañana: qué arde hoy."""
    por_rol: dict[str, int] = {}
    for a in avisos:
        por_rol[a.rol] = por_rol.get(a.rol, 0) + 1
    criticos = [a for a in avisos if a.urgencia == "critica"]
    return {
        "total": len(avisos),
        "criticos": len(criticos),
        "por_rol": por_rol,
        "dinero_en_juego": round(sum(a.importe or 0 for a in avisos), 2),
        "lo_primero": criticos[0].titulo if criticos else
                      (avisos[0].titulo if avisos else "Nada urgente hoy."),
    }


# ===========================================================================
# Auxiliares de calendario
# ===========================================================================

def _dias_laborables(desde: date, hasta: date) -> int:
    if hasta <= desde:
        return 0
    dias, cursor = 0, desde
    while cursor < hasta:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            dias += 1
    return dias


def _sumar_laborables(desde: date, dias: int) -> date:
    cursor, restantes = desde, dias
    while restantes > 0:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            restantes -= 1
    return cursor
