# Historical console client module for the existing HTTP business operations.
from menu_respaldos import gestionar as gestionar_respaldos
from menu_navegacion import elegir_sector

"""Cliente de consola para consultar y gestionar el catálogo local."""

import re
from pathlib import Path
from functools import partial
from getpass import getpass
from uuid import uuid4

import requests

from mensajes import error_respuesta, etiqueta, pedir_fecha_compra

from validaciones import pedir_numero, pedir_opcion

URL_API_LOCAL = "http://127.0.0.1:8000"


def mostrar_productos(sesion, texto=None):
    pagina = 1
    while True:
        try:
            respuesta = sesion.get(
                f"{URL_API_LOCAL}/productos",
                params={"pagina": pagina, "texto": texto},
                timeout=10,
            )
            respuesta.raise_for_status()
            resultado = respuesta.json()
        except requests.ConnectionError:
            print(
                "No se pudo conectar con el servidor del negocio. Comprobá que esté encendido y volvé a intentar."
            )
            return
        except requests.RequestException as error:
            print(
                error_respuesta(error.response)
                if isinstance(error, requests.HTTPError)
                else "No se pudo consultar el catálogo. Revisá la conexión con el servidor."
            )
            return

        if not resultado["productos"]:
            print("No se encontraron productos.")
            return

        for producto in resultado["productos"]:
            marca = producto["marca"] or "Sin marca"
            print(
                f'{producto["id"]} | {producto["nombre"]} | {marca} | '
                f'{producto["categoria"]} | Precio: {producto["precio"]} | '
                f'Stock: {producto["stock"]}'
            )

        paginas = resultado["cantidad_paginas"]
        print(f'Página {pagina} de {paginas} | Coincidencias: {resultado["total"]}')
        if (
            pagina >= paginas
            or pedir_opcion("¿Siguiente página? (s/n): ", ["s", "n"]) == "n"
        ):
            return
        pagina += 1


def modificar_catalogo(sesion, opcion, id_producto=None):
    contextual = id_producto is not None
    ruta = "/productos"
    datos = None
    if opcion == "3":
        metodo = "POST"
        datos = {
            "nombre": input("Nombre: "),
            "categoria": input("Categoría (alimento, tecnologia o libreria): "),
            "precio": pedir_numero("Precio: "),
            "stock": pedir_numero("Stock: "),
            "marca": input("Marca (opcional): ").strip() or None,
        }
    else:
        if id_producto is None:
            id_producto = pedir_numero("ID del producto: ")
        ruta = f"/productos/{id_producto}"
        if opcion == "4":
            metodo = "PATCH"
            campo = pedir_opcion(
                "Campo (marca/precio/stock): ", ["marca", "precio", "stock"]
            )
            valor = input("Marca: ") if campo == "marca" else pedir_numero("Valor: ")
            datos = {campo: valor}
            if campo == "stock":
                datos["motivo_stock"] = input("Motivo del ajuste de stock: ").strip()
        else:
            if (
                pedir_opcion(
                    f"¿Eliminar el producto {id_producto}? (s/n): ", ["s", "n"]
                )
                == "n"
            ):
                return
            metodo = "DELETE"

    if contextual and opcion == "4":
        print(f"Producto {id_producto} | Cambios solicitados:")
        for campo, valor in datos.items():
            print(f'  {etiqueta(campo)}: {valor if valor is not None else "Sin dato"}')
        if pedir_opcion("¿Confirmar cambio del producto? (s/n): ", ["s", "n"]) != "s":
            return

    try:
        respuesta = sesion.request(metodo, URL_API_LOCAL + ruta, json=datos, timeout=10)
        respuesta.raise_for_status()
    except requests.HTTPError as error:
        print(error_respuesta(error.response))
        return
    except requests.RequestException as error:
        print(
            "No se pudo conectar con el servidor. Comprobá que esté encendido y volvé a intentar."
        )
        return

    if respuesta.status_code == 204:
        print("Producto eliminado.")
        return True
    else:
        producto = respuesta.json()
        print(f'Producto guardado: {producto["id"]} | {producto["nombre"]}')
        return producto


def comprar_producto(sesion):
    producto_id = pedir_numero("ID del producto: ")
    cantidad = pedir_numero("Cantidad: ")
    if producto_id <= 0 or cantidad <= 0:
        print("El ID y la cantidad deben ser mayores que cero.")
        return
    if (
        pedir_opcion(
            f"¿Confirmar compra de {cantidad} del producto {producto_id}? (s/n): ",
            ["s", "n"],
        )
        == "n"
    ):
        return

    referencia = uuid4().hex
    datos = {"producto_id": producto_id, "cantidad": cantidad}
    while True:
        try:
            respuesta = sesion.put(
                f"{URL_API_LOCAL}/ventas/{referencia}", json=datos, timeout=10
            )
        except requests.RequestException:
            print(
                f"No se pudo confirmar el resultado de la compra. Referencia: {referencia}"
            )
            if pedir_opcion("¿Reintentar la misma compra? (s/n): ", ["s", "n"]) == "s":
                continue
            return
        if respuesta.status_code != 200:
            print(error_respuesta(respuesta))
            return

        venta = respuesta.json()["venta"]
        print(
            f'Compra registrada. Referencia: {venta["referencia"]} | '
            f'Stock al registrar la compra: {venta["stock_restante"]}'
        )
        return


def solicitar_compras(sesion, metodo, ruta, datos=None):
    try:
        respuesta = sesion.request(metodo, URL_API_LOCAL + ruta, json=datos, timeout=10)
        if respuesta.status_code not in (200, 201):
            print(error_respuesta(respuesta))
            return None
        return respuesta.json()
    except (requests.RequestException, ValueError):
        print(
            "No se pudo confirmar el resultado con el servidor. Consultá el registro. Si reintentás, usá la misma referencia y los mismos datos; no generes una referencia nueva."
        )
        return None


