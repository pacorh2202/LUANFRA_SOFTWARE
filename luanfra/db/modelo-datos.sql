-- =============================================================
--  Talleres Luanfra — Sistema de ofertas, plazos y trazabilidad
--  Modelo de datos v1 · PostgreSQL 16+
--
--  Ejecutar:  psql -U luanfra -d luanfra -f modelo-datos.sql
--
--  Esquemas:
--    stage  copia cruda del ERP, sin transformar
--    core   datos normalizados (piezas, rutas, histórico de ventas)
--    ops    lo que genera el sistema (peticiones, ofertas, análisis)
--    audit  registro inmutable encadenado por hash
-- =============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- digest() para el hash de auditoría

CREATE SCHEMA IF NOT EXISTS stage;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS audit;

COMMENT ON SCHEMA stage IS 'Copia literal del ERP. Nada se transforma aquí. Si mañana descubrimos que interpretamos mal un campo, se reprocesa desde aquí sin volver a tocar el ERP.';
COMMENT ON SCHEMA core  IS 'Datos normalizados y limpios. Fuente para cálculo y búsqueda.';
COMMENT ON SCHEMA ops   IS 'Datos que produce el sistema: peticiones, ofertas, análisis, correcciones.';
COMMENT ON SCHEMA audit IS 'Registro de eventos. Solo INSERT. Encadenado por hash.';


-- =============================================================
-- 0. UTILIDADES COMUNES
-- =============================================================

-- Todas las tablas de negocio llevan estas cuatro columnas.
-- No se borra nada nunca: se marca anulado_en.
CREATE OR REPLACE FUNCTION core.tocar_modificado() RETURNS trigger AS $$
BEGIN
  NEW.modificado_en  := now();
  NEW.modificado_por := current_user;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

-- Dinero: SIEMPRE numeric. Nunca float. Nunca money.
CREATE DOMAIN core.importe AS numeric(14,4);
-- Tiempo: SIEMPRE minutos enteros. Nunca decimales de hora.
CREATE DOMAIN core.minutos AS integer CHECK (VALUE >= 0);


-- =============================================================
-- 1. STAGE — control de cargas desde el ERP
-- =============================================================
-- Las tablas stage.erp_* las creará el script de extracción
-- espejando el esquema del QGIS. Aquí solo el registro de cargas.

CREATE TABLE stage.carga (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tabla_origen    text        NOT NULL,
  tabla_destino   text        NOT NULL,
  inicio          timestamptz NOT NULL DEFAULT now(),
  fin             timestamptz,
  filas_leidas    bigint,
  filas_escritas  bigint,
  modo            text        NOT NULL CHECK (modo IN ('completa','incremental')),
  corte_desde     timestamptz,           -- para cargas incrementales
  estado          text        NOT NULL DEFAULT 'en_curso'
                              CHECK (estado IN ('en_curso','ok','error')),
  error           text
);
CREATE INDEX ON stage.carga (tabla_destino, inicio DESC);

COMMENT ON TABLE stage.carga IS 'Bitácora de cada extracción desde el ERP. Sin esto no sabrás nunca si los datos de anoche entraron.';


-- =============================================================
-- 2. CORE — maestros
-- =============================================================

CREATE TABLE core.cliente (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  erp_id          text UNIQUE,           -- clave en el QGIS, para volver a casar en cada sync
  nombre          text NOT NULL,
  nif             text,
  pais            text DEFAULT 'ES',
  dominios_email  text[],                -- para identificar al cliente por el remitente
  activo          boolean NOT NULL DEFAULT true,
  creado_en       timestamptz NOT NULL DEFAULT now(),
  creado_por      text NOT NULL DEFAULT current_user,
  modificado_en   timestamptz,
  modificado_por  text,
  anulado_en      timestamptz,
  anulado_por     text
);
CREATE INDEX ON core.cliente USING gin (dominios_email);
CREATE TRIGGER t_mod BEFORE UPDATE ON core.cliente
  FOR EACH ROW EXECUTE FUNCTION core.tocar_modificado();


