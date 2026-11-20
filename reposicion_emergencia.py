"""Emergency purchase receipts, attachments and associated expenditure."""

from auditoria_comercial import registrar as auditar

import base64
import binascii
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import PurePath

from errores import ProductoNoEncontradoError
from pedidos_venta import ConflictoEntregaError
from movimientos_inventario import registrar

MAX_ARCHIVO = 5 * 1024 * 1024


def crear_tabla(db):
    db.execute("""CREATE TABLE IF NOT EXISTS reposiciones_emergencia (
        producto_id INTEGER NOT NULL REFERENCES productos(id),referencia TEXT NOT NULL,
        cantidad INTEGER NOT NULL CHECK(cantidad>0),costo_unitario_centavos INTEGER NOT NULL,
        origen TEXT NOT NULL,motivo TEXT NOT NULL,
        registrado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        PRIMARY KEY(producto_id,referencia))""")
    db.execute("""CREATE TABLE IF NOT EXISTS compras_emergencia (
        referencia TEXT PRIMARY KEY,origen TEXT NOT NULL,origen_normalizado TEXT NOT NULL,
        motivo TEXT NOT NULL,empleado TEXT NOT NULL,registrado_por TEXT NOT NULL,
        fecha_compra TEXT NOT NULL,tipo_comprobante TEXT NOT NULL,numero_comprobante TEXT NOT NULL,
        total_centavos INTEGER NOT NULL CHECK(total_centavos>0),solicitud TEXT NOT NULL,
        resultado_reposicion TEXT NOT NULL DEFAULT '{}',
        registrado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(origen_normalizado,fecha_compra,tipo_comprobante,numero_comprobante))""")
    db.execute("""CREATE TABLE IF NOT EXISTS gastos_fondo_emergencia (
        id INTEGER PRIMARY KEY,referencia TEXT NOT NULL UNIQUE REFERENCES compras_emergencia(referencia),
        fondo TEXT NOT NULL DEFAULT 'emergencias_reposicion',
        importe_centavos INTEGER NOT NULL CHECK(importe_centavos>0),
        registrado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))""")
    db.execute("""CREATE TABLE IF NOT EXISTS comprobantes_emergencia (
        referencia TEXT PRIMARY KEY REFERENCES compras_emergencia(referencia),
        nombre TEXT NOT NULL,mime TEXT NOT NULL,sha256 TEXT NOT NULL,contenido BLOB NOT NULL,
        adjuntado_por TEXT NOT NULL,
        adjuntado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))""")


def preparar_adjunto(adjunto):
    if adjunto is None:
        return None
    try:
        contenido = base64.b64decode(adjunto["contenido_base64"], validate=True)
    except (ValueError, binascii.Error):
        raise ConflictoEntregaError(
            "El archivo no tiene una codificación base64 válida"
        ) from None
    if not contenido or len(contenido) > MAX_ARCHIVO:
        raise ConflictoEntregaError("El comprobante debe ocupar entre 1 byte y 5 MB")
    nombre = adjunto["nombre"]
    if "/" in nombre or "\\" in nombre or any(ord(x) < 32 for x in nombre):
        raise ConflictoEntregaError("Usá solo el nombre del archivo, sin carpetas")
    extension = PurePath(nombre).suffix.lower()
    formatos = {
        ".pdf": ("application/pdf", b"%PDF-"),
        ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
        ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
        ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    }
    if extension not in formatos or not contenido.startswith(formatos[extension][1]):
        raise ConflictoEntregaError(
            "El archivo debe ser PDF, PNG o JPEG y coincidir con su extensión"
        )
    return {
        "nombre": nombre,
        "mime": formatos[extension][0],
        "sha256": hashlib.sha256(contenido).hexdigest(),
        "contenido": contenido,
    }


def guardar_adjunto(db, referencia, adjunto, usuario):
    anterior = db.execute(
        "SELECT sha256,nombre FROM comprobantes_emergencia WHERE referencia=?",
        (referencia,),
    ).fetchone()
    if anterior:
        if (anterior["sha256"], anterior["nombre"]) != (
            adjunto["sha256"],
            adjunto["nombre"],
        ):
            raise ConflictoEntregaError(
                "La compra ya tiene otro archivo de comprobante"
            )
        return
    repetido = db.execute(
        "SELECT referencia FROM comprobantes_emergencia WHERE sha256=?",
        (adjunto["sha256"],),
    ).fetchone()
    if repetido:
        raise ConflictoEntregaError(
            f"El archivo ya pertenece a la compra {repetido[0]}"
        )
    db.execute(
        """INSERT INTO comprobantes_emergencia
        (referencia,nombre,mime,sha256,contenido,adjuntado_por) VALUES (?,?,?,?,?,?)""",
        (
            referencia,
            adjunto["nombre"],
            adjunto["mime"],
            adjunto["sha256"],
            adjunto["contenido"],
            usuario,
        ),
    )


