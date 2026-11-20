"""Regression tests: interfaz web."""

from unittest import TestCase
import test_regresion

WEB = {"X-Interfaz-Web": "1"}


class InterfazWeb(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def test_archivos_publicos_solo_en_directorio_interfaz(self):
        r = self.cliente.get("/", follow_redirects=False)
        self.assertEqual(r.status_code, 307)
        self.assertEqual(r.headers["location"], "/interfaz/")
        for path, mime in [
            ("/interfaz/", "text/html"),
            ("/interfaz/app.js", "javascript"),
            ("/interfaz/i18n.js", "javascript"), ("/interfaz/messages.js", "javascript"),
            ("/interfaz/ventas_caja.js", "javascript"),
            ("/interfaz/devoluciones_web.js", "javascript"),
            ("/interfaz/entregas_atencion.js", "javascript"),
            ("/interfaz/cliente_web.js", "javascript"),
            ("/interfaz/abastecimiento_web.js", "javascript"),
            ("/interfaz/reposicion_simulada.js", "javascript"),
            ("/interfaz/estilos.css", "text/css"),
        ]:
            response = self.cliente.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(mime, response.headers["content-type"])
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertIn(
                "connect-src 'self'", response.headers["content-security-policy"]
            )
        self.assertEqual(self.cliente.get("/interfaz/servidor.py").status_code, 404)

    def test_login_web_sin_dialogo_basico_y_api_compatible(self):
        normal = self.cliente.get("/sesion")
        web = self.cliente.get("/sesion", headers=WEB)
        self.assertEqual(normal.status_code, 401)
        self.assertEqual(web.status_code, 401)
        self.assertIn("www-authenticate", normal.headers)
        self.assertNotIn("www-authenticate", web.headers)
        self.assertEqual(web.headers["cache-control"], "no-store")
        ok = self.cliente.get("/sesion", auth=self.compras, headers=WEB)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["rol_efectivo"], "administrador")
        self.assertNotIn("clave_hash", ok.text)

    def test_recorrido_lectura_no_cambia_stock_ni_auditoria(self):
        before = self.solicitar("GET", "/productos/1")
        history = self.solicitar("GET", "/auditoria/comercial/producto/1")["total"]
        products = self.solicitar(
            "GET",
            "/productos?texto=Mouse&categoria=tecnologia&pagina=1&limite=10",
            headers=WEB,
        )
        self.assertEqual(products["total"], 1)
        id = products["productos"][0]["id"]
        context = self.solicitar("GET", f"/operaciones/productos/{id}", headers=WEB)
        self.assertEqual(context["producto"], before)
        self.solicitar(
            "GET",
            f"/inventario/movimientos?producto_id={id}&pagina=1&limite=10",
            headers=WEB,
        )
        self.solicitar(
            "GET", f"/auditoria/comercial/producto/{id}?pagina=1&limite=10", headers=WEB
        )
        self.assertEqual(before, self.solicitar("GET", "/productos/1"))
        self.assertEqual(
            history, self.solicitar("GET", "/auditoria/comercial/producto/1")["total"]
        )

    def test_cabecera_web_no_otorga_permisos(self):
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={
                "usuario": "operador_web",
                "rol": "empleado",
                "clave": "PruebaSegura123",
            },
        )
        employee = ("operador_web", "PruebaSegura123")
        context = self.solicitar(
            "GET", "/operaciones/productos/1", auth=employee, headers=WEB
        )
        self.assertEqual(context["acciones"], ["detalle", "movimientos"])
        self.solicitar(
            "GET", "/inventario/movimientos?producto_id=1", auth=employee, headers=WEB
        )
        self.solicitar(
            "PATCH", "/productos/1", 403, auth=employee, headers=WEB, json={"precio": 1}
        )
        self.solicitar(
            "GET", "/auditoria/comercial/producto/1", 403, auth=employee, headers=WEB
        )
        self.assertEqual(self.solicitar("GET", "/productos/1")["precio"], 8500)

    def test_contrasena_temporal_bloquea_catalogo_hasta_cambio(self):
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={
                "usuario": "temporal_web",
                "rol": "empleado",
                "clave": "PruebaSegura123",
            },
        )
        self.solicitar(
            "PUT",
            "/usuarios/temporal_web/restablecimientos/web-prueba",
            json={"temporal": "TemporalSegura456", "motivo": "Prueba de interfaz"},
        )
        auth = ("temporal_web", "TemporalSegura456")
        self.assertTrue(
            self.solicitar("GET", "/sesion", auth=auth, headers=WEB)[
                "debe_cambiar_clave"
            ]
        )
        self.solicitar("GET", "/productos", 403, auth=auth, headers=WEB)
        self.solicitar(
            "PUT",
            "/mi-cuenta/clave",
            auth=auth,
            headers=WEB,
            json={"actual": auth[1], "nueva": "DefinitivaSegura789"},
        )
        self.solicitar("GET", "/sesion", 401, auth=auth, headers=WEB)
        self.solicitar(
            "GET",
            "/productos",
            auth=("temporal_web", "DefinitivaSegura789"),
            headers=WEB,
        )

    def test_editar_solo_precio_no_modifica_stock(self):
        before = self.solicitar("GET", "/productos/1")["stock"]
        response = self.solicitar(
            "PATCH", "/productos/1", json={"precio": 9000}, headers=WEB
        )
        self.assertEqual(response["stock"], before)
        self.assertEqual(response["precio"], 9000)
        history = self.solicitar("GET", "/auditoria/comercial/producto/1")[
            "movimientos"
        ]
        self.assertIn("precio", str(history))


if __name__ == "__main__":
    import unittest

    unittest.main()
