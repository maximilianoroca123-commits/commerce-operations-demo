# Pruebas y verificación

[Español](TESTING.es.md) · [English](TESTING.en.md) · [Inicio](../README.es.md)

## Entorno y ejecución

Se verificó la entrega con Python 3.12.14 y Node 24.22.3. La suite Python utiliza unittest y el cliente de pruebas de FastAPI. Las pruebas de JavaScript utilizan el ejecutor de Node; los contratos de interfaz bilingüe utilizan Happy DOM.

```bash
python -m unittest discover -q
npm ci
npm test
```

Usar el intérprete del entorno virtual y ejecutar desde la raíz del proyecto. Para ejecutar un bloque concreto: `python -m unittest test_portfolio_release -q` o `node --test test_i18n_dom.cjs`.

Resultado de esta entrega: **326 pruebas Python y 41 pruebas JavaScript aprobadas**.

## Cobertura funcional

| Área | Qué se comprueba | Referencias |
| --- | --- | --- |
| Inventario y catálogo | Cantidades, filtros, movimientos y restricciones | `test_regresion.py`, `test_movimientos.py` |
| Acceso y pertenencia | Roles, datos propios, cuentas y contraseñas | `test_usuarios.py`, `test_ciclo_cuentas.py` |
| Ventas y caja | Cobro, vuelto, turno, reintegro y conteo | `test_efectivo.py`, `test_interfaz_ventas_caja.py` |
| Compra online | Reserva, pago, pedido y titularidad | `test_caja.py`, `test_interfaz_cliente.py` |
| Entrega y atención | Transiciones, solicitud y respuesta vinculada | `test_pedidos_venta.py`, `test_interfaz_entregas_atencion.py` |
| Devolución y reintegro | Separación física/financiera y repetición | `test_devoluciones.py`, `test_interfaz_devoluciones.py` |
| Proveedor y remitos | Avisos, pertenencia, parciales y cierres | `test_abastecimiento.py`, `test_interfaz_abastecimiento.py` |
| Reposición automática | Fondos, oferta, reserva, concurrencia y despacho | `test_reposicion_simulada.py` |
| Recuperación y evidencia | Auditoría, respaldos y comprobantes | `test_auditoria_comercial.py`, `test_respaldos.py`, `test_tickets.py` |
| Presentación bilingüe | Idioma, datos sin traducir, formularios y mismas escrituras | `test_i18n_dom.cjs` |
| Edición de portafolio | Comprobantes ES/EN, pertenencia y preparación idempotente | `test_portfolio_release.py` |

Las pruebas HTTP crean bases temporales por caso. La muestra automática controla el reloj para verificar plazos sin depender de largas esperas. También hay casos que dejan avanzar al trabajador de la API sin una pantalla abierta.

## Contratos de idioma

Las nuevas comprobaciones verifican que:

- El acceso, navegación, catálogo y controles se presentan en ambos idiomas.
- La preferencia se conserva sin almacenar credenciales.
- Cambiar de idioma conserva carrito y valores introducidos, sin nuevas escrituras.
- Nombres, marcas y notas se mantienen aunque coincidan con una palabra traducible.
- El circuito automático completo envía los mismos campos y cantidades en ES/EN.
- La actualización periódica mantiene el idioma y no borra un aporte sin enviar.
- Los avisos automáticos se traducen; las notas redactadas por usuarios no.
- Los errores de dominio cuentan con mensajes en inglés y conservan sus códigos HTTP.
- Descargar un comprobante en otro idioma no evita la restricción de pertenencia ni modifica stock.
- La preparación repetida de cuentas no cambia contraseñas existentes.

Los nombres JSON, como `cantidad` y `costo_pagado_centavos`, son contratos de la API; no se traducen al cambiar la interfaz.

## Evidencia y límites

Esta edición se apoya en los recorridos manuales de la versión funcional previa y agrega pruebas automatizadas de la presentación bilingüe. No se afirma que Happy DOM equivalga a una revisión visual en todos los navegadores.

La suite no demuestra ausencia de todo defecto ni sustituye pruebas de una pasarela bancaria, un entorno público o logística real. Para revisar visualmente la entrega, seguir el mismo [recorrido de demostración](DEMO.es.md) en ambos idiomas usando bases aisladas y datos ficticios.

Las capturas personales del desarrollo no se distribuyen. Los fixtures de `tests/fixtures/` son respuestas de una base temporal con identidades sintéticas, sin contraseñas. No contienen la base del usuario ni datos de clientes reales.
