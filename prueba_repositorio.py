# Manual development checks for repository operations.


from repositorio_sqlite import conectar_db


def comprobar_nombres_duplicados():
    conexion = conectar_db()
    try:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT LOWER(nombre), COUNT(*)
            FROM productos
            GROUP BY LOWER(nombre)
            HAVING COUNT(*) > 1
            """)
        resultados = cursor.fetchall()
        print(resultados)
    finally:
        conexion.close()


def comprobar_precios_y_stock():
    conexion = conectar_db()
    try:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT id, nombre, precio, stock
            FROM productos
            WHERE precio IS NULL OR precio <= 0
            OR stock IS NULL OR stock < 0
            """)
        resultado = cursor.fetchall()
        return resultado
    finally:
        conexion.close()


if __name__ == "__main__":
    print("Nombres duplicados:")
    comprobar_nombres_duplicados()
    print("Productos con precio o stock inválidos:", comprobar_precios_y_stock())
