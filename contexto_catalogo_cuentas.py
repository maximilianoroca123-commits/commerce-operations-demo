"""Operational product and account read models for staff clients."""

from fastapi import HTTPException
from inventario_reservas import reservado
from reposicion import PEDIDO_ABIERTO


def producto(db, id, rol):
    p = db.execute("SELECT * FROM productos WHERE id=?", (id,)).fetchone()
    if p is None:
        raise HTTPException(404, "Producto no encontrado")
    reservadas = reservado(db, id)
    por_recibir = db.execute(
        "SELECT COALESCE(SUM(cantidad-cantidad_recibida),0) FROM pedidos_reposicion WHERE producto_id=? AND "
        + PEDIDO_ABIERTO,
        (id,),
    ).fetchone()[0]
    acciones = ["detalle", "movimientos"]
    regla = None
    if rol == "administrador":
        acciones += [
            "editar",
            "eliminar",
            "regla",
            "configurar",
            "reponer",
            "historial",
        ]
        fila = db.execute(
            "SELECT * FROM reglas_reposicion WHERE producto_id=?", (id,)
        ).fetchone()
        regla = dict(fila) if fila else None
    return {
        "producto": dict(p),
        "reservadas": reservadas,
        "disponible": p["stock"] - reservadas,
        "por_recibir": por_recibir,
        "regla": regla,
        "acciones": acciones,
    }


def cuenta(db, nombre, actor):
    fila = db.execute(
        "SELECT usuario,rol,cliente_id,proveedor,activo,debe_cambiar_clave,creado_en FROM usuarios WHERE usuario=?",
        (nombre,),
    ).fetchone()
    if fila is None:
        raise HTTPException(404, "Cuenta individual no encontrada")
    u = dict(fila)
    acciones = ["detalle", "historial"]
    if nombre != str(actor):
        otras = db.execute(
            "SELECT COUNT(*) FROM usuarios WHERE rol='administrador' AND activo=1 AND usuario!=?",
            (nombre,),
        ).fetchone()[0]
        if u["activo"]:
            if u["rol"] != "administrador" or otras > 0:
                acciones.append("desactivar")
            acciones.append("restablecer")
        else:
            acciones.append("activar")
    return {"cuenta": u, "acciones": acciones, "es_propia": nombre == str(actor)}
