# Registro de decisiones

Una línea por decisión, con su motivo. Cuando dentro de un año no recuerdes
por qué algo está así, la respuesta debería estar aquí.

## 2026-09 · PostgreSQL como base propia
SQL Server es el del ERP y no se toca. Postgres para lo nuestro: pgvector para
similitud, jsonb para atributos que aún no sabemos que necesitaremos, y coste cero.

## 2026-09 · Cuatro esquemas: stage / core / ops / audit
`stage` guarda la copia literal del ERP sin transformar. El día que descubramos
que interpretamos mal un campo, se reprocesa desde ahí sin volver a pedir acceso.

## 2026-09 · Dinero en Decimal, tiempo en minutos enteros
Dominios `core.importe` y `core.minutos` para que meter un float sea imposible.
Los decimales de hora son la fuente clásica de descuadres inexplicables.

## 2026-09 · Tarifas y precios con vigencia, en tablas aparte
Para poder reconstruir qué tarifa se aplicó en una oferta de hace dos años.
Un campo `tarifa_actual` haría imposible la auditoría.

## 2026-09 · La regla de precio mínimo vive en la base de datos
`CHECK nunca_bajo_coste` en `ops.oferta`. Si un fallo del código o un correo
manipulado intentan colar un precio bajo coste, la base lo rechaza.

## 2026-09 · Lógica de negocio sin dependencias de base de datos
`servicios/` no importa SQLAlchemy. Se prueba sin infraestructura y es auditable
leyendo un fichero.

## 2026-09 · Tres vías: repetida / parecida / nueva
El sistema debe poder decir "no sé". Un presupuestador que siempre da un número
no es fiable; uno que se calla cuando no sabe, sí.

## 2026-09 · Dos fechas de entrega, nunca una
Óptima y comprometible. Al cliente se le da la comprometible.

## 2026-09 · Interfaz inspirada en Holded
Sidebar de iconos, fila de KPIs, tabla limpia y panel lateral contextual.
Se copia el listón de acabado, no el catálogo de funciones.

## 2026-09 · El ERP hace mucho más de lo que suponíamos
Las capturas mostraron: presupuestos estructurados con situación y fecha de
aceptación, carga real por máquina, plano de planta en tiempo real, estadísticas
de tiempos por cliente y sección, y un presupuestador paramétrico de piñones con
histórico filtrado por Paso, Z y Ø. Consecuencia: el proyecto deja de ser
"construir un sistema" y pasa a ser "llenar huecos concretos".

## 2026-09 · La normalización de descripciones es el trabajo central
En las líneas de presupuesto el código de artículo va casi siempre vacío y la
pieza vive en texto libre. Sin estructurar eso no hay similares, ni comparables,
ni presupuestador para nada que no sea un piñón.

## 2026-09 · Reglas deterministas antes que embeddings
El módulo de piñones acierta filtrando por Paso, Z y Ø: una regla, no un modelo.
Las piezas del taller son geometría, no prosa. Un parecido calculado por reglas
es explicable ("mismo material, Ø un 4% mayor"), gratis y comprobable con casos.
Los embeddings entran después, solo para lo que las reglas no cubran.

## 2026-09 · Los materiales se comparan por grupo, no solo por igualdad
Dos aceros al carbono distintos se mecanizan parecido; un inox y un bronce no.
Material idéntico = 1,0; mismo grupo = 0,55; grupo distinto = 0,15.

## 2026-09 · Dos niveles en el taller: sección y máquina
El ERP planifica por sección (tornos CNC, fresadora CNC, láser…) e imputa por
máquina concreta, y hay más de sesenta. El modelo v1 tenía un solo nivel.

## 2026-09 · El resultado de una oferta se deriva, no se inventa
`core.resultado_desde_situacion()` traduce la situación literal del ERP a
ganada / perdida / sin respuesta. Se guarda también el literal original para no
perder información al traducir.

## 2026-09 · Sincronización: pull, tres cadencias, idempotente
No se instala nada en el servidor del ERP ni se crean triggers. Tiramos nosotros.
Histórico una vez, maestros cada noche, operativo cada 5-10 minutos. Todo contra
`erp_id`, así que reintentar no duplica. El corte incremental retrocede 15 minutos
sobre la carga anterior: los relojes no están sincronizados y perder una fila para
siempre es peor que reprocesar quince minutos.