def mostrar_pedido(pedido):
    recibidas = pedido["cantidad_recibida"]
    saldo = pedido.get("cantidad_pendiente", pedido["cantidad"] - recibidas)
    costo = pedido["costo_ofertado_centavos"]
    pesos, centavos = divmod(costo, 100)
    print(
        f'Pedido {pedido["id"]} | Producto {pedido["producto_id"]} | '
        f'{pedido["proveedor"]} | {etiqueta(pedido.get("estado", "pendiente"))} | '
        f'Recibidas: {recibidas}/{pedido["cantidad"]} | Pendientes: {saldo} | '
        f"Costo ofertado por unidad: ${pesos},{centavos:02d}"
    )


def generar_pedido(sesion, producto_id=None):
    if producto_id is None:
        producto_id = pedir_numero("ID del producto: ")
    if producto_id <= 0:
        print("El ID debe ser mayor que cero.")
        return
    resultado = solicitar_compras(
        sesion, "POST", f"/productos/{producto_id}/reposicion"
    )
    if resultado is None:
        return
    mensajes = {
        "pedido_generado": "Pedido generado.",
        "pedido_pendiente": "El producto ya tiene un pedido abierto.",
        "con_stock": "El producto todavía tiene stock.",
        "sin_oferta_elegible": "No hay una oferta elegible para la reposición.",
    }
    print(
        mensajes.get(
            resultado["estado"],
            resultado.get("motivo") or etiqueta(resultado["estado"]),
        )
    )
    if "pedidos" in resultado:
        for pedido in resultado["pedidos"]:
            mostrar_pedido(pedido)
    elif "pedido" in resultado:
        mostrar_pedido(resultado["pedido"])


def listar_pedidos_abiertos(sesion):
    from menu_abastecimiento import pedidos

    pedidos(sesion)


def registrar_entrega_pedido(sesion, pedido_id=None, en_pesos=False):
    if pedido_id is None:
        pedido_id = pedir_numero("ID del pedido: ")
    referencia = input("Referencia del remito: ").strip()
    cantidad = pedir_numero("Cantidad recibida: ")
    if en_pesos:
        from menu_abastecimiento import pedir_costo

        costo = pedir_costo()
    else:
        costo = pedir_numero(
            "Costo pagado por unidad en centavos (ej. 120000 para $1200): "
        )
    if pedido_id <= 0 or cantidad <= 0 or costo <= 0:
        print("El ID, la cantidad y el costo deben ser mayores que cero.")
        return
    if not codigo_valido(referencia):
        print(
            "Ingresá una referencia de hasta 64 caracteres con letras, números, guiones o guiones bajos."
        )
        return
    if en_pesos:
        print(
            f"Cantidad: {cantidad} | Costo real por unidad: ${costo//100},{costo%100:02d}"
        )
    if (
        pedir_opcion(
            f"¿Registrar el remito {referencia} en el pedido {pedido_id}? (s/n): ",
            ["s", "n"],
        )
        == "n"
    ):
        return

    while True:
        resultado = solicitar_compras(
            sesion,
            "PUT",
            f"/pedidos/{pedido_id}/recepciones/{referencia}",
            {"cantidad": cantidad, "costo_pagado_centavos": costo},
        )
        if resultado is not None:
            break
        if (
            not en_pesos
            or pedir_opcion(
                "¿Reintentar exactamente el mismo remito y datos? (s/n): ", ["s", "n"]
            )
            != "s"
        ):
            return

    mensajes = {
        "entrega_registrada": "Entrega registrada.",
        "entrega_ya_registrada": "El remito ya estaba registrado.",
    }
    print(
        mensajes.get(
            resultado["estado"], resultado.get("motivo") or resultado["estado"]
        )
    )
    mostrar_pedido(resultado["pedido"])


def codigo_valido(valor):
    return re.fullmatch(r"[A-Za-z0-9_-]{1,64}", valor) is not None


def finalizar_pedido(sesion, operacion, descripcion, pedido_id=None):
    if pedido_id is None:
        pedido_id = pedir_numero("ID del pedido: ")
    if pedido_id <= 0:
        print("El ID debe ser mayor que cero.")
        return
    if (
        pedir_opcion(
            f"¿Confirmar {descripcion} del pedido {pedido_id}? (s/n): ", ["s", "n"]
        )
        == "n"
    ):
        return

    resultado = solicitar_compras(sesion, "PUT", f"/pedidos/{pedido_id}/{operacion}")
    if resultado is None:
        return
    mensajes = {
        "cancelado": "Pedido cancelado.",
        "ya_cancelado": "El pedido ya estaba cancelado.",
        "cerrado_incompleto": "Pedido cerrado incompleto.",
        "ya_cerrado_incompleto": "El pedido ya estaba cerrado incompleto.",
    }
    print(
        mensajes.get(
            resultado["estado"], resultado.get("motivo") or resultado["estado"]
        )
    )
    pedido = resultado["pedido"]
    mostrar_pedido(pedido)
    if pedido["cantidad_no_entregada"]:
        print(f'Unidades no entregadas: {pedido["cantidad_no_entregada"]}')


