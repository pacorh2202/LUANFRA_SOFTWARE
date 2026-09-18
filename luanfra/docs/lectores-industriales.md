# Lectores industriales y motor de decisión — piloto

## Elección técnica

CADEX Manufacturing Toolkit reconoce características de mecanizado de geometría
B-Rep STEP; Werk24 extrae datos técnicos del PDF. Son proveedores comerciales
complementarios. Ninguno conoce por sí mismo las capacidades verificadas,
tarifas y carga de este taller. No se garantiza reconocimiento completo.

Fuentes oficiales consultadas el 18/09/2026:

- https://docs.cadexsoft.com/mtk/mtk_machining
- https://docs.cadexsoft.com/mtk/mtk_converter_example
- https://docs.cadexsoft.com/mtk/mtk_licensing
- https://v2.docs.werk24.io/getting-started/api-requests/
- https://v2.docs.werk24.io/asks/features/

## Implementado y pendiente

`POST /fabricacion/expediente` recibe multipart `step`, `pdf` y `proceso`
(`machining_milling` o `machining_turning`). Ejecuta los adaptadores oficiales,
conserva evidencias de cada archivo y devuelve una huella del par documental.
No envía órdenes ni crea presupuestos. El informe conserva parámetros, unidades,
referencias de geometría/página y datos originales; no inventa equivalencias entre
caras STEP y llamadas PDF. La conciliación y la misma revisión siguen pendientes
de validación humana. Un ensamblaje requiere separar piezas y revisar cantidades.

CADEX: adaptador CLI basado en documentación, probado con un proceso simulado.
Falta ejecutarlo con el SDK y licencias reales; no están incluidos en este repo.
Werk24: SDK 2.6.0 instalado e interfaz comprobada; pruebas de callbacks simulados.
No se ha hecho ninguna petición a su servicio ni se han enviado planos del taller.
El lector exige ambos tipos de respuesta en todas las páginas. Límite piloto:
20 MiB por archivo y 20 páginas PDF. No se declara completitud por recibir JSON.

`POST /fabricacion/decidir` recibe ruta y alternativas revisadas. Cruza proceso,
material y envolvente de bruto/utillaje con máquinas activas, exige referencia
de validación de accesibilidad, herramientas y tolerancias; tarifas integrales
vigentes; carga con sello temporal de como máximo 36 horas. La antigüedad
admitida permite una copia nocturna, no significa carga en tiempo real.
Compara dos heurísticas secuenciales: coste y terminación más temprana. Respeta
precedencia de lote completo y acumula operaciones que vuelven a la misma máquina.
No promete óptimo global, no reserva capacidad ni reordena otros pedidos.

El presupuesto separa material, máquina, preparación, programación, herramientas,
calidad, subcontrata, transporte, otros e indirectos. Importes en euros, sin IVA.
Los extras son por lote; el peso bruto es por pieza y debe estar confirmado.
Un cero debe declararse explícitamente cuando corresponda; un importe desconocido
impide obtener un precio total. Verificar qué incluye la tarifa integral para no
cobrar mano de obra o indirectos dos veces. Preparación se cobra por cada paso:
si varias operaciones comparten un amarre, agruparlas o distribuir el setup
explícitamente antes de pedir la decisión. No se infiere por repetir máquina.

Los plazos externos no están modelados: si hay subcontrata positiva o desconocida,
se omiten fechas. Solo calendario lunes-viernes con festivos aportados; no se
asignan automáticamente horas nocturnas a CNC capaces de trabajar solas. Recursos
humanos compartidos, materiales disponibles y intervalos intradía están pendientes.

El hash y la revisión técnica del endpoint de decisión son declaraciones del
cliente autenticado: todavía no existe un expediente persistido e inmutable que
los enlace. Por eso todas las propuestas requieren aprobación y no hay despacho.
La UI no se ha conectado aún a estos dos endpoints.

## Configuración

Instalar extras en el entorno privado:

```sh
cd luanfra/api
python -m pip install -e '.[dev,geometria,lectores]'
```

Instalar el SDK CADEX autorizado con MTKConverter y sus dos licencias; configurar
`CADEX_MTK_CONVERTER` con ruta absoluta y `CADEX_MTK_VERSION` con versión real.
El programa usa `-i`, `-p`, `-e`, `--no-screenshot`; lee `process_data.json`.
No se ejecuta shell ni se aceptan comandos del cliente. La ejecución termina a
los 120 s. Para producción, aislar el trabajador con límites de memoria/CPU,
concurrencia y almacenamiento: estos límites aún no los impone este endpoint.
CADEX documenta telemetría de licenciamiento y una opción on-premises; confirmar
las condiciones antes de asumir operación sin conexión.

Werk24 necesita una cuenta y configuración del SDK oficial. Confirmar región,
retención y condiciones aplicables a los planos antes de habilitar
`WERK24_HABILITADO=true`. El proveedor procesa documentos fuera del servidor.
No hay fallback silencioso a otra IA ni envío cuando está deshabilitado.
Las variables deben llegar al proceso API; Docker Compose todavía no instala
CADEX ni monta sus licencias ni configura las credenciales de Werk24.

Pruebas locales, sin llamadas comerciales:

```sh
python -m pytest -q tests/test_decision_fabricacion.py tests/test_lectores_industriales.py
```

Ejemplo de solicitud sintética: `docs/ejemplo-decision-fabricacion.json`.
Actualizar fecha de referencia y lectura de carga al repetir la prueba.

## Validación antes de confiar en los resultados

Preparar un conjunto privado de 30 pares STEP/PDF con revisión conocida:
ejes, casquillos, placas, piñones y piezas con cavidades, roscas, GD&T y acabados.
Un técnico marca las características y ruta esperadas. Separar entrenamiento/
calibración y evaluación. Medir omisiones, falsos positivos, asociación cara-cota,
revisión correcta, máquinas válidas y error de tiempos y costes por familia.
Toda omisión crítica detectada bloquea aprobación automática. Superar esta muestra
no demuestra fiabilidad universal. Ampliar con piezas complejas antes de escalar.

Para arrancar la prueba real faltan SDK/licencias CADEX y cuenta Werk24, los
pares STEP/PDF, capacidades verificadas de máquinas, detalle de costes de tarifa
y partes reales por orden-operación-máquina. Los CSV disponibles no sustituyen
esos datos. No se han cargado ni publicado archivos de empresa en esta rama.
