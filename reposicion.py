"""Supplier selection, purchase orders, delivery notes and goods receipt."""

from movimientos_inventario import registrar as registrar_movimiento

from auditoria_comercial import registrar as auditar

import sqlite3
from contextlib import closing

from errores import ProductoNoEncontradoError
from inventario_reservas import reservado

CANTIDAD_REPOSICION = 3
PEDIDO_ABIERTO = (
    "recibido_en IS NULL AND cancelado_en IS NULL AND cerrado_incompleto_en IS NULL"
)


class ConflictoReposicionError(Exception):
    pass


def orden_identificador(valor):
    if valor.isascii() and valor.isdecimal():

        digitos = valor.lstrip("0")
        return (0, len(digitos), digitos, valor)
    return (1, valor.casefold(), valor)


def prioridad_oferta(oferta):
    return (
        oferta["costo_centavos"],
        orden_identificador(oferta["proveedor"]),
        orden_identificador(oferta["id_externo"]),
    )


def generar_reposicion(conectar_db, producto_id):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        regla = db.execute(
            "SELECT 1 FROM reglas_reposicion WHERE producto_id=?", (producto_id,)
        ).fetchone()
        if regla:
            from reposicion_automatica import evaluar

            return evaluar(db, producto_id)
        producto = db.execute(
            "SELECT stock FROM productos WHERE id = ?", (producto_id,)
        ).fetchone()
        if producto is None:
            raise ProductoNoEncontradoError("Producto local no encontrado")

        pendiente = db.execute(
            f"SELECT * FROM pedidos_reposicion WHERE producto_id = ? AND {PEDIDO_ABIERTO}",
            (producto_id,),
        ).fetchone()
        if pendiente is not None:
            return {
                "estado": "pedido_pendiente",
                "pedido": pedido_con_estado(pendiente),
            }
        if producto["stock"] != 0:
            return {"estado": "con_stock"}

        ultima_compra = db.execute(
            """SELECT costo_pagado_centavos FROM pedidos_reposicion
               WHERE producto_id = ? AND (recibido_en IS NOT NULL OR cerrado_incompleto_en IS NOT NULL)
               ORDER BY COALESCE(recibido_en, cerrado_incompleto_en) DESC, id DESC LIMIT 1""",
            (producto_id,),
        ).fetchone()
        ultimo_costo = ultima_compra["costo_pagado_centavos"] if ultima_compra else None
        ofertas = db.execute(
            """SELECT o.proveedor, o.id_externo, o.costo_centavos
               FROM vinculos_oferta v JOIN ofertas_proveedor o USING (proveedor, id_externo)
               WHERE v.producto_id = ? AND o.vigente = 1 AND o.stock_proveedor >= ?
                 AND (? IS NULL OR o.costo_centavos <= ?)""",
            (producto_id, CANTIDAD_REPOSICION, ultimo_costo, ultimo_costo),
        )
        oferta = min(ofertas, key=prioridad_oferta, default=None)
        if oferta is None:
            return {
                "estado": "sin_oferta_elegible",
                "ultimo_costo_centavos": ultimo_costo,
            }

        cursor = db.execute(
            """INSERT INTO pedidos_reposicion
               (producto_id, proveedor, id_externo, cantidad, costo_ofertado_centavos)
               VALUES (?, ?, ?, ?, ?)""",
            (
                producto_id,
                oferta["proveedor"],
                oferta["id_externo"],
                CANTIDAD_REPOSICION,
                oferta["costo_centavos"],
            ),
        )
        pedido = db.execute(
            "SELECT * FROM pedidos_reposicion WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        auditar(
            db,
            "pedido_proveedor",
            pedido["id"],
            "pedido_proveedor_creado",
            {
                "producto_id": producto_id,
                "proveedor": oferta["proveedor"],
                "cantidad": CANTIDAD_REPOSICION,
                "costo_unitario_centavos": oferta["costo_centavos"],
            },
        )
        return {"estado": "pedido_generado", "pedido": dict(pedido)}


