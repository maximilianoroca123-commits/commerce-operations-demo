"""Historical console client module for the existing HTTP business operations."""


def gestionar(sesion):
    from menu_cuentas import api, pedir_opcion

    print(
        "1. Crear copia completa / 2. Listar copias / 3. Verificar recuperación aislada / 0. Volver"
    )
    opcion = pedir_opcion("Opción: ", ["0", "1", "2", "3"])
    if opcion == "0":
        return
    if opcion == "1":
        r = api(sesion, "POST", "/respaldos")
        if r:
            print("Copia verificada: " + r["archivo"])
            print(
                "Integridad, relaciones y consultas del programa: OK. La base de trabajo no se reemplazó."
            )
    else:
        r = api(sesion, "GET", "/respaldos")
        if not r:
            return
        for n, x in enumerate(r["respaldos"], 1):
            print(
                f'{n}. {x["archivo"]} | {x.get("creado_en", "")} | {x.get("actor", "")} | {x.get("error", "Verificada al crear; se puede volver a verificar")}'
            )
        if not r["respaldos"]:
            print("Todavía no hay copias.")
            return
        if opcion == "3":
            numero = pedir_opcion(
                "Número de la copia (0 para volver): ",
                ["0"] + [str(n) for n in range(1, len(r["respaldos"]) + 1)],
            )
            if numero == "0":
                return
            from urllib.parse import quote

            nombre = r["respaldos"][int(numero) - 1]["archivo"]
            resultado = api(
                sesion, "POST", "/respaldos/" + quote(nombre, safe="") + "/verificacion"
            )
            if resultado:
                v = resultado["verificacion"]
                print(
                    f'Recuperación aislada: OK | Productos: {v["productos"]} | Cuentas: {v["cuentas"]} | Pedidos de venta: {v["pedidos_venta"]}'
                )
                print(
                    "Se verificaron integridad, relaciones y consultas sin ejecutar pagos ni reposición. Tu base actual sigue igual."
                )
