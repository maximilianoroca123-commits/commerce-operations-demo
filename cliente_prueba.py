"""Manual HTTP examples used during development."""

from getpass import getpass

import requests

if __name__ == "__main__":
    respuesta = requests.get(
        "http://127.0.0.1:8000/productos",
        params={"categoria": "tecnologia", "pagina": 1, "limite": 2},
        auth=(input("Usuario: ").strip(), getpass("Contraseña: ")),
        timeout=10,
    )
    print(respuesta.status_code)
    print(respuesta.json())
