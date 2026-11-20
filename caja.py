"""Persistent simulated payment processing, reservations and reconciliation."""

from movimientos_inventario import registrar as registrar_movimiento

from auditoria_comercial import registrar as auditar

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from errores import ProductoNoEncontradoError
from inventario_reservas import reservado
from pedidos_venta import sincronizar_cobro
from ventas import ConflictoVentaError


def ahora():
    return datetime.now(timezone.utc)


def detalle_cobro(db, referencia):
    fila = db.execute(
        "SELECT * FROM cobros_demo WHERE referencia = ?", (referencia,)
    ).fetchone()
    if fila is None:
        raise ProductoNoEncontradoError("Cobro no encontrado")
    cobro = dict(fila)
    cobro["estado"] = cobro.pop("estado_operacion")
    proveedor = db.execute(
        "SELECT * FROM proveedor_pagos_demo WHERE referencia = ?", (referencia,)
    ).fetchone()
    cobro["estado_pago"] = proveedor["estado"]
    cobro["reembolso"] = proveedor["reembolso"]
    sincronizar_cobro(db, referencia)
    cobro["pedido_venta_id"] = db.execute(
        "SELECT id FROM pedidos_venta WHERE origen='qr' AND referencia=?", (referencia,)
    ).fetchone()[0]
    cobro["productos"] = [
        dict(p)
        for p in db.execute(
            "SELECT producto_id, nombre, cantidad, precio_unitario FROM items_cobro WHERE referencia = ? ORDER BY producto_id",
            (referencia,),
        )
    ]
    return cobro


# Reconcile provider status and local stock once; payment and delivery remain separate.
def conciliar(db, referencia):
    cobro = detalle_cobro(db, referencia)
    proveedor = db.execute(
        "SELECT * FROM proveedor_pagos_demo WHERE referencia = ?", (referencia,)
    ).fetchone()
    if not proveedor["disponible"]:
        if cobro["reserva_activa"]:
            db.execute(
                "UPDATE cobros_demo SET estado_operacion = 'verificando' WHERE referencia = ?",
                (referencia,),
            )
        resultado = detalle_cobro(db, referencia)
        if resultado["estado"] != cobro["estado"]:
            auditar(
                db,
                "venta",
                resultado["pedido_venta_id"],
                "cobro_conciliado",
                {"anterior": cobro["estado"], "nuevo": resultado["estado"]},
                responsable="sistema_pagos",
            )
        return resultado

    pago = proveedor["estado"]
    if (
        pago == "pendiente"
        and cobro["vence_en"]
        and ahora().isoformat() >= cobro["vence_en"]
    ):

        pago = "vencido"
        db.execute(
            "UPDATE proveedor_pagos_demo SET estado = ?, version = version + 1 WHERE referencia = ?",
            (pago, referencia),
        )
    estado = cobro["estado"]
    if pago == "aprobado" and estado not in ("aprobado", "reembolsado"):
        hay_stock = all(
            db.execute(
                "SELECT stock FROM productos WHERE id = ?", (p["producto_id"],)
            ).fetchone()[0]
            - reservado(db, p["producto_id"], referencia)
            >= p["cantidad"]
            for p in cobro["productos"]
        )
        if hay_stock:
            for p in cobro["productos"]:
                db.execute(
                    "UPDATE productos SET stock = stock - ? WHERE id = ?",
                    (p["cantidad"], p["producto_id"]),
                )
                registrar_movimiento(
                    db,
                    p["producto_id"],
                    "venta_qr",
                    referencia,
                    -p["cantidad"],
                    "Cobro aprobado",
                )
            estado = "aprobado"
        else:
            estado = "requiere_devolucion"
        db.execute(
            """UPDATE cobros_demo SET estado = 'aprobado', estado_operacion = ?,
               reserva_activa = 0, resuelto_en = ? WHERE referencia = ?""",
            (estado, ahora().isoformat(), referencia),
        )
    elif pago in ("rechazado", "cancelado", "vencido"):
        db.execute(
            """UPDATE cobros_demo SET estado = 'rechazado', estado_operacion = ?,
               reserva_activa = 0, resuelto_en = ? WHERE referencia = ?""",
            (pago, ahora().isoformat(), referencia),
        )
    elif pago in ("pendiente", "procesando") and estado in (
        "pendiente",
        "procesando",
        "verificando",
    ):
        db.execute(
            "UPDATE cobros_demo SET estado_operacion = ? WHERE referencia = ?",
            (pago, referencia),
        )
    resultado = detalle_cobro(db, referencia)
    if resultado["estado"] != cobro["estado"]:
        auditar(
            db,
            "venta",
            resultado["pedido_venta_id"],
            "cobro_conciliado",
            {"anterior": cobro["estado"], "nuevo": resultado["estado"]},
            responsable="sistema_pagos",
        )
    return resultado