def corregir_remito(
    sesion, pedido_id=None, referencia=None, en_pesos=False, remito_actual=None
):
    contextual = referencia is not None
    if pedido_id is None:
        pedido_id = pedir_numero("ID del pedido: ")
    if referencia is None:
        referencia = input("Referencia del remito original: ").strip()
    if contextual:
        from uuid import uuid4

        codigo = uuid4().hex
        print("Código de corrección para reintentar: " + codigo)
    else:
        codigo = input("Código de la corrección (ej. corr-1): ").strip()
    cantidad = pedir_numero("Cantidad total corregida del remito: ")
    if en_pesos:
        from menu_abastecimiento import pedir_costo

        costo = pedir_costo()
    else:
        costo = pedir_numero(
            "Costo unitario corregido en centavos (ej. 120000 para $1200): "
        )
    motivo = input("Motivo de la corrección: ").strip()
    if pedido_id <= 0 or cantidad <= 0 or costo <= 0:
        print("El ID, la cantidad y el costo deben ser mayores que cero.")
        return
    if not codigo_valido(referencia) or not codigo_valido(codigo):
        print(
            "La referencia y el código admiten hasta 64 letras, números, guiones o guiones bajos."
        )
        return
    if not 1 <= len(motivo) <= 500:
        print("El motivo debe tener entre 1 y 500 caracteres.")
        return
    if (
        remito_actual
        and cantidad == remito_actual["cantidad"]
        and costo == remito_actual["costo_pagado_centavos"]
    ):
        print(
            "La cantidad y el costo ya coinciden con el remito. No se registró otra corrección."
        )
        return
    if (
        pedir_opcion(
            f"¿Corregir el remito {referencia} del pedido {pedido_id}? (s/n): ",
            ["s", "n"],
        )
        == "n"
    ):
        return

    while True:
        resultado = solicitar_compras(
            sesion,
            "PUT",
            f"/pedidos/{pedido_id}/recepciones/{referencia}/correcciones/{codigo}",
            {"cantidad": cantidad, "costo_pagado_centavos": costo, "motivo": motivo},
        )
        if resultado is not None:
            break
        if (
            not contextual
            or pedir_opcion(
                "¿Reintentar esta misma corrección con el mismo código y datos? (s/n): ",
                ["s", "n"],
            )
            != "s"
        ):
            return
    if resultado["estado"] == "correccion_ya_registrada":
        print("La corrección ya estaba registrada.")
    else:
        print("Corrección registrada.")
    correccion = resultado["correccion"]
    print(
        f'Cantidad en el remito: {correccion["cantidad_anterior"]} a {correccion["cantidad"]} | '
        f'Costo unitario en centavos: {correccion["costo_anterior_centavos"]} '
        f'a {correccion["costo_pagado_centavos"]}'
    )
    mostrar_pedido(resultado["pedido"])


def consultar_ventas(sesion):
    pagina = 1
    while True:
        resultado = solicitar_compras(
            sesion, "GET", f"/ventas?pagina={pagina}&limite=10"
        )
        if resultado is None:
            return
        if not resultado["pedidos"]:
            print("No hay ventas cobradas.")
            return
        for pedido in resultado["pedidos"]:
            print(
                f'Venta {pedido["id"]} | {pedido["canal"]} | {pedido["modalidad"]} | '
                f'Total: ${pedido["total"]} | Entrega: {etiqueta(pedido["estado_entrega"])} | '
                f'Referencia: {pedido["referencia"]}'
            )
        if pagina * 10 >= resultado["total"]:
            return
        if pedir_opcion("¿Siguiente página? (s/n): ", ["s", "n"]) == "n":
            return
        pagina += 1


def consultar_detalle_venta(sesion):
    pedido_id = pedir_numero("ID del pedido de venta: ")
    if pedido_id <= 0:
        print("El ID debe ser mayor que cero.")
        return
    pedido = solicitar_compras(sesion, "GET", f"/pedidos-venta/{pedido_id}")
    if pedido is None:
        return
    mostrar_detalle_pedido(pedido)


def mostrar_detalle_pedido(pedido):
    print(
        f'Pedido de venta {pedido["id"]} | Pago: {etiqueta(pedido["estado_pago"])} | '
        f'Entrega: {etiqueta(pedido["estado_entrega"])} | Total: ${pedido["total"]}'
    )
    print(
        f'Cliente: {pedido.get("cliente_id") or "sin identificar"} | Registrado por: {pedido.get("registrado_por") or "registro anterior sin identificación de operador"}'
    )
    if pedido.get("cliente_al_comprar"):
        c = pedido["cliente_al_comprar"]
        print(f'Contacto al comprar: {c["nombre"]} {c["apellido"]} | {c["correo"]}')
    if pedido.get("direccion_entrega"):
        print("Dirección de entrega: " + pedido["direccion_entrega"])
    for producto in pedido["productos"]:
        print(
            f'{producto["cantidad"]} x {producto["nombre"]} | '
            f'Precio unitario: ${producto["precio_unitario"]} | '
            f'Subtotal: ${producto["cantidad"] * producto["precio_unitario"]}'
        )

    mostrar_devoluciones(pedido["devoluciones"])


def guardar_ticket_venta(sesion, pedido_id=None):
    if pedido_id is None:
        pedido_id = pedir_numero("ID del pedido de venta: ")
    if pedido_id <= 0:
        print("El ID debe ser mayor que cero.")
        return
    try:
        respuesta = sesion.get(
            f"{URL_API_LOCAL}/pedidos-venta/{pedido_id}/ticket", timeout=10
        )
        if respuesta.status_code != 200:
            print(error_respuesta(respuesta))
            return
        carpeta = Path(__file__).resolve().parent / "tickets"
        carpeta.mkdir(exist_ok=True)
        ruta = carpeta / f"venta-{pedido_id}.html"
        ruta.write_text(respuesta.text, encoding="utf-8")
    except requests.RequestException:
        print("No se pudo consultar el ticket en la API.")
        return
    except OSError as error:
        print(f"No se pudo guardar el ticket: {error}")
        return
    print(f"Ticket guardado: {ruta}")
    print("Abrilo en el navegador y usá Ctrl+P para imprimir o guardar como PDF.")


