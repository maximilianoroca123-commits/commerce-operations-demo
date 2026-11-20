"""Supplier-owned purchase order queries and notice history."""

from reposicion import pedido_con_estado
from fastapi import HTTPException


def propio(db, pedido_id, proveedor):
    fila = db.execute(
        "SELECT * FROM pedidos_reposicion WHERE id=? AND proveedor=?",
        (pedido_id, proveedor),
    ).fetchone()
    if fila is None:
        raise HTTPException(404, "Pedido no encontrado")
    return pedido_con_estado(fila)


def acciones_aviso(pedido):
    return (
        ["confirmado", "despachado", "sin_disponibilidad"]
        if pedido["estado"] in ("pendiente", "parcial")
        else []
    )


def listar(db, proveedor, filtro, pagina, limite):
    condicion = "proveedor=?"
    if filtro == "abiertos":
        condicion += " AND recibido_en IS NULL AND cancelado_en IS NULL AND cerrado_incompleto_en IS NULL"
    total = db.execute(
        "SELECT COUNT(*) FROM pedidos_reposicion WHERE " + condicion, (proveedor,)
    ).fetchone()[0]
    filas = db.execute(
        "SELECT * FROM pedidos_reposicion WHERE "
        + condicion
        + " ORDER BY id DESC LIMIT ? OFFSET ?",
        (proveedor, limite, (pagina - 1) * limite),
    )
    return {
        "pedidos": [pedido_con_estado(x) for x in filas],
        "total": total,
        "pagina": pagina,
        "limite": limite,
    }


def avisos(db, pedido_id, proveedor, pagina, limite):
    propio(db, pedido_id, proveedor)
    total = db.execute(
        "SELECT COUNT(*) FROM avisos_proveedor WHERE pedido_id=?", (pedido_id,)
    ).fetchone()[0]
    filas = db.execute(
        "SELECT referencia,estado,nota,registrado_en FROM avisos_proveedor WHERE pedido_id=? ORDER BY registrado_en DESC,referencia DESC LIMIT ? OFFSET ?",
        (pedido_id, limite, (pagina - 1) * limite),
    )
    return {
        "avisos": [dict(x) for x in filas],
        "total": total,
        "pagina": pagina,
        "limite": limite,
    }
