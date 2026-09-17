"""
Datos ficticios para poder desarrollar mientras no llega la copia del QGIS.

Ejecutar:  python scripts/sembrar_demo.py
Vaciar:    python scripts/sembrar_demo.py --limpiar

IMPORTANTE: esto es solo para desarrollo. En cuanto tengas datos reales,
este script no se vuelve a ejecutar contra la base buena.
"""
import json
import random
import sys
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, ".")

from sqlalchemy import text  # noqa: E402

from app.bd import SesionLocal  # noqa: E402

CLIENTES = [
    ("Metalúrgica del Segura, S.L.", "B30111222", ["metalsegura.es"]),
    ("Hidráulicas Levante, S.A.", "A30333444", ["hidlevante.com"]),
    ("Componentes Agrícolas Sur", "B30555666", ["compagrisur.es"]),
    ("Estructuras Murcia, S.L.", "B30777888", ["estructurasmurcia.es"]),
]

CENTROS = [
    ("TORNO-1", "Torno CNC 1", Decimal("0.48"), Decimal("8"), Decimal("0.72")),
    ("TORNO-2", "Torno CNC 2", Decimal("0.46"), Decimal("16"), Decimal("0.68")),
    ("FRESA-1", "Centro mecanizado 1", Decimal("0.62"), Decimal("16"), Decimal("0.70")),
    ("RECT-1", "Rectificadora", Decimal("0.55"), Decimal("8"), Decimal("0.65")),
    ("TEMPLE", "Tratamiento térmico (externo)", Decimal("0.01"), Decimal("8"), Decimal("1.00")),
]

MATERIALES = [
    ("F-114", "Acero al carbono F-114", Decimal("7.85"), Decimal("2.40")),
    ("F-125", "Acero aleado F-125", Decimal("7.85"), Decimal("3.10")),
    ("AISI-316", "Inoxidable AISI 316", Decimal("8.00"), Decimal("6.80")),
    ("1.2379", "Acero herramienta 1.2379", Decimal("7.70"), Decimal("9.50")),
]

FAMILIAS = ["Eje de transmisión", "Casquillo", "Brida", "Piñón", "Soporte", "Vástago"]


def limpiar(s):
    for t in ["ops.correccion", "ops.comparable", "ops.oferta", "ops.extraccion",
              "ops.peticion_documento", "ops.peticion", "ops.carga_centro",
              "core.linea_venta", "core.documento_venta", "core.parte_trabajo",
              "core.orden_fabricacion", "core.operacion_ruta", "core.pieza",
              "core.precio_material", "core.material", "core.tarifa_centro",
              "core.centro_trabajo", "core.cliente", "ops.version_modelo"]:
        s.execute(text(f"DELETE FROM {t}"))
    s.commit()
    print("Datos de demo eliminados.")


