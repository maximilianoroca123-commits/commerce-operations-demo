# Arquitectura y funcionamiento

[Español](ARCHITECTURE.es.md) · [English](ARCHITECTURE.en.md) · [Inicio](../README.es.md)

## Diseño general

El sistema es una aplicación FastAPI modular con una base SQLite local y dos clientes: web y consola. La web usa JavaScript, HTML y CSS del mismo origen. Los módulos separan entrada HTTP, identidad, reglas del negocio, almacenamiento e historial, sin presentar cada archivo como un microservicio independiente.

| Responsabilidad | Archivos principales |
| --- | --- |
| Rutas y ciclo de vida del servidor | `servidor.py`, `rutas_*.py` |
| Contratos y límites de entrada | `modelos.py`, modelos de `usuarios.py` y de routers |
| Identidad, roles y pertenencia | `autenticacion.py`, `usuarios.py` |
| Catálogo e inventario | `repositorio_sqlite.py`, `movimientos_inventario.py`, `inventario_reservas.py` |
| Cobro y seguimiento de venta | `caja.py`, `caja_efectivo.py`, `pedidos_venta.py` |
| Devolución y atención | `devoluciones.py`, `gestiones_cliente.py` |
| Ofertas y recepción al proveedor | `catalogos.py`, `reposicion.py`, `pedidos_proveedor.py` |
| Regla general y fondo ficticio | `reposicion_simulada.py` |
| Auditoría y recuperación | `auditoria_comercial.py`, `respaldos.py` |
| Interfaz y traducción | `interfaz/*.js`, `interfaz/i18n.js` |

Los servicios ejecutan SQL cuando necesitan coordinar una transacción completa. No se utiliza un ORM. El CRUD original de `main.py` conserva su base `productos.db`; la aplicación web utiliza `productos_api.db`. `menu_api.py` es cliente de esta última API.

## Contratos y permisos

FastAPI y Pydantic comprueban tipos, cantidades y campos aceptados. Las dependencias verifican identidad y rol. Los servicios validan además stock, dinero, estado y pertenencia en el momento de actuar.

Autenticar una cuenta no permite consultar cualquier pedido: el cliente sólo accede a sus compras y el proveedor a sus pedidos. La interfaz orienta mediante botones disponibles, pero el servidor conserva la autorización real.

Las contraseñas se guardan derivadas con scrypt y sal individual. Las respuestas de validación evitan repetir datos sensibles de la solicitud. Las credenciales de la web permanecen en memoria y se eliminan al cerrar sesión.

## Transacciones y reintentos

Las operaciones relacionadas se confirman dentro de una transacción. `BEGIN IMMEDIATE` obtiene el turno de escritura antes de verificar y modificar saldos o cantidades que podrían estar en competencia.

Los remitos, ventas, aportes y otras operaciones utilizan referencias y comprobaciones de repetición. Repetir una referencia con los mismos datos recupera el resultado cuando el recorrido lo admite; reutilizarla con contenido distinto genera conflicto.

Si una respuesta se pierde, la web conserva referencia y cuerpo de la operación incierta. Reintenta esos mismos datos en lugar de crear otra operación. Esto no constituye una garantía de ejecución exactamente una vez para cualquier servicio externo futuro.

## Inventario y dinero

| Concepto | Significado |
| --- | --- |
| Stock físico | Unidades registradas en el negocio |
| Reserva de mercadería | Unidades comprometidas por compras abiertas |
| Disponible | Stock físico menos unidades reservadas |
| Por recibir | Mercadería pedida al proveedor que aún no ingresó |
| Caja de ventas | Efectivo esperado y contado por turno |
| Fondo de emergencia | Registro previo de compras y gastos de emergencia |
| Fondo simulado | Dinero ficticio reservado y pagado en la muestra automática |

Crear una compra online reserva mercadería; aprobar su pago descuenta el stock correspondiente una sola vez. Entregarla no vuelve a descontar. Recibir una devolución apta y reintegrar dinero son operaciones diferentes.

Generar, pagar o despachar un pedido al proveedor no agrega unidades al inventario local. Sólo la recepción física confirmada lo hace. La caja de ventas y el fondo simulado no se afectan entre sí.

Los precios locales y la caja usan pesos enteros; los costos de abastecimiento y el fondo simulado usan centavos enteros. Por ejemplo, `costo_pagado_centavos=50050` significa ARS 500,50 por unidad. Los nombres de campo conservan esa distinción.

## Automatización de muestra

La regla general pide 3 unidades cuando el producto elegido llega a stock físico 0, con un máximo de ARS 1000 por unidad, oferta apta y fondos suficientes. Se reserva el importe completo antes de permitir el pago.

El administrador aprueba el pago ficticio con un botón. El proveedor simulado avanza preparación → listo → despacho. Los estados y fechas quedan en SQLite. La recepción sigue siendo manual y puede ser parcial.

La tarea se ejecuta en la API aproximadamente cada segundo; cada paso de preparación/despacho demora unos cinco segundos. El panel consulta resultados cada dos segundos. Cerrar la página no detiene el trabajo si la API permanece activa; detener la API sí lo suspende, con continuidad desde los datos guardados al reiniciar.

Pausar evita pedidos nuevos, sin deshacer reservas ni pagos. Cancelar antes de pagar libera la reserva y pausa la generación. Reintegros a proveedores y cambios de costo después de pagar no están implementados en esta muestra.

## Internacionalización

`messages.json` contiene el catálogo ES/EN; `i18n.js` gestiona idioma y presentación. `messages.js` es su copia generada para el navegador. Tras editar el catálogo se ejecuta `python tools/build_i18n.py`; el paquete ya incluye ese archivo y no necesita generarlo para funcionar. Los elementos de texto se enlazan con funciones de presentación para actualizarse sin recargar ni repetir solicitudes de escritura. Los campos, sesión, carrito y referencias se conservan.

Las traducciones no cambian códigos de estado, campos JSON, categorías persistidas ni identificadores. Las notas y nombres introducidos por usuarios se tratan como datos. Los mensajes propios del simulador se localizan. La descarga del comprobante envía `idioma=es` o `idioma=en`, con la misma verificación de titularidad.

Sólo la preferencia de idioma se guarda en almacenamiento local. Los formularios HTML localizan sus mensajes habituales de validación. La moneda sigue siendo ARS, aunque cambien separadores y formato visual.

## Historial y recuperación

Los movimientos de inventario explican cambios de cantidad. La auditoría identifica actor y operación. Ambos se registran junto al cambio correspondiente. Un respaldo conserva el estado completo, no sólo el catálogo.

Las copias se verifican mediante integridad de SQLite, relaciones y huella SHA-256. La restauración se realiza con el servidor detenido y conserva un resguardo anterior. No se reconstruyen retrospectivamente eventos previos a la incorporación de la auditoría.

## Extensiones deliberadamente separadas

El motor de reglas individuales, compras de emergencia y administración avanzada permanecen en módulos/API/consola existentes. La presentación no agrega nuevos pagos reales ni automatiza transporte físico. Una futura integración externa debería resolver autenticidad de notificaciones, fallos, conciliación y pruebas sin sustituir estas reglas por supuestos de la interfaz.
