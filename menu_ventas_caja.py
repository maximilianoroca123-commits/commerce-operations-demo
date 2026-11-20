"""Historical console client module for the existing HTTP business operations."""

from uuid import uuid4
from urllib.parse import quote
from mensajes import etiqueta
from validaciones import pedir_numero, pedir_opcion
from menu_cuentas import api


def escribir(sesion, ruta, datos):
    while True:
        r = api(sesion, "PUT", ruta, datos)
        if r is not None:
            return r
        print(
            "No se pudo confirmar la respuesta. No generes otra referencia sin comprobar el resultado."
        )
        if (
            pedir_opcion("¿Reintentar la misma operación y datos? (s/n): ", ["s", "n"])
            != "s"
        ):
            return None


def nueva_venta(sesion):
    c = api(sesion, "GET", "/operaciones/caja-actual")
    if c is None:
        return
    if c["caja"] is None:
        print(
            "No hay caja abierta. Entrá a Caja de efectivo → 19 para abrir y contar el fondo inicial."
        )
        return
    caja = c["caja"]["referencia"]
    referencia = "venta-" + uuid4().hex
    print(
        "Turno seleccionado: " + caja + " | Referencia para reintentar: " + referencia
    )
    carrito = {}
    while True:
        id = pedir_numero("ID del producto: ")
        cantidad = pedir_numero("Cantidad: ")
        if id <= 0 or cantidad <= 0:
            print("Producto y cantidad deben ser positivos.")
            return
        carrito[id] = carrito.get(id, 0) + cantidad
        if pedir_opcion("¿Agregar otro producto? (s/n): ", ["s", "n"]) == "n":
            break
    total = 0
    for id, cantidad in carrito.items():
        p = api(sesion, "GET", f"/productos/{id}")
        if p is None:
            return
        subtotal = p["precio"] * cantidad
        total += subtotal
        print(f'{cantidad} x {p["nombre"]} | Subtotal: ${subtotal}')
    print(f"Total consultado: ${total}. El servidor lo comprueba antes de cobrar.")
    recibido = pedir_numero("Efectivo recibido en pesos: ")
    if recibido < total:
        print("El efectivo no cubre el total. No se registró el cobro.")
        return
    print(f"Recibido: ${recibido} | Vuelto calculado: ${recibido-total}")
    if pedir_opcion("¿Confirmar este cobro en efectivo? (s/n): ", ["s", "n"]) != "s":
        return
    datos = {
        "caja": caja,
        "recibido": recibido,
        "productos": [
            {"producto_id": id, "cantidad": cantidad}
            for id, cantidad in carrito.items()
        ],
        "total_esperado": total,
    }
    r = escribir(sesion, f"/ventas-efectivo/{referencia}", datos)
    if r is None:
        return
    print(
        f'Venta {r["pedido_venta_id"]} | Total: ${r["total"]} | Recibido: ${r["recibido"]} | Vuelto: ${r["vuelto"]}'
    )
    if (
        pedir_opcion(
            "¿Abrir las acciones de esta venta para consultar o guardar su comprobante? (s/n): ",
            ["s", "n"],
        )
        == "s"
    ):
        gestionar_venta(sesion, r["pedido_venta_id"])


