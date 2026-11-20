"""Shared sales records and customer delivery state transitions."""

from auditoria_comercial import registrar as auditar

import sqlite3
import json
from contextlib import closing

from errores import ProductoNoEncontradoError


class ConflictoEntregaError(Exception):
    pass


def crear_tablas(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS pedidos_venta (
            id INTEGER PRIMARY KEY,
            origen TEXT NOT NULL CHECK (origen IN ('directa','qr')),
            referencia TEXT NOT NULL,
            canal TEXT NOT NULL CHECK (canal IN ('presencial','online')),
            modalidad TEXT NOT NULL CHECK (modalidad IN ('local','retiro','envio')),
            estado_pago TEXT NOT NULL,
            estado_entrega TEXT NOT NULL,
            total INTEGER NOT NULL CHECK (total > 0),
            creado_en TEXT NOT NULL,
            entregado_en TEXT,
            UNIQUE (origen, referencia)
        )
        """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS items_pedido_venta (
            pedido_id INTEGER NOT NULL REFERENCES pedidos_venta(id),
            producto_id INTEGER NOT NULL REFERENCES productos(id),
            nombre TEXT NOT NULL,
            cantidad INTEGER NOT NULL CHECK (cantidad > 0),
            precio_unitario INTEGER NOT NULL CHECK (precio_unitario > 0),
            PRIMARY KEY (pedido_id, producto_id)
        )
        """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS historial_entrega (
            id INTEGER PRIMARY KEY,
            pedido_id INTEGER NOT NULL REFERENCES pedidos_venta(id),
            estado TEXT NOT NULL,
            registrado_en TEXT NOT NULL
        )
        """)


def estado_inicial(pago, canal):
    if pago == "aprobado":
        return "entregado" if canal == "presencial" else "pendiente"
    if pago in ("rechazado", "cancelado", "vencido", "reembolsado"):
        return "cancelado"
    if pago == "requiere_devolucion":
        return "revision"
    return "pendiente_pago"


def registrar_estado(db, pedido_id, estado):
    db.execute(
        """UPDATE pedidos_venta SET estado_entrega = ?,
           entregado_en = CASE WHEN ? = 'entregado'
               THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE entregado_en END WHERE id = ?""",
        (estado, estado, pedido_id),
    )
    db.execute(
        """INSERT INTO historial_entrega (pedido_id,estado,registrado_en)
           VALUES (?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))""",
        (pedido_id, estado),
    )


def sincronizar(db, origen, referencia, canal, modalidad, pago, total, lineas):
    existente = db.execute(
        "SELECT id,estado_pago FROM pedidos_venta WHERE origen = ? AND referencia = ?",
        (origen, referencia),
    ).fetchone()
    if existente is None:
        estado = estado_inicial(pago, canal)
        cursor = db.execute(
            """INSERT INTO pedidos_venta
               (origen,referencia,canal,modalidad,estado_pago,estado_entrega,total,creado_en)
               VALUES (?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))""",
            (origen, referencia, canal, modalidad, pago, estado, total),
        )
        pedido_id = cursor.lastrowid
        db.executemany(
            "INSERT INTO items_pedido_venta VALUES (?,?,?,?,?)",
            [(pedido_id, *linea) for linea in lineas],
        )
        registrar_estado(db, pedido_id, estado)
        auditar(
            db,
            "venta",
            pedido_id,
            "pedido_creado",
            {
                "origen": origen,
                "referencia": referencia,
                "canal": canal,
                "modalidad": modalidad,
                "total_pesos": total,
                "pago": pago,
            },
        )
        return pedido_id

    pedido_id, pago_anterior = existente
    if pago_anterior != pago:
        db.execute(
            "UPDATE pedidos_venta SET estado_pago = ? WHERE id = ?", (pago, pedido_id)
        )
        auditar(
            db,
            "venta",
            pedido_id,
            "pago_actualizado",
            {"anterior": pago_anterior, "nuevo": pago},
            responsable="sistema_pagos",
        )
        estado = estado_inicial(pago, canal)
        actual = db.execute(
            "SELECT estado_entrega FROM pedidos_venta WHERE id = ?", (pedido_id,)
        ).fetchone()[0]
        if estado != actual:
            registrar_estado(db, pedido_id, estado)
    return pedido_id


def sincronizar_cobro(db, referencia):
    c = db.execute(
        "SELECT canal,modalidad,estado_operacion,total FROM cobros_demo WHERE referencia = ?",
        (referencia,),
    ).fetchone()
    lineas = [
        tuple(p)
        for p in db.execute(
            """SELECT producto_id,nombre,cantidad,precio_unitario FROM items_cobro
           WHERE referencia = ? ORDER BY producto_id""",
            (referencia,),
        )
    ]
    return sincronizar(db, "qr", referencia, *c, lineas)


def sincronizar_venta_directa(db, referencia):
    p = db.execute(
        """SELECT v.producto_id,p.nombre,v.cantidad,v.precio_unitario FROM ventas v
           JOIN productos p ON p.id=v.producto_id WHERE v.referencia=?""",
        (referencia,),
    ).fetchone()
    return sincronizar(
        db,
        "directa",
        referencia,
        "presencial",
        "local",
        "aprobado",
        p[2] * p[3],
        [tuple(p)],
    )


def siguiente_entrega(pedido):
    """Return the next delivery step shared by read and write paths."""
    if pedido["estado_pago"] != "aprobado" or any(
        x["tipo"] == "cancelacion" for x in pedido["devoluciones"]["operaciones"]
    ):
        return None
    return {
        "pendiente": "preparando",
        "preparando": "listo",
        "listo": "enviado" if pedido["modalidad"] == "envio" else "entregado",
        "enviado": "entregado",
    }.get(pedido["estado_entrega"])


def detalle(db, pedido_id):
    fila = db.execute(
        "SELECT * FROM pedidos_venta WHERE id = ?", (pedido_id,)
    ).fetchone()
    if fila is None:
        raise ProductoNoEncontradoError("Pedido de venta no encontrado")
    pedido = dict(fila)
    titular = db.execute(
        "SELECT cliente_id,propietario,registrado_por,contacto_compra,direccion_entrega FROM titulares_pedido WHERE pedido_id=?",
        (pedido_id,),
    ).fetchone()
    pedido["cliente_id"] = titular["cliente_id"] if titular else None
    pedido["registrado_por"] = titular["registrado_por"] if titular else None
    pedido["cliente_al_comprar"] = (
        json.loads(titular["contacto_compra"])
        if titular and titular["contacto_compra"]
        else None
    )
    pedido["direccion_entrega"] = titular["direccion_entrega"] if titular else None
    pedido["identificacion_cliente"] = (
        "registrado" if pedido["cliente_id"] else "sin_identificar"
    )
    efectivo = db.execute(
        "SELECT caja,recibido,vuelto FROM ventas_efectivo WHERE pedido_id=?",
        (pedido_id,),
    ).fetchone()
    pedido["medio_pago"] = (
        "efectivo"
        if efectivo
        else ("qr_demo" if pedido["origen"] == "qr" else "no_especificado")
    )
    pedido["efectivo"] = dict(efectivo) if efectivo else None
    pedido["productos"] = [
        dict(p)
        for p in db.execute(
            """SELECT producto_id,nombre,cantidad,precio_unitario FROM items_pedido_venta
           WHERE pedido_id = ? ORDER BY producto_id""",
            (pedido_id,),
        )
    ]
    from devoluciones import resumen

    pedido["devoluciones"] = resumen(db, pedido_id)
    pedido["historial_entrega"] = [
        dict(p)
        for p in db.execute(
            "SELECT estado,registrado_en FROM historial_entrega WHERE pedido_id = ? ORDER BY id",
            (pedido_id,),
        )
    ]
    pedido["siguiente_estado_entrega"] = siguiente_entrega(pedido)
    pedido["acciones_cliente"] = acciones_cliente(pedido)
    return pedido


def consultar(conectar_db, pedido_id):
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        return detalle(db, pedido_id)


def listar(
    conectar_db,
    canal,
    estado_entrega,
    pagina,
    limite,
    estado_pago=None,
    propietario=None,
    solo_pendientes=False,
):
    filtros, datos = [], []
    for campo, valor in (
        ("canal", canal),
        ("estado_entrega", estado_entrega),
        ("estado_pago", estado_pago),
    ):
        if valor is not None:
            filtros.append(campo + " = ?")
            datos.append(valor)
    if propietario is not None:
        filtros.append(
            "id IN (SELECT pedido_id FROM titulares_pedido WHERE propietario=?)"
        )
        datos.append(str(propietario))
    if solo_pendientes:
        filtros.append(
            "estado_pago='aprobado' AND estado_entrega IN ('pendiente','preparando','listo','enviado')"
        )
    condicion = " WHERE " + " AND ".join(filtros) if filtros else ""
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        total = db.execute(
            "SELECT COUNT(*) FROM pedidos_venta" + condicion, datos
        ).fetchone()[0]
        filas = db.execute(
            "SELECT * FROM pedidos_venta"
            + condicion
            + " ORDER BY id DESC LIMIT ? OFFSET ?",
            [*datos, limite, (pagina - 1) * limite],
        )
        return {
            "pedidos": [dict(fila) for fila in filas],
            "total": total,
            "pagina": pagina,
            "limite": limite,
        }


def cambiar_entrega(conectar_db, pedido_id, estado):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        pedido = detalle(db, pedido_id)
        if pedido["estado_pago"] != "aprobado":
            raise ConflictoEntregaError(
                "El pedido debe estar pagado antes de preparar o entregar"
            )
        if any(
            x["tipo"] == "cancelacion" for x in pedido["devoluciones"]["operaciones"]
        ):
            raise ConflictoEntregaError("El pedido fue cancelado comercialmente")
        actual = pedido["estado_entrega"]
        if estado == actual:
            return pedido
        siguiente = siguiente_entrega(pedido)
        if estado != siguiente:
            raise ConflictoEntregaError(
                f"Transición de entrega inválida desde {actual}"
            )
        registrar_estado(db, pedido_id, estado)
        auditar(
            db,
            "venta",
            pedido_id,
            "entrega_actualizada",
            {"anterior": actual, "nuevo": estado},
        )
        return detalle(db, pedido_id)


def pendiente_entrega(db, producto_id):
    return db.execute(
        """SELECT COALESCE(SUM(i.cantidad),0) FROM items_pedido_venta i
           JOIN pedidos_venta p ON p.id=i.pedido_id
           WHERE i.producto_id=? AND p.estado_pago='aprobado' AND p.estado_entrega NOT IN ('entregado','cancelado')""",
        (producto_id,),
    ).fetchone()[0]


def acciones_cliente(pedido):
    """Return suggested actions; mutation services validate their preconditions again."""
    acciones = ["detalle", "solicitudes"]
    if pedido["origen"] == "qr" and pedido["estado_pago"] == "pendiente":
        acciones.append("pagar")
    if pedido["estado_pago"] == "aprobado":
        acciones.append("comprobante")
        if pedido["estado_entrega"] == "entregado" and pedido["devoluciones"][
            "estado_comercial"
        ] not in ("devuelta", "cancelada"):
            acciones.append("devolucion")
        elif (
            pedido["estado_entrega"] in ("pendiente", "preparando", "listo")
            and not pedido["devoluciones"]["operaciones"]
        ):
            acciones.append("cancelacion")
    return acciones
