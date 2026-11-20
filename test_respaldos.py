"""Regression tests: respaldos."""

import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import preparar_db_api
import respaldos
import test_regresion


class Copias(TestCase):
    def setUp(self):
        self.temp = self.enterContext(TemporaryDirectory())
        self.ruta = Path(self.temp) / "trabajo.db"
        with patch.object(preparar_db_api, "RUTA_DB_API", self.ruta):
            preparar_db_api.preparar_db_api()

    def test_copia_recupera_estado_y_conserva_anterior(self):
        copia = respaldos.crear(self.ruta, actor="admin_prueba")
        with closing(sqlite3.connect(self.ruta)) as db, db:
            db.execute("UPDATE productos SET stock=99 WHERE id=1")
        r = respaldos.restaurar(self.ruta, copia["archivo"])
        with closing(sqlite3.connect(self.ruta)) as db, db:
            self.assertEqual(
                db.execute("SELECT stock FROM productos WHERE id=1").fetchone()[0], 7
            )
        with TemporaryDirectory() as t:
            p = Path(t) / "anterior.db"
            respaldos._extraer(
                respaldos.carpeta(self.ruta) / r["resguardo_anterior"], p
            )
            with closing(sqlite3.connect(p)) as db, db:
                self.assertEqual(
                    db.execute("SELECT stock FROM productos WHERE id=1").fetchone()[0],
                    99,
                )

    def test_verificacion_aislada_no_modifica_fuente(self):
        c = respaldos.crear(self.ruta)
        anterior = respaldos._hash(self.ruta)
        r = respaldos.verificar(self.ruta, c["archivo"])
        self.assertEqual(r["verificacion"]["consultas_aplicacion"], "ok")
        self.assertEqual(anterior, respaldos._hash(self.ruta))

    def test_dano_hash_no_reemplaza_base(self):
        c = respaldos.crear(self.ruta)
        p = respaldos.carpeta(self.ruta) / c["archivo"]
        with zipfile.ZipFile(p) as z:
            meta = z.read("manifiesto.json")
            base = z.read("productos_api.db")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("manifiesto.json", meta)
            z.writestr("productos_api.db", base + b"cambio")
        antes = respaldos._hash(self.ruta)
        with self.assertRaises(respaldos.ErrorRespaldo):
            respaldos.restaurar(self.ruta, c["archivo"])
        self.assertEqual(antes, respaldos._hash(self.ruta))

    def test_esquema_incompatible(self):
        p = Path(self.temp) / "ajena.db"
        with closing(sqlite3.connect(p)) as db, db:
            db.execute("CREATE TABLE otra(id INTEGER)")
        with self.assertRaises(respaldos.ErrorRespaldo):
            respaldos.verificar_base(p)

    def test_base_corrupta(self):
        p = Path(self.temp) / "rota.db"
        p.write_bytes(b"no es sqlite")
        with self.assertRaises(respaldos.ErrorRespaldo):
            respaldos.verificar_base(p)

    def test_servidor_activo_impide_restauracion(self):
        c = respaldos.crear(self.ruta)
        with respaldos.bloqueo(self.ruta):
            with self.assertRaises(respaldos.ErrorRespaldo):
                respaldos.restaurar(self.ruta, c["archivo"])

    def test_copia_fallida_no_publicada(self):
        with patch.object(
            respaldos, "verificar_base", side_effect=respaldos.ErrorRespaldo("prueba")
        ):
            with self.assertRaises(respaldos.ErrorRespaldo):
                respaldos.crear(self.ruta)
        self.assertEqual(respaldos.listar(self.ruta), [])

    def test_automatico_diario_y_manuales_conservadas(self):
        a = respaldos.automatico_si_corresponde(self.ruta)
        self.assertIsNotNone(a)
        self.assertIsNone(respaldos.automatico_si_corresponde(self.ruta))
        m = respaldos.crear(self.ruta, actor="administrador")
        self.assertNotEqual(m["archivo"], a["archivo"])
        self.assertEqual(len(respaldos.listar(self.ruta)), 2)

    def test_no_admite_rutas_externas(self):
        with self.assertRaises(respaldos.ErrorRespaldo):
            respaldos.verificar(self.ruta, "../otra.zip")

    def test_zip_con_archivos_inesperados(self):
        p = respaldos.carpeta(self.ruta)
        p.mkdir()
        with zipfile.ZipFile(p / "malo.zip", "w") as z:
            z.writestr("../escape", "dato")
        with self.assertRaises(respaldos.ErrorRespaldo):
            respaldos.verificar(self.ruta, "malo.zip")

    def test_wal_incluido_en_copia(self):
        with closing(sqlite3.connect(self.ruta)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("UPDATE productos SET stock=11 WHERE id=1")
            db.commit()
            c = respaldos.crear(self.ruta)
        with TemporaryDirectory() as t:
            p = Path(t) / "restaurada.db"
            respaldos._extraer(respaldos.carpeta(self.ruta) / c["archivo"], p)
            with closing(sqlite3.connect(p)) as db, db:
                self.assertEqual(
                    db.execute("SELECT stock FROM productos WHERE id=1").fetchone()[0],
                    11,
                )

    def test_restaurar_base_danada_preserva_evidencia(self):
        c = respaldos.crear(self.ruta)
        self.ruta.write_bytes(b"base danada de prueba")
        r = respaldos.restaurar(self.ruta, c["archivo"])
        self.assertIn("sin validar", r["resguardo_anterior"])
        evidencia = list(respaldos.carpeta(self.ruta).glob("evidencia-*"))[0]
        self.assertEqual(
            (evidencia / self.ruta.name).read_bytes(), b"base danada de prueba"
        )
        self.assertEqual(respaldos.verificar_base(self.ruta)["productos"], 3)

    def test_no_copia_una_transaccion_sin_confirmar(self):
        with closing(sqlite3.connect(self.ruta)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("UPDATE productos SET stock=91 WHERE id=1")
            c = respaldos.crear(self.ruta)
            db.rollback()
        with TemporaryDirectory() as t:
            p = Path(t) / "copia.db"
            respaldos._extraer(respaldos.carpeta(self.ruta) / c["archivo"], p)
            with closing(sqlite3.connect(p)) as db, db:
                self.assertEqual(
                    db.execute("SELECT stock FROM productos WHERE id=1").fetchone()[0],
                    7,
                )

    def test_fallo_reemplazo_conserva_base_y_resguardo(self):
        c = respaldos.crear(self.ruta)
        with closing(sqlite3.connect(self.ruta)) as db, db:
            db.execute("UPDATE productos SET stock=21 WHERE id=1")
        original = respaldos.os.replace

        def fallar(src, dst):
            if Path(dst) == self.ruta:
                raise OSError("fallo simulado")
            return original(src, dst)

        with patch.object(respaldos.os, "replace", side_effect=fallar):
            with self.assertRaises(OSError):
                respaldos.restaurar(self.ruta, c["archivo"])
        with closing(sqlite3.connect(self.ruta)) as db, db:
            self.assertEqual(
                db.execute("SELECT stock FROM productos WHERE id=1").fetchone()[0], 21
            )
        self.assertTrue(
            any(x.get("tipo") == "antes_restaurar" for x in respaldos.listar(self.ruta))
        )

    def test_relacion_rota_no_se_publica(self):
        with closing(sqlite3.connect(self.ruta)) as db, db:
            db.execute(
                "INSERT INTO comprobantes_emergencia(referencia,nombre,mime,sha256,contenido,adjuntado_por) VALUES ('no-existe','a.pdf','application/pdf','hash',?, 'prueba')",
                (b"pdf",),
            )
        with self.assertRaises(respaldos.ErrorRespaldo):
            respaldos.crear(self.ruta)
        self.assertEqual(respaldos.listar(self.ruta), [])

    def test_sincroniza_archivos_con_permiso_de_escritura(self):

        original_open = Path.open
        original_fsync = respaldos.os.fsync
        modos = {}
        sincronizados = []

        def abrir(ruta, mode="r", *args, **kwargs):
            archivo = original_open(ruta, mode, *args, **kwargs)
            modos[archivo.fileno()] = mode
            return archivo

        def sincronizar(fd):
            modo = modos.get(fd, "")
            self.assertTrue(any(x in modo for x in ("+", "w", "a")), modo)
            sincronizados.append(modo)
            return original_fsync(fd)

        with patch.object(Path, "open", new=abrir), patch.object(
            respaldos.os, "fsync", side_effect=sincronizar
        ):
            c = respaldos.crear(self.ruta)
            respaldos.restaurar(self.ruta, c["archivo"])
        self.assertGreaterEqual(len(sincronizados), 5)

    def test_bloqueo_no_lee_el_byte_bloqueado(self):
        from unittest.mock import MagicMock

        abrir = Path.open
        archivos = []

        def sin_lectura(ruta, *args, **kwargs):
            real = abrir(ruta, *args, **kwargs)
            doble = MagicMock(wraps=real)
            doble.__enter__.return_value = doble
            doble.__exit__.side_effect = lambda *exc: real.close()
            doble.read.side_effect = PermissionError("byte bloqueado en Windows")
            archivos.append(doble)
            return doble

        with patch.object(Path, "open", new=sin_lectura):
            with respaldos.bloqueo(self.ruta):
                with self.assertRaises(respaldos.ErrorRespaldo):
                    with respaldos.bloqueo(self.ruta):
                        pass
        self.assertEqual(len(archivos), 2)
        for archivo in archivos:
            archivo.read.assert_not_called()


class Permisos(TestCase):
    setUp = test_regresion.RegresionInventario.setUp
    solicitar = test_regresion.RegresionInventario.solicitar

    def test_solo_admin_y_verifica_sin_reemplazar(self):
        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={
                "usuario": "empleado_copias",
                "rol": "empleado",
                "clave": "PruebaSegura123",
            },
        )
        for auth in [("empleado_copias", "PruebaSegura123"), self.consulta]:
            self.solicitar("GET", "/respaldos", 403, auth=auth)
            self.solicitar("POST", "/respaldos", 403, auth=auth)
        c = self.solicitar("POST", "/respaldos", 201)
        r = self.solicitar("POST", "/respaldos/" + c["archivo"] + "/verificacion")
        self.assertEqual(r["verificacion"]["integridad"], "ok")
        self.assertNotIn("clave_hash", json.dumps(r))
        self.assertNotIn("PruebaSegura123", json.dumps(r))
        self.solicitar(
            "POST",
            "/respaldos/" + c["archivo"] + "/verificacion",
            403,
            auth=self.consulta,
        )

    def test_recupera_cuentas_historial_y_archivos_exactos(self):
        import base64
        import repositorio_sqlite
        from usuarios import verificar_clave

        self.solicitar(
            "POST",
            "/usuarios",
            201,
            json={
                "usuario": "admin_respaldo",
                "rol": "administrador",
                "clave": "PruebaSegura123",
            },
        )
        datos = {
            "origen": "Comercio",
            "motivo": "Prueba",
            "empleado": "Prueba",
            "fecha_compra": "2020-01-01",
            "tipo_comprobante": "ticket",
            "numero_comprobante": "1",
            "productos": [
                {"producto_id": 1, "cantidad": 1, "costo_unitario_centavos": 100000}
            ],
        }
        self.solicitar("PUT", "/reposiciones-emergencia/em-respaldo", json=datos)
        self.solicitar(
            "PUT",
            "/reposiciones-emergencia/em-respaldo/comprobante",
            json={
                "nombre": "prueba.pdf",
                "contenido_base64": base64.b64encode(b"%PDF-prueba").decode(),
            },
        )
        self.solicitar(
            "PUT",
            "/ventas/respaldo-venta",
            auth=self.consulta,
            json={"producto_id": 1, "cantidad": 1},
        )
        ruta = repositorio_sqlite.RUTA_DB_API
        with closing(sqlite3.connect(ruta)) as db, db:
            tablas = [
                x[0]
                for x in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            antes = {
                n: db.execute('SELECT * FROM "' + n + '" ORDER BY rowid').fetchall()
                for n in tablas
            }
        c = self.solicitar("POST", "/respaldos", 201)
        with TemporaryDirectory() as t:
            recuperada = Path(t) / "copia.db"
            respaldos._extraer(respaldos.carpeta(ruta) / c["archivo"], recuperada)
            with closing(sqlite3.connect(recuperada)) as db, db:
                for n, filas in antes.items():
                    self.assertEqual(
                        filas,
                        db.execute(
                            'SELECT * FROM "' + n + '" ORDER BY rowid'
                        ).fetchall(),
                        n,
                    )
                clave = db.execute(
                    "SELECT clave_hash FROM usuarios WHERE usuario='admin_respaldo'"
                ).fetchone()[0]
                self.assertTrue(verificar_clave("PruebaSegura123", clave))
                self.assertEqual(
                    db.execute(
                        "SELECT contenido FROM comprobantes_emergencia"
                    ).fetchone()[0],
                    b"%PDF-prueba",
                )
            self.assertEqual(respaldos.verificar_base(recuperada)["pedidos_venta"], 1)