CREATE TABLE core.centro_trabajo (
  id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  erp_id                text UNIQUE,
  codigo                text NOT NULL UNIQUE,
  nombre                text NOT NULL,
  tipo                  text NOT NULL DEFAULT 'interno'
                        CHECK (tipo IN ('interno','subcontrata')),
  turnos_dia            numeric(3,1) NOT NULL DEFAULT 1,
  horas_turno           numeric(4,2) NOT NULL DEFAULT 8,
  factor_disponibilidad numeric(4,3) NOT NULL DEFAULT 0.700
                        CHECK (factor_disponibilidad > 0 AND factor_disponibilidad <= 1),
  plazo_externo_dias    integer,         -- solo para subcontratas
  activo                boolean NOT NULL DEFAULT true,
  creado_en             timestamptz NOT NULL DEFAULT now(),
  creado_por            text NOT NULL DEFAULT current_user,
  modificado_en         timestamptz,
  modificado_por        text,
  anulado_en            timestamptz,
  anulado_por           text
);
CREATE TRIGGER t_mod BEFORE UPDATE ON core.centro_trabajo
  FOR EACH ROW EXECUTE FUNCTION core.tocar_modificado();

COMMENT ON COLUMN core.centro_trabajo.factor_disponibilidad IS
  'Horas que la máquina produce de verdad / horas teóricas. Sale del histórico de partes. Suele estar entre 0,65 y 0,80. Es la variable que más afecta a los plazos.';


-- Tarifas con vigencia: hay que poder reconstruir qué tarifa se aplicó
-- en una oferta de hace dos años.
CREATE TABLE core.tarifa_centro (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  centro_trabajo_id bigint NOT NULL REFERENCES core.centro_trabajo(id),
  vigente_desde     date   NOT NULL,
  vigente_hasta     date,
  tarifa_minuto     core.importe NOT NULL CHECK (tarifa_minuto > 0),
  notas             text,
  creado_en         timestamptz NOT NULL DEFAULT now(),
  creado_por        text NOT NULL DEFAULT current_user,
  CONSTRAINT rango_valido CHECK (vigente_hasta IS NULL OR vigente_hasta > vigente_desde)
);
CREATE INDEX ON core.tarifa_centro (centro_trabajo_id, vigente_desde DESC);


CREATE TABLE core.material (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  erp_id          text UNIQUE,
  codigo          text NOT NULL UNIQUE,   -- F-114, 1.2379, AISI 316...
  designacion     text NOT NULL,
  densidad_kg_dm3 numeric(6,3),
  merma_pct       numeric(5,2) NOT NULL DEFAULT 10.00,
  creado_en       timestamptz NOT NULL DEFAULT now(),
  creado_por      text NOT NULL DEFAULT current_user,
  modificado_en   timestamptz,
  modificado_por  text
);
CREATE TRIGGER t_mod BEFORE UPDATE ON core.material
  FOR EACH ROW EXECUTE FUNCTION core.tocar_modificado();


