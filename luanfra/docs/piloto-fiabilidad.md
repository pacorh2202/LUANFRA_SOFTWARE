# Piloto de fiabilidad — septiembre de 2026

Esta entrega prepara un piloto administrativo local. No es una puesta en
producción, un planificador APS completo ni una integración con los CNC.

## Cambios

- Costes: minutos fraccionarios en el cálculo, importes Decimal, validaciones
  y selección explícita entre recargo sobre coste y margen sobre venta.
  Se conserva recargo_coste por defecto para no alterar presupuestos previos.
- Plazos: acumula operaciones repetidas, respeta su secuencia por lote completo,
  valida capacidades y excluye fines de semana y festivos indicados. La fecha
  con colchón no representa una probabilidad de entrega validada.
- Pantalla Taller: simulador editable de capacidad, cola y operaciones.
  No modifica órdenes ni reserva máquinas. La fecha de referencia es el día
  anterior al primer día completo que se considera disponible.
- Rutas: los supuestos de geometría y preparación se muestran y reducen la
  confianza. Las tarifas ausentes o subcontratas pendientes no se sustituyen
  por medias. La ruta sigue siendo una propuesta que requiere revisión técnica.
- Geometría: llamada compatible con cadquery-ocp 7.8.1.1.post1.
- Ofertas: bloqueo por planos con análisis pendiente o incidencias bloqueantes;
  corrección solo en borradores, con motivo, Decimal y actor autenticado.
- Indicadores: no se publica OEE sin calendario real y marcha medida.
  La preparación calculada desde rutas se identifica como estimada.
  Calibración agrupada por orden-operación y cantidades imputadas; verificar
  todavía que el ERP imputa cantidades por parte, no contadores acumulados.
- CSV: diagnóstico sin escrituras, validación conservadora y apartamiento
  de filas dudosas. No deduce el significado económico de las columnas.

## Acceso local del piloto

Todos los usuarios configurados son administradores del piloto con acceso
a los datos de la aplicación. Los selectores de rol del asistente y avisos
son filtros funcionales, no permisos por departamento. No abrir a toda la
plantilla hasta implementar autorización granular, SSO/MFA y revisión técnica.

La API exige Bearer para todas las rutas salvo /vivo. Sin configuración devuelve
503. /sesion devuelve la identidad autenticada. Las claves se mantienen solo
en memoria del navegador; recargar requiere entrar de nuevo.

Generar una clave distinta por administrador en el equipo de despliegue:

```python
import secrets, hashlib, json
clave = secrets.token_urlsafe(32)
print("Clave personal (entregar de forma privada):", clave)
print("Configuración:", json.dumps({hashlib.sha256(clave.encode()).hexdigest(): "administrador"}))
```

Guardar el objeto JSON como ACCESO_CLAVES_JSON en .env, usando comillas simples
alrededor del JSON. Para revocar una clave, eliminar su hash y reiniciar la API.
No publicar claves ni .env. Usar HTTPS y acceso privado al habilitar acceso remoto.

Docker Compose requiere BD_PASSWORD y ACCESO_CLAVES_JSON. Puertos limitados al
equipo local. Adminer se activa solo con --profile administracion. Sigue siendo
un perfil de desarrollo: quedan pendientes separar el usuario administrador de
PostgreSQL y el de aplicación, copias restauradas y despliegue de producción.

## Verificación

Desde luanfra/api: python -m pytest -q. Instalar las dependencias declaradas y
los extras dev y geometria para cubrir el reconocimiento 3D. Desde luanfra/web:
npm ci y npm run build. Los tests añadidos emplean datos sintéticos.

El diagnóstico de exportaciones se ejecuta localmente:

```bash
python scripts/diagnosticar_ordenes.py /ruta/privada/export.csv
```

Devuelve conteos y números de línea, sin nombres de clientes ni importes.
Una fila estructuralmente válida no equivale a un dato contable conciliado.
Exportaciones multilínea o con comillas incorrectas se apartan para revisión.

## Límites que impiden desplegar como sistema definitivo

1. Validar consultas, transacciones y bloqueos contra PostgreSQL con datos
   sintéticos, y conciliar el mapeo del ERP antes de datos de producción.
2. La migración `db/003-minutos-decimales.sql` permite persistir fracciones
   sin redondeo. En bases existentes debe aplicarse explícitamente tras copia
   de seguridad; ver `db/tests/README.md`. Validada con PostgreSQL embebido,
   pendiente de prueba de integración con la API y PostgreSQL 16 en servidor.
3. El planificador usa capacidad media diaria y secuencia de lotes completos;
   no modela intervalos, turnos variables por fecha, operarios compartidos,
   prioridad de pedidos o transferencia parcial de lotes.
4. Los CNC desatendidos requieren identificación y calendarios reales;
   no se les asignan automáticamente 24 horas ni fines de semana.
5. Confirmar alcance de tarifas, significado de Valoración/CosteUnidad,
   fecha prevista frente a real y partes de producción.
6. La autenticación del piloto no resuelve por sí sola auditoría criptográfica,
   privilegios de BD, secretos del histórico Git o protección de archivos CAD.
7. El flujo de nueva revisión de oferta todavía debe construirse. Una oferta
   ya revisada no se puede corregir por este endpoint.

Los CSV, planos y tarifas reales no forman parte de esta entrega Git.