def gestionar_devolucion(sesion, cancelar=False):
    pedido_id = pedir_numero("ID del pedido de venta: ")
    referencia = input(
        "Referencia única de la operación (guardala para reintentar): "
    ).strip()
    motivo = input("Motivo: ").strip()
    datos = {"motivo": motivo}
    if not cancelar:
        producto_id = pedir_numero("ID del producto recibido: ")
        cantidad = pedir_numero("Cantidad devuelta: ")
        reponer = (
            pedir_opcion("¿Está apto para volver al stock? (s/n): ", ["s", "n"]) == "s"
        )
        datos["productos"] = [
            {"producto_id": producto_id, "cantidad": cantidad, "reponer": reponer}
        ]
    if pedir_opcion("¿Confirmar registro? (s/n): ", ["s", "n"]) != "s":
        return
    ruta = "cancelaciones" if cancelar else "devoluciones"
    resultado = solicitar_compras(
        sesion, "PUT", f"/pedidos-venta/{pedido_id}/{ruta}/{referencia}", datos=datos
    )
    if resultado is not None:
        mostrar_devoluciones(resultado)


def mostrar_devoluciones(resumen):
    print(f'Estado comercial: {etiqueta(resumen["estado_comercial"])}')
    for operacion in resumen["operaciones"]:
        print(
            f'{operacion["referencia"]} | {operacion["tipo"]} | '
            f'Importe: ${operacion["importe"]} | Reintegro: {etiqueta(operacion["estado_reintegro"])}'
        )
    print(
        "El ingreso de mercadería devuelta y el reintegro de dinero son registros separados."
    )
    print(
        f'Reintegrado: ${resumen["importe_reintegrado"]} | '
        f'Pendiente de reintegrar: ${resumen["importe_por_reintegrar"]}'
    )


def simular_reintegro(sesion):
    pedido_id = pedir_numero("ID del pedido de venta: ")
    referencia = input("Referencia de la devolución o cancelación: ").strip()
    opcion = pedir_opcion("Simular 1. Confirmado / 2. Fallido: ", ["1", "2"])
    estado = "confirmado" if opcion == "1" else "fallido"
    if pedir_opcion("¿Confirmar simulación? (s/n): ", ["s", "n"]) != "s":
        return
    resultado = solicitar_compras(
        sesion,
        "PUT",
        f"/pedidos-venta/{pedido_id}/devoluciones/{referencia}/reintegro",
        datos={"estado": estado},
    )
    if resultado is not None:
        mostrar_devoluciones(resultado)


def consultar_movimientos(sesion, producto_id=None):
    if producto_id is None:
        producto_id = pedir_numero("ID del producto (0 para todos): ")
    if producto_id < 0:
        print("El ID no puede ser negativo.")
        return
    pagina = 1
    while True:
        ruta = f"/inventario/movimientos?pagina={pagina}&limite=10"
        if producto_id:
            ruta += f"&producto_id={producto_id}"
        resultado = solicitar_compras(sesion, "GET", ruta)
        if resultado is None:
            return
        if not resultado["movimientos"]:
            print("No hay movimientos para esa consulta.")
            return
        for m in resultado["movimientos"]:
            print(
                f'{m["registrado_en"]} | Producto {m["producto_id"]}: {m["nombre"]} | '
                f'{etiqueta(m["tipo"])} | Unidades: {m["cantidad"]} | Cambio: {m["variacion"]:+d} | '
                f'Stock: {m["stock_anterior"]} -> {m["stock_resultante"]} | '
                f'Referencia: {m["referencia"]} | {m["motivo"]}'
            )
        if pagina * 10 >= resultado["total"]:
            return
        if pedir_opcion("¿Siguiente página? (s/n): ", ["s", "n"]) == "n":
            return
        pagina += 1


def mostrar_caja_efectivo(caja):
    print(
        f'Caja {caja["referencia"]} | {caja["estado"]} | '
        f'Fondo inicial: ${caja["fondo_inicial"]} | Saldo esperado: ${caja["saldo_esperado"]}'
    )
    for m in caja["movimientos"]:
        print(
            f'{m["registrado_en"]} | {etiqueta(m["tipo"])} | ${m["importe"]:+d} | '
            f'{m["referencia"]} | {m["motivo"]}'
        )
    if caja["estado"] == "cerrada":
        print(f'Contado: ${caja["contado"]} | Diferencia: ${caja["diferencia"]:+d}')
        print(
            "La diferencia es dinero contado menos saldo esperado: positiva = sobrante; negativa = faltante."
        )


def gestionar_caja_efectivo(sesion, operacion):
    referencia = input("Referencia del turno de caja (ej. caja-dia-1): ").strip()
    if operacion == "consulta":
        resultado = solicitar_compras(sesion, "GET", f"/cajas/{referencia}")
    else:
        if operacion == "apertura":
            datos = {"fondo_inicial": pedir_numero("Fondo inicial en pesos: ")}
            ruta = f"/cajas/{referencia}/apertura"
        elif operacion == "cierre":
            datos = {"contado": pedir_numero("Efectivo contado en pesos: ")}
            ruta = f"/cajas/{referencia}/cierre"
        else:
            codigo = input(
                "Referencia única del movimiento (guardala para reintentar): "
            ).strip()
            tipo = pedir_opcion("Tipo (ingreso/retiro): ", ["ingreso", "retiro"])
            datos = {
                "tipo": tipo,
                "importe": pedir_numero("Importe en pesos: "),
                "motivo": input("Motivo: ").strip(),
            }
            ruta = f"/cajas/{referencia}/movimientos/{codigo}"
        if pedir_opcion("¿Confirmar operación de caja? (s/n): ", ["s", "n"]) != "s":
            return
        resultado = solicitar_compras(sesion, "PUT", ruta, datos=datos)
    if resultado is not None:
        mostrar_caja_efectivo(resultado)