def caja_actual(sesion):
    while True:
        c = api(sesion, "GET", "/operaciones/caja-actual")
        if c is None:
            return
        caja = c["caja"]
        if caja:
            print(
                f'Caja {caja["referencia"]} | Fondo inicial: ${caja["fondo_inicial"]} | Esperado: ${caja["saldo_esperado"]}'
            )
            opciones = {
                "1": "consultar",
                "2": "cobrar",
                "3": "cerrar",
                "4": "movimiento",
                "5": "historial_cajas",
            }
            etiquetas = {
                "1": "Ver movimientos del turno",
                "2": "Cobrar venta en efectivo",
                "3": "Cerrar y contar caja",
                "4": "Ingreso o retiro manual",
                "5": "Consultar turnos anteriores",
            }
            permitidas = {
                n: a
                for n, a in opciones.items()
                if a in c["acciones"] or a == "historial_cajas"
            }
        else:
            print("No hay caja abierta.")
            permitidas = {"1": "abrir", "5": "historial_cajas"}
            etiquetas = {"1": "Abrir nuevo turno", "5": "Consultar turnos anteriores"}
        for n in permitidas:
            print(n + ". " + etiquetas[n])
        print("0. Volver al sector")
        op = pedir_opcion("Acción de caja: ", ["0", *permitidas])
        if op == "0":
            return
        accion = permitidas[op]
        if accion == "historial_cajas":
            turnos(sesion)
            continue
        if accion == "cobrar":
            nueva_venta(sesion)
            continue
        from menu_api import mostrar_caja_efectivo

        if accion == "consultar":
            r = api(sesion, "GET", "/cajas/" + quote(caja["referencia"], safe=""))
            if r:
                mostrar_caja_efectivo(r)
            continue
        if accion == "abrir":
            ref = "caja-" + uuid4().hex
            datos = {"fondo_inicial": pedir_numero("Fondo inicial contado en pesos: ")}
            ruta = f"/cajas/{ref}/apertura"
            print("Referencia del turno: " + ref)
        elif accion == "cerrar":
            datos = {
                "contado": pedir_numero("Efectivo contado en pesos: "),
                "saldo_esperado": caja["saldo_esperado"],
            }
            print(
                f'Diferencia estimada: ${datos["contado"]-caja["saldo_esperado"]:+d}. Si el saldo cambia, se deberá revisar el conteo.'
            )
            ruta = f'/cajas/{quote(caja["referencia"],safe="")}/cierre'
        else:
            tipo = pedir_opcion("Tipo (ingreso/retiro): ", ["ingreso", "retiro"])
            datos = {
                "tipo": tipo,
                "importe": pedir_numero("Importe en pesos: "),
                "motivo": input("Motivo: ").strip(),
            }
            ref = "mov-" + uuid4().hex
            print("Referencia del movimiento: " + ref)
            ruta = f'/cajas/{quote(caja["referencia"],safe="")}/movimientos/{ref}'
        if pedir_opcion("¿Confirmar operación de caja? (s/n): ", ["s", "n"]) == "s":
            r = escribir(sesion, ruta, datos)
            if r:
                mostrar_caja_efectivo(r)


def turnos(sesion):
    from menu_api import mostrar_caja_efectivo

    pagina = 1
    while True:
        r = api(sesion, "GET", f"/cajas?pagina={pagina}&limite=10")
        if r is None:
            return
        for n, x in enumerate(r["cajas"], 1):
            print(
                f'{n}. {x["referencia"]} | '
                + ("Cerrada" if x["cerrado_en"] else "Abierta")
            )
        if not r["cajas"]:
            print("No hay turnos registrados.")
            return
        opciones = ["0", *[str(n) for n in range(1, len(r["cajas"]) + 1)]]
        if pagina * 10 < r["total"]:
            opciones.append("s")
            print("s. Siguiente página")
        if pagina > 1:
            opciones.append("a")
            print("a. Página anterior")
        op = pedir_opcion("Turno a consultar (0 vuelve): ", opciones)
        if op == "0":
            return
        if op == "s":
            pagina += 1
            continue
        if op == "a":
            pagina -= 1
            continue
        ref = r["cajas"][int(op) - 1]["referencia"]
        resultado = api(sesion, "GET", "/cajas/" + quote(ref, safe=""))
        if resultado:
            mostrar_caja_efectivo(resultado)


def ventas(sesion):
    pagina = 1
    while True:
        r = api(sesion, "GET", f"/ventas?pagina={pagina}&limite=10")
        if r is None:
            return
        filas = r["pedidos"]
        for n, x in enumerate(filas, 1):
            print(
                f'{n}. Venta {x["id"]} | ${x["total"]} | {etiqueta(x["estado_entrega"])} | {x["canal"]}'
            )
        if not filas:
            print("No hay ventas cobradas en esta página.")
            return
        opciones = ["0", *[str(n) for n in range(1, len(filas) + 1)]]
        if pagina * 10 < r["total"]:
            opciones.append("s")
            print("s. Siguiente página")
        if pagina > 1:
            opciones.append("a")
            print("a. Página anterior")
        op = pedir_opcion("Venta de esta página (0 vuelve): ", opciones)
        if op == "0":
            return
        if op == "s":
            pagina += 1
            continue
        if op == "a":
            pagina -= 1
            continue
        gestionar_venta(sesion, filas[int(op) - 1]["id"])


