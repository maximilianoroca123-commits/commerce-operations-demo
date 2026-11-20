"""Historical console client module for the existing HTTP business operations."""

import re
from validaciones import pedir_opcion
from mensajes import etiqueta
from menu_cuentas import api


def pedir_costo():
    while True:
        texto = input(
            "Costo real por unidad en pesos (ej. 1200 o 1200,50; sin separador de miles): "
        ).strip()
        if re.fullmatch(r"\d{1,16}([.,]\d{1,2})?", texto):
            partes = texto.replace(",", ".").split(".")
            centavos = int(partes[0]) * 100 + int(
                (partes[1] if len(partes) > 1 else "").ljust(2, "0")
            )
            if 0 < centavos <= 2**63 - 1:
                return centavos
        print(
            "Ingresá un importe positivo, con hasta dos decimales y sin separadores de miles."
        )


def pedidos(sesion):
    from menu_api import mostrar_pedido

    pagina = 1
    filtro = "abiertos"
    while True:
        r = api(
            sesion,
            "GET",
            f"/abastecimiento/pedidos?filtro={filtro}&pagina={pagina}&limite=10",
        )
        if r is None:
            return
        print(f'\nAbastecimiento · {filtro} | Página {pagina} | Total: {r["total"]}')
        for n, p in enumerate(r["pedidos"], 1):
            print(f'{n}. Seleccionar pedido {p["id"]}')
            mostrar_pedido(p)
        if not r["pedidos"]:
            print("No hay pedidos para este filtro.")
        print("t. Alternar abiertos/todos | 0. Volver al sector")
        opciones = ["0", "t", *[str(n) for n in range(1, len(r["pedidos"]) + 1)]]
        if pagina * 10 < r["total"]:
            opciones.append("s")
            print("s. Siguiente página")
        if pagina > 1:
            opciones.append("a")
            print("a. Página anterior")
        op = pedir_opcion("Pedido de la página: ", opciones)
        if op == "0":
            return
        if op == "t":
            filtro = "todos" if filtro == "abiertos" else "abiertos"
            pagina = 1
            continue
        if op == "s":
            pagina += 1
            continue
        if op == "a":
            pagina -= 1
            continue
        gestionar(sesion, r["pedidos"][int(op) - 1]["id"])


def remitos(sesion, id, corregir=False):
    from menu_api import corregir_remito

    pagina = 1
    while True:
        r = api(
            sesion,
            "GET",
            f"/abastecimiento/pedidos/{id}/remitos?pagina={pagina}&limite=10",
        )
        if r is None:
            return
        for n, x in enumerate(r["remitos"], 1):
            costo = x["costo_pagado_centavos"]
            print(
                f'{n}. {x["referencia"]} | Cantidad: {x["cantidad"]} | Costo unitario: ${costo//100},{costo%100:02d} | {x["registrado_en"]} UTC'
            )
        if not r["remitos"]:
            print("No hay remitos registrados.")
            return
        opciones = ["0"]
        if corregir:
            opciones.extend(str(n) for n in range(1, len(r["remitos"]) + 1))
        if pagina * 10 < r["total"]:
            opciones.append("s")
        if pagina > 1:
            opciones.append("a")
        if len(opciones) == 1:
            return
        print("0. Volver | s/a. Cambiar página cuando esté disponible")
        op = pedir_opcion("Remito a corregir: " if corregir else "Página: ", opciones)
        if op == "0":
            return
        if op == "s":
            pagina += 1
            continue
        if op == "a":
            pagina -= 1
            continue
        x = r["remitos"][int(op) - 1]
        corregir_remito(
            sesion,
            pedido_id=id,
            referencia=x["referencia"],
            en_pesos=True,
            remito_actual=x,
        )
        return


