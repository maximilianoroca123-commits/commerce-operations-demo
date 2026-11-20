"""Supporting module for the local commerce operations demonstration."""

from movimientos_inventario import registrar as registrar_movimiento

import sqlite3
from contextlib import closing

from errores import ProductoNoEncontradoError
from inventario_reservas import reservado
from pedidos_venta import sincronizar_venta_directa


class ConflictoVentaError(Exception):
    pass


def registrar_venta(conectar_db, referencia, producto_id, cantidad, actor=None):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        from usuarios import comprobar_titular, vincular_actor

        comprobar_titular(db, "directa", referencia, actor)
        existente = db.execute(
            "SELECT * FROM ventas WHERE referencia = ?", (referencia,)
        ).fetchone()
        if existente is not None:
            if (existente["producto_id"], existente["cantidad"]) != (
                producto_id,
                cantidad,
            ):
                raise ConflictoVentaError("La referencia ya corresponde a otra venta")
            return {
                "estado": "venta_ya_registrada",
                "venta": dict(existente),
                "pedido_venta_id": sincronizar_venta_directa(db, referencia),
            }

        producto = db.execute(
            "SELECT precio, stock FROM productos WHERE id = ?", (producto_id,)
        ).fetchone()
        if producto is None:
            raise ProductoNoEncontradoError("Producto local no encontrado")
        if cantidad > producto["stock"] - reservado(db, producto_id):
            raise ConflictoVentaError("Stock insuficiente para la cantidad solicitada")

        restante = producto["stock"] - cantidad
        db.execute(
            "UPDATE productos SET stock = ? WHERE id = ?", (restante, producto_id)
        )
        registrar_movimiento(
            db, producto_id, "venta_directa", referencia, -cantidad, "Venta cobrada"
        )
        venta = db.execute(
            """INSERT INTO ventas
               (referencia, producto_id, cantidad, precio_unitario, stock_restante, registrado_en)
               VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
               RETURNING *""",
            (referencia, producto_id, cantidad, producto["precio"], restante),
        ).fetchone()
        vincular_actor(db, sincronizar_venta_directa(db, referencia), actor)
        return {
            "estado": "venta_registrada",
            "venta": dict(venta),
            "pedido_venta_id": sincronizar_venta_directa(db, referencia),
        }