def cobrar_en_efectivo(sesion):
    caja = input("Referencia del turno de caja abierto: ").strip()
    referencia = input("Referencia única de venta (guardala para reintentar): ").strip()
    productos = []
    while True:
        id = pedir_numero("ID del producto: ")
        cantidad = pedir_numero("Cantidad: ")
        productos.append({"producto_id": id, "cantidad": cantidad})
        if pedir_opcion("¿Agregar otro producto? (s/n): ", ["s", "n"]) == "n":
            break

    total = 0
    for item in productos:
        producto = solicitar_compras(sesion, "GET", f'/productos/{item["producto_id"]}')
        if producto is None:
            return
        subtotal = producto["precio"] * item["cantidad"]
        total += subtotal
        print(f'{item["cantidad"]} x {producto["nombre"]}: ${subtotal}')
    print(f"Total consultado: ${total}")
    recibido = pedir_numero("Efectivo recibido en pesos: ")
    if pedir_opcion("¿Confirmar cobro en efectivo? (s/n): ", ["s", "n"]) != "s":
        return
    resultado = solicitar_compras(
        sesion,
        "PUT",
        f"/ventas-efectivo/{referencia}",
        datos={"caja": caja, "recibido": recibido, "productos": productos},
    )
    if resultado is not None:
        print(
            f'Venta {resultado["pedido_venta_id"]} | Total: ${resultado["total"]} | '
            f'Recibido: ${resultado["recibido"]} | Vuelto: ${resultado["vuelto"]}'
        )


def configurar_regla_reposicion(sesion, id=None):
    if id is None:
        id = pedir_numero("ID del producto: ")
    activa = pedir_opcion("¿Activar regla? (s/n): ", ["s", "n"]) == "s"
    print(
        "Automático: genera pedidos según la regla. Aviso: informa el faltante sin generar pedidos."
    )
    modo = pedir_opcion("Modo (automatico/aviso): ", ["automatico", "aviso"])
    minimo = pedir_numero("Mínimo para reponer (ej. 5): ")
    objetivo = pedir_numero("Stock objetivo (ej. 10): ")
    alerta = pedir_numero("Alertar desde (entre mínimo y objetivo, ej. 7): ")
    multiplo = pedir_numero("Múltiplo de unidades por pedido (ej. 1): ")
    maximo = pedir_numero("Máximo de unidades por pedido automático (ej. 20): ")
    costo = pedir_numero(
        "Techo unitario en centavos (0 sin techo; último costo solo informativo): "
    )
    importe = pedir_numero("Importe máximo por pedido en centavos (ej. 1000000): ")
    if (
        pedir_opcion(
            "¿Guardar regla? La regla activa se evalúa automáticamente. (s/n): ",
            ["s", "n"],
        )
        != "s"
    ):
        return
    resultado = solicitar_compras(
        sesion,
        "PUT",
        f"/productos/{id}/regla-reposicion",
        datos={
            "activa": activa,
            "modo": modo,
            "minimo": minimo,
            "objetivo": objetivo,
            "alertar_desde": alerta,
            "multiplo": multiplo,
            "max_unidades": maximo,
            "costo_max_centavos": costo or None,
            "importe_max_centavos": importe,
        },
    )
    if resultado is not None:
        print(f'Regla guardada para producto {id}, versión {resultado["version"]}.')
        print(
            "Regla desactivada: no genera pedidos ni avisos de esta regla."
            if not activa
            else (
                "Modo aviso: se informarán faltantes sin generar pedidos."
                if modo == "aviso"
                else "Modo automático: intentará cubrir el objetivo al alcanzar el mínimo; contará los pedidos abiertos."
            )
        )
        print(
            "Las revisiones periódicas requieren que el servidor siga funcionando y la revisión automática esté habilitada."
        )


def evaluar_reposicion(sesion):
    resultado = solicitar_compras(sesion, "POST", "/reposicion-automatica/evaluar")
    if resultado is not None:
        for r in resultado["resultados"]:
            print(
                f'Producto {r["producto_id"]} | {etiqueta(r["estado"])} | Disponible para vender: {r["disponible"]} | '
                f'Por recibir: {r["por_recibir"]} | {r["motivo"]}'
            )
            pedidos = r.get("pedidos", [r["pedido"]] if "pedido" in r else [])
            for pedido in pedidos:
                mostrar_pedido(pedido)
            print(
                f'Unidades que aún faltan para el objetivo, contando pedidos abiertos: {r.get("faltante_objetivo",0)}'
            )
            print(
                "Disponible = stock menos unidades reservadas. Por recibir = mercadería pedida que todavía no ingresó."
            )
        if not resultado["resultados"]:
            print("No hay reglas configuradas.")


def consultar_alertas_reposicion(sesion):
    pagina = 1
    while True:
        resultado = solicitar_compras(
            sesion, "GET", f"/reposicion-automatica/alertas?pagina={pagina}&limite=10"
        )
        if resultado is None:
            return
        if not resultado["alertas"]:
            print("No hay alertas activas de reposición.")
            return
        for a in resultado["alertas"]:
            print(
                f'Alerta {a["id"]} | Producto {a["producto_id"]} | {etiqueta(a["codigo"])} | {a["detalle"]}'
            )
        if (
            pagina * 10 >= resultado["total"]
            or pedir_opcion("¿Siguiente página? (s/n): ", ["s", "n"]) == "n"
        ):
            return
        pagina += 1


def leer_adjunto_emergencia():
    import base64

    ruta = (
        input(
            "Ruta completa del PDF/PNG/JPG (hasta 5 MB; admite comillas; Enter omite el adjunto): "
        )
        .strip()
        .strip('"')
    )
    if not ruta:
        return None
    archivo = Path(ruta)
    if archivo.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("El archivo supera 5 MB")
    return {
        "nombre": archivo.name,
        "contenido_base64": base64.b64encode(archivo.read_bytes()).decode("ascii"),
    }