def recuperar_cobros(conectar_db):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        referencias = [
            fila[0]
            for fila in db.execute(
                """SELECT c.referencia FROM cobros_demo c
               JOIN proveedor_pagos_demo p USING (referencia)
               WHERE c.estado_operacion IN ('pendiente','procesando','verificando')
                  OR (p.estado = 'aprobado' AND c.estado_operacion IN ('vencido','cancelado','rechazado'))"""
            )
        ]
        return [conciliar(db, ref) for ref in referencias]


def crear_cobro(
    conectar_db,
    referencia,
    productos,
    canal="presencial",
    modalidad="local",
    actor=None,
    direccion=None,
):
    cantidades = {}
    for p in productos:
        cantidades[p["producto_id"]] = (
            cantidades.get(p["producto_id"], 0) + p["cantidad"]
        )
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        from usuarios import comprobar_titular, vincular_actor

        comprobar_titular(db, "qr", referencia, actor)

        for fila in db.execute(
            "SELECT referencia FROM cobros_demo WHERE reserva_activa = 1"
        ).fetchall():
            conciliar(db, fila[0])
        if db.execute(
            "SELECT 1 FROM cobros_demo WHERE referencia = ?", (referencia,)
        ).fetchone():
            existente = detalle_cobro(db, referencia)
            if actor is not None and not actor.legado:
                anterior = db.execute(
                    "SELECT direccion_entrega FROM titulares_pedido WHERE pedido_id=?",
                    (existente["pedido_venta_id"],),
                ).fetchone()
                if anterior and anterior[0] != direccion:
                    raise ConflictoVentaError(
                        "No se puede cambiar la dirección al reintentar el mismo pedido"
                    )
            if (
                {p["producto_id"]: p["cantidad"] for p in existente["productos"]}
                != cantidades
                or existente["canal"] != canal
                or existente["modalidad"] != modalidad
            ):
                raise ConflictoVentaError("La referencia ya corresponde a otro carrito")
            return existente
        lineas = []
        total = 0
        for identificador, cantidad in sorted(cantidades.items()):
            p = db.execute(
                "SELECT nombre, precio, stock FROM productos WHERE id = ?",
                (identificador,),
            ).fetchone()
            if p is None:
                raise ProductoNoEncontradoError(
                    f"Producto {identificador} no encontrado"
                )
            if cantidad > p["stock"] - reservado(db, identificador):
                raise ConflictoVentaError(
                    f"Stock disponible insuficiente del producto {identificador}"
                )
            total += cantidad * p["precio"]
            if total > 2**63 - 1:
                raise ConflictoVentaError("El total supera el máximo admitido")
            lineas.append(
                (referencia, identificador, p["nombre"], cantidad, p["precio"])
            )
        vence = (ahora() + timedelta(minutes=5)).isoformat()
        db.execute(
            """INSERT INTO cobros_demo
               (referencia,total,estado,reserva_activa,vence_en,canal,modalidad) VALUES (?,?,'pendiente',1,?,?,?)""",
            (referencia, total, vence, canal, modalidad),
        )
        db.executemany("INSERT INTO items_cobro VALUES (?,?,?,?,?)", lineas)
        db.execute(
            "INSERT INTO proveedor_pagos_demo (referencia,estado) VALUES (?,'pendiente')",
            (referencia,),
        )
        vincular_actor(db, sincronizar_cobro(db, referencia), actor, direccion)
        return detalle_cobro(db, referencia)


def consultar_cobro(conectar_db, referencia):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        return conciliar(db, referencia)


