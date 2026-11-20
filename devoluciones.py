"""Physical returns and refunds recorded as separate business operations."""

from movimientos_inventario import registrar as registrar_movimiento

from auditoria_comercial import registrar as auditar

import json
import sqlite3
from contextlib import closing

from pedidos_venta import ConflictoEntregaError, detalle, registrar_estado


def crear_tablas(db):
    db.execute("""CREATE TABLE IF NOT EXISTS devoluciones_venta (
        pedido_id INTEGER NOT NULL REFERENCES pedidos_venta(id),
        referencia TEXT NOT NULL,
        tipo TEXT NOT NULL CHECK(tipo IN ('devolucion','cancelacion')),
        motivo TEXT NOT NULL,
        solicitud TEXT NOT NULL,
        importe INTEGER NOT NULL CHECK(importe > 0),
        estado_reintegro TEXT NOT NULL DEFAULT 'pendiente'
            CHECK(estado_reintegro IN ('pendiente','fallido','confirmado')),
        creado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        reintegrado_en TEXT,
        PRIMARY KEY(pedido_id,referencia))""")
    db.execute(
        """CREATE TABLE IF NOT EXISTS items_devolucion (
        pedido_id INTEGER NOT NULL,
        referencia TEXT NOT NULL,
        producto_id INTEGER NOT NULL,
        cantidad INTEGER NOT NULL CHECK(cantidad > 0),
        reponer INTEGER NOT NULL CHECK(reponer IN (0,1)),
        PRIMARY KEY(pedido_id,referencia,producto_id),
        FOREIGN KEY(pedido_id,referencia) REFERENCES devoluciones_venta(pedido_id,referencia),
        FOREIGN KEY(pedido_id,producto_id) REFERENCES items_pedido_venta(pedido_id,producto_id))"""
    )


def resumen(db, pedido_id):
    operaciones = []
    for fila in db.execute(
        "SELECT * FROM devoluciones_venta WHERE pedido_id=? ORDER BY creado_en,referencia",
        (pedido_id,),
    ):
        operacion = dict(fila)
        operacion.pop("solicitud")
        operacion["productos"] = [
            dict(x)
            for x in db.execute(
                "SELECT producto_id,cantidad,reponer FROM items_devolucion WHERE pedido_id=? AND referencia=? ORDER BY producto_id",
                (pedido_id, operacion["referencia"]),
            )
        ]
        operaciones.append(operacion)
    total = sum(x["importe"] for x in operaciones)
    confirmado = sum(
        x["importe"] for x in operaciones if x["estado_reintegro"] == "confirmado"
    )
    venta_total = db.execute(
        "SELECT total FROM pedidos_venta WHERE id=?", (pedido_id,)
    ).fetchone()[0]
    comercial = "vigente"
    if operaciones:
        comercial = (
            "cancelada"
            if operaciones[0]["tipo"] == "cancelacion"
            else ("devuelta" if total == venta_total else "devuelta_parcial")
        )
    return {
        "estado_comercial": comercial,
        "operaciones": operaciones,
        "importe_devoluciones": total,
        "importe_reintegrado": confirmado,
        "importe_por_reintegrar": total - confirmado,
    }


