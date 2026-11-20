"""Regression tests: reposicion automatica."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from unittest import TestCase
from unittest.mock import patch
import os
import sqlite3
import catalogos
import preparar_db_api
import reposicion_automatica as auto
import repositorio_sqlite
import test_regresion
from proveedor_demo import catalogo


class ReposicionAutomatica(TestCase):
    solicitar = test_regresion.RegresionInventario.solicitar
    importar_oferta = test_regresion.RegresionInventario.importar_oferta

    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"CRUD_REPOSICION_AUTOMATICA": "0"}))
        test_regresion.RegresionInventario.setUp(self)

    def regla(self, id=1, **datos):
        return self.solicitar(
            "PUT",
            f"/productos/{id}/regla-reposicion",
            json={
                "minimo": 5,
                "objetivo": 10,
                "alertar_desde": 7,
                "costo_max_centavos": 150000,
                **datos,
            },
        )

    def stock(self, n):
        return self.solicitar(
            "PATCH", "/productos/1", json={"stock": n, "motivo_stock": "Prueba"}
        )

    def evaluar(self):
        return self.solicitar(
            "POST", "/reposicion-automatica/evaluar?actualizar_catalogos=false"
        )["resultados"][0]

    def alertas(self, activas=True):
        return self.solicitar(
            "GET", f"/reposicion-automatica/alertas?activas={str(activas).lower()}"
        )["alertas"]

    def ofertas(self):
        self.importar_oferta("demo", "1250.50")
        self.importar_oferta("demo-b", "1200.00")

    def test_aviso_anticipado_minimo_inclusivo_objetivo_y_mas_barato(self):
        self.ofertas()
        self.regla()
        r = self.evaluar()
        self.assertEqual(r["estado"], "stock_en_alerta")
        self.assertEqual(self.alertas()[0]["codigo"], "cerca_del_minimo")
        self.stock(5)
        r = self.evaluar()
        self.assertEqual(r["estado"], "pedido_generado")
        self.assertEqual(r["pedido"]["cantidad"], 5)
        self.assertEqual(r["pedido"]["proveedor"], "demo-b")
        self.assertEqual(self.alertas(), [])
        self.assertEqual(self.evaluar()["estado"], "pedido_pendiente")
        self.assertEqual(len(self.solicitar("GET", "/pedidos")), 1)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 5)

    def test_venta_grande_reservas_y_objetivo_individual(self):
        self.ofertas()
        self.stock(2)
        self.regla()
        r = self.evaluar()
        self.assertEqual(r["pedido"]["cantidad"], 8)
        self.assertEqual(r["pedido"]["proveedor"], "demo-b")
        self.regla(id=2, minimo=2, alertar_desde=3, objetivo=6)
        resultados = self.solicitar(
            "POST", "/reposicion-automatica/evaluar?actualizar_catalogos=false"
        )["resultados"]
        self.assertEqual(resultados[1]["estado"], "stock_suficiente")

    def test_reserva_activa_dispara_sin_restar_stock_y_liberacion_no_duplica(self):
        self.ofertas()
        self.regla()
        self.solicitar(
            "PUT",
            "/cobros-demo/reserva",
            auth=self.consulta,
            json={"productos": [{"producto_id": 1, "cantidad": 2}]},
        )
        r = self.evaluar()
        self.assertEqual((r["stock"], r["reservado"], r["disponible"]), (7, 2, 5))
        self.assertEqual(r["pedido"]["cantidad"], 5)
        self.solicitar(
            "PUT",
            "/cobros-demo/reserva/pago",
            auth=self.consulta,
            json={"estado": "rechazado"},
        )
        self.assertEqual(self.evaluar()["estado"], "pedido_pendiente")
        self.assertEqual(len(self.solicitar("GET", "/pedidos")), 1)

    def test_stock_proveedor_insuficiente_y_alerta_no_se_duplica(self):
        self.importar_oferta("demo-b", "1200.00")
        self.stock(0)
        self.regla(objetivo=20, alertar_desde=7, importe_max_centavos=5000000)
        self.evaluar()
        self.evaluar()
        self.assertEqual(len(self.alertas()), 1)
        self.assertEqual(self.alertas()[0]["codigo"], "cobertura_insuficiente")
        self.assertEqual(len(self.solicitar("GET", "/pedidos")), 1)
        self.importar_oferta("demo", "1250.50")
        r = self.evaluar()
        self.assertEqual(r["nuevos_pedidos"][0]["cantidad"], 10)
        self.assertEqual(r["por_recibir"], 20)
        self.assertEqual(self.alertas(), [])
        self.assertTrue(self.alertas(False)[0]["resuelta_en"])

    def test_catalogo_vencido_no_compra_hasta_actualizar(self):
        self.importar_oferta("demo", "1200.00")
        self.stock(5)
        self.regla(vigencia_minutos=1)
        futuro = auto.ahora() + timedelta(minutes=2)
        with patch.object(auto, "ahora", return_value=futuro):
            self.evaluar()
            self.assertEqual(self.alertas()[0]["codigo"], "catalogo_no_confiable")
        self.importar_oferta("demo", "1200.00")
        self.assertEqual(self.evaluar()["estado"], "pedido_generado")

    def test_presupuesto_precio_y_cantidad_maxima(self):
        self.ofertas()
        self.stock(5)
        self.regla(max_unidades=4)
        self.evaluar()
        self.assertEqual(self.alertas()[0]["codigo"], "limite_unidades")
        self.regla(costo_max_centavos=100000)
        self.evaluar()
        self.assertEqual(self.alertas()[0]["codigo"], "limite_precio")
        self.regla(importe_max_centavos=500000)
        r = self.evaluar()
        self.assertEqual(r["estado"], "cobertura_parcial")
        self.assertEqual(r["pedido"]["cantidad"], 4)
        self.solicitar("PUT", f'/pedidos/{r["pedido"]["id"]}/cancelacion')
        self.regla(multiplo=3)
        self.assertEqual(self.evaluar()["pedido"]["cantidad"], 6)

    def test_modo_aviso_desactivacion_y_validacion_permisos(self):
        self.stock(5)
        self.regla(modo="aviso")
        self.evaluar()
        self.assertEqual(self.alertas()[0]["codigo"], "reposicion_sugerida")
        self.regla(activa=False)
        self.assertEqual(self.evaluar()["estado"], "desactivada")
        self.assertEqual(self.alertas(), [])
        self.solicitar(
            "PUT",
            "/productos/1/regla-reposicion",
            422,
            json={"minimo": 10, "objetivo": 10},
        )
        self.solicitar(
            "PUT", "/productos/1/regla-reposicion", 403, auth=self.consulta, json={}
        )
        self.solicitar("PUT", "/productos/999/regla-reposicion", 404, json={})
        self.solicitar("GET", "/reposicion-automatica/alertas?pagina=0", 422)
        self.assertFalse(
            self.solicitar("GET", "/productos/2/regla-reposicion")["configurada"]
        )

    def test_recepcion_parcial_y_cierre_incompleto_recalculan_faltante(self):
        self.ofertas()
        self.stock(5)
        self.regla()
        id = self.evaluar()["pedido"]["id"]
        self.solicitar(
            "PUT",
            f"/pedidos/{id}/recepciones/primero",
            json={"cantidad": 2, "costo_pagado_centavos": 120000},
        )
        r = self.evaluar()
        self.assertEqual(
            (r["disponible"], r["por_recibir"], r["proyectado"]), (7, 3, 10)
        )
        self.solicitar("PUT", f"/pedidos/{id}/cierre-incompleto")

        parcial = self.evaluar()
        self.assertEqual(parcial["estado"], "pedido_generado")
        self.assertEqual(parcial["pedido"]["cantidad"], 3)
        self.stock(5)
        r = self.evaluar()
        self.assertEqual(r["estado"], "pedido_generado")
        self.assertNotEqual(r["pedido"]["id"], id)
        self.assertEqual(r["pedido"]["cantidad"], 2)

    def test_cancelacion_pausa_hasta_revision_y_pedido_demorado(self):
        self.ofertas()
        self.stock(5)
        self.regla(plazo_horas=1)
        id = self.evaluar()["pedido"]["id"]
        futuro = auto.ahora() + timedelta(hours=2)
        with patch.object(auto, "ahora", return_value=futuro):
            self.assertEqual(self.evaluar()["estado"], "pedido_pendiente")
            self.assertEqual(self.alertas()[0]["codigo"], "pedido_demorado")
        self.solicitar("PUT", f"/pedidos/{id}/cancelacion")
        self.assertEqual(self.evaluar()["estado"], "requiere_revision")
        self.assertEqual(self.alertas()[0]["codigo"], "pedido_cancelado")
        self.assertEqual(len(self.solicitar("GET", "/pedidos")), 1)
        self.regla()
        self.assertEqual(self.evaluar()["estado"], "pedido_generado")

    def test_nuevas_ventas_generan_pedido_por_el_faltante(self):
        self.ofertas()
        self.stock(5)
        self.regla()
        self.evaluar()
        self.solicitar(
            "PUT",
            "/ventas/otra",
            auth=self.consulta,
            json={"producto_id": 1, "cantidad": 2},
        )
        r = self.evaluar()
        self.assertEqual(r["proyectado"], 10)
        self.assertEqual(r["nuevos_pedidos"][0]["cantidad"], 2)
        self.assertEqual(self.alertas(), [])
        self.assertEqual(len(self.solicitar("GET", "/pedidos")), 2)

    def test_dos_evaluaciones_simultaneas_y_reinicio_no_duplican(self):
        self.ofertas()
        self.stock(5)
        self.regla()
        with ThreadPoolExecutor(max_workers=2) as e:
            resultados = list(
                e.map(
                    lambda _: auto.evaluar_producto(repositorio_sqlite.conectar_db, 1),
                    [1, 2],
                )
            )
        self.assertEqual(
            sorted(x["estado"] for x in resultados),
            ["pedido_generado", "pedido_pendiente"],
        )
        preparar_db_api.preparar_db_api()
        self.assertEqual(self.evaluar()["estado"], "pedido_pendiente")
        with closing(repositorio_sqlite.conectar_db()) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM pedidos_automaticos").fetchone()[0], 1
            )
        self.assertEqual(len(self.solicitar("GET", "/pedidos")), 1)

    def test_actualiza_catalogo_solo_cuando_corresponde_y_falla_no_compra(self):
        self.importar_oferta("demo", "1200.00")
        self.stock(5)
        self.regla()
        antes = auto.ahora() - timedelta(minutes=2)
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.execute(
                "UPDATE catalogos_control SET ultimo_intento=?", (antes.isoformat(),)
            )
        with patch.object(
            catalogos, "descargar_catalogo", side_effect=OSError("Sin conexión")
        ) as descarga:
            self.solicitar("POST", "/reposicion-automatica/evaluar")
            self.assertEqual(descarga.call_count, 1)
            self.solicitar("POST", "/reposicion-automatica/evaluar")
            self.assertEqual(descarga.call_count, 1)
        self.assertEqual(self.alertas()[0]["codigo"], "catalogo_no_confiable")
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.execute(
                "UPDATE catalogos_control SET ultimo_intento=?", (antes.isoformat(),)
            )
        with patch.object(catalogos, "descargar_catalogo", return_value=catalogo()):
            r = self.solicitar("POST", "/reposicion-automatica/evaluar")["resultados"][
                0
            ]
        self.assertEqual(r["estado"], "pedido_generado")

    def test_fallo_auditoria_revierte_pedido_automatico(self):
        self.ofertas()
        self.stock(5)
        self.regla()
        with patch("servidor.logger.error"), patch.object(
            auto, "actualizar_alerta", side_effect=sqlite3.OperationalError("Prueba")
        ):
            self.solicitar(
                "POST", "/reposicion-automatica/evaluar?actualizar_catalogos=false", 500
            )
        self.assertEqual(self.solicitar("GET", "/pedidos"), [])
        self.assertEqual(self.evaluar()["estado"], "pedido_generado")

    def test_sin_ofertas_y_resolucion_por_recuperacion_stock(self):
        self.stock(5)
        self.regla()
        self.evaluar()
        self.assertEqual(self.alertas()[0]["codigo"], "sin_ofertas")
        self.stock(10)
        self.assertEqual(self.evaluar()["estado"], "stock_suficiente")
        self.assertEqual(self.alertas(), [])

    def test_ultimo_costo_es_informativo_y_permite_reponer_mas_caro(self):
        self.importar_oferta("demo", "1200.00")
        self.stock(0)
        id = self.solicitar("POST", "/productos/1/reposicion")["pedido"]["id"]
        self.solicitar(
            "PUT", f"/pedidos/{id}/recepcion", json={"costo_pagado_centavos": 120000}
        )
        self.importar_oferta("demo", "1300.00")
        self.regla(costo_max_centavos=None)
        r = self.evaluar()
        self.assertEqual(r["estado"], "pedido_generado")
        self.assertEqual(r["ultimo_costo_referencia"], 120000)
        self.assertEqual(r["pedido"]["costo_ofertado_centavos"], 130000)

    def test_cierre_incompleto_con_stock_bajo_repone_solo_lo_faltante(self):
        self.ofertas()
        self.stock(2)
        self.regla()
        id = self.evaluar()["pedido"]["id"]
        self.solicitar(
            "PUT",
            f"/pedidos/{id}/recepciones/primero",
            json={"cantidad": 2, "costo_pagado_centavos": 120000},
        )
        self.solicitar("PUT", f"/pedidos/{id}/cierre-incompleto")
        nuevo = self.evaluar()["pedido"]
        self.assertNotEqual(nuevo["id"], id)
        self.assertEqual(nuevo["cantidad"], 6)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 4)

    def test_ejecucion_programada_habilitada_y_desactivada(self):
        with patch.object(auto, "ejecutar_ciclo") as ejecutar:
            auto.ciclo_programado(repositorio_sqlite.conectar_db)
            ejecutar.assert_not_called()
            with patch.dict(os.environ, {"CRUD_REPOSICION_AUTOMATICA": "1"}):
                auto.ciclo_programado(repositorio_sqlite.conectar_db)
            ejecutar.assert_called_once_with(repositorio_sqlite.conectar_db)

    def test_ciclo_programado_real_genera_y_luego_no_duplica(self):
        self.ofertas()
        self.stock(5)
        self.regla()
        with patch.dict(os.environ, {"CRUD_REPOSICION_AUTOMATICA": "1"}):
            auto.ciclo_programado(repositorio_sqlite.conectar_db)
            auto.ciclo_programado(repositorio_sqlite.conectar_db)
        pedidos = self.solicitar("GET", "/pedidos")
        self.assertEqual(len(pedidos), 1)
        self.assertEqual(pedidos[0]["cantidad"], 5)

    def test_menu_configura_regla_y_consulta_alertas(self):
        import menu_api

        cliente, auth = self.cliente, self.compras

        class Sesion:
            def request(self, metodo, url, **datos):
                datos.pop("timeout", None)
                return cliente.request(metodo, url, auth=auth, **datos)

        with patch(
            "builtins.input",
            side_effect=[
                "1",
                "s",
                "aviso",
                "5",
                "10",
                "7",
                "1",
                "20",
                "150000",
                "1000000",
                "s",
            ],
        ), patch("builtins.print"):
            menu_api.configurar_regla_reposicion(Sesion())
        self.stock(5)
        self.evaluar()
        with patch("builtins.print") as salida:
            menu_api.consultar_alertas_reposicion(Sesion())
        self.assertIn(
            "Reposición sugerida", " ".join(str(x) for x in salida.call_args_list)
        )