def recibir_pedido(conectar_db, pedido_id, costo_pagado_centavos):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        pedido = buscar_pedido(db, pedido_id)
        if pedido["cancelado_en"] is not None:
            raise ConflictoReposicionError("El pedido está cancelado")
        if pedido["cerrado_incompleto_en"] is not None:
            raise ConflictoReposicionError("El pedido está cerrado incompleto")

        if pedido["recibido_en"] is not None:
            if pedido["costo_pagado_centavos"] != costo_pagado_centavos:
                raise ConflictoReposicionError("El pedido ya se recibió con otro costo")
            return {"estado": "ya_recibido", "pedido": dict(pedido)}

        if pedido["cantidad_recibida"] > 0:
            raise ConflictoReposicionError("Registrá el saldo como una nueva entrega")

        aplicar_entrega(db, pedido, pedido["cantidad"], costo_pagado_centavos)
        return {"estado": "recibido", "pedido": dict(buscar_pedido(db, pedido_id))}


# Persist physical stock, inventory movement and audit records in the same transaction.
def aplicar_entrega(db, pedido, cantidad, costo_pagado_centavos, referencia="completa"):
    from reposicion_simulada import validar_recepcion, recepcion_completada

    validar_recepcion(db, pedido, costo_pagado_centavos)
    actualizado = db.execute(
        "UPDATE productos SET stock = stock + ? WHERE id = ? AND stock <= ?",
        (cantidad, pedido["producto_id"], 2**63 - 1 - cantidad),
    )
    if actualizado.rowcount != 1:
        raise ConflictoReposicionError("La recepción supera el máximo de stock")

    registrar_movimiento(
        db,
        pedido["producto_id"],
        "recepcion",
        f'{pedido["id"]}:{referencia}',
        cantidad,
        "Recepción de proveedor",
    )
    total_recibido = pedido["cantidad_recibida"] + cantidad
    db.execute(
        """UPDATE pedidos_reposicion SET cantidad_recibida = ?, costo_pagado_centavos = ?,
               recibido_en = CASE WHEN ? = cantidad
                   THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') END
           WHERE id = ?""",
        (total_recibido, costo_pagado_centavos, total_recibido, pedido["id"]),
    )

    if total_recibido == pedido["cantidad"]:
        recepcion_completada(db, pedido["id"])
    auditar(
        db,
        "pedido_proveedor",
        pedido["id"],
        "mercaderia_recibida",
        {
            "remito": referencia,
            "cantidad": cantidad,
            "costo_unitario_centavos": costo_pagado_centavos,
        },
    )


# The delivery-note reference identifies a receipt; conflicting reuse is rejected.
def registrar_entrega(
    conectar_db, pedido_id, referencia, cantidad, costo_pagado_centavos
):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        pedido = buscar_pedido(db, pedido_id)
        entrega = db.execute(
            """SELECT referencia, cantidad, costo_pagado_centavos, registrado_en
               FROM recepciones_pedido WHERE pedido_id = ? AND referencia = ?""",
            (pedido_id, referencia),
        ).fetchone()
        if entrega is not None:
            if (entrega["cantidad"], entrega["costo_pagado_centavos"]) != (
                cantidad,
                costo_pagado_centavos,
            ):
                raise ConflictoReposicionError(
                    "La referencia ya se usó con otros datos"
                )
            return {
                "estado": "entrega_ya_registrada",
                "entrega": dict(entrega),
                "pedido": pedido_con_estado(pedido),
            }

        if pedido["cancelado_en"] is not None:
            raise ConflictoReposicionError("El pedido está cancelado")
        if pedido["cerrado_incompleto_en"] is not None:
            raise ConflictoReposicionError("El pedido está cerrado incompleto")
        if cantidad > pedido["cantidad"] - pedido["cantidad_recibida"]:
            raise ConflictoReposicionError("La cantidad supera el saldo pendiente")
        costo_anterior = pedido["costo_pagado_centavos"]
        if costo_anterior is not None and costo_anterior != costo_pagado_centavos:
            raise ConflictoReposicionError(
                "El costo unitario debe coincidir con el de la primera entrega"
            )

        aplicar_entrega(db, pedido, cantidad, costo_pagado_centavos, referencia)
        entrega = db.execute(
            """INSERT INTO recepciones_pedido
               (pedido_id, referencia, cantidad, costo_pagado_centavos, registrado_en)
               VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
               RETURNING referencia, cantidad, costo_pagado_centavos, registrado_en""",
            (pedido_id, referencia, cantidad, costo_pagado_centavos),
        ).fetchone()
        return {
            "estado": "entrega_registrada",
            "entrega": dict(entrega),
            "pedido": pedido_con_estado(buscar_pedido(db, pedido_id)),
        }


