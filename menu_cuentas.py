"""Historical console client module for the existing HTTP business operations."""

import json
from getpass import getpass
from pathlib import Path
from uuid import uuid4
from validaciones import pedir_opcion, pedir_numero


def api(sesion, metodo, ruta, datos=None):
    from menu_api import solicitar_compras

    return solicitar_compras(sesion, metodo, ruta, datos)


def crear_cuenta(sesion):
    nombre = input(
        "Usuario (minúsculas, 3 a 40 letras/números/guiones; empieza con letra): "
    ).strip()
    rol = pedir_opcion(
        "Rol (administrador/empleado/cliente/proveedor): ",
        ["administrador", "empleado", "cliente", "proveedor"],
    )
    clave = getpass(
        "Contraseña nueva (10 a 128 caracteres, sin tildes/ñ; no se muestra): "
    )
    if clave != getpass("Repetí la contraseña: "):
        print("Las contraseñas no coinciden. No se creó la cuenta.")
        return
    datos = {"usuario": nombre, "rol": rol, "clave": clave}
    if rol == "cliente":
        datos["cliente"] = {
            "nombre": input("Nombre: ").strip(),
            "apellido": input("Apellido: ").strip(),
            "correo": input("Correo (no se verifica por correo todavía): ").strip(),
            "telefono": input("Teléfono opcional (Enter omite): ").strip() or None,
        }
    if rol == "proveedor":
        datos["proveedor"] = pedir_opcion(
            "Proveedor asociado (demo/demo-b): ", ["demo", "demo-b"]
        )
    if (
        pedir_opcion(f"¿Crear la cuenta {nombre} con rol {rol}? (s/n): ", ["s", "n"])
        == "n"
    ):
        return
    r = api(sesion, "POST", "/usuarios", datos)
    if r:
        print(
            f'Cuenta creada: {r["usuario"]} | Rol: {r["rol"]} | Cliente: {r["cliente_id"] or "no corresponde"}'
        )


def listar_cuentas(sesion):
    pagina = 1
    while True:
        r = api(sesion, "GET", f"/usuarios?pagina={pagina}&limite=20")
        if r is None:
            return
        for u in r["usuarios"]:
            print(
                f'{u["usuario"]} | {u["rol"]} | {"Activa" if u["activo"] else "Desactivada"} | Cliente: {u["cliente_id"]} | Proveedor: {u["proveedor"]} | Cambio de contraseña pendiente: {"sí" if u.get("debe_cambiar_clave") else "no"}'
            )
        if (
            pagina * 20 >= r["total"]
            or pedir_opcion("¿Siguiente página? (s/n): ", ["s", "n"]) == "n"
        ):
            return
        pagina += 1


def activar_cuenta(sesion):
    nombre = input("Usuario a activar/desactivar: ").strip()
    activo = pedir_opcion("¿Debe quedar activo? (s/n): ", ["s", "n"]) == "s"
    r = api(sesion, "PUT", f"/usuarios/{nombre}/estado", {"activo": activo})
    if r:
        print("Estado actualizado. Los nuevos accesos se comprobarán con este estado.")


def cambiar_clave(sesion):
    actual = getpass("Contraseña actual: ")
    nueva = getpass("Contraseña nueva (10 a 128 caracteres, sin tildes/ñ): ")
    if nueva != getpass("Repetí la nueva contraseña: "):
        print("Las contraseñas no coinciden.")
        return
    r = api(sesion, "PUT", "/mi-cuenta/clave", {"actual": actual, "nueva": nueva})
    if r:
        sesion.auth = (sesion.auth[0], nueva)
        print(r["mensaje"])
        return True
    return False


def listar_mis_pedidos(sesion):
    from menu_pedidos_cliente import mis_pedidos

    mis_pedidos(sesion)


def comprar_online(sesion):
    ref = (
        input(
            "Referencia de compra (Enter genera una; guardala para reintentar): "
        ).strip()
        or uuid4().hex
    )
    productos = []
    while True:
        productos.append(
            {
                "producto_id": pedir_numero("ID del producto: "),
                "cantidad": pedir_numero("Cantidad: "),
            }
        )
        if pedir_opcion("¿Agregar otro producto? (s/n): ", ["s", "n"]) == "n":
            break
    modalidad = pedir_opcion("Entrega (retiro/envio): ", ["retiro", "envio"])
    datos = {"productos": productos, "canal": "online", "modalidad": modalidad}
    if modalidad == "envio":
        datos["direccion_entrega"] = input(
            "Dirección completa (calle, número, localidad y referencia): "
        ).strip()
    print(f"Referencia que debés conservar: {ref}")
    r = api(sesion, "PUT", f"/cobros-demo/{ref}", datos)
    if r:
        print(
            f'Pedido {r["pedido_venta_id"]} | Total calculado por el negocio: ${r["total"]} | Pago: {r["estado"]}'
        )
        print(
            "Este paso reserva mercadería. Para continuar entrá a Mis pedidos → 4 y elegí este pedido; no se cobra dinero real."
        )


