-- =============================================================
--  Migración 002 — ajustar el modelo a lo que el ERP hace de verdad
--
--  Ejecutar después de modelo-datos.sql:
--    psql -U luanfra -d luanfra -f db/002-ajustes-erp.sql
--
--  MOTIVO
--  Las capturas del QGIS mostraron tres cosas que el modelo v1 no contemplaba:
--
--   1. El taller tiene DOS niveles: secciones (fresadora CNC, tornos CNC,
--      taladrado, láser…) y dentro más de sesenta máquinas concretas.
--      El modelo v1 tenía un solo nivel de centro de trabajo.
--
--   2. Los presupuestos ya llevan situación y fecha de aceptación. Ganada o
--      perdida no hay que empezar a registrarlo: ya está en el histórico.
--
--   3. Las líneas de presupuesto llevan el código de artículo casi siempre
--      vacío y la pieza en texto libre. La normalización de esa descripción
--      es el trabajo central del proyecto y necesita su propia trazabilidad.
-- =============================================================


-- -------------------------------------------------------------
-- 1. SECCIONES: el nivel que faltaba sobre las máquinas
-- -------------------------------------------------------------

CREATE TABLE core.seccion (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  erp_id         text UNIQUE,
  codigo         text NOT NULL UNIQUE,
  nombre         text NOT NULL,
  orden          integer,
  activa         boolean NOT NULL DEFAULT true,
  creado_en      timestamptz NOT NULL DEFAULT now(),
  creado_por     text NOT NULL DEFAULT current_user,
  modificado_en  timestamptz,
  modificado_por text
);
CREATE TRIGGER t_mod BEFORE UPDATE ON core.seccion
  FOR EACH ROW EXECUTE FUNCTION core.tocar_modificado();

COMMENT ON TABLE core.seccion IS
  'Fresadora CNC, centros de mecanizado, tornos CNC, torno paralelo, taladrado, programación, enderezadora, plegadoras, láser. Es el nivel al que se planifica; la máquina concreta es el nivel al que se imputa.';

ALTER TABLE core.centro_trabajo
  ADD COLUMN seccion_id     bigint REFERENCES core.seccion(id),
  ADD COLUMN carga_erp      numeric(12,3),
  ADD COLUMN carga_leida_en timestamptz,
  ADD COLUMN posicion_plano integer,
  ADD COLUMN inicio_produccion date;

CREATE INDEX ON core.centro_trabajo (seccion_id);

COMMENT ON COLUMN core.centro_trabajo.carga_erp IS
  'Carga que el propio ERP calcula por máquina, tal cual la muestra Control de Rutas. Se copia sin recalcular: es su número, no el nuestro.';
COMMENT ON COLUMN core.centro_trabajo.posicion_plano IS
  'Posición en el plano de planta en tiempo real del ERP.';


-- Estado instantáneo de máquina, el que pinta el plano de planta cada 30 s.
CREATE TABLE core.estado_maquina (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  centro_trabajo_id bigint NOT NULL REFERENCES core.centro_trabajo(id),
  leido_en          timestamptz NOT NULL DEFAULT now(),
  estado            text NOT NULL CHECK (estado IN
                      ('produciendo','parada','preparacion','averia','sin_dato')),
  orden_id          bigint REFERENCES core.orden_fabricacion(id),
  minutos_restantes numeric(10,2)
);
CREATE INDEX ON core.estado_maquina (centro_trabajo_id, leido_en DESC);

COMMENT ON COLUMN core.estado_maquina.minutos_restantes IS
  'Negativo cuando la orden ya va fuera de plazo. El ERP lo muestra por máquina; aquí sirve para agregarlo y saber cuánto va tarde en total.';


-- Cola de órdenes por máquina, tal como la ordena el ERP.
CREATE TABLE core.cola_maquina (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  centro_trabajo_id bigint NOT NULL REFERENCES core.centro_trabajo(id),
  leido_en          timestamptz NOT NULL DEFAULT now(),
  posicion          integer NOT NULL,
  orden_id          bigint REFERENCES core.orden_fabricacion(id),
  cliente_id        bigint REFERENCES core.cliente(id),
  tiempo_horas      numeric(10,3),
  prioridad         text,
  fecha_alta        date,
  fecha_entrega     date,
  iniciada          boolean NOT NULL DEFAULT false,
  unidades          numeric(12,3),
  referencia        text
);
CREATE INDEX ON core.cola_maquina (centro_trabajo_id, leido_en DESC, posicion);
CREATE INDEX ON core.cola_maquina (fecha_entrega) WHERE NOT iniciada;