def gestionar_venta(sesion, id):
    from menu_api import (
        mostrar_detalle_pedido,
        mostrar_devoluciones,
        guardar_ticket_venta,
    )
    from menu_cuentas import ver_solicitudes, mostrar_detalle_historial

    nombres = {
        "1": ("detalle", "Ver detalle"),
        "2": ("comprobante", "Guardar comprobante"),
        "3": ("entrega", "Registrar próximo paso de entrega"),
        "4": ("devolver", "Recibir devolución"),
        "5": ("cancelar", "Cancelar antes del despacho"),
        "6": ("reintegrar", "Gestionar reintegro simulado"),
        "7": ("devoluciones", "Ver devoluciones y reintegros"),
        "8": ("historial", "Ver responsables de la venta"),
        "9": ("solicitudes", "Ver solicitudes y respuestas"),
        "10": ("atender_solicitud", "Atender solicitud pendiente de esta venta"),
    }
    while True:
        c = api(sesion, "GET", f"/operaciones/ventas/{id}")
        if c is None:
            return
        p = c["pedido"]
        print(
            f'\nVenta {id} | Total: ${p["total"]} | Entrega: {etiqueta(p["estado_entrega"])} | Medio: {p["medio_pago"]}'
        )
        disponibles = {n: x for n, x in nombres.items() if x[0] in c["acciones"]}
        for n, (_, texto) in disponibles.items():
            print(n + ". " + texto)
        print("0. Volver")
        op = pedir_opcion("Acción sobre esta venta: ", ["0", *disponibles])
        if op == "0":
            return
        accion = disponibles[op][0]
        if accion == "detalle":
            mostrar_detalle_pedido(p)
        elif accion == "comprobante":
            guardar_ticket_venta(sesion, id)
        elif accion == "devoluciones":
            mostrar_devoluciones(p["devoluciones"])
        elif accion == "solicitudes":
            ver_solicitudes(sesion, id)
        elif accion == "historial":
            pagina = 1
            while True:
                h = api(
                    sesion,
                    "GET",
                    f"/auditoria/comercial/venta/{id}?pagina={pagina}&limite=10",
                )
                if h is None:
                    break
                for x in h["movimientos"]:
                    print(
                        f'{x["registrado_en"]} UTC | {etiqueta(x["accion"])} | {x["actor"]}'
                    )
                    mostrar_detalle_historial(x["detalle"])
                if not h["movimientos"]:
                    print("No hay eventos desde que se incorporó el historial.")
                if (
                    pagina * 10 >= h["total"]
                    or pedir_opcion("¿Siguiente página? (s/n): ", ["s", "n"]) == "n"
                ):
                    break
                pagina += 1
        elif accion == "entrega":
            siguiente = p["siguiente_estado_entrega"]
            print("Próximo estado: " + etiqueta(siguiente))
            print(
                "Confirmá únicamente si ese paso ocurrió físicamente. No se cobra otra vez ni se descuenta stock."
            )
            if pedir_opcion("¿Registrar paso? (s/n): ", ["s", "n"]) == "s":
                escribir(sesion, f"/pedidos-venta/{id}/entrega", {"estado": siguiente})
        elif accion in ("devolver", "cancelar"):
            devolver(sesion, p, cancelar=accion == "cancelar")
        elif accion == "reintegrar":
            reintegrar(sesion, p)
        elif accion == "atender_solicitud":
            r = api(
                sesion,
                "GET",
                f"/solicitudes-clientes?pedido_id={id}&estado=pendiente_revision&limite=50",
            )
            if r and r["solicitudes"]:
                for n, x in enumerate(r["solicitudes"], 1):
                    print(f'{n}. {etiqueta(x["tipo"])} | {x["motivo"]}')
                seleccion = pedir_opcion(
                    "Solicitud (0 vuelve): ",
                    ["0", *[str(n) for n in range(1, len(r["solicitudes"]) + 1)]],
                )
                if seleccion != "0":
                    from menu_atencion import atender

                    atender(sesion, r["solicitudes"][int(seleccion) - 1])
                if r["total"] > 50:
                    print("Para revisar más solicitudes usá Atención al cliente → 43.")