## 2026-09 · Un fallo en una tabla no aborta la sincronización
Es preferible tener nueve tablas al día y una vieja que ninguna. Cada carga deja
rastro en `stage.carga`, y hay una consulta que detecta tablas que llevan horas
sin una carga correcta: el fallo típico no es que reviente, es que lleva meses
fallando en silencio.

## 2026-09 · La pérdida por dispersión se mide contra la mediana
Contra el máximo saldría una cifra enorme e inútil: el máximo suele ser un caso
raro (urgencia, lote de una unidad). Y solo cuenta lo ofertado por debajo:
cobrar de más otro día no compensa, son clientes y ofertas distintas.

## 2026-09 · El seguimiento de ofertas pondera el tiempo en curva
Llamar al tercer día es pronto y al día noventa es tarde. El punto bueno está
entre la segunda y la cuarta semana. Se combina con el importe y con la tasa de
éxito histórica de ese cliente.

## 2026-09 · La deriva de margen se mide por pendiente, no por extremos
Un trimestre malo aislado no es una tendencia, y comparando el primero con el
último lo parecería. La pendiente solo se mueve si el patrón se repite.

## 2026-09 · El tiempo de mecanizado se calcula, no se adivina
Velocidad de corte, avance, profundidad y número de pasadas. Las mismas fórmulas
que aplica el programador de CNC. El cilindrado se calcula pasada a pasada
porque el diámetro cambia y con él las revoluciones.

## 2026-09 · Los valores de corte son una referencia, no una verdad
La diferencia entre el tiempo teórico y el real puede ser del 40%. Por eso existe
`calibrar_con_historico()`: el modelo teórico da la forma de la curva y los partes
de trabajo dan las constantes. Sin calibrar sirve para comparar piezas entre sí;
calibrado, para poner precio.

## 2026-09 · La geometría de un piñón se deduce, no se pide
Dp = p / sen(180°/Z). Comprobado contra la pantalla de Piñones Especiales del
ERP: paso 19,05 con Z14 da 85,6 mm, exactamente su valor. Así una descripción
sin diámetro ("PIÑON Z18 08B-1") se puede rutar igual.

## 2026-09 · La tolerancia decide la ruta, y ahí está el dinero
`calidad_it()` traduce milímetros a calidad IT y decide si hace falta
rectificadora. Un IT7 en ø100 puede multiplicar el tiempo por cinco. El sistema
lo detecta y redacta la pregunta comercial al cliente.

## 2026-09 · Los KPI llevan objetivo y sentido
Sin `sentido`, la interfaz pintaría de verde un plazo de 90 días. Y cada
indicador sale de una consulta que se puede abrir: un panel en el que no te fías
de un número es un panel que nadie mira a los dos meses.

## 2026-09 · Validación del motor de mecanizado contra 12.701 presupuestos reales
La fórmula Dp = p/sen(180°/Z) coincide con el dato del ERP con un error mediano
del 0,0015% en 12.460 filas. La correlación entre los minutos que estima el motor
y el importe de mano de obra del ERP es 0,82, con una tarifa implícita de
0,60 €/min. El modelo tiene la forma correcta; falta calibrar la constante.

## 2026-09 · El export de piñones solo trae ofertas ACEPTADAS
12.701 filas, todas con orden y fecha de aceptación. Sirve para aprender a poner
precio a una pieza, pero no para saber a partir de qué precio se deja de ganar.
Hay que pedir el export equivalente de las no aceptadas.

## 2026-09 · DPI_ImpTP es precio de venta, no coste
Coincide con 'Importe Unidad' en el 99,9% de las filas, y ImpMat/ImpMO están
calculados con precio de venta (el módulo maneja Precio Coste y Precio Venta por
separado). Por eso la suma da un margen aparente del 3%: no es el margen real.

