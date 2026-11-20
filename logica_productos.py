# Product construction and controlled partial updates.


def construir_producto(id, nombre, categoria, precio, stock, marca=None):
    nuevo_producto = {
        "id": id,
        "nombre": nombre,
        "categoria": categoria,
        "precio": precio,
        "stock": stock,
        "marca": marca,
    }
    return nuevo_producto


def aplicar_cambios_producto(producto, cambios):
    producto_actualizado = producto.copy()
    if "stock" in cambios:
        producto_actualizado["stock"] = cambios["stock"]
    if "precio" in cambios:
        producto_actualizado["precio"] = cambios["precio"]
    if "marca" in cambios:
        producto_actualizado["marca"] = cambios["marca"]
    return producto_actualizado
