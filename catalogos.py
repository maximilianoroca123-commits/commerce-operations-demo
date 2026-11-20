"""Supplier catalog ingestion, offer normalization and local product links."""

from auditoria_comercial import registrar as auditar

import json
import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation
from urllib.request import urlopen

from config import CATEGORIAS_VALIDAS
from errores import ProductoNoEncontradoError

PROVEEDORES = {
    "demo": "http://127.0.0.1:8001/catalogo",
    "demo-b": "http://127.0.0.1:8001/catalogo-b",
}
CATEGORIAS = {"tecnología": "tecnologia", "alimentos": "alimento"}


def descargar_catalogo(url):
    with urlopen(url, timeout=5) as respuesta:
        return json.load(respuesta, parse_float=Decimal)


def texto_obligatorio(fila, campo):
    valor = fila.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"{campo} obligatorio")
    return " ".join(valor.split())


def normalizar_oferta(fila):
    if not isinstance(fila, dict):
        raise ValueError("La fila debe ser un objeto")

    identificador = fila.get("id")
    if type(identificador) not in (str, int) or not str(identificador).strip():
        raise ValueError("id externo obligatorio")

    stock = fila.get("stock")
    if stock is None or (type(stock) is int and stock == 0):
        raise ValueError("sin stock")
    if type(stock) is not int or not 0 < stock <= 2**63 - 1:
        raise ValueError("stock inválido")

    try:
        costo = Decimal(str(fila.get("precio")))
    except InvalidOperation:
        raise ValueError("precio obligatorio o inválido") from None
    if not costo.is_finite() or not 0 < costo <= Decimal("92233720368547758.07"):
        raise ValueError("precio fuera de rango")
    if costo.as_tuple().exponent < -2:
        raise ValueError("precio con más de dos decimales")

    categoria = texto_obligatorio(fila, "categoria").casefold()
    categoria = CATEGORIAS.get(categoria, categoria)
    if categoria not in CATEGORIAS_VALIDAS:
        raise ValueError("categoría sin equivalencia local")

    return {
        "id_externo": str(identificador).strip(),
        "nombre": texto_obligatorio(fila, "nombre"),
        "marca": texto_obligatorio(fila, "marca"),
        "categoria": categoria,
        "costo_centavos": int(costo * 100),
        "stock_proveedor": stock,
    }


