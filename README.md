# Solicitud de Compra Interna — Odoo 18

## Instalación y actualización

Colocar el repositorio en el directorio de addons con el nombre
`purchase_request_app`, reiniciar Odoo y actualizar el módulo:

```bash
odoo-bin -d NOMBRE_BD -u purchase_request_app --stop-after-init
```

La versión `18.0.1.1.0` depende explícitamente de `purchase_stock`. Al actualizar,
asigna una secuencia a las solicitudes existentes que todavía tienen `/` o
`Nuevo`, conserva los números válidos y toma la compañía de la ubicación destino
para las solicitudes anteriores. Las nuevas solicitudes, incluidas las copias y
las creaciones por importación/API sin `name`, reciben una referencia `SC00001`.
Si falta una secuencia activa con código `purchase.request`, se muestra un error.
La secuencia del módulo se comparte entre compañías y se protege con `noupdate`
para conservar su formato y contador.

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
- **Generar solicitud de compra** procesa las líneas seleccionadas con cantidad
  positiva. Cada línea debe tener proveedor. Se crea una orden por combinación
  de proveedor y tipo de operación; A&B e insumos con operaciones distintas nunca
  se mezclan en una misma orden aunque compartan proveedor.
- La ubicación destino del formulario sigue utilizándose para consultar
  existencias y generar traslados. En compras, el destino lo determina el tipo de
  operación configurado para la categoría del producto.

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
referencias anteriores.
