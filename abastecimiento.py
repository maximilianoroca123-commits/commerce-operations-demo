"""Read models and permitted actions for supplier purchase orders."""

from reposicion import buscar_pedido, pedido_con_estado


def acciones(pedido, rol):
    disponibles = ["remitos", "avisos", "historial"]
    if pedido["estado"] in ("pendiente", "parcial"):
        disponibles.append("recibir")
    if rol == "administrador":
        if pedido["estado"] == "pendiente":
            disponibles.append("cancelar")
        if pedido["estado"] == "parcial":
            disponibles.extend(["cerrar", "corregir"])
    return disponibles


def listar(db, filtro, pagina, limite):
    donde = (
        " WHERE recibido_en IS NULL AND cancelado_en IS NULL AND cerrado_incompleto_en IS NULL"
        if filtro == "abiertos"
        else ""
    )
    total = db.execute("SELECT COUNT(*) FROM pedidos_reposicion" + donde).fetchone()[0]
    filas = db.execute(
        "SELECT * FROM pedidos_reposicion"
        + donde
        + " ORDER BY id DESC LIMIT ? OFFSET ?",
        (limite, (pagina - 1) * limite),
    )
    return {
        "pedidos": [pedido_con_estado(x) for x in filas],
        "total": total,
        "pagina": pagina,
        "limite": limite,
    }


def contexto(db, id, rol):
    pedido = pedido_con_estado(buscar_pedido(db, id))
    producto = db.execute(
        "SELECT nombre FROM productos WHERE id=?", (pedido["producto_id"],)
    ).fetchone()
    from reposicion_simulada import compra_db

    sim = compra_db(db, id)
    disponibles = acciones(pedido, rol)
    if sim:
        disponibles = [x for x in disponibles if x not in ("corregir", "cerrar")]
        if sim["estado"] != "despachado":
            disponibles = [x for x in disponibles if x != "recibir"]
        if sim["pagado_en"]:
            disponibles = [x for x in disponibles if x != "cancelar"]
    return {
        "pedido": pedido,
        "producto_nombre": producto["nombre"] if producto else "Producto anterior",
        "acciones": disponibles,
        "simulacion": sim,
    }


def remitos(db, id, pagina, limite):
    buscar_pedido(db, id)
    total = db.execute(
        "SELECT COUNT(*) FROM recepciones_pedido WHERE pedido_id=?", (id,)
    ).fetchone()[0]
    filas = db.execute(
        "SELECT * FROM recepciones_pedido WHERE pedido_id=? ORDER BY registrado_en DESC,referencia LIMIT ? OFFSET ?",
        (id, limite, (pagina - 1) * limite),
    )
    return {
        "remitos": [dict(x) for x in filas],
        "total": total,
        "pagina": pagina,
        "limite": limite,
    }