def listar_pedidos(conectar_db, estado=None, producto_id=None):
    filtros = []
    parametros = []
    if estado == "pendiente":
        filtros.append(f"{PEDIDO_ABIERTO} AND cantidad_recibida = 0")
    elif estado == "parcial":
        filtros.append(f"{PEDIDO_ABIERTO} AND cantidad_recibida > 0")
    elif estado == "recibido":
        filtros.append("recibido_en IS NOT NULL")
    elif estado == "cancelado":
        filtros.append("cancelado_en IS NOT NULL")
    elif estado == "cerrado_incompleto":
        filtros.append("cerrado_incompleto_en IS NOT NULL")
    if producto_id is not None:
        filtros.append("producto_id = ?")
        parametros.append(producto_id)

    consulta = "SELECT * FROM pedidos_reposicion"
    if filtros:
        consulta += " WHERE " + " AND ".join(filtros)

    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        filas = db.execute(consulta + " ORDER BY id DESC", parametros)
        return [pedido_con_estado(fila) for fila in filas]


def consultar_pedido(conectar_db, pedido_id):
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        return pedido_con_estado(buscar_pedido(db, pedido_id))


def buscar_pedido(db, pedido_id):
    fila = db.execute(
        "SELECT * FROM pedidos_reposicion WHERE id = ?", (pedido_id,)
    ).fetchone()
    if fila is None:
        raise ProductoNoEncontradoError("Pedido no encontrado")
    return fila


def pedido_con_estado(fila):
    pedido = dict(fila)
    estado = "pendiente"
    if fila["cancelado_en"] is not None:
        estado = "cancelado"
    elif fila["recibido_en"] is not None:
        estado = "recibido"
    elif fila["cerrado_incompleto_en"] is not None:
        estado = "cerrado_incompleto"
    elif fila["cantidad_recibida"] > 0:
        estado = "parcial"
    saldo = fila["cantidad"] - fila["cantidad_recibida"]
    pedido["cantidad_no_entregada"] = saldo if estado == "cerrado_incompleto" else 0
    pedido["cantidad_pendiente"] = saldo if estado in ("pendiente", "parcial") else 0
    pedido["estado"] = estado
    return pedido


def cancelar_pedido(conectar_db, pedido_id):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        pedido = buscar_pedido(db, pedido_id)
        if pedido["recibido_en"] is not None:
            raise ConflictoReposicionError("El pedido ya se recibió")
        if pedido["cancelado_en"] is not None:
            return {"estado": "ya_cancelado", "pedido": pedido_con_estado(pedido)}

        if pedido["cerrado_incompleto_en"] is not None:
            raise ConflictoReposicionError("El pedido está cerrado incompleto")
        if pedido["cantidad_recibida"] > 0:
            raise ConflictoReposicionError("El pedido ya tiene una recepción parcial")

        from reposicion_simulada import cancelar_db

        cancelar_db(db, pedido_id)
        db.execute(
            """UPDATE pedidos_reposicion
               SET cancelado_en = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?""",
            (pedido_id,),
        )
        auditar(db, "pedido_proveedor", pedido_id, "pedido_proveedor_cancelado")
        return {
            "estado": "cancelado",
            "pedido": pedido_con_estado(buscar_pedido(db, pedido_id)),
        }


def cerrar_incompleto(conectar_db, pedido_id):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        pedido = pedido_con_estado(buscar_pedido(db, pedido_id))
        if pedido["estado"] == "cerrado_incompleto":
            return {"estado": "ya_cerrado_incompleto", "pedido": pedido}
        from reposicion_simulada import exigir_pedido_normal

        exigir_pedido_normal(db, pedido_id)
        if pedido["estado"] != "parcial":
            raise ConflictoReposicionError(
                "Solo se puede cerrar incompleto un pedido parcial"
            )
        db.execute(
            """UPDATE pedidos_reposicion
               SET cerrado_incompleto_en = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
               WHERE id = ?""",
            (pedido_id,),
        )
        auditar(
            db,
            "pedido_proveedor",
            pedido_id,
            "pedido_proveedor_cerrado_incompleto",
            {"sin_recibir": pedido["cantidad_pendiente"]},
        )
        return {
            "estado": "cerrado_incompleto",
            "pedido": pedido_con_estado(buscar_pedido(db, pedido_id)),
        }