def avisos(sesion, id):
    pagina = 1
    while True:
        r = api(
            sesion,
            "GET",
            f"/abastecimiento/pedidos/{id}/avisos?pagina={pagina}&limite=10",
        )
        if r is None:
            return
        if not r["avisos"]:
            print("El proveedor todavía no registró avisos para este pedido.")
        for x in r["avisos"]:
            print(f'{x["registrado_en"]} UTC | {etiqueta(x["estado"])} | {x["nota"]}')
        opciones = ["0"]
        if pagina * 10 < r["total"]:
            opciones.append("s")
        if pagina > 1:
            opciones.append("a")
        if len(opciones) == 1:
            return
        print("0. Volver | s/a. Cambiar página cuando esté disponible")
        op = pedir_opcion("Página: ", opciones)
        if op == "0":
            return
        pagina += 1 if op == "s" else -1


def historial(sesion, id):
    from menu_cuentas import mostrar_detalle_historial

    pagina = 1
    while True:
        r = api(
            sesion,
            "GET",
            f"/auditoria/comercial/pedido_proveedor/{id}?pagina={pagina}&limite=10",
        )
        if r is None:
            return
        if not r["movimientos"]:
            print(
                "Sin eventos desde la incorporación del historial. No se reconstruye el pasado."
            )
        for x in r["movimientos"]:
            print(
                f'{x["registrado_en"]} UTC | {etiqueta(x["accion"])} | Responsable: {x["actor"]}'
            )
            mostrar_detalle_historial(x["detalle"])
        if (
            pagina * 10 >= r["total"]
            or pedir_opcion("¿Siguiente página? (s/n): ", ["s", "n"]) == "n"
        ):
            return
        pagina += 1


def gestionar(sesion, id):
    from menu_api import mostrar_pedido, registrar_entrega_pedido, finalizar_pedido

    nombres = {
        "1": ("detalle", "Ver detalle"),
        "2": ("recibir", "Recibir mercadería"),
        "3": ("remitos", "Ver remitos"),
        "4": ("avisos", "Ver avisos del proveedor"),
        "5": ("historial", "Ver historial de responsables"),
        "6": ("cancelar", "Cancelar pedido sin recibir"),
        "7": ("cerrar", "Cerrar recepción incompleta"),
        "8": ("corregir", "Corregir un remito"),
    }
    while True:
        c = api(sesion, "GET", f"/abastecimiento/pedidos/{id}")
        if c is None:
            return
        p = c["pedido"]
        mostrar_pedido(p)
        print("Producto: " + c["producto_nombre"])
        opciones = {
            n: v
            for n, v in nombres.items()
            if v[0] == "detalle" or v[0] in c["acciones"]
        }
        for n, (_, texto) in opciones.items():
            print(n + ". " + texto)
        print("0. Volver a la lista")
        op = pedir_opcion("Acción sobre este pedido: ", ["0", *opciones])
        if op == "0":
            return
        accion = opciones[op][0]
        if accion == "detalle":
            print(
                f'Oferta: {p["id_externo"]} | Solicitadas: {p["cantidad"]} | Recibidas: {p["cantidad_recibida"]} | Pendientes: {p["cantidad_pendiente"]}'
            )
            print(
                "Los avisos de despacho del proveedor no equivalen a una recepción física."
            )
        elif accion == "recibir":
            print(
                f'Registrá sólo lo recibido físicamente. Pendiente: {p["cantidad_pendiente"]}. Conservá la referencia real del remito para reintentar sin duplicar stock.'
            )
            registrar_entrega_pedido(sesion, pedido_id=id, en_pesos=True)
        elif accion == "remitos":
            remitos(sesion, id)
        elif accion == "avisos":
            avisos(sesion, id)
        elif accion == "historial":
            historial(sesion, id)
        elif accion == "corregir":
            remitos(sesion, id, corregir=True)
        elif accion == "cancelar":
            finalizar_pedido(sesion, "cancelacion", "la cancelación", pedido_id=id)
        elif accion == "cerrar":
            finalizar_pedido(
                sesion, "cierre-incompleto", "el cierre incompleto", pedido_id=id
            )
