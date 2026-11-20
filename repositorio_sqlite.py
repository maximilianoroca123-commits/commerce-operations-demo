# SQLite product storage and inventory-aware product changes.
from movimientos_inventario import registrar as registrar_movimiento


from auditoria_comercial import registrar as auditar

import sqlite3

from config import RUTA_DB_API
from inventario_reservas import reservado
from ventas import ConflictoVentaError
from errores import ProductoDuplicadoError, ProductoNoEncontradoError, ErrorPersistencia
from logica_productos import aplicar_cambios_producto, construir_producto


def conectar_db():
    try:
        conexion = sqlite3.connect(RUTA_DB_API)
        try:
            conexion.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error:
            conexion.close()
            raise
        return conexion
    except sqlite3.OperationalError as error:
        raise ErrorPersistencia("No se pudo conectar con la base de datos") from error


def fila_a_producto(fila):
    if fila is None:
        return None
    nuevo_diccionario = {
        "id": fila[0],
        "nombre": fila[1],
        "categoria": fila[2],
        "precio": fila[3],
        "stock": fila[4],
        "marca": fila[5],
    }
    return nuevo_diccionario


def obtener_producto_por_id(id):
    conexion = conectar_db()
    try:
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT id, nombre, categoria, precio, stock, marca FROM productos WHERE id = ?",
            (id,),
        )
        fila = cursor.fetchone()
        producto = fila_a_producto(fila)
        return producto
    except sqlite3.OperationalError as error:
        raise ErrorPersistencia("No se pudo consultar el producto") from error
    finally:
        conexion.close()


def obtener_producto_por_nombre(nombre):
    conexion = conectar_db()
    try:
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT id, nombre, categoria, precio, stock, marca FROM productos WHERE LOWER(nombre) = ?",
            (nombre.lower(),),
        )
        fila = cursor.fetchone()
        producto = fila_a_producto(fila)
        return producto
    except sqlite3.OperationalError as error:
        raise ErrorPersistencia(
            "No se pudo consultar el producto por nombre"
        ) from error
    finally:
        conexion.close()


def obtener_todos_los_productos():
    conexion = conectar_db()
    try:
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT id, nombre, categoria, precio, stock, marca FROM productos"
        )
        filas = cursor.fetchall()
        productos = []
        for fila in filas:
            producto = fila_a_producto(fila)
            productos.append(producto)
        return productos
    except sqlite3.OperationalError as error:
        raise ErrorPersistencia("No se pudo obtener los productos") from error
    finally:
        conexion.close()