def mostrar_compra_emergencia(r):
    total = r["total_centavos"]
    print(
        f'Compra {r["referencia"]} | Total: ${total//100}.{total%100:02d} | Fondo de emergencia para reposición'
    )
    print(
        f'Empleado declarado: {r["empleado"]} | Cuenta que registró: {r["registrado_por"]}'
    )
    if r["estado_documentacion"] == "completo":
        print("Documentación completa: archivo del comprobante adjuntado.")
    else:
        print(
            "Documentación: falta adjuntar el archivo (opción 30). La compra y el gasto ya están registrados."
        )
    print(
        "Situación histórica al registrar esta compra (no es el stock actual; consultalo en la opción 2):"
    )
    for estado in r["situacion_al_registrar"]:
        print(
            f'Producto {estado["producto_id"]} | {etiqueta(estado["estado"])} | '
            f'Unidades que faltaban para el objetivo, contando pedidos: {estado.get("faltante_objetivo","sin regla")}'
        )


def recibir_emergencia(sesion):

    print("Registrá esta compra cuando la mercadería ya haya llegado al negocio.")
    print(
        "La referencia identifica esta compra: conservála para consultar o reintentar sin duplicar."
    )
    referencia = input("Referencia única de la compra: ").strip()
    while not codigo_valido(referencia):
        print(
            "Usá entre 1 y 64 letras sin tildes, números, guiones o guiones bajos; sin espacios."
        )
        referencia = input("Referencia única de la compra: ").strip()
    origen = input("Lugar de compra / proveedor de emergencia: ").strip()
    motivo = input("Motivo de emergencia: ").strip()
    empleado = input("Nombre del empleado que compró/recibió: ").strip()
    fecha = pedir_fecha_compra()
    tipo = pedir_opcion(
        "Tipo de comprobante (ticket/factura/boleta/otro): ",
        ["ticket", "factura", "boleta", "otro"],
    )
    numero = input("Número de comprobante: ").strip()
    productos = []
    while True:
        productos.append(
            {
                "producto_id": pedir_numero("ID del producto recibido: "),
                "cantidad": pedir_numero("Cantidad recibida físicamente: "),
                "costo_unitario_centavos": pedir_numero(
                    "Costo por unidad en centavos (ej. 180000 = $1800): "
                ),
            }
        )
        if (
            pedir_opcion(
                "¿Agregar otro producto del mismo comprobante? (s/n): ", ["s", "n"]
            )
            == "n"
        ):
            break
    while True:
        try:
            adjunto = leer_adjunto_emergencia()
            break
        except (OSError, ValueError):
            print(
                "No se pudo abrir el comprobante. Revisá que la ruta exista, que el archivo pueda leerse y que no supere 5 MB."
            )
            print(
                "Los datos de compra se conservan. Corregí la ruta o presioná Enter para adjuntar después."
            )
    total = sum(x["cantidad"] * x["costo_unitario_centavos"] for x in productos)
    print(
        f'Revisá antes de confirmar: {sum(x["cantidad"] for x in productos)} unidades en {len(productos)} líneas. Total: ${total//100}.{total%100:02d}.'
    )
    print(
        "Se registrarán las unidades recibidas y un gasto; la caja de ventas no se modifica."
    )
    print(
        "Origen del dinero: fondo de emergencia, con disponibilidad suficiente simulada."
    )
    if pedir_opcion("¿Confirmar recepción y gasto? (s/n): ", ["s", "n"]) != "s":
        return
    r = solicitar_compras(
        sesion,
        "PUT",
        f"/reposiciones-emergencia/{referencia}",
        datos={
            "productos": productos,
            "origen": origen,
            "motivo": motivo,
            "empleado": empleado,
            "fecha_compra": fecha,
            "tipo_comprobante": tipo,
            "numero_comprobante": numero,
            "adjunto": adjunto,
        },
    )
    if r is not None:
        print(
            "La compra ya estaba registrada: no se agregaron unidades ni gastos nuevamente."
            if r.get("operacion_repetida")
            else "Compra registrada: se sumaron las unidades al inventario y el gasto al fondo de emergencia."
        )
        mostrar_compra_emergencia(r)


def consultar_fondo_emergencia(sesion):
    pagina = 1
    while True:
        r = solicitar_compras(
            sesion, "GET", f"/fondo-emergencias?pagina={pagina}&limite=10"
        )
        if r is None:
            return
        total = r["total_egresos_centavos"]
        print(
            f"Fondo separado de la caja de ventas. Disponibilidad suficiente simulada. Gastos: ${total//100}.{total%100:02d}"
        )
        for m in r["movimientos"]:
            valor = m["importe_centavos"]
            print(
                f'{m["registrado_en"]} | {m["referencia"]} | Egreso: ${valor//100}.{valor%100:02d}'
            )
        if (
            pagina * 10 >= r["total"]
            or pedir_opcion("¿Siguiente página? (s/n): ", ["s", "n"]) == "n"
        ):
            return
        pagina += 1


def consultar_compra_emergencia(sesion):
    referencia = input("Referencia de la compra de emergencia: ").strip()
    r = solicitar_compras(sesion, "GET", f"/reposiciones-emergencia/{referencia}")
    if r is not None:
        mostrar_compra_emergencia(r)
        for p in r["productos"]:
            print(
                f'Producto {p["producto_id"]} | Unidades: {p["cantidad"]} | Costo por unidad: ${p["costo_unitario_centavos"]//100}.{p["costo_unitario_centavos"]%100:02d}'
            )


def adjuntar_comprobante_emergencia(sesion):
    referencia = input("Referencia de compra ya registrada: ").strip()
    try:
        datos = leer_adjunto_emergencia()
    except (OSError, ValueError) as error:
        print(f"No se pudo leer el comprobante: {error}")
        return
    if datos is None:
        return
    r = solicitar_compras(
        sesion, "PUT", f"/reposiciones-emergencia/{referencia}/comprobante", datos=datos
    )
    if r is not None:
        print(
            "Este mismo archivo ya estaba adjuntado. Se conserva el registro existente."
            if r.get("operacion_repetida")
            else "Comprobante adjuntado correctamente."
        )
        print("Adjuntar un comprobante no modifica el stock ni registra otro gasto.")
        mostrar_compra_emergencia(r)