# A publication is a full catalog snapshot; omitted offers become inactive.
def guardar_catalogo(
    conectar_db, proveedor, catalogo, fuente="externo", respetar_publicado=False
):
    if not isinstance(catalogo, dict) or catalogo.get("moneda") != "ARS":
        raise ValueError("El catálogo debe declarar la moneda ARS")
    filas = catalogo.get("productos")
    if not isinstance(filas, list):
        raise ValueError("El catálogo debe incluir una lista de productos")

    resumen = {
        "recibidas": len(filas),
        "nuevas": 0,
        "actualizadas": 0,
        "sin_cambios": 0,
        "ofertas": [],
        "rechazos": [],
    }
    vistos = set()
    with closing(conectar_db()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if respetar_publicado:
            actual = db.execute(
                "SELECT modo FROM fuentes_catalogo WHERE proveedor=?", (proveedor,)
            ).fetchone()
            if actual and actual[0] == "publicado":
                return {
                    **resumen,
                    "omitido": "El proveedor publicó su catálogo directamente",
                }
        anterior_fuente = db.execute(
            "SELECT modo FROM fuentes_catalogo WHERE proveedor=?", (proveedor,)
        ).fetchone()
        if anterior_fuente is not None and anterior_fuente[0] != fuente:
            auditar(
                db,
                "proveedor",
                proveedor,
                "fuente_catalogo_cambiada",
                {"anterior": anterior_fuente[0], "nuevo": fuente},
            )
        db.execute(
            "INSERT INTO fuentes_catalogo(proveedor,modo) VALUES (?,?) ON CONFLICT(proveedor) DO UPDATE SET modo=excluded.modo",
            (proveedor, fuente),
        )
        antes = db.execute(
            "SELECT id_externo,nombre,marca,categoria,costo_centavos,stock_proveedor,vigente FROM ofertas_proveedor WHERE proveedor=? ORDER BY id_externo",
            (proveedor,),
        ).fetchall()

        db.execute(
            "UPDATE ofertas_proveedor SET vigente = 0 WHERE proveedor = ?", (proveedor,)
        )
        for numero, fila in enumerate(filas, start=1):
            try:
                oferta = normalizar_oferta(fila)
                id_externo = oferta["id_externo"]
                if id_externo in vistos:
                    raise ValueError("id externo repetido en el catálogo")
            except ValueError as error:
                resumen["rechazos"].append({"fila": numero, "motivo": str(error)})
                continue
            vistos.add(id_externo)

            valores = (
                oferta["nombre"],
                oferta["marca"],
                oferta["categoria"],
                oferta["costo_centavos"],
                oferta["stock_proveedor"],
            )
            anterior = db.execute(
                """SELECT nombre, marca, categoria, costo_centavos, stock_proveedor
                   FROM ofertas_proveedor WHERE proveedor = ? AND id_externo = ?""",
                (proveedor, id_externo),
            ).fetchone()
            if anterior == valores:
                resumen["sin_cambios"] += 1
            else:
                db.execute(
                    """INSERT INTO ofertas_proveedor
                       (proveedor, id_externo, nombre, marca, categoria,
                        costo_centavos, stock_proveedor)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(proveedor, id_externo) DO UPDATE SET
                           nombre = excluded.nombre, marca = excluded.marca,
                           categoria = excluded.categoria,
                           costo_centavos = excluded.costo_centavos,
                           stock_proveedor = excluded.stock_proveedor""",
                    (proveedor, id_externo, *valores),
                )
                estado = "nuevas" if anterior is None else "actualizadas"
                resumen[estado] += 1
            db.execute(
                "UPDATE ofertas_proveedor SET vigente = 1 WHERE proveedor = ? AND id_externo = ?",
                (proveedor, id_externo),
            )
            resumen["ofertas"].append(oferta)

        from reposicion_automatica import observar_stock

        stocks = {
            str(fila["id"]).strip(): fila["stock"]
            for fila in filas
            if isinstance(fila, dict)
            and type(fila.get("id")) in (str, int)
            and type(fila.get("stock")) is int
            and fila["stock"] >= 0
        }
        existentes = db.execute(
            "SELECT id_externo FROM versiones_stock_oferta WHERE proveedor=?",
            (proveedor,),
        ).fetchall()
        presentes = {
            str(fila.get("id")).strip()
            for fila in filas
            if isinstance(fila, dict) and "id" in fila
        }
        for (externo,) in existentes:
            if externo not in presentes:
                stocks[externo] = 0
        for externo, stock in stocks.items():
            observar_stock(db, proveedor, externo, stock)
        from datetime import datetime, timezone

        fecha = datetime.now(timezone.utc).isoformat()
        db.execute(
            """INSERT INTO catalogos_control(proveedor,actualizado_en,ultimo_intento,error)
            VALUES (?,?,?,NULL) ON CONFLICT(proveedor) DO UPDATE SET
            actualizado_en=excluded.actualizado_en,ultimo_intento=excluded.ultimo_intento,error=NULL""",
            (proveedor, fecha, fecha),
        )
        despues = db.execute(
            "SELECT id_externo,nombre,marca,categoria,costo_centavos,stock_proveedor,vigente FROM ofertas_proveedor WHERE proveedor=? ORDER BY id_externo",
            (proveedor,),
        ).fetchall()
        if antes != despues:
            auditar(
                db,
                "proveedor",
                proveedor,
                "catalogo_actualizado",
                {
                    "recibidas": resumen["recibidas"],
                    "nuevas": resumen["nuevas"],
                    "actualizadas": resumen["actualizadas"],
                    "rechazos": len(resumen["rechazos"]),
                },
            )
    return resumen


def listar_ofertas(conectar_db, proveedor):
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        filas = db.execute(
            """SELECT o.id_externo, o.nombre, o.marca, o.categoria,
                      o.costo_centavos, o.stock_proveedor, o.vigente, v.producto_id,
                      p.nombre AS producto_nombre, p.marca AS producto_marca
               FROM ofertas_proveedor o
               LEFT JOIN vinculos_oferta v USING (proveedor, id_externo)
               LEFT JOIN productos p ON p.id = v.producto_id
               WHERE o.proveedor = ?
               ORDER BY o.id_externo""",
            (proveedor,),
        )
        return [dict(fila) for fila in filas]


def vincular_oferta(conectar_db, proveedor, id_externo, producto_id):
    with closing(conectar_db()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if (
            db.execute(
                "SELECT 1 FROM ofertas_proveedor WHERE proveedor = ? AND id_externo = ?",
                (proveedor, id_externo),
            ).fetchone()
            is None
        ):
            raise ProductoNoEncontradoError("Oferta no encontrada")
        if (
            db.execute(
                "SELECT 1 FROM productos WHERE id = ?", (producto_id,)
            ).fetchone()
            is None
        ):
            raise ProductoNoEncontradoError("Producto local no encontrado")

        anterior = db.execute(
            "SELECT producto_id FROM vinculos_oferta WHERE proveedor=? AND id_externo=?",
            (proveedor, id_externo),
        ).fetchone()
        if anterior is None or anterior[0] != producto_id:
            auditar(
                db,
                "proveedor",
                proveedor,
                "oferta_vinculada",
                {
                    "id_externo": id_externo,
                    "producto_id": producto_id,
                    "producto_anterior": anterior[0] if anterior else None,
                },
            )
        db.execute(
            """INSERT INTO vinculos_oferta (proveedor, id_externo, producto_id)
               VALUES (?, ?, ?)
               ON CONFLICT (proveedor, id_externo) DO UPDATE
               SET producto_id = excluded.producto_id""",
            (proveedor, id_externo, producto_id),
        )
        return {
            "proveedor": proveedor,
            "id_externo": id_externo,
            "producto_id": producto_id,
        }
