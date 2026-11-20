"""Historical console client module for the existing HTTP business operations."""

from validaciones import pedir_opcion


def elegir_sector(grupos, etiquetas, permitidas, titulo="Sectores", estado=None):
    if estado is None:
        estado = {}
    visibles = [
        (nombre, [n for n in numeros if n in permitidas]) for nombre, numeros in grupos
    ]
    visibles = [g for g in visibles if g[1]]
    while True:
        sector = estado.get("sector")
        if sector is None:
            print("\n" + titulo)
            for i, (nombre, _) in enumerate(visibles, 1):
                print(f"{i}. {nombre}")
            print("0. Salir")
            sector = pedir_opcion(
                "Sector: ", ["0"] + [str(i) for i in range(1, len(visibles) + 1)]
            )
            if sector == "0":
                return "0"
            estado["sector"] = sector
        nombre, numeros = visibles[int(sector) - 1]
        print("\n" + nombre)
        for n in numeros:
            print(f"{n}. {etiquetas[n]}")
        print("0. Volver a sectores")
        accion = pedir_opcion("Acción: ", ["0", *numeros])
        if accion != "0":
            return accion
        estado.pop("sector", None)
