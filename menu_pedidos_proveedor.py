"""Historical console client module for the existing HTTP business operations."""

import hashlib
import json
from urllib.parse import quote
from validaciones import pedir_opcion
from mensajes import etiqueta
from menu_cuentas import api


def mostrar_ofertas(sesion, proveedor):
    filas = api(sesion, "GET", f'/proveedores/{quote(proveedor,safe="")}/ofertas')
    if filas is None:
        return
    if not filas:
        print("No hay ofertas registradas para tu proveedor.")
        return
    for x in filas:
        costo = x["costo_centavos"]
        print(
            f'{x["id_externo"]} | {x["nombre"]} | {x["marca"]} | Costo unitario: ${costo//100},{costo%100:02d} | Stock informado: {x["stock_proveedor"]} | '
            + ("Activa" if x["vigente"] else "Inactiva")
        )


def mis_pedidos(sesion):
    pagina = 1
    filtro = "abiertos"
    from menu_api import mostrar_pedido

    while True:
        r = api(
            sesion,
            "GET",
            f"/mi-proveedor/pedidos?filtro={filtro}&pagina={pagina}&limite=10",
        )
        if r is None:
            return
        print(
            "\nPedidos "
            + ("abiertos" if filtro == "abiertos" else "de todos los estados")
            + f' | Página {pagina} | Total: {r["total"]}'
        )
        filas = r["pedidos"]
        for n, p in enumerate(filas, 1):
            print(f'{n}. Seleccionar pedido {p["id"]}')
            mostrar_pedido(p)
        if not filas:
            print("No hay pedidos para este filtro.")
        opciones = ["0", "t", *[str(n) for n in range(1, len(filas) + 1)]]
        print(
            "t. "
            + (
                "Ver todos, incluidos cerrados"
                if filtro == "abiertos"
                else "Ver sólo abiertos"
            )
            + " | 0. Volver al sector"
        )
        if pagina * 10 < r["total"]:
            opciones.append("s")
            print("s. Siguiente página")
        if pagina > 1:
            opciones.append("a")
            print("a. Página anterior")
        op = pedir_opcion("Elegí un pedido de la lista: ", opciones)
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
        gestionar(sesion, filas[int(op) - 1]["id"])


def mostrar_avisos(sesion, pedido_id):
    pagina = 1
    while True:
        r = api(
            sesion,
            "GET",
            f"/mi-proveedor/pedidos/{pedido_id}/avisos?pagina={pagina}&limite=10",
        )
        if r is None:
            return
        if not r["avisos"]:
            print("Todavía no hay avisos para este pedido.")
        for x in r["avisos"]:
            print(
                f'{x["registrado_en"]} UTC | {etiqueta(x["estado"])} | {x["nota"]} | Referencia: {x["referencia"]}'
            )
        opciones = ["0"]
        if pagina * 10 < r["total"]:
            opciones.append("s")
        if pagina > 1:
            opciones.append("a")
        if len(opciones) == 1:
            return
        print(
            "s. Siguiente página (si disponible) | a. Anterior (si disponible) | 0. Volver"
        )
        op = pedir_opcion("Página: ", opciones)
        if op == "0":
            return
        pagina += 1 if op == "s" else -1


def informar(sesion, contexto):
    pedido_id = contexto["pedido"]["id"]
    estados = contexto["acciones_aviso"]
    if not estados:
        print("El pedido está cerrado; sólo se consulta.")
        return
    for n, estado in enumerate(estados, 1):
        print(f"{n}. {etiqueta(estado)}")
    op = pedir_opcion(
        "Estado a informar (0 para volver): ",
        ["0", *[str(n) for n in range(1, len(estados) + 1)]],
    )
    if op == "0":
        return
    datos = {
        "estado": estados[int(op) - 1],
        "nota": input("Nota para el negocio: ").strip(),
    }
    if not datos["nota"]:
        print("Ingresá una nota. No se registró ningún aviso.")
        return
    ultimo = contexto["ultimo_aviso"]
    if ultimo and all(ultimo[k] == datos[k] for k in ("estado", "nota")):
        print("El último aviso ya contiene este estado y esta nota. No se duplicó.")
        return

    contenido = json.dumps(
        [pedido_id, ultimo["referencia"] if ultimo else None, datos],
        sort_keys=True,
        ensure_ascii=False,
    )
    referencia = "aviso-" + hashlib.sha256(contenido.encode()).hexdigest()[:32]
    print(f'Pedido {pedido_id} | {etiqueta(datos["estado"])} | {datos["nota"]}')
    print("Referencia automática para reintentar: " + referencia)
    print(
        "Este aviso no ingresa mercadería al inventario ni confirma su recepción por el negocio."
    )
    if pedir_opcion("¿Confirmar envío del aviso? (s/n): ", ["s", "n"]) != "s":
        return
    while True:
        r = api(
            sesion,
            "PUT",
            f"/mi-proveedor/pedidos/{pedido_id}/avisos/{referencia}",
            datos,
        )
        if r is not None:
            print(r["mensaje"])
            return
        print(
            "No se confirmó la respuesta. Consultá los avisos antes de crear uno diferente."
        )
        if (
            pedir_opcion("¿Reintentar exactamente el mismo aviso? (s/n): ", ["s", "n"])
            != "s"
        ):
            return


def gestionar(sesion, pedido_id):
    from menu_api import mostrar_pedido

    while True:
        c = api(sesion, "GET", f"/mi-proveedor/pedidos/{pedido_id}")
        if c is None:
            return
        p = c["pedido"]
        mostrar_pedido(p)
        if c["ultimo_aviso"]:
            print(
                "Último aviso: "
                + etiqueta(c["ultimo_aviso"]["estado"])
                + " | "
                + c["ultimo_aviso"]["nota"]
            )
        print("1. Ver detalle | 2. Ver avisos | 0. Volver a la lista")
        opciones = ["0", "1", "2"]
        if c["acciones_aviso"]:
            opciones.append("3")
            print("3. Informar estado al negocio")
        else:
            print(
                "Pedido cerrado: los avisos anteriores quedan disponibles para consulta."
            )
        op = pedir_opcion("Acción sobre este pedido: ", opciones)
        if op == "0":
            return
        if op == "1":
            print(
                f'Oferta del proveedor: {p["id_externo"]} | Cantidad solicitada: {p["cantidad"]} | Estado de recepción: {etiqueta(p["estado"])}'
            )
            print(
                "La recepción de stock la registra el personal del negocio cuando recibe físicamente los productos."
            )
        elif op == "2":
            mostrar_avisos(sesion, pedido_id)
        else:
            informar(sesion, c)
