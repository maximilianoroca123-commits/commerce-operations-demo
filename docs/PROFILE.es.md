# Descripción para portafolio

[Español](PROFILE.es.md) · [English](PROFILE.en.md) · [Inicio](../README.es.md)

## Título

Sistema de gestión comercial con interfaz ES/EN y reposición simulada

## Descripción

Proyecto personal de demostración para gestionar operaciones de un negocio pequeño: inventario, ventas, caja, pedidos online, entregas, devoluciones, atención al cliente y abastecimiento.

Desarrollado con Python, FastAPI, SQLite y JavaScript. La interfaz web permite cambiar entre español e inglés conservando la misma lógica, sesión y datos. Incluye control por roles, titularidad de pedidos, historial de movimientos y comprobantes bilingües.

La demostración de reposición evalúa stock, ofertas y fondos ficticios, reserva el importe de compra y permite aprobar un pago simulado. El proveedor automático avanza hasta el despacho; la recepción manual confirma las unidades que ingresan al inventario.

El repositorio incluye código, instalación local, recorridos reproducibles y pruebas automatizadas de reglas de negocio, permisos, reintentos y traducción. Los pagos y proveedores automáticos son simulados: no hay transacciones bancarias reales ni facturación fiscal.

## Capacidades demostradas

- Separación entre interfaz, API, reglas del negocio y persistencia.
- Operaciones relacionadas dentro de transacciones SQLite.
- Control de acceso y pertenencia de registros.
- Prevención de duplicados mediante referencias y reintentos controlados.
- Automatización por estados persistentes y presentación bilingüe.
- Documentación de resultados esperados y pruebas de regresión.

## Alcance de la experiencia presentada

Es una muestra personal desarrollada iterativamente con asistencia de IA y comprobaciones funcionales. No se presenta como experiencia comercial con un cliente, una integración bancaria real ni un sistema productivo desplegado.
