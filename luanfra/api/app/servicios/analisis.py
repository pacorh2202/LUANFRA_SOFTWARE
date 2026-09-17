"""
Análisis de negocio.

Cuatro cosas que vuestros datos ya contienen y que hoy nadie mira, porque el
ERP las enseña de una en una y nadie las agrega.

Todo son funciones puras: reciben listas de números y devuelven conclusiones.
Las consultas viven en las rutas; aquí solo está el razonamiento, que es lo que
hay que poder defender delante de un cliente o de dirección.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta


# ===========================================================================
# 1. DISPERSIÓN DE PRECIOS
#    La misma pieza ofertada a precios distintos a lo largo de los años.
#    Es el dinero que se escapa sin que nadie lo note.
# ===========================================================================

@dataclass
class Dispersion:
    referencia: str
    veces: int
    minimo: float
    maximo: float
    mediana: float
    coef_variacion: float          # desviación / media
    recorrido_pct: float           # (max-min)/min
    perdida_estimada: float        # lo que se dejó de cobrar contra la mediana
    gravedad: str                  # "alta" | "media" | "baja"
    motivo: str


def analizar_dispersion(referencia: str, precios: list[float],
                        umbral_alto: float = 0.25) -> Dispersion | None:
    """
    Mide cuánto varía el precio de una misma pieza.

    La pérdida se calcula contra la MEDIANA, no contra el máximo: el máximo
    puede ser un caso raro (urgencia, lote de una unidad) y usarlo inflaría
    la cifra hasta volverla inútil. La mediana es lo que se cobra normalmente.

    Solo se computa como pérdida lo ofertado POR DEBAJO de la mediana. Cobrar
    de más algún día no compensa: son clientes distintos y ofertas distintas.
    """
    limpios = [p for p in precios if p and p > 0]
    if len(limpios) < 3:
        return None

    minimo, maximo = min(limpios), max(limpios)
    mediana = statistics.median(limpios)
    media = statistics.fmean(limpios)
    desv = statistics.pstdev(limpios)
    coef = desv / media if media else 0.0
    recorrido = (maximo - minimo) / minimo if minimo else 0.0
    perdida = sum(mediana - p for p in limpios if p < mediana)

    if coef >= umbral_alto and recorrido >= 0.40:
        gravedad = "alta"
        motivo = (f"El precio va de {minimo:,.0f} a {maximo:,.0f} €. "
                  f"Se ha ofertado la misma pieza con un {recorrido*100:.0f}% de diferencia.")
    elif coef >= umbral_alto / 2:
        gravedad = "media"
        motivo = "Variación apreciable entre ofertas de la misma pieza."
    else:
        gravedad = "baja"
        motivo = "Precio estable."

    return Dispersion(
        referencia=referencia, veces=len(limpios),
        minimo=round(minimo, 2), maximo=round(maximo, 2), mediana=round(mediana, 2),
        coef_variacion=round(coef, 4), recorrido_pct=round(recorrido, 4),
        perdida_estimada=round(perdida, 2), gravedad=gravedad,
        motivo=motivo.replace(",", "."),
    )


# ===========================================================================
# 2. SEGUIMIENTO DE OFERTAS ABIERTAS
#    Presupuestos enviados que nadie ha vuelto a tocar.
# ===========================================================================

@dataclass
class Seguimiento:
    oferta_id: int
    cliente: str
    importe: float
    dias_abierta: int
    prioridad: float
    accion: str


def prioridad_seguimiento(importe: float, dias_abierta: int,
                          tasa_exito_cliente: float = 0.5,
                          caducidad_dias: int = 90) -> tuple[float, str]:
    """
    Ordena a quién llamar primero.

    Tres factores: cuánto vale, cuánto lleva esperando y cómo suele responder
    ese cliente. El tiempo pesa en curva: llamar al tercer día es pronto y al
    nonagésimo es tarde; el punto dulce está entre la segunda y la cuarta semana.
    """
    if dias_abierta < 5:
        ventana = 0.2
        accion = "Aún es pronto para insistir."
    elif dias_abierta <= 35:
        ventana = 1.0
        accion = "Momento bueno para llamar."
    elif dias_abierta <= caducidad_dias:
        ventana = 0.6
        accion = "Se está enfriando: última oportunidad de rescatarla."
    else:
        ventana = 0.15
        accion = "Darla por perdida y registrarla como tal."

    peso_importe = min(1.0, importe / 10_000) if importe else 0.0
    prioridad = round(peso_importe * ventana * (0.4 + 0.6 * tasa_exito_cliente), 4)
    return prioridad, accion


def ordenar_seguimiento(ofertas: list[dict], hoy: date | None = None) -> list[Seguimiento]:
    hoy = hoy or date.today()
    salida = []
    for o in ofertas:
        dias = (hoy - o["fecha"]).days
        p, accion = prioridad_seguimiento(
            float(o.get("importe") or 0), dias, float(o.get("tasa_exito", 0.5)))
        salida.append(Seguimiento(
            oferta_id=o["id"], cliente=o.get("cliente", "—"),
            importe=round(float(o.get("importe") or 0), 2),
            dias_abierta=dias, prioridad=p, accion=accion))
    return sorted(salida, key=lambda s: -s.prioridad)


# ===========================================================================
# 3. RIESGO DE RETRASO
#    El ERP muestra el tiempo restante máquina a máquina. Nadie lo suma.
# ===========================================================================

@dataclass
class RiesgoOrden:
    orden: str
    cliente: str
    fecha_entrega: date
    dias: int                      # negativo = ya fuera de plazo
    horas_pendientes: float
    estado: str                    # "vencida" | "critica" | "ajustada" | "holgada"
    mensaje: str


def clasificar_riesgo(fecha_entrega: date, horas_pendientes: float,
                      horas_utiles_dia: float = 8.0,
                      hoy: date | None = None) -> RiesgoOrden:
    """
    Compara lo que falta por hacer con el tiempo que queda de verdad.

    Se cuentan días laborables, no naturales: prometer para el lunes lo que
    necesita dos días cuando hoy es viernes es cómo se incumplen los plazos.
    """
    hoy = hoy or date.today()
    dias = _dias_laborables(hoy, fecha_entrega)
    capacidad = dias * horas_utiles_dia

    if fecha_entrega < hoy:
        estado = "vencida"
        mensaje = f"Vencida hace {(hoy - fecha_entrega).days} días."
    elif capacidad <= 0 or horas_pendientes > capacidad:
        estado = "critica"
        mensaje = (f"Faltan {horas_pendientes:.0f} h y solo caben {capacidad:.0f} h "
                   f"antes de la entrega.")
    elif horas_pendientes > capacidad * 0.75:
        estado = "ajustada"
        mensaje = "Llega, pero sin margen para ninguna incidencia."
    else:
        estado = "holgada"
        mensaje = "Con margen."

    return RiesgoOrden(orden="", cliente="", fecha_entrega=fecha_entrega,
                       dias=dias if fecha_entrega >= hoy else -(hoy - fecha_entrega).days,
                       horas_pendientes=round(horas_pendientes, 2),
                       estado=estado, mensaje=mensaje)


def _dias_laborables(desde: date, hasta: date) -> int:
    if hasta <= desde:
        return 0
    dias, cursor = 0, desde
    while cursor < hasta:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            dias += 1
    return dias


def resumen_retrasos(ordenes: list[RiesgoOrden]) -> dict:
    """La cifra global que hoy no tiene nadie."""
    por_estado: dict[str, int] = {}
    for o in ordenes:
        por_estado[o.estado] = por_estado.get(o.estado, 0) + 1
    vencidas = [o for o in ordenes if o.estado == "vencida"]
    return {
        "total": len(ordenes),
        "por_estado": por_estado,
        "vencidas": len(vencidas),
        "horas_en_riesgo": round(
            sum(o.horas_pendientes for o in ordenes if o.estado in ("vencida", "critica")), 1),
        "peor_retraso_dias": min((o.dias for o in vencidas), default=0),
    }


# ===========================================================================
# 4. DERIVA DE CLIENTE
#    Un margen que se erosiona trimestre a trimestre se ve con meses de
#    antelación si alguien mira los datos. Nadie los mira.
# ===========================================================================

@dataclass
class Deriva:
    cliente: str
    periodos: int
    primero: float
    ultimo: float
    pendiente: float               # variación media por periodo, en puntos
    tendencia: str                 # "cae" | "estable" | "mejora"
    aviso: str | None = None
    serie: list[float] = field(default_factory=list)


def analizar_deriva(cliente: str, serie: list[float],
                    umbral_puntos: float = 1.5) -> Deriva | None:
    """
    Regresión lineal simple sobre la serie de márgenes por periodo.

    Se usa la pendiente y no la diferencia entre el primero y el último porque
    un trimestre malo aislado no es una tendencia, y con la diferencia lo
    parecería. La pendiente solo se mueve si el patrón se repite.
    """
    limpia = [float(x) for x in serie if x is not None]
    if len(limpia) < 3:
        return None

    n = len(limpia)
    xs = list(range(n))
    mx, my = statistics.fmean(xs), statistics.fmean(limpia)
    denom = sum((x - mx) ** 2 for x in xs)
    pendiente = sum((x - mx) * (y - my) for x, y in zip(xs, limpia)) / denom if denom else 0.0

    if pendiente <= -umbral_puntos:
        tendencia = "cae"
        aviso = (f"El margen de {cliente} pierde {abs(pendiente):.1f} puntos por periodo. "
                 f"De {limpia[0]:.1f}% a {limpia[-1]:.1f}%. Conviene revisar precios.")
    elif pendiente >= umbral_puntos:
        tendencia, aviso = "mejora", None
    else:
        tendencia, aviso = "estable", None

    return Deriva(cliente=cliente, periodos=n, primero=round(limpia[0], 2),
                  ultimo=round(limpia[-1], 2), pendiente=round(pendiente, 3),
                  tendencia=tendencia, aviso=aviso, serie=[round(x, 2) for x in limpia])