CREATE TABLE core.precio_material (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  material_id   bigint NOT NULL REFERENCES core.material(id),
  vigente_desde date   NOT NULL,
  precio_kg     core.importe NOT NULL CHECK (precio_kg > 0),
  fuente        text,
  creado_en     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON core.precio_material (material_id, vigente_desde DESC);


-- Datos mínimos del trabajador. Trazabilidad de producción, no expediente.
-- Aquí NO van datos personales más allá de lo imprescindible para
-- imputar un parte. Nada de rendimiento, valoraciones ni comparativas.
CREATE TABLE core.trabajador (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  erp_id         text UNIQUE,
  codigo         text NOT NULL UNIQUE,
  nombre_corto   text,
  activo         boolean NOT NULL DEFAULT true,
  creado_en      timestamptz NOT NULL DEFAULT now(),
  creado_por     text NOT NULL DEFAULT current_user,
  modificado_en  timestamptz,
  modificado_por text
);
CREATE TRIGGER t_mod BEFORE UPDATE ON core.trabajador
  FOR EACH ROW EXECUTE FUNCTION core.tocar_modificado();

COMMENT ON TABLE core.trabajador IS
  'Solo para imputar partes y trazar una orden. Antes de encender el módulo de planta: información previa por escrito a la plantilla y consulta a la representación legal.';


-- =============================================================
-- 3. CORE — piezas y rutas
-- =============================================================

CREATE TABLE core.pieza (
  id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  erp_id                 text UNIQUE,
  cliente_id             bigint REFERENCES core.cliente(id),
  referencia_cliente     text,
  referencia_interna     text,
  revision               text,
  descripcion_original   text,           -- tal cual viene del ERP
  descripcion_normalizada text,          -- resultado de la clasificación
  material_id            bigint REFERENCES core.material(id),
  peso_bruto_kg          numeric(10,3),
  peso_neto_kg           numeric(10,3),
  dim_x_mm               numeric(10,2),
  dim_y_mm               numeric(10,2),
  dim_z_mm               numeric(10,2),
  tolerancia_general     text,           -- ISO 2768-m, -f...
  tratamiento            text,
  atributos              jsonb NOT NULL DEFAULT '{}'::jsonb,
  primera_vez            date,
  ultima_vez             date,
  veces_fabricada        integer NOT NULL DEFAULT 0,
  creado_en              timestamptz NOT NULL DEFAULT now(),
  creado_por             text NOT NULL DEFAULT current_user,
  modificado_en          timestamptz,
  modificado_por         text,
  anulado_en             timestamptz,
  anulado_por            text,
  UNIQUE (cliente_id, referencia_cliente, revision)
);
CREATE INDEX ON core.pieza (material_id);
CREATE INDEX ON core.pieza USING gin (atributos);
CREATE INDEX ON core.pieza USING gin (to_tsvector('spanish', coalesce(descripcion_normalizada,'')));
CREATE TRIGGER t_mod BEFORE UPDATE ON core.pieza
  FOR EACH ROW EXECUTE FUNCTION core.tocar_modificado();

COMMENT ON COLUMN core.pieza.atributos IS
  'Campos que aún no sabemos que necesitaremos: roscas, acabados, número de agujeros. jsonb evita rehacer la tabla cada vez que aparece un atributo nuevo.';


CREATE TABLE core.operacion_ruta (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  pieza_id            bigint NOT NULL REFERENCES core.pieza(id) ON DELETE CASCADE,
  secuencia           integer NOT NULL,
  centro_trabajo_id   bigint NOT NULL REFERENCES core.centro_trabajo(id),
  descripcion         text,
  minutos_preparacion core.minutos NOT NULL DEFAULT 0,
  minutos_unitario    core.minutos NOT NULL DEFAULT 0,
  origen              text NOT NULL DEFAULT 'erp'
                      CHECK (origen IN ('erp','historico','estimado','manual')),
  creado_en           timestamptz NOT NULL DEFAULT now(),
  creado_por          text NOT NULL DEFAULT current_user,
  modificado_en       timestamptz,
  modificado_por      text,
  UNIQUE (pieza_id, secuencia)
);
CREATE TRIGGER t_mod BEFORE UPDATE ON core.operacion_ruta
  FOR EACH ROW EXECUTE FUNCTION core.tocar_modificado();

COMMENT ON COLUMN core.operacion_ruta.origen IS
  'De dónde salen estos tiempos. Un tiempo "estimado" por el modelo no vale lo mismo que uno medido: hay que poder distinguirlos al presupuestar.';


-- =============================================================
-- 4. CORE — documentos (planos, PDF, adjuntos)
-- =============================================================

CREATE TABLE core.documento (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sha256          text NOT NULL UNIQUE,   -- deduplicación y trazabilidad
  tipo            text NOT NULL CHECK (tipo IN
                    ('plano','modelo_3d','pedido','oferta','correo','otro')),
  formato         text,                   -- pdf, step, dxf, xlsx
  nombre_original text,
  ruta_almacen    text NOT NULL,
  bytes           bigint,
  es_vectorial    boolean,                -- PDF con capa de texto = análisis fiable
  cliente_id      bigint REFERENCES core.cliente(id),
  pieza_id        bigint REFERENCES core.pieza(id),
  revision        text,
  recibido_en     timestamptz NOT NULL DEFAULT now(),
  creado_en       timestamptz NOT NULL DEFAULT now(),
  creado_por      text NOT NULL DEFAULT current_user
);
CREATE INDEX ON core.documento (pieza_id, revision);
CREATE INDEX ON core.documento (cliente_id, recibido_en DESC);

COMMENT ON COLUMN core.documento.sha256 IS
  'Si el cliente reenvía el mismo plano, no se procesa dos veces. Y en una auditoría demuestra que el fichero analizado es exactamente el que llegó.';


-- =============================================================
-- 5. CORE — histórico de ventas (los 20 años)
-- =============================================================

CREATE TABLE core.documento_venta (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  erp_id        text,
  tipo          text NOT NULL CHECK (tipo IN
                  ('presupuesto','pedido','albaran','factura')),
  numero        text,
  cliente_id    bigint NOT NULL REFERENCES core.cliente(id),
  fecha         date   NOT NULL,
  moneda        char(3) NOT NULL DEFAULT 'EUR',
  total         core.importe,
  estado        text,
  resultado     text CHECK (resultado IN ('ganada','perdida','sin_respuesta')),
  creado_en     timestamptz NOT NULL DEFAULT now(),
  creado_por    text NOT NULL DEFAULT current_user,
  UNIQUE (tipo, erp_id)
);
CREATE INDEX ON core.documento_venta (cliente_id, fecha DESC);
CREATE INDEX ON core.documento_venta (tipo, fecha DESC);

COMMENT ON COLUMN core.documento_venta.resultado IS
  'Solo para presupuestos. Si el ERP no lo guarda, hay que empezar a guardarlo: sin saber qué ofertas se perdieron no se puede calibrar el precio.';


CREATE TABLE core.linea_venta (
  id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  documento_venta_id     bigint NOT NULL REFERENCES core.documento_venta(id) ON DELETE CASCADE,
  linea                  integer NOT NULL,
  pieza_id               bigint REFERENCES core.pieza(id),
  descripcion_original   text,
  cantidad               numeric(12,3) NOT NULL,
  precio_unitario        core.importe NOT NULL,
  importe                core.importe,
  -- Deflactado: un precio de 2007 no es comparable con uno de hoy
  precio_unitario_defl   core.importe,
  indice_deflactor       numeric(10,6),
  base_deflactor         text DEFAULT 'IPRI productos metálicos',
  creado_en              timestamptz NOT NULL DEFAULT now(),
  UNIQUE (documento_venta_id, linea)
);
CREATE INDEX ON core.linea_venta (pieza_id);


CREATE TABLE core.orden_fabricacion (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  erp_id         text UNIQUE,
  numero         text,
  pieza_id       bigint REFERENCES core.pieza(id),
  cliente_id     bigint REFERENCES core.cliente(id),
  cantidad       numeric(12,3) NOT NULL,
  fecha_apertura date,
  fecha_prevista date,
  fecha_cierre   date,
  estado         text,
  creado_en      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON core.orden_fabricacion (pieza_id);
CREATE INDEX ON core.orden_fabricacion (estado, fecha_prevista);


CREATE TABLE core.parte_trabajo (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  erp_id            text UNIQUE,
  orden_id          bigint NOT NULL REFERENCES core.orden_fabricacion(id),
  operacion_ruta_id bigint REFERENCES core.operacion_ruta(id),
  centro_trabajo_id bigint NOT NULL REFERENCES core.centro_trabajo(id),
  trabajador_id     bigint REFERENCES core.trabajador(id),
  inicio            timestamptz NOT NULL,
  fin               timestamptz,
  minutos           core.minutos,
  cantidad_ok       numeric(12,3) NOT NULL DEFAULT 0,
  cantidad_rechazo  numeric(12,3) NOT NULL DEFAULT 0,
  causa_incidencia  text,
  origen            text NOT NULL DEFAULT 'erp'
                    CHECK (origen IN ('erp','terminal','manual')),
  creado_en         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fin_posterior CHECK (fin IS NULL OR fin >= inicio)
);
CREATE INDEX ON core.parte_trabajo (orden_id);
CREATE INDEX ON core.parte_trabajo (centro_trabajo_id, inicio DESC);
CREATE INDEX ON core.parte_trabajo (inicio DESC);

COMMENT ON TABLE core.parte_trabajo IS
  'El dato del que depende TODO el motor de plazos. Si esto no es real, las fechas de entrega son inventadas.';


-- =============================================================
-- 6. OPS — peticiones que llegan
-- =============================================================

CREATE TABLE ops.peticion (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  recibido_en   timestamptz NOT NULL DEFAULT now(),
  canal         text NOT NULL DEFAULT 'email'
                CHECK (canal IN ('email','telefono','portal','manual')),
  mensaje_id    text UNIQUE,             -- Message-ID del correo: evita duplicados
  remitente     text,
  asunto        text,
  cuerpo        text,
  cliente_id    bigint REFERENCES core.cliente(id),
  cliente_nuevo boolean NOT NULL DEFAULT false,
  estado        text NOT NULL DEFAULT 'recibida'
                CHECK (estado IN ('recibida','clasificada','analizada',
                                  'ofertada','bloqueada','descartada')),
  via           text CHECK (via IN ('A_repetida','B_similar','C_nueva')),
  responsable   text,
  creado_en     timestamptz NOT NULL DEFAULT now(),
  modificado_en timestamptz,
  modificado_por text
);
CREATE INDEX ON ops.peticion (estado, recibido_en DESC);
CREATE INDEX ON ops.peticion (cliente_id, recibido_en DESC);
CREATE TRIGGER t_mod BEFORE UPDATE ON ops.peticion
  FOR EACH ROW EXECUTE FUNCTION core.tocar_modificado();


CREATE TABLE ops.peticion_documento (
  peticion_id  bigint NOT NULL REFERENCES ops.peticion(id) ON DELETE CASCADE,
  documento_id bigint NOT NULL REFERENCES core.documento(id),
  PRIMARY KEY (peticion_id, documento_id)
);


-- Lo que la IA extrae del correo y los adjuntos.
-- Se guarda aparte de la petición: es una interpretación, no un hecho.
CREATE TABLE ops.extraccion (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  peticion_id    bigint NOT NULL REFERENCES ops.peticion(id) ON DELETE CASCADE,
  campos         jsonb NOT NULL,
  faltantes      text[],                  -- lo que no se pudo determinar
  confianza      numeric(4,3) CHECK (confianza BETWEEN 0 AND 1),
  modelo         text NOT NULL,
  version_prompt text NOT NULL,
  creado_en      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON ops.extraccion (peticion_id, creado_en DESC);


CREATE TABLE ops.analisis_plano (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  documento_id   bigint NOT NULL REFERENCES core.documento(id),
  metodo         text NOT NULL CHECK (metodo IN
                   ('geometrico_3d','texto_vectorial','vision','mixto')),
  hallazgos      jsonb NOT NULL DEFAULT '[]'::jsonb,
  bloqueantes    integer NOT NULL DEFAULT 0,
  confianza      numeric(4,3) CHECK (confianza BETWEEN 0 AND 1),
  version_reglas text NOT NULL,
  creado_en      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON ops.analisis_plano (documento_id, creado_en DESC);

COMMENT ON COLUMN ops.analisis_plano.hallazgos IS
  'Lista de {codigo, gravedad, texto, zona}. El sistema afirma que FALTA algo; nunca certifica que el plano esté bien.';


-- =============================================================
-- 7. OPS — ofertas
-- =============================================================

CREATE TABLE ops.version_modelo (
  id         text PRIMARY KEY,            -- p.ej. '2026.11-a'
  descripcion text,
  metricas   jsonb,
  activa     boolean NOT NULL DEFAULT false,
  creado_en  timestamptz NOT NULL DEFAULT now()
);


CREATE TABLE ops.oferta (
  id                        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  peticion_id               bigint NOT NULL REFERENCES ops.peticion(id),
  pieza_id                  bigint REFERENCES core.pieza(id),
  cantidad                  numeric(12,3) NOT NULL,
  via                       text NOT NULL CHECK (via IN ('A_repetida','B_similar','C_nueva')),

  precio_propuesto          core.importe,
  precio_min                core.importe,
  precio_max                core.importe,
  coste_calculado           core.importe,
  desglose                  jsonb,        -- material / máquina / preparación / externo / indirectos
  hipotesis                 text[],       -- lo que se asumió y hay que escribir en la oferta

  fecha_entrega_optima      date,
  fecha_entrega_comprometible date,

  confianza                 numeric(4,3) CHECK (confianza BETWEEN 0 AND 1),
  version_modelo            text REFERENCES ops.version_modelo(id),

  estado                    text NOT NULL DEFAULT 'borrador'
                            CHECK (estado IN ('borrador','revisada','enviada','descartada')),
  precio_enviado            core.importe,
  enviada_en                timestamptz,
  enviada_por               text,
  resultado                 text CHECK (resultado IN ('ganada','perdida','sin_respuesta')),
  resultado_en              date,

  creado_en                 timestamptz NOT NULL DEFAULT now(),
  creado_por                text NOT NULL DEFAULT current_user,
  modificado_en             timestamptz,
  modificado_por            text,
  CONSTRAINT banda_coherente CHECK (
    precio_min IS NULL OR precio_max IS NULL OR precio_min <= precio_max),
  CONSTRAINT nunca_bajo_coste CHECK (
    precio_propuesto IS NULL OR coste_calculado IS NULL
    OR precio_propuesto >= coste_calculado)
);
CREATE INDEX ON ops.oferta (estado, creado_en DESC);
CREATE INDEX ON ops.oferta (pieza_id);
CREATE TRIGGER t_mod BEFORE UPDATE ON ops.oferta
  FOR EACH ROW EXECUTE FUNCTION core.tocar_modificado();

COMMENT ON CONSTRAINT nunca_bajo_coste ON ops.oferta IS
  'Regla dura en la base de datos, no en el código de la aplicación. Aunque un bug o un prompt manipulado lo intente, la base lo rechaza.';


-- Las piezas históricas en las que se apoyó la propuesta.
CREATE TABLE ops.comparable (
  oferta_id        bigint NOT NULL REFERENCES ops.oferta(id) ON DELETE CASCADE,
  pieza_id         bigint NOT NULL REFERENCES core.pieza(id),
  similitud        numeric(5,4),
  precio_historico core.importe,
  minutos_reales   core.minutos,
  fecha_referencia date,
  PRIMARY KEY (oferta_id, pieza_id)
);


-- La señal más valiosa del sistema.
CREATE TABLE ops.correccion (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  oferta_id        bigint NOT NULL REFERENCES ops.oferta(id) ON DELETE CASCADE,
  campo            text NOT NULL,
  valor_propuesto  text,
  valor_corregido  text,
  motivo           text,
  usuario          text NOT NULL DEFAULT current_user,
  creado_en        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON ops.correccion (campo, creado_en DESC);

COMMENT ON TABLE ops.correccion IS
  'Cada vez que cambias 3.800 por 4.200 antes de enviar, ese delta es lo que enseña al sistema tu criterio real. Con 200 correcciones registradas empieza a reproducirlo.';


-- Reglas de facturación y oferta por cliente.
CREATE TABLE ops.regla_cliente (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cliente_id  bigint NOT NULL REFERENCES core.cliente(id),
  clave       text   NOT NULL,   -- 'requiere_num_pedido', 'dia_corte', 'portal', 'agrupa_mensual'
  valor       text,
  notas       text,
  creado_en   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cliente_id, clave)
);


-- Foto de la cola de cada máquina, para el motor de plazos.
CREATE TABLE ops.carga_centro (
  id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  centro_trabajo_id    bigint NOT NULL REFERENCES core.centro_trabajo(id),
  calculado_en         timestamptz NOT NULL DEFAULT now(),
  minutos_comprometidos core.minutos NOT NULL,
  fecha_liberacion     date,
  UNIQUE (centro_trabajo_id, calculado_en)
);
CREATE INDEX ON ops.carga_centro (centro_trabajo_id, calculado_en DESC);


-- =============================================================
-- 8. AUDIT — registro inmutable
-- =============================================================

CREATE TABLE audit.evento (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ts              timestamptz NOT NULL DEFAULT now(),
  actor           text NOT NULL DEFAULT current_user,
  accion          text NOT NULL,
  entidad         text NOT NULL,
  entidad_id      text,
  datos_antes     jsonb,
  datos_despues   jsonb,
  version_sistema text,
  hash_anterior   text,
  hash_propio     text NOT NULL
);
CREATE INDEX ON audit.evento (entidad, entidad_id, ts DESC);
CREATE INDEX ON audit.evento (ts DESC);

-- Encadenado por hash: si alguien modifica una fila del pasado, la cadena se rompe
-- y se detecta. Misma idea que exige Verifactu para las facturas.
CREATE OR REPLACE FUNCTION audit.encadenar() RETURNS trigger AS $$
DECLARE ultimo text;
BEGIN
  SELECT hash_propio INTO ultimo FROM audit.evento ORDER BY id DESC LIMIT 1;
  NEW.hash_anterior := ultimo;
  NEW.hash_propio := encode(digest(
      coalesce(ultimo,'') || NEW.ts::text || NEW.actor || NEW.accion ||
      NEW.entidad || coalesce(NEW.entidad_id,'') ||
      coalesce(NEW.datos_antes::text,'') || coalesce(NEW.datos_despues::text,''),
      'sha256'), 'hex');
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER t_encadenar BEFORE INSERT ON audit.evento
  FOR EACH ROW EXECUTE FUNCTION audit.encadenar();

-- Verificación de integridad de la cadena.
CREATE OR REPLACE FUNCTION audit.verificar_cadena()
RETURNS TABLE (id bigint, ts timestamptz, problema text) AS $$
  WITH recalculado AS (
    SELECT e.id, e.ts, e.hash_propio,
           lag(e.hash_propio) OVER (ORDER BY e.id) AS esperado_anterior,
           e.hash_anterior
    FROM audit.evento e
  )
  SELECT r.id, r.ts, 'la cadena no cuadra con el evento anterior'
  FROM recalculado r
  WHERE r.hash_anterior IS DISTINCT FROM r.esperado_anterior;
$$ LANGUAGE sql STABLE;


-- =============================================================
-- 9. VISTAS DE TRABAJO
-- =============================================================

-- Tarifa vigente hoy por centro
CREATE VIEW core.v_tarifa_actual AS
SELECT DISTINCT ON (t.centro_trabajo_id)
       t.centro_trabajo_id, c.codigo, c.nombre, t.tarifa_minuto, t.vigente_desde
FROM core.tarifa_centro t
JOIN core.centro_trabajo c ON c.id = t.centro_trabajo_id
WHERE t.vigente_desde <= current_date
  AND (t.vigente_hasta IS NULL OR t.vigente_hasta > current_date)
ORDER BY t.centro_trabajo_id, t.vigente_desde DESC;

-- Minutos reales medidos por pieza y operación: la base del modelo de horas
CREATE VIEW core.v_minutos_reales AS
SELECT o.pieza_id,
       p.centro_trabajo_id,
       count(*)                              AS n_partes,
       sum(p.minutos)                        AS minutos_totales,
       sum(o.cantidad)                       AS unidades,
       round(sum(p.minutos)::numeric / nullif(sum(o.cantidad),0), 2) AS minutos_por_unidad
FROM core.parte_trabajo p
JOIN core.orden_fabricacion o ON o.id = p.orden_id
WHERE p.minutos IS NOT NULL
GROUP BY o.pieza_id, p.centro_trabajo_id;

-- Estimado contra real: dónde nos equivocamos sistemáticamente
CREATE VIEW ops.v_desviacion_tiempos AS
SELECT r.pieza_id,
       r.centro_trabajo_id,
       r.minutos_unitario                    AS estimado,
       v.minutos_por_unidad                  AS real_medido,
       round(100 * (v.minutos_por_unidad - r.minutos_unitario)
             / nullif(r.minutos_unitario,0), 1) AS desviacion_pct
FROM core.operacion_ruta r
JOIN core.v_minutos_reales v
  ON v.pieza_id = r.pieza_id AND v.centro_trabajo_id = r.centro_trabajo_id;


-- =============================================================
-- 10. SEGURIDAD BÁSICA DE ROLES
-- =============================================================

CREATE ROLE luanfra_lectura NOLOGIN;
CREATE ROLE luanfra_app     NOLOGIN;

GRANT USAGE ON SCHEMA core, ops, audit TO luanfra_lectura, luanfra_app;
GRANT SELECT ON ALL TABLES IN SCHEMA core, ops TO luanfra_lectura;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA core, ops TO luanfra_app;

-- La auditoría solo admite INSERT. Ni la aplicación puede alterarla.
GRANT INSERT, SELECT ON audit.evento TO luanfra_app;
REVOKE UPDATE, DELETE, TRUNCATE ON audit.evento FROM luanfra_app, luanfra_lectura, PUBLIC;


-- =============================================================
-- 11. BLOQUE OPCIONAL — búsqueda por similitud (necesita pgvector)
-- =============================================================
-- Ejecutar solo cuando tengas la extensión instalada.
-- La dimensión depende del modelo de embeddings que uses.
--
-- CREATE EXTENSION IF NOT EXISTS vector;
--
-- CREATE TABLE core.pieza_embedding (
--   pieza_id   bigint PRIMARY KEY REFERENCES core.pieza(id) ON DELETE CASCADE,
--   modelo     text   NOT NULL,
--   embedding  vector(1536) NOT NULL,
--   creado_en  timestamptz NOT NULL DEFAULT now()
-- );
-- CREATE INDEX ON core.pieza_embedding
--   USING hnsw (embedding vector_cosine_ops);
