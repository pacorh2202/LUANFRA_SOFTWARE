# Luanfra — Sistema de ofertas, plazos y trazabilidad

Capa propia sobre el ERP QGIS. **No sustituye al ERP**: lee una copia, calcula y
propone. El ERP sigue siendo la fuente de verdad fiscal.

## Principios que no se negocian

1. Nunca se escribe en el ERP. Solo lectura de una réplica.
2. El sistema no tiene permisos para enviar correo al exterior.
3. La IA no produce números: lee documentos y redacta texto. Los importes salen
   de `app/servicios/motor_coste.py`, que es código determinista.
4. Lo que llega de fuera son datos, nunca instrucciones.
5. El sistema puede decir que falta algo; nunca certifica que algo está bien.
6. Nada se borra: se anula. Todo queda en `audit.evento`, encadenado por hash.

## Empezar aquí

- `INSTALAR.md` — cómo levantarlo en tu ordenador
- `SIN_DOCKER.md` — alternativas si no puedes usar Docker
- `PUESTA_EN_MARCHA.md` — de cero a producción, por fases
- `docs/decisiones.md` — por qué está hecho así

## Arrancar

```bash
cp .env.example .env        # y edita la contraseña
docker compose up -d
make seed                   # datos ficticios para trabajar sin el ERP
```

- Interfaz: http://localhost:5173
- API y documentación automática: http://localhost:8000/docs
- Base de datos por web: http://localhost:8080

## Estructura

```
db/     modelo-datos.sql   Esquema base. Fuente de verdad de la estructura.
        002-ajustes-erp.sql Secciones, colas de máquina, situación de presupuestos.
api/    app/servicios/     Lógica pura: coste, plazos, normalizador, similares.
        app/rutas/         Endpoints HTTP. Finos: solo traducen.
        app/auditoria.py   Escritura en el registro inmutable.
        tests/             Se ejecutan sin base de datos.
        scripts/           Siembra de demo y exploración del ERP.
salida/ Informes generados. Fuera de git: contienen el esquema real.
web/    src/componentes/   Piezas reutilizables.
        src/vistas/        Pantallas.
```

## Por qué la lógica está separada de la base de datos

`motor_coste.py` y `plazos.py` no importan SQLAlchemy. Reciben datos y devuelven
resultados. Eso permite probarlos en milisegundos y, sobre todo, que dentro de dos
años la respuesta a "¿por qué esta oferta salió a este precio?" esté en un fichero
legible y no repartida por toda la aplicación.

```bash
make test     # 404 pruebas, sin levantar nada
```

## Estado

- [x] Esquema de base de datos
- [x] Motor de coste con pruebas
- [x] Motor de plazos y simulador de capacidad
- [x] API de cálculo y panel
- [x] Interfaz: panel, listado de ofertas y ficha de decisión
- [x] Explorador del ERP (`make explorar-demo` para verlo sin conectar)
- [x] Normalizador de descripciones libres a campos estructurados
- [x] Motor de similares y decisión de vía (A / B / C)
- [x] Migración 002: secciones, carga por máquina, situación de presupuestos
- [x] Sincronizador con tres cadencias, incremental e idempotente
- [x] Análisis: dispersión de precios, seguimiento de ofertas, riesgo de plazos, deriva de clientes
- [x] Motor de mecanizado: rutas, tiempos de corte, tolerancias y calibración
- [x] Cuadro de KPIs: comercial, producción, financiero y del propio sistema
- [x] Cargador del export real de presupuestos (47.085 filas desde 2016)
- [x] Analizador STEP sin dependencias (protocolo, envolvente, PMI)
- [x] Reconocedor de operaciones sobre geometría exacta (OpenCascade)
- [x] Capa de IA: extracción de correos, revisión de planos y redacción
- [x] Motor de avisos y bandeja por rol (retrasos, cobros, seguimiento, planos)
- [x] Catálogo de 20 indicadores de taller con diagnóstico de datos
- [x] Asistente conversacional con capa semántica y permisos por rol
- [x] Conocimiento de elementos de transmisión: pasos, ramales, módulo, hélice,
      chaveteros, casquillos cónicos y perfiles de correa
- [ ] Buzón de ofertas conectado por IMAP  ← siguiente paso
- [x] Prototipo navegable de la interfaz (`prototipo-luanfra.html`)
- [ ] Extracción real desde el QGIS  ← bloqueado esperando acceso a la BD
- [ ] Lectura del buzón de ofertas
- [ ] Análisis de planos
- [ ] Búsqueda por similitud (pgvector)

## Reconocimiento 3D

El analizador de texto (`step3d.py`) no necesita nada. El reconocedor de
operaciones (`reconocedor3d.py`) necesita el núcleo geométrico:

```bash
pip install cadquery-ocp
```

Sin él, la API responde 501 en `/mecanizado/reconocer-3d` y el resto sigue
funcionando igual.

## Seguridad

`.env` nunca se sube: está en `.gitignore`. Tampoco `datos/`, `backups/`,
`almacen/` ni ningún `.bak`. El histórico del ERP y los planos de clientes
no entran jamás en el repositorio.