def emitir_evento(conectar_db, referencia, evento, estado, permitir_tardia=True):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        detalle_cobro(db, referencia)
        anterior = db.execute(
            "SELECT estado FROM eventos_pago_demo WHERE referencia = ? AND evento = ?",
            (referencia, evento),
        ).fetchone()
        if anterior:
            if anterior["estado"] != estado:
                raise ConflictoVentaError("El evento ya se usó con otros datos")
            return detalle_cobro(db, referencia)
        actual = db.execute(
            "SELECT * FROM proveedor_pagos_demo WHERE referencia = ?", (referencia,)
        ).fetchone()
        if not actual["disponible"]:
            raise ConflictoVentaError("El proveedor simulado está desconectado")

        finales = ("aprobado", "rechazado", "cancelado", "vencido")
        if actual["estado"] in finales:
            if estado in ("pendiente", "procesando"):
                estado_guardado = actual["estado"]
            elif estado == actual["estado"] or (
                estado == "aprobado" and permitir_tardia
            ):
                estado_guardado = estado
            else:
                raise ConflictoVentaError("El cobro ya tiene otro resultado definitivo")
        else:
            if estado == "cancelado" and actual["estado"] == "procesando":
                raise ConflictoVentaError("El pago sigue procesándose")
            if estado == "pendiente" and actual["estado"] == "procesando":
                estado_guardado = "procesando"
            else:
                if (
                    actual["estado"] == "pendiente"
                    and estado in ("aprobado", "procesando")
                    and ahora().isoformat() >= detalle_cobro(db, referencia)["vence_en"]
                ):
                    raise ConflictoVentaError(
                        "El cobro venció antes de iniciar el pago"
                    )
                estado_guardado = estado
        db.execute(
            "INSERT INTO eventos_pago_demo VALUES (?,?,?)", (referencia, evento, estado)
        )
        db.execute(
            "UPDATE proveedor_pagos_demo SET estado = ?, version = version + 1 WHERE referencia = ?",
            (estado_guardado, referencia),
        )
        auditar(
            db,
            "venta",
            detalle_cobro(db, referencia)["pedido_venta_id"],
            "aviso_pago_recibido",
            {
                "evento": evento,
                "estado_informado": estado,
                "estado_aplicado": estado_guardado,
            },
        )

        return detalle_cobro(db, referencia)


def confirmar_pago(conectar_db, referencia, estado):
    actual = consultar_cobro(conectar_db, referencia)
    if actual["estado"] not in ("pendiente", "procesando", "verificando"):
        if actual["estado"] != estado:
            raise ConflictoVentaError("El cobro ya tiene otro resultado definitivo")
        return actual
    emitir_evento(
        conectar_db, referencia, "confirmacion-" + estado, estado, permitir_tardia=False
    )
    return consultar_cobro(conectar_db, referencia)


def conectar_proveedor(conectar_db, referencia, disponible):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        detalle_cobro(db, referencia)
        anterior = db.execute(
            "SELECT disponible FROM proveedor_pagos_demo WHERE referencia=?",
            (referencia,),
        ).fetchone()[0]
        if bool(anterior) != disponible:
            auditar(
                db,
                "venta",
                detalle_cobro(db, referencia)["pedido_venta_id"],
                "conexion_pago_cambiada",
                {"disponible": disponible},
            )
        db.execute(
            "UPDATE proveedor_pagos_demo SET disponible = ? WHERE referencia = ?",
            (int(disponible), referencia),
        )
    return consultar_cobro(conectar_db, referencia)


def reembolsar(conectar_db, referencia):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        cobro = conciliar(db, referencia)
        if cobro["estado"] == "reembolsado":
            return cobro
        if cobro["estado"] != "requiere_devolucion":
            raise ConflictoVentaError(
                "Esta devolución corresponde a un pago tardío sin mercadería entregada"
            )
        proveedor = db.execute(
            "SELECT disponible FROM proveedor_pagos_demo WHERE referencia = ?",
            (referencia,),
        ).fetchone()
        if not proveedor[0]:
            raise ConflictoVentaError("No se pudo confirmar la devolución")
        db.execute(
            "UPDATE proveedor_pagos_demo SET reembolso = 'confirmado' WHERE referencia = ?",
            (referencia,),
        )
        db.execute(
            "UPDATE cobros_demo SET estado_operacion = 'reembolsado' WHERE referencia = ?",
            (referencia,),
        )
        auditar(
            db,
            "venta",
            cobro["pedido_venta_id"],
            "pago_tardio_reembolsado",
            {"referencia": referencia},
        )
        return detalle_cobro(db, referencia)
