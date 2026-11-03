# Solicitud de Compra Interna — Odoo 18

## Instalación y actualización

Colocar el repositorio en el directorio de addons con el nombre
`purchase_request_app`, reiniciar Odoo y actualizar el módulo:

```bash
odoo-bin -d NOMBRE_BD -u purchase_request_app --stop-after-init
```

El módulo depende explícitamente de `purchase_stock`. Desde `18.0.1.1.0`, al actualizar,
asigna una secuencia a las solicitudes existentes que todavía tienen `/` o
`Nuevo`, conserva los números válidos y toma la compañía de la ubicación destino
para las solicitudes anteriores. Las nuevas solicitudes, incluidas las copias y
las creaciones por importación/API sin `name`, reciben una referencia `SC00001`.
Si falta una secuencia activa con código `purchase.request`, se muestra un error.
La secuencia del módulo se comparte entre compañías y se protege con `noupdate`
para conservar su formato y contador.

La versión `18.0.1.2.0` mueve `request_type` de la solicitud a sus líneas. La
migración copia el tipo anterior a todas las líneas existentes antes de retirar
el campo del encabezado. Conserva el destino de cada solicitud, los orígenes
de las líneas y las compras y traslados ya vinculados. Si una línea de traslado
antigua no tenía origen, deberá completarse antes de generar el traslado.

Entre `18.0.1.2.1` y `18.0.1.4.1`, **Ubicación destino** era opcional para
compras y se exigía al confirmar solicitudes con traslados o al generarlos.
Desde `18.0.1.4.2` es obligatoria en todas las solicitudes, incluidas las de
solo compras, al crear y editar en el formulario o por importación/API.
En solicitudes antiguas sin destino, debe completarse antes de solicitar,
confirmar, generar documentos o guardar cambios. No se asigna un destino
arbitrario al actualizar.

Desde `18.0.1.3.0`, cada línea muestra su unidad de medida: la unidad de compra
del producto para **Compra** y su unidad de venta para **Traslado**. Al actualizar,
las cantidades de los traslados existentes se convierten de la unidad anterior
a la de venta para conservar la cantidad física; los documentos ya generados
conservan sus unidades y cantidades originales.

Desde `18.0.1.4.0`, las líneas que generan una compra o un traslado quedan
marcadas como **Procesadas** y bloqueadas. La actualización también bloquea
las líneas anteriores que coinciden con documentos vinculados, incluidos los
cancelados, por solicitud, tipo, producto y proveedor u origen. Las versiones
anteriores no guardaban un vínculo con cada línea: si varias líneas coinciden,
todas quedan bloqueadas para evitar volver a generar el mismo documento.
Los documentos eliminados antes de actualizar no dejan evidencia suficiente
para identificar sus líneas.

**Categoría de productos** pasa a ser obligatoria. Las solicitudes anteriores
que la tengan vacía deben completarla al editar el formulario y antes de
confirmarlas o generar documentos; la actualización no asigna una categoría
arbitraria a datos existentes.

Desde `18.0.1.4.2`, el selector resuelve explícitamente la categoría seleccionada
y todas sus descendientes recorriendo `parent_id`, sin depender del índice
`parent_path`. La misma jerarquía se utiliza para validar productos y determinar
la operación A&B. Por ejemplo, seleccionar `TODOS / A&B` incluye productos de
`TODOS / A&B / ABARROTES / Abart` y de cualquier nivel inferior.

## Configuración por compañía

En **Ajustes > Compras > Solicitudes de compra**, configurar:

- **Categoría de A&B**: categoría padre que identifica A&B. Se incluyen sus
  productos directos y todas las subcategorías, sin depender del nombre.
- **Tipo de operación de A&B**: recepción con la ubicación destino de A&B,
  por ejemplo `A&B/Stock`.
- **Tipo de operación de insumos**: recepción para productos fuera de A&B,
  con la ubicación destino correspondiente a insumos.

Los tipos de operación deben estar activos, pertenecer a la compañía y tener
una ubicación destino interna activa. La categoría A&B y la operación aplicable
son necesarias antes de generar compras. Para compras se configuran operaciones
de **recepción**: al confirmar la orden, Odoo crea la recepción en el destino del
tipo de operación seleccionado. Si el almacén utiliza varias etapas, se respeta
su flujo de recepción configurado.

## Uso

- **Ubicación destino** y **Ubicación origen** muestran únicamente ubicaciones
  internas cuya ruta termina en `/Stock` (sin distinguir mayúsculas). Se muestra
  la ruta completa, por ejemplo `A/Stock`, y se excluyen las ubicaciones padre y
  otros estantes o ubicaciones internas.
  **Ubicación destino** es obligatoria para todos los tipos de solicitud.
