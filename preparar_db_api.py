# Additive database preparation and initial product seeding when empty.


import sqlite3

from pedidos_venta import crear_tablas, sincronizar_cobro, sincronizar_venta_directa

from config import RUTA_DB_API

productos_iniciales = [
    {
        "nombre": "Mouse",
        "categoria": "tecnologia",
        "precio": 8500,
        "stock": 7,
        "marca": "TecnoSur",
    },
    {
        "nombre": "teclado",
        "categoria": "tecnologia",
        "precio": 7500,
        "stock": 5,
        "marca": "TecnoSur",
    },
    {
        "nombre": "Pan",
        "categoria": "alimento",
        "precio": 7000,
        "stock": 12,
        "marca": "Pan del Barrio",
    },
]


def crear_tabla_productos_api(conexion):
    cursor = conexion.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT,
        categoria TEXT,
        precio INTEGER NOT NULL CHECK (precio > 0),
        stock INTEGER NOT NULL CHECK (stock >= 0),
        marca TEXT
        )
        """)


def preparar_db_api():
    from auditoria_comercial import habilitada, crear_tablas as crear_auditoria

    conexion = sqlite3.connect(RUTA_DB_API)
    token = habilitada.set(False)
    try:
        with conexion:

            conexion.execute("BEGIN IMMEDIATE")
            crear_auditoria(conexion)
            crear_tabla_productos_api(conexion)
            columnas = conexion.execute("PRAGMA table_info(productos)")
            if "marca" not in {columna[1] for columna in columnas}:
                conexion.execute("ALTER TABLE productos ADD COLUMN marca TEXT")

                conexion.executemany(
                    """
                    UPDATE productos SET marca = :marca
                    WHERE nombre = :nombre AND categoria = :categoria
                      AND precio = :precio AND stock = :stock
                    """,
                    productos_iniciales,
                )

            conexion.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS indice_productos_nombre_unico
                ON productos (LOWER(nombre))
                """)
            conexion.execute("""
                CREATE TABLE IF NOT EXISTS ofertas_proveedor (
                    proveedor TEXT NOT NULL,
                    id_externo TEXT NOT NULL,
                    nombre TEXT NOT NULL,
                    marca TEXT NOT NULL,
                    categoria TEXT NOT NULL,
                    costo_centavos INTEGER NOT NULL CHECK (costo_centavos > 0),
                    stock_proveedor INTEGER NOT NULL CHECK (stock_proveedor > 0),
                    PRIMARY KEY (proveedor, id_externo)
                )
                """)
            conexion.execute("""
                CREATE TABLE IF NOT EXISTS vinculos_oferta (
                    proveedor TEXT NOT NULL,
                    id_externo TEXT NOT NULL,
                    producto_id INTEGER NOT NULL,
                    PRIMARY KEY (proveedor, id_externo),
                    FOREIGN KEY (proveedor, id_externo)
                        REFERENCES ofertas_proveedor (proveedor, id_externo)
                        ON DELETE CASCADE,
                    FOREIGN KEY (producto_id) REFERENCES productos (id)
                        ON DELETE CASCADE
                )
                """)
            columnas_oferta = conexion.execute("PRAGMA table_info(ofertas_proveedor)")
            if "vigente" not in {columna[1] for columna in columnas_oferta}:
                conexion.execute(
                    "ALTER TABLE ofertas_proveedor ADD COLUMN vigente INTEGER "
                    "NOT NULL DEFAULT 0 CHECK (vigente IN (0, 1))"
                )
            conexion.execute("""
                CREATE TABLE IF NOT EXISTS pedidos_reposicion (
                    id INTEGER PRIMARY KEY,
                    producto_id INTEGER NOT NULL REFERENCES productos(id),
                    proveedor TEXT NOT NULL,
                    id_externo TEXT NOT NULL,
                    cantidad INTEGER NOT NULL CHECK (cantidad > 0),
                    costo_ofertado_centavos INTEGER NOT NULL,
                    costo_pagado_centavos INTEGER CHECK (costo_pagado_centavos > 0),
                    recibido_en TEXT,
                    cancelado_en TEXT
                )
                """)
            columnas_pedido = {
                columna[1]
                for columna in conexion.execute("PRAGMA table_info(pedidos_reposicion)")
            }
            if "cancelado_en" not in columnas_pedido:
                conexion.execute(
                    "ALTER TABLE pedidos_reposicion ADD COLUMN cancelado_en TEXT"
                )
                conexion.execute("DROP INDEX IF EXISTS pedido_pendiente_por_producto")
            if "cerrado_incompleto_en" not in columnas_pedido:
                conexion.execute(
                    "ALTER TABLE pedidos_reposicion ADD COLUMN cerrado_incompleto_en TEXT"
                )
                conexion.execute("DROP INDEX IF EXISTS pedido_pendiente_por_producto")
            conexion.execute("DROP INDEX IF EXISTS pedido_pendiente_por_producto")
            conexion.execute("""
                CREATE INDEX IF NOT EXISTS pedidos_abiertos_producto
                ON pedidos_reposicion (producto_id)
                WHERE recibido_en IS NULL AND cancelado_en IS NULL AND cerrado_incompleto_en IS NULL
                """)
            if "cantidad_recibida" not in columnas_pedido:
                conexion.execute("""
                    ALTER TABLE pedidos_reposicion ADD COLUMN cantidad_recibida
                    INTEGER NOT NULL DEFAULT 0 CHECK (cantidad_recibida BETWEEN 0 AND cantidad)
                    """)
                conexion.execute("""
                    UPDATE pedidos_reposicion SET cantidad_recibida = cantidad
                    WHERE recibido_en IS NOT NULL
                    """)
            conexion.execute("""
                CREATE TABLE IF NOT EXISTS recepciones_pedido (
                    pedido_id INTEGER NOT NULL REFERENCES pedidos_reposicion(id),
                    referencia TEXT NOT NULL,
                    cantidad INTEGER NOT NULL CHECK (cantidad > 0),
                    costo_pagado_centavos INTEGER NOT NULL CHECK (costo_pagado_centavos > 0),
                    registrado_en TEXT NOT NULL,
                    PRIMARY KEY (pedido_id, referencia)
                )
                """)
            conexion.execute("""
                CREATE TABLE IF NOT EXISTS correcciones_recepcion (
                    pedido_id INTEGER NOT NULL,
                    referencia TEXT NOT NULL,
                    correccion TEXT NOT NULL,
                    cantidad_anterior INTEGER NOT NULL,
                    costo_anterior_centavos INTEGER NOT NULL,
                    cantidad INTEGER NOT NULL,
                    costo_pagado_centavos INTEGER NOT NULL,
                    motivo TEXT NOT NULL,
                    registrado_en TEXT NOT NULL,
                    PRIMARY KEY (pedido_id, referencia, correccion),
                    FOREIGN KEY (pedido_id, referencia)
                        REFERENCES recepciones_pedido (pedido_id, referencia)
                )
                """)
            conexion.execute("""
                CREATE TABLE IF NOT EXISTS ventas (
                    referencia TEXT PRIMARY KEY NOT NULL,
                    producto_id INTEGER NOT NULL REFERENCES productos(id),
                    cantidad INTEGER NOT NULL CHECK (cantidad > 0),
                    precio_unitario INTEGER NOT NULL CHECK (precio_unitario > 0),
                    stock_restante INTEGER NOT NULL CHECK (stock_restante >= 0),
                    registrado_en TEXT NOT NULL
                )
                """)
            conexion.execute("""
                CREATE TABLE IF NOT EXISTS cobros_demo (
                    referencia TEXT PRIMARY KEY NOT NULL,
                    total INTEGER NOT NULL CHECK (total > 0),
                    estado TEXT NOT NULL CHECK (estado IN ('pendiente', 'aprobado', 'rechazado')),
                    resuelto_en TEXT
                )
                """)
            conexion.execute("""
                CREATE TABLE IF NOT EXISTS items_cobro (
                    referencia TEXT NOT NULL REFERENCES cobros_demo(referencia),
                    producto_id INTEGER NOT NULL REFERENCES productos(id),
                    nombre TEXT NOT NULL,
                    cantidad INTEGER NOT NULL CHECK (cantidad > 0),
                    precio_unitario INTEGER NOT NULL CHECK (precio_unitario > 0),
                    PRIMARY KEY (referencia, producto_id)
                )
                """)
            columnas_cobro = {
                c[1] for c in conexion.execute("PRAGMA table_info(cobros_demo)")
            }
            if "reserva_activa" not in columnas_cobro:
                conexion.execute(
                    "ALTER TABLE cobros_demo ADD COLUMN reserva_activa INTEGER NOT NULL DEFAULT 0"
                )
                conexion.execute("ALTER TABLE cobros_demo ADD COLUMN vence_en TEXT")
                conexion.execute(
                    "ALTER TABLE cobros_demo ADD COLUMN estado_operacion TEXT NOT NULL DEFAULT 'pendiente'"
                )
                conexion.execute("UPDATE cobros_demo SET estado_operacion = estado")
            if "reserva_activa" not in columnas_cobro:
                conexion.execute("""
                    UPDATE cobros_demo SET estado = 'rechazado', estado_operacion = 'vencido'
                    WHERE estado = 'pendiente'
                    """)
            conexion.execute("""
                CREATE TABLE IF NOT EXISTS proveedor_pagos_demo (
                    referencia TEXT PRIMARY KEY REFERENCES cobros_demo(referencia),
                    estado TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 0,
                    disponible INTEGER NOT NULL DEFAULT 1,
                    reembolso TEXT
                )
                """)
            conexion.execute("""
                INSERT OR IGNORE INTO proveedor_pagos_demo (referencia, estado)
                SELECT referencia, CASE WHEN estado_operacion = 'vencido' THEN 'vencido' ELSE estado END FROM cobros_demo
                """)
            conexion.execute("""
                CREATE TABLE IF NOT EXISTS eventos_pago_demo (
                    referencia TEXT NOT NULL REFERENCES cobros_demo(referencia),
                    evento TEXT NOT NULL,
                    estado TEXT NOT NULL,
                    PRIMARY KEY (referencia, evento)
                )
                """)
            columnas_cobro = {
                c[1] for c in conexion.execute("PRAGMA table_info(cobros_demo)")
            }
            if "canal" not in columnas_cobro:
                conexion.execute(
                    "ALTER TABLE cobros_demo ADD COLUMN canal TEXT NOT NULL DEFAULT 'presencial'"
                )
                conexion.execute(
                    "ALTER TABLE cobros_demo ADD COLUMN modalidad TEXT NOT NULL DEFAULT 'local'"
                )
            crear_tablas(conexion)
            from usuarios import crear_tablas as crear_usuarios

            crear_usuarios(conexion)
            from devoluciones import crear_tablas as crear_devoluciones

            crear_devoluciones(conexion)
            from caja_efectivo import crear_tablas as crear_caja_efectivo

            crear_caja_efectivo(conexion)
            for (referencia,) in conexion.execute(
                "SELECT referencia FROM ventas"
            ).fetchall():
                sincronizar_venta_directa(conexion, referencia)
            for (referencia,) in conexion.execute(
                "SELECT referencia FROM cobros_demo"
            ).fetchall():
                sincronizar_cobro(conexion, referencia)
            from movimientos_inventario import (
                crear_tablas as crear_movimientos,
                iniciar_saldos,
                siguiente_id,
            )

            crear_movimientos(conexion)
            if conexion.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 0:
                for producto in productos_iniciales:
                    conexion.execute(
                        """INSERT INTO productos (id,nombre,categoria,precio,stock,marca)
                        VALUES (:id,:nombre,:categoria,:precio,:stock,:marca)""",
                        {**producto, "id": siguiente_id(conexion)},
                    )
            iniciar_saldos(conexion)
            from reposicion_automatica import (
                crear_tablas as crear_reposicion_automatica,
            )

            crear_reposicion_automatica(conexion)
            from reposicion_emergencia import crear_tabla as crear_emergencias

            crear_emergencias(conexion)
            from reposicion_simulada import crear_tablas as crear_simulacion

            crear_simulacion(conexion)
    finally:
        conexion.close()
        habilitada.reset(token)


if __name__ == "__main__":
    preparar_db_api()