def pagar_online(sesion, referencia=None):
    ref = (
        referencia
        if referencia is not None
        else input("Referencia de tu compra: ").strip()
    )
    opcion = pedir_opcion("Pago de prueba: 1. Aprobar / 2. Rechazar: ", ["1", "2"])
    r = api(
        sesion,
        "PUT",
        f"/cobros-demo/{ref}/pago",
        {"estado": "aprobado" if opcion == "1" else "rechazado"},
    )
    if r:
        from mensajes import etiqueta

        print(
            f'Pago simulado: {etiqueta(r["estado"])}. Consultá el pedido {r["pedido_venta_id"]} para seguir la entrega.'
        )


def solicitar_gestion(sesion, pedido_id=None, tipo=None):
    id = pedido_id if pedido_id is not None else pedir_numero("ID de tu pedido: ")
    ref = (
        uuid4().hex
        if pedido_id is not None
        else input("Referencia de solicitud (Enter genera una): ").strip()
        or uuid4().hex
    )
    tipo = tipo or pedir_opcion(
        "Solicitud (devolucion/cancelacion): ", ["devolucion", "cancelacion"]
    )
    print("Referencia de solicitud para reintentar: " + ref)
    r = api(
        sesion,
        "PUT",
        f"/pedidos-venta/{id}/solicitudes/{ref}",
        {"tipo": tipo, "motivo": input("Motivo: ").strip()},
    )
    if r:
        print(
            f'Solicitud registrada: {r["estado"]}. El negocio debe revisarla; este aviso no mueve stock ni devuelve dinero.'
        )


def ver_solicitudes(sesion, pedido_id=None):
    pagina = 1
    while True:
        filtro = f"&pedido_id={pedido_id}" if pedido_id is not None else ""
        r = api(
            sesion, "GET", f"/solicitudes-clientes?pagina={pagina}&limite=20" + filtro
        )
        if r is None:
            return
        if not r["solicitudes"]:
            print("No hay solicitudes para esta consulta.")
        for x in r["solicitudes"]:
            print(
                f'Pedido {x["pedido_id"]} | {x["referencia"]} | {x["tipo"]} | {x["estado"]} | {x["motivo"]}'
            )
            if x.get("resolucion"):
                print("  Respuesta del negocio: " + x["resolucion"]["motivo"])
        if (
            pagina * 20 >= r["total"]
            or pedir_opcion("¿Siguiente página? (s/n): ", ["s", "n"]) == "n"
        ):
            return
        pagina += 1


def resolver_solicitud(sesion):
    print(
        "Primero registrá la devolución/cancelación y el reintegro cuando correspondan. Esta opción solo deja constancia de la atención."
    )
    id = pedir_numero("ID del pedido: ")
    ref = input("Referencia de la solicitud del cliente: ").strip()
    estado = pedir_opcion(
        "Resolución (atendida/rechazada): ", ["atendida", "rechazada"]
    )
    r = api(
        sesion,
        "PUT",
        f"/solicitudes-clientes/{id}/{ref}/resolucion",
        {"estado": estado, "motivo": input("Explicación de la resolución: ").strip()},
    )
    if r:
        print(f'Resolución registrada: {r["estado"]}. No modifica inventario ni pagos.')


def ver_avisos(sesion):
    id = pedir_numero("ID del pedido al proveedor: ")
    r = api(sesion, "GET", f"/pedidos/{id}/avisos-proveedor")
    if r:
        for a in r["avisos"]:
            print(f'{a["proveedor"]} | {a["estado"]} | {a["nota"]}')
        if not r["avisos"]:
            print("El proveedor todavía no registró avisos para este pedido.")


