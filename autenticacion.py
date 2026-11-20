"""Account authentication and role-based authorization for API requests."""

import os
from secrets import compare_digest
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import repositorio_sqlite
from usuarios import consultar_usuario, verificar_clave

esquema_basico = HTTPBasic()
CUENTAS = {"consulta": "CRUD_CLAVE_CONSULTA", "compras": "CRUD_CLAVE_COMPRAS"}


class Identidad(str):
    def __new__(
        cls,
        nombre,
        rol,
        cliente_id=None,
        proveedor=None,
        legado=False,
        debe_cambiar=False,
        version=0,
    ):
        obj = super().__new__(cls, nombre)
        obj.rol, obj.cliente_id, obj.proveedor, obj.legado = (
            rol,
            cliente_id,
            proveedor,
            legado,
        )
        obj.debe_cambiar_clave, obj.version_credencial = bool(debe_cambiar), version
        return obj


def _autenticar(request, credenciales):
    nombre, clave = credenciales.username, credenciales.password
    if len(clave) > 128 or len(nombre) > 64:
        raise HTTPException(
            401, "Credenciales inválidas", headers={"WWW-Authenticate": "Basic"}
        )
    if nombre in CUENTAS:
        if os.environ.get("CRUD_CUENTAS_COMPATIBILIDAD", "1") != "1":
            raise HTTPException(
                401, "Credenciales inválidas", headers={"WWW-Authenticate": "Basic"}
            )
        esperada = os.environ.get(CUENTAS[nombre])
        if esperada and compare_digest(clave.encode(), esperada.encode()):
            return Identidad(
                nombre,
                "administrador" if nombre == "compras" else "cliente",
                legado=True,
            )
    else:
        cuenta = consultar_usuario(repositorio_sqlite.conectar_db, nombre)
        if cuenta and cuenta["activo"] and verificar_clave(clave, cuenta["clave_hash"]):
            if cuenta["debe_cambiar_clave"] and (
                request.method,
                request.url.path,
            ) not in (("GET", "/sesion"), ("PUT", "/mi-cuenta/clave")):
                raise HTTPException(
                    403,
                    "Debés cambiar tu contraseña temporal antes de continuar. Iniciá el menú con esa contraseña para elegir una nueva.",
                )
            return Identidad(
                nombre,
                cuenta["rol"],
                cuenta["cliente_id"],
                cuenta["proveedor"],
                debe_cambiar=cuenta["debe_cambiar_clave"],
                version=cuenta["version_credencial"],
            )
    raise HTTPException(
        401, "Credenciales inválidas", headers={"WWW-Authenticate": "Basic"}
    )


async def autenticar(
    request: Request, credenciales: HTTPBasicCredentials = Depends(esquema_basico)
):
    import asyncio
    from auditoria_comercial import identidad_actual

    identidad = await asyncio.to_thread(_autenticar, request, credenciales)
    token = identidad_actual.set(identidad)
    try:
        yield identidad
    finally:
        identidad_actual.reset(token)


OPCIONES_EMPLEADO = {
    "7",
    "8",
    "12",
    "13",
    "14",
    "15",
    "17",
    "18",
    "19",
    "20",
    "21",
    "23",
    "27",
    "28",
    "29",
    "30",
}
RUTAS_EMPLEADO = {
    ("GET", "/pedidos"),
    ("GET", "/pedidos/{id}"),
    ("PUT", "/pedidos/{id}/recepcion"),
    ("PUT", "/pedidos/{id}/recepciones/{referencia}"),
    ("GET", "/ventas"),
    ("PUT", "/pedidos-venta/{id}/entrega"),
    ("PUT", "/pedidos-venta/{id}/devoluciones/{referencia}"),
    ("PUT", "/pedidos-venta/{id}/devoluciones/{referencia}/reintegro"),
    ("GET", "/inventario/movimientos"),
    ("PUT", "/cajas/{referencia}/apertura"),
    ("GET", "/cajas"),
    ("GET", "/cajas/{referencia}"),
    ("PUT", "/cajas/{referencia}/cierre"),
    ("PUT", "/ventas-efectivo/{referencia}"),
    ("PUT", "/productos/{id}/reposiciones-emergencia/{referencia}"),
    ("PUT", "/reposiciones-emergencia/{referencia}"),
    ("GET", "/reposiciones-emergencia"),
    ("GET", "/reposiciones-emergencia/{referencia}"),
    ("PUT", "/reposiciones-emergencia/{referencia}/comprobante"),
    ("GET", "/reposiciones-emergencia/{referencia}/comprobante"),
    ("GET", "/fondo-emergencias"),
}


def exigir_compras(request: Request, usuario: str = Depends(autenticar)):
    if usuario.rol == "administrador":
        return usuario
    ruta = request.scope["route"].path
    if usuario.rol == "empleado" and (request.method, ruta) in RUTAS_EMPLEADO:
        return usuario
    if (
        usuario.rol == "proveedor"
        and request.method == "GET"
        and ruta in ("/pedidos", "/pedidos/{id}", "/proveedores/{proveedor}/ofertas")
    ):
        if (
            "proveedor" in request.path_params
            and request.path_params["proveedor"] != usuario.proveedor
        ):
            raise HTTPException(404, "Catálogo no encontrado")
        return usuario
    raise HTTPException(403, "Tu rol no tiene permiso para esta operación")


def exigir_consulta(request: Request, usuario: str = Depends(autenticar)):
    if (
        usuario.rol not in ("cliente", "empleado", "administrador")
        or str(usuario) == "compras"
    ):
        raise HTTPException(403, "Tu cuenta no puede realizar esta operación de compra")
    ruta = request.scope["route"].path
    if not usuario.legado and ruta == "/ventas/{referencia}":
        raise HTTPException(
            403,
            "Para ventas presenciales usá la caja; para compras online creá un pedido con pago",
        )
    if usuario.rol == "cliente":
        if ruta.startswith("/cobros-demo/"):
            from contextlib import closing
            from usuarios import comprobar_titular

            with closing(repositorio_sqlite.conectar_db()) as db:
                comprobar_titular(db, "qr", request.path_params["referencia"], usuario)
            if not usuario.legado and ruta not in (
                "/cobros-demo/{referencia}",
                "/cobros-demo/{referencia}/pago",
            ):
                raise HTTPException(
                    403,
                    "La gestión técnica del proveedor de pagos corresponde al personal del negocio",
                )
    return usuario


def exigir_administrador(usuario: str = Depends(autenticar)):
    if usuario.rol != "administrador":
        raise HTTPException(403, "Se requiere una cuenta administradora")
    return usuario