- **Categoría de productos** en la solicitud filtra los productos de sus líneas
  a esa categoría y todas sus descendientes. Es obligatoria y debe abarcar todos
  los productos de la solicitud. Al cambiarla, los productos existentes deben
  seguir perteneciendo a la categoría seleccionada; no se eliminan líneas.
- Cada línea tiene un **Tipo**: **Compra** o **Traslado**. Una solicitud puede
  combinar ambos. El origen es obligatorio para las líneas de traslado, tanto
  en el formulario como al crear o editar por API.
- **Unidad de medida** se muestra siempre y se determina automáticamente por
  el tipo de línea y el producto, aunque ambas unidades coincidan. La cantidad
  solicitada y la existencia se expresan en esa unidad; las compras y movimientos
  generados utilizan la misma unidad que la línea. Por ejemplo, un producto que
  se compra por docena y se vende por unidad usa docenas para compras y unidades
  para traslados.
- **Generar compras** procesa únicamente las líneas de compra seleccionadas con
  cantidad positiva que aún no estén procesadas. Cada línea debe tener proveedor. Se crea una orden por combinación
  de proveedor y tipo de operación; A&B e insumos con operaciones distintas nunca
  se mezclan en una misma orden aunque compartan proveedor.
- **Generar traslados** procesa únicamente las líneas de traslado seleccionadas
  con cantidad positiva que aún no estén procesadas. Todas usan la **Ubicación destino** del encabezado;
  pueden tener orígenes distintos, elegidos en **Ubicación origen** de cada línea.
  Se agrupan por origen y se utiliza el tipo de operación interna de ese almacén.
  Para otro destino se debe crear otra solicitud. No se permite trasladar entre
  una misma ubicación ni omitir silenciosamente líneas sin origen.
- Al generar el documento, la línea queda **Procesada**: se conserva su selección
  y no se permite desmarcarla, editarla ni eliminarla, tampoco por importación/API.
  El bloqueo permanece si se cancela o elimina el documento generado o se reinicia
  la solicitud. Las líneas pendientes y las nuevas siguen siendo editables.
  Los botones se ocultan cuando no quedan líneas pendientes con cantidad positiva
  de su tipo y, en el servidor, excluyen siempre las ya procesadas. Las llamadas
  simultáneas se serializan para impedir documentos duplicados.
  Tampoco se permite cambiar el destino tras generar un traslado, cambiar la
  compañía o eliminar una solicitud con líneas procesadas.
- La existencia de una línea de traslado se consulta en su origen; la de una
  línea de compra, en la ubicación del encabezado. En compras, la recepción
  continúa usando el destino del tipo de operación configurado para su categoría.
- Las pestañas **Compras generadas** y **Traslados generados** muestran los
  documentos vinculados, sus estados y ubicaciones, y permiten abrirlos desde la
  solicitud, con los permisos habituales de Compras e Inventario.
- Al abrir un traslado interno vinculado a una solicitud, su formulario incluye
  el botón **Imprimir traslado**. Desde `18.0.1.4.1`, este botón ejecuta el reporte
  estándar **Operaciones de albarán** (`stock.report_picking`) en PDF, en cualquier
  estado del traslado, usando la acción `stock.action_report_picking`.
  Al final del reporte de estos traslados aparecen dos espacios de firma,
  **Despacho** y **Recibido**, uno junto al otro. Se imprimen después del contenido
  y permanecen juntos si es necesario pasar a una página nueva.
- El cierre automático requiere cubrir todas las cantidades: compras confirmadas
  para las líneas de compra y movimientos terminados para las líneas de traslado.
  Un mismo producto puede aparecer en ambos tipos sin que una compra complete el
  traslado. Los traslados parciales permanecen pendientes hasta completar el saldo.

## Pruebas

Ejecutar en una base de pruebas con Odoo 18 y los addons oficiales disponibles:

```bash
odoo-bin -d purchase_request_test -i purchase_request_app \
  --test-enable --test-tags /purchase_request_app \
  --without-demo=all --stop-after-init
```

Las pruebas cubren numeración, copias, formularios, filtros de ubicaciones,
categorías descendientes, solicitudes mixtas, recepción en el destino configurado,
agrupación por proveedor, configuración incompleta, traslados y migración de
referencias anteriores. También cubren solicitudes con ambos tipos, agrupación
por origen con destino común, orígenes obligatorios, existencias en origen,
cierre por cantidades, traslados parciales y migración del tipo a las líneas.
Además, verifican la categoría obligatoria, el bloqueo de líneas procesadas,
su persistencia tras cancelar/eliminar documentos, generación de nuevas líneas
sin duplicar las anteriores y actualización de líneas históricas.
También cubren búsquedas por nombre y código en subcategorías profundas,
jerarquías con un índice desactualizado y destino obligatorio para todos los tipos.