def gestionar_entregas(sesion):
    """Select a customer order and confirm one permitted delivery step at a time."""
    pagina = 1
    while True:
        r = solicitar_compras(
            sesion,
            "GET",
            f"/pedidos-venta?pendientes_entrega=true&pagina={pagina}&limite=10",
        )
        if r is None:
            return
        if not r["pedidos"]:
            print("No hay pedidos pagados pendientes de entrega.")
            return
        print("Pedidos pagados por preparar, despachar o entregar:")
        ids = {p["id"] for p in r["pedidos"]}
        for p in r["pedidos"]:
            print(
                f'Pedido {p["id"]} | {etiqueta(p["modalidad"])} | {etiqueta(p["estado_entrega"])} | Total: ${p["total"]}'
            )
        print(f'Página {pagina} | Total de pedidos pendientes: {r["total"]}')
        opciones = ["1", "0"]
        if pagina * 10 < r["total"]:
            opciones.append("2")
        if pagina > 1:
            opciones.append("3")
        print("1. Elegir un pedido de esta página | 0. Volver al menú")
        if "2" in opciones:
            print("2. Siguiente página")
        if "3" in opciones:
            print("3. Página anterior")
        op = pedir_opcion("Opción: ", opciones)
        if op == "0":
            return
        if op == "2":
            pagina += 1
            continue
        if op == "3":
            pagina -= 1
            continue
        id = pedir_numero("ID del pedido de esta página: ")
        if id not in ids:
            print("Elegí uno de los pedidos listados. No se modificó ninguna entrega.")
            continue
        while True:
            pedido = solicitar_compras(sesion, "GET", f"/pedidos-venta/{id}")
            if pedido is None:
                return
            print(
                f'Pedido {id} | Pago: {etiqueta(pedido["estado_pago"])} | Entrega: {etiqueta(pedido["estado_entrega"])}'
            )
            for producto in pedido["productos"]:
                print(f'{producto["cantidad"]} x {producto["nombre"]}')
            if pedido.get("direccion_entrega"):
                print("Dirección: " + pedido["direccion_entrega"])
            proximo = pedido.get("siguiente_estado_entrega")
            if not proximo:
                print(
                    "Este pedido ya no tiene pasos de entrega pendientes. No se realizaron cambios."
                )
                return
            acciones = {
                "preparando": "Iniciar preparación",
                "listo": "Marcar listo para entregar",
                "enviado": "Confirmar despacho al domicilio",
                "entregado": "Confirmar entrega al cliente",
            }
            print("Próximo paso permitido: " + acciones[proximo])
            if proximo == "entregado":
                print("Confirmá únicamente si el cliente ya recibió la mercadería.")
            if proximo == "enviado":
                print(
                    "Confirmá únicamente si la mercadería ya salió hacia el domicilio."
                )
            if pedir_opcion("¿Registrar este paso? (s/n): ", ["s", "n"]) == "n":
                print("No se cambió el estado de entrega.")
                return
            actualizado = solicitar_compras(
                sesion, "PUT", f"/pedidos-venta/{id}/entrega", {"estado": proximo}
            )
            if actualizado is None:
                print(
                    "Consultá nuevamente el pedido antes de continuar; otro operador puede haber actualizado su estado."
                )
                return
            print(
                "Estado registrado: "
                + etiqueta(actualizado["estado_entrega"])
                + ". No se genera otro cobro ni se descuenta stock nuevamente."
            )
            if actualizado["estado_entrega"] == "entregado":
                return
            if (
                pedir_opcion(
                    "¿Continuar con el siguiente paso de este pedido? (s/n): ",
                    ["s", "n"],
                )
                == "n"
            ):
                return


