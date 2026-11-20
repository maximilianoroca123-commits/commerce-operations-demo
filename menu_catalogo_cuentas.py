"""Historical console client module for the existing HTTP business operations."""

from urllib.parse import urlencode, quote
from mensajes import etiqueta
from validaciones import pedir_opcion
from menu_cuentas import api


def seleccionar(sesion, ruta, clave, mostrar, abrir, parametros=None):
    pagina = 1
    while True:
        consulta = urlencode({**(parametros or {}), "pagina": pagina, "limite": 10})
        r = api(sesion, "GET", ruta + "?" + consulta)
        if r is None:
            return
        filas = r[clave]
        if not filas:
            print("No hay resultados para esta página.")
            return
        for n, x in enumerate(filas, 1):
            print(f"{n}. " + mostrar(x))
        opciones = ["0", *[str(n) for n in range(1, len(filas) + 1)]]
        if pagina * 10 < r["total"]:
            opciones.append("s")
            print("s. Siguiente página")
        if pagina > 1:
            opciones.append("a")
            print("a. Página anterior")
        op = pedir_opcion("Elegí una fila (0 vuelve al sector): ", opciones)
        if op == "0":
            return
        if op == "s":
            pagina += 1
            continue
        if op == "a":
            pagina -= 1
            continue
        abrir(sesion, filas[int(op) - 1])


def productos(sesion, texto=None):
    seleccionar(
        sesion,
        "/productos",
        "productos",
        lambda p: f'{p["id"]} | {p["nombre"]} | {p["marca"] or "Sin marca"} | ${p["precio"]} | Stock: {p["stock"]}',
        lambda sesion, p: producto(sesion, p["id"]),
        {"texto": texto} if texto else {},
    )


def historial_producto(sesion, id):
    from menu_cuentas import mostrar_detalle_historial

    pagina = 1
    while True:
        r = api(
            sesion,
            "GET",
            f"/auditoria/comercial/producto/{id}?pagina={pagina}&limite=10",
        )
        if r is None:
            return
        for x in r["movimientos"]:
            print(f'{x["registrado_en"]} UTC | {etiqueta(x["accion"])} | {x["actor"]}')
            mostrar_detalle_historial(x["detalle"])
        if not r["movimientos"]:
            print("No hay cambios registrados desde que se incorporó el historial.")
        if (
            pagina * 10 >= r["total"]
            or pedir_opcion("¿Siguiente página? (s/n): ", ["s", "n"]) == "n"
        ):
            return
        pagina += 1


def producto(sesion, id):
    from menu_api import (
        modificar_catalogo,
        consultar_movimientos,
        configurar_regla_reposicion,
        generar_pedido,
    )
    from menu_cuentas import mostrar_detalle_historial

    etiquetas = {
        "1": ("detalle", "Ver detalle"),
        "2": ("editar", "Editar marca, precio o stock"),
        "3": ("movimientos", "Ver movimientos de inventario"),
        "4": ("regla", "Consultar regla de reposición"),
        "5": ("configurar", "Configurar regla de reposición"),
        "6": ("reponer", "Evaluar y solicitar reposición"),
        "7": ("historial", "Ver responsables de cambios"),
        "8": ("eliminar", "Eliminar producto"),
    }
    while True:
        c = api(sesion, "GET", f"/operaciones/productos/{id}")
        if c is None:
            return
        p = c["producto"]
        print(
            f'\nProducto {id}: {p["nombre"]} | Precio: ${p["precio"]} | Stock físico: {p["stock"]}'
        )
        print(
            f'Reservadas: {c["reservadas"]} | Disponibles: {c["disponible"]} | Por recibir: {c["por_recibir"]}'
        )
        opciones = {n: x for n, x in etiquetas.items() if x[0] in c["acciones"]}
        for n, (_, texto) in opciones.items():
            print(n + ". " + texto)
        op = pedir_opcion(
            "Acción del producto (0 vuelve a la lista): ", ["0", *opciones]
        )
        if op == "0":
            return
        accion = opciones[op][0]
        if accion == "detalle":
            print(f'Marca: {p["marca"] or "Sin marca"} | Categoría: {p["categoria"]}')
        elif accion == "movimientos":
            consultar_movimientos(sesion, producto_id=id)
        elif accion == "editar":
            modificar_catalogo(sesion, "4", id_producto=id)
        elif accion == "eliminar":
            if modificar_catalogo(sesion, "5", id_producto=id):
                return
        elif accion == "regla":
            if c["regla"]:
                mostrar_detalle_historial(c["regla"])
            else:
                print("Este producto no tiene una regla configurada.")
        elif accion == "configurar":
            configurar_regla_reposicion(sesion, id=id)
        elif accion == "reponer":
            print(
                "Esta evaluación puede generar pedidos según el stock, ofertas y regla configurada."
            )
            if (
                pedir_opcion("¿Evaluar y solicitar reposición? (s/n): ", ["s", "n"])
                == "s"
            ):
                generar_pedido(sesion, producto_id=id)
        else:
            historial_producto(sesion, id)


def cuentas(sesion):
    seleccionar(
        sesion,
        "/usuarios",
        "usuarios",
        lambda u: f'{u["usuario"]} | {etiqueta(u["rol"])} | '
        + ("Activa" if u["activo"] else "Desactivada"),
        lambda sesion, u: cuenta(sesion, u["usuario"]),
    )


def cuenta(sesion, nombre):
    from menu_cuentas import restablecer_clave, historial_cuentas

    ruta = "/usuarios/" + quote(nombre, safe="")
    etiquetas = {
        "1": ("detalle", "Consultar cuenta"),
        "2": ("historial", "Historial de cambios"),
        "3": ("desactivar", "Desactivar cuenta"),
        "4": ("activar", "Activar cuenta"),
        "5": ("restablecer", "Restablecer contraseña olvidada"),
    }
    while True:
        c = api(sesion, "GET", ruta)
        if c is None:
            return
        u = c["cuenta"]
        print(
            f'\nCuenta: {nombre} | {etiqueta(u["rol"])} | '
            + ("Activa" if u["activo"] else "Desactivada")
        )
        if c["es_propia"]:
            print(
                "Es tu cuenta actual. Cambiá tu contraseña desde la opción 37; no se permite desactivarla o restablecerla desde aquí."
            )
        opciones = {n: x for n, x in etiquetas.items() if x[0] in c["acciones"]}
        for n, (_, texto) in opciones.items():
            print(n + ". " + texto)
        op = pedir_opcion(
            "Acción de esta cuenta (0 vuelve a la lista): ", ["0", *opciones]
        )
        if op == "0":
            return
        accion = opciones[op][0]
        if accion == "detalle":
            print(
                f'Cliente: {u["cliente_id"] or "No corresponde"} | Proveedor: {u["proveedor"] or "No corresponde"}'
            )
            print(
                "Cambio de contraseña temporal pendiente: "
                + ("Sí" if u["debe_cambiar_clave"] else "No")
            )
            print("Creada: " + u["creado_en"])
        elif accion == "historial":
            historial_cuentas(sesion, nombre=nombre)
        elif accion == "restablecer":
            restablecer_clave(sesion, nombre=nombre)
        else:
            activo = accion == "activar"
            if (
                pedir_opcion(f"¿Confirmar {accion} {nombre}? (s/n): ", ["s", "n"])
                == "s"
            ):
                r = api(sesion, "PUT", ruta + "/estado", {"activo": activo})
                if r:
                    print(
                        "Estado actualizado; se conservan su identidad y operaciones."
                    )
