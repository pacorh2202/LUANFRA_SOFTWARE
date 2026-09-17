-- Migración 003: conservar minutos fraccionarios, sin redondeo implícito.
-- Ejecutar una sola vez, después de 002, con el propietario del esquema.
-- Transacción completa: si existen dependencias adicionales, aborta sin CASCADE.
BEGIN;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                 WHERE n.nspname='core' AND t.typname='minutos'
                   AND t.typbasetype='integer'::regtype) THEN
    RAISE EXCEPTION '003 requiere core.minutos entero; ya aplicada o esquema incompatible';
  END IF;
END $$;
DROP VIEW ops.v_desviacion_tiempos;
DROP VIEW core.v_minutos_reales;
ALTER DOMAIN core.minutos RENAME TO minutos_enteros_legacy;
CREATE DOMAIN core.minutos AS numeric
  CHECK (VALUE >= 0 AND VALUE < 'Infinity'::numeric);
COMMENT ON DOMAIN core.minutos IS
  'Minutos decimales no negativos y finitos. Sin redondeo al persistir; nunca horas.';
ALTER TABLE core.operacion_ruta ALTER COLUMN minutos_preparacion TYPE core.minutos USING minutos_preparacion::numeric;
ALTER TABLE core.operacion_ruta ALTER COLUMN minutos_unitario TYPE core.minutos USING minutos_unitario::numeric;
ALTER TABLE core.parte_trabajo ALTER COLUMN minutos TYPE core.minutos USING minutos::numeric;
ALTER TABLE ops.comparable ALTER COLUMN minutos_reales TYPE core.minutos USING minutos_reales::numeric;
ALTER TABLE ops.carga_centro ALTER COLUMN minutos_comprometidos TYPE core.minutos USING minutos_comprometidos::numeric;
DROP DOMAIN core.minutos_enteros_legacy;

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


GRANT SELECT ON core.v_minutos_reales, ops.v_desviacion_tiempos TO luanfra_lectura;
GRANT SELECT, INSERT, UPDATE ON core.v_minutos_reales, ops.v_desviacion_tiempos TO luanfra_app;
COMMIT;
