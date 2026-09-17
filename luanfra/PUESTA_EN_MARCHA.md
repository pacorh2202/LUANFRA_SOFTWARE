# Puesta en marcha, de cero a funcionando

Esta guía va por fases. La idea que la ordena: **arranca hoy lo que depende de
otros, porque tarda solo, y aprovecha la espera para lo que depende de ti.**

Si haces esto en el orden contrario, te pasarás tres semanas esperando a JLQS
sin haber avanzado nada.

---

## Fase 0 — Hoy, una hora

Objetivo: verlo funcionando en tu portátil con vuestros datos reales.

1. Instala **Docker Desktop** desde docker.com. Acepta WSL2 y reinicia.
2. Descomprime el proyecto en `C:\luanfra`.
3. Copia `.env.example` a `.env` y cambia `BD_PASSWORD`.
4. Abre PowerShell en esa carpeta y ejecuta `docker compose up -d`.
5. Copia `DATOS_PRESUPUESTO.xltx` a la carpeta `api` y carga:

       docker compose exec api python scripts/cargar_presupuestos_csv.py DATOS_PRESUPUESTO.xltx --limpiar

6. Abre `http://localhost:8000/docs` y prueba `/kpis` y `/analisis/dispersion-precios`.

**No sigas a la fase siguiente hasta que esto funcione.** Todo lo demás se apoya
aquí.

---

## Fase 1 — Esta semana: lo que tarda solo

Estas cuatro cosas no dependen de ti y tienen semanas de plazo. Arráncalas hoy
aunque no vayas a usarlas hasta dentro de un mes.

### 1.1 Acceso a la base del ERP

Ya mandaste la petición. Si en una semana no hay respuesta, insiste. Es el
cuello de botella real del proyecto: sin partes de trabajo, 18 de los 20
indicadores de taller salen sin dato.

Lo que necesitas exactamente:
- Un usuario de SQL Server con permiso de solo lectura sobre la base `QGIS`
- O una copia de seguridad restaurada en otra máquina

### 1.2 Asesor laboral

Antes de diseñar la captura en planta, no después. Los puntos a plantearle:
información previa y por escrito a la plantilla, consulta a la representación
legal si la hay, evaluación de impacto, y nada de biometría para fichar.

### 1.3 Buzón de ofertas

Pide a quien lleve el correo un buzón `ofertas@luanfra.com` con **acceso IMAP
activado**. Ese será el que se comunique a los clientes.

### 1.4 Confidencialidad y datos

- Revisa los acuerdos firmados con Industrias YUK, Renold y el resto: ¿permiten
  procesar sus planos en un servicio externo?
- Si vas a usar IA, contrata el acuerdo de tratamiento de datos con Anthropic y
  pide retención cero.

---

## Fase 2 — Esta semana: lo que depende solo de ti

Mientras esperas lo anterior.

### 2.1 Mírate los datos

Abre `/docs` y recorre estos endpoints con calma:

| Endpoint | Qué te va a enseñar |
|---|---|
| `/kpis` | Tasa de éxito real, 27% y cayendo |
| `/kpis/taller/diagnostico` | Qué se puede medir hoy y qué falta |
| `/analisis/dispersion-precios` | Piezas ofertadas a precios muy distintos |
| `/analisis/seguimiento-ofertas` | A quién llamar hoy |
| `/avisos` | La bandeja de acciones, por rol |

Dedica una mañana. De aquí salen decisiones que no tienen nada que ver con el
software.

### 2.2 Prueba el análisis de planos a mano

Coge veinte planos de peticiones recientes y compruébalos tú contra la lista del
blueprint. En una tarde sabrás si ese módulo va a funcionar en vuestro caso.

### 2.3 Activa la IA y pruébala con cinco correos

1. Saca una clave en `console.anthropic.com`
2. Ponla en `.env` como `ANTHROPIC_API_KEY`
3. `docker compose restart api`
4. `docker compose exec api pip install anthropic`
5. Prueba el asistente en `/docs`, endpoint `/asistente`

Copia cinco peticiones reales de clientes y mira si las entiende. Si acierta en
cuatro, el módulo de correo funcionará.

### 2.4 Mide la línea base

