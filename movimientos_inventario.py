"""Inventory movement history recorded with stock mutations."""

import sqlite3
from contextlib import closing


def crear_tablas(db):

    db.execute("""CREATE TABLE IF NOT EXISTS movimientos_inventario (
        id INTEGER PRIMARY KEY,
        producto_id INTEGER NOT NULL,
        nombre TEXT NOT NULL,
        tipo TEXT NOT NULL,
        referencia TEXT NOT NULL,
        motivo TEXT NOT NULL,
        cantidad INTEGER NOT NULL,
        variacion INTEGER NOT NULL,
        stock_anterior INTEGER NOT NULL CHECK(stock_anterior >= 0),
        stock_resultante INTEGER NOT NULL CHECK(stock_resultante >= 0),
        registrado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        CHECK(stock_resultante = stock_anterior + variacion),
        UNIQUE(producto_id,tipo,referencia))""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS movimientos_no_editar
        BEFORE UPDATE ON movimientos_inventario BEGIN
        SELECT RAISE(ABORT,'El historial de inventario no se edita'); END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS movimientos_no_borrar
        BEFORE DELETE ON movimientos_inventario BEGIN
        SELECT RAISE(ABORT,'El historial de inventario no se borra'); END""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS movimientos_producto ON movimientos_inventario(producto_id,id)"
    )


def registrar(db, producto_id, tipo, referencia, variacion, motivo, cantidad=None):
    fila = db.execute(
        "SELECT nombre,stock FROM productos WHERE id=?", (producto_id,)
    ).fetchone()
    nombre, stock = fila
    previo = db.execute(
        "SELECT stock_resultante FROM movimientos_inventario WHERE producto_id=? ORDER BY id DESC LIMIT 1",
        (producto_id,),
    ).fetchone()
    if previo is not None and previo[0] != stock - variacion:
        raise sqlite3.IntegrityError(
            "El stock no coincide con su historial de movimientos"
        )

    db.execute(
        """INSERT INTO movimientos_inventario
        (producto_id,nombre,tipo,referencia,motivo,cantidad,variacion,stock_anterior,stock_resultante)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            producto_id,
            nombre,
            tipo,
            str(referencia),
            motivo,
            abs(variacion) if cantidad is None else cantidad,
            variacion,
            stock - variacion,
            stock,
        ),
    )


def iniciar_saldos(db):
    for id, stock in db.execute(
        """SELECT id,stock FROM productos p WHERE NOT EXISTS
        (SELECT 1 FROM movimientos_inventario m WHERE m.producto_id=p.id)"""
    ).fetchall():
        registrar(
            db,
            id,
            "saldo_inicial",
            "actualizacion-inventario",
            stock,
            "Stock existente al comenzar el historial. No reconstruye operaciones anteriores",
        )


def siguiente_id(db):
    return db.execute(
        """SELECT MAX(id)+1 FROM (
        SELECT COALESCE(MAX(id),0) AS id FROM productos
        UNION ALL SELECT COALESCE(MAX(producto_id),0) FROM movimientos_inventario)"""
    ).fetchone()[0]


def listar(conectar_db, producto_id, tipo, pagina, limite):
    filtros, datos = [], []
    for campo, valor in [("producto_id", producto_id), ("tipo", tipo)]:
        if valor is not None:
            filtros.append(campo + "=?")
            datos.append(valor)
    condicion = " WHERE " + " AND ".join(filtros) if filtros else ""
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        total = db.execute(
            "SELECT COUNT(*) FROM movimientos_inventario" + condicion, datos
        ).fetchone()[0]
        filas = db.execute(
            "SELECT * FROM movimientos_inventario"
            + condicion
            + " ORDER BY id DESC LIMIT ? OFFSET ?",
            [*datos, limite, (pagina - 1) * limite],
        )
        return {
            "movimientos": [dict(x) for x in filas],
            "total": total,
            "pagina": pagina,
            "limite": limite,
        }
