"""Regression tests: interfaz abastecimiento."""

from contextlib import closing
from unittest import TestCase
import test_regresion
import repositorio_sqlite

WEB = {"X-Interfaz-Web": "1"}


class InterfazAbastecimiento(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def cuenta(self, nombre, rol, proveedor=None):
        datos = {"usuario": nombre, "clave": "PruebaSegura123", "rol": rol}
        if proveedor:
            datos["proveedor"] = proveedor
        self.solicitar("POST", "/usuarios", 201, json=datos)
        return (nombre, "PruebaSegura123")

    def preparar(self):
        self.proveedor = self.cuenta("proveedor_web", "proveedor", "demo")
        self.otro = self.cuenta("otro_proveedor_web", "proveedor", "demo-b")
        self.empleado = self.cuenta("empleado_web", "empleado")
        self.producto = self.solicitar(
            "POST",
            "/productos",
            201,
            json={
                "nombre": "Prueba abastecimiento web",
                "marca": "Demo",
                "categoria": "tecnologia",
                "precio": 1000,
                "stock": 0,
            },
        )["id"]
        self.oferta = {
            "id": "web-abast-1",
            "nombre": "Prueba abastecimiento web",
            "marca": "Demo",
            "categoria": "tecnologia",
            "precio": "500.50",
            "stock": 3,
        }
        self.solicitar(
            "PUT",
            "/mi-proveedor/catalogo",
            auth=self.proveedor,
            json={"productos": [self.oferta]},
            headers=WEB,
        )
        self.solicitar(
            "PUT",
            "/proveedores/demo/ofertas/web-abast-1/vinculo",
            json={"producto_id": self.producto},
            headers=WEB,
        )
        self.id = self.solicitar(
            "POST", f"/productos/{self.producto}/reposicion", headers=WEB
        )["pedido"]["id"]
        return self.id

    def stock(self):
        return self.solicitar("GET", f"/productos/{self.producto}")["stock"]

    def recibir(self, ref="remito-web-1", cantidad=1, costo=50050, codigo=200):
        return self.solicitar(
            "PUT",
            f"/pedidos/{self.id}/recepciones/{ref}",
            codigo,
            auth=self.empleado,
            json={"cantidad": cantidad, "costo_pagado_centavos": costo},
            headers=WEB,
        )

    def test_publicar_vincular_avisar_y_recibir_parcial_sin_duplicar_stock(self):
        self.preparar()
        sesion = self.solicitar("GET", "/sesion", auth=self.proveedor, headers=WEB)
        self.assertEqual(
            (sesion["rol_efectivo"], sesion["proveedor"]), ("proveedor", "demo")
        )
        self.assertEqual(self.stock(), 0)
        aviso = {"estado": "despachado", "nota": "Se despachan tres unidades"}
        path = f"/mi-proveedor/pedidos/{self.id}/avisos/aviso-web-1"
        for _ in range(2):
            self.solicitar("PUT", path, auth=self.proveedor, json=aviso, headers=WEB)
        self.assertEqual(self.stock(), 0)
        self.assertEqual(
            self.solicitar(
                "GET", f"/abastecimiento/pedidos/{self.id}/avisos", auth=self.empleado
            )["total"],
            1,
        )
        for _ in range(2):
            self.recibir()
        self.assertEqual(self.stock(), 1)
        context = self.solicitar(
            "GET", f"/abastecimiento/pedidos/{self.id}", auth=self.empleado
        )
        self.assertEqual(context["pedido"]["estado"], "parcial")
        self.assertNotIn("corregir", context["acciones"])
        self.recibir("remito-web-2", 2)
        self.recibir("remito-web-2", 2)
        self.assertEqual(self.stock(), 3)
        self.assertEqual(
            self.solicitar("GET", f"/abastecimiento/pedidos/{self.id}/remitos")[
                "total"
            ],
            2,
        )
        self.assertEqual(
            self.solicitar("GET", f"/abastecimiento/pedidos/{self.id}")["pedido"][
                "costo_pagado_centavos"
            ],
            50050,
        )
        self.assertEqual(
            self.solicitar(
                "GET", f"/mi-proveedor/pedidos/{self.id}", auth=self.proveedor
            )["acciones_aviso"],
            [],
        )
        self.solicitar("PUT", path, auth=self.proveedor, json=aviso)
        self.solicitar("PUT", path + "-nuevo", 409, auth=self.proveedor, json=aviso)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)

    def test_recibir_no_permite_cambiar_remito_repetido_ni_superar_pendiente(self):
        self.preparar()
        self.recibir()
        self.recibir(cantidad=2, codigo=409)
        self.recibir("exceso", 3, codigo=409)
        self.assertEqual(self.stock(), 1)

    def test_correccion_parcial_auditada_con_reintento_y_cierre_con_faltantes(self):
        self.preparar()
        self.recibir()
        path = (
            f"/pedidos/{self.id}/recepciones/remito-web-1/correcciones/correccion-web-1"
        )
        data = {
            "cantidad": 2,
            "costo_pagado_centavos": 50125,
            "motivo": "Conteo y factura corregidos",
        }
        for _ in range(2):
            self.solicitar("PUT", path, json=data, headers=WEB)
        self.assertEqual(self.stock(), 2)
        history = self.solicitar(
            "GET",
            f"/auditoria/comercial/pedido_proveedor/{self.id}",
            auth=self.empleado,
        )
        self.assertIn("correccion", str(history).lower())
        self.solicitar("PUT", f"/pedidos/{self.id}/cierre-incompleto", headers=WEB)
        p = self.solicitar("GET", f"/abastecimiento/pedidos/{self.id}")["pedido"]
        self.assertEqual(
            (p["estado"], p["cantidad_no_entregada"]), ("cerrado_incompleto", 1)
        )
        self.assertEqual(self.stock(), 2)
        self.recibir("tarde", 1, 50125, codigo=409)

    def test_cancelacion_pendiente_no_mueve_stock_y_quita_acciones(self):
        self.preparar()
        self.solicitar("PUT", f"/pedidos/{self.id}/cancelacion", headers=WEB)
        p = self.solicitar("GET", f"/abastecimiento/pedidos/{self.id}")
        self.assertEqual(p["pedido"]["estado"], "cancelado")
        self.assertNotIn("recibir", p["acciones"])
        self.assertEqual(self.stock(), 0)

    def test_permisos_y_titularidad_en_todas_las_acciones(self):
        self.preparar()
        for suffix in ["", "/avisos"]:
            self.solicitar(
                "GET",
                f"/mi-proveedor/pedidos/{self.id}" + suffix,
                404,
                auth=self.otro,
                headers=WEB,
            )
        self.solicitar("GET", "/abastecimiento/pedidos", 403, auth=self.proveedor)
        for path, data in [
            (f"/pedidos/{self.id}/cancelacion", None),
            (f"/pedidos/{self.id}/cierre-incompleto", None),
            (
                f"/pedidos/{self.id}/recepciones/r/correcciones/c",
                {"cantidad": 1, "costo_pagado_centavos": 50050, "motivo": "Prueba"},
            ),
        ]:
            self.solicitar("PUT", path, 403, auth=self.empleado, json=data, headers=WEB)
        self.solicitar(
            "PUT",
            f"/pedidos/{self.id}/recepciones/r",
            403,
            auth=self.proveedor,
            json={"cantidad": 1, "costo_pagado_centavos": 50050},
        )
        self.solicitar(
            "PUT",
            "/mi-proveedor/catalogo",
            403,
            auth=self.empleado,
            json={"productos": []},
        )
        self.solicitar(
            "PUT",
            "/proveedores/demo/ofertas/web-abast-1/vinculo",
            403,
            auth=self.empleado,
            json={"producto_id": self.producto},
        )
        self.solicitar("GET", "/proveedores/demo-b/ofertas", 404, auth=self.proveedor)
        self.assertEqual(self.stock(), 0)

    def test_catalogo_completo_conserva_incluidas_y_desactiva_solo_omitidas(self):
        self.preparar()
        second = {**self.oferta, "id": "otro-codigo", "nombre": "Otra oferta"}
        self.solicitar(
            "PUT",
            "/mi-proveedor/catalogo",
            auth=self.proveedor,
            json={"productos": [self.oferta, second]},
        )
        offers = self.solicitar("GET", "/proveedores/demo/ofertas")
        self.assertTrue(all(o["vigente"] for o in offers))
        self.assertEqual(len(offers), 2)
        self.solicitar(
            "PUT",
            "/mi-proveedor/catalogo",
            auth=self.proveedor,
            json={"productos": [self.oferta]},
        )
        offers = {
            x["id_externo"]: x
            for x in self.solicitar("GET", "/proveedores/demo/ofertas")
        }
        self.assertEqual(offers["web-abast-1"]["producto_id"], self.producto)
        self.assertTrue(offers["web-abast-1"]["vigente"])
        self.assertFalse(offers["otro-codigo"]["vigente"])

    def test_filtros_y_paginacion_del_proveedor_aislan_antes_de_paginar(self):
        self.preparar()
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.executemany(
                "INSERT INTO pedidos_reposicion(producto_id,proveedor,id_externo,cantidad,costo_ofertado_centavos) VALUES (?,?,?,?,?)",
                [(self.producto, "demo-b", "ajeno", 1, 50050)] * 12,
            )
        own = self.solicitar(
            "GET",
            "/mi-proveedor/pedidos?filtro=todos&pagina=1&limite=10",
            auth=self.proveedor,
        )
        self.assertEqual(own["total"], 1)
        self.assertEqual(own["pedidos"][0]["id"], self.id)
        self.solicitar("PUT", f"/pedidos/{self.id}/cancelacion")
        self.assertEqual(
            self.solicitar(
                "GET", "/mi-proveedor/pedidos?filtro=abiertos", auth=self.proveedor
            )["total"],
            0,
        )

    def test_evaluar_dos_veces_recupera_el_mismo_pedido_abierto(self):
        self.preparar()
        result = self.solicitar(
            "POST", f"/productos/{self.producto}/reposicion", headers=WEB
        )
        self.assertEqual(result["estado"], "pedido_pendiente")
        self.assertEqual(result["pedido"]["id"], self.id)
        self.assertEqual(self.solicitar("GET", "/abastecimiento/pedidos")["total"], 1)
