"""Regression tests: usuarios."""

import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase
from unittest.mock import patch
import test_regresion
import preparar_db_api
import repositorio_sqlite


class Usuarios(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar
    importar_oferta = test_regresion.RegresionInventario.importar_oferta

    def alta(self, nombre, rol="cliente", proveedor=None):
        datos = {"usuario": nombre, "clave": "PruebaSegura123", "rol": rol}
        if rol == "cliente":
            datos["cliente"] = {
                "nombre": nombre.title(),
                "apellido": "Prueba",
                "correo": nombre + "@example.com",
            }
        if proveedor:
            datos["proveedor"] = proveedor
        r = self.solicitar("POST", "/usuarios", 201, json=datos)
        return (nombre, "PruebaSegura123"), r

    def online(self, auth, ref="online-1", **otros):
        return self.solicitar(
            "PUT",
            "/cobros-demo/" + ref,
            auth=auth,
            json={
                "productos": [{"producto_id": 1, "cantidad": 1}],
                "canal": "online",
                "modalidad": "retiro",
                **otros,
            },
        )

    def test_cuentas_individuales_y_hash_no_expuesto(self):
        ana, r = self.alta("ana")
        self.assertIsNotNone(r["cliente_id"])
        sesion = self.solicitar("GET", "/sesion", auth=ana)
        self.assertEqual(sesion["rol"], "cliente")
        self.assertEqual(
            self.solicitar("GET", "/mi-perfil", auth=ana)["cliente"][
                "correo_verificado"
            ],
            0,
        )
        with closing(repositorio_sqlite.conectar_db()) as db:
            guardada = db.execute(
                "SELECT clave_hash FROM usuarios WHERE usuario=?", ("ana",)
            ).fetchone()[0]
        self.assertNotIn(ana[1], guardada)
        self.assertTrue(guardada.startswith("scrypt$"))
        listado = self.solicitar("GET", "/usuarios")
        self.assertNotIn("clave_hash", str(listado))
        self.assertNotIn(ana[1], str(listado))
        self.solicitar("GET", "/sesion", 401, auth=("ana", "incorrecta"))

    def test_cliente_solo_sus_pedidos_pago_y_ticket_incluso_paginacion(self):
        ana, _ = self.alta("ana")
        otro, _ = self.alta("bruno")
        uno = self.online(ana)
        dos = self.online(otro, "otro")
        self.online(ana, "segundo")
        total = self.solicitar("GET", "/pedidos-venta?limite=1", auth=ana)
        self.assertEqual(total["total"], 2)
        self.assertEqual(len(total["pedidos"]), 1)
        id = uno["pedido_venta_id"]
        self.solicitar(
            "PUT", "/cobros-demo/online-1/pago", auth=ana, json={"estado": "aprobado"}
        )
        self.solicitar("GET", f"/pedidos-venta/{id}", auth=ana)
        self.assertEqual(
            self.cliente.get(f"/pedidos-venta/{id}/ticket", auth=ana).status_code, 200
        )
        for ruta in [
            f"/pedidos-venta/{id}",
            f"/pedidos-venta/{id}/ticket",
            "/cobros-demo/online-1",
        ]:
            self.solicitar("GET", ruta, 404, auth=otro)
        for sufijo, datos in [
            ("pago", {"estado": "rechazado"}),
            ("eventos/ajeno", {"estado": "cancelado"}),
            ("conexion", {"disponible": False}),
            ("devolucion", None),
        ]:
            self.solicitar(
                "PUT", "/cobros-demo/online-1/" + sufijo, 404, auth=otro, json=datos
            )
        self.assertEqual(self.solicitar("GET", "/pedidos-venta", auth=otro)["total"], 1)
        self.assertNotEqual(id, dos["pedido_venta_id"])

    def test_colision_referencia_no_reasigna_ni_informa_compra_ajena(self):
        ana, _ = self.alta("ana")
        bruno, _ = self.alta("bruno")
        self.online(ana)
        self.solicitar(
            "PUT",
            "/cobros-demo/online-1",
            404,
            auth=bruno,
            json={
                "productos": [{"producto_id": 1, "cantidad": 1}],
                "canal": "online",
                "modalidad": "retiro",
            },
        )
        self.assertEqual(
            self.solicitar("GET", "/pedidos-venta", auth=bruno)["total"], 0
        )
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)

    def test_colision_concurrente_clientes_distintos(self):
        ana, _ = self.alta("ana")
        bruno, _ = self.alta("bruno")
        datos = {
            "productos": [{"producto_id": 1, "cantidad": 1}],
            "canal": "online",
            "modalidad": "retiro",
        }
        with ThreadPoolExecutor(max_workers=2) as ex:
            r = list(
                ex.map(
                    lambda auth: self.cliente.put(
                        "/cobros-demo/colision", auth=auth, json=datos
                    ),
                    [ana, bruno],
                )
            )
        self.assertEqual(sorted(x.status_code for x in r), [200, 404])
        self.assertEqual(
            sum(
                self.solicitar("GET", "/pedidos-venta", auth=a)["total"]
                for a in [ana, bruno]
            ),
            1,
        )

    def test_cliente_no_puede_atribuirse_otra_identidad_ni_descontar_sin_pagar(self):
        ana, _ = self.alta("ana")
        base = {
            "productos": [{"producto_id": 1, "cantidad": 1}],
            "canal": "online",
            "modalidad": "retiro",
        }
        self.solicitar(
            "PUT", "/cobros-demo/falso", 422, auth=ana, json={**base, "cliente_id": 999}
        )
        self.solicitar(
            "PUT",
            "/ventas/falso",
            403,
            auth=ana,
            json={"producto_id": 1, "cantidad": 1},
        )
        self.solicitar(
            "PUT",
            "/cobros-demo/presencial",
            422,
            auth=ana,
            json={"productos": base["productos"]},
        )
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)

    def test_venta_anonima_conserva_empleado_turno_pago_y_cliente_nulo(self):
        empleado, _ = self.alta("maxi", "empleado")
        ana, _ = self.alta("ana")
        self.solicitar(
            "PUT",
            "/cajas/turno-prueba/apertura",
            auth=empleado,
            json={"fondo_inicial": 1000},
        )
        datos = {
            "caja": "turno-prueba",
            "recibido": 10000,
            "productos": [{"producto_id": 1, "cantidad": 1}],
        }
        venta = self.solicitar(
            "PUT", "/ventas-efectivo/anonima", auth=empleado, json=datos
        )
        detalle = self.solicitar(
            "GET", f'/pedidos-venta/{venta["pedido_venta_id"]}', auth=empleado
        )
        self.assertIsNone(detalle["cliente_id"])
        self.assertEqual(detalle["registrado_por"], "maxi")
        self.assertEqual(detalle["identificacion_cliente"], "sin_identificar")
        self.assertEqual(
            detalle["efectivo"],
            {"caja": "turno-prueba", "recibido": 10000, "vuelto": 1500},
        )
        self.assertEqual(detalle["medio_pago"], "efectivo")
        self.solicitar(
            "GET", f'/pedidos-venta/{venta["pedido_venta_id"]}', 404, auth=ana
        )
        self.assertEqual(self.solicitar("GET", "/pedidos-venta", auth=ana)["total"], 0)
        self.assertEqual(
            self.solicitar(
                "PUT", "/ventas-efectivo/anonima", auth=empleado, json=datos
            ),
            venta,
        )
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)

    def test_no_se_asignan_historicos_al_migrar(self):
        ana, _ = self.alta("ana")
        venta = self.solicitar(
            "PUT",
            "/ventas/historica",
            auth=self.consulta,
            json={"producto_id": 1, "cantidad": 1},
        )
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.execute("DELETE FROM titulares_pedido")
        preparar_db_api.preparar_db_api()
        preparar_db_api.preparar_db_api()
        r = self.solicitar("GET", f'/pedidos-venta/{venta["pedido_venta_id"]}')
        self.assertIsNone(r["cliente_id"])
        self.assertIsNone(r["registrado_por"])
        self.assertEqual(self.solicitar("GET", "/pedidos-venta", auth=ana)["total"], 0)
        self.solicitar(
            "GET", f'/pedidos-venta/{venta["pedido_venta_id"]}', 404, auth=self.consulta
        )

    def test_permisos_empleado_prohiben_administracion_y_retiros(self):
        empleado, _ = self.alta("maxi", "empleado")
        for metodo, ruta, datos in [
            ("POST", "/usuarios", {}),
            ("POST", "/productos", {}),
            ("PATCH", "/productos/1", {"stock": 0}),
            ("DELETE", "/productos/1", None),
            ("PUT", "/productos/1/regla-reposicion", {}),
            ("POST", "/proveedores/demo/importar", None),
            ("POST", "/reposicion-automatica/evaluar", None),
            (
                "PUT",
                "/cajas/turno/movimientos/retiro",
                {"tipo": "retiro", "importe": 10, "motivo": "prueba"},
            ),
        ]:
            self.solicitar(metodo, ruta, 403, auth=empleado, json=datos)
        self.solicitar("GET", "/usuarios", 403, auth=empleado)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)

    def test_cliente_no_puede_operar_el_negocio(self):
        ana, _ = self.alta("ana")
        for ruta in [
            "/usuarios",
            "/pedidos",
            "/ventas",
            "/fondo-emergencias",
            "/inventario/movimientos",
            "/reposiciones-emergencia",
            "/cajas",
        ]:
            self.solicitar("GET", ruta, 403, auth=ana)
        self.solicitar(
            "PUT", "/usuarios/ana/estado", 403, auth=ana, json={"activo": True}
        )

    def test_desactivar_y_cambiar_clave_revalida_cada_peticion(self):
        ana, _ = self.alta("ana")
        self.solicitar(
            "PUT",
            "/mi-cuenta/clave",
            409,
            auth=ana,
            json={"actual": "mala", "nueva": "NuevaSegura123"},
        )
        self.solicitar(
            "PUT",
            "/mi-cuenta/clave",
            auth=ana,
            json={"actual": ana[1], "nueva": "NuevaSegura123"},
        )
        self.solicitar("GET", "/sesion", 401, auth=ana)
        ana = ("ana", "NuevaSegura123")
        self.solicitar("GET", "/sesion", auth=ana)
        self.solicitar("PUT", "/usuarios/ana/estado", json={"activo": False})
        self.solicitar("GET", "/sesion", 401, auth=ana)
        self.solicitar("PUT", "/usuarios/ana/estado", json={"activo": True})
        self.solicitar("GET", "/sesion", auth=ana)

    def test_alta_atomica_y_campos_estrictos(self):
        datos = {
            "usuario": "ana",
            "clave": "PruebaSegura123",
            "rol": "cliente",
            "cliente": {
                "nombre": "Ana",
                "apellido": "Prueba",
                "correo": "ana@example.com",
            },
        }
        self.solicitar("POST", "/usuarios", 201, json=datos)
        self.solicitar("POST", "/usuarios", 409, json=datos)
        for cambios in [
            {"usuario": "consulta"},
            {"usuario": "otra", "clave": "corta"},
            {"usuario": "otra", "clave": "ContraseñaNoASCII"},
            {"usuario": "otra", "cliente": None},
            {"usuario": "otra", "rol": "administrador"},
            {"usuario": "otra", "tarjeta": "1234"},
        ]:
            self.solicitar("POST", "/usuarios", 422, json={**datos, **cambios})
        with closing(repositorio_sqlite.conectar_db()) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM clientes").fetchone()[0], 1
            )

    def test_snapshot_contacto_y_direccion_conservados(self):
        ana, r = self.alta("ana")
        self.solicitar(
            "PUT",
            "/cobros-demo/sin-direccion",
            422,
            auth=ana,
            json={
                "productos": [{"producto_id": 1, "cantidad": 1}],
                "canal": "online",
                "modalidad": "envio",
            },
        )
        pedido = self.online(
            ana, modalidad="envio", direccion_entrega="Calle de prueba 123, ciudad"
        )
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.execute(
                "UPDATE clientes SET nombre=?,correo=? WHERE id=?",
                ("Nuevo", "nuevo@example.com", r["cliente_id"]),
            )
        detalle = self.solicitar(
            "GET", f'/pedidos-venta/{pedido["pedido_venta_id"]}', auth=ana
        )
        self.assertEqual(detalle["cliente_al_comprar"]["nombre"], "Ana")
        self.assertEqual(detalle["direccion_entrega"], "Calle de prueba 123, ciudad")
        self.solicitar(
            "PUT",
            "/cobros-demo/online-1",
            409,
            auth=ana,
            json={
                "productos": [{"producto_id": 1, "cantidad": 1}],
                "canal": "online",
                "modalidad": "envio",
                "direccion_entrega": "Otra calle 999",
            },
        )

    def test_solicitud_cliente_no_reintegra_ni_repone(self):
        ana, _ = self.alta("ana")
        otro, _ = self.alta("bruno")
        id = self.online(ana)["pedido_venta_id"]
        datos = {"tipo": "cancelacion", "motivo": "Cambio de planes"}
        self.solicitar(
            "PUT", f"/pedidos-venta/{id}/solicitudes/sol-1", 409, auth=ana, json=datos
        )
        self.solicitar(
            "PUT", "/cobros-demo/online-1/pago", auth=ana, json={"estado": "aprobado"}
        )
        r = self.solicitar(
            "PUT", f"/pedidos-venta/{id}/solicitudes/sol-1", auth=ana, json=datos
        )
        self.assertEqual(
            self.solicitar(
                "PUT", f"/pedidos-venta/{id}/solicitudes/sol-1", auth=ana, json=datos
            ),
            r,
        )
        self.solicitar(
            "PUT", f"/pedidos-venta/{id}/solicitudes/sol-2", 404, auth=otro, json=datos
        )
        self.assertEqual(
            self.solicitar("GET", "/solicitudes-clientes", auth=otro)["total"], 0
        )
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 6)
        self.assertEqual(
            self.solicitar("GET", f"/pedidos-venta/{id}", auth=ana)["devoluciones"][
                "importe_reintegrado"
            ],
            0,
        )

    def test_proveedor_solo_catalogo_y_pedidos_propios_no_ventas(self):
        proveedor, _ = self.alta("proveedor_a", "proveedor", "demo")
        self.importar_oferta("demo", "1200.00")
        self.importar_oferta("demo-b", "1300.00")
        self.solicitar("GET", "/proveedores/demo/ofertas", auth=proveedor)
        self.solicitar("GET", "/proveedores/demo-b/ofertas", 404, auth=proveedor)
        self.solicitar("GET", "/pedidos-venta", 403, auth=proveedor)
        self.solicitar("GET", "/pedidos-venta/1", 403, auth=proveedor)
        self.solicitar("GET", "/ventas", 403, auth=proveedor)
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.executemany(
                "INSERT INTO pedidos_reposicion(producto_id,proveedor,id_externo,cantidad,costo_ofertado_centavos) VALUES (1,?,?,2,120000)",
                [("demo", "0012"), ("demo-b", "0012")],
            )
        self.assertEqual(len(self.solicitar("GET", "/pedidos", auth=proveedor)), 1)
        self.solicitar("GET", "/pedidos/2", 404, auth=proveedor)
        self.solicitar(
            "PUT",
            "/pedidos/1/recepciones/remito",
            403,
            auth=proveedor,
            json={"cantidad": 2, "costo_pagado_centavos": 120000},
        )
        r = self.solicitar(
            "PUT",
            "/mi-proveedor/pedidos/1/avisos/envio-1",
            auth=proveedor,
            json={"estado": "despachado", "nota": "Sale hoy"},
        )
        self.assertIn("recepción física", r["mensaje"])
        self.solicitar(
            "PUT",
            "/mi-proveedor/pedidos/2/avisos/envio-1",
            404,
            auth=proveedor,
            json={"estado": "despachado", "nota": "Ajeno"},
        )
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)

    def test_proveedor_publica_sin_alterar_catalogo_ajeno_y_refresh_respeta_fuente(
        self,
    ):
        proveedor, _ = self.alta("proveedor_a", "proveedor", "demo")
        self.importar_oferta("demo-b", "1200.00")
        datos = {
            "productos": [
                {
                    "id": "0012",
                    "nombre": "Mouse",
                    "marca": "TecnoSur",
                    "categoria": "tecnologia",
                    "precio": "1400.00",
                    "stock": 3,
                }
            ]
        }
        r = self.solicitar("PUT", "/mi-proveedor/catalogo", auth=proveedor, json=datos)
        self.assertEqual(r["nuevas"], 1)
        self.assertEqual(
            self.solicitar("GET", "/proveedores/demo-b/ofertas")[0]["costo_centavos"],
            120000,
        )
        self.solicitar(
            "PUT",
            "/mi-proveedor/catalogo",
            422,
            auth=proveedor,
            json={**datos, "proveedor": "demo-b"},
        )
        self.solicitar(
            "PUT", "/proveedores/demo/ofertas/0012/vinculo", json={"producto_id": 1}
        )
        self.solicitar(
            "PUT",
            "/productos/1/regla-reposicion",
            json={
                "activa": True,
                "modo": "aviso",
                "minimo": 5,
                "objetivo": 10,
                "alertar_desde": 7,
                "multiplo": 1,
                "max_unidades": 20,
                "importe_max_centavos": 1000000,
            },
        )
        from reposicion_automatica import actualizar_catalogos

        with patch("catalogos.descargar_catalogo") as descargar:
            actualizar_catalogos(repositorio_sqlite.conectar_db)
            descargar.assert_not_called()

    def test_sesion_ofrece_solo_opciones_habilitadas(self):
        empleado, _ = self.alta("maxi", "empleado")
        admin, _ = self.alta("jefe", "administrador")
        self.assertIn(
            "20", self.solicitar("GET", "/sesion", auth=empleado)["opciones_operativas"]
        )
        self.assertNotIn(
            "24", self.solicitar("GET", "/sesion", auth=empleado)["opciones_operativas"]
        )
        self.assertIn(
            "31", self.solicitar("GET", "/sesion", auth=admin)["opciones_operativas"]
        )
        self.solicitar(
            "PUT", "/usuarios/jefe/estado", 409, auth=admin, json={"activo": False}
        )

    def test_publicacion_solicitud_resolucion_y_adjunto_no_saltan_autorizacion(self):
        ana, _ = self.alta("ana")
        empleado, _ = self.alta("maxi", "empleado")
        for metodo, ruta, datos in [
            ("PUT", "/mi-proveedor/catalogo", {"productos": []}),
            (
                "PUT",
                "/solicitudes-clientes/1/ref/resolucion",
                {"estado": "atendida", "motivo": "prueba"},
            ),
            (
                "PUT",
                "/reposiciones-emergencia/ref/comprobante",
                {"nombre": "a.pdf", "contenido_base64": "QQ=="},
            ),
        ]:
            self.solicitar(metodo, ruta, 403, auth=ana, json=datos)

    def test_cliente_no_puede_simular_gestion_tecnica_de_pagos(self):
        ana, _ = self.alta("ana")
        self.online(ana)
        for sufijo, datos in [
            ("conexion", {"disponible": False}),
            ("eventos/tecnico", {"estado": "cancelado"}),
            ("devolucion", None),
        ]:
            self.solicitar(
                "PUT", "/cobros-demo/online-1/" + sufijo, 403, auth=ana, json=datos
            )

    def test_validacion_no_devuelve_password_ni_datos_en_input(self):
        datos = {
            "usuario": "ana",
            "clave": "SECRETO",
            "rol": "cliente",
            "cliente": {
                "nombre": "Ana",
                "apellido": "Prueba",
                "correo": "ana@example.com",
            },
        }
        r = self.cliente.post("/usuarios", auth=self.compras, json=datos)
        self.assertEqual(r.status_code, 422)
        self.assertNotIn("SECRETO", r.text)
        self.assertNotIn("input", r.text)

    def test_menu_crea_cuenta_y_acepta_respuesta_201(self):
        import menu_cuentas

        cliente, auth = self.cliente, self.compras

        class Sesion:
            def request(self, metodo, url, **datos):
                datos.pop("timeout", None)
                return cliente.request(metodo, url, auth=auth, **datos)

        with patch(
            "builtins.input",
            side_effect=["ana", "cliente", "Ana", "Prueba", "ana@example.com", "", "s"],
        ), patch("menu_cuentas.getpass", return_value="PruebaSegura123"), patch(
            "builtins.print"
        ) as salida:
            menu_cuentas.crear_cuenta(Sesion())
        self.assertIn("Cuenta creada", " ".join(str(x) for x in salida.call_args_list))
        self.solicitar("GET", "/sesion", auth=("ana", "PruebaSegura123"))

    def test_menu_empleado_no_muestra_acciones_de_administracion(self):
        import menu_api
        from autenticacion import OPCIONES_EMPLEADO

        with patch("builtins.input", side_effect=["2", "0", "0"]), patch(
            "builtins.print"
        ) as salida:
            menu_api.ejecutar_menu(None, "empleado", OPCIONES_EMPLEADO)
        texto = " ".join(str(x) for x in salida.call_args_list)
        self.assertIn("Cobrar venta en efectivo", texto)
        self.assertNotIn("Configurar reposición automática", texto)
        self.assertNotIn("Crear cuenta individual", texto)

    def test_solicitud_resolucion_por_empleado_sin_modificar_pago(self):
        ana, _ = self.alta("ana")
        empleado, _ = self.alta("maxi", "empleado")
        id = self.online(ana)["pedido_venta_id"]
        self.solicitar(
            "PUT", "/cobros-demo/online-1/pago", auth=ana, json={"estado": "aprobado"}
        )
        self.solicitar(
            "PUT",
            f"/pedidos-venta/{id}/solicitudes/ref",
            auth=ana,
            json={"tipo": "cancelacion", "motivo": "Consulta"},
        )
        self.solicitar(
            "PUT",
            f"/solicitudes-clientes/{id}/ref/resolucion",
            auth=empleado,
            json={"estado": "rechazada", "motivo": "Se coordina entrega"},
        )
        self.assertEqual(
            self.solicitar("GET", "/solicitudes-clientes", auth=ana)["solicitudes"][0][
                "estado"
            ],
            "rechazada",
        )
        self.assertEqual(
            self.solicitar("GET", f"/pedidos-venta/{id}", auth=ana)["estado_pago"],
            "aprobado",
        )

    def test_cuentas_compatibilidad_se_pueden_desactivar_sin_perder_admin_individual(
        self,
    ):
        import os

        admin, _ = self.alta("jefe", "administrador")
        with patch.dict(os.environ, {"CRUD_CUENTAS_COMPATIBILIDAD": "0"}):
            self.solicitar("GET", "/sesion", 401, auth=self.compras)
            self.solicitar("GET", "/sesion", 401, auth=self.consulta)
            self.solicitar("GET", "/sesion", auth=admin)