## 2026-09 · La dispersión de precios hay que controlarla por lote y por año
Sin controlar salían 281.000 € "dejados de cobrar". Controlando tramo de lote y
año, la cifra baja a 25.000 € (0,4% de la facturación). La correlación entre
unidades y precio unitario es -0,545: el efecto lote lo explicaba casi todo.
Cualquier análisis de precios que no controle esas dos variables es ruido.

## 2026-09 · Núcleo geométrico real para el reconocimiento de operaciones
`reconocedor3d.py` carga el sólido en OpenCascade (paquete cadquery-ocp) y
trabaja sobre B-rep exacto, no sobre malla. Volumen, diámetros y profundidades
salen con la precisión del modelo original: comprobado contra el cálculo a mano
en tres piezas, coincidencia exacta.

## 2026-09 · Se separa lo MEDIDO de lo INTERPRETADO
Exacto: volumen, área, envolvente, diámetros, profundidades, pasante o ciego,
interior o exterior. Interpretación: si es torneable, si un cilindro exterior es
un escalón, cuánto material hay que arrancar. Y lo que no se puede saber por
geometría —si un agujero lleva rosca— sale en "dudas" y no se cobra.

## 2026-09 · Dos fallos del reconocedor que solo aparecieron con sólidos reales
1. La normal se invertía dos veces (BRepGProp_Face con UseOrientation=True ya la
   orienta), y un agujero pasante ø10 salía como escalón de torneado de ø10.
2. La torneabilidad comparaba las dos dimensiones menores de la envolvente; un
   casquillo ø60×50 salía como no torneable. Hay que comparar las dos
   perpendiculares al eje.

## 2026-09 · Entrenar un modelo con el histórico sería peor que consultarlo
Un modelo entrenado no explica de dónde sale un número, se queda congelado hasta
el siguiente reentrenamiento e inventa cuando no sabe. La consulta a la base es
trazable, instantánea y puede decir "no sé".

## 2026-09 · La IA entra solo en tres sitios
Leer correos, leer planos y redactar. No calcula precios, no estima tiempos y no
decide rutas: eso es determinista y auditable. Un modelo de lenguaje produce la
salida más plausible, y cuando no sabe un precio se lo inventa con naturalidad.

## 2026-09 · El cliente de IA se inyecta como parámetro
`extraer_de_correo(asunto, cuerpo, llamar)`. En producción `llamar` habla con la
API; en pruebas devuelve respuestas fijas. Las 22 pruebas de la capa de IA corren
sin red y sin gastar una llamada. Cambiar de modelo o de proveedor es cambiar una
función.

## 2026-09 · Falla cerrado
Si la llamada revienta, la respuesta es "no sé" con los campos vacíos. Nunca un
valor por defecto que parezca razonable: eso es lo que mete un dato inventado en
un presupuesto sin que nadie se entere.

## 2026-09 · Se comprueba que la redacción no toca el importe
Si el modelo escribe "unos 1.800 € aproximadamente" en vez de 1.774,66 €, la
redacción entera se descarta. Es el fallo más caro posible y el más fácil de
que pase desapercibido.

## 2026-09 · Motor de avisos: el dato ya existe, lo que falta es el camino
El ERP sabe que una orden va tarde, que un albarán lleva 80 días sin factura y
que una oferta de 25.000 € lleva meses sin contestar. Lo que no existe es el
camino entre ese dato y quien puede actuar. Cada aviso lleva tres cosas que un
informe no tiene: a quién le toca, qué hacer y para cuándo.

## 2026-09 · Cuatro reglas de los avisos
1. Un aviso sin acción en imperativo es ruido.
2. Un aviso sin rol dueño no es de nadie.
3. Mejor avisar antes: un retraso detectado tres días antes vale cien veces más
   que el mismo retraso el día de la entrega.
4. Lo repetido se agrupa: veinte avisos iguales son uno con veinte casos.

## 2026-09 · El aviso proactivo de retraso trae el correo escrito
Cuando una orden no va a llegar, el sistema redacta el correo al cliente con
fecha nueva calculada en días laborables. Es el correo que casi nadie escribe
porque da pereza, y el que cambia por completo cómo se vive un retraso desde
el otro lado.

