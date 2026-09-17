import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { PGlite } from '@electric-sql/pglite';
import { pgcrypto } from '@electric-sql/pglite/contrib/pgcrypto';

const sql = name => readFile(new URL('../' + name, import.meta.url), 'utf8');
test('migración sobre esquema existente y datos sintéticos', async t => {
  const db = new PGlite({ extensions: { pgcrypto } });
  try {
    await db.exec(await sql('modelo-datos.sql'));
    await db.exec(await sql('002-ajustes-erp.sql'));
    await db.exec(`INSERT INTO core.centro_trabajo (codigo,nombre) VALUES ('TEST','Centro sintético');
      INSERT INTO core.pieza DEFAULT VALUES;
      INSERT INTO core.operacion_ruta (pieza_id,secuencia,centro_trabajo_id,minutos_preparacion,minutos_unitario)
        VALUES (1,1,1,12,3);
      INSERT INTO core.orden_fabricacion (pieza_id,cantidad) VALUES (1,10);
      INSERT INTO core.parte_trabajo (orden_id,centro_trabajo_id,inicio,minutos,cantidad_ok)
        VALUES (1,1,now(),30,10);
      INSERT INTO ops.carga_centro (centro_trabajo_id,minutos_comprometidos) VALUES (1,75);`);
    await db.exec(await sql('003-minutos-decimales.sql'));
    await t.test('conserva los datos enteros', async () => {
      const {rows} = await db.query('SELECT minutos_preparacion::text AS prep, minutos_unitario::text AS unit FROM core.operacion_ruta');
      assert.deepEqual(rows,[{prep:'12',unit:'3'}]);
      assert.equal((await db.query('SELECT minutos::text AS m FROM core.parte_trabajo')).rows[0].m,'30');
      assert.equal((await db.query('SELECT minutos_comprometidos::text AS m FROM ops.carga_centro')).rows[0].m,'75');
    });
    await t.test('las cinco columnas conservan el dominio decimal', async () => {
      const {rows} = await db.query(`SELECT count(*)::int AS n FROM information_schema.columns
        WHERE domain_schema='core' AND domain_name='minutos' AND data_type='numeric'
        AND table_name IN ('operacion_ruta','parte_trabajo','comparable','carga_centro')`);
      assert.equal(rows[0].n,5);
    });
    await t.test('persiste fracciones sin redondearlas', async () => {
      await db.exec(`UPDATE core.operacion_ruta SET minutos_preparacion=0.125, minutos_unitario=1.23456789;
        UPDATE core.parte_trabajo SET minutos=12.3456789;
        UPDATE ops.carga_centro SET minutos_comprometidos=75.125;`);
      const {rows} = await db.query('SELECT minutos_preparacion::text AS prep, minutos_unitario::text AS unit FROM core.operacion_ruta');
      assert.deepEqual(rows,[{prep:'0.125',unit:'1.23456789'}]);
      assert.equal((await db.query('SELECT minutos::text AS m FROM core.parte_trabajo')).rows[0].m,'12.3456789');
      assert.equal((await db.query('SELECT minutos_comprometidos::text AS m FROM ops.carga_centro')).rows[0].m,'75.125');
    });
    await t.test('rechaza negativos, NaN e infinitos al escribir', async () => {
      for (const invalid of ['-0.001','NaN','Infinity','-Infinity']) {
        await assert.rejects(db.query('UPDATE core.parte_trabajo SET minutos=$1::numeric',[invalid]), e=>e.code==='23514');
      }
    });
    await t.test('conserva nulos opcionales y el cero', async () => {
      await db.exec('UPDATE core.parte_trabajo SET minutos=NULL; UPDATE core.operacion_ruta SET minutos_preparacion=0');
      assert.equal((await db.query('SELECT minutos FROM core.parte_trabajo')).rows[0].minutos,null);
    });
    await t.test('vistas accesibles por el rol de lectura', async () => {
      await db.exec('SET ROLE luanfra_lectura');
      await db.query('SELECT * FROM core.v_minutos_reales');
      await db.query('SELECT * FROM ops.v_desviacion_tiempos');
      await db.exec('RESET ROLE');
    });
    await t.test('una repetición falla sin perder datos ni vistas', async () => {
      await assert.rejects(db.exec(await sql('003-minutos-decimales.sql')));
      await db.exec('ROLLBACK');
      assert.equal((await db.query('SELECT minutos_unitario::text AS m FROM core.operacion_ruta')).rows[0].m,'1.23456789');
      await db.query('SELECT * FROM ops.v_desviacion_tiempos');
    });
  } finally { await db.close(); }
});
