# Instalación para probarlo en tu ordenador

Tres formas, de menos a más. La primera no requiere instalar nada.

---

## Opción A — Solo ver la interfaz (2 minutos, sin instalar nada)

Abre `prototipo-luanfra.html` con doble clic. Se abre en el navegador y funciona
sin conexión. Puedes navegar por las seis pantallas, filtrar ofertas, aprobar,
corregir precios y usar el simulador de capacidad.

Es un prototipo con datos ficticios: sirve para juzgar la interfaz, no para
trabajar.

---

## Opción B — El sistema completo (20 minutos)

### 1. Instalar Docker Desktop

Descárgalo de `docker.com/products/docker-desktop` e instálalo.

En Windows te pedirá activar WSL2; acepta y reinicia cuando lo pida. Al terminar,
abre Docker Desktop y espera a que el icono de la ballena deje de moverse.

Para comprobar que va, abre PowerShell y escribe:

    docker --version

### 2. Descomprimir el proyecto

Descomprime `luanfra-proyecto.zip` en una carpeta sin acentos ni espacios.
Por ejemplo `C:\luanfra`.

### 3. Crear el fichero de configuración

Dentro de esa carpeta, copia `.env.example` y llámalo `.env`.

En PowerShell, desde la carpeta del proyecto:

    copy .env.example .env

Ábrelo con el Bloc de notas y cambia al menos la contraseña:

    BD_PASSWORD=la_que_tu_quieras

El resto puedes dejarlo como está de momento.

### 4. Arrancar

Desde la misma carpeta:

    docker compose up -d

La primera vez tarda unos minutos porque se descarga todo. Cuando termine:

- Interfaz:            http://localhost:5173
- API y documentación: http://localhost:8000/docs
- Base de datos:       http://localhost:8080

### 5. Meter datos

**Con datos de prueba inventados:**

    docker compose exec api python scripts/sembrar_demo.py

**Con tus presupuestos reales:** copia `DATOS_PRESUPUESTO.xltx` dentro de la
carpeta `api` del proyecto y ejecuta:

    docker compose exec api python scripts/cargar_presupuestos_csv.py DATOS_PRESUPUESTO.xltx --limpiar

Tarda un par de minutos. Al terminar tendrás 47.085 presupuestos dentro.

### 6. Ver que funciona

Abre `http://localhost:8000/docs`. Es la documentación automática de la API: cada
endpoint se puede probar desde ahí pulsando "Try it out". Empieza por
`/kpis` y por `/piezas/similares`.

---

## Opción C — Además, el reconocimiento de ficheros 3D

El núcleo geométrico pesa unos 200 MB y va aparte:

    docker compose exec api pip install cadquery-ocp

Después, en `/docs`, el endpoint `/mecanizado/reconocer-3d` acepta un STEP y
devuelve volumen exacto, agujeros, escalones y material a arrancar.

---

## Comandos del día a día

| Qué quieres | Comando |
|---|---|
| Arrancar | `docker compose up -d` |
| Parar | `docker compose down` |
| Ver qué pasa | `docker compose logs -f api` |
| Ejecutar las pruebas | `docker compose exec api python -m pytest -q` |
| Entrar en la base de datos | `docker compose exec db psql -U luanfra -d luanfra` |
| Empezar de cero | `docker compose down -v` y volver a arrancar |

`docker compose down -v` borra la base de datos entera. Úsalo solo cuando quieras
empezar limpio.

---

## Si algo falla

**"docker: command not found"** — Docker Desktop no está arrancado. Ábrelo y
espera a que el icono se quede quieto.

**"port is already allocated"** — otro programa usa ese puerto. Cambia el número
de la izquierda en `docker-compose.yml`, por ejemplo `"5433:5432"`.

**La interfaz carga pero sin datos** — la API no arranca. Mira el motivo con
`docker compose logs api`.

**Todo va muy lento la primera vez** — normal, está descargando las imágenes.
La segunda vez arranca en segundos.

---

## Qué NO hace falta instalar

Python, PostgreSQL, Node ni nada más. Todo va dentro de los contenedores. Docker
Desktop es lo único que toca tu ordenador, y se desinstala como cualquier programa.