def devolver(sesion, p, cancelar=False):
    print(
        "La devolución física, el reintegro y la respuesta a la solicitud son registros separados. Si hay una solicitud del cliente, conviene atenderla desde Atención al cliente → 43."
    )
    datos = {"motivo": input("Motivo: ").strip()}
    if not cancelar:
        print(
            "Registrá sólo mercadería recibida físicamente. Cantidad 0 omite el producto."
        )
        lineas = []
        for producto in p["productos"]:
            id = producto["producto_id"]
            devuelto = sum(
                x["cantidad"]
                for op in p["devoluciones"]["operaciones"]
                for x in op["productos"]
                if x["producto_id"] == id
            )
            disponible = producto["cantidad"] - devuelto
            if disponible <= 0:
                continue
            cantidad = pedir_numero(
                f'Cantidad recibida de {producto["nombre"]} (0 a {disponible}): '
            )
            if not 0 <= cantidad <= disponible:
                print("Cantidad fuera de rango. No se registró la devolución.")
                return
            if cantidad:
                reponer = (
                    pedir_opcion("¿Está apto para volver al stock? (s/n): ", ["s", "n"])
                    == "s"
                )
                lineas.append(
                    {"producto_id": id, "cantidad": cantidad, "reponer": reponer}
                )
        if not lineas:
            print("No se registraron productos.")
            return
        datos["productos"] = lineas
        importe = sum(
            x["precio_unitario"] * l["cantidad"]
            for x in p["productos"]
            for l in lineas
            if x["producto_id"] == l["producto_id"]
        )
    else:
        importe = p["total"]
    ref = "operacion-" + uuid4().hex
    print(f"Importe: ${importe} | Referencia para reintentar: {ref}")
    if pedir_opcion("¿Confirmar registro comercial? (s/n): ", ["s", "n"]) != "s":
        return
    ruta = "cancelaciones" if cancelar else "devoluciones"
    escribir(sesion, f'/pedidos-venta/{p["id"]}/{ruta}/{ref}', datos)


def reintegrar(sesion, p):
    pendientes = [
        x
        for x in p["devoluciones"]["operaciones"]
        if x["estado_reintegro"] != "confirmado"
    ]
    for n, x in enumerate(pendientes, 1):
        print(
            f'{n}. {x["referencia"]} | ${x["importe"]} | {etiqueta(x["estado_reintegro"])}'
        )
    op = pedir_opcion(
        "Reintegro a gestionar (0 vuelve): ",
        ["0", *[str(n) for n in range(1, len(pendientes) + 1)]],
    )
    if op == "0":
        return
    operacion = pendientes[int(op) - 1]
    if p["medio_pago"] == "efectivo":
        c = api(sesion, "GET", "/operaciones/caja-actual")
        if c is None:
            return
        if c["caja"] is None:
            print(
                "Se requiere una caja abierta para registrar el reintegro en efectivo."
            )
            return
        print(
            f'Se registrará la salida en caja {c["caja"]["referencia"]}, si el reintegro se confirma.'
        )
    print(
        f'Reintegro simulado: ${operacion["importe"]}. No se realiza una transferencia bancaria real.'
    )
    estado = pedir_opcion("1. Confirmado / 2. Fallido / 0. Volver: ", ["0", "1", "2"])
    if estado == "0":
        return
    if pedir_opcion("¿Confirmar simulación y su registro? (s/n): ", ["s", "n"]) != "s":
        return
    escribir(
        sesion,
        f'/pedidos-venta/{p["id"]}/devoluciones/{quote(operacion["referencia"],safe="")}/reintegro',
        {"estado": "confirmado" if estado == "1" else "fallido"},
    )
