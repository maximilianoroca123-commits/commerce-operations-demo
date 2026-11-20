"""Regression tests: auditoria comercial."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest import TestCase
from unittest.mock import patch
import test_regresion
import preparar_db_api
import repositorio_sqlite


class AuditoriaComercial(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar
    importar_oferta = test_regresion.RegresionInventario.importar_oferta

    def cuenta(self, nombre, rol="empleado"):
        datos = {"usuario": nombre, "rol": rol, "clave": "PruebaSegura123"}
        if rol == "cliente":
            datos["cliente"] = {
                "nombre": nombre,
                "apellido": "Prueba",
                "correo": nombre + "@example.com",
            }
        if rol == "proveedor":
            datos["proveedor"] = "demo"
        self.solicitar("POST", "/usuarios", 201, json=datos)
        return (nombre, "PruebaSegura123")

    def historial(self, tipo, id, auth=None):
        return self.solicitar("GET", f"/auditoria/comercial/{tipo}/{id}", auth=auth)[
            "movimientos"
        ]

    def online(self, auth=None, ref="online"):
        return self.solicitar(
            "PUT",
            f"/cobros-demo/{ref}",
            auth=auth or self.consulta,
            json={
                "productos": [{"producto_id": 1, "cantidad": 1}],
                "canal": "online",
                "modalidad": "retiro",
            },
        )["pedido_venta_id"]

    def pagar(self, auth=None, ref="online"):
        return self.solicitar(
            "PUT",
            f"/cobros-demo/{ref}/pago",
            auth=auth or self.consulta,
            json={"estado": "aprobado"},
        )

    def entregar(self, id, auth=None):
        for estado in ["preparando", "listo", "entregado"]:
            self.solicitar(
                "PUT",
                f"/pedidos-venta/{id}/entrega",
                auth=auth,
                json={"estado": estado},
            )

    def test_venta_online_y_entrega_registran_cuenta_autenticada(self):
        ana = self.cuenta("ana", "cliente")
        empleado = self.cuenta("operador")
        id = self.online(ana)
        self.pagar(ana)
        self.entregar(id, empleado)
        h = self.historial("venta", id, empleado)
        creado = next(x for x in h if x["accion"] == "pedido_creado")
        self.assertEqual((creado["actor"], creado["rol"]), ("ana", "cliente"))
        entregas = [x for x in h if x["accion"] == "entrega_actualizada"]
        self.assertEqual(len(entregas), 3)
        self.assertTrue(all(x["actor"] == "operador" for x in entregas))
        self.assertTrue(any(x["actor"] == "sistema_pagos" for x in h))
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)

    def test_reintentos_y_lecturas_no_duplican_historial(self):
        id = self.online()
        self.pagar()
        self.entregar(id)
        antes = self.historial("venta", id)
        self.online()
        self.pagar()
        self.solicitar(
            "PUT", f"/pedidos-venta/{id}/entrega", json={"estado": "entregado"}
        )
        self.solicitar("GET", f"/pedidos-venta/{id}")
        self.solicitar("GET", "/cobros-demo/online", auth=self.consulta)
        self.assertEqual(self.historial("venta", id), antes)

    def test_caja_venta_reintegro_y_cierre_con_responsables(self):
        empleado = self.cuenta("operador")
        otro = self.cuenta("supervisor")
        self.solicitar(
            "PUT", "/cajas/turno/apertura", auth=empleado, json={"fondo_inicial": 1000}
        )
        venta = self.solicitar(
            "PUT",
            "/ventas-efectivo/venta",
            auth=empleado,
            json={
                "caja": "turno",
                "recibido": 10000,
                "productos": [{"producto_id": 1, "cantidad": 1}],
            },
        )
        id = venta["pedido_venta_id"]
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/devoluciones/dev",
            auth=otro,
            json={
                "motivo": "Prueba",
                "productos": [{"producto_id": 1, "cantidad": 1, "reponer": True}],
            },
        )
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/devoluciones/dev/reintegro",
            auth=otro,
            json={"estado": "confirmado"},
        )
        self.solicitar("PUT", "/cajas/turno/cierre", auth=otro, json={"contado": 1000})
        h = self.historial("caja", "turno")
        self.assertEqual(
            {x["accion"] for x in h},
            {"caja_abierta", "venta_cobrada", "reintegro_efectivo", "caja_cerrada"},
        )
        self.assertEqual(
            next(x["actor"] for x in h if x["accion"] == "caja_abierta"), "operador"
        )
        self.assertEqual(
            next(x["actor"] for x in h if x["accion"] == "caja_cerrada"), "supervisor"
        )
        self.assertEqual(
            next(
                x["actor"]
                for x in self.historial("venta", id)
                if x["accion"] == "devolucion_recibida"
            ),
            "supervisor",
        )

    def test_error_en_auditoria_revierte_stock_cobro_y_caja(self):
        self.solicitar("PUT", "/cajas/turno/apertura", json={"fondo_inicial": 1000})
        with patch("servidor.logger.error"), patch(
            "caja_efectivo.auditar",
            side_effect=sqlite3.IntegrityError("fallo de historial"),
        ):
            self.solicitar(
                "PUT",
                "/ventas-efectivo/venta",
                500,
                json={
                    "caja": "turno",
                    "recibido": 10000,
                    "productos": [{"producto_id": 1, "cantidad": 1}],
                },
            )
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)
        self.assertEqual(self.solicitar("GET", "/cajas/turno")["saldo_esperado"], 1000)
        self.assertEqual(self.solicitar("GET", "/pedidos-venta")["total"], 0)
        self.assertEqual(len(self.historial("caja", "turno")), 1)

    def test_error_en_auditoria_revierte_entrega(self):
        id = self.online()
        self.pagar()
        with patch("servidor.logger.error"), patch(
            "pedidos_venta.auditar",
            side_effect=sqlite3.IntegrityError("fallo de historial"),
        ):
            self.solicitar(
                "PUT",
                f"/pedidos-venta/{id}/entrega",
                500,
                json={"estado": "preparando"},
            )
        self.assertEqual(
            self.solicitar("GET", f"/pedidos-venta/{id}")["estado_entrega"], "pendiente"
        )

    def test_reintegro_fallido_reintento_y_confirmado_solo_cambios_reales(self):
        id = self.online()
        self.pagar()
        self.entregar(id)
        datos = {
            "motivo": "Prueba",
            "productos": [{"producto_id": 1, "cantidad": 1, "reponer": True}],
        }
        for _ in range(2):
            self.solicitar("PUT", f"/pedidos-venta/{id}/devoluciones/dev", json=datos)
        for estado in ["fallido", "fallido", "confirmado", "confirmado"]:
            self.solicitar(
                "PUT",
                f"/pedidos-venta/{id}/devoluciones/dev/reintegro",
                json={"estado": estado},
            )
        h = self.historial("venta", id)
        self.assertEqual(sum(x["accion"] == "devolucion_recibida" for x in h), 1)
        self.assertEqual(sum(x["accion"] == "reintegro_actualizado" for x in h), 2)

    def test_pedidos_proveedor_recepcion_y_cancelacion(self):
        self.solicitar(
            "PUT",
            "/ventas/agotar",
            auth=self.consulta,
            json={"producto_id": 1, "cantidad": 7},
        )
        self.importar_oferta("demo", "1200.00")
        id = self.solicitar("POST", "/productos/1/reposicion")["pedido"]["id"]
        empleado = self.cuenta("operador")
        datos = {"cantidad": 1, "costo_pagado_centavos": 120000}
        for _ in range(2):
            self.solicitar(
                "PUT", f"/pedidos/{id}/recepciones/remito", auth=empleado, json=datos
            )
        h = self.historial("pedido_proveedor", id)
        self.assertEqual(sum(x["accion"] == "mercaderia_recibida" for x in h), 1)
        self.assertEqual(
            next(x["actor"] for x in h if x["accion"] == "mercaderia_recibida"),
            "operador",
        )
        self.solicitar("PUT", f"/pedidos/{id}/cierre-incompleto")
        self.assertTrue(
            any(
                x["accion"] == "pedido_proveedor_cerrado_incompleto"
                for x in self.historial("pedido_proveedor", id)
            )
        )

    def test_automatico_distingue_sistema_y_evaluador(self):
        self.importar_oferta("demo", "1200.00")
        self.solicitar(
            "PATCH", "/productos/1", json={"stock": 4, "motivo_stock": "Prueba"}
        )
        self.solicitar(
            "PUT",
            "/productos/1/regla-reposicion",
            json={
                "modo": "automatico",
                "minimo": 5,
                "objetivo": 10,
                "alertar_desde": 7,
                "multiplo": 1,
                "max_unidades": 20,
                "importe_max_centavos": 1000000,
            },
        )
        r = self.solicitar(
            "POST", "/reposicion-automatica/evaluar?actualizar_catalogos=false"
        )
        id = r["resultados"][0]["pedidos"][0]["id"]
        creado = self.historial("pedido_proveedor", id)[0]
        self.assertEqual(creado["actor"], "sistema_reposicion")
        self.assertEqual(creado["iniciado_por"], "compras")
        antes = len(self.historial("pedido_proveedor", id))
        self.solicitar(
            "POST", "/reposicion-automatica/evaluar?actualizar_catalogos=false"
        )
        self.assertEqual(len(self.historial("pedido_proveedor", id)), antes)

    def test_permisos_de_historial_no_exponen_a_clientes_o_proveedores(self):
        id = self.online()
        for rol, nombre in [("cliente", "ana"), ("proveedor", "vendedor")]:
            auth = self.cuenta(nombre, rol)
            self.solicitar("GET", "/auditoria/comercial", 403, auth=auth)
            self.solicitar("GET", f"/auditoria/comercial/venta/{id}", 403, auth=auth)
        empleado = self.cuenta("operador")
        self.solicitar("GET", f"/auditoria/comercial/venta/{id}", auth=empleado)
        self.solicitar("GET", "/auditoria/comercial", 403, auth=empleado)
        self.solicitar("GET", "/auditoria/comercial/producto/1", 403, auth=empleado)

    def test_historial_inmutable_y_migracion_no_agrega_hechos(self):
        self.online()
        antes = self.solicitar("GET", "/auditoria/comercial")
        preparar_db_api.preparar_db_api()
        preparar_db_api.preparar_db_api()
        self.assertEqual(self.solicitar("GET", "/auditoria/comercial"), antes)
        with closing(repositorio_sqlite.conectar_db()) as db:
            for sql in [
                "DELETE FROM auditoria_comercial",
                "UPDATE auditoria_comercial SET actor='otro'",
            ]:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql)
                db.rollback()

    def test_contexto_no_mezcla_cuentas_simultaneas(self):
        ana = self.cuenta("ana", "cliente")
        bruno = self.cuenta("bruno", "cliente")
        with ThreadPoolExecutor(max_workers=2) as ex:
            r = list(
                ex.map(
                    lambda par: self.cliente.put(
                        "/cobros-demo/" + par[0],
                        auth=par[1],
                        json={
                            "productos": [{"producto_id": 1, "cantidad": 1}],
                            "canal": "online",
                            "modalidad": "retiro",
                        },
                    ),
                    [("ana", ana), ("bruno", bruno)],
                )
            )
        for nombre, respuesta in zip(["ana", "bruno"], r):
            self.assertEqual(respuesta.status_code, 200)
            h = self.historial("venta", respuesta.json()["pedido_venta_id"])
            self.assertEqual(h[0]["actor"], nombre)

        self.solicitar("PATCH", "/productos/2", json={"precio": 8000})
        self.assertEqual(self.historial("producto", 2)[0]["actor"], "compras")

    def test_catalogo_vinculo_y_producto_registran_cambios_no_consultas(self):
        self.importar_oferta("demo", "1200.00")
        antes = len(self.historial("proveedor", "demo"))
        self.importar_oferta("demo", "1200.00")
        self.assertEqual(len(self.historial("proveedor", "demo")), antes)
        self.solicitar("PATCH", "/productos/1", json={"precio": 9000})
        antes = len(self.historial("producto", 1))
        self.solicitar("PATCH", "/productos/1", json={"precio": 9000})
        self.assertEqual(len(self.historial("producto", 1)), antes)
        self.solicitar("GET", "/auditoria/comercial?limite=1&entidad=producto")
        self.solicitar("GET", "/auditoria/comercial?pagina=0", 422)

    def test_solicitud_y_resolucion_quedan_en_historial_de_venta(self):
        ana = self.cuenta("ana", "cliente")
        id = self.online(ana)
        self.pagar(ana)
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/solicitudes/sol-1",
            auth=ana,
            json={"tipo": "cancelacion", "motivo": "Prueba"},
        )
        self.solicitar(
            "PUT",
            f"/solicitudes-clientes/{id}/sol-1/resolucion",
            json={"estado": "rechazada", "motivo": "Prueba"},
        )
        h = self.historial("venta", id)
        self.assertEqual(
            next(x["actor"] for x in h if x["accion"] == "solicitud_cliente_creada"),
            "ana",
        )
        self.assertEqual(
            next(x["actor"] for x in h if x["accion"] == "solicitud_cliente_resuelta"),
            "compras",
        )
        self.assertNotIn("PruebaSegura123", str(h))
        self.assertNotIn("ana@example.com", str(h))

    def test_emergencia_y_adjunto_posterior_no_duplican_eventos(self):
        import base64

        empleado = self.cuenta("operador")
        datos = {
            "origen": "Comercio",
            "motivo": "Prueba",
            "empleado": "Nombre declarado",
            "fecha_compra": "2020-01-01",
            "tipo_comprobante": "ticket",
            "numero_comprobante": "1",
            "productos": [
                {"producto_id": 1, "cantidad": 1, "costo_unitario_centavos": 100000}
            ],
        }
        for _ in range(2):
            self.solicitar(
                "PUT", "/reposiciones-emergencia/em-1", auth=empleado, json=datos
            )
        adjunto = {
            "nombre": "prueba.pdf",
            "contenido_base64": base64.b64encode(b"%PDF-prueba").decode(),
        }
        for _ in range(2):
            self.solicitar(
                "PUT",
                "/reposiciones-emergencia/em-1/comprobante",
                auth=empleado,
                json=adjunto,
            )
        h = self.historial("emergencia", "em-1")
        self.assertEqual(len(h), 2)
        self.assertTrue(all(x["actor"] == "operador" for x in h))
        self.assertNotIn("Nombre declarado", str(h))
        self.assertNotIn(adjunto["contenido_base64"], str(h))

    def test_apertura_cierre_y_movimiento_repetidos_no_duplican(self):
        for _ in range(2):
            self.solicitar("PUT", "/cajas/turno/apertura", json={"fondo_inicial": 1000})
        for _ in range(2):
            self.solicitar(
                "PUT",
                "/cajas/turno/movimientos/retiro",
                json={"tipo": "retiro", "importe": 100, "motivo": "Prueba"},
            )
        for _ in range(2):
            self.solicitar("PUT", "/cajas/turno/cierre", json={"contado": 900})
        self.assertEqual(len(self.historial("caja", "turno")), 3)

    def test_automatico_fuera_de_peticion_no_hereda_ultimo_usuario(self):
        from auditoria_comercial import registrar

        self.online()
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            registrar(db, "producto", 1, "evento_sistema_prueba", {})
        self.assertEqual(self.historial("producto", 1)[0]["actor"], "sistema")
        self.assertIsNone(self.historial("producto", 1)[0]["iniciado_por"])

    def test_correccion_y_cancelacion_de_proveedor_quedan_registradas(self):
        self.solicitar(
            "PUT",
            "/ventas/agotar",
            auth=self.consulta,
            json={"producto_id": 1, "cantidad": 7},
        )
        self.importar_oferta("demo", "1200.00")
        id = self.solicitar("POST", "/productos/1/reposicion")["pedido"]["id"]
        self.solicitar(
            "PUT",
            f"/pedidos/{id}/recepciones/rem",
            json={"cantidad": 1, "costo_pagado_centavos": 120000},
        )
        datos = {"cantidad": 2, "costo_pagado_centavos": 120000, "motivo": "Prueba"}
        for _ in range(2):
            self.solicitar(
                "PUT", f"/pedidos/{id}/recepciones/rem/correcciones/corr", json=datos
            )
        self.assertEqual(
            sum(
                x["accion"] == "recepcion_corregida"
                for x in self.historial("pedido_proveedor", id)
            ),
            1,
        )
        self.solicitar("PUT", f"/pedidos/{id}/cierre-incompleto")
        self.solicitar(
            "PUT",
            "/ventas/segunda",
            auth=self.consulta,
            json={"producto_id": 1, "cantidad": 2},
        )
        nuevo = self.solicitar("POST", "/productos/1/reposicion")["pedido"]["id"]
        for _ in range(2):
            self.solicitar("PUT", f"/pedidos/{nuevo}/cancelacion")
        self.assertEqual(
            sum(
                x["accion"] == "pedido_proveedor_cancelado"
                for x in self.historial("pedido_proveedor", nuevo)
            ),
            1,
        )