# Receive returned goods and restore only resalable units; money is handled separately.
def registrar(conectar_db, pedido_id, referencia, datos, tipo="devolucion"):

    solicitud = json.dumps(datos, sort_keys=True, ensure_ascii=False)
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        pedido = detalle(db, pedido_id)
        anterior = db.execute(
            "SELECT solicitud,tipo FROM devoluciones_venta WHERE pedido_id=? AND referencia=?",
            (pedido_id, referencia),
        ).fetchone()
        if anterior:
            if anterior["solicitud"] != solicitud or anterior["tipo"] != tipo:
                raise ConflictoEntregaError(
                    "La referencia ya fue utilizada con otros datos"
                )
            return resumen(db, pedido_id)
        if pedido["estado_pago"] != "aprobado":
            raise ConflictoEntregaError("Esta operación requiere una venta pagada")
        if tipo == "cancelacion":
            if pedido["estado_entrega"] not in ("pendiente", "preparando", "listo"):
                raise ConflictoEntregaError(
                    "Solo se cancela antes del despacho o entrega. Si salió, registrá su devolución al recibirlo"
                )
            if pedido["devoluciones"]["operaciones"]:
                raise ConflictoEntregaError(
                    "El pedido ya tiene una devolución o cancelación"
                )
            lineas = [
                {
                    "producto_id": x["producto_id"],
                    "cantidad": x["cantidad"],
                    "reponer": True,
                }
                for x in pedido["productos"]
            ]
        else:
            if pedido["estado_entrega"] != "entregado":
                raise ConflictoEntregaError(
                    "Registrá la devolución cuando el pedido esté entregado y recibas los productos"
                )
            lineas = datos["productos"]
        ids = [x["producto_id"] for x in lineas]
        if len(ids) != len(set(ids)):
            raise ConflictoEntregaError(
                "No repitas un producto dentro de la devolución"
            )
        vendidos = {x["producto_id"]: x for x in pedido["productos"]}
        importe = 0
        for linea in lineas:
            producto = vendidos.get(linea["producto_id"])
            devuelto = db.execute(
                "SELECT COALESCE(SUM(cantidad),0) FROM items_devolucion WHERE pedido_id=? AND producto_id=?",
                (pedido_id, linea["producto_id"]),
            ).fetchone()[0]
            if producto is None or linea["cantidad"] + devuelto > producto["cantidad"]:
                raise ConflictoEntregaError(
                    "Producto ajeno al pedido o cantidad superior a la pendiente de devolución"
                )
            importe += linea["cantidad"] * producto["precio_unitario"]
        db.execute(
            "INSERT INTO devoluciones_venta (pedido_id,referencia,tipo,motivo,solicitud,importe) VALUES (?,?,?,?,?,?)",
            (pedido_id, referencia, tipo, datos["motivo"], solicitud, importe),
        )
        for linea in lineas:
            db.execute(
                "INSERT INTO items_devolucion VALUES (?,?,?,?,?)",
                (
                    pedido_id,
                    referencia,
                    linea["producto_id"],
                    linea["cantidad"],
                    int(linea["reponer"]),
                ),
            )
            if linea["reponer"]:
                db.execute(
                    "UPDATE productos SET stock=stock+? WHERE id=?",
                    (linea["cantidad"], linea["producto_id"]),
                )
            registrar_movimiento(
                db,
                linea["producto_id"],
                tipo,
                f"{pedido_id}:{referencia}",
                linea["cantidad"] if linea["reponer"] else 0,
                datos["motivo"],
                linea["cantidad"],
            )
        if tipo == "cancelacion":
            registrar_estado(db, pedido_id, "cancelado")
        auditar(
            db,
            "venta",
            pedido_id,
            "venta_cancelada" if tipo == "cancelacion" else "devolucion_recibida",
            {"referencia": referencia, "importe_pesos": importe, "productos": lineas},
        )
        return resumen(db, pedido_id)


# Record the refund outcome without receiving the same goods again.
def reintegrar(conectar_db, pedido_id, referencia, resultado, caja_esperada=None):

    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        detalle(db, pedido_id)
        fila = db.execute(
            "SELECT estado_reintegro,importe FROM devoluciones_venta WHERE pedido_id=? AND referencia=?",
            (pedido_id, referencia),
        ).fetchone()
        if fila is None:
            raise ConflictoEntregaError("Primero registrá la devolución o cancelación")
        if fila[0] == "confirmado":
            if resultado != "confirmado":
                raise ConflictoEntregaError("El reintegro ya está confirmado")
            return resumen(db, pedido_id)
        if resultado == "confirmado":
            from caja_efectivo import registrar_reintegro

            importe = db.execute(
                "SELECT importe FROM devoluciones_venta WHERE pedido_id=? AND referencia=?",
                (pedido_id, referencia),
            ).fetchone()[0]
            registrar_reintegro(db, pedido_id, referencia, importe, caja_esperada)
        db.execute(
            """UPDATE devoluciones_venta SET estado_reintegro=?,
            reintegrado_en=CASE WHEN ?='confirmado' THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NULL END
            WHERE pedido_id=? AND referencia=?""",
            (resultado, resultado, pedido_id, referencia),
        )
        if fila[0] != resultado:
            auditar(
                db,
                "venta",
                pedido_id,
                "reintegro_actualizado",
                {
                    "referencia": referencia,
                    "anterior": fila[0],
                    "nuevo": resultado,
                    "importe_pesos": fila[1],
                },
            )
        return resumen(db, pedido_id)
