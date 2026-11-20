"""Local administrative entry point for offline backup restoration."""

import argparse
import json
from pathlib import Path
from config import RUTA_DB_API
from respaldos import restaurar, verificar, ErrorRespaldo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archivo", help="Nombre del ZIP dentro de la carpeta respaldos")
    parser.add_argument(
        "--verificar", action="store_true", help="Comprobar sin restaurar"
    )
    args = parser.parse_args()
    try:
        if args.verificar:
            r = verificar(RUTA_DB_API, args.archivo)
            print(json.dumps(r["verificacion"], ensure_ascii=False, indent=2))
            return
        print(
            "Detené el servidor, los menús y cualquier herramienta que use esta base."
        )
        print(
            "Restaurar reemplaza los datos actuales y puede recuperar contraseñas anteriores. No revierte operaciones externas."
        )
        print("Base que se reemplazará: " + str(Path(RUTA_DB_API).resolve()))
        if input("Para continuar escribí RESTAURAR: ") != "RESTAURAR":
            print("Cancelado; no se modificó la base.")
            return
        r = restaurar(RUTA_DB_API, args.archivo)
        print(
            "Restauración completada. Resguardo anterior: "
            + str(r["resguardo_anterior"])
        )
    except (ErrorRespaldo, OSError) as e:
        parser.exit(1, "No se completó: " + str(e) + "\n")


if __name__ == "__main__":
    main()
