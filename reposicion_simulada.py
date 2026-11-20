"""General-rule replenishment demonstration with reserved funds and simulated dispatch."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
import sqlite3
from auditoria_comercial import registrar as auditar
from errores import ProductoNoEncontradoError
from reposicion import ConflictoReposicionError, PEDIDO_ABIERTO, prioridad_oferta

REGLA = {"minimo": 0, "cantidad": 3, "costo_max_centavos": 100000, "vigencia_horas": 24}
PASO_SEGUNDOS = 5


def ahora():
    return datetime.now(timezone.utc)


def crear_tablas(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS simulacion_reposicion (
        id INTEGER PRIMARY KEY CHECK(id=1),activa INTEGER NOT NULL DEFAULT 0 CHECK(activa IN(0,1)),
        producto_id INTEGER REFERENCES productos(id),resultado TEXT NOT NULL DEFAULT 'Sin activar')"""
    )
    db.execute("INSERT OR IGNORE INTO simulacion_reposicion(id) VALUES (1)")
    db.execute("""CREATE TABLE IF NOT EXISTS aportes_reposicion_simulada (
        referencia TEXT PRIMARY KEY,importe_centavos INTEGER NOT NULL CHECK(importe_centavos>0),
        registrado_en TEXT NOT NULL,actor TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS compras_reposicion_simulada (
        pedido_id INTEGER PRIMARY KEY REFERENCES pedidos_reposicion(id),
        importe_centavos INTEGER NOT NULL CHECK(importe_centavos>0),
        estado TEXT NOT NULL CHECK(estado IN('pendiente_pago','preparando','listo','despachado','recibido','cancelado')),
        pagado_en TEXT,actualizado_en TEXT NOT NULL)""")


def instalar(conectar):
    with closing(conectar()) as db, db:
        crear_tablas(db)


# Derive available funds from contributions minus payments and unpaid reservations.
def fondo_db(db):
    aportes = db.execute(
        "SELECT COALESCE(SUM(importe_centavos),0) FROM aportes_reposicion_simulada"
    ).fetchone()[0]
    pagado = db.execute(
        "SELECT COALESCE(SUM(importe_centavos),0) FROM compras_reposicion_simulada WHERE pagado_en IS NOT NULL"
    ).fetchone()[0]
    reservado = db.execute(
        "SELECT COALESCE(SUM(importe_centavos),0) FROM compras_reposicion_simulada WHERE estado='pendiente_pago'"
    ).fetchone()[0]
    return {
        "aportado_centavos": aportes,
        "pagado_centavos": pagado,
        "saldo_centavos": aportes - pagado,
        "reservado_centavos": reservado,
        "disponible_centavos": aportes - pagado - reservado,
    }


def compra_db(db, id):
    r = db.execute(
        "SELECT * FROM compras_reposicion_simulada WHERE pedido_id=?", (id,)
    ).fetchone()
    return dict(r) if r else None


def consultar(conectar, pagina=1):
    with closing(conectar()) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        config = dict(
            db.execute("SELECT * FROM simulacion_reposicion WHERE id=1").fetchone()
        )
        p = db.execute(
            "SELECT id,nombre,stock FROM productos WHERE id=?", (config["producto_id"],)
        ).fetchone()
        compras = [
            dict(x)
            for x in db.execute(
                """SELECT c.*,p.producto_id,p.proveedor,p.id_externo,p.cantidad,
            p.cantidad_recibida,p.costo_ofertado_centavos,x.nombre AS producto_nombre
            FROM compras_reposicion_simulada c JOIN pedidos_reposicion p ON p.id=c.pedido_id
            JOIN productos x ON x.id=p.producto_id ORDER BY c.pedido_id DESC LIMIT 10 OFFSET ?""",
                ((pagina - 1) * 10,),
            )
        ]
        total = db.execute(
            "SELECT COUNT(*) FROM compras_reposicion_simulada"
        ).fetchone()[0]
        return {
            "simulado": True,
            "regla": REGLA,
            "configuracion": config,
            "producto": dict(p) if p else None,
            "fondo": fondo_db(db),
            "compras": compras,
            "total": total,
            "pagina": pagina,
        }