-- -------------------------------------------------------------
-- 2. PRESUPUESTOS: situación y aceptación ya existen en el ERP
-- -------------------------------------------------------------

ALTER TABLE core.documento_venta
  ADD COLUMN situacion        text,
  ADD COLUMN fecha_aceptacion date,
  ADD COLUMN agente           text,
  ADD COLUMN comision_pct     numeric(6,3),
  ADD COLUMN forma_pago       text,
  ADD COLUMN tarifa           text,
  ADD COLUMN serie            text,
  ADD COLUMN orden_generada   text;

CREATE INDEX ON core.documento_venta (situacion) WHERE tipo = 'presupuesto';
CREATE INDEX ON core.documento_venta (fecha_aceptacion) WHERE fecha_aceptacion IS NOT NULL;

COMMENT ON COLUMN core.documento_venta.situacion IS
  'Literal del ERP: "Pendiente de Aceptación", "Cortado", etc. Se guarda tal cual y se traduce a resultado en una vista, para no perder el original.';

-- El resultado se deriva de la situación del ERP, no se inventa.
CREATE OR REPLACE FUNCTION core.resultado_desde_situacion(
  situacion text, fecha_aceptacion date, fecha date
) RETURNS text AS $$
  SELECT CASE
    WHEN fecha_aceptacion IS NOT NULL THEN 'ganada'
    WHEN situacion ILIKE '%rechaz%' OR situacion ILIKE '%anulad%'
      OR situacion ILIKE '%perdid%' THEN 'perdida'
    WHEN fecha < current_date - interval '120 days' THEN 'sin_respuesta'
    ELSE NULL
  END
$$ LANGUAGE sql IMMUTABLE;

COMMENT ON FUNCTION core.resultado_desde_situacion IS
  'Un presupuesto sin respuesta a los 120 días se da por perdido a efectos de estadística, pero se marca aparte: no es lo mismo que un rechazo explícito.';


ALTER TABLE core.linea_venta
  ADD COLUMN codigo_articulo text,
  ADD COLUMN unidades        numeric(12,3),
  ADD COLUMN dto1_pct        numeric(6,3),
  ADD COLUMN dto2_pct        numeric(6,3);

CREATE INDEX ON core.linea_venta (codigo_articulo) WHERE codigo_articulo IS NOT NULL;

COMMENT ON COLUMN core.linea_venta.codigo_articulo IS
  'Casi siempre vacío en el histórico: la pieza va en descripcion_original. Cuando viene relleno, esa parte del histórico es la más fiable y por ahí conviene empezar a normalizar.';


-- -------------------------------------------------------------
-- 3. NORMALIZACIÓN: trazabilidad de cómo se interpretó cada texto
-- -------------------------------------------------------------

