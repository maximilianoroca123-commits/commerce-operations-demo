"""Regression tests: fondo emergencias."""

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest import TestCase
from unittest.mock import patch
import sqlite3
import preparar_db_api
import reposicion_emergencia
import repositorio_sqlite
import test_reposicion_automatica as base


class FondoEmergencias(TestCase):
    setUp = base.ReposicionAutomatica.setUp
    solicitar = base.ReposicionAutomatica.solicitar
    regla = base.ReposicionAutomatica.regla
    stock = base.ReposicionAutomatica.stock
    alertas = base.ReposicionAutomatica.alertas

    def datos(self, cantidad=3, numero="T-1", adjunto=None, **extras):
        return {
            "productos": [
                {
                    "producto_id": 1,
                    "cantidad": cantidad,
                    "costo_unitario_centavos": 180050,
                }
            ],
            "origen": "Comercio vecino",
            "motivo": "Falta de proveedor",
            "empleado": "Ana",
            "fecha_compra": "2020-01-01",
            "tipo_comprobante": "ticket",
            "numero_comprobante": numero,
            "adjunto": adjunto,
            **extras,
        }

    def compra(self, ref="emergencia", codigo=200, **datos):
        return self.solicitar(
            "PUT", f"/reposiciones-emergencia/{ref}", codigo, json=self.datos(**datos)
        )

    def fondo(self):
        return self.solicitar("GET", "/fondo-emergencias")

    def archivo(
        self, nombre="boleta.pdf", contenido=b"%PDF-1.4\nComprobante de prueba\n%%EOF"
    ):
        return {
            "nombre": nombre,
            "contenido_base64": base64.b64encode(contenido).decode(),
        }

    def test_parcial_y_objetivo_actualizan_alerta_y_gasto_en_el_momento(self):
        self.stock(4)
        self.regla()
        parcial = self.compra()
        self.assertEqual(parcial["situacion_al_registrar"][0]["faltante_objetivo"], 3)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)
        self.assertEqual(self.fondo()["total_egresos_centavos"], 540150)
        completo = self.compra("segunda", numero="T-2")
        self.assertEqual(
            completo["situacion_al_registrar"][0]["estado"], "stock_suficiente"
        )
        self.assertEqual(self.alertas(), [])
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 10)
        self.assertEqual(self.fondo()["total_egresos_centavos"], 1080300)
        self.assertEqual(completo["registrado_por"], "compras")
        self.assertEqual(completo["empleado"], "Ana")

    def test_reintento_y_comprobante_con_otra_referencia_no_duplican(self):
        r = self.compra()
        repetida = self.compra()
        self.assertTrue(repetida.pop("operacion_repetida"))
        self.assertEqual(repetida, r)
        self.compra(cantidad=4, codigo=409)
        self.compra("otra", codigo=409)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 10)
        self.assertEqual(self.fondo()["total"], 1)

    def test_compra_varios_productos_un_solo_comprobante_y_gasto(self):
        datos = self.datos(
            productos=[
                {"producto_id": 1, "cantidad": 1, "costo_unitario_centavos": 100025},
                {"producto_id": 2, "cantidad": 2, "costo_unitario_centavos": 150010},
            ]
        )
        r = self.solicitar("PUT", "/reposiciones-emergencia/mixta", json=datos)
        self.assertEqual(r["total_centavos"], 400045)
        self.assertEqual(len(r["productos"]), 2)
        self.assertEqual(self.solicitar("GET", "/productos/2")["stock"], 7)
        self.assertEqual(self.fondo()["total"], 1)
        datos["productos"].reverse()
        repetida = self.solicitar("PUT", "/reposiciones-emergencia/mixta", json=datos)
        self.assertTrue(repetida.pop("operacion_repetida"))
        self.assertEqual(repetida, r)

    def test_adjunto_al_recibir_descarga_identica_y_permisos(self):
        a = self.archivo()
        r = self.compra(adjunto=a)
        self.assertEqual(r["estado_documentacion"], "completo")
        self.assertEqual(r["comprobante"]["mime"], "application/pdf")
        respuesta = self.cliente.get(
            "/reposiciones-emergencia/emergencia/comprobante", auth=self.compras
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.content, base64.b64decode(a["contenido_base64"]))
        self.assertIn("attachment", respuesta.headers["content-disposition"])
        self.assertEqual(
            self.cliente.get(
                "/reposiciones-emergencia/emergencia/comprobante", auth=self.consulta
            ).status_code,
            403,
        )
        self.assertEqual(
            self.cliente.get(
                "/reposiciones-emergencia/emergencia/comprobante"
            ).status_code,
            401,
        )

    def test_adjunto_posterior_no_vuelve_a_cargar_stock_o_dinero(self):
        r = self.compra()
        self.assertEqual(r["estado_documentacion"], "adjunto_pendiente")
        self.assertEqual(
            self.solicitar("GET", "/reposiciones-emergencia?adjunto_pendiente=true")[
                "total"
            ],
            1,
        )
        self.solicitar("GET", "/reposiciones-emergencia/emergencia/comprobante", 404)
        a = self.archivo("boleta.png", b"\x89PNG\r\n\x1a\nprueba")
        actualizado = self.solicitar(
            "PUT", "/reposiciones-emergencia/emergencia/comprobante", json=a
        )
        self.assertEqual(actualizado["estado_documentacion"], "completo")
        repetida = self.solicitar(
            "PUT", "/reposiciones-emergencia/emergencia/comprobante", json=a
        )
        self.assertFalse(actualizado.pop("operacion_repetida"))
        self.assertTrue(repetida.pop("operacion_repetida"))
        self.assertEqual(repetida, actualizado)
        self.solicitar(
            "PUT",
            "/reposiciones-emergencia/emergencia/comprobante",
            409,
            json=self.archivo(),
        )
        self.assertEqual(
            self.solicitar("GET", "/reposiciones-emergencia?adjunto_pendiente=true")[
                "total"
            ],
            0,
        )
        self.assertEqual(self.fondo()["total"], 1)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 10)

        self.assertEqual(self.compra()["comprobante"], actualizado["comprobante"])

    def test_archivos_invalidos_no_producen_efectos(self):
        for a in [
            self.archivo("boleta.exe"),
            self.archivo("boleta.pdf", b"No es PDF"),
            self.archivo("../boleta.pdf"),
            {"nombre": "boleta.pdf", "contenido_base64": "?!"},
            self.archivo(contenido=b"%PDF-" + b"x" * (5 * 1024 * 1024)),
        ]:
            self.compra(codigo=409, adjunto=a)
        self.assertEqual(self.fondo()["total"], 0)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)

    def test_fallo_del_gasto_revierte_stock_comprobante_y_compra(self):
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.execute(
                """CREATE TRIGGER fallar_fondo BEFORE INSERT ON gastos_fondo_emergencia
                BEGIN SELECT RAISE(ABORT,'Fallo simulado'); END"""
            )
        with patch("servidor.logger.error"):
            self.compra(codigo=500, adjunto=self.archivo())
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)
        self.assertEqual(self.fondo()["total"], 0)
        self.assertEqual(self.solicitar("GET", "/reposiciones-emergencia")["total"], 0)
        with closing(repositorio_sqlite.conectar_db()) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM comprobantes_emergencia").fetchone()[
                    0
                ],
                0,
            )

    def test_fallo_recalculo_revierte_toda_la_compra(self):
        with patch("servidor.logger.error"), patch(
            "reposicion_automatica.evaluar",
            side_effect=sqlite3.OperationalError("Prueba"),
        ):
            self.compra(codigo=500)
        self.assertEqual(self.fondo()["total"], 0)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)

    def test_no_afecta_la_caja_de_ventas_y_sobrevive_actualizacion(self):
        self.solicitar("PUT", "/cajas/turno/apertura", json={"fondo_inicial": 1000})
        antes = self.solicitar("GET", "/cajas/turno")
        r = self.compra(adjunto=self.archivo())
        preparar_db_api.preparar_db_api()
        self.assertEqual(self.solicitar("GET", "/cajas/turno"), antes)
        self.assertEqual(
            self.solicitar("GET", "/reposiciones-emergencia/emergencia"), r
        )
        self.assertEqual(self.fondo()["total"], 1)

    def test_dos_confirmaciones_simultaneas_cargan_una_vez(self):
        datos = self.datos()
        with ThreadPoolExecutor(max_workers=2) as e:
            respuestas = list(
                e.map(
                    lambda _: self.cliente.put(
                        "/reposiciones-emergencia/emergencia",
                        auth=self.compras,
                        json=datos,
                    ),
                    [1, 2],
                )
            )
        self.assertEqual([x.status_code for x in respuestas], [200, 200])
        resultados = [r.json() for r in respuestas]
        self.assertEqual(
            sum(bool(r.pop("operacion_repetida", False)) for r in resultados), 1
        )
        self.assertEqual(resultados[0], resultados[1])
        self.assertEqual(self.fondo()["total"], 1)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 10)

    def test_datos_obligatorios_fecha_importe_productos_y_consulta(self):
        self.compra(codigo=422, fecha_compra="2999-01-01")
        self.compra(codigo=422, empleado=" ")
        self.compra(codigo=422, numero_comprobante=" ")
        self.compra(
            codigo=409,
            productos=[{"producto_id": 1, "cantidad": 1, "costo_unitario_centavos": 1}]
            * 2,
        )
        self.compra(
            codigo=404,
            productos=[
                {"producto_id": 999, "cantidad": 1, "costo_unitario_centavos": 1}
            ],
        )
        self.compra(
            codigo=409,
            productos=[
                {"producto_id": 1, "cantidad": 2, "costo_unitario_centavos": 2**63 - 1}
            ],
        )
        self.solicitar("GET", "/fondo-emergencias", 403, auth=self.consulta)
        self.solicitar("GET", "/fondo-emergencias?pagina=0", 422)
        self.solicitar("GET", "/reposiciones-emergencia/no-existe", 404)
        self.assertEqual(self.fondo()["total"], 0)

    def test_con_pedidos_pendientes_o_exceso_actualiza_alerta_sin_cancelarlos(self):
        self.stock(4)
        self.regla()

        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.execute(
                """INSERT INTO pedidos_reposicion(producto_id,proveedor,id_externo,cantidad,costo_ofertado_centavos)
                VALUES (1,'demo','0012',3,120000)"""
            )
        r = self.compra()
        self.assertEqual(r["situacion_al_registrar"][0]["faltante_objetivo"], 0)
        self.assertEqual(self.alertas(), [])
        self.compra("exceso", numero="T-2", cantidad=4)
        self.assertEqual(self.alertas()[0]["codigo"], "exceso_proyectado")
        self.assertEqual(self.solicitar("GET", "/pedidos")[0]["estado"], "pendiente")

    def test_migracion_no_inventa_gastos_de_recepciones_antiguas(self):
        with closing(repositorio_sqlite.conectar_db()) as db, db:
            db.execute(
                """INSERT INTO reposiciones_emergencia(producto_id,referencia,cantidad,costo_unitario_centavos,origen,motivo)
                VALUES (1,'vieja',1,100000,'Anterior','Prueba')"""
            )
        preparar_db_api.preparar_db_api()
        self.assertEqual(self.fondo()["total"], 0)
        self.compra("vieja", codigo=409)

    def test_mismo_archivo_con_otro_numero_y_referencia_rechaza_duplicado(self):
        self.compra(adjunto=self.archivo())
        self.compra("otra", codigo=409, numero="Otro-numero", adjunto=self.archivo())
        self.assertEqual(self.fondo()["total"], 1)
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 10)

    def test_reposicion_parcial_reanuda_campana_por_encima_del_minimo(self):
        self.stock(4)
        self.regla()
        self.compra(cantidad=3)
        with closing(repositorio_sqlite.conectar_db()) as db:
            self.assertEqual(
                db.execute(
                    "SELECT activa FROM campanas_reposicion WHERE producto_id=1"
                ).fetchone()[0],
                1,
            )
        self.assertEqual(self.alertas()[0]["codigo"], "sin_ofertas")
        self.assertEqual(self.solicitar("GET", "/productos/1")["stock"], 7)
