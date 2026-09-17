# Cómo rellenar el mapa de las naves

## Lo que ya tienes hecho

Dos cosas del ERP ahorran la mayor parte del trabajo:

1. **El maestro de máquinas** ya tiene código, nombre y una columna `Posición`.
   Exporta esa tabla entera y me la pasas: con eso tengo los nombres reales y
   los códigos, que es lo más pesado.

2. **El plano de planta en tiempo real** que ya pinta el ERP. Una captura de
   pantalla a tamaño completo me da la forma de la nave y la distribución
   aproximada. No hace falta que sea exacta.

## Lo que necesito de ti

### Imprescindible

- **Forma y medidas de cada nave.** Largo y ancho en metros. Si no son
  rectangulares, un croquis a mano con las medidas de cada lado sirve
  perfectamente. Una foto del papel vale.
- **Qué máquina está en qué nave.** Si el maestro no lo dice, basta una columna
  más en el Excel.
- **Dónde está la entrada de material y la zona de expedición.** Marca el flujo:
  por dónde entra el redondo y por dónde sale la pieza terminada.

### Muy recomendable

- **Posición aproximada de cada máquina.** No hace falta precisión de
  topógrafo: coordenadas en metros desde la esquina inferior izquierda de cada
  nave, a ojo. Un error de un metro no importa.
- **Tamaño aproximado de las máquinas grandes.** La Soraluce de 10 metros no
  puede dibujarse igual que un taladro de columna.
- **Zonas fijas:** oficinas, almacén, control de calidad, vestuarios, el
  recorrido del puente grúa.

### Si lo tienes a mano

- **Plano en PDF o DWG** de la nave, del que sea: seguridad contra incendios,
  seguro, licencia de actividad. Suele existir y es lo más rápido de todo.

## Formato

Rellena `maquinas-mapa.csv` con punto y coma como separador y coma decimal,
igual que los export del ERP. Las columnas:

| Columna | Qué poner |
|---|---|
| `codigo` | El código del ERP. Es la clave que enlaza con la carga |
| `nombre` | Nombre completo, el que usa la gente |
| `nave` | 1 o 2 |
| `seccion` | La sección del ERP: TORNOS CNC, FRESADORA CNC, LASER… |
| `x`, `y` | Metros desde la esquina inferior izquierda de su nave |
| `ancho`, `largo` | Metros. A ojo vale |
| `orientacion` | `horizontal` o `vertical` |
| `notas` | Lo que quieras: cuello de botella, en desuso, sin conectar |

## Lo que NO hace falta

- Que esté a escala exacta
- Que estén las 60 máquinas desde el principio: empieza por las 20 que más
  trabajo mueven
- Software de CAD: un croquis en papel y el Excel son suficientes

## Cómo lo haría yo

Imprime el plano de planta del ERP, dale una vuelta a la nave con el papel y un
boli, y anota las medidas y lo que esté mal colocado. Media hora andando por el
taller vale más que dos horas delante del ordenador.
