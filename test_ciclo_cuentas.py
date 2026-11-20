"""Regression tests: ciclo cuentas."""

import sqlite3
from contextlib import closing
from unittest import TestCase
from unittest.mock import patch
from fastapi import HTTPException
import test_regresion
import repositorio_sqlite
import preparar_db_api
from autenticacion import Identidad
from usuarios import CambioClave, AltaUsuario, crear_usuario
from rutas_usuarios import clave as cambiar_clave_directa


class CicloCuentas(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def alta(self, nombre="ana", rol="cliente"):
        datos = {"usuario": nombre, "rol": rol, "clave": "OriginalSegura123"}
        if rol == "cliente":
            datos["cliente"] = {
                "nombre": "Ana",
                "apellido": "Prueba",
                "correo": nombre + "@example.com",
            }
        if rol == "proveedor":
            datos["proveedor"] = "demo"
        r = self.solicitar("POST", "/usuarios", 201, json=datos)
        return (nombre, "OriginalSegura123"), r

    def restablecer(
        self, nombre="ana", ref="reset-1", codigo=200, auth=None, **cambios
    ):
        return self.solicitar(
            "PUT",
            f"/usuarios/{nombre}/restablecimientos/{ref}",
            codigo,
            auth=auth,
            json={
                "temporal": "TemporalSegura123",
                "motivo": "Olvido de contraseña",
                **cambios,
            },
        )

    def historia(self, nombre="ana"):
        return self.solicitar("GET", "/auditoria/cuentas", params={"usuario": nombre})

    def test_recuperacion_obliga_cambio_antes_de_ver_datos(self):
        ana, antes = self.alta()
        self.restablecer()
        self.solicitar("GET", "/sesion", 401, auth=ana)
        temporal = ("ana", "TemporalSegura123")
        sesion = self.solicitar("GET", "/sesion", auth=temporal)
        self.assertTrue(sesion["debe_cambiar_clave"])
        self.assertEqual(sesion["opciones_operativas"], [])
        for ruta in [
            "/productos",
            "/mi-perfil",
            "/pedidos-venta",
            "/solicitudes-clientes",
        ]:
            self.solicitar("GET", ruta, 403, auth=temporal)
        self.solicitar(
            "PUT",
            "/mi-cuenta/clave",
            409,
            auth=temporal,
            json={"actual": temporal[1], "nueva": temporal[1]},
        )
        self.solicitar(
            "PUT",
            "/mi-cuenta/clave",
            auth=temporal,
            json={"actual": temporal[1], "nueva": "DefinitivaSegura123"},
        )
        self.solicitar("GET", "/sesion", 401, auth=temporal)
        nueva = ("ana", "DefinitivaSegura123")
        self.assertFalse(
            self.solicitar("GET", "/sesion", auth=nueva)["debe_cambiar_clave"]
        )
        self.assertEqual(
            self.solicitar("GET", "/mi-perfil", auth=nueva)["cliente"]["id"],
            antes["cliente_id"],
        )
        self.assertEqual(
            [x["accion"] for x in self.historia()["movimientos"]],
            ["clave_cambiada", "clave_restablecida", "cuenta_creada"],
        )

    def test_reintento_no_desarma_cambio_posterior_del_usuario(self):
        self.alta()
        self.restablecer()
        temporal = ("ana", "TemporalSegura123")
        self.solicitar(
            "PUT",
            "/mi-cuenta/clave",
            auth=temporal,
            json={"actual": temporal[1], "nueva": "DefinitivaSegura123"},
        )
        r = self.restablecer()
        self.assertEqual(r["estado"], "ya_registrado")
        self.solicitar("GET", "/sesion", auth=("ana", "DefinitivaSegura123"))
        self.solicitar("GET", "/sesion", 401, auth=temporal)
        self.assertEqual(self.historia()["total"], 3)
        self.restablecer(codigo=409, temporal="OtraTemporalSegura123")
        self.restablecer(codigo=409, motivo="Otros datos")

    def test_solo_administrador_restablece_y_consulta_historial(self):
        ana, _ = self.alta()
        for rol, nombre in [("empleado", "operador"), ("proveedor", "vendedor")]:
            auth, _ = self.alta(nombre, rol)
            self.restablecer(codigo=403, auth=auth)
            self.solicitar("GET", "/auditoria/cuentas", 403, auth=auth)
        self.restablecer(codigo=403, auth=ana)
        self.solicitar("GET", "/auditoria/cuentas", 403, auth=ana)
        self.restablecer(nombre="consulta", codigo=404)
        self.restablecer(nombre="compras", codigo=409)

    def test_historial_no_contiene_contrasenas_ni_hashes(self):
        self.alta()
        self.restablecer()
        texto = str(self.historia())
        for secreto in [
            "OriginalSegura123",
            "TemporalSegura123",
            "scrypt$",
            "clave_hash",
        ]:
            self.assertNotIn(secreto, texto)
        evento = self.historia()["movimientos"][0]
        self.assertEqual(evento["actor"], "compras")
        self.assertEqual(evento["detalle"]["referencia"], "reset-1")

    def test_desactivar_reactivar_conserva_historial_y_no_duplica_eventos(self):
        ana, cuenta = self.alta()
        for activo in [False, False]:
            self.solicitar("PUT", "/usuarios/ana/estado", json={"activo": activo})
        self.solicitar("GET", "/sesion", 401, auth=ana)
        self.restablecer(codigo=409)
        self.solicitar("PUT", "/usuarios/ana/estado", json={"activo": True})
        self.assertEqual(
            self.solicitar("GET", "/sesion", auth=ana)["cliente_id"],
            cuenta["cliente_id"],
        )
        self.assertEqual(self.historia()["total"], 3)

    def test_historial_inmutable_y_migracion_no_inventa_eventos(self):
        self.alta()
        preparar_db_api.preparar_db_api()
        preparar_db_api.preparar_db_api()
        self.assertEqual(self.historia()["total"], 1)
        with closing(repositorio_sqlite.conectar_db()) as db:
            for sql in [
                "DELETE FROM auditoria_cuentas",
                "UPDATE auditoria_cuentas SET actor='otro'",
            ]:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql)
                db.rollback()

    def test_fallo_del_historial_revierte_creacion_con_ficha(self):
        datos = AltaUsuario(
            usuario="ana",
            clave="OriginalSegura123",
            rol="cliente",
            cliente={
                "nombre": "Ana",
                "apellido": "Prueba",
                "correo": "ana@example.com",
            },
        )
        with patch(
            "usuarios.registrar_cuenta",
            side_effect=sqlite3.IntegrityError("fallo de prueba"),
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                crear_usuario(repositorio_sqlite.conectar_db, datos, "compras")
        with closing(repositorio_sqlite.conectar_db()) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0], 0
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM clientes").fetchone()[0], 0
            )

    def test_fallo_del_historial_revierte_restablecimiento(self):
        ana, _ = self.alta()
        with patch(
            "rutas_usuarios.registrar_cuenta",
            side_effect=sqlite3.IntegrityError("fallo de prueba"),
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                self.restablecer()
        self.solicitar("GET", "/sesion", auth=ana)
        with closing(repositorio_sqlite.conectar_db()) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM restablecimientos_clave").fetchone()[
                    0
                ],
                0,
            )

    def test_cambio_desactualizado_no_pisa_restablecimiento(self):
        self.alta()
        vieja = Identidad("ana", "cliente", version=0)
        self.restablecer()
        with self.assertRaises(HTTPException) as error:
            cambiar_clave_directa(
                CambioClave(actual="OriginalSegura123", nueva="IntrusaSegura123"), vieja
            )
        self.assertEqual(error.exception.status_code, 409)
        self.solicitar("GET", "/sesion", auth=("ana", "TemporalSegura123"))

    def test_administrador_temporal_tambien_queda_bloqueado(self):
        admin, _ = self.alta("jefe", "administrador")
        self.restablecer(nombre="jefe")
        temporal = ("jefe", "TemporalSegura123")
        self.solicitar("GET", "/usuarios", 403, auth=temporal)
        self.solicitar("GET", "/auditoria/cuentas", 403, auth=temporal)
        self.solicitar(
            "PUT", "/usuarios/ana/estado", 403, auth=temporal, json={"activo": False}
        )
        self.solicitar(
            "PUT",
            "/mi-cuenta/clave",
            auth=temporal,
            json={"actual": temporal[1], "nueva": "JefeDefinitiva123"},
        )
        self.solicitar("GET", "/usuarios", auth=("jefe", "JefeDefinitiva123"))

    def test_historial_filtro_y_paginacion_antes_del_conteo(self):
        self.alta()
        self.alta("bruno")
        self.restablecer()
        r = self.solicitar("GET", "/auditoria/cuentas?usuario=ana&limite=1")
        self.assertEqual(r["total"], 2)
        self.assertEqual(len(r["movimientos"]), 1)
        self.assertEqual(r["movimientos"][0]["afectado"], "ana")
        self.solicitar("GET", "/auditoria/cuentas?pagina=0", 422)

    def test_menu_cambia_temporal_antes_de_mostrar_menu(self):
        import menu_api

        self.alta()
        self.restablecer()
        cliente = self.cliente

        class Sesion:
            auth = None

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def get(self, url, **datos):
                return self.request("GET", url, **datos)

            def request(self, metodo, url, **datos):
                datos.pop("timeout", None)
                r = cliente.request(metodo, url, auth=self.auth, **datos)
                return r

        with patch("menu_api.requests.Session", return_value=Sesion()), patch(
            "builtins.input", side_effect=["ana", "0"]
        ), patch("menu_api.getpass", return_value="TemporalSegura123"), patch(
            "menu_cuentas.getpass",
            side_effect=[
                "TemporalSegura123",
                "DefinitivaSegura123",
                "DefinitivaSegura123",
            ],
        ), patch(
            "builtins.print"
        ) as salida:
            menu_api.main()
        texto = " ".join(str(x) for x in salida.call_args_list)
        self.assertIn("temporal", texto)
        self.assertIn("CLIENTE", texto)
        self.solicitar("GET", "/sesion", auth=("ana", "DefinitivaSegura123"))

    def test_restablecer_desactivada_no_la_reactiva(self):
        self.alta()
        self.solicitar("PUT", "/usuarios/ana/estado", json={"activo": False})
        self.restablecer(codigo=409)
        self.solicitar("GET", "/sesion", 401, auth=("ana", "OriginalSegura123"))
        self.assertEqual(self.historia()["total"], 2)

    def test_fallo_de_auditoria_revierte_cambio_y_desactivacion(self):
        ana, _ = self.alta()
        with patch(
            "rutas_usuarios.registrar_cuenta",
            side_effect=sqlite3.IntegrityError("fallo de prueba"),
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                self.solicitar(
                    "PUT",
                    "/mi-cuenta/clave",
                    auth=ana,
                    json={"actual": ana[1], "nueva": "OtraSegura123"},
                )
            with self.assertRaises(sqlite3.IntegrityError):
                self.solicitar("PUT", "/usuarios/ana/estado", json={"activo": False})
        self.solicitar("GET", "/sesion", auth=ana)
        self.assertEqual(self.historia()["total"], 1)
