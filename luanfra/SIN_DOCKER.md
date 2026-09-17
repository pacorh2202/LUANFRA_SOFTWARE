# Si no puedes usar Docker

Pasa a menudo en ordenadores de empresa: política de seguridad, falta de
permisos de administrador o virtualización desactivada en la BIOS. Hay tres
salidas, de menos a más esfuerzo.

---

## Opción 1 — Sin instalar absolutamente nada

**`prototipo-luanfra.html`** — doble clic. Las seis pantallas de la interfaz
funcionando, con datos ficticios. Para juzgar el diseño.

**`informe-luanfra.html`** — doble clic. El análisis completo de tus 47.085
presupuestos reales: evolución por año, concentración de clientes, elasticidad
precio-éxito, dispersión y validación de la geometría.

Los dos son ficheros sueltos. No necesitan conexión, ni servidor, ni permisos.

---

## Opción 2 — Solo Python

Python se puede instalar **sin permisos de administrador**, para tu usuario.
Descárgalo de python.org y en el instalador marca "Install for me only".

Con eso puedes regenerar el informe cuando saques un export nuevo del ERP:

    pip install --user pandas openpyxl
    python generar_informe.py DATOS_PRESUPUESTO.xltx

Y también ejecutar toda la lógica de negocio, que no necesita base de datos:

    pip install --user pytest
    cd api
    python -m pytest -q

Esas pruebas ejercitan el motor de coste, el de plazos, el normalizador, el de
similares, el de mecanizado, los avisos y los indicadores. Es la parte del
sistema donde vive el conocimiento, y funciona sin infraestructura.

---

## Opción 3 — El sistema completo sin Docker

Necesitas tres cosas instaladas a mano. Es más trabajo y más frágil, pero
funciona.

### PostgreSQL portátil

Descarga la versión **ZIP** (no el instalador) de
`enterprisedb.com/download-postgresql-binaries`. Descomprime y arranca:

    .\bin\initdb -D datos -U luanfra -A trust
    .\bin\pg_ctl -D datos -l log.txt start
    .\bin\createdb -U luanfra luanfra
    .\bin\psql -U luanfra -d luanfra -f ..\db\modelo-datos.sql
    .\bin\psql -U luanfra -d luanfra -f ..\db\002-ajustes-erp.sql

### La API

    cd api
    pip install --user fastapi "uvicorn[standard]" sqlalchemy "psycopg[binary]" pydantic-settings pandas openpyxl python-multipart
    python scripts\cargar_presupuestos_csv.py ..\DATOS_PRESUPUESTO.xltx --limpiar
    python -m uvicorn app.main:app --port 8000

Y abre `http://localhost:8000/docs`.

### La interfaz

Necesita Node. Si tampoco puedes instalarlo, usa `/docs`: tiene todas las
funciones y no hace falta nada más.

    cd web
    npm install
    npm run dev

---

## Opción 4 — Pedirlo a informática

Si el proyecto va a seguir adelante, esta es la buena. Lo que hay que pedir:

- Un servidor Linux pequeño en la nave, en la misma red que el ERP
- Docker instalado en ese servidor
- Acceso desde tu equipo por navegador

Ventajas frente a tu portátil: funciona aunque lo apagues, lo pueden usar
varias personas, se puede hacer copia de seguridad de verdad y no expone nada a
internet.

Mientras tanto, con las opciones 1 y 2 puedes avanzar semanas de trabajo.