def crear_producto(nombre, categoria, precio, stock, marca=None):
    conexion = conectar_db()
    try:
        conexion.execute("BEGIN IMMEDIATE")
        from movimientos_inventario import siguiente_id

        nuevo_id = siguiente_id(conexion)
        cursor = conexion.cursor()
        cursor.execute(
            """
                INSERT INTO productos (id, nombre, categoria, precio, stock, marca)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
            (nuevo_id, nombre, categoria, precio, stock, marca),
        )
        registrar_movimiento(
            conexion, nuevo_id, "alta", str(nuevo_id), stock, "Alta del producto"
        )
        auditar(
            conexion,
            "producto",
            nuevo_id,
            "producto_creado",
            {"precio_pesos": precio, "stock": stock},
        )
        conexion.commit()
        nuevo_id = cursor.lastrowid
        producto = construir_producto(nuevo_id, nombre, categoria, precio, stock, marca)
        return producto
    except sqlite3.IntegrityError as error:
        if "indice_productos_nombre_unico" in str(error):
            raise ProductoDuplicadoError("El producto ya existe") from error
        raise ErrorPersistencia(
            "Error interno, no se pudo realizar la operacion"
        ) from error
    except sqlite3.OperationalError as error:
        raise ErrorPersistencia("No se pudo crear el producto") from error
    finally:
        conexion.close()


def guardar_producto_actualizado(producto_id, cambios):
    conexion = conectar_db()
    try:
        conexion.execute("BEGIN IMMEDIATE")
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT id, nombre, categoria, precio, stock, marca FROM productos WHERE id = ?",
            (producto_id,),
        )
        existente = fila_a_producto(cursor.fetchone())
        if existente is None:
            raise ProductoNoEncontradoError("Producto no encontrado")
        producto_actualizado = aplicar_cambios_producto(existente, cambios)
        if producto_actualizado["stock"] < reservado(conexion, producto_id):
            raise ConflictoVentaError(
                "El stock no puede quedar por debajo de las unidades reservadas"
            )
        cursor.execute(
            """
                UPDATE productos
                SET precio = ?, stock = ?, marca = ?
                WHERE id = ?
                """,
            (
                producto_actualizado["precio"],
                producto_actualizado["stock"],
                producto_actualizado["marca"],
                producto_actualizado["id"],
            ),
        )
        cantidad_filas = cursor.rowcount
        if cantidad_filas == 0:
            raise ProductoNoEncontradoError("Producto no encontrado")
        diferencia = producto_actualizado["stock"] - existente["stock"]
        if diferencia:
            from uuid import uuid4

            registrar_movimiento(
                conexion,
                producto_id,
                "ajuste_manual",
                uuid4().hex,
                diferencia,
                cambios.get("motivo_stock") or "Ajuste manual de existencias",
            )
        diferencias = {
            k: {"anterior": existente[k], "nuevo": producto_actualizado[k]}
            for k in ("precio", "stock", "marca")
            if existente[k] != producto_actualizado[k]
        }
        if diferencias:
            auditar(
                conexion, "producto", producto_id, "producto_actualizado", diferencias
            )
        conexion.commit()
        return producto_actualizado
    except sqlite3.OperationalError as error:
        raise ErrorPersistencia("No se pudo actualizar el producto") from error
    except sqlite3.IntegrityError as error:
        raise ErrorPersistencia(
            "Error interno, no se pudo realizar la operacion"
        ) from error
    finally:
        conexion.close()


def eliminar_producto(id):
    conexion = conectar_db()
    try:
        cursor = conexion.cursor()
        conexion.execute("BEGIN IMMEDIATE")
        anterior = conexion.execute(
            "SELECT stock FROM productos WHERE id=?", (id,)
        ).fetchone()
        if anterior is None:
            raise ProductoNoEncontradoError("Producto no encontrado")
        conexion.execute("UPDATE productos SET stock=0 WHERE id=?", (id,))
        registrar_movimiento(
            conexion, id, "baja", str(id), -anterior[0], "Baja del producto"
        )
        cursor.execute("DELETE FROM productos WHERE id = ?", (id,))
        cantidad_filas = cursor.rowcount
        if cantidad_filas == 0:
            raise ProductoNoEncontradoError("Producto no encontrado")
        auditar(
            conexion,
            "producto",
            id,
            "producto_eliminado",
            {"stock_anterior": anterior[0]},
        )
        conexion.commit()
    except sqlite3.OperationalError as error:
        raise ErrorPersistencia("No se pudo eliminar el producto") from error
    finally:
        conexion.close()


def obtener_productos_paginados(
    pagina,
    limite,
    categoria: str | None = None,
    precio_min: int | None = None,
    precio_max: int | None = None,
    texto: str | None = None,
):
    offset = (pagina - 1) * limite
    conexion = conectar_db()
    try:
        cursor = conexion.cursor()
        cursor.execute(
            """
                SELECT id, nombre, categoria, precio, stock, marca
                FROM productos
                WHERE (? IS NULL OR categoria = ?)
                AND (? IS NULL OR precio >= ?)
                AND (? IS NULL OR precio <= ?)
                AND (? IS NULL OR instr(LOWER(nombre), LOWER(?)) > 0
                               OR instr(LOWER(marca), LOWER(?)) > 0)
                ORDER BY id ASC
                LIMIT ? OFFSET ?
                """,
            (
                categoria,
                categoria,
                precio_min,
                precio_min,
                precio_max,
                precio_max,
                texto,
                texto,
                texto,
                limite,
                offset,
            ),
        )
        filas = cursor.fetchall()
        productos = []
        for fila in filas:
            producto = fila_a_producto(fila)
            productos.append(producto)
        return productos
    except sqlite3.OperationalError as error:
        raise ErrorPersistencia("No se pudo listar los productos") from error
    finally:
        conexion.close()


def contar_productos(
    categoria: str | None = None,
    precio_min: int | None = None,
    precio_max: int | None = None,
    texto: str | None = None,
):
    conexion = conectar_db()
    try:
        cursor = conexion.cursor()
        cursor.execute(
            """
                SELECT COUNT(*) FROM productos
                WHERE (? IS NULL OR categoria = ?)
                AND (? IS NULL OR precio >= ?)
                AND (? IS NULL OR precio <= ?)
                AND (? IS NULL OR instr(LOWER(nombre), LOWER(?)) > 0
                               OR instr(LOWER(marca), LOWER(?)) > 0)
                """,
            (
                categoria,
                categoria,
                precio_min,
                precio_min,
                precio_max,
                precio_max,
                texto,
                texto,
                texto,
            ),
        )
        fila = cursor.fetchone()
        total = fila[0]
        return total
    except sqlite3.OperationalError as error:
        raise ErrorPersistencia("No se pudo contar los productos") from error
    finally:
        conexion.close()
