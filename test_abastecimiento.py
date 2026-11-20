"""Regression tests: abastecimiento."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest import TestCase
from unittest.mock import patch
import sqlite3
import catalogos
import preparar_db_api
import reposicion_automatica as auto
import repositorio_sqlite
import test_reposicion_automatica as pruebas_base


class Abastecimiento(TestCase):
    setUp = pruebas_base.ReposicionAutomatica.setUp
    solicitar = pruebas_base.ReposicionAutomatica.solicitar
    stock = pruebas_base.ReposicionAutomatica.stock
    regla = pruebas_base.ReposicionAutomatica.regla
    evaluar = pruebas_base.ReposicionAutomatica.evaluar
    alertas = pruebas_base.ReposicionAutomatica.alertas

    def oferta(self, proveedor, costo, stock):
        datos = {
            "moneda": "ARS",
            "productos": [
                {
                    "id": "0012",
                    "nombre": "Mouse",
                    "marca": "TecnoSur",
                    "categoria": "tecnologia",
                    "precio": costo,
                    "stock": stock,
                }
            ],
        }
        catalogos.guardar_catalogo(repositorio_sqlite.conectar_db, proveedor, datos)
        self.solicitar(
            "PUT",
            f"/proveedores/{proveedor}/ofertas/0012/vinculo",
            json={"producto_id": 1},
        )

    def preparar(self):
        self.stock(4)
        self.regla(costo_max_centavos=None, importe_max_centavos=10000000)

    def emergencia(self, cantidad=3, ref="emergencia", codigo=200, **campos):
        return self.solicitar(
            "PUT",
            f"/productos/1/reposiciones-emergencia/{ref}",
            codigo,
            json={
                "cantidad": cantidad,
                "costo_unitario_centavos": 180000,
                "origen": "Comercio vecino",
                "motivo": "Proveedor sin stock",
                "empleado": "Ana",
                "fecha_compra": "2020-01-01",
                "tipo_comprobante": "ticket",
                "numero_comprobante": ref,
                **campos,
            },
        )

    def test_prefiere_un_proveedor_completo_a_dividir_mas_barato(self):
        self.oferta("demo", "1500", 6)
        self.oferta("demo-b", "1000", 4)
        self.preparar()
        r = self.evaluar()
        self.assertEqual(len(r["nuevos_pedidos"]), 1)
        self.assertEqual(r["pedido"]["proveedor"], "demo")
        self.assertEqual(r["pedido"]["cantidad"], 6)
        self.assertEqual(r["faltante_objetivo"], 0)

    def test_entre_completos_elige_el_de_menor_costo(self):
        self.oferta("demo", "1500", 6)
        self.oferta("demo-b", "1000", 6)
        self.preparar()
        self.assertEqual(self.evaluar()["pedido"]["proveedor"], "demo-b")

    def test_reparte_en_dos_y_persistencia_no_duplica(self):
        self.oferta("demo", "1300", 3)
        self.oferta("demo-b", "1200", 3)
        self.preparar()
        r = self.evaluar()
        self.assertEqual(
            [(x["proveedor"], x["cantidad"]) for x in r["nuevos_pedidos"]],
            [("demo-b", 3), ("demo", 3)],
        )
        self.assertEqual(r["por_recibir"], 6)
        self.assertEqual(r["faltante_objetivo"], 0)
        preparar_db_api.preparar_db_api()
        self.assertEqual(self.evaluar()["nuevos_pedidos"], [])
        self.assertEqual(len(self.solicitar("GET", "/pedidos")), 2)
        for x in r["nuevos_pedidos"]:
            self.solicitar(
                "PUT",
                f'/pedidos/{x["id"]}/recepcion',
                json={"costo_pagado_centavos": x["costo_ofertado_centavos"]},
            )
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 10)
        self.assertEqual(self.evaluar()["estado"], "stock_suficiente")

    def test_compra_parcial_alerta_y_completa_tras_restock_sin_repetir_oferta(self):
        self.oferta("demo", "1300", 2)
        self.oferta("demo-b", "1200", 1)
        self.preparar()
        r = self.evaluar()
        self.assertEqual(r["estado"], "cobertura_parcial")
        self.assertEqual(r["faltante_objetivo"], 3)
        alertaid = self.alertas()[0]["id"]
        self.assertEqual(self.evaluar()["nuevos_pedidos"], [])
        self.assertEqual(self.alertas()[0]["id"], alertaid)
        a = next(x for x in r["pedidos"] if x["proveedor"] == "demo")
        self.solicitar(
            "PUT",
            f'/pedidos/{a["id"]}/recepcion',
            json={"costo_pagado_centavos": 130000},
        )

        self.oferta("demo", "1300", 2)
        self.assertEqual(self.evaluar()["nuevos_pedidos"], [])
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)
        self.oferta("demo-b", "1200", 4)
        nuevo = self.evaluar()
        self.assertEqual(nuevo["nuevos_pedidos"][0]["cantidad"], 3)
        self.assertEqual(nuevo["faltante_objetivo"], 0)
        self.assertEqual(self.alertas(), [])

    def test_restock_cero_y_luego_misma_cantidad_se_reconoce(self):
        self.oferta("demo", "1300", 2)
        self.preparar()
        pedido = self.evaluar()["pedido"]
        self.solicitar(
            "PUT",
            f'/pedidos/{pedido["id"]}/recepcion',
            json={"costo_pagado_centavos": 130000},
        )
        self.assertEqual(self.evaluar()["nuevos_pedidos"], [])

        catalogos.guardar_catalogo(
            repositorio_sqlite.conectar_db,
            "demo",
            {
                "moneda": "ARS",
                "productos": [
                    {
                        "id": "0012",
                        "nombre": "Mouse",
                        "marca": "TecnoSur",
                        "categoria": "tecnologia",
                        "precio": "1300",
                        "stock": 0,
                    }
                ],
            },
        )
        self.evaluar()
        self.oferta("demo", "1300", 2)
        r = self.evaluar()
        self.assertEqual(r["nuevos_pedidos"][0]["cantidad"], 2)
        self.assertEqual(r["faltante_objetivo"], 2)

    def test_emergencia_cubre_faltante_y_reintento_no_duplica_stock(self):
        self.oferta("demo", "1300", 3)
        self.preparar()
        self.evaluar()
        r = self.emergencia()
        repetida = self.emergencia()
        self.assertTrue(repetida.pop("operacion_repetida"))
        self.assertEqual(repetida, r)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)
        estado = self.evaluar()
        self.assertEqual(estado["faltante_objetivo"], 0)
        self.assertEqual(estado["nuevos_pedidos"], [])
        self.assertEqual(len(self.solicitar("GET", "/pedidos")), 1)
        movimientos = self.solicitar(
            "GET", "/inventario/movimientos?tipo=reposicion_emergencia"
        )["movimientos"]
        self.assertEqual(len(movimientos), 1)
        self.assertEqual(movimientos[0]["variacion"], 3)
        self.emergencia(cantidad=4, codigo=409)

    def test_emergencia_excesiva_no_cancela_pedidos_automaticamente(self):
        self.oferta("demo", "1300", 6)
        self.preparar()
        self.evaluar()
        self.emergencia(cantidad=10)
        self.evaluar()
        self.assertEqual(self.alertas()[0]["codigo"], "exceso_proyectado")
        self.assertEqual(self.solicitar("GET", "/pedidos")[0]["estado"], "pendiente")

    def test_fallo_segundo_pedido_revierte_la_compra_dividida_completa(self):
        self.oferta("demo", "1300", 3)
        self.oferta("demo-b", "1200", 3)
        self.preparar()
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.execute(
                """CREATE TRIGGER fallar_demo BEFORE INSERT ON pedidos_reposicion
                WHEN NEW.proveedor='demo' BEGIN SELECT RAISE(ABORT,'Fallo simulado'); END"""
            )
        with patch("servidor.logger.error"):
            self.solicitar(
                "POST", "/reposicion-automatica/evaluar?actualizar_catalogos=false", 500
            )
        self.assertEqual(self.solicitar("GET", "/pedidos"), [])
        with closing(repositorio_sqlite.conectar_db()) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM asignaciones_oferta").fetchone()[0], 0
            )

    def test_concurrencia_no_duplica_pedidos_divididos(self):
        self.oferta("demo", "1300", 3)
        self.oferta("demo-b", "1200", 3)
        self.preparar()
        with ThreadPoolExecutor(max_workers=2) as e:
            r = list(
                e.map(
                    lambda _: auto.evaluar_producto(repositorio_sqlite.conectar_db, 1),
                    [1, 2],
                )
            )
        self.assertEqual(sum(len(x["nuevos_pedidos"]) for x in r), 2)
        self.assertEqual(len(self.solicitar("GET", "/pedidos")), 2)

    def test_emergencia_permisos_validacion_y_fallo_registro(self):
        self.preparar()
        self.solicitar(
            "PUT",
            "/productos/1/reposiciones-emergencia/ajena",
            403,
            auth=self.consulta,
            json={
                "cantidad": 1,
                "costo_unitario_centavos": 100,
                "origen": "Vecino",
                "motivo": "Prueba",
                "empleado": "Ana",
                "fecha_compra": "2020-01-01",
                "tipo_comprobante": "ticket",
                "numero_comprobante": "p",
            },
        )
        self.emergencia(cantidad=0, codigo=422)
        self.solicitar(
            "PUT",
            "/productos/999/reposiciones-emergencia/no-existe",
            404,
            json={
                "cantidad": 1,
                "costo_unitario_centavos": 100,
                "origen": "Vecino",
                "motivo": "Prueba",
                "empleado": "Ana",
                "fecha_compra": "2020-01-01",
                "tipo_comprobante": "ticket",
                "numero_comprobante": "p",
            },
        )
        with patch("servidor.logger.error"), patch(
            "reposicion_emergencia.registrar",
            side_effect=sqlite3.OperationalError("Prueba"),
        ):
            self.emergencia(codigo=500)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 4)

    def test_menu_registra_entrada_emergencia(self):
        import menu_api

        self.preparar()
        cliente, auth = self.cliente, self.compras

        class Sesion:
            def request(self, metodo, url, **datos):
                datos.pop("timeout", None)
                return cliente.request(metodo, url, auth=auth, **datos)

        with patch(
            "builtins.input",
            side_effect=[
                "ticket-vecino",
                "Comercio vecino",
                "Faltante",
                "Ana",
                "2020-01-01",
                "ticket",
                "T-1",
                "1",
                "2",
                "180000",
                "n",
                "",
                "s",
            ],
        ), patch("builtins.print"):
            menu_api.recibir_emergencia(Sesion())
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)
