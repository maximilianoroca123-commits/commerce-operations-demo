"""Historical console client module for the existing HTTP business operations."""

from menu_cuentas import api
from validaciones import pedir_opcion, pedir_numero
from mensajes import etiqueta


def gestionar_solicitudes(sesion):
    pagina = 1
    while True:
        r = api(
            sesion,
            "GET",
            f"/solicitudes-clientes?estado=pendiente_revision&pagina={pagina}&limite=10",
        )
        if r is None:
            return
        filas = r["solicitudes"]
        if not filas:
            print("No hay solicitudes pendientes en esta página.")
            return
        for n, x in enumerate(filas, 1):
            print(
                f'{n}. Pedido {x["pedido_id"]} | {etiqueta(x["tipo"])} | {x["motivo"]}'
            )
        opciones = ["0", *[str(n) for n in range(1, len(filas) + 1)]]
        print("0. Volver")
        if pagina * 10 < r["total"]:
            print("s. Siguiente página")
            opciones.append("s")
        if pagina > 1:
            print("a. Página anterior")
            opciones.append("a")
        op = pedir_opcion("Elegí una solicitud: ", opciones)
        if op == "0":
            return
        if op == "s":
            pagina += 1
            continue
        if op == "a":
            pagina -= 1
            continue
        atender(sesion, filas[int(op) - 1])

        pagina = 1


def atender(sesion, solicitud):
    from menu_api import mostrar_devoluciones

    base = f'/solicitudes-clientes/{solicitud["pedido_id"]}/{solicitud["referencia"]}'
    nombres = {
        "recibir": "Recibir mercadería devuelta",
        "cancelar": "Cancelar venta antes del despacho",
        "reintegrar": "Gestionar reintegro simulado",
        "resolver": "Registrar atención completada",
        "rechazar": "Rechazar solicitud con explicación",
    }
    while True:
        c = api(sesion, "GET", base)
        if c is None:
            return
        p = c["pedido"]
        id = p["id"]
        ref = c["referencia_operacion"]
        print(
            f'\nPedido {id} | Solicitud: {solicitud["referencia"]} | {etiqueta(c["solicitud"]["estado"])}'
        )
        print("Motivo del cliente: " + c["solicitud"]["motivo"])
        print(
            f'Pago: {etiqueta(p["estado_pago"])} | Entrega: {etiqueta(p["estado_entrega"])}'
        )
        for x in c["productos"]:
            print(
                f'{x["producto_id"]}. {x["nombre"]} | Compradas: {x["cantidad"]} | Pendientes de devolución: {x["pendiente_devolver"]}'
            )
        mostrar_devoluciones(p["devoluciones"])
        if c["resolucion"]:
            print("Respuesta al cliente: " + c["resolucion"]["motivo"])
        acciones = {str(i): accion for i, accion in enumerate(c["acciones"], 1)}
        for n, accion in acciones.items():
            print(n + ". " + nombres[accion])
        print("h. Historial del pedido | 0. Guardar lo realizado y volver")
        if not acciones and c["solicitud"]["estado"] == "pendiente_revision":
            print(
                "No hay pasos disponibles para tu rol y el estado actual. Consultá con el administrador."
            )
        op = pedir_opcion("Acción: ", ["0", "h", *acciones])
        if op == "0":
            return
        if op == "h":
            h = api(sesion, "GET", f"/auditoria/comercial/venta/{id}?limite=50")
            if h:
                for x in h["movimientos"]:
                    print(
                        f'{x["registrado_en"]} | {etiqueta(x["accion"])} | {x["actor"]}'
                    )
                if h["total"] > 50:
                    print(
                        "Se muestran los 50 eventos más recientes. El historial completo está en Auditoría."
                    )
            continue
        accion = acciones[op]
        ruta = None
        datos = None
        if accion in ("recibir", "cancelar"):
            datos = {"motivo": c["solicitud"]["motivo"]}
            if accion == "recibir":
                print(
                    "Registrá únicamente productos que ya recibiste físicamente. Cantidad 0 omite un producto."
                )
                lineas = []
                for x in c["productos"]:
                    if x["pendiente_devolver"] <= 0:
                        continue
                    while True:
                        cantidad = pedir_numero(
                            f'Cantidad recibida de {x["nombre"]} (0 a {x["pendiente_devolver"]}): '
                        )
                        if 0 <= cantidad <= x["pendiente_devolver"]:
                            break
                        print("La cantidad supera lo pendiente o es negativa.")
                    if cantidad:
                        reponer = (
                            pedir_opcion(
                                "¿Está apto para volver al stock? (s/n): ", ["s", "n"]
                            )
                            == "s"
                        )
                        lineas.append(
                            {
                                "producto_id": x["producto_id"],
                                "cantidad": cantidad,
                                "reponer": reponer,
                            }
                        )
                if not lineas:
                    print("No se registró mercadería.")
                    continue
                datos["productos"] = lineas
                importe = sum(
                    x["precio_unitario"] * l["cantidad"]
                    for x in c["productos"]
                    for l in lineas
                    if x["producto_id"] == l["producto_id"]
                )
                print(f"Importe de esta devolución: ${importe}")
            else:
                print(
                    f'Se cancelará la venta por ${p["total"]} y se repondrá su mercadería.'
                )
            print("Referencia automática para reintentar: " + ref)
            ruta = (
                f"/pedidos-venta/{id}/"
                + ("devoluciones" if accion == "recibir" else "cancelaciones")
                + "/"
                + ref
            )
        elif accion == "reintegrar":
            operacion = c["operacion"]
            print(
                f'Reintegro de ${operacion["importe"]} | Medio: {p["medio_pago"]}. Es una simulación.'
            )
            if p["medio_pago"] == "efectivo":
                print(
                    "Se descontará de la caja abierta; verificá que corresponda a la entrega efectiva del dinero."
                )
            resultado = pedir_opcion(
                "1. Confirmado / 2. Fallido / 0. Volver: ", ["0", "1", "2"]
            )
            if resultado == "0":
                continue
            datos = {"estado": "confirmado" if resultado == "1" else "fallido"}
            ruta = f"/pedidos-venta/{id}/devoluciones/{ref}/reintegro"
        else:
            if accion == "resolver":
                print(
                    "Se atiende la solicitud por los productos de esta devolución. Si fue parcial, quedan otras unidades sin devolver."
                )
            motivo = input("Explicación para el cliente: ").strip()
            if not motivo:
                print("Ingresá una explicación.")
                continue
            datos = {
                "estado": "atendida" if accion == "resolver" else "rechazada",
                "motivo": motivo,
            }
            ruta = base + "/resolucion"
        if pedir_opcion("¿Confirmar esta operación? (s/n): ", ["s", "n"]) != "s":
            continue
        r = api(sesion, "PUT", ruta, datos)
        if r is None:
            print(
                "No se pudo confirmar la respuesta. Se consultará el estado antes de continuar; no uses una referencia nueva."
            )
        else:
            print(
                "Operación registrada. Se actualiza el pedido para continuar o salir."
            )