## 2026-09 · Bandeja por rol, no panel único
Taller, administración, comercial, dirección y oficina técnica ven cosas
distintas. Una bandeja con treinta avisos de los que veintisiete no te tocan
es una bandeja que se deja de mirar a la semana.

## 2026-09 · Catálogo de 20 indicadores de taller, con fórmula y propósito
Cinco categorías: eficiencia de máquina, preparación y lotes, flujo y plazos,
calidad, y estimación y coste. Cada indicador lleva su fórmula escrita, su
unidad, su objetivo y qué datos necesita. Un indicador mal definido es peor que
no tenerlo: dos personas miran el mismo número y entienden cosas distintas.

## 2026-09 · Objetivos de taller por encargo, no de línea de serie
Un OEE del 85% es clase mundial en una línea que hace siempre la misma pieza.
Con lotes de 1 a 250 y sesenta máquinas distintas, entre 45% y 65% ya es bueno.
Poner el objetivo en 85% solo consigue que nadie se lo tome en serio.

## 2026-09 · "Sin dato" no es cero
Cuando falta el dato de partida, el indicador sale como "sin dato" y dice qué
falta. Un panel lleno de ceros se deja de mirar en dos semanas.

## 2026-09 · El diagnóstico dice qué dato capturar primero
`/kpis/taller/diagnostico` comprueba qué hay de verdad en las tablas y señala el
dato que más indicadores desbloquea. Sirve para priorizar la captura en planta
en vez de construir un panel vacío.

## 2026-09 · La eficiencia de flujo es el indicador que más sorprende
Tiempo mecanizando dividido por el plazo total. En un taller típico está entre
el 5% y el 15%: el resto del plazo la pieza está esperando. Es una buena
noticia: para acortar plazos no hacen falta máquinas, hace falta que la pieza
deje de esperar.

## 2026-09 · El asistente no escribe SQL: elige de un catálogo
Un modelo que se equivoca en un JOIN no da un error, da un número plausible y
equivocado. Hay siete consultas escritas y probadas por nosotros; el trabajo del
modelo es elegir cuál encaja y sacar los parámetros. La clave elegida se valida
contra el catálogo y el SQL se comprueba otra vez justo antes de la base.

## 2026-09 · Dos carriles separados y marcados
"datos" son números de la base. "tecnico" es conocimiento general de mecanizado.
La marca de la fuente importa más que la respuesta: quien pregunta tiene que
saber siempre si un número viene de su base o de la cabeza de un modelo.
Mezclarlo es la forma más rápida de que una estimación acabe en una oferta.

## 2026-09 · "No sé" es una respuesta de primera clase
Si ninguna consulta encaja, el asistente lo dice y enseña lo que sí puede
responder. Nunca fuerza la pregunta hacia la consulta más parecida.

## 2026-09 · El catálogo del asistente depende del rol
El taller ve cinco consultas; dirección ve siete. Los importes ganados y las
ofertas abiertas no salen para todo el mundo.

## 2026-09 · Conocimiento específico de elementos de transmisión
Una descripción de piñón lleva cinco datos donde parecía haber uno. Se reconocen
las tres formas de escribir el paso (08B-2, ASA 40-2, PASO 12,7), los ramales
(simple, doble, triple), el módulo distinguido de una rosca métrica, el ángulo
de presión, el dentado helicoidal con su ángulo y sentido, los cuatro diámetros
de un piñón (primitivo, exterior, cubo, taladro), el chavetero, los prisioneros,
el casquillo cónico Taper Lock, el perfil de correa y las normas citadas.

## 2026-09 · Las cotas etiquetadas se extraen antes que las generales
Fallo real: el "8x3,3" de un chavetero se tomaba por el largo y el ancho de la
pieza, y el Ø del cubo por el diámetro exterior. Ahora se retiran del texto las
cotas con etiqueta antes de buscar las dimensiones generales.

## 2026-09 · En una pieza dentada el diámetro que manda es el exterior
Nunca el del taladro ni el del cubo: el exterior es el que hay que tornear.

## 2026-09 · Mismo Z y distinto módulo no es la misma pieza
Cambia el diámetro, la fresa madre y el tiempo de tallado. El comparador pondera
el módulo con un 14% y los ramales con un 8%.