def configurar(conectar, producto_id, activa):
    with closing(conectar()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        if not db.execute(
            "SELECT 1 FROM productos WHERE id=?", (producto_id,)
        ).fetchone():
            raise ProductoNoEncontradoError("Producto no encontrado")
        if (
            activa
            and db.execute(
                "SELECT 1 FROM reglas_reposicion WHERE producto_id=?", (producto_id,)
            ).fetchone()
        ):
            raise ConflictoReposicionError(
                "Elegí un producto de prueba sin regla individual para no superponer automatizaciones."
            )
        anterior = db.execute(
            "SELECT * FROM simulacion_reposicion WHERE id=1"
        ).fetchone()
        if (
            anterior["producto_id"] != producto_id
            and db.execute(
                "SELECT 1 FROM compras_reposicion_simulada WHERE estado NOT IN ('recibido','cancelado')"
            ).fetchone()
        ):
            raise ConflictoReposicionError(
                "Terminá o cancelá el pedido simulado abierto antes de elegir otro producto."
            )
        if (anterior["producto_id"], bool(anterior["activa"])) != (producto_id, activa):
            db.execute(
                "UPDATE simulacion_reposicion SET producto_id=?,activa=?,resultado=? WHERE id=1",
                (
                    producto_id,
                    int(activa),
                    (
                        "Esperando evaluación automática"
                        if activa
                        else "Generación de pedidos pausada"
                    ),
                ),
            )
            auditar(
                db,
                "producto",
                producto_id,
                "simulacion_reposicion_configurada",
                {"activa": activa, "regla_general": REGLA},
            )
    return {"guardada": True}


def aportar(conectar, referencia, importe, actor):
    with closing(conectar()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        previo = db.execute(
            "SELECT importe_centavos FROM aportes_reposicion_simulada WHERE referencia=?",
            (referencia,),
        ).fetchone()
        if previo:
            if previo[0] != importe:
                raise ConflictoReposicionError(
                    "La referencia del aporte ya se usó con otro importe."
                )
        else:
            if fondo_db(db)["aportado_centavos"] + importe > 100000000000:
                raise ConflictoReposicionError("El fondo de prueba alcanzó su límite.")
            db.execute(
                "INSERT INTO aportes_reposicion_simulada VALUES (?,?,?,?)",
                (referencia, importe, ahora().isoformat(), str(actor)),
            )
            auditar(
                db,
                "proveedor",
                "fondo_simulado",
                "aporte_fondo_simulado",
                {"referencia": referencia, "importe_centavos": importe},
            )
        return fondo_db(db)


def preparar_ejemplo(conectar):
    """Create isolated sample data once without resetting inventory or funds on replay."""
    from movimientos_inventario import siguiente_id, registrar

    with closing(conectar()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        previo = db.execute(
            """SELECT p.id,p.nombre,p.stock FROM productos p JOIN vinculos_oferta v ON v.producto_id=p.id
            WHERE v.proveedor='simulado' AND v.id_externo='muestra-auto'"""
        ).fetchone()
        if previo:
            return {"producto": dict(previo), "ya_preparado": True}
        if db.execute(
            "SELECT 1 FROM compras_reposicion_simulada WHERE estado NOT IN ('recibido','cancelado')"
        ).fetchone():
            raise ConflictoReposicionError(
                "Terminá o cancelá la prueba abierta antes de preparar otro ejemplo."
            )
        id = siguiente_id(db)
        nombre = f"Prueba reposición automática (ID {id})"
        fecha = ahora().isoformat()
        db.execute(
            "INSERT INTO productos(id,nombre,categoria,precio,stock,marca) VALUES (?,?,?,1000,0,?)",
            (id, nombre, "tecnologia", "Simulado"),
        )
        registrar(db, id, "alta", str(id), 0, "Alta del producto de muestra automática")
        auditar(
            db,
            "producto",
            id,
            "producto_creado",
            {"simulado": True, "precio_pesos": 1000, "stock": 0},
        )
        db.execute(
            """INSERT INTO ofertas_proveedor(proveedor,id_externo,nombre,marca,categoria,costo_centavos,stock_proveedor,vigente)
            VALUES ('simulado','muestra-auto',?,'Simulado','tecnologia',50050,3,1)""",
            (nombre,),
        )
        db.execute(
            "INSERT INTO vinculos_oferta(proveedor,id_externo,producto_id) VALUES ('simulado','muestra-auto',?)",
            (id,),
        )
        db.execute(
            "INSERT OR REPLACE INTO fuentes_catalogo(proveedor,modo) VALUES ('simulado','publicado')"
        )
        db.execute(
            "INSERT OR REPLACE INTO catalogos_control(proveedor,actualizado_en,ultimo_intento,error) VALUES ('simulado',?,?,NULL)",
            (fecha, fecha),
        )
        db.execute(
            "UPDATE simulacion_reposicion SET producto_id=?,activa=1,resultado='Ejemplo preparado. Agregá dinero ficticio para comenzar.' WHERE id=1",
            (id,),
        )
        auditar(
            db,
            "producto",
            id,
            "ejemplo_reposicion_preparado",
            {"proveedor": "simulado", "costo_centavos": 50050, "unidades": 3},
            responsable="reposicion_simulada",
        )
        return {
            "producto": {"id": id, "nombre": nombre, "stock": 0},
            "ya_preparado": False,
        }


# A confirmed payment is replayed without spending funds or restarting preparation again.
def pagar(conectar, id):
    with closing(conectar()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        compra = compra_db(db, id)
        if not compra:
            raise ProductoNoEncontradoError("Pedido simulado no encontrado")
        if compra["pagado_en"]:
            return compra
        if compra["estado"] != "pendiente_pago":
            raise ConflictoReposicionError("Este pedido ya no admite pago.")
        p = db.execute("SELECT * FROM pedidos_reposicion WHERE id=?", (id,)).fetchone()
        if p["cancelado_en"] or p["recibido_en"] or p["cerrado_incompleto_en"]:
            raise ConflictoReposicionError("El pedido ya está cerrado.")
        fecha = ahora().isoformat()
        db.execute(
            "UPDATE compras_reposicion_simulada SET estado='preparando',pagado_en=?,actualizado_en=? WHERE pedido_id=?",
            (fecha, fecha, id),
        )
        auditar(
            db,
            "pedido_proveedor",
            id,
            "pago_proveedor_simulado_aprobado",
            {"importe_centavos": compra["importe_centavos"]},
        )
        aviso_db(
            db,
            p,
            "confirmado",
            "Pago simulado confirmado. Preparación iniciada automáticamente.",
            fecha,
        )
        return compra_db(db, id)


def aviso_db(db, pedido, estado, nota, fecha):
    referencia = "simulacion-" + estado
    db.execute(
        """INSERT OR IGNORE INTO avisos_proveedor(pedido_id,referencia,proveedor,usuario,estado,nota,registrado_en)
        VALUES (?,?,?,?,?,?,?)""",
        (
            pedido["id"],
            referencia,
            pedido["proveedor"],
            "proveedor_simulado",
            estado,
            nota,
            fecha,
        ),
    )
    auditar(
        db,
        "pedido_proveedor",
        pedido["id"],
        "proveedor_simulado_" + estado,
        {"nota": nota},
        responsable="proveedor_simulado",
    )


# Advance persisted supplier stages only; dispatch does not increase local inventory.
def avanzar_db(db, fecha):
    for c in db.execute(
        "SELECT * FROM compras_reposicion_simulada WHERE estado IN ('preparando','listo')"
    ).fetchall():
        if (
            datetime.fromisoformat(c["actualizado_en"])
            + timedelta(seconds=PASO_SEGUNDOS)
            > fecha
        ):
            continue
        nuevo = "listo" if c["estado"] == "preparando" else "despachado"
        db.execute(
            "UPDATE compras_reposicion_simulada SET estado=?,actualizado_en=? WHERE pedido_id=?",
            (nuevo, fecha.isoformat(), c["pedido_id"]),
        )
        auditar(
            db,
            "pedido_proveedor",
            c["pedido_id"],
            "entrega_proveedor_simulada",
            {"estado": nuevo},
            responsable="proveedor_simulado",
        )
        if nuevo == "despachado":
            p = db.execute(
                "SELECT * FROM pedidos_reposicion WHERE id=?", (c["pedido_id"],)
            ).fetchone()
            aviso_db(
                db,
                p,
                "despachado",
                "Despacho simulado. El negocio debe confirmar la recepción física.",
                fecha.isoformat(),
            )


# Evaluate availability and funds within a write transaction before creating the order and reservation.
def ciclo(conectar):
    from reposicion_automatica import capacidad_oferta

    with closing(conectar()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        fecha = ahora()
        avanzar_db(db, fecha)
        config = db.execute("SELECT * FROM simulacion_reposicion WHERE id=1").fetchone()
        if not config["activa"]:
            return
        id = config["producto_id"]

        def resultado(text):
            db.execute(
                "UPDATE simulacion_reposicion SET resultado=? WHERE id=1", (text,)
            )

        p = db.execute("SELECT stock FROM productos WHERE id=?", (id,)).fetchone()
        if not p:
            return resultado("El producto ya no está disponible. Pausá la prueba.")
        if db.execute(
            "SELECT 1 FROM reglas_reposicion WHERE producto_id=?", (id,)
        ).fetchone():
            return resultado(
                "Existe una regla individual: simulación detenida para este producto."
            )
        if db.execute(
            "SELECT 1 FROM pedidos_reposicion WHERE producto_id=? AND "
            + PEDIDO_ABIERTO,
            (id,),
        ).fetchone():
            return resultado("Hay un pedido abierto. No se genera otro.")
        if p["stock"] > REGLA["minimo"]:
            return resultado("Stock suficiente. Se repone sólo al llegar a cero.")
        ofertas = [
            dict(x)
            for x in db.execute(
                """SELECT o.*,c.actualizado_en,c.error FROM ofertas_proveedor o
            JOIN vinculos_oferta v USING(proveedor,id_externo)
            LEFT JOIN catalogos_control c USING(proveedor)
            WHERE v.producto_id=? AND o.vigente=1 AND o.costo_centavos<=?""",
                (id, REGLA["costo_max_centavos"]),
            )
        ]
        elegibles = []
        for o in ofertas:
            if not o["actualizado_en"] or o["error"]:
                continue
            if (
                datetime.fromisoformat(o["actualizado_en"])
                + timedelta(hours=REGLA["vigencia_horas"])
                < fecha
            ):
                continue
            if capacidad_oferta(db, o) >= REGLA["cantidad"]:
                elegibles.append(o)
        if not elegibles:
            return resultado(
                "Sin oferta vigente para 3 unidades a un máximo de $1.000 por unidad. Revisá catálogo y vínculo."
            )
        oferta = min(elegibles, key=prioridad_oferta)
        importe = REGLA["cantidad"] * oferta["costo_centavos"]
        if fondo_db(db)["disponible_centavos"] < importe:
            return resultado(
                "Fondo simulado insuficiente. No se creó un pedido ni se reservó dinero."
            )
        cursor = db.execute(
            """INSERT INTO pedidos_reposicion(producto_id,proveedor,id_externo,cantidad,costo_ofertado_centavos)
            VALUES (?,?,?,?,?)""",
            (
                id,
                oferta["proveedor"],
                oferta["id_externo"],
                REGLA["cantidad"],
                oferta["costo_centavos"],
            ),
        )
        pedido_id = cursor.lastrowid
        db.execute(
            "INSERT INTO compras_reposicion_simulada VALUES (?,?,'pendiente_pago',NULL,?)",
            (pedido_id, importe, fecha.isoformat()),
        )
        db.execute(
            "INSERT INTO asignaciones_oferta VALUES (?,?,?,?)",
            (
                pedido_id,
                oferta["proveedor"],
                oferta["id_externo"],
                oferta["version_stock"],
            ),
        )
        auditar(
            db,
            "pedido_proveedor",
            pedido_id,
            "pedido_proveedor_creado",
            {
                "simulado": True,
                "cantidad": REGLA["cantidad"],
                "importe_reservado_centavos": importe,
            },
            responsable="reposicion_simulada",
        )
        resultado("Pedido generado y dinero reservado. Falta aprobar el pago simulado.")


def validar_recepcion(db, pedido, costo):
    c = compra_db(db, pedido["id"])
    if c and (c["estado"] != "despachado" or not c["pagado_en"]):
        raise ConflictoReposicionError(
            "Esperá el pago aprobado y el despacho simulado antes de recibir."
        )
    if c and costo != pedido["costo_ofertado_centavos"]:
        raise ConflictoReposicionError(
            "En esta prueba, el costo recibido debe coincidir con el costo ya pagado."
        )


def recepcion_completada(db, id):
    db.execute(
        "UPDATE compras_reposicion_simulada SET estado='recibido',actualizado_en=? WHERE pedido_id=?",
        (ahora().isoformat(), id),
    )


# An unpaid cancellation releases its reservation and pauses further automatic orders.
def cancelar_db(db, id):
    c = compra_db(db, id)
    if not c:
        return
    if c["pagado_en"]:
        raise ConflictoReposicionError(
            "El pedido simulado ya fue pagado. La muestra no incluye reintegros a proveedores."
        )
    db.execute(
        "UPDATE compras_reposicion_simulada SET estado='cancelado',actualizado_en=? WHERE pedido_id=?",
        (ahora().isoformat(), id),
    )
    db.execute(
        "UPDATE simulacion_reposicion SET activa=0,resultado='Pedido cancelado: reserva liberada y generación pausada' WHERE id=1"
    )


def exigir_pedido_normal(db, id):
    if compra_db(db, id):
        raise ConflictoReposicionError(
            "La muestra de pago usa una cantidad y un costo acordados; no incluye correcciones ni cierres con faltantes. Completá la recepción."
        )