def corregir_entrega(
    conectar_db, pedido_id, referencia, correccion, cantidad, costo, motivo
):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        pedido = pedido_con_estado(buscar_pedido(db, pedido_id))
        clave = (pedido_id, referencia, correccion)
        anterior = db.execute(
            """SELECT * FROM correcciones_recepcion
               WHERE pedido_id = ? AND referencia = ? AND correccion = ?""",
            clave,
        ).fetchone()
        if anterior is not None:
            datos = (
                anterior["cantidad"],
                anterior["costo_pagado_centavos"],
                anterior["motivo"],
            )
            if datos != (cantidad, costo, motivo):
                raise ConflictoReposicionError(
                    "El código de corrección ya se usó con otros datos"
                )
            return {
                "estado": "correccion_ya_registrada",
                "correccion": dict(anterior),
                "pedido": pedido,
            }

        entrega = db.execute(
            """SELECT cantidad, costo_pagado_centavos FROM recepciones_pedido
               WHERE pedido_id = ? AND referencia = ?""",
            (pedido_id, referencia),
        ).fetchone()
        if entrega is None:
            raise ProductoNoEncontradoError("Remito no encontrado")
        if pedido["estado"] != "parcial":
            raise ConflictoReposicionError(
                "Solo se pueden corregir remitos de un pedido parcial abierto"
            )
        from reposicion_simulada import exigir_pedido_normal

        exigir_pedido_normal(db, pedido_id)
        diferencia = cantidad - entrega["cantidad"]
        if diferencia > pedido["cantidad_pendiente"]:
            raise ConflictoReposicionError(
                "La cantidad corregida supera el total pedido"
            )
        if (
            costo != entrega["costo_pagado_centavos"]
            and pedido["cantidad_recibida"] != entrega["cantidad"]
        ):
            raise ConflictoReposicionError(
                "El costo solo se puede corregir si hay un único remito"
            )

        actualizado = db.execute(
            "UPDATE productos SET stock = stock + ? WHERE id = ? AND stock BETWEEN ? AND ?",
            (
                diferencia,
                pedido["producto_id"],
                max(0, reservado(db, pedido["producto_id"]) - diferencia),
                2**63 - 1 - max(0, diferencia),
            ),
        )
        if actualizado.rowcount != 1:
            raise ConflictoReposicionError("El ajuste dejaría el stock fuera de rango")

        registrar_movimiento(
            db,
            pedido["producto_id"],
            "correccion_remito",
            f"{pedido_id}:{referencia}:{correccion}",
            diferencia,
            motivo,
        )
        total = pedido["cantidad_recibida"] + diferencia
        db.execute(
            """UPDATE pedidos_reposicion SET cantidad_recibida = ?, costo_pagado_centavos = ?,
               recibido_en = CASE WHEN ? = cantidad THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') END
               WHERE id = ?""",
            (total, costo, total, pedido_id),
        )
        db.execute(
            """UPDATE recepciones_pedido SET cantidad = ?, costo_pagado_centavos = ?
               WHERE pedido_id = ? AND referencia = ?""",
            (cantidad, costo, pedido_id, referencia),
        )
        registrada = db.execute(
            """INSERT INTO correcciones_recepcion
               (pedido_id, referencia, correccion, cantidad_anterior, costo_anterior_centavos,
                cantidad, costo_pagado_centavos, motivo, registrado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
               RETURNING *""",
            (
                *clave,
                entrega["cantidad"],
                entrega["costo_pagado_centavos"],
                cantidad,
                costo,
                motivo,
            ),
        ).fetchone()
        auditar(
            db,
            "pedido_proveedor",
            pedido_id,
            "recepcion_corregida",
            {
                "remito": referencia,
                "correccion": correccion,
                "cantidad_anterior": entrega["cantidad"],
                "cantidad_nueva": cantidad,
                "costo_unitario_centavos": costo,
            },
        )
        return {
            "estado": "correccion_registrada",
            "correccion": dict(registrada),
            "pedido": pedido_con_estado(buscar_pedido(db, pedido_id)),
        }


def listar_correcciones(conectar_db, pedido_id, referencia):
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        if (
            db.execute(
                "SELECT 1 FROM recepciones_pedido WHERE pedido_id = ? AND referencia = ?",
                (pedido_id, referencia),
            ).fetchone()
            is None
        ):
            raise ProductoNoEncontradoError("Remito no encontrado")
        filas = db.execute(
            """SELECT * FROM correcciones_recepcion WHERE pedido_id = ? AND referencia = ?
               ORDER BY registrado_en, rowid""",
            (pedido_id, referencia),
        )
        return [dict(fila) for fila in filas]
