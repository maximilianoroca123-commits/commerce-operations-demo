"""Regression tests: regresion."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

import preparar_db_api
import repositorio_sqlite
import servidor
from proveedor_demo import catalogo, catalogo_b


class RegresionInventario(TestCase):
    def setUp(self):
        temporal = self.enterContext(TemporaryDirectory())
        ruta = Path(temporal) / "pruebas.db"
        self.enterContext(patch.object(preparar_db_api, "RUTA_DB_API", ruta))
        self.enterContext(patch.object(repositorio_sqlite, "RUTA_DB_API", ruta))
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "CRUD_CLAVE_COMPRAS": "clave-prueba-compras",
                    "CRUD_CUENTAS_COMPATIBILIDAD": "1",
                    "DEMO_STOCK_MOUSE": "20",
                    "DEMO_B_STOCK_MOUSE": "10",
                    "CRUD_CLAVE_CONSULTA": "clave-prueba-consulta",
                },
            )
        )
        preparar_db_api.preparar_db_api()
        self.cliente = self.enterContext(TestClient(servidor.app))
        self.compras = ("compras", "clave-prueba-compras")
        self.consulta = ("consulta", "clave-prueba-consulta")

    def solicitar(self, metodo, ruta, codigo=200, auth=None, **datos):
        respuesta = self.cliente.request(
            metodo, ruta, auth=auth or self.compras, **datos
        )
        self.assertEqual(respuesta.status_code, codigo, respuesta.text)
        return respuesta.json()

    def stock(self):
        return self.solicitar("GET", "/productos/1")["stock"]

    def vender(self, referencia, cantidad, codigo=200):
        return self.solicitar(
            "PUT",
            f"/ventas/{referencia}",
            codigo,
            auth=self.consulta,
            json={"producto_id": 1, "cantidad": cantidad},
        )

    def importar_oferta(self, proveedor, precio):
        datos = catalogo() if proveedor == "demo" else catalogo_b()
        datos["productos"][0]["precio"] = precio
        with patch.object(servidor, "descargar_catalogo", return_value=datos):
            self.solicitar("POST", f"/proveedores/{proveedor}/importar")
        self.solicitar(
            "PUT",
            f"/proveedores/{proveedor}/ofertas/0012/vinculo",
            json={"producto_id": 1},
        )

    def agotar_mouse(self):
        self.vender("venta-inicial", self.stock())

    def reponer(self):
        return self.solicitar("POST", "/productos/1/reposicion")

    def preparar_pedido(self):
        self.agotar_mouse()
        self.importar_oferta("demo", "1200.00")
        resultado = self.reponer()
        self.assertEqual(resultado["estado"], "pedido_generado")
        return resultado["pedido"]["id"]

    def entregar(self, pedido, referencia, cantidad, costo=120000, codigo=200):
        return self.solicitar(
            "PUT",
            f"/pedidos/{pedido}/recepciones/{referencia}",
            codigo,
            json={"cantidad": cantidad, "costo_pagado_centavos": costo},
        )

    def test_venta_rechaza_stock_insuficiente_y_respeta_permisos(self):
        inicial = self.stock()
        self.vender("venta-excesiva", inicial + 1, 409)
        self.solicitar(
            "PUT", "/ventas/venta-compras", 403, json={"producto_id": 1, "cantidad": 1}
        )
        self.solicitar("POST", "/productos/1/reposicion", 403, auth=self.consulta)
        self.assertEqual(self.stock(), inicial)

    def test_ciclo_venta_reposicion_y_reintentos_de_entrega(self):
        inicial = self.stock()
        pedido = self.preparar_pedido()
        self.assertEqual(self.stock(), 0)
        reintento = self.vender("venta-inicial", inicial)
        self.assertEqual(reintento["estado"], "venta_ya_registrada")
        repetido = self.reponer()
        self.assertEqual(repetido["estado"], "pedido_pendiente")
        self.assertEqual(repetido["pedido"]["id"], pedido)
        parcial = self.entregar(pedido, "remito-1", 2)["pedido"]
        self.assertEqual(
            (parcial["estado"], parcial["cantidad_pendiente"]), ("parcial", 1)
        )
        self.entregar(pedido, "remito-2", 2, codigo=409)
        self.assertEqual(self.stock(), 2)
        completo = self.entregar(pedido, "remito-2", 1)["pedido"]
        self.assertEqual(
            (completo["estado"], completo["cantidad_pendiente"]), ("recibido", 0)
        )
        self.assertEqual(
            self.entregar(pedido, "remito-2", 1)["estado"], "entrega_ya_registrada"
        )
        self.assertEqual(self.stock(), 3)

    def test_reposicion_respeta_el_costo_y_desempata_por_proveedor(self):
        pedido = self.preparar_pedido()
        self.entregar(pedido, "recepcion", 3)
        self.vender("segunda-venta", 3)
        self.importar_oferta("demo", "1300.00")
        self.importar_oferta("demo-b", "1300.00")
        self.assertEqual(
            self.reponer(),
            {
                "estado": "sin_oferta_elegible",
                "ultimo_costo_centavos": 120000,
            },
        )
        self.importar_oferta("demo-b", "1200.00")
        self.importar_oferta("demo", "1200.00")
        self.assertEqual(self.reponer()["pedido"]["proveedor"], "demo")

    def test_cancelacion_conserva_historial_y_permite_otro_pedido(self):
        pedido = self.preparar_pedido()
        ruta = f"/pedidos/{pedido}/cancelacion"
        self.assertEqual(self.solicitar("PUT", ruta)["estado"], "cancelado")
        self.assertEqual(self.solicitar("PUT", ruta)["estado"], "ya_cancelado")
        self.entregar(pedido, "remito", 1, codigo=409)
        self.assertEqual(
            self.solicitar("GET", f"/pedidos/{pedido}")["estado"], "cancelado"
        )
        self.assertEqual(self.stock(), 0)
        self.assertNotEqual(self.reponer()["pedido"]["id"], pedido)

    def test_cierre_incompleto_conserva_lo_recibido(self):
        pedido = self.preparar_pedido()
        self.entregar(pedido, "remito", 2)
        ruta = f"/pedidos/{pedido}/cierre-incompleto"
        resultado = self.solicitar("PUT", ruta)["pedido"]
        self.assertEqual(resultado["estado"], "cerrado_incompleto")
        self.assertEqual(resultado["cantidad_pendiente"], 0)
        self.assertEqual(resultado["cantidad_no_entregada"], 1)
        self.assertEqual(self.solicitar("PUT", ruta)["estado"], "ya_cerrado_incompleto")
        self.entregar(pedido, "remito-tardio", 1, codigo=409)
        self.assertEqual(self.stock(), 2)
        self.assertEqual(self.solicitar("GET", "/pedidos?estado=parcial"), [])
        self.assertEqual(
            self.solicitar("GET", "/pedidos?estado=cerrado_incompleto"), [resultado]
        )

    def test_correccion_conserva_auditoria_y_aplica_solo_la_diferencia(self):
        pedido = self.preparar_pedido()
        self.entregar(pedido, "remito-prueba", 1, costo=1)
        historial = f"/pedidos/{pedido}/recepciones/remito-prueba/correcciones"
        ruta = f"{historial}/corr-1"
        datos = {
            "cantidad": 2,
            "costo_pagado_centavos": 120000,
            "motivo": "Error de carga",
        }
        correccion = self.solicitar("PUT", ruta, json=datos)
        self.assertEqual(correccion["estado"], "correccion_registrada")
        self.assertEqual(correccion["correccion"]["cantidad_anterior"], 1)
        self.assertEqual(correccion["correccion"]["costo_anterior_centavos"], 1)
        self.assertEqual(self.solicitar("GET", historial), [correccion["correccion"]])
        self.assertEqual(
            self.solicitar("PUT", ruta, json=datos)["estado"],
            "correccion_ya_registrada",
        )
        self.solicitar("PUT", ruta, 409, json={**datos, "cantidad": 3})
        self.assertEqual(self.stock(), 2)
        self.assertEqual(
            self.entregar(pedido, "remito-final", 1)["pedido"]["estado"], "recibido"
        )
        self.assertEqual(self.stock(), 3)
