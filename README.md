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

Desde `18.0.1.2.1`, **Ubicación destino** es opcional al guardar la solicitud.
Si hay líneas de traslado, se exige al confirmar la solicitud y al generar
traslados. Las solicitudes que contienen únicamente compras pueden confirmarse
y generar órdenes sin ese campo. Esta actualización utiliza el ajuste normal
del esquema de Odoo; no necesita un script de migración adicional.

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
- **Categoría de productos** en la solicitud filtra los productos de sus líneas
  a esa categoría y todas sus descendientes. Sin categoría se permiten todas,
  incluyendo solicitudes mixtas. Al cambiarla, los productos existentes deben
  seguir perteneciendo a la categoría seleccionada; no se eliminan líneas.
- Cada línea tiene un **Tipo**: **Compra** o **Traslado**. Una solicitud puede
  combinar ambos. El origen es obligatorio para las líneas de traslado, tanto
  en el formulario como al crear o editar por API.
- **Generar compras** procesa únicamente las líneas de compra seleccionadas con
  cantidad positiva. Cada línea debe tener proveedor. Se crea una orden por combinación
  de proveedor y tipo de operación; A&B e insumos con operaciones distintas nunca
  se mezclan en una misma orden aunque compartan proveedor.
- **Generar traslados** procesa únicamente las líneas de traslado seleccionadas
  con cantidad positiva. Todas usan la **Ubicación destino** del encabezado;
  pueden tener orígenes distintos, elegidos en **Ubicación origen** de cada línea.
  Se agrupan por origen y se utiliza el tipo de operación interna de ese almacén.
  Para otro destino se debe crear otra solicitud. No se permite trasladar entre
  una misma ubicación ni omitir silenciosamente líneas sin origen.
- La existencia de una línea de traslado se consulta en su origen; la de una
  línea de compra, en la ubicación del encabezado. En compras, la recepción
  continúa usando el destino del tipo de operación configurado para su categoría.
- Las pestañas **Compras generadas** y **Traslados generados** muestran los
  documentos vinculados, sus estados y ubicaciones, y permiten abrirlos desde la
  solicitud, con los permisos habituales de Compras e Inventario.
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
