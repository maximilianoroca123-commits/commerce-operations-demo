"""ES/EN setup of synthetic local demonstration accounts without shipped passwords."""

import argparse
from getpass import getpass
import preparar_db_api
from repositorio_sqlite import conectar_db
from usuarios import AltaUsuario, crear_usuario, consultar_usuario

ACCOUNTS = (
    ("demo_admin", "administrador", {}),
    ("demo_staff", "empleado", {}),
    (
        "demo_customer",
        "cliente",
        {
            "cliente": {
                "nombre": "Demo",
                "apellido": "Customer",
                "correo": "customer@example.com",
            }
        },
    ),
    ("demo_supplier", "proveedor", {"proveedor": "demo"}),
)


def create_demo_accounts(password, connect=conectar_db):
    """Create missing accounts only; never reset passwords or replace existing data."""
    created = []
    for username, role, extra in ACCOUNTS:
        if consultar_usuario(connect, username):
            continue
        crear_usuario(
            connect,
            AltaUsuario(usuario=username, clave=password, rol=role, **extra),
            "local_demo_setup",
        )
        created.append(username)
    return created


def main():
    parser = argparse.ArgumentParser(
        description="Local ES/EN demonstration account setup"
    )
    parser.add_argument("--language", choices=("es", "en"), default="es")
    language = parser.parse_args().language

    def t(es, en):
        return en if language == "en" else es

    preparar_db_api.preparar_db_api()
    print(
        t(
            "Preparación local: las cuentas existentes no se modifican.",
            "Local setup: existing accounts are not modified.",
        )
    )
    while True:
        password = getpass(
            t(
                "Contraseña de prueba para las cuentas nuevas (10–128 caracteres ASCII): ",
                "Demo password for new accounts (10–128 ASCII characters): ",
            )
        )
        repeat = getpass(t("Repetir contraseña: ", "Repeat password: "))
        if (
            password == repeat
            and 10 <= len(password) <= 128
            and all(32 <= ord(c) <= 126 for c in password)
        ):
            break
        print(
            t(
                "Las contraseñas deben coincidir y cumplir el formato indicado.",
                "Passwords must match and meet the stated format.",
            )
        )
    created = create_demo_accounts(password)
    print(
        t("Cuentas creadas: ", "Created accounts: ")
        + (
            ", ".join(created)
            or t("Ninguna; ya existían.", "None; they already existed.")
        )
    )
    role_labels = {
        "administrador": t("Administrador", "Administrator"),
        "empleado": t("Empleado", "Employee"),
        "cliente": t("Cliente", "Customer"),
        "proveedor": t("Proveedor", "Supplier"),
    }
    for username, role, _ in ACCOUNTS:
        print(username + " · " + role_labels[role])
    print(
        t(
            "Las cuentas nuevas usan la contraseña elegida; las anteriores conservan la suya.",
            "New accounts use the chosen password; existing accounts keep their current password.",
        )
    )
    print("http://127.0.0.1:8000/interfaz/")


if __name__ == "__main__":
    main()