def ejecutar_menu(sesion, rol, permisos=None):
    from menu_catalogo_cuentas import (
        productos as gestionar_productos,
        cuentas as gestionar_cuentas,
    )
    from menu_ventas_caja import nueva_venta, ventas as gestionar_ventas, caja_actual
    from menu_atencion import gestionar_solicitudes
    from menu_cuentas import (
        crear_cuenta,
        listar_cuentas,
        activar_cuenta,
        ver_solicitudes,
        resolver_solicitud,
        ver_avisos,
        cambiar_clave,
        restablecer_clave,
        historial_cuentas,
        historial_comercial,
    )

    acciones_compras = {
        "6": generar_pedido,
        "7": listar_pedidos_abiertos,
        "8": registrar_entrega_pedido,
        "9": partial(
            finalizar_pedido, operacion="cancelacion", descripcion="la cancelación"
        ),
        "10": partial(
            finalizar_pedido,
            operacion="cierre-incompleto",
            descripcion="el cierre incompleto",
        ),
        "11": corregir_remito,
        "12": gestionar_ventas,
        "13": consultar_detalle_venta,
        "14": guardar_ticket_venta,
        "15": gestionar_devolucion,
        "16": partial(gestionar_devolucion, cancelar=True),
        "17": simular_reintegro,
        "18": consultar_movimientos,
        "19": caja_actual,
        "20": nueva_venta,
        "21": partial(gestionar_caja_efectivo, operacion="consulta"),
        "22": partial(gestionar_caja_efectivo, operacion="movimiento"),
        "23": partial(gestionar_caja_efectivo, operacion="cierre"),
        "24": configurar_regla_reposicion,
        "25": evaluar_reposicion,
        "26": consultar_alertas_reposicion,
        "27": recibir_emergencia,
        "28": consultar_fondo_emergencia,
        "29": consultar_compra_emergencia,
        "30": adjuntar_comprobante_emergencia,
        "31": crear_cuenta,
        "32": gestionar_cuentas,
        "33": activar_cuenta,
        "34": ver_solicitudes,
        "35": resolver_solicitud,
        "36": ver_avisos,
        "37": cambiar_clave,
        "38": gestionar_entregas,
        "39": restablecer_clave,
        "40": historial_cuentas,
        "41": historial_comercial,
        "42": gestionar_respaldos,
        "43": gestionar_solicitudes,
    }
    opciones = ["1", "2", "0"]
    if rol in ("compras", "administrador", "empleado"):
        opciones.extend(["3", "4", "5", *acciones_compras])
    elif rol == "consulta":
        opciones.append("3")

    if permisos is not None:
        opciones = [x for x in opciones if x in ("0", "1", "2", "37") or x in permisos]
    etiquetas = {
        "1": "Buscar por nombre o marca",
        "2": "Elegir un producto y gestionarlo",
        "3": "Crear producto",
        "4": "Editar producto",
        "5": "Eliminar producto",
        "6": "Evaluar y solicitar reposición a proveedores",
        "7": "Elegir un pedido de abastecimiento y gestionarlo",
        "8": "Registrar mercadería recibida del proveedor",
        "9": "Cancelar pedido al proveedor sin recibir",
        "10": "Cerrar pedido recibido parcialmente",
        "11": "Corregir recepción de remito",
        "12": "Elegir una venta y gestionarla",
        "13": "Detalle de pedido de venta",
        "14": "Guardar ticket de venta",
        "15": "Recibir devolución de venta",
        "16": "Cancelar venta pagada sin despachar",
        "17": "Simular reintegro de dinero",
        "18": "Historial de inventario",
        "19": "Turno actual y operaciones de caja",
        "20": "Cobrar venta en efectivo sin identificar al cliente",
        "21": "Consultar caja de efectivo",
        "22": "Ingreso o retiro de efectivo",
        "23": "Cerrar caja de efectivo",
        "24": "Configurar reposición automática",
        "25": "Evaluar reposición ahora",
        "26": "Ver alertas de reposición",
        "27": "Registrar reposición manual de emergencia",
        "28": "Consultar fondo de emergencia",
        "29": "Consultar compra de emergencia",
        "30": "Adjuntar comprobante pendiente",
        "31": "Crear cuenta individual",
        "32": "Elegir una cuenta y gestionar acceso",
        "33": "Activar/desactivar cuenta",
        "34": "Consultar solicitudes de clientes",
        "35": "Registrar resolución de solicitud",
        "36": "Consultar avisos del proveedor",
        "37": "Cambiar mi contraseña",
        "38": "Preparar, despachar o entregar pedidos de clientes",
        "39": "Restablecer contraseña olvidada de otra cuenta",
        "40": "Historial de cambios de cuentas",
        "41": "Historial de responsables de operaciones comerciales",
        "42": "Copias de seguridad y verificación",
        "43": "Gestionar solicitudes paso a paso",
    }
    if rol == "consulta":
        etiquetas["3"] = "Comprar producto (compatibilidad)"
    navegacion = {}
    while True:
        grupos = [
            ("Catálogo e inventario", ["1", "2", "3"]),
            ("Ventas", ["20", "12"]),
            ("Entregas", ["38"]),
            ("Atención al cliente", ["43", "34", "35", "15", "16", "17"]),
            ("Caja de efectivo", ["19"]),
            ("Abastecimiento", ["7", "27", "28", "29", "30"]),
            ("Control de reposición", ["18", "25", "26"]),
            ("Cuentas y acceso", ["31", "32", "37", "40"]),
            ("Auditoría", ["41"]),
            ("Respaldos", ["42"]),
        ]
        opcion = elegir_sector(
            grupos, etiquetas, opciones, "Sectores del negocio", navegacion
        )
        if opcion == "0":
            return
        if opcion == "1":
            texto = input("Nombre o marca: ").strip()
            if not texto:
                print("Ingresá un nombre o una marca.")
                continue
            if rol in ("compras", "administrador", "empleado"):
                gestionar_productos(sesion, texto)
            else:
                mostrar_productos(sesion, texto)
        elif opcion == "2":
            if rol in ("compras", "administrador", "empleado"):
                gestionar_productos(sesion)
            else:
                mostrar_productos(sesion)
        elif rol == "consulta":
            comprar_producto(sesion)
        elif opcion in acciones_compras:
            acciones_compras[opcion](sesion)
        else:
            modificar_catalogo(sesion, opcion)


def main():
    with requests.Session() as sesion:
        sesion.auth = (input("Usuario: ").strip(), getpass("Contraseña: "))
        try:
            respuesta = sesion.get(f"{URL_API_LOCAL}/sesion", timeout=10)
            respuesta.raise_for_status()
        except requests.HTTPError as error:
            print(error_respuesta(error.response))
            return
        except requests.RequestException as error:
            print(
                "No se pudo conectar con el servidor. Comprobá que esté encendido y volvé a intentar."
            )
            return

        datos = respuesta.json()
        if datos.get("debe_cambiar_clave"):
            from menu_cuentas import cambiar_clave

            print(
                "Tu cuenta tiene una contraseña temporal. Cambiala antes de acceder al menú de operaciones."
            )
            if not cambiar_clave(sesion):
                print(
                    "No se habilitó el menú. Podés volver a iniciar sesión para completar el cambio."
                )
                return
            datos = solicitar_compras(sesion, "GET", "/sesion")
            if datos is None:
                return
        rol = datos["rol"]
        print(
            f"Sesión iniciada como {datos['usuario']}. Rol: {datos.get('rol_efectivo',rol)}."
        )
        from menu_cuentas import menu_cliente, menu_proveedor

        if rol == "cliente":
            menu_cliente(sesion)
        elif rol == "proveedor":
            menu_proveedor(sesion, datos["proveedor"])
        else:
            ejecutar_menu(sesion, rol, datos.get("opciones_operativas"))


if __name__ == "__main__":
    main()