def detalle_db(db, referencia):
    fila = db.execute(
        "SELECT * FROM compras_emergencia WHERE referencia=?", (referencia,)
    ).fetchone()
    if fila is None:
        raise ProductoNoEncontradoError("Compra de emergencia no encontrada")
    compra = dict(fila)
    compra.pop("solicitud")
    compra.pop("origen_normalizado")
    compra["situacion_al_registrar"] = json.loads(compra.pop("resultado_reposicion"))
    compra["productos"] = [
        dict(x)
        for x in db.execute(
            """SELECT producto_id,cantidad,costo_unitario_centavos
        FROM reposiciones_emergencia WHERE referencia=? ORDER BY producto_id""",
            (referencia,),
        )
    ]
    archivo = db.execute(
        """SELECT nombre,mime,sha256,LENGTH(contenido) AS bytes,adjuntado_por,adjuntado_en
        FROM comprobantes_emergencia WHERE referencia=?""",
        (referencia,),
    ).fetchone()
    compra["comprobante"] = dict(archivo) if archivo else None
    compra["estado_documentacion"] = "completo" if archivo else "adjunto_pendiente"
    compra["fondo"] = "emergencias_reposicion"
    compra["gasto_registrado"] = True
    return compra


def recibir_compra(conectar_db, referencia, datos, usuario):
    datos = dict(datos)
    datos["productos"] = sorted(datos["productos"], key=lambda x: x["producto_id"])
    ids = [x["producto_id"] for x in datos["productos"]]
    if len(ids) != len(set(ids)):
        raise ConflictoEntregaError("No repitas un producto dentro de la compra")
    adjunto = preparar_adjunto(datos.pop("adjunto", None))
    huella_archivo = (
        {k: v for k, v in adjunto.items() if k != "contenido"} if adjunto else None
    )
    solicitud = json.dumps(
        {**datos, "adjunto": huella_archivo}, sort_keys=True, ensure_ascii=False
    )
    total = sum(
        x["cantidad"] * x["costo_unitario_centavos"] for x in datos["productos"]
    )
    if total > 2**63 - 1:
        raise ConflictoEntregaError("El importe total de la compra está fuera de rango")
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        anterior = db.execute(
            "SELECT solicitud FROM compras_emergencia WHERE referencia=?", (referencia,)
        ).fetchone()
        if anterior:
            if anterior[0] != solicitud:
                raise ConflictoEntregaError(
                    "La referencia ya corresponde a una compra con datos diferentes. Consultá la compra (opción 29) antes de volver a cargarla."
                )
            return {**detalle_db(db, referencia), "operacion_repetida": True}
        if db.execute(
            "SELECT 1 FROM reposiciones_emergencia WHERE referencia=?", (referencia,)
        ).fetchone():
            raise ConflictoEntregaError(
                "La referencia corresponde a una recepción anterior a esta versión"
            )
        origen_normalizado = " ".join(datos["origen"].casefold().split())
        numero = " ".join(datos["numero_comprobante"].upper().split())
        duplicado = db.execute(
            """SELECT referencia FROM compras_emergencia WHERE origen_normalizado=?
            AND fecha_compra=? AND tipo_comprobante=? AND numero_comprobante=?""",
            (
                origen_normalizado,
                datos["fecha_compra"],
                datos["tipo_comprobante"],
                numero,
            ),
        ).fetchone()
        if duplicado:
            raise ConflictoEntregaError(
                f"El comprobante ya se registró en la compra {duplicado[0]}"
            )
        for item in datos["productos"]:
            if (
                db.execute(
                    "SELECT 1 FROM productos WHERE id=?", (item["producto_id"],)
                ).fetchone()
                is None
            ):
                raise ProductoNoEncontradoError("Producto no encontrado")
        db.execute(
            """INSERT INTO compras_emergencia
            (referencia,origen,origen_normalizado,motivo,empleado,registrado_por,fecha_compra,
             tipo_comprobante,numero_comprobante,total_centavos,solicitud) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                referencia,
                datos["origen"],
                origen_normalizado,
                datos["motivo"],
                datos["empleado"],
                usuario,
                datos["fecha_compra"],
                datos["tipo_comprobante"],
                numero,
                total,
                solicitud,
            ),
        )
        for item in datos["productos"]:
            id, n = item["producto_id"], item["cantidad"]
            actualizado = db.execute(
                "UPDATE productos SET stock=stock+? WHERE id=? AND stock<=?",
                (n, id, 2**63 - 1 - n),
            )
            if actualizado.rowcount != 1:
                raise ConflictoEntregaError("La recepción supera el máximo de stock")
            db.execute(
                """INSERT INTO reposiciones_emergencia
                (producto_id,referencia,cantidad,costo_unitario_centavos,origen,motivo) VALUES (?,?,?,?,?,?)""",
                (
                    id,
                    referencia,
                    n,
                    item["costo_unitario_centavos"],
                    datos["origen"],
                    datos["motivo"],
                ),
            )
            registrar(db, id, "reposicion_emergencia", referencia, n, datos["motivo"])
        db.execute(
            "INSERT INTO gastos_fondo_emergencia(referencia,importe_centavos) VALUES (?,?)",
            (referencia, total),
        )
        if adjunto:
            guardar_adjunto(db, referencia, adjunto, usuario)
        from reposicion_automatica import evaluar

        for id in ids:
            regla = db.execute(
                "SELECT 1 FROM reglas_reposicion WHERE producto_id=?", (id,)
            ).fetchone()
            if regla:
                db.execute(
                    "INSERT INTO campanas_reposicion VALUES (?,1) ON CONFLICT(producto_id) DO UPDATE SET activa=1",
                    (id,),
                )
        situaciones = [
            evaluar(db, id) or {"producto_id": id, "estado": "sin_regla"} for id in ids
        ]
        db.execute(
            "UPDATE compras_emergencia SET resultado_reposicion=? WHERE referencia=?",
            (json.dumps(situaciones, sort_keys=True), referencia),
        )
        auditar(
            db,
            "emergencia",
            referencia,
            "compra_emergencia_recibida",
            {
                "total_centavos": total,
                "productos": datos["productos"],
                "con_adjunto": bool(adjunto),
            },
        )
        return detalle_db(db, referencia)


def recibir(conectar_db, id, referencia, datos, usuario="compras"):
    datos = dict(datos)
    item = {k: datos.pop(k) for k in ("cantidad", "costo_unitario_centavos")}
    return recibir_compra(
        conectar_db,
        referencia,
        {**datos, "productos": [{"producto_id": id, **item}]},
        usuario,
    )


def consultar(conectar_db, referencia):
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        return detalle_db(db, referencia)


def adjuntar(conectar_db, referencia, datos, usuario):
    adjunto = preparar_adjunto(datos)
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        detalle_db(db, referencia)
        repetida = (
            db.execute(
                "SELECT 1 FROM comprobantes_emergencia WHERE referencia=?",
                (referencia,),
            ).fetchone()
            is not None
        )
        guardar_adjunto(db, referencia, adjunto, usuario)
        if not repetida:
            auditar(db, "emergencia", referencia, "comprobante_adjuntado")
        return {**detalle_db(db, referencia), "operacion_repetida": repetida}


def descargar(conectar_db, referencia):
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        detalle_db(db, referencia)
        fila = db.execute(
            "SELECT contenido,mime FROM comprobantes_emergencia WHERE referencia=?",
            (referencia,),
        ).fetchone()
        if fila is None:
            raise ProductoNoEncontradoError(
                "La compra todavía no tiene un archivo adjunto"
            )
        return dict(fila)


def listar(conectar_db, pagina, limite, pendientes=False):
    condicion = (
        " WHERE NOT EXISTS(SELECT 1 FROM comprobantes_emergencia a WHERE a.referencia=c.referencia)"
        if pendientes
        else ""
    )
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        total = db.execute(
            "SELECT COUNT(*) FROM compras_emergencia c" + condicion
        ).fetchone()[0]
        filas = db.execute(
            "SELECT c.* FROM compras_emergencia c"
            + condicion
            + " ORDER BY registrado_en DESC,referencia DESC LIMIT ? OFFSET ?",
            (limite, (pagina - 1) * limite),
        ).fetchall()
        return {
            "compras": [detalle_db(db, x["referencia"]) for x in filas],
            "total": total,
            "pagina": pagina,
            "limite": limite,
        }


def consultar_fondo(conectar_db, pagina, limite):
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row

        importes = db.execute("SELECT importe_centavos FROM gastos_fondo_emergencia")
        total = sum(x[0] for x in importes)
        cantidad = db.execute(
            "SELECT COUNT(*) FROM gastos_fondo_emergencia"
        ).fetchone()[0]
        filas = db.execute(
            "SELECT * FROM gastos_fondo_emergencia ORDER BY id DESC LIMIT ? OFFSET ?",
            (limite, (pagina - 1) * limite),
        )
        return {
            "fondo": "emergencias_reposicion",
            "disponibilidad": "asumida_suficiente_demo",
            "total_egresos_centavos": total,
            "movimientos": [dict(x) for x in filas],
            "total": cantidad,
            "pagina": pagina,
            "limite": limite,
        }
