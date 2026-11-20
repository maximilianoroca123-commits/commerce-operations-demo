"""Verified SQLite backups and offline restoration with file locking."""

import hashlib
import json
import os
import sqlite3
import tempfile
import time
import uuid
import zipfile
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

FORMATO = 1
INTERVALO = 24 * 60 * 60


class ErrorRespaldo(Exception):
    pass


@contextmanager
def bloqueo(ruta, nombre="servidor"):
    """Acquire an operating-system lock released when the process exits."""
    archivo = Path(str(ruta) + "." + nombre + ".lock")
    archivo.parent.mkdir(parents=True, exist_ok=True)
    with archivo.open("a+b") as f:
        try:

            if os.fstat(f.fileno()).st_size == 0:
                f.write(b"0")
                f.flush()
            f.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise ErrorRespaldo(
                "La base está en uso por el servidor u otra tarea de mantenimiento. Detenela y reintentá."
            ) from e
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


def carpeta(ruta):
    return Path(ruta).resolve().parent / "respaldos"


def abrir_lectura(ruta):
    db = sqlite3.connect(Path(ruta).resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def verificar_base(ruta):
    """Verify database integrity, relationships and application queries without business mutations."""
    from pedidos_venta import detalle
    from auditoria_comercial import listar

    esperado = json.loads(
        Path(__file__).with_name("esquema_respaldo.json").read_text(encoding="utf-8")
    )
    try:
        with closing(abrir_lectura(ruta)) as db:
            if [x[0] for x in db.execute("PRAGMA integrity_check")] != ["ok"]:
                raise ErrorRespaldo("La copia tiene errores de integridad de SQLite.")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ErrorRespaldo("La copia tiene relaciones inválidas.")
            for tabla, columnas in esperado.items():
                reales = {
                    x["name"] for x in db.execute('PRAGMA table_info("' + tabla + '")')
                }
                if not set(columnas) <= reales:
                    raise ErrorRespaldo(
                        "La copia no corresponde al esquema compatible: " + tabla
                    )

            productos = db.execute(
                "SELECT id,nombre,precio,stock FROM productos"
            ).fetchall()
            if any(x["stock"] < 0 or x["precio"] <= 0 for x in productos):
                raise ErrorRespaldo("La copia contiene stock o precios inválidos.")
            cuentas = db.execute(
                "SELECT usuario,rol,activo,debe_cambiar_clave,version_credencial FROM usuarios"
            ).fetchall()
            pedidos = list(db.execute("SELECT id FROM pedidos_venta ORDER BY id"))
            for p in pedidos:
                detalle(db, p["id"])

            resumen = {
                tabla: db.execute('SELECT COUNT(*) FROM "' + tabla + '"').fetchone()[0]
                for tabla in esperado
            }
            for x in db.execute("SELECT * FROM comprobantes_emergencia"):
                tuple(x)
        listar(lambda: abrir_lectura(ruta), 1, 20)
        return {
            "productos": len(productos),
            "cuentas": len(cuentas),
            "pedidos_venta": len(pedidos),
            "filas_por_tabla": resumen,
            "integridad": "ok",
            "relaciones": "ok",
            "consultas_aplicacion": "ok",
        }
    except (sqlite3.Error, ValueError, KeyError, TypeError) as e:
        raise ErrorRespaldo(
            "No se pudo abrir o consultar la copia con esta versión del programa."
        ) from e


def _hash(ruta):
    h = hashlib.sha256()
    with Path(ruta).open("rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


# Use SQLite backup rather than copying a database file while writes may be active.
def _copiar(origen, destino):
    limite = time.monotonic() + 60

    def progreso(estado, pendientes, total):
        if time.monotonic() > limite:
            raise ErrorRespaldo(
                "El respaldo superó el tiempo de espera; no se publicó una copia incompleta."
            )

    with closing(abrir_lectura(origen)) as src, closing(
        sqlite3.connect(destino)
    ) as dst:
        src.backup(dst, pages=256, progress=progreso, sleep=0.05)
    with Path(destino).open("r+b") as f:
        os.fsync(f.fileno())


def _crear(ruta, tipo, actor):
    if tipo not in ("manual", "automatico", "antes_restaurar"):
        raise ErrorRespaldo("Tipo de respaldo inválido.")
    destino = carpeta(ruta)
    destino.mkdir(parents=True, exist_ok=True, mode=0o700)
    sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    nombre = f"{tipo}-{sello}-{uuid.uuid4().hex[:8]}.zip"
    with tempfile.TemporaryDirectory(dir=destino) as temp:
        temp = Path(temp)
        base = temp / "productos_api.db"
        _copiar(ruta, base)
        pruebas = verificar_base(base)
        info = {
            "formato": FORMATO,
            "archivo": nombre,
            "tipo": tipo,
            "actor": str(actor),
            "creado_en": datetime.now(timezone.utc).isoformat(),
            "sha256": _hash(base),
            "verificacion": pruebas,
        }
        provisional = temp / "respaldo.zip"
        with zipfile.ZipFile(provisional, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(base, "productos_api.db")
            z.writestr("manifiesto.json", json.dumps(info, ensure_ascii=False))
        provisional.chmod(0o600)
        with provisional.open("r+b") as f:
            os.fsync(f.fileno())
        os.replace(provisional, destino / nombre)
    return info


def crear(ruta, tipo="manual", actor="sistema_respaldos"):
    with bloqueo(ruta, "respaldos"):
        return _crear(ruta, tipo, actor)


def _ruta(ruta, nombre):
    if Path(nombre).name != nombre or not nombre.endswith(".zip"):
        raise ErrorRespaldo("Nombre de respaldo inválido.")
    p = carpeta(ruta) / nombre
    if p.is_symlink() or not p.is_file():
        raise ErrorRespaldo("Respaldo no encontrado.")
    return p


def _extraer(archivo, destino):
    try:
        with zipfile.ZipFile(archivo) as z:
            if sorted(z.namelist()) != ["manifiesto.json", "productos_api.db"]:
                raise ErrorRespaldo("El respaldo no contiene los archivos esperados.")
            if z.getinfo("manifiesto.json").file_size > 1024 * 1024:
                raise ErrorRespaldo("Manifiesto inválido.")
            info = json.loads(z.read("manifiesto.json"))
            if info.get("formato") != FORMATO:
                raise ErrorRespaldo("Formato de respaldo no compatible.")
            with z.open("productos_api.db") as src, destino.open("wb") as dst:
                import shutil

                shutil.copyfileobj(src, dst, 1024 * 1024)
        if _hash(destino) != info.get("sha256"):
            raise ErrorRespaldo("La copia cambió o está dañada: SHA-256 no coincide.")
        return info
    except (OSError, zipfile.BadZipFile, ValueError, KeyError) as e:
        raise ErrorRespaldo("No se pudo leer el respaldo.") from e


def verificar(ruta, nombre):
    archivo = _ruta(ruta, nombre)

    with tempfile.TemporaryDirectory() as temp:
        copia = Path(temp) / "recuperacion.db"
        info = _extraer(archivo, copia)
        info["verificacion"] = verificar_base(copia)
        info["archivo"] = nombre
        return info


def listar(ruta):
    resultados = []
    for p in sorted(carpeta(ruta).glob("*.zip"), reverse=True):
        try:
            with zipfile.ZipFile(p) as z:
                if z.getinfo("manifiesto.json").file_size > 1024 * 1024:
                    raise ValueError()
                info = json.loads(z.read("manifiesto.json"))
            resultados.append(
                {
                    "archivo": p.name,
                    "tipo": info["tipo"],
                    "creado_en": info["creado_en"],
                    "actor": info["actor"],
                    "verificada_al_crear": True,
                }
            )
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            resultados.append(
                {"archivo": p.name, "error": "Archivo ilegible; no usar sin verificar."}
            )
    resultados.sort(key=lambda x: x.get("creado_en", ""), reverse=True)
    return resultados


def automatico_si_corresponde(ruta):

    with bloqueo(ruta, "respaldos"):
        for x in listar(ruta):
            if x.get("tipo") == "automatico":
                try:
                    edad = (
                        datetime.now(timezone.utc)
                        - datetime.fromisoformat(x["creado_en"])
                    ).total_seconds()
                    if 0 <= edad < INTERVALO:
                        verificar(ruta, x["archivo"])
                        return None
                except (ErrorRespaldo, ValueError):
                    pass
        return _crear(ruta, "automatico", "sistema_respaldos")


def restaurar(ruta, nombre):
    """Restore locally with the API stopped; no HTTP restoration endpoint is exposed."""
    ruta = Path(ruta).resolve()
    with bloqueo(ruta), bloqueo(ruta, "respaldos"):
        with tempfile.TemporaryDirectory(dir=ruta.parent) as temp:
            preparada = Path(temp) / "recuperacion.db"
            _extraer(_ruta(ruta, nombre), preparada)
            resultado = verificar_base(preparada)
            resguardo = None
            evidencia = None
            if ruta.exists():
                try:
                    resguardo = _crear(ruta, "antes_restaurar", "mantenimiento_local")[
                        "archivo"
                    ]
                except (ErrorRespaldo, sqlite3.Error):

                    import shutil

                    evidencia = carpeta(ruta) / ("evidencia-" + uuid.uuid4().hex)
                    evidencia.mkdir()
                    for original in [
                        ruta,
                        Path(str(ruta) + "-wal"),
                        Path(str(ruta) + "-shm"),
                        Path(str(ruta) + "-journal"),
                    ]:
                        if original.exists():
                            shutil.copy2(original, evidencia / original.name)
                    resguardo = evidencia.name + " (archivos originales sin validar)"
                if evidencia is None:
                    with closing(sqlite3.connect(ruta)) as actual:
                        r = actual.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                        if r and r[0]:
                            raise ErrorRespaldo(
                                "La base sigue ocupada; no se restauró."
                            )
                        modo = actual.execute("PRAGMA journal_mode=DELETE").fetchone()[
                            0
                        ]
                        if modo.lower() != "delete":
                            raise ErrorRespaldo(
                                "No se pudo cerrar el diario de la base."
                            )

            movidos = []
            try:
                for sufijo in ("-wal", "-shm", "-journal"):
                    lateral = Path(str(ruta) + sufijo)
                    if lateral.exists():
                        if evidencia is None:
                            raise ErrorRespaldo(
                                "Quedó un diario activo; cerrá todas las conexiones antes de restaurar."
                            )
                        guardado = Path(temp) / lateral.name
                        os.replace(lateral, guardado)
                        movidos.append((guardado, lateral))
                with preparada.open("r+b") as f:
                    os.fsync(f.fileno())
                os.replace(preparada, ruta)
            except BaseException:
                for guardado, lateral in movidos:
                    os.replace(guardado, lateral)
                raise
            return {
                "restaurada": nombre,
                "resguardo_anterior": resguardo,
                "verificacion": resultado,
            }