def sembrar(s):
    random.seed(42)

    s.execute(text("""INSERT INTO ops.version_modelo (id, descripcion, activa)
                      VALUES ('2026.09-a','Versión inicial de desarrollo', true)
                      ON CONFLICT DO NOTHING"""))

    cli_ids = []
    for nombre, nif, dominios in CLIENTES:
        cli_ids.append(s.execute(text("""
            INSERT INTO core.cliente (nombre, nif, dominios_email)
            VALUES (:n, :nif, :d) RETURNING id"""),
            {"n": nombre, "nif": nif, "d": dominios}).scalar())

    centro_ids = {}
    for codigo, nombre, tarifa, horas, factor in CENTROS:
        cid = s.execute(text("""
            INSERT INTO core.centro_trabajo
                (codigo, nombre, tipo, horas_turno, factor_disponibilidad, plazo_externo_dias)
            VALUES (:c,:n,:t,:h,:f,:p) RETURNING id"""),
            {"c": codigo, "n": nombre,
             "t": "subcontrata" if codigo == "TEMPLE" else "interno",
             "h": horas, "f": factor,
             "p": 8 if codigo == "TEMPLE" else None}).scalar()
        centro_ids[codigo] = cid
        s.execute(text("""INSERT INTO core.tarifa_centro
                          (centro_trabajo_id, vigente_desde, tarifa_minuto)
                          VALUES (:id, '2026-01-01', :t)"""), {"id": cid, "t": tarifa})

    mat_ids = {}
    for codigo, desig, densidad, precio in MATERIALES:
        mid = s.execute(text("""
            INSERT INTO core.material (codigo, designacion, densidad_kg_dm3)
            VALUES (:c,:d,:den) RETURNING id"""),
            {"c": codigo, "d": desig, "den": densidad}).scalar()
        mat_ids[codigo] = mid
        s.execute(text("""INSERT INTO core.precio_material
                          (material_id, vigente_desde, precio_kg, fuente)
                          VALUES (:m,'2026-01-01',:p,'demo')"""), {"m": mid, "p": precio})

    # 120 piezas con histórico repartido en 6 años
    pieza_ids = []
    for i in range(120):
        familia = random.choice(FAMILIAS)
        diam = random.choice([20, 25, 30, 35, 40, 45, 50, 60, 80])
        mat = random.choice(list(mat_ids))
        cli = random.choice(cli_ids)
        primera = date(2020, 1, 1) + timedelta(days=random.randint(0, 2100))
        pid = s.execute(text("""
            INSERT INTO core.pieza
              (cliente_id, referencia_cliente, referencia_interna, revision,
               descripcion_original, descripcion_normalizada, material_id,
               peso_bruto_kg, tolerancia_general, primera_vez, ultima_vez,
               veces_fabricada, atributos)
            VALUES (:cli, :ref, :refi, 'A', :desc, :desc, :mat, :peso,
                    :tol, :pv, :uv, :vf, CAST(:attr AS jsonb))
            RETURNING id"""), {
            "cli": cli, "ref": f"{familia[:3].upper()}-{diam}-{1000+i}",
            "refi": f"LF{4000+i}",
            "desc": f"{familia} ø{diam} {mat}",
            "mat": mat_ids[mat],
            "peso": Decimal(str(round(random.uniform(0.3, 12.0), 3))),
            "tol": random.choice(["ISO 2768-m", "ISO 2768-f", None]),
            "pv": primera, "uv": primera + timedelta(days=random.randint(0, 400)),
            "vf": random.randint(1, 14),
            "attr": f'{{"diametro_mm": {diam}, "familia": "{familia}"}}',
        }).scalar()
        pieza_ids.append(pid)

        # ruta: 1-3 operaciones
        for seq, codigo in enumerate(random.sample(list(centro_ids), random.randint(1, 3)), 1):
            s.execute(text("""
                INSERT INTO core.operacion_ruta
                  (pieza_id, secuencia, centro_trabajo_id, descripcion,
                   minutos_preparacion, minutos_unitario, origen)
                VALUES (:p,:s,:c,:d,:mp,:mu,'historico')"""), {
                "p": pid, "s": seq, "c": centro_ids[codigo],
                "d": f"Operación en {codigo}",
                "mp": random.randint(20, 120), "mu": random.randint(2, 45)})

    # Histórico de presupuestos con resultado ganado/perdido
    for _ in range(400):
        pid = random.choice(pieza_ids)
        cli = s.execute(text("SELECT cliente_id FROM core.pieza WHERE id=:p"),
                        {"p": pid}).scalar()
        fecha = date(2020, 1, 1) + timedelta(days=random.randint(0, 2400))
        cantidad = random.choice([1, 5, 10, 25, 50, 100, 250, 500])
        precio_u = Decimal(str(round(random.uniform(3, 240), 2)))
        did = s.execute(text("""
            INSERT INTO core.documento_venta
              (tipo, numero, cliente_id, fecha, total, resultado)
            VALUES ('presupuesto', :num, :cli, :f, :tot, :res) RETURNING id"""), {
            "num": f"P{fecha.year}-{random.randint(1,9999):04d}",
            "cli": cli, "f": fecha, "tot": precio_u * cantidad,
            "res": random.choices(["ganada", "perdida", "sin_respuesta"],
                                  weights=[55, 30, 15])[0]}).scalar()
        s.execute(text("""
            INSERT INTO core.linea_venta
              (documento_venta_id, linea, pieza_id, cantidad, precio_unitario, importe)
            VALUES (:d,1,:p,:c,:pu,:imp)"""), {
            "d": did, "p": pid, "c": cantidad, "pu": precio_u, "imp": precio_u * cantidad})

    # Peticiones y ofertas pendientes de revisar, para el panel
    vias = ["A_repetida"] * 6 + ["B_similar"] * 3 + ["C_nueva"] * 2
    for i, via in enumerate(vias):
        cli = random.choice(cli_ids)
        pid = random.choice(pieza_ids)
        pet = s.execute(text("""
            INSERT INTO ops.peticion
              (canal, mensaje_id, remitente, asunto, cliente_id, estado, via)
            VALUES ('email', :mid, :rem, :asu, :cli, 'analizada', :via)
            RETURNING id"""), {
            "mid": f"<demo-{i}@correo>", "rem": "compras@cliente.es",
            "asu": f"Solicitud de oferta {2000+i}", "cli": cli, "via": via}).scalar()

        if via == "C_nueva":
            precio = pmin = pmax = coste = None
            conf = Decimal("0.25")
        else:
            coste = Decimal(str(round(random.uniform(300, 6000), 2)))
            precio = (coste * Decimal("1.35")).quantize(Decimal("0.01"))
            conf = Decimal("0.88") if via == "A_repetida" else Decimal("0.62")
            amp = (Decimal("1") - conf) * Decimal("0.30")
            pmin = (precio * (1 - amp)).quantize(Decimal("0.01"))
            pmax = (precio * (1 + amp)).quantize(Decimal("0.01"))

        cantidad = random.choice([10, 25, 50, 100, 250])
        desglose = None
        if coste:
            mat = (coste * Decimal("0.42")).quantize(Decimal("0.01"))
            maq = (coste * Decimal("0.34")).quantize(Decimal("0.01"))
            prep = (coste * Decimal("0.08")).quantize(Decimal("0.01"))
            ext = (coste * Decimal("0.07")).quantize(Decimal("0.01"))
            ind = (coste - mat - maq - prep - ext).quantize(Decimal("0.01"))
            desglose = json.dumps({
                "material": str(mat), "maquina": str(maq), "preparacion": str(prep),
                "externo": str(ext), "indirectos": str(ind), "coste_total": str(coste),
                "margen_pct": "35", "minutos_totales": random.randint(400, 4200),
            })

        dias_opt = random.randint(6, 15)
        oferta_id = s.execute(text("""
            INSERT INTO ops.oferta
              (peticion_id, pieza_id, cantidad, via, precio_propuesto, precio_min,
               precio_max, coste_calculado, confianza, version_modelo, estado,
               fecha_entrega_optima, fecha_entrega_comprometible, hipotesis, desglose)
            VALUES (:pet,:pz,:cant,:via,:pre,:pmin,:pmax,:coste,:conf,'2026.09-a',
                    'borrador', :fo, :fc, :hip, CAST(:des AS jsonb))
            RETURNING id"""), {
            "pet": pet, "pz": pid, "cant": cantidad,
            "via": via, "pre": precio, "pmin": pmin, "pmax": pmax, "coste": coste,
            "conf": conf,
            "fo": date.today() + timedelta(days=dias_opt),
            "fc": date.today() + timedelta(days=int(dias_opt * 1.6) + 2),
            "hip": ["Tolerancia general asumida ISO 2768-m",
                    "Sin tratamiento superficial"] if via != "A_repetida" else [],
            "des": desglose}).scalar()

        # Piezas comparables en las que se apoya la propuesta
        for cmp_id in random.sample(pieza_ids, random.randint(3, 5)):
            if cmp_id == pid:
                continue
            s.execute(text("""
                INSERT INTO ops.comparable
                  (oferta_id, pieza_id, similitud, precio_historico,
                   minutos_reales, fecha_referencia)
                VALUES (:o,:p,:s,:pr,:m,:f) ON CONFLICT DO NOTHING"""), {
                "o": oferta_id, "p": cmp_id,
                "s": Decimal(str(round(random.uniform(0.62, 0.97), 4))),
                "pr": Decimal(str(round(random.uniform(200, 5200), 2))),
                "m": random.randint(120, 3200),
                "f": date.today() - timedelta(days=random.randint(60, 1400))})

        # Documento de plano y su análisis
        doc = s.execute(text("""
            INSERT INTO core.documento
              (sha256, tipo, formato, nombre_original, ruta_almacen,
               es_vectorial, cliente_id, pieza_id, revision)
            VALUES (:h,'plano','pdf',:n,:r,:v,:c,:p,'A') RETURNING id"""), {
            "h": f"demo{i:04d}" + "0" * 56, "n": f"plano_{2000+i}.pdf",
            "r": f"almacen/demo/plano_{2000+i}.pdf",
            "v": via != "C_nueva", "c": cli, "p": pid}).scalar()
        s.execute(text("""INSERT INTO ops.peticion_documento (peticion_id, documento_id)
                          VALUES (:pe,:d)"""), {"pe": pet, "d": doc})

        catalogo = [
            ("TOL_GENERAL", "bloqueante", "El plano no declara tolerancia general."),
            ("TOL_AJUSTE", "bloqueante",
             "El alojamiento no lleva tolerancia y es superficie de ajuste."),
            ("RUGOSIDAD", "importante", "Sin rugosidad especificada en superficie funcional."),
            ("TRATAMIENTO", "importante",
             "No indica si las cotas son antes o después del recubrimiento."),
            ("ROSCA", "importante", "Rosca sin profundidad útil indicada."),
            ("PROYECCION", "menor", "No indica sistema de proyección."),
            ("ESCALA", "menor", "Falta la escala en el cajetín."),
        ]
        n_hall = {"A_repetida": 0, "B_similar": 2, "C_nueva": 4}[via]
        hallazgos = [
            {"codigo": c, "gravedad": g, "texto": t}
            for c, g, t in random.sample(catalogo, n_hall)
        ] if n_hall else []
        s.execute(text("""
            INSERT INTO ops.analisis_plano
              (documento_id, metodo, hallazgos, bloqueantes, confianza, version_reglas)
            VALUES (:d,:m,CAST(:h AS jsonb),:b,:c,'reglas-2026.09')"""), {
            "d": doc, "m": "texto_vectorial" if via != "C_nueva" else "vision",
            "h": json.dumps(hallazgos),
            "b": sum(1 for x in hallazgos if x["gravedad"] == "bloqueante"),
            "c": Decimal("0.90") if via != "C_nueva" else Decimal("0.55")})

    # Foto de carga actual por centro
    for codigo, cid in centro_ids.items():
        s.execute(text("""INSERT INTO ops.carga_centro
                          (centro_trabajo_id, minutos_comprometidos, fecha_liberacion)
                          VALUES (:c,:m,:f)"""), {
            "c": cid, "m": random.randint(600, 9000),
            "f": date.today() + timedelta(days=random.randint(3, 25))})

    s.execute(text("""INSERT INTO audit.evento (actor, accion, entidad, entidad_id)
                      VALUES ('script','sembrar_demo','sistema','0')"""))
    s.commit()
    print("Datos de demo cargados: 4 clientes, 120 piezas, 400 presupuestos, 11 ofertas.")


if __name__ == "__main__":
    sesion = SesionLocal()
    try:
        if "--limpiar" in sys.argv:
            limpiar(sesion)
        else:
            sembrar(sesion)
    finally:
        sesion.close()
