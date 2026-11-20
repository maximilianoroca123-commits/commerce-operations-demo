"""Active goods reservations used to calculate available inventory."""


def reservado(db, producto_id, excluir=None):
    return db.execute(
        """SELECT COALESCE(SUM(i.cantidad), 0) FROM items_cobro i
           JOIN cobros_demo c USING (referencia)
           WHERE i.producto_id = ? AND c.reserva_activa = 1
             AND (? IS NULL OR c.referencia != ?)""",
        (producto_id, excluir, excluir),
    ).fetchone()[0]
