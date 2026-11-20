"""Regression tests: movimientos."""

from contextlib import closing
from unittest import TestCase
from unittest.mock import patch
import sqlite3
import preparar_db_api
import repositorio_sqlite
import test_regresion


class MovimientosInventario(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar
    vender = test_regresion.RegresionInventario.vender
    preparar_pedido = test_regresion.RegresionInventario.preparar_pedido
    agotar_mouse = test_regresion.RegresionInventario.agotar_mouse
    importar_oferta = test_regresion.RegresionInventario.importar_oferta
    reponer = test_regresion.RegresionInventario.reponer

    def stock(self):
        return self.solicitar("GET", "/productos/1")["stock"]

    def movimientos(self, consulta="producto_id=1"):
        return self.solicitar("GET", "/inventario/movimientos?limite=50&" + consulta)[
            "movimientos"
        ]

    def comprobar_saldo(self):
        saldo = 0
        for fila in reversed(self.movimientos()):
            self.assertEqual(fila["stock_anterior"], saldo)
            saldo += fila["variacion"]
            self.assertEqual(fila["stock_resultante"], saldo)
        self.assertEqual(saldo, self.stock())

    def test_saldo_inicial_migracion_repetida_y_filtros(self):
        antes = self.movimientos()
        self.assertEqual(len(antes), 1)
        self.assertEqual(antes[0]["tipo"], "saldo_inicial")
        self.assertEqual(antes[0]["stock_anterior"], 0)
        self.assertEqual(antes[0]["stock_resultante"], 7)
        preparar_db_api.preparar_db_api()
        preparar_db_api.preparar_db_api()
        self.assertEqual(self.movimientos(), antes)
        self.assertEqual(
            self.solicitar("GET", "/inventario/movimientos?limite=1")["total"], 3
        )
        self.assertEqual(self.movimientos("producto_id=999"), [])
        self.solicitar("GET", "/inventario/movimientos?pagina=0", 422)
        self.solicitar("GET", "/inventario/movimientos?tipo=no-existe", 422)
        self.solicitar("GET", "/inventario/movimientos", 403, auth=self.consulta)
        self.assertEqual(self.cliente.get("/inventario/movimientos").status_code, 401)
        self.comprobar_saldo()

    def test_venta_reintento_y_ajuste_con_motivo(self):
        self.vender("venta", 2)
        self.vender("venta", 2)
        self.vender("exceso", 999, 409)
        self.assertEqual(len(self.movimientos()), 2)
        self.solicitar("PATCH", "/productos/1", json={"precio": 9000})
        self.assertEqual(len(self.movimientos()), 2)
        self.solicitar(
            "PATCH", "/productos/1", json={"stock": 6, "motivo_stock": "Conteo físico"}
        )
        m = self.movimientos()[0]
        self.assertEqual(
            (m["tipo"], m["variacion"], m["stock_anterior"], m["stock_resultante"]),
            ("ajuste_manual", 1, 5, 6),
        )
        self.assertEqual(m["motivo"], "Conteo físico")
        self.solicitar(
            "PATCH", "/productos/1", json={"stock": 6, "motivo_stock": "Conteo físico"}
        )
        self.assertEqual(len(self.movimientos()), 3)
        self.solicitar(
            "PATCH", "/productos/1", 422, json={"motivo_stock": "Sin ajuste"}
        )
        self.comprobar_saldo()

    def test_qr_reserva_rechazo_no_mueven_stock_cancelacion_y_reintegro(self):
        datos = {
            "productos": [{"producto_id": 1, "cantidad": 1}],
            "canal": "online",
            "modalidad": "retiro",
        }
        id = self.solicitar("PUT", "/cobros-demo/qr", auth=self.consulta, json=datos)[
            "pedido_venta_id"
        ]
        self.assertEqual(len(self.movimientos()), 1)
        for _ in range(2):
            self.solicitar(
                "PUT",
                "/cobros-demo/qr/pago",
                auth=self.consulta,
                json={"estado": "aprobado"},
            )
        self.assertEqual(self.movimientos()[0]["tipo"], "venta_qr")
        for _ in range(2):
            self.solicitar(
                "PUT",
                f"/pedidos-venta/{id}/cancelaciones/can",
                json={"motivo": "No retira"},
            )
        self.assertEqual(len(self.movimientos()), 3)
        self.assertEqual(self.movimientos()[0]["tipo"], "cancelacion")
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/devoluciones/can/reintegro",
            json={"estado": "confirmado"},
        )
        self.assertEqual(len(self.movimientos()), 3)
        self.solicitar("PUT", "/cobros-demo/rechazo", auth=self.consulta, json=datos)
        self.solicitar(
            "PUT",
            "/cobros-demo/rechazo/pago",
            auth=self.consulta,
            json={"estado": "rechazado"},
        )
        self.assertEqual(len(self.movimientos()), 3)
        self.comprobar_saldo()

    def test_devolucion_apta_y_danada_registran_distinta_variacion(self):
        id = self.vender("venta", 2)["pedido_venta_id"]
        for ref, reponer in [("apto", True), ("danado", False)]:
            datos = {
                "motivo": ref,
                "productos": [{"producto_id": 1, "cantidad": 1, "reponer": reponer}],
            }
            for _ in range(2):
                self.solicitar(
                    "PUT", f"/pedidos-venta/{id}/devoluciones/{ref}", json=datos
                )
        filas = self.movimientos()
        self.assertEqual(len(filas), 4)
        self.assertEqual(
            (filas[0]["cantidad"], filas[0]["variacion"], filas[0]["stock_resultante"]),
            (1, 0, 6),
        )
        self.assertEqual(filas[1]["variacion"], 1)
        self.comprobar_saldo()

    def test_recepcion_y_correccion_remito_solo_una_vez(self):
        id = self.preparar_pedido()
        for _ in range(2):
            self.solicitar(
                "PUT",
                f"/pedidos/{id}/recepciones/remito",
                json={"cantidad": 1, "costo_pagado_centavos": 120000},
            )
        for _ in range(2):
            self.solicitar(
                "PUT",
                f"/pedidos/{id}/recepciones/remito/correcciones/cor",
                json={
                    "cantidad": 2,
                    "costo_pagado_centavos": 120000,
                    "motivo": "Cantidad mal cargada",
                },
            )
        filas = self.movimientos()
        self.assertEqual(
            [m["tipo"] for m in filas],
            ["correccion_remito", "recepcion", "venta_directa", "saldo_inicial"],
        )
        self.assertEqual(filas[0]["variacion"], 1)
        self.assertEqual(filas[0]["motivo"], "Cantidad mal cargada")
        self.comprobar_saldo()

    def test_falla_historial_revierte_venta_y_stock(self):
        with patch("servidor.logger.error"), patch(
            "ventas.registrar_movimiento",
            side_effect=sqlite3.OperationalError("Falla simulada"),
        ):
            self.vender("fallida", 1, 500)
        self.assertEqual(self.stock(), 7)
        self.assertEqual(len(self.movimientos()), 1)
        self.assertEqual(self.solicitar("GET", "/ventas")["total"], 0)
        self.vender("fallida", 1)
        self.comprobar_saldo()

    def test_alta_baja_preservan_historial_y_no_reutilizan_id(self):
        datos = {"nombre": "Nuevo", "categoria": "tecnologia", "precio": 10, "stock": 2}
        id = self.solicitar("POST", "/productos", 201, json=datos)["id"]
        self.assertEqual(self.movimientos(f"producto_id={id}")[0]["tipo"], "alta")
        respuesta = self.cliente.delete(f"/productos/{id}", auth=self.compras)
        self.assertEqual(respuesta.status_code, 204, respuesta.text)
        historial = self.movimientos(f"producto_id={id}")
        self.assertEqual(historial[0]["tipo"], "baja")
        self.assertEqual(historial[0]["stock_resultante"], 0)
        nuevo = self.solicitar(
            "POST", "/productos", 201, json={**datos, "nombre": "Otro"}
        )["id"]
        self.assertGreater(nuevo, id)
        self.assertEqual(self.movimientos(f"producto_id={id}"), historial)

    def test_historial_no_se_edita_y_menu_consulta(self):
        with closing(repositorio_sqlite.conectar_db()) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE movimientos_inventario SET motivo="Otro"')
            db.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM movimientos_inventario")
        import menu_api

        cliente, auth = self.cliente, self.compras

        class Sesion:
            def request(self, metodo, url, **datos):
                datos.pop("timeout", None)
                return cliente.request(metodo, url, auth=auth, **datos)

        with patch("builtins.input", side_effect=["1"]), patch(
            "builtins.print"
        ) as salida:
            menu_api.consultar_movimientos(Sesion())
        texto = " ".join(str(x) for x in salida.call_args_list)
        self.assertIn("Stock inicial", texto)
        self.assertIn("Stock: 0 -> 7", texto)

    def test_actualizacion_base_antigua_inicia_en_stock_actual(self):
        self.vender("anterior", 2)
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.execute("DROP TABLE movimientos_inventario")
        preparar_db_api.preparar_db_api()
        filas = self.movimientos()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["tipo"], "saldo_inicial")
        self.assertEqual(filas[0]["variacion"], 5)
        self.vender("nueva", 1)
        self.comprobar_saldo()

    def test_recepcion_completa_repetida_y_ajuste_negativo(self):
        id = self.preparar_pedido()
        for _ in range(2):
            self.solicitar(
                "PUT",
                f"/pedidos/{id}/recepcion",
                json={"costo_pagado_centavos": 120000},
            )
        self.assertEqual(self.movimientos()[0]["variacion"], 3)
        self.assertEqual(len(self.movimientos()), 3)
        self.solicitar(
            "PATCH",
            "/productos/1",
            json={"stock": 2, "motivo_stock": "Rotura en depósito"},
        )
        self.assertEqual(self.movimientos()[0]["variacion"], -1)
        self.comprobar_saldo()
