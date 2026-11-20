"""Regression tests: pedidos venta."""

from unittest import TestCase

import preparar_db_api
import test_regresion


class PedidosVenta(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def crear(self, referencia="pedido-online", **campos):
        datos = {
            "productos": [{"producto_id": 1, "cantidad": 2}],
            "canal": "online",
            "modalidad": "retiro",
            **campos,
        }
        return self.solicitar(
            "PUT", f"/cobros-demo/{referencia}", auth=self.consulta, json=datos
        )

    def pagar(self, referencia="pedido-online", estado="aprobado"):
        return self.solicitar(
            "PUT",
            f"/cobros-demo/{referencia}/pago",
            auth=self.consulta,
            json={"estado": estado},
        )

    def pedido(self, identificador):
        return self.solicitar("GET", f"/pedidos-venta/{identificador}")

    def entregar(self, identificador, estado, codigo=200, **datos):
        return self.solicitar(
            "PUT",
            f"/pedidos-venta/{identificador}/entrega",
            codigo,
            json={"estado": estado},
            **datos,
        )

    def stock(self):
        return self.solicitar("GET", "/productos/1")["stock"]

    def test_retiro_pagado_preparado_y_entregado_sin_doble_descuento(self):
        id = self.crear()["pedido_venta_id"]
        self.assertEqual(self.pedido(id)["estado_entrega"], "pendiente_pago")
        self.entregar(id, "preparando", 409)
        self.pagar()
        self.assertEqual(self.pedido(id)["estado_entrega"], "pendiente")
        self.assertEqual(self.stock(), 5)
        disponibilidad = self.solicitar("GET", "/productos/1/disponibilidad")
        self.assertEqual(disponibilidad["vendido_pendiente_entrega"], 2)
        self.entregar(id, "listo", 409)
        self.entregar(id, "preparando")
        self.entregar(id, "listo")
        self.entregar(id, "enviado", 409)
        resultado = self.entregar(id, "entregado")
        self.assertEqual(self.entregar(id, "entregado"), resultado)
        self.assertEqual(len(resultado["historial_entrega"]), 5)
        self.assertTrue(resultado["entregado_en"])
        self.assertEqual(self.stock(), 5)
        self.assertEqual(
            self.solicitar("GET", "/productos/1/disponibilidad")[
                "vendido_pendiente_entrega"
            ],
            0,
        )
        self.entregar(id, "preparando", 409)

    def test_envio_requiere_despacho_y_conserva_estado_ante_reintento_pago(self):
        id = self.crear(modalidad="envio")["pedido_venta_id"]
        self.pagar()
        self.entregar(id, "preparando")
        self.entregar(id, "listo")
        self.entregar(id, "entregado", 409)
        self.entregar(id, "enviado")
        self.pagar()
        self.assertEqual(self.pedido(id)["estado_entrega"], "enviado")
        self.entregar(id, "entregado")
        self.assertEqual(self.stock(), 5)

    def test_compra_directa_y_qr_comparten_registro_sin_colision(self):
        referencia = "misma-referencia"
        venta = self.solicitar(
            "PUT",
            f"/ventas/{referencia}",
            auth=self.consulta,
            json={"producto_id": 1, "cantidad": 1},
        )
        directo = venta["pedido_venta_id"]
        qr = self.crear(referencia, canal="presencial", modalidad="local")[
            "pedido_venta_id"
        ]
        self.assertNotEqual(directo, qr)
        self.pagar(referencia)
        self.assertEqual(self.pedido(directo)["estado_entrega"], "entregado")
        self.assertEqual(self.pedido(qr)["estado_entrega"], "entregado")
        self.assertEqual(self.solicitar("GET", "/pedidos-venta")["total"], 2)
        self.assertEqual(self.stock(), 4)
        self.assertEqual(self.pedido(directo)["productos"][0]["nombre"], "Mouse")

    def test_rechazo_cancela_entrega_y_libera_stock(self):
        id = self.crear()["pedido_venta_id"]
        self.pagar(estado="rechazado")
        self.assertEqual(self.pedido(id)["estado_entrega"], "cancelado")
        self.entregar(id, "preparando", 409)
        self.assertEqual(self.stock(), 7)

    def test_migracion_repetida_conserva_preparacion_e_historial(self):
        id = self.crear()["pedido_venta_id"]
        self.pagar()
        self.entregar(id, "preparando")
        antes = self.pedido(id)
        preparar_db_api.preparar_db_api()
        preparar_db_api.preparar_db_api()
        self.assertEqual(self.pedido(id), antes)
        self.assertEqual(self.solicitar("GET", "/pedidos-venta")["total"], 1)

    def test_permisos_y_filtros(self):
        id = self.crear()["pedido_venta_id"]
        self.pagar()
        self.entregar(id, "preparando", 403, auth=self.consulta)
        self.assertEqual(
            self.solicitar(
                "GET", "/pedidos-venta?canal=online&estado_entrega=pendiente"
            )["total"],
            1,
        )
        self.assertEqual(
            self.solicitar("GET", "/pedidos-venta?canal=presencial")["total"], 0
        )
        self.solicitar("GET", "/pedidos-venta?pagina=0", 422)
        self.solicitar("GET", "/pedidos-venta/999", 404)

    def test_reintento_no_puede_cambiar_canal_del_pedido(self):
        self.crear()
        self.solicitar(
            "PUT",
            "/cobros-demo/pedido-online",
            409,
            auth=self.consulta,
            json={"productos": [{"producto_id": 1, "cantidad": 2}]},
        )
        self.solicitar(
            "PUT",
            "/cobros-demo/datos-invalidos",
            422,
            auth=self.consulta,
            json={
                "productos": [{"producto_id": 1, "cantidad": 1}],
                "canal": "presencial",
                "modalidad": "envio",
            },
        )

    def test_migracion_incorpora_ventas_anteriores_sin_descontar_stock(self):
        from contextlib import closing
        import repositorio_sqlite

        self.solicitar(
            "PUT",
            "/ventas/venta-antigua",
            auth=self.consulta,
            json={"producto_id": 1, "cantidad": 1},
        )
        self.crear("qr-antiguo", canal="presencial", modalidad="local")
        self.pagar("qr-antiguo")
        stock = self.stock()
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.execute("DROP TABLE historial_entrega")
            db.execute("DROP TABLE items_pedido_venta")
            db.execute("DELETE FROM titulares_pedido")
            db.execute("DROP TABLE pedidos_venta")
            db.execute("ALTER TABLE cobros_demo DROP COLUMN canal")
            db.execute("ALTER TABLE cobros_demo DROP COLUMN modalidad")
        preparar_db_api.preparar_db_api()
        pedidos = self.solicitar("GET", "/pedidos-venta")["pedidos"]
        self.assertEqual(len(pedidos), 2)
        self.assertEqual({p["origen"] for p in pedidos}, {"directa", "qr"})
        self.assertTrue(
            all(
                p["canal"] == "presencial" and p["estado_entrega"] == "entregado"
                for p in pedidos
            )
        )
        self.assertEqual(self.stock(), stock)
