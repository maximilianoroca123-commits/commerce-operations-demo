"""Operational read models for sales and the current cash shift."""

from pedidos_venta import detalle


def caja_actual(db, rol):
    fila = db.execute("SELECT * FROM turnos_caja WHERE cerrado_en IS NULL").fetchone()
    if fila is None:
        return {"caja": None, "acciones": ["abrir"]}
    caja = dict(fila)
    caja["saldo_esperado"] = (
        caja["fondo_inicial"]
        + db.execute(
            "SELECT COALESCE(SUM(importe),0) FROM movimientos_caja WHERE caja=?",
            (caja["referencia"],),
        ).fetchone()[0]
    )
    caja["estado"] = "abierta"
    return {
        "caja": caja,
        "acciones": ["consultar", "cobrar", "cerrar"]
        + (["movimiento"] if rol == "administrador" else []),
    }


def venta(db, id, rol):
    p = detalle(db, id)
    acciones = ["detalle", "historial", "devoluciones", "solicitudes"]
    if p["estado_pago"] == "aprobado":
        acciones.append("comprobante")
        if p["siguiente_estado_entrega"]:
            acciones.append("entrega")
        if p["estado_entrega"] == "entregado" and p["devoluciones"][
            "estado_comercial"
        ] not in ("devuelta", "cancelada"):
            acciones.append("devolver")
        if (
            rol == "administrador"
            and p["estado_entrega"] in ("pendiente", "preparando", "listo")
            and not p["devoluciones"]["operaciones"]
        ):
            acciones.append("cancelar")
    if any(
        x["estado_reintegro"] != "confirmado" for x in p["devoluciones"]["operaciones"]
    ):
        acciones.append("reintegrar")
    if db.execute(
        "SELECT 1 FROM solicitudes_cliente WHERE pedido_id=? AND estado='pendiente_revision'",
        (id,),
    ).fetchone():
        acciones = [a for a in acciones if a not in ("devolver", "cancelar")]
        acciones.append("atender_solicitud")
    return {"pedido": p, "acciones": acciones}
