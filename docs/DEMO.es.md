# Recorrido de demostración

[Español](DEMO.es.md) · [English](DEMO.en.md) · [Inicio](../README.es.md)

Usar únicamente datos ficticios y una base de demostración. Los IDs se generan al operar; anotar los que muestre la aplicación. No se presupone que un pedido tenga un número determinado. La preparación de cuentas está en el README.

## 1. Circuito automático mínimo

1. Ingresar como `demo_admin`. Elegir Español en el encabezado.
2. Abrir Reposición simulada → Preparar ejemplo → revisar → confirmar.
3. Esperar: con fondo inicial cero, no debe generarse un pedido.
4. Agregar **2000** ficticios al fondo y confirmar. Esperar el pedido automático.
5. Comprobar tres unidades a **500,50**: reservado **1501,50**, pagado **0**, disponible **498,50**.
6. Pulsar Simular pago aprobado y confirmar. Pagado pasa a **1501,50**; reservado a **0**.
7. Observar preparación → listo → despachado sin registrar avisos manualmente. El stock físico sigue en **0**.
8. Abrir el pedido → Recibir mercadería. Remito `demo-auto-1`, cantidad **3**, costo unitario **500,50**. Revisar y confirmar.
9. Comprobar stock **3**, pedido recibido y disponible **498,50**.
10. Volver al panel y Pausar generación de pedidos.

Preparar ejemplo es idempotente: si ya existe, conserva su estado; no reinicia stock ni agrega fondos. Para repetir desde cero usar otra base aislada, no modificar tablas manualmente.

## 2. Compra online y atención

1. Como administrador, crear producto ficticio `Demo item`, categoría Tecnología, marca `Demo`, precio **1000** y stock **5**.
2. Como `demo_customer`, agregar una unidad al carrito, elegir Retiro en local y crear el pedido.
3. Antes del pago: físico **5**, reservada **1**, disponible **4**. Aprobar el pago simulado antes del vencimiento de la reserva.
4. Físico pasa a **4**. Como `demo_staff`, avanzar la entrega por preparación, listo y entregado.
5. Como cliente, solicitar devolución. La solicitud sola no cambia stock ni dinero.
6. Como empleado, abrir Atención al cliente, recibir una unidad apta y confirmar el reintegro simulado.
7. Completar la atención con una explicación ficticia. El cliente debe verla en su solicitud.
8. Resultado: stock **5**, reintegrado **1000**, pendiente **0**, solicitud atendida. La compra online no ingresa billetes en caja.

Crear el pedido y pagar son pasos distintos. Entregar no vuelve a cobrar ni a descontar. Las devoluciones usan el precio guardado de la venta.

## 3. Caja y venta presencial

1. Como empleado, abrir un turno con fondo inicial contado **1000**. Si ya existe un turno, revisarlo antes de continuar.
2. Vender una unidad de `Demo item` a **1000**; efectivo recibido **2000**, vuelto **1000**.
3. Comprobar stock **5 → 4** y saldo esperado **1000 → 2000**. Descargar el comprobante.
4. Registrar devolución apta de una unidad: stock **4 → 5**, con dinero todavía pendiente.
5. Confirmar el reintegro de **1000** desde la caja abierta: saldo esperado vuelve a **1000**.
6. Contar y cerrar con **1000**; diferencia esperada **0**.

La recepción de la devolución y el egreso de dinero son dos operaciones. Un turno anterior cerrado no se modifica para registrar un reintegro posterior.

## 4. Proveedor y recepción parcial

1. Como administrador, crear `Demo procurement`, precio **1000** y stock **0**, sin regla individual.
2. Como `demo_supplier`, abrir Mi catálogo. Agregar código `demo-offer-1`, nombre `Demo procurement`, marca `Demo`, Tecnología, costo **500,50**, disponibilidad **3**. Conservar otras ofertas que se quieran mantener activas.
3. Como administrador, vincular esa oferta al producto local y evaluar reposición. Anotar el pedido creado.
4. Como proveedor, registrar aviso confirmado y despachado. El stock local permanece en **0**.
5. Como empleado, recibir remito `demo-delivery-1`, una unidad a **500,50**: estado parcial, pendientes **2**, stock **1**.
6. Recibir remito `demo-delivery-2`, dos unidades al mismo costo: recibido, pendientes **0**, stock **3**.
7. Como proveedor, consultar el pedido cerrado: no admite nuevos avisos.

El catálogo publicado es completo: omitir una fila la deja inactiva. Este pedido normal no usa el fondo ficticio del circuito automático.

## 5. Comprobación bilingüe

Cambiar ES/EN con un carrito o formulario sin enviar. Deben conservarse sus valores y sesión, sin nuevas escrituras. Cambian etiquetas, estados presentados, fechas e importes; nombres y notas propios permanecen iguales.

Durante un diálogo de confirmación, finalizar o cancelar antes de cambiar el idioma. El comprobante descargado usa el idioma seleccionado. Repetir el mismo recorrido en una base nueva y en inglés produce los mismos efectos en cantidades, dinero e historial.

## 6. Operaciones complementarias

| Operación | Acceso y condición |
| --- | --- |
| Cancelar compra del cliente | Solicitud antes del despacho; administración procesa y gestiona el reintegro |
| Cancelar pedido al proveedor | Administración, sin recepciones; el simulado sin pagar libera reserva y pausa |
| Corregir remito o cerrar con faltantes | Administración, pedido normal parcial; no usar un pedido de muestra ya pagado |
| Administrar cuentas | Consola/API; no se modifican roles desde una compra |
| Reglas individuales y alertas | API/consola; separadas de la regla general de muestra |
| Emergencias y comprobantes | API/consola; fondo y registros distintos |
| Respaldo y restauración | Crear/verificar por API/consola; restaurar localmente con API detenida |

Las ramas alternativas requieren registros de ensayo adecuados. No se puede cancelar, corregir y cerrar con faltantes el mismo pedido después de recibirlo por completo.
