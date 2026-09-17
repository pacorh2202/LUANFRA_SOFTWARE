# Validación de la migración 003

Ejecutar con Node.js 20 o posterior:

```sh
cd luanfra/db/tests
npm ci
npm test
```

Se ejecutan el esquema original, la migración 002 y la 003 sobre PostgreSQL
embebido (PGlite), con pgcrypto y datos exclusivamente sintéticos. Comprueba
conservación de enteros, cinco columnas migradas, fracciones sin redondeo,
restricciones, nulos, permisos de lectura y rechazo transaccional de una
segunda ejecución.

No sustituye la prueba de restauración ni las pruebas de API, concurrencia,
rendimiento y bloqueos en un servidor PostgreSQL 16 real.

## Aplicación

En instalaciones nuevas, Docker Compose aplica las tres migraciones al crear
un volumen vacío. Reiniciar un volumen existente NO aplica migraciones.
Para una base existente, hacer y comprobar una copia de seguridad, parar las
escrituras durante una ventana de mantenimiento y ejecutar con el propietario:

```sh
psql -v ON_ERROR_STOP=1 -d luanfra -f db/003-minutos-decimales.sql
```

La migración puede bloquear y reescribir las tablas. Se ejecuta una sola vez,
dentro de una transacción. Si hay vistas o dependencias personalizadas, aborta
sin eliminarlas en cascada: deben revisarse antes de volver a intentarlo.
Recrea las dos vistas originales y los permisos de los roles estándar;
instalaciones con permisos personalizados deben inventariarlos y reponerlos.
No hay reversión automática a enteros: truncaría fracciones nuevas.

La migración cambia la precisión, no el significado de los partes. Las vistas
históricas conservan su definición anterior; su cociente por cantidad de orden
no debe utilizarse como tiempo unitario validado cuando existen varios partes.
La validación de cantidades, operaciones y preparaciones queda pendiente antes
de calibrar presupuestos con datos de planta.