def menu_cliente(sesion):
    navegacion = {}
    from menu_api import mostrar_productos

    acciones = {
        "2": lambda: mostrar_productos(sesion),
        "3": lambda: comprar_online(sesion),
        "4": lambda: listar_mis_pedidos(sesion),
        "9": lambda: ver_solicitudes(sesion),
        "10": lambda: print(api(sesion, "GET", "/mi-perfil")),
        "11": lambda: cambiar_clave(sesion),
    }
    while True:
        from menu_navegacion import elegir_sector

        etiquetas = {
            "1": "Buscar productos",
            "2": "Ver productos",
            "3": "Crear compra online",
            "4": "Elegir un pedido y gestionarlo",
            "9": "Mis solicitudes y respuestas",
            "10": "Mi perfil",
            "11": "Cambiar contraseña",
        }
        grupos = [
            ("Comprar", ["1", "2", "3"]),
            ("Mis pedidos", ["4"]),
            ("Ayuda con una compra", ["9"]),
            ("Mi cuenta", ["10", "11"]),
        ]
        op = elegir_sector(
            grupos, etiquetas, ["1", *acciones], "CLIENTE · Tus sectores", navegacion
        )
        if op == "0":
            return
        if op == "1":
            mostrar_productos(sesion, input("Nombre o marca: ").strip())
        else:
            acciones[op]()