Anota hoy estos números, aunque sea a ojo:

- Días entre entregar y facturar
- Días en responder a una petición de oferta
- Cuántos plazos se cumplen
- Horas semanales dedicadas a presupuestar

Sin línea base no podrás demostrar que el proyecto ha servido para algo, y eso
importa tanto para la deducción de I+D como para convencer a dirección.

---

## Fase 3 — Cuando llegue el acceso al ERP

### 3.1 Explora el esquema

    docker compose exec api python scripts/explorar_erp.py

Te deja `salida/erp/informe.md` con el mapa completo: tablas, filas, relaciones
y cobertura temporal. Pásamelo y hacemos el mapeo campo a campo.

Truco: si no encuentras las tablas de presupuestos, abre una oferta que
reconozcas en el QGIS, coge su importe y búscalo:

    docker compose exec api python scripts/explorar_erp.py --buscar "4237,50"

### 3.2 Arranca la sincronización

Tres cadencias: histórico una vez, maestros cada noche, operativo cada diez
minutos. El operativo es el que alimenta las fechas de entrega.

### 3.3 Los indicadores se llenan solos

En cuanto entren los partes de trabajo, el cuadro de taller pasa de 2 a 20
indicadores con dato. Y ahí es donde empiezan a doler.

### 3.4 Calibra los tiempos

    GET /mecanizado/calibracion

Compara los tiempos teóricos con los imputados de verdad y te da el factor por
máquina. **Hasta que no hagas esto, el motor de mecanizado sirve para comparar
piezas entre sí, no para poner precio.**

---

## Fase 4 — Modo sombra, dos meses

El sistema presupuesta todo lo que entra y te lo manda. Tú sigues ofertando como
siempre. Al final comparas.

La métrica: **qué porcentaje de propuestas caen dentro del ±10% de lo que
habrías puesto tú**, mirando solo la vía A (piezas repetidas).

- Por encima del 80%: listo para usar
- Entre el 50% y el 80%: usable con revisión atenta
- Por debajo del 50%: hay que revisar el modelo antes de tocar nada

Y guarda cada corrección que hagas. Con doscientas registradas el sistema empieza
a reproducir tu criterio, que hoy vive en una sola cabeza.

---

## Fase 5 — Producción, por partes

No lo enciendas todo a la vez para todo el mundo. Ese es el error que mata estos
proyectos.

**Primero:** los avisos, con la bandeja de una sola persona. Son de solo lectura
y no pueden estropear nada. Si esa persona los encuentra útiles, se extiende.

**Después:** el presupuestador para la vía A, con revisión humana obligatoria de
todas las ofertas.

**Luego:** el buzón de correo, para que el expediente se prepare solo.

**Al final:** las fechas comprometibles en la oferta y el análisis de planos.

---

## Fase 6 — Lo que hay que mantener vivo

Un sistema así sin nadie que lo cuide se degrada en un año.

| Cada | Qué |
|---|---|
| Día | Mirar la bandeja de avisos |
| Semana | Revisar las correcciones registradas |
| Mes | Recalibrar tiempos, revisar tarifas y precios de material |
| Trimestre | Repasar los indicadores contra la línea base |
| Semestre | Restaurar una copia de seguridad de verdad, con cronómetro |
| Año | Revisar accesos y actualizar dependencias |

---

## Resumen del calendario

| Cuándo | Qué |
|---|---|
| Hoy | Levantarlo en tu portátil |
| Esta semana | Insistir a JLQS, asesor laboral, buzón, clave de IA |
| Semanas 2-3 | Mirarte los datos, probar planos a mano, línea base |
| Cuando llegue el ERP | Explorar, mapear, sincronizar, calibrar |
| Meses 2-3 | Modo sombra |
| Mes 4 | Producción por partes |

---

## Cómo saber si va bien

No por lo que hace el software, sino por estos cuatro números:

1. **Días de entrega a factura.** De 90 a menos de 5.
2. **Días en responder una oferta.** Menos de 2.
3. **Plazos cumplidos.** Más del 90%.
4. **Horas de administración en presupuestar y facturar.** La mitad.

Si en seis meses esos cuatro no se han movido, el proyecto no está funcionando
por mucho código que tenga.
