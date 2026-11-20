"""Customer request context and the next permitted processing action."""

import hashlib
from pedidos_venta import detalle


def contexto(db, solicitud, rol):
    pedido = detalle(db, solicitud["pedido_id"])
    referencia = (
        "gestion-"
        + hashlib.sha256(
            f'{solicitud["pedido_id"]}:{solicitud["referencia"]}'.encode()
        ).hexdigest()[:32]
    )
    operaciones = pedido["devoluciones"]["operaciones"]
    operacion = next((x for x in operaciones if x["referencia"] == referencia), None)
    pendientes = []
    for p in pedido["productos"]:
        devueltos = sum(
            l["cantidad"]
            for op in operaciones
            for l in op["productos"]
            if l["producto_id"] == p["producto_id"]
        )
        pendientes.append({**p, "pendiente_devolver": p["cantidad"] - devueltos})
    acciones = []
    if solicitud["estado"] == "pendiente_revision":
        if operacion:
            if operacion["estado_reintegro"] != "confirmado":
                acciones.append("reintegrar")
            else:
                acciones.append("resolver")
        else:
            acciones.append("rechazar")
            if pedido["estado_pago"] == "aprobado":
                if (
                    solicitud["tipo"] == "devolucion"
                    and pedido["estado_entrega"] == "entregado"
                    and any(p["pendiente_devolver"] > 0 for p in pendientes)
                ):
                    acciones.append("recibir")
                if (
                    solicitud["tipo"] == "cancelacion"
                    and rol == "administrador"
                    and pedido["estado_entrega"] in ("pendiente", "preparando", "listo")
                    and not operaciones
                ):
                    acciones.append("cancelar")
    resolucion = db.execute(
        "SELECT estado,motivo,usuario FROM resoluciones_cliente WHERE pedido_id=? AND referencia=?",
        (solicitud["pedido_id"], solicitud["referencia"]),
    ).fetchone()
    return {
        "solicitud": solicitud,
        "pedido": pedido,
        "productos": pendientes,
        "referencia_operacion": referencia,
        "operacion": operacion,
        "acciones": acciones,
        "resolucion": dict(resolucion) if resolucion else None,
    }
