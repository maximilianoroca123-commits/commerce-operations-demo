"""Historical console client module for the existing HTTP business operations."""

from validaciones import pedir_opcion
from mensajes import etiqueta
from menu_cuentas import api


def mis_pedidos(sesion):
    pagina = 1
    while True:
        r = api(sesion, "GET", f"/pedidos-venta?pagina={pagina}&limite=10")
        if r is None:
            return
        filas = r["pedidos"]
        if not filas:
            print("No hay pedidos en esta página.")
            return
        for n, p in enumerate(filas, 1):
            print(
                f'{n}. Pedido {p["id"]} | Total: ${p["total"]} | Pago: {etiqueta(p["estado_pago"])} | Entrega: {etiqueta(p["estado_entrega"])}'
            )
        opciones = ["0", *[str(n) for n in range(1, len(filas) + 1)]]
        print("0. Volver a Mis pedidos")
        if pagina * 10 < r["total"]:
            opciones.append("s")
            print("s. Siguiente página")
        if pagina > 1:
            opciones.append("a")
            print("a. Página anterior")
        opcion = pedir_opcion("Elegí un pedido de la lista: ", opciones)
        if opcion == "0":
            return
        if opcion == "s":
            pagina += 1
            continue
        if opcion == "a":
            pagina -= 1
            continue
        gestionar_pedido(sesion, filas[int(opcion) - 1]["id"])


def gestionar_pedido(sesion, pedido_id):
    from menu_api import mostrar_detalle_pedido, guardar_ticket_venta
    from menu_cuentas import pagar_online, solicitar_gestion, ver_solicitudes

    while True:
        p = api(sesion, "GET", f"/pedidos-venta/{pedido_id}")
        if p is None:
            return
        print(
            f'\nPedido {p["id"]} | Pago: {etiqueta(p["estado_pago"])} | Entrega: {etiqueta(p["estado_entrega"])} | Total: ${p["total"]}'
        )
        permitidas = p["acciones_cliente"]
        acciones = {
            "1": ("detalle", "Ver detalle"),
            "2": ("pagar", "Simular pago de esta compra"),
            "3": ("comprobante", "Guardar comprobante"),
            "4": ("devolucion", "Solicitar devolución"),
            "5": ("cancelacion", "Solicitar cancelación"),
            "6": ("solicitudes", "Ver solicitudes y respuestas de este pedido"),
        }
        visibles = {n: valor for n, valor in acciones.items() if valor[0] in permitidas}
        for n, (_, texto) in visibles.items():
            print(n + ". " + texto)
        print("0. Volver a la lista de pedidos")
        opcion = pedir_opcion("Acción sobre este pedido: ", ["0", *visibles])
        if opcion == "0":
            return
        accion = visibles[opcion][0]
        if accion == "detalle":
            mostrar_detalle_pedido(p)
        elif accion == "comprobante":
            guardar_ticket_venta(sesion, pedido_id)
        elif accion == "pagar":
            pagar_online(sesion, p["referencia"])
        elif accion == "solicitudes":
            ver_solicitudes(sesion, pedido_id)
        else:

            r = api(
                sesion,
                "GET",
                f"/solicitudes-clientes?pedido_id={pedido_id}&estado=pendiente_revision&limite=50",
            )
            if r is None:
                continue
            if any(x["tipo"] == accion for x in r["solicitudes"]):
                print(
                    "Ya tenés una solicitud pendiente de este tipo. Revisá sus respuestas antes de crear otra."
                )
                ver_solicitudes(sesion, pedido_id)
                continue
            if (
                pedir_opcion(
                    "¿Crear esta solicitud para el pedido seleccionado? (s/n): ",
                    ["s", "n"],
                )
                == "s"
            ):
                solicitar_gestion(sesion, pedido_id, accion)
