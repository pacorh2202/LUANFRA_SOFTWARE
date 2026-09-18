"""Propuestas auditables de ruta. Nunca despacha órdenes ni controla CNC.

Cada alternativa requiere validación de método, amarre, herramientas y acceso.
Se comparan dos heurísticas secuenciales; no es optimización global ni APS.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, model_validator
from app.servicios.motor_coste import EntradaCoste, Operacion, calcular
from app.servicios.plazos import ColaCentro, CargaPedido, calcular as calcular_plazo

Positivo = Annotated[Decimal, Field(ge=0.000001, le=100000000, allow_inf_nan=False)]
NoNegativo = Annotated[Decimal, Field(ge=0, le=100000000, allow_inf_nan=False)]
Texto = Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]
Vector = tuple[Positivo, Positivo, Positivo]


class Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Maquina(Modelo):
    codigo: Texto
    procesos: set[Texto] = Field(min_length=1)
    materiales: set[Texto] = Field(min_length=1)
    # Envolvente útil, ejes en orientación de amarre confirmada, no tamaño de mesa.
    envolvente_util_mm: Vector
    activa: bool = True
    coste_hora_integral: Positivo | None = None
    referencia_tarifa: Texto | None = None
    tarifa_desde: date | None = None
    tarifa_hasta: date | None = None
    minutos_cola: NoNegativo | None = None
    carga_leida_en: AwareDatetime | None = None
    horas_dia: Annotated[Decimal, Field(gt=0, le=10, allow_inf_nan=False)]
    disponibilidad: Annotated[Decimal, Field(gt=0, le=1, allow_inf_nan=False)]


class Alternativa(Modelo):
    maquina: Texto
    envolvente_amarre_mm: Vector  # Incluye bruto y utillaje en orientación propuesta.
    preparacion_min: NoNegativo
    ciclo_min: Positivo
    origen_tiempo: Literal["medido", "calibrado", "manual", "teorico"]
    referencia_tiempo: Texto
    validacion_tecnica: Texto | None = None  # Referencia de revisión, nunca inferida por tamaño.


class Paso(Modelo):
    id: Texto
    proceso: Texto
    evidencia: Texto  # Cara STEP / página y llamada PDF / revisión técnica.
    alternativas: list[Alternativa] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unicas(self):
        if len({a.maquina for a in self.alternativas}) != len(self.alternativas):
            raise ValueError("Máquina repetida en alternativas de una operación")
        return self


class Economia(Modelo):
    peso_bruto_kg: Positivo | None = None  # Por pieza; bruto confirmado, no volumen neto STEP.
    precio_kg: Positivo | None = None
    merma_pct: Annotated[Decimal, Field(ge=0, le=1000, allow_inf_nan=False)] = Decimal(0)
    programacion_lote: NoNegativo | None = None
    herramientas_lote: NoNegativo | None = None
    calidad_lote: NoNegativo | None = None
    subcontrata_lote: NoNegativo | None = None
    transporte_lote: NoNegativo | None = None
    otros_lote: NoNegativo | None = None
    indirectos_pct: Annotated[Decimal, Field(ge=0, le=1000, allow_inf_nan=False)]
    margen_pct: Annotated[Decimal, Field(ge=0, le=1000, allow_inf_nan=False)]
    politica: Literal["recargo_coste", "margen_venta"]

    @model_validator(mode="after")
    def margen(self):
        if self.politica == "margen_venta" and self.margen_pct >= 100:
            raise ValueError("Margen sobre venta menor de 100 requerido")
        return self


class PeticionDecision(Modelo):
    expediente_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: Texto
    material: Texto
    cantidad: int = Field(strict=True, gt=0, le=1000000)
    # Esta declaración corresponde al revisor técnico; no certifica el extractor.
    revision_tecnica: Texto | None = None
    bloqueos_documentales: list[Texto] = Field(default_factory=list, max_length=100)
    desde: date
    festivos: set[date] = Field(default_factory=set, max_length=400)
    colchon_pct: Annotated[Decimal, Field(ge=0, le=200, allow_inf_nan=False)] = Decimal(50)
    maquinas: list[Maquina] = Field(min_length=1, max_length=200)
    operaciones: list[Paso] = Field(min_length=1, max_length=100)
    economia: Economia

    @model_validator(mode="after")
    def identificadores(self):
        for ids in ([m.codigo for m in self.maquinas], [p.id for p in self.operaciones]):
            if len(set(ids)) != len(ids):
                raise ValueError("Identificadores duplicados")
        return self


def dinero(n):
    return n.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def decidir(p: PeticionDecision, ahora: datetime | None = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    maquinas = {m.codigo: m for m in p.maquinas}
    bloqueos = list(p.bloqueos_documentales)
    if not p.revision_tecnica:
        bloqueos.append("Falta revisión conjunta STEP/PDF y confirmación de ruta completa")
    if p.desde < ahora.date():
        bloqueos.append("La fecha de planificación está en el pasado")
    candidatos, descartes = {}, []
    for paso in p.operaciones:
        candidatos[paso.id] = []
        for a in paso.alternativas:
            m = maquinas.get(a.maquina)
            motivos = []
            if m is None:
                motivos.append("Máquina no inventariada")
            else:
                if not m.activa:
                    motivos.append("Máquina inactiva")
                if paso.proceso not in m.procesos:
                    motivos.append("Proceso no habilitado")
                if p.material not in m.materiales:
                    motivos.append("Material no habilitado")
                if any(x > limite for x, limite in zip(a.envolvente_amarre_mm, m.envolvente_util_mm)):
                    motivos.append("Bruto y amarre exceden la envolvente útil")
                if m.minutos_cola is None or m.carga_leida_en is None:
                    motivos.append("Faltan datos de carga; desconocido no equivale a cero")
                elif not timedelta(0) <= ahora - m.carga_leida_en <= timedelta(hours=36):
                    motivos.append("Carga futura o con más de 36 horas")
                if (m.coste_hora_integral is None or not m.referencia_tarifa or
                        m.tarifa_desde is None or m.tarifa_desde > ahora.date() or
                        (m.tarifa_hasta is not None and m.tarifa_hasta <= ahora.date())):
                    motivos.append("Falta tarifa integral vigente y su referencia")
            if not a.validacion_tecnica:
                motivos.append("Falta validar amarre, herramientas, acceso y tolerancias")
            if motivos:
                descartes.append({"operacion": paso.id, "maquina": a.maquina, "motivos": motivos})
            else:
                candidatos[paso.id].append((a, m))
        if not candidatos[paso.id]:
            bloqueos.append(f"Sin alternativa válida para {paso.id}")
    salida = {"version_motor": "decision-2026.09-a", "expediente_sha256": p.expediente_sha256,
              "revision": p.revision, "evaluado_en": ahora, "bloqueos": bloqueos,
              "descartes": descartes, "propuestas": [], "requiere_aprobacion": True,
              "despacho_automatico": False,
              "limitaciones": ["Dos heurísticas, sin garantía de óptimo global",
                "Colas agregadas, sin reserva ni reordenación de pedidos",
                "Turno diurno de hasta 10 horas; sin horas desatendidas",
                "Capacidad de operarios compartidos y huecos intradía no modelados",
                "Expediente y revisión declarados por el cliente API; pendiente persistencia y verificación"]}
    if bloqueos:
        return salida
    faltantes = [k for k,v in p.economia.model_dump().items() if v is None]
    for criterio in ("menor_coste", "menor_plazo"):
        capacidad = {m.codigo: m.horas_dia * 60 * m.disponibilidad for m in p.maquinas}
        libres = {m.codigo: (m.minutos_cola or Decimal(0)) / capacidad[m.codigo] for m in p.maquinas}
        fin = Decimal(0)
        ruta, ops, cargas, usados = [], [], [], {}
        for paso in p.operaciones:
            opciones = []
            for a,m in candidatos[paso.id]:
                minutos = a.preparacion_min + a.ciclo_min * p.cantidad
                inicio = max(fin, libres[m.codigo])
                termina = inicio + minutos / capacidad[m.codigo]
                coste = minutos * m.coste_hora_integral / 60
                clave = (coste, termina, m.codigo) if criterio == "menor_coste" else (termina, coste, m.codigo)
                opciones.append((clave,a,m,minutos,inicio,termina,coste))
            _,a,m,minutos,inicio,fin,coste = min(opciones, key=lambda x:x[0])
            libres[m.codigo] = fin
            usados[m.codigo] = m
            ruta.append({"operacion": paso.id, "proceso": paso.proceso, "maquina": m.codigo,
                "minutos_lote": minutos, "inicio_dia_laborable": inicio, "fin_dia_laborable": fin,
                "coste_operacion": dinero(coste), "origen_tiempo": a.origen_tiempo,
                "referencia_tiempo": a.referencia_tiempo, "referencia_tarifa": m.referencia_tarifa,
                "validacion_tecnica": a.validacion_tecnica, "evidencia": paso.evidencia,
                "carga_leida_en": m.carga_leida_en})
            ops.append(Operacion(m.codigo,a.preparacion_min,a.ciclo_min,m.coste_hora_integral/60))
            cargas.append(CargaPedido(m.codigo,float(minutos)))
        if fin > 3650:
            salida['propuestas'].append({'criterio':criterio,'ruta':ruta,'presupuesto':None,
                'bloqueos':['Horizonte superior a 3650 días laborables; revise tiempos y capacidad']})
            continue
        plazo = calcular_plazo([ColaCentro(m.codigo,float(m.minutos_cola),m.horas_dia,m.disponibilidad)
                               for m in usados.values()], cargas, p.desde, p.colchon_pct, frozenset(p.festivos))
        presupuesto = None
        if not faltantes:
            e = p.economia
            base = calcular(EntradaCoste(p.cantidad,e.peso_bruto_kg,e.precio_kg,e.merma_pct,
                                         ops,Decimal(0),Decimal(0)))
            extras = {k: getattr(e,k) for k in type(e).model_fields if k.endswith('_lote')}
            subtotal = base.coste_total + sum(extras.values())
            indirectos = dinero(subtotal * e.indirectos_pct / 100)
            coste = dinero(subtotal + indirectos)
            precio = dinero(coste / (1-e.margen_pct/100) if e.politica == 'margen_venta'
                            else coste*(1+e.margen_pct/100))
            presupuesto = {"moneda":"EUR", "impuestos_incluidos":False,
                "material":base.coste_material,"maquina":base.coste_maquina,
                "preparacion":base.coste_preparacion, **extras,"indirectos":indirectos,
                "coste_lote":coste,"precio_lote":precio,"precio_unitario":dinero(precio/p.cantidad),
                "politica":e.politica,"margen_pct":e.margen_pct}
        salida['propuestas'].append({"criterio":criterio,"ruta":ruta,
            "fecha_estimada":plazo.fecha_optima if p.economia.subcontrata_lote == 0 else None,
            "fecha_con_colchon":plazo.fecha_comprometible if p.economia.subcontrata_lote == 0 else None,
            "plazo_externo_pendiente":p.economia.subcontrata_lote != 0,
            "presupuesto":presupuesto,"datos_economicos_pendientes":faltantes,
            "tiempos_teoricos":any(x['origen_tiempo']=='teorico' for x in ruta)})
    return salida
