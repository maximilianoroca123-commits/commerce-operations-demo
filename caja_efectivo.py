"""Cash shifts, expected balances, in-person payments and cash refunds."""

from auditoria_comercial import registrar as auditar

import json
import sqlite3
from contextlib import closing

from errores import ProductoNoEncontradoError
from pedidos_venta import ConflictoEntregaError, sincronizar
from inventario_reservas import reservado
from movimientos_inventario import registrar as registrar_stock

MAXIMO = 2**63 - 1


def crear_tablas(db):
    db.execute("""CREATE TABLE IF NOT EXISTS turnos_caja (
        referencia TEXT PRIMARY KEY,
        fondo_inicial INTEGER NOT NULL CHECK(fondo_inicial >= 0),
        abierto_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        cerrado_en TEXT,
        contado INTEGER,
        esperado_cierre INTEGER,
        diferencia INTEGER)""")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS una_caja_abierta
        ON turnos_caja((1)) WHERE cerrado_en IS NULL""")
    db.execute("""CREATE TABLE IF NOT EXISTS movimientos_caja (
        id INTEGER PRIMARY KEY,
        caja TEXT NOT NULL REFERENCES turnos_caja(referencia),
        referencia TEXT NOT NULL,
        tipo TEXT NOT NULL CHECK(tipo IN ('venta','ingreso','retiro','reintegro')),
        importe INTEGER NOT NULL CHECK(importe != 0),
        motivo TEXT NOT NULL,
        registrado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(caja,referencia))""")
    db.execute("""CREATE TABLE IF NOT EXISTS ventas_efectivo (
        referencia TEXT PRIMARY KEY,
        caja TEXT NOT NULL REFERENCES turnos_caja(referencia),
        pedido_id INTEGER NOT NULL UNIQUE REFERENCES pedidos_venta(id),
        solicitud TEXT NOT NULL,
        recibido INTEGER NOT NULL CHECK(recibido > 0),
        vuelto INTEGER NOT NULL CHECK(vuelto >= 0))""")


def obtener(db, referencia):
    fila = db.execute(
        "SELECT * FROM turnos_caja WHERE referencia=?", (referencia,)
    ).fetchone()
    if fila is None:
        raise ProductoNoEncontradoError("Turno de caja no encontrado")
    caja = dict(fila)
    caja["movimientos"] = [
        dict(x)
        for x in db.execute(
            "SELECT * FROM movimientos_caja WHERE caja=? ORDER BY id", (referencia,)
        )
    ]
    caja["saldo_esperado"] = caja["fondo_inicial"] + sum(
        x["importe"] for x in caja["movimientos"]
    )
    caja["estado"] = "cerrada" if caja["cerrado_en"] else "abierta"
    return caja


def exigir_abierta(db, referencia):
    caja = obtener(db, referencia)
    if caja["cerrado_en"]:
        raise ConflictoEntregaError("La caja está cerrada")
    return caja


def mover(db, caja, referencia, tipo, importe, motivo):
    saldo = exigir_abierta(db, caja)["saldo_esperado"]
    if not 0 <= saldo + importe <= MAXIMO:
        raise ConflictoEntregaError(
            "El movimiento dejaría el efectivo de caja fuera de rango"
        )
    db.execute(
        "INSERT INTO movimientos_caja (caja,referencia,tipo,importe,motivo) VALUES (?,?,?,?,?)",
        (caja, referencia, tipo, importe, motivo),
    )


def abrir(conectar_db, referencia, fondo):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        anterior = db.execute(
            "SELECT fondo_inicial FROM turnos_caja WHERE referencia=?", (referencia,)
        ).fetchone()
        if anterior:
            if anterior[0] != fondo:
                raise ConflictoEntregaError(
                    "La referencia de apertura ya tiene otro fondo inicial"
                )
            return obtener(db, referencia)
        if db.execute("SELECT 1 FROM turnos_caja WHERE cerrado_en IS NULL").fetchone():
            raise ConflictoEntregaError(
                "Ya existe una caja abierta. Cerrala antes de abrir otra"
            )
        db.execute(
            "INSERT INTO turnos_caja (referencia,fondo_inicial) VALUES (?,?)",
            (referencia, fondo),
        )
        auditar(db, "caja", referencia, "caja_abierta", {"fondo_inicial_pesos": fondo})
        return obtener(db, referencia)


def consultar(conectar_db, referencia):
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        return obtener(db, referencia)


def listar(conectar_db, pagina, limite):
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        total = db.execute("SELECT COUNT(*) FROM turnos_caja").fetchone()[0]
        filas = db.execute(
            "SELECT * FROM turnos_caja ORDER BY abierto_en DESC,referencia DESC LIMIT ? OFFSET ?",
            (limite, (pagina - 1) * limite),
        )
        return {
            "cajas": [dict(x) for x in filas],
            "total": total,
            "pagina": pagina,
            "limite": limite,
        }


# Compare counted cash with the current expected balance before closing the shift.
def cerrar(conectar_db, referencia, contado, saldo_consultado=None):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        caja = obtener(db, referencia)
        if caja["cerrado_en"]:
            if caja["contado"] != contado:
                raise ConflictoEntregaError(
                    "La caja ya se cerró con otro importe contado"
                )
            return caja
        esperado = caja["saldo_esperado"]
        if saldo_consultado is not None and esperado != saldo_consultado:
            raise ConflictoEntregaError(
                "El saldo cambió desde la consulta. Revisá los movimientos y volvé a contar antes de cerrar."
            )
        db.execute(
            """UPDATE turnos_caja SET contado=?,esperado_cierre=?,diferencia=?,
            cerrado_en=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE referencia=?""",
            (contado, esperado, contado - esperado, referencia),
        )
        auditar(
            db,
            "caja",
            referencia,
            "caja_cerrada",
            {
                "contado_pesos": contado,
                "esperado_pesos": esperado,
                "diferencia_pesos": contado - esperado,
            },
        )
        return obtener(db, referencia)


def movimiento_manual(conectar_db, caja, referencia, tipo, importe, motivo):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        obtener(db, caja)
        signo = importe if tipo == "ingreso" else -importe
        anterior = db.execute(
            "SELECT tipo,importe,motivo FROM movimientos_caja WHERE caja=? AND referencia=?",
            (caja, referencia),
        ).fetchone()
        if anterior:
            if tuple(anterior) != (tipo, signo, motivo):
                raise ConflictoEntregaError("La referencia ya se usó con otros datos")
            return obtener(db, caja)
        mover(db, caja, referencia, tipo, signo, motivo)
        auditar(
            db,
            "caja",
            caja,
            "efectivo_" + tipo,
            {"referencia": referencia, "importe_pesos": signo},
        )
        return obtener(db, caja)


# Validate the cash shift and cart before recording cash, sale and stock together.
def cobrar(conectar_db, referencia, datos, actor=None):
    solicitud = json.dumps(datos, sort_keys=True, ensure_ascii=False)
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        anterior = db.execute(
            "SELECT * FROM ventas_efectivo WHERE referencia=?", (referencia,)
        ).fetchone()
        if anterior:
            if anterior["solicitud"] != solicitud:
                raise ConflictoEntregaError(
                    "La referencia de venta ya se usó con otros datos"
                )
            return resultado(db, referencia)
        exigir_abierta(db, datos["caja"])
        productos = datos["productos"]
        if len({x["producto_id"] for x in productos}) != len(productos):
            raise ConflictoEntregaError("No repitas un producto dentro del carrito")
        lineas, total = [], 0
        for item in productos:
            p = db.execute(
                "SELECT nombre,precio,stock FROM productos WHERE id=?",
                (item["producto_id"],),
            ).fetchone()
            if p is None:
                raise ProductoNoEncontradoError("Producto no encontrado")
            if item["cantidad"] > p["stock"] - reservado(db, item["producto_id"]):
                raise ConflictoEntregaError("Stock insuficiente o reservado")
            total += item["cantidad"] * p["precio"]
            lineas.append(
                (item["producto_id"], p["nombre"], item["cantidad"], p["precio"])
            )
        if datos.get("total_esperado") is not None and datos["total_esperado"] != total:
            raise ConflictoEntregaError(
                "El precio cambió desde la consulta. Revisá el total antes de volver a confirmar el cobro."
            )
        if total > MAXIMO or datos["recibido"] < total:
            raise ConflictoEntregaError(
                "El efectivo recibido no cubre el total o el total está fuera de rango"
            )
        ref_interna = "efectivo:" + referencia
        for id, nombre, cantidad, precio in lineas:
            db.execute("UPDATE productos SET stock=stock-? WHERE id=?", (cantidad, id))
            registrar_stock(
                db,
                id,
                "venta_efectivo",
                referencia,
                -cantidad,
                "Venta cobrada en efectivo",
            )
        pedido = sincronizar(
            db, "directa", ref_interna, "presencial", "local", "aprobado", total, lineas
        )
        from usuarios import vincular_actor

        vincular_actor(db, pedido, actor)
        mover(
            db,
            datos["caja"],
            "venta:" + referencia,
            "venta",
            total,
            "Venta " + str(pedido),
        )
        db.execute(
            "INSERT INTO ventas_efectivo VALUES (?,?,?,?,?,?)",
            (
                referencia,
                datos["caja"],
                pedido,
                solicitud,
                datos["recibido"],
                datos["recibido"] - total,
            ),
        )
        auditar(
            db,
            "venta",
            pedido,
            "venta_efectivo_cobrada",
            {
                "caja": datos["caja"],
                "recibido_pesos": datos["recibido"],
                "vuelto_pesos": datos["recibido"] - total,
                "total_pesos": total,
            },
        )
        auditar(
            db,
            "caja",
            datos["caja"],
            "venta_cobrada",
            {"venta_id": pedido, "referencia": referencia, "importe_pesos": total},
        )
        return resultado(db, referencia)


def resultado(db, referencia):
    fila = db.execute(
        "SELECT * FROM ventas_efectivo WHERE referencia=?", (referencia,)
    ).fetchone()
    return {
        "referencia": referencia,
        "pedido_venta_id": fila["pedido_id"],
        "caja": fila["caja"],
        "recibido": fila["recibido"],
        "vuelto": fila["vuelto"],
        "total": fila["recibido"] - fila["vuelto"],
    }


def registrar_reintegro(db, pedido_id, referencia, importe, caja_esperada=None):

    if (
        db.execute(
            "SELECT 1 FROM ventas_efectivo WHERE pedido_id=?", (pedido_id,)
        ).fetchone()
        is None
    ):
        return
    abierta = db.execute(
        "SELECT referencia FROM turnos_caja WHERE cerrado_en IS NULL"
    ).fetchone()
    if abierta is None:
        raise ConflictoEntregaError(
            "Abrí una caja para registrar la salida del reintegro en efectivo"
        )
    if caja_esperada is not None and abierta[0] != caja_esperada:
        raise ConflictoEntregaError(
            "La caja cambió desde la consulta. Revisá el turno antes de confirmar el reintegro."
        )
    mover(
        db,
        abierta[0],
        f"reintegro:{pedido_id}:{referencia}",
        "reintegro",
        -importe,
        f"Reintegro de venta {pedido_id}, devolución {referencia}",
    )

    auditar(
        db,
        "caja",
        abierta[0],
        "reintegro_efectivo",
        {"venta_id": pedido_id, "referencia": referencia, "importe_pesos": -importe},
    )
