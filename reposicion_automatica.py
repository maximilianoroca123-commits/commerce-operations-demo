"""Earlier individual-product replenishment policies and persistent alerts."""

from auditoria_comercial import registrar as auditar

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from errores import ProductoNoEncontradoError
from inventario_reservas import reservado
from reposicion import PEDIDO_ABIERTO, pedido_con_estado, prioridad_oferta


def ahora():
    return datetime.now(timezone.utc)


def crear_tablas(db):
    db.execute("""CREATE TABLE IF NOT EXISTS reglas_reposicion (
        producto_id INTEGER PRIMARY KEY REFERENCES productos(id),
        configuracion TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1)""")
    db.execute("""CREATE TABLE IF NOT EXISTS catalogos_control (
        proveedor TEXT PRIMARY KEY,
        actualizado_en TEXT,
        ultimo_intento TEXT,
        error TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS pedidos_automaticos (
        pedido_id INTEGER PRIMARY KEY REFERENCES pedidos_reposicion(id),
        producto_id INTEGER NOT NULL REFERENCES productos(id),
        version_regla INTEGER NOT NULL,
        creado_en TEXT NOT NULL,
        decision TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS alertas_reposicion (
        id INTEGER PRIMARY KEY,
        producto_id INTEGER NOT NULL REFERENCES productos(id),
        codigo TEXT NOT NULL,
        detalle TEXT NOT NULL,
        creada_en TEXT NOT NULL,
        actualizada_en TEXT NOT NULL,
        resuelta_en TEXT)""")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS alerta_reposicion_abierta
        ON alertas_reposicion(producto_id) WHERE resuelta_en IS NULL""")
    db.execute("""CREATE TABLE IF NOT EXISTS estado_reposicion (
        producto_id INTEGER PRIMARY KEY REFERENCES productos(id),
        resultado TEXT NOT NULL,
        evaluado_en TEXT NOT NULL)""")

    db.execute(
        """CREATE TABLE IF NOT EXISTS campanas_reposicion (
        producto_id INTEGER PRIMARY KEY REFERENCES productos(id), activa INTEGER NOT NULL)"""
    )
    db.execute("""CREATE TABLE IF NOT EXISTS versiones_stock_oferta (
        proveedor TEXT NOT NULL,id_externo TEXT NOT NULL, stock_observado INTEGER NOT NULL,
        version INTEGER NOT NULL,PRIMARY KEY(proveedor,id_externo))""")
    db.execute("""CREATE TABLE IF NOT EXISTS asignaciones_oferta (
        pedido_id INTEGER PRIMARY KEY REFERENCES pedidos_reposicion(id),
        proveedor TEXT NOT NULL,id_externo TEXT NOT NULL,version INTEGER NOT NULL)""")


def guardar_regla(conectar_db, id, configuracion):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM productos WHERE id=?", (id,)).fetchone() is None:
            raise ProductoNoEncontradoError("Producto no encontrado")

        db.execute(
            """INSERT INTO reglas_reposicion(producto_id,configuracion) VALUES (?,?)
            ON CONFLICT(producto_id) DO UPDATE SET configuracion=excluded.configuracion,version=version+1""",
            (id, json.dumps(configuracion, sort_keys=True)),
        )
        resultado = consultar_regla_db(db, id)
        auditar(
            db,
            "producto",
            id,
            "regla_reposicion_guardada",
            {"version": resultado["version"], "configuracion": configuracion},
        )
        return resultado


def consultar_regla_db(db, id):
    if db.execute("SELECT 1 FROM productos WHERE id=?", (id,)).fetchone() is None:
        raise ProductoNoEncontradoError("Producto no encontrado")
    fila = db.execute(
        "SELECT * FROM reglas_reposicion WHERE producto_id=?", (id,)
    ).fetchone()
    if fila is None:
        return {"producto_id": id, "configurada": False}
    resultado = db.execute(
        "SELECT resultado,evaluado_en FROM estado_reposicion WHERE producto_id=?", (id,)
    ).fetchone()
    return {
        "producto_id": id,
        "configurada": True,
        "version": fila["version"],
        "regla": json.loads(fila["configuracion"]),
        "ultima_evaluacion": json.loads(resultado["resultado"]) if resultado else None,
        "evaluado_en": resultado["evaluado_en"] if resultado else None,
    }


def consultar_regla(conectar_db, id):
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        return consultar_regla_db(db, id)


def actualizar_alerta(db, id, codigo, detalle):
    fila = db.execute(
        "SELECT * FROM alertas_reposicion WHERE producto_id=? AND resuelta_en IS NULL",
        (id,),
    ).fetchone()
    fecha = ahora().isoformat()
    if fila and fila["codigo"] == codigo:
        if fila["detalle"] != detalle:
            db.execute(
                "UPDATE alertas_reposicion SET detalle=?,actualizada_en=? WHERE id=?",
                (detalle, fecha, fila["id"]),
            )
        return
    if fila:
        db.execute(
            "UPDATE alertas_reposicion SET resuelta_en=? WHERE id=?",
            (fecha, fila["id"]),
        )
    if codigo:
        db.execute(
            "INSERT INTO alertas_reposicion(producto_id,codigo,detalle,creada_en,actualizada_en) VALUES (?,?,?,?,?)",
            (id, codigo, detalle, fecha, fecha),
        )


def observar_stock(db, proveedor, id_externo, stock):
    anterior = db.execute(
        "SELECT stock_observado,version FROM versiones_stock_oferta WHERE proveedor=? AND id_externo=?",
        (proveedor, id_externo),
    ).fetchone()
    version = 1 if anterior is None else anterior[1] + int(anterior[0] != stock)
    db.execute(
        """INSERT INTO versiones_stock_oferta VALUES (?,?,?,?) ON CONFLICT(proveedor,id_externo)
        DO UPDATE SET stock_observado=excluded.stock_observado,version=excluded.version""",
        (proveedor, id_externo, stock, version),
    )
    return version


def capacidad_oferta(db, oferta):
    """Exclude units already ordered or received from the same observed offer capacity."""
    clave = (oferta["proveedor"], oferta["id_externo"])
    version = observar_stock(db, *clave, oferta["stock_proveedor"])
    pendientes = db.execute(
        f"""SELECT COALESCE(SUM(cantidad-cantidad_recibida),0) FROM pedidos_reposicion
        WHERE proveedor=? AND id_externo=? AND {PEDIDO_ABIERTO}""",
        clave,
    ).fetchone()[0]
    recibidas = db.execute(
        """SELECT COALESCE(SUM(p.cantidad_recibida),0) FROM asignaciones_oferta a
        JOIN pedidos_reposicion p ON p.id=a.pedido_id
        WHERE a.proveedor=? AND a.id_externo=? AND a.version=?""",
        (*clave, version),
    ).fetchone()[0]
    oferta["version_stock"] = version
    return max(0, oferta["stock_proveedor"] - pendientes - recibidas)


def armar_plan(ofertas, cantidad, multiplo, presupuesto):
    plan = []
    restante = cantidad
    for o in sorted(ofertas, key=prioridad_oferta):
        unidades = min(restante, o["disponibles"], presupuesto // o["costo_centavos"])
        unidades = (unidades // multiplo) * multiplo
        if unidades:
            plan.append((o, unidades))
            restante -= unidades
            presupuesto -= unidades * o["costo_centavos"]
        if restante == 0:
            break
    return plan


def evaluar(db, id):
    fila = db.execute(
        "SELECT configuracion,version FROM reglas_reposicion WHERE producto_id=?", (id,)
    ).fetchone()
    if fila is None:
        return None
    regla = json.loads(fila["configuracion"])
    stock = db.execute("SELECT stock FROM productos WHERE id=?", (id,)).fetchone()[0]
    reservas = reservado(db, id) if regla["considerar_reservas"] else 0
    disponible = stock - reservas
    pendientes = db.execute(
        f"SELECT * FROM pedidos_reposicion WHERE producto_id=? AND {PEDIDO_ABIERTO} ORDER BY id",
        (id,),
    ).fetchall()
    por_recibir = sum(p["cantidad"] - p["cantidad_recibida"] for p in pendientes)
    proyectado = disponible + por_recibir
    necesidad = max(0, regla["objetivo"] - proyectado)
    cantidad = ((necesidad + regla["multiplo"] - 1) // regla["multiplo"]) * regla[
        "multiplo"
    ]
    compra = db.execute(
        """SELECT costo_pagado_centavos FROM pedidos_reposicion WHERE producto_id=?
        AND (recibido_en IS NOT NULL OR cerrado_incompleto_en IS NOT NULL)
        ORDER BY COALESCE(recibido_en,cerrado_incompleto_en) DESC,id DESC LIMIT 1""",
        (id,),
    ).fetchone()
    resultado = {
        "producto_id": id,
        "stock": stock,
        "reservado": reservas,
        "disponible": disponible,
        "por_recibir": por_recibir,
        "proyectado": proyectado,
        "cantidad_calculada": cantidad,
        "faltante_objetivo": necesidad,
        "ultimo_costo_referencia": compra[0] if compra else None,
        "pedidos": [pedido_con_estado(p) for p in pendientes],
        "nuevos_pedidos": [],
    }
    if pendientes:
        resultado["pedido"] = pedido_con_estado(pendientes[0])

    def terminar(estado, codigo=None, mensaje=""):
        resultado["estado"] = estado
        resultado["motivo"] = mensaje
        actualizar_alerta(db, id, codigo, mensaje)
        db.execute(
            """INSERT INTO estado_reposicion VALUES (?,?,?) ON CONFLICT(producto_id)
            DO UPDATE SET resultado=excluded.resultado,evaluado_en=excluded.evaluado_en""",
            (id, json.dumps(resultado, sort_keys=True), ahora().isoformat()),
        )
        return resultado

    campana = db.execute(
        "SELECT activa FROM campanas_reposicion WHERE producto_id=?", (id,)
    ).fetchone()
    en_reposicion = bool(campana and campana[0]) or disponible <= regla["minimo"]
    if not regla["activa"] or disponible >= regla["objetivo"]:
        en_reposicion = False
    db.execute(
        "INSERT INTO campanas_reposicion VALUES (?,?) ON CONFLICT(producto_id) DO UPDATE SET activa=excluded.activa",
        (id, int(en_reposicion)),
    )
    if not regla["activa"]:
        return terminar("desactivada")
    if not en_reposicion:
        if proyectado > regla["objetivo"] and pendientes:
            return terminar(
                "pedido_pendiente",
                "exceso_proyectado",
                "La entrada manual y los pedidos abiertos superan el objetivo. Revisar los pedidos, sin cancelarlos automáticamente",
            )
        if pendientes:
            return terminar("pedido_pendiente")
        if disponible <= regla["alertar_desde"]:
            return terminar(
                "stock_en_alerta",
                "cerca_del_minimo",
                "El disponible se acerca al mínimo. Todavía no corresponde comprar",
            )
        return terminar("pedido_pendiente" if pendientes else "stock_suficiente")
    if cantidad == 0:
        demorados = [
            p["id"]
            for p in pendientes
            if db.execute(
                """SELECT 1 FROM pedidos_automaticos
            WHERE pedido_id=? AND creado_en<=?""",
                (
                    p["id"],
                    (ahora() - timedelta(hours=regla["plazo_horas"])).isoformat(),
                ),
            ).fetchone()
        ]
        if demorados:
            return terminar(
                "pedido_pendiente",
                "pedido_demorado",
                f"Pedidos fuera del plazo esperado: {demorados}. Revisar con los proveedores",
            )
        if proyectado > regla["objetivo"]:
            return terminar(
                "pedido_pendiente",
                "exceso_proyectado",
                "Las entradas previstas superan el objetivo. Revisar antes de comprar más",
            )
        return terminar("pedido_pendiente" if pendientes else "stock_suficiente")
    cancelado = db.execute(
        """SELECT 1 FROM pedidos_automaticos a JOIN pedidos_reposicion p ON p.id=a.pedido_id
        WHERE a.producto_id=? AND a.version_regla=? AND p.cancelado_en IS NOT NULL LIMIT 1""",
        (id, fila["version"]),
    ).fetchone()
    if cancelado:
        return terminar(
            "requiere_revision",
            "pedido_cancelado",
            "Se canceló un pedido automático. Revisar y volver a guardar la regla para reanudar",
        )
    if cantidad > regla["max_unidades"]:
        return terminar(
            "requiere_revision",
            "limite_unidades",
            "El faltante supera el máximo de unidades autorizado por evaluación",
        )
    if regla["modo"] == "aviso":
        return terminar(
            "requiere_revision",
            "reposicion_sugerida",
            f"Faltan {necesidad} unidades para el objetivo. Modo aviso: no se compra",
        )
    ofertas = [
        dict(x)
        for x in db.execute(
            """SELECT o.*,c.actualizado_en,c.error
        FROM vinculos_oferta v JOIN ofertas_proveedor o USING(proveedor,id_externo)
        LEFT JOIN catalogos_control c ON c.proveedor=o.proveedor
        WHERE v.producto_id=? AND o.vigente=1""",
            (id,),
        )
    ]
    if not ofertas:
        return terminar(
            "sin_oferta_elegible",
            "sin_ofertas",
            f"Faltan {necesidad} unidades. Revisar catálogos o reponer manualmente",
        )
    frescas = [
        o
        for o in ofertas
        if o["actualizado_en"]
        and not o["error"]
        and datetime.fromisoformat(o["actualizado_en"])
        + timedelta(minutes=regla["vigencia_minutos"])
        > ahora()
    ]
    if not frescas:
        return terminar(
            "sin_oferta_elegible",
            "catalogo_no_confiable",
            f"Faltan {necesidad} unidades. Catálogos desactualizados o inaccesibles",
        )
    elegibles = []
    for o in frescas:
        o["disponibles"] = capacidad_oferta(db, o)

        if (
            regla["costo_max_centavos"] is None
            or o["costo_centavos"] <= regla["costo_max_centavos"]
        ):
            elegibles.append(o)
    grupos = {
        proveedor: [o for o in elegibles if o["proveedor"] == proveedor]
        for proveedor in {o["proveedor"] for o in elegibles}
    }
    planes_unicos = [
        armar_plan(grupo, cantidad, regla["multiplo"], regla["importe_max_centavos"])
        for grupo in grupos.values()
    ]
    completos = [plan for plan in planes_unicos if sum(q for o, q in plan) == cantidad]
    if completos:

        plan = min(
            completos,
            key=lambda plan: (
                sum(o["costo_centavos"] * q for o, q in plan),
                prioridad_oferta(plan[0][0]),
            ),
        )
    else:
        plan = armar_plan(
            elegibles, cantidad, regla["multiplo"], regla["importe_max_centavos"]
        )
    for oferta, unidades in plan:
        cursor = db.execute(
            """INSERT INTO pedidos_reposicion
            (producto_id,proveedor,id_externo,cantidad,costo_ofertado_centavos) VALUES (?,?,?,?,?)""",
            (
                id,
                oferta["proveedor"],
                oferta["id_externo"],
                unidades,
                oferta["costo_centavos"],
            ),
        )
        pedido = pedido_con_estado(
            db.execute(
                "SELECT * FROM pedidos_reposicion WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
        )
        auditar(
            db,
            "pedido_proveedor",
            pedido["id"],
            "pedido_proveedor_creado",
            {
                "producto_id": id,
                "proveedor": oferta["proveedor"],
                "cantidad": unidades,
                "costo_unitario_centavos": oferta["costo_centavos"],
                "regla_version": fila["version"],
            },
            responsable="sistema_reposicion",
        )
        decision = {
            **resultado,
            "regla": regla,
            "estrategia": "objetivo_prioriza_un_proveedor",
            "plan_compra": [
                {
                    "proveedor": o["proveedor"],
                    "id_externo": o["id_externo"],
                    "cantidad": q,
                    "costo_centavos": o["costo_centavos"],
                }
                for o, q in plan
            ],
            "prioridad_resuelta": (
                "un_proveedor"
                if len({o["proveedor"] for o, q in plan}) == 1
                else "compra_dividida"
            ),
            "proveedor_elegido": oferta["proveedor"],
            "cantidad_pedido": unidades,
            "costo_unitario_centavos": oferta["costo_centavos"],
        }
        db.execute(
            "INSERT INTO pedidos_automaticos VALUES (?,?,?,?,?)",
            (
                pedido["id"],
                id,
                fila["version"],
                ahora().isoformat(),
                json.dumps(decision, sort_keys=True),
            ),
        )
        db.execute(
            "INSERT INTO asignaciones_oferta VALUES (?,?,?,?)",
            (
                pedido["id"],
                oferta["proveedor"],
                oferta["id_externo"],
                oferta["version_stock"],
            ),
        )
        resultado["pedidos"].append(pedido)
        resultado["nuevos_pedidos"].append(pedido)
    compradas = sum(q for o, q in plan)
    resultado["por_recibir"] += compradas
    resultado["proyectado"] += compradas
    resultado["faltante_objetivo"] = max(0, regla["objetivo"] - resultado["proyectado"])
    if resultado["nuevos_pedidos"]:
        resultado["pedido"] = resultado["nuevos_pedidos"][0]
    if resultado["faltante_objetivo"]:
        codigo = "cobertura_insuficiente"
        if not elegibles or (any(o["disponibles"] > 0 for o in elegibles) and not plan):
            codigo = "limite_precio"
        mensaje = (
            f'Faltan {resultado["faltante_objetivo"]} unidades para el objetivo, contando los pedidos abiertos. '
            "Se revisará periódicamente. Puede registrarse una reposición manual de emergencia"
        )
        return terminar(
            "cobertura_parcial" if compradas else "sin_oferta_elegible", codigo, mensaje
        )
    return terminar("pedido_generado" if compradas else "pedido_pendiente")


def evaluar_producto(conectar_db, id):
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM productos WHERE id=?", (id,)).fetchone() is None:
            raise ProductoNoEncontradoError("Producto no encontrado")
        return evaluar(db, id) or {"producto_id": id, "estado": "sin_regla"}


def actualizar_catalogos(conectar_db):
    from catalogos import PROVEEDORES, descargar_catalogo, guardar_catalogo

    with closing(conectar_db()) as db:
        ids = [
            x[0]
            for x in db.execute(
                "SELECT producto_id FROM reglas_reposicion WHERE json_extract(configuracion,'$.activa')=1"
            )
        ]
        if not ids:
            return
        proveedores = {
            x[0]
            for id in ids
            for x in db.execute(
                "SELECT DISTINCT proveedor FROM vinculos_oferta WHERE producto_id=?",
                (id,),
            )
        }
    for proveedor in sorted(proveedores):
        fecha = ahora()
        with closing(conectar_db()) as db, db:
            modo = db.execute(
                "SELECT modo FROM fuentes_catalogo WHERE proveedor=?", (proveedor,)
            ).fetchone()
            if modo and modo[0] == "publicado":
                continue
            previo = db.execute(
                "SELECT ultimo_intento FROM catalogos_control WHERE proveedor=?",
                (proveedor,),
            ).fetchone()
            if (
                previo
                and previo[0]
                and datetime.fromisoformat(previo[0]) + timedelta(seconds=60) > fecha
            ):
                continue
            db.execute(
                """INSERT INTO catalogos_control(proveedor,ultimo_intento) VALUES (?,?)
                ON CONFLICT(proveedor) DO UPDATE SET ultimo_intento=excluded.ultimo_intento""",
                (proveedor, fecha.isoformat()),
            )
        try:
            if proveedor not in PROVEEDORES:
                raise ValueError("Proveedor sin conexión configurada")
            guardar_catalogo(
                conectar_db,
                proveedor,
                descargar_catalogo(PROVEEDORES[proveedor]),
                respetar_publicado=True,
            )
        except (OSError, ValueError):
            with closing(conectar_db()) as db, db:
                db.execute(
                    "UPDATE catalogos_control SET error=? WHERE proveedor=?",
                    ("No se pudo actualizar el catálogo", proveedor),
                )


def ejecutar_ciclo(conectar_db, refrescar=True):
    if refrescar:
        actualizar_catalogos(conectar_db)
    with closing(conectar_db()) as db:
        ids = [
            x[0]
            for x in db.execute(
                "SELECT producto_id FROM reglas_reposicion ORDER BY producto_id"
            )
        ]
    return {"resultados": [evaluar_producto(conectar_db, id) for id in ids]}


def ciclo_programado(conectar_db):
    if os.environ.get("CRUD_REPOSICION_AUTOMATICA", "1") == "1":
        ejecutar_ciclo(conectar_db)


def listar_alertas(conectar_db, activas, pagina, limite):
    condicion = " WHERE resuelta_en IS NULL" if activas else ""
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        total = db.execute(
            "SELECT COUNT(*) FROM alertas_reposicion" + condicion
        ).fetchone()[0]
        filas = db.execute(
            "SELECT * FROM alertas_reposicion"
            + condicion
            + " ORDER BY id DESC LIMIT ? OFFSET ?",
            (limite, (pagina - 1) * limite),
        )
        return {
            "alertas": [dict(x) for x in filas],
            "total": total,
            "pagina": pagina,
            "limite": limite,
        }