CREATE TABLE core.normalizacion (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  linea_venta_id    bigint REFERENCES core.linea_venta(id) ON DELETE CASCADE,
  pieza_id          bigint REFERENCES core.pieza(id),
  descripcion_origen text NOT NULL,
  campos            jsonb NOT NULL,
  confianza         numeric(4,3) NOT NULL CHECK (confianza BETWEEN 0 AND 1),
  dudoso            text[],
  restos            text,
  metodo            text NOT NULL DEFAULT 'reglas'
                    CHECK (metodo IN ('reglas','ia','manual','mixto')),
  version_reglas    text NOT NULL,
  confirmada_por    text,
  confirmada_en     timestamptz,
  creado_en         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON core.normalizacion (pieza_id);
CREATE INDEX ON core.normalizacion (confianza) WHERE confirmada_en IS NULL;
CREATE INDEX ON core.normalizacion USING gin (campos);

COMMENT ON TABLE core.normalizacion IS
  'Una fila por intento de interpretar una descripción libre. Guarda el texto de origen, lo que se entendió, con qué método y con qué versión de reglas. Permite reprocesar los 20 años cuando las reglas mejoren, sin volver a tocar el ERP.';
COMMENT ON COLUMN core.normalizacion.metodo IS
  'reglas: determinista. ia: propuesto por un modelo. manual: escrito por una persona. La IA nunca sobreescribe un campo que las reglas resolvieron con confianza alta.';
COMMENT ON COLUMN core.normalizacion.restos IS
  'Lo que ninguna regla consumió. Leer los restos más frecuentes es la forma de descubrir qué reglas faltan.';


-- Campos que el módulo de piñones especiales ya maneja y que conviene
-- reflejar para poder comparar contra su histórico.
ALTER TABLE core.pieza
  ADD COLUMN dientes_z      integer CHECK (dientes_z IS NULL OR dientes_z BETWEEN 5 AND 250),
  ADD COLUMN paso_cadena    text,
  ADD COLUMN ramales        smallint,
  ADD COLUMN diametro_primitivo numeric(10,2),
  ADD COLUMN es_pinon       boolean GENERATED ALWAYS AS (dientes_z IS NOT NULL) STORED;

CREATE INDEX ON core.pieza (dientes_z, paso_cadena) WHERE dientes_z IS NOT NULL;
CREATE INDEX ON core.pieza (diametro_primitivo) WHERE diametro_primitivo IS NOT NULL;


-- -------------------------------------------------------------
-- 4. VISTAS DE TRABAJO
-- -------------------------------------------------------------

-- Tasa de éxito por cliente: a partir de qué precio dejamos de ganar.
CREATE VIEW ops.v_acierto_por_cliente AS
SELECT c.id AS cliente_id, c.nombre,
       count(*)                                             AS presupuestos,
       count(*) FILTER (WHERE dv.fecha_aceptacion IS NOT NULL) AS ganados,
       round(100.0 * count(*) FILTER (WHERE dv.fecha_aceptacion IS NOT NULL)
             / nullif(count(*),0), 1)                       AS tasa_exito_pct,
       round(avg(dv.total), 2)                              AS importe_medio
FROM core.documento_venta dv
JOIN core.cliente c ON c.id = dv.cliente_id
WHERE dv.tipo = 'presupuesto'
GROUP BY c.id, c.nombre;

-- Cuánto trabajo va fuera de plazo, agregado. El ERP lo muestra máquina a
-- máquina; nadie tiene la cifra global.
CREATE VIEW ops.v_ordenes_fuera_de_plazo AS
SELECT ct.codigo AS maquina, s.nombre AS seccion,
       cm.orden_id, cl.nombre AS cliente, cm.fecha_entrega,
       (current_date - cm.fecha_entrega) AS dias_de_retraso,
       cm.tiempo_horas, cm.unidades
FROM core.cola_maquina cm
JOIN core.centro_trabajo ct ON ct.id = cm.centro_trabajo_id
LEFT JOIN core.seccion s    ON s.id = ct.seccion_id
LEFT JOIN core.cliente cl   ON cl.id = cm.cliente_id
WHERE cm.fecha_entrega < current_date
  AND NOT cm.iniciada
  AND cm.leido_en = (SELECT max(leido_en) FROM core.cola_maquina);

-- Calidad de la normalización: cuánto del histórico es realmente utilizable.
CREATE VIEW core.v_calidad_normalizacion AS
SELECT date_trunc('year', dv.fecha)::date       AS anio,
       count(*)                                  AS lineas,
       count(n.id)                               AS normalizadas,
       count(*) FILTER (WHERE lv.codigo_articulo IS NOT NULL) AS con_codigo_articulo,
       round(avg(n.confianza), 3)                AS confianza_media,
       count(*) FILTER (WHERE n.confianza < 0.55) AS necesitan_revision
FROM core.linea_venta lv
JOIN core.documento_venta dv ON dv.id = lv.documento_venta_id
LEFT JOIN core.normalizacion n ON n.linea_venta_id = lv.id
GROUP BY 1
ORDER BY 1;

COMMENT ON VIEW core.v_calidad_normalizacion IS
  'La consulta que decide el alcance del proyecto: dice año por año qué parte del histórico es utilizable. La expectativa razonable es que los últimos años sean buenos y los primeros solo sirvan para tendencias.';


GRANT SELECT ON ALL TABLES IN SCHEMA core, ops TO luanfra_lectura;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA core, ops TO luanfra_app;