def menu_proveedor(sesion, proveedor):
    navegacion = {}
    from menu_api import mostrar_pedido

    while True:
        from menu_navegacion import elegir_sector

        etiquetas = {
            "1": "Mis ofertas",
            "2": "Elegir un pedido y gestionarlo",
            "4": "Publicar catálogo completo",
            "7": "Cambiar contraseña",
        }
        grupos = [
            ("Catálogo", ["1", "4"]),
            ("Pedidos del negocio", ["2"]),
            ("Mi cuenta", ["7"]),
        ]
        op = elegir_sector(
            grupos,
            etiquetas,
            list("1247"),
            f"Proveedor {proveedor} · Tus sectores",
            navegacion,
        )
        if op == "0":
            return
        if op == "1":
            from menu_pedidos_proveedor import mostrar_ofertas

            mostrar_ofertas(sesion, proveedor)
        elif op == "2":
            from menu_pedidos_proveedor import mis_pedidos

            mis_pedidos(sesion)
        elif op == "4":
            print(
                "El archivo reemplaza todas tus ofertas vigentes. Las ofertas omitidas dejan de ofrecerse."
            )
            ruta = Path(input("Ruta del JSON (admite comillas): ").strip().strip('"'))
            try:
                if ruta.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError("Máximo 2 MB")
                datos = json.loads(ruta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                print("No se pudo leer el JSON. Revisá ruta, tamaño y formato.")
                continue
            if (
                pedir_opcion("¿Publicar el catálogo completo? (s/n): ", ["s", "n"])
                == "s"
            ):
                print(api(sesion, "PUT", "/mi-proveedor/catalogo", datos))
        else:
            cambiar_clave(sesion)


def restablecer_clave(sesion, nombre=None):
    contextual = nombre is not None
    if nombre is None:
        nombre = input("Usuario que olvidó su contraseña: ").strip()
    ref = (
        uuid4().hex
        if contextual
        else input(
            "Referencia del restablecimiento (Enter genera una; guardala para reintentar): "
        ).strip()
        or uuid4().hex
    )
    temporal = getpass(
        "Contraseña temporal (10 a 128 caracteres, sin tildes/ñ; no se muestra): "
    )
    if temporal != getpass("Repetí la contraseña temporal: "):
        print("Las contraseñas no coinciden. No se modificó la cuenta.")
        return
    motivo = input(
        "Motivo del restablecimiento (no incluyas contraseñas aquí): "
    ).strip()
    print(f"Cuenta: {nombre} | Referencia que debés conservar: {ref}")
    print(
        "La contraseña anterior dejará de funcionar. El usuario deberá cambiar la temporal antes de operar."
    )
    if pedir_opcion("¿Confirmar restablecimiento? (s/n): ", ["s", "n"]) != "s":
        return
    while True:
        r = api(
            sesion,
            "PUT",
            f"/usuarios/{nombre}/restablecimientos/{ref}",
            {"temporal": temporal, "motivo": motivo},
        )
        if r:
            print(r["mensaje"])
            return
        if (
            not contextual
            or pedir_opcion(
                "¿Reintentar el mismo restablecimiento con la misma referencia y datos? (s/n): ",
                ["s", "n"],
            )
            != "s"
        ):
            return


def historial_cuentas(sesion, nombre=None):
    from urllib.parse import urlencode
    from mensajes import etiqueta

    if nombre is None:
        nombre = input("Usuario a consultar (Enter para todos): ").strip()
    pagina = 1
    while True:
        consulta = urlencode(
            {"pagina": pagina, "limite": 20, **({"usuario": nombre} if nombre else {})}
        )
        r = api(sesion, "GET", "/auditoria/cuentas?" + consulta)
        if r is None:
            return
        if not r["movimientos"]:
            print(
                "No hay movimientos de cuentas para esta consulta desde esta actualización."
            )
        for x in r["movimientos"]:
            print(
                f'{x["registrado_en"]} UTC | {etiqueta(x["accion"])} | Realizado por: {x["actor"]} | Cuenta: {x["afectado"]}'
            )
            if x["detalle"].get("referencia"):
                print("Referencia: " + x["detalle"]["referencia"])
            if x["detalle"].get("motivo"):
                print("Motivo: " + x["detalle"]["motivo"])
            if x["detalle"].get("rol"):
                print("Rol asignado: " + x["detalle"]["rol"])
        if (
            pagina * 20 >= r["total"]
            or pedir_opcion("¿Siguiente página? (s/n): ", ["s", "n"]) == "n"
        ):
            return
        pagina += 1


def historial_comercial(sesion):
    from mensajes import etiqueta
    from urllib.parse import urlencode

    pagina = 1
    filtros = {}
    tipo = pedir_opcion(
        "Historial: 1. Venta / 2. Caja / 3. Pedido a proveedor / 4. Compra emergencia / 5. Producto / 6. Catálogo proveedor / 7. General (administrador): ",
        list("1234567"),
    )
    if tipo == "7":
        ruta = "/auditoria/comercial"
        actor = input("Cuenta responsable (Enter para todas): ").strip()
        if actor:
            filtros["actor_filtro"] = actor
    else:
        entidad = {
            "1": "venta",
            "2": "caja",
            "3": "pedido_proveedor",
            "4": "emergencia",
            "5": "producto",
            "6": "proveedor",
        }[tipo]
        id = input("ID numérico o referencia exacta del registro: ").strip()
        from urllib.parse import quote

        ruta = f'/auditoria/comercial/{entidad}/{quote(id,safe="")}'
    while True:
        r = api(
            sesion,
            "GET",
            ruta + "?" + urlencode({**filtros, "pagina": pagina, "limite": 20}),
        )
        if r is None:
            return
        if not r["movimientos"]:
            print(
                "No hay operaciones registradas para esta consulta desde la actualización. El historial anterior no se reconstruye."
            )
        for x in r["movimientos"]:
            print(
                f'{x["registrado_en"]} UTC | {etiqueta(x["accion"])} | {etiqueta(x["entidad"])} {x["entidad_id"]}'
            )
            print(f'Responsable: {x["actor"]} | Rol: {etiqueta(x["rol"])}')
            if x["iniciado_por"]:
                print("Revisión iniciada por: " + x["iniciado_por"])
            mostrar_detalle_historial(x["detalle"])
        if (
            pagina * 20 >= r["total"]
            or pedir_opcion("¿Siguiente página? (s/n): ", ["s", "n"]) == "n"
        ):
            return
        pagina += 1


def mostrar_detalle_historial(datos, nivel=1):
    from mensajes import etiqueta, ESTADOS

    prefijo = "  " * nivel
    for campo, valor in datos.items():
        nombre = etiqueta(campo.removesuffix("_centavos").removesuffix("_pesos"))
        if isinstance(valor, dict):
            print(f"{prefijo}{nombre}:")
            mostrar_detalle_historial(valor, nivel + 1)
        elif isinstance(valor, list):
            print(f"{prefijo}{nombre}:")
            for linea in valor:
                if isinstance(linea, dict):
                    mostrar_detalle_historial(linea, nivel + 1)
                else:
                    print(prefijo + "  " + str(linea))
        else:
            if isinstance(valor, bool):
                texto = "Sí" if valor else "No"
            elif valor is None:
                texto = "Sin dato"
            elif campo.endswith("_centavos") and isinstance(valor, int):
                texto = (
                    f'${"-" if valor<0 else ""}{abs(valor)//100}.{abs(valor)%100:02d}'
                )
            elif campo.endswith("_pesos") and isinstance(valor, int):
                texto = f"${valor}"
            elif isinstance(valor, str) and valor in ESTADOS:
                texto = etiqueta(valor)
            else:
                texto = str(valor)
            print(f"{prefijo}{nombre}: {texto}")
