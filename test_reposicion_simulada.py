"""Regression tests: reposicion simulada."""

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest import TestCase
from unittest.mock import patch
import time
import sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path
import test_regresion
import reposicion_simulada as sim
import repositorio_sqlite
import respaldos


class ReposicionSimulada(TestCase):
    solicitar = test_regresion.RegresionInventario.solicitar

    def setUp(self):
        self.tick = sim.ciclo
        self.enterContext(patch.object(sim, "ciclo", return_value=None))
        test_regresion.RegresionInventario.setUp(self)

    def preparar(self, saldo=200000, oferta=True):
        self.producto = self.solicitar(
            "POST",
            "/productos",
            201,
            json={
                "nombre": "Prueba automatización",
                "marca": "Demo",
                "categoria": "tecnologia",
                "precio": 1000,
                "stock": 0,
            },
        )["id"]
        for name, rol, extra in [
            ("proveedor_auto", "proveedor", {"proveedor": "demo"}),
            ("empleado_auto", "empleado", {}),
        ]:
            self.solicitar(
                "POST",
                "/usuarios",
                201,
                json={"usuario": name, "clave": "PruebaSegura123", "rol": rol, **extra},
            )
        self.proveedor = ("proveedor_auto", "PruebaSegura123")
        self.empleado = ("empleado_auto", "PruebaSegura123")
        if oferta:
            self.publicar()
        if saldo:
            self.solicitar(
                "PUT",
                "/reposicion-simulada/aportes/aporte-1",
                json={"importe_centavos": saldo},
            )
        self.solicitar(
            "PUT",
            "/reposicion-simulada/configuracion",
            json={"producto_id": self.producto, "activa": True},
        )
        return self.producto

    def publicar(self, stock=3, precio="500.50"):
        self.solicitar(
            "PUT",
            "/mi-proveedor/catalogo",
            auth=self.proveedor,
            json={
                "productos": [
                    {
                        "id": "auto-web-1",
                        "nombre": "Prueba automatización",
                        "marca": "Demo",
                        "categoria": "tecnologia",
                        "precio": precio,
                        "stock": stock,
                    }
                ]
            },
        )
        self.solicitar(
            "PUT",
            "/proveedores/demo/ofertas/auto-web-1/vinculo",
            json={"producto_id": self.producto},
        )

    def ciclo(self):
        self.tick(repositorio_sqlite.conectar_db)

    def estado(self):
        return self.solicitar("GET", "/reposicion-simulada")

    def generar(self):
        self.preparar()
        self.ciclo()
        self.id = self.estado()["compras"][0]["pedido_id"]
        return self.id

    def pagar(self):
        return self.solicitar(
            "PUT", f"/reposicion-simulada/pedidos/{self.id}/pago-aprobado"
        )

    def avanzar(self):
        fecha = sim.ahora()
        for seconds in (6, 12):
            with patch.object(
                sim, "ahora", return_value=fecha + timedelta(seconds=seconds)
            ):
                self.ciclo()

    def recibir(self, ref="remito-auto", cantidad=3, costo=50050, codigo=200):
        return self.solicitar(
            "PUT",
            f"/pedidos/{self.id}/recepciones/{ref}",
            codigo,
            auth=self.empleado,
            json={"cantidad": cantidad, "costo_pagado_centavos": costo},
        )

    def test_circuito_fondo_reserva_pago_despacho_y_recepcion_sin_duplicados(self):
        self.generar()
        r = self.estado()
        self.assertEqual(r["fondo"]["reservado_centavos"], 150150)
        self.assertEqual(r["fondo"]["disponible_centavos"], 49850)
        self.assertEqual(r["fondo"]["pagado_centavos"], 0)
        self.ciclo()
        self.assertEqual(self.estado()["total"], 1)
        self.recibir(codigo=409)
        self.pagar()
        self.pagar()
        r = self.estado()
        self.assertEqual(r["fondo"]["reservado_centavos"], 0)
        self.assertEqual(r["fondo"]["pagado_centavos"], 150150)
        self.assertEqual(r["compras"][0]["estado"], "preparando")
        self.recibir(codigo=409)
        self.avanzar()
        self.assertEqual(self.estado()["compras"][0]["estado"], "despachado")
        self.assertEqual(
            self.solicitar("GET", f"/productos/{self.producto}")["stock"], 0
        )
        own = self.solicitar(
            "GET", f"/mi-proveedor/pedidos/{self.id}", auth=self.proveedor
        )
        self.assertEqual(own["simulacion"]["estado"], "despachado")
        self.assertEqual(own["acciones_aviso"], [])
        self.recibir()
        self.recibir()
        self.assertEqual(
            self.solicitar("GET", f"/productos/{self.producto}")["stock"], 3
        )
        self.assertEqual(self.estado()["compras"][0]["estado"], "recibido")
        self.assertEqual(self.estado()["fondo"]["saldo_centavos"], 49850)
        self.ciclo()
        self.assertEqual(self.estado()["total"], 1)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)
        self.assertEqual(self.solicitar("GET", "/cajas")["total"], 0)

    def test_sin_saldo_no_genera_pedido_y_aporte_repetido_no_duplica(self):
        self.preparar(saldo=0)
        self.ciclo()
        self.assertEqual(self.estado()["total"], 0)
        self.assertIn("insuficiente", self.estado()["configuracion"]["resultado"])
        for _ in range(2):
            self.solicitar(
                "PUT",
                "/reposicion-simulada/aportes/aporte-nuevo",
                json={"importe_centavos": 200000},
            )
        self.solicitar(
            "PUT",
            "/reposicion-simulada/aportes/aporte-nuevo",
            409,
            json={"importe_centavos": 200001},
        )
        self.assertEqual(self.estado()["fondo"]["aportado_centavos"], 200000)
        self.ciclo()
        self.assertEqual(self.estado()["total"], 1)

    def test_sin_oferta_stock_o_precio_permitido_no_compra(self):
        self.preparar(oferta=False)
        self.ciclo()
        self.assertEqual(self.estado()["total"], 0)
        self.publicar(stock=2)
        self.ciclo()
        self.assertEqual(self.estado()["total"], 0)
        self.publicar(stock=3, precio="1000.01")
        self.ciclo()
        self.assertEqual(self.estado()["total"], 0)
        self.publicar()
        self.ciclo()
        self.assertEqual(self.estado()["total"], 1)

    def test_catalogo_vencido_no_compra_hasta_que_se_publique(self):
        self.preparar()
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.execute(
                "UPDATE catalogos_control SET actualizado_en='2020-01-01T00:00:00+00:00'"
            )
        self.ciclo()
        self.assertEqual(self.estado()["total"], 0)
        self.publicar()
        self.ciclo()
        self.assertEqual(self.estado()["total"], 1)

    def test_cancelar_sin_pago_libera_reserva_y_pausa_para_no_recomprar(self):
        self.generar()
        self.solicitar("PUT", f"/pedidos/{self.id}/cancelacion")
        self.ciclo()
        r = self.estado()
        self.assertFalse(r["configuracion"]["activa"])
        self.assertEqual(r["fondo"]["disponible_centavos"], 200000)
        self.assertEqual(r["compras"][0]["estado"], "cancelado")
        self.assertEqual(r["total"], 1)
        self.solicitar(
            "PUT", f"/reposicion-simulada/pedidos/{self.id}/pago-aprobado", 409
        )

    def test_pago_impide_cancelacion_cambio_costo_y_cierre_que_requieren_reintegro(
        self,
    ):
        self.generar()
        self.pagar()
        self.solicitar("PUT", f"/pedidos/{self.id}/cancelacion", 409)
        self.avanzar()
        self.recibir(costo=50051, codigo=409)
        self.recibir(cantidad=1)
        self.solicitar("PUT", f"/pedidos/{self.id}/cierre-incompleto", 409)
        self.solicitar(
            "PUT",
            f"/pedidos/{self.id}/recepciones/remito-auto/correcciones/c",
            409,
            json={"cantidad": 2, "costo_pagado_centavos": 50050, "motivo": "Prueba"},
        )
        self.recibir("remito-auto-2", 2)
        self.assertEqual(self.estado()["fondo"]["pagado_centavos"], 150150)

    def test_pausa_no_deshace_reserva_ni_detiene_un_pedido_pagado(self):
        self.generar()
        self.pagar()
        self.solicitar(
            "PUT",
            "/reposicion-simulada/configuracion",
            json={"producto_id": self.producto, "activa": False},
        )
        self.avanzar()
        self.assertEqual(self.estado()["compras"][0]["estado"], "despachado")
        self.assertFalse(self.estado()["configuracion"]["activa"])

    def test_concurrencia_no_duplica_pedidos_pagos_ni_gasto(self):
        self.preparar()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.ciclo(), range(4)))
        r = self.estado()
        self.assertEqual(r["total"], 1)
        self.id = r["compras"][0]["pedido_id"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(
                pool.map(
                    lambda _: sim.pagar(repositorio_sqlite.conectar_db, self.id),
                    range(4),
                )
            )
        self.assertEqual(self.estado()["fondo"]["pagado_centavos"], 150150)

    def test_permisos_simulados_y_proveedor_solo_lectura_de_su_pedido(self):
        self.generar()
        self.solicitar("GET", "/reposicion-simulada", auth=self.empleado)
        self.solicitar("GET", "/reposicion-simulada", 403, auth=self.proveedor)
        for auth in [self.empleado, self.proveedor, self.consulta]:
            self.solicitar(
                "PUT",
                f"/reposicion-simulada/pedidos/{self.id}/pago-aprobado",
                403,
                auth=auth,
            )
            self.solicitar(
                "PUT",
                "/reposicion-simulada/aportes/ajeno",
                403,
                auth=auth,
                json={"importe_centavos": 200000},
            )
            self.solicitar(
                "PUT",
                "/reposicion-simulada/configuracion",
                403,
                auth=auth,
                json={"producto_id": self.producto, "activa": True},
            )
        self.solicitar(
            "PUT",
            f"/mi-proveedor/pedidos/{self.id}/avisos/manual",
            409,
            auth=self.proveedor,
            json={"estado": "despachado", "nota": "No corresponde"},
        )

    def test_reinicio_repetido_y_backup_conservan_pago_y_estado(self):
        self.generar()
        self.pagar()
        sim.instalar(repositorio_sqlite.conectar_db)
        self.pagar()
        self.avanzar()
        with closing(repositorio_sqlite.conectar_db()) as db:
            path = db.execute("PRAGMA database_list").fetchone()[2]
        copy = respaldos.crear(path)
        self.assertEqual(
            respaldos.verificar(path, copy["archivo"])["verificacion"]["integridad"],
            "ok",
        )
        with TemporaryDirectory() as t:
            extraida = Path(t) / "copia.db"
            respaldos._extraer(respaldos.carpeta(path) / copy["archivo"], extraida)
            with closing(sqlite3.connect(extraida)) as db:
                self.assertEqual(
                    db.execute(
                        "SELECT estado,importe_centavos FROM compras_reposicion_simulada"
                    ).fetchone(),
                    ("despachado", 150150),
                )
                self.assertEqual(
                    db.execute(
                        "SELECT SUM(importe_centavos) FROM aportes_reposicion_simulada"
                    ).fetchone()[0],
                    200000,
                )
        self.assertEqual(self.estado()["fondo"]["pagado_centavos"], 150150)
        self.assertEqual(self.estado()["compras"][0]["estado"], "despachado")

    def test_trabajador_avanza_sin_boton_evaluar_ni_pantalla_abierta(self):
        self.preparar()

        def esperar(condicion):
            limite = time.monotonic() + 3
            while time.monotonic() < limite:
                if condicion():
                    return
                time.sleep(0.05)
            self.fail(
                "El trabajador no avanzó la simulación dentro del plazo de prueba"
            )

        with patch.object(sim, "ciclo", self.tick):
            esperar(lambda: self.estado()["total"] == 1)
            self.id = self.estado()["compras"][0]["pedido_id"]
            self.pagar()

            fecha = sim.ahora()
            with patch.object(sim, "ahora", return_value=fecha + timedelta(seconds=6)):
                esperar(lambda: self.estado()["compras"][0]["estado"] == "listo")
            with patch.object(sim, "ahora", return_value=fecha + timedelta(seconds=12)):
                esperar(lambda: self.estado()["compras"][0]["estado"] == "despachado")
        self.assertEqual(self.estado()["fondo"]["pagado_centavos"], 150150)

    def test_no_superpone_regla_individual_ni_cambia_producto_con_pedido_abierto(self):
        self.generar()
        self.solicitar(
            "PUT",
            "/reposicion-simulada/configuracion",
            409,
            json={"producto_id": 1, "activa": True},
        )
        self.solicitar(
            "PUT",
            "/productos/1/regla-reposicion",
            json={
                "activa": True,
                "modo": "aviso",
                "minimo": 1,
                "objetivo": 3,
                "alertar_desde": 2,
                "multiplo": 1,
                "max_unidades": 3,
                "importe_max_centavos": 300000,
            },
        )
        self.solicitar(
            "PUT",
            "/reposicion-simulada/configuracion",
            409,
            json={"producto_id": 1, "activa": True},
        )

    def test_no_reutiliza_disponibilidad_del_proveedor_ya_recibida(self):
        self.generar()
        self.pagar()
        self.avanzar()
        self.recibir()
        self.solicitar(
            "PUT",
            "/ventas/agotar-prueba",
            auth=self.consulta,
            json={"producto_id": self.producto, "cantidad": 3},
        )
        self.solicitar(
            "PUT",
            "/reposicion-simulada/aportes/segundo-aporte",
            json={"importe_centavos": 200000},
        )
        self.ciclo()
        self.assertEqual(self.estado()["total"], 1)
        self.publicar(stock=6)
        self.ciclo()
        self.assertEqual(self.estado()["total"], 2)
        self.assertEqual(self.estado()["fondo"]["reservado_centavos"], 150150)

    def test_actualizacion_agrega_tablas_sin_alterar_productos_existentes(self):
        before = self.solicitar("GET", "/productos/1")
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            for tabla in [
                "compras_reposicion_simulada",
                "aportes_reposicion_simulada",
                "simulacion_reposicion",
            ]:
                db.execute("DROP TABLE " + tabla)
        for _ in range(2):
            sim.instalar(repositorio_sqlite.conectar_db)
        self.assertEqual(self.solicitar("GET", "/productos/1"), before)
        self.assertEqual(self.estado()["fondo"]["disponible_centavos"], 0)
        self.assertFalse(self.estado()["configuracion"]["activa"])

    def test_preparar_ejemplo_es_atomico_y_no_duplica_ni_resetea_datos(self):
        antes = self.solicitar("GET", "/productos/1")
        ejemplo = self.solicitar("PUT", "/reposicion-simulada/ejemplo")
        self.producto = ejemplo["producto"]["id"]
        self.assertEqual(self.estado()["producto"]["stock"], 0)
        self.assertTrue(self.estado()["configuracion"]["activa"])
        self.ciclo()
        self.assertEqual(self.estado()["total"], 0)
        self.solicitar(
            "PUT",
            "/reposicion-simulada/aportes/ejemplo-aporte",
            json={"importe_centavos": 200000},
        )
        self.ciclo()
        self.id = self.estado()["compras"][0]["pedido_id"]
        self.pagar()
        self.avanzar()
        self.assertEqual(self.estado()["compras"][0]["proveedor"], "simulado")
        self.solicitar(
            "PUT",
            f"/pedidos/{self.id}/recepciones/ejemplo",
            json={"cantidad": 3, "costo_pagado_centavos": 50050},
        )
        repetido = self.solicitar("PUT", "/reposicion-simulada/ejemplo")
        self.assertTrue(repetido["ya_preparado"])
        self.assertEqual(repetido["producto"]["id"], self.producto)
        self.assertEqual(repetido["producto"]["stock"], 3)
        self.assertEqual(self.estado()["total"], 1)
        self.assertEqual(self.estado()["fondo"]["pagado_centavos"], 150150)
        self.assertEqual(self.solicitar("GET", "/productos/1"), antes)
        self.solicitar("PUT", "/reposicion-simulada/ejemplo", 403, auth=self.consulta)
