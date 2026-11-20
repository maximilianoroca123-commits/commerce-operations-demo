"""API route group: usuarios."""

from auditoria_comercial import registrar as auditar

import sqlite3
from contextlib import closing
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from autenticacion import autenticar, exigir_administrador
from usuarios import (
    AltaUsuario,
    EstadoUsuario,
    CambioClave,
    crear_usuario,
    verificar_clave,
    hash_clave,
    exigir_titular,
    registrar_cuenta,
    RestablecerClave,
)
import repositorio_sqlite

router = APIRouter()
Ref = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Pos = Annotated[int, Path(gt=0, le=2**63 - 1)]


@router.post("/usuarios", status_code=201)
def alta(datos: AltaUsuario, actor: str = Depends(exigir_administrador)):
    return crear_usuario(repositorio_sqlite.conectar_db, datos, actor)


@router.get("/usuarios")
def listado(
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 20,
    actor: str = Depends(exigir_administrador),
):
    with closing(repositorio_sqlite.conectar_db()) as db:
        db.row_factory = sqlite3.Row
        filas = db.execute(
            "SELECT usuario,rol,cliente_id,proveedor,activo,debe_cambiar_clave,creado_en FROM usuarios ORDER BY usuario LIMIT ? OFFSET ?",
            (limite, (pagina - 1) * limite),
        )
        return {
            "usuarios": [dict(x) for x in filas],
            "total": db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0],
            "pagina": pagina,
            "limite": limite,
        }


@router.put("/usuarios/{nombre}/estado")
def estado(
    nombre: str, datos: EstadoUsuario, actor: str = Depends(exigir_administrador)
):
    if nombre == str(actor):
        raise HTTPException(
            409, "No podés desactivar tu propia cuenta durante esta sesión"
        )
    with closing(repositorio_sqlite.conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        cuenta = db.execute(
            "SELECT rol,activo FROM usuarios WHERE usuario=?", (nombre,)
        ).fetchone()
        if not cuenta:
            raise HTTPException(
                404,
                "Cuenta no encontrada; las cuentas de compatibilidad se configuran por variables de entorno",
            )
        if cuenta["rol"] == "administrador" and not datos.activo and cuenta["activo"]:
            otras = db.execute(
                "SELECT COUNT(*) FROM usuarios WHERE rol='administrador' AND activo=1 AND usuario!=?",
                (nombre,),
            ).fetchone()[0]
            if not otras:
                raise HTTPException(
                    409, "Conservá al menos una cuenta administradora individual activa"
                )
        if bool(cuenta["activo"]) != datos.activo:
            db.execute(
                "UPDATE usuarios SET activo=? WHERE usuario=?",
                (int(datos.activo), nombre),
            )
            registrar_cuenta(
                db,
                actor,
                nombre,
                "cuenta_activada" if datos.activo else "cuenta_desactivada",
                {},
            )
        return {"usuario": nombre, "activo": datos.activo}


@router.put("/mi-cuenta/clave")
def clave(datos: CambioClave, actor: str = Depends(autenticar)):
    if actor.legado:
        raise HTTPException(
            409,
            "Esta cuenta de compatibilidad usa una clave de entorno. Creá una cuenta individual",
        )
    nueva = hash_clave(datos.nueva)
    with closing(repositorio_sqlite.conectar_db()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        anterior = db.execute(
            "SELECT clave_hash,activo,version_credencial FROM usuarios WHERE usuario=?",
            (str(actor),),
        ).fetchone()
        if not anterior[1] or anterior[2] != actor.version_credencial:
            raise HTTPException(
                409,
                "La cuenta cambió mientras realizabas la operación. Volvé a iniciar sesión.",
            )
        if not verificar_clave(datos.actual, anterior[0]):
            raise HTTPException(409, "La contraseña actual no coincide")
        if verificar_clave(datos.nueva, anterior[0]):
            raise HTTPException(
                409, "Elegí una contraseña diferente de la actual o temporal"
            )
        db.execute(
            "UPDATE usuarios SET clave_hash=?,debe_cambiar_clave=0,version_credencial=version_credencial+1 WHERE usuario=?",
            (nueva, str(actor)),
        )
        registrar_cuenta(db, actor, str(actor), "clave_cambiada", {})
        return {
            "mensaje": "Contraseña actualizada. Usá la nueva al volver a iniciar sesión."
        }


@router.put("/usuarios/{nombre}/restablecimientos/{referencia}")
def restablecer(
    nombre: str,
    referencia: Ref,
    datos: RestablecerClave,
    actor: str = Depends(exigir_administrador),
):
    if nombre == str(actor):
        raise HTTPException(409, "Para tu propia cuenta usá Cambiar mi contraseña")
    nueva = hash_clave(datos.temporal)
    with closing(repositorio_sqlite.conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        cuenta = db.execute(
            "SELECT activo,clave_hash FROM usuarios WHERE usuario=?", (nombre,)
        ).fetchone()
        if not cuenta:
            raise HTTPException(
                404,
                "Cuenta individual no encontrada; las cuentas de compatibilidad usan variables de entorno",
            )
        anterior = db.execute(
            "SELECT * FROM restablecimientos_clave WHERE usuario=? AND referencia=?",
            (nombre, referencia),
        ).fetchone()
        if anterior:
            if (
                not verificar_clave(datos.temporal, anterior["clave_hash"])
                or datos.motivo != anterior["motivo"]
            ):
                raise HTTPException(
                    409,
                    "Esta referencia de restablecimiento ya corresponde a otros datos",
                )
            return {
                "usuario": nombre,
                "estado": "ya_registrado",
                "mensaje": "Este restablecimiento ya estaba registrado. No se volvió a modificar la contraseña.",
            }
        if not cuenta["activo"]:
            raise HTTPException(
                409,
                "La cuenta está desactivada. Revisá si corresponde reactivarla antes de restablecer su contraseña",
            )
        if verificar_clave(datos.temporal, cuenta["clave_hash"]):
            raise HTTPException(
                409, "La contraseña temporal debe ser diferente de la contraseña actual"
            )
        db.execute(
            "UPDATE usuarios SET clave_hash=?,debe_cambiar_clave=1,version_credencial=version_credencial+1 WHERE usuario=?",
            (nueva, nombre),
        )
        db.execute(
            "INSERT INTO restablecimientos_clave(usuario,referencia,clave_hash,motivo,actor) VALUES (?,?,?,?,?)",
            (nombre, referencia, nueva, datos.motivo, str(actor)),
        )
        registrar_cuenta(
            db,
            actor,
            nombre,
            "clave_restablecida",
            {"referencia": referencia, "motivo": datos.motivo},
        )
        return {
            "usuario": nombre,
            "estado": "registrado",
            "mensaje": "Contraseña temporal registrada. La anterior ya no permite acceder; el usuario debe cambiar la temporal antes de operar.",
        }


@router.get("/auditoria/cuentas")
def historial_cuentas(
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 20,
    usuario: str | None = None,
    actor: str = Depends(exigir_administrador),
):
    import json

    condicion = " WHERE afectado=?" if usuario else ""
    valores = [usuario] if usuario else []
    with closing(repositorio_sqlite.conectar_db()) as db:
        db.row_factory = sqlite3.Row
        filas = []
        for f in db.execute(
            "SELECT * FROM auditoria_cuentas"
            + condicion
            + " ORDER BY id DESC LIMIT ? OFFSET ?",
            [*valores, limite, (pagina - 1) * limite],
        ):
            fila = dict(f)
            fila["detalle"] = json.loads(fila["detalle"])
            filas.append(fila)
        return {
            "movimientos": filas,
            "total": db.execute(
                "SELECT COUNT(*) FROM auditoria_cuentas" + condicion, valores
            ).fetchone()[0],
            "pagina": pagina,
            "limite": limite,
        }


@router.get("/mi-perfil")
def perfil(actor: str = Depends(autenticar)):
    if actor.rol != "cliente":
        raise HTTPException(403, "Esta consulta corresponde al perfil del cliente")
    if not actor.cliente_id:
        return {
            "usuario": str(actor),
            "cliente": None,
            "mensaje": "Cuenta de compatibilidad sin ficha personal",
        }
    with closing(repositorio_sqlite.conectar_db()) as db:
        db.row_factory = sqlite3.Row
        return {
            "usuario": str(actor),
            "cliente": dict(
                db.execute(
                    "SELECT * FROM clientes WHERE id=?", (actor.cliente_id,)
                ).fetchone()
            ),
        }


class Solicitud(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: Literal["devolucion", "cancelacion"]
    motivo: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


@router.put("/pedidos-venta/{id}/solicitudes/{referencia}")
def solicitar(
    id: Pos, referencia: Ref, datos: Solicitud, actor: str = Depends(autenticar)
):
    if actor.rol != "cliente":
        raise HTTPException(403, "Solo el cliente puede registrar su solicitud")
    exigir_titular(repositorio_sqlite.conectar_db, id, actor)
    with closing(repositorio_sqlite.conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        anterior = db.execute(
            "SELECT * FROM solicitudes_cliente WHERE pedido_id=? AND referencia=?",
            (id, referencia),
        ).fetchone()
        if anterior:
            if (anterior["tipo"], anterior["motivo"]) != (datos.tipo, datos.motivo):
                raise HTTPException(
                    409, "La referencia ya corresponde a otra solicitud"
                )
            return dict(anterior)
        pedido = db.execute(
            "SELECT estado_pago,estado_entrega FROM pedidos_venta WHERE id=?", (id,)
        ).fetchone()
        if pedido["estado_pago"] != "aprobado":
            raise HTTPException(
                409, "El pedido debe estar pagado para solicitar esta gestión"
            )
        if datos.tipo == "devolucion" and pedido["estado_entrega"] != "entregado":
            raise HTTPException(
                409, "La devolución se solicita después de recibir la mercadería"
            )
        if datos.tipo == "cancelacion" and pedido["estado_entrega"] not in (
            "pendiente",
            "preparando",
            "listo",
        ):
            raise HTTPException(
                409, "El pedido ya fue despachado o cerrado; consultá al negocio"
            )
        db.execute(
            "INSERT INTO solicitudes_cliente(pedido_id,referencia,usuario,tipo,motivo) VALUES (?,?,?,?,?)",
            (id, referencia, str(actor), datos.tipo, datos.motivo),
        )
        auditar(
            db,
            "venta",
            id,
            "solicitud_cliente_creada",
            {"referencia": referencia, "tipo": datos.tipo},
        )
        return dict(
            db.execute(
                "SELECT * FROM solicitudes_cliente WHERE pedido_id=? AND referencia=?",
                (id, referencia),
            ).fetchone()
        )


@router.get("/solicitudes-clientes")
def solicitudes(
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 20,
    estado: Literal["pendiente_revision", "atendida", "rechazada"] | None = None,
    pedido_id: Annotated[int | None, Query(gt=0)] = None,
    actor: str = Depends(autenticar),
):
    if actor.rol == "proveedor":
        raise HTTPException(403, "El proveedor no accede a solicitudes de clientes")
    filtros = []
    valores = []
    if actor.rol == "cliente":
        filtros.append("s.usuario=?")
        valores.append(str(actor))
    if estado is not None:
        filtros.append("s.estado=?")
        valores.append(estado)
    if pedido_id is not None:
        filtros.append("s.pedido_id=?")
        valores.append(pedido_id)
    condicion = " WHERE " + " AND ".join(filtros) if filtros else ""
    with closing(repositorio_sqlite.conectar_db()) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        filas = []
        consulta = """SELECT s.*,r.estado AS respuesta_estado,r.motivo AS respuesta_motivo
                    FROM solicitudes_cliente s LEFT JOIN resoluciones_cliente r
                    ON s.pedido_id=r.pedido_id AND s.referencia=r.referencia"""
        for x in db.execute(
            consulta
            + condicion
            + " ORDER BY s.registrado_en DESC,s.pedido_id DESC,s.referencia LIMIT ? OFFSET ?",
            [*valores, limite, (pagina - 1) * limite],
        ):
            fila = dict(x)
            estado_res = fila.pop("respuesta_estado")
            motivo = fila.pop("respuesta_motivo")
            fila["resolucion"] = (
                {"estado": estado_res, "motivo": motivo} if estado_res else None
            )
            filas.append(fila)
        return {
            "solicitudes": filas,
            "total": db.execute(
                "SELECT COUNT(*) FROM solicitudes_cliente s" + condicion, valores
            ).fetchone()[0],
            "pagina": pagina,
            "limite": limite,
        }


@router.get("/solicitudes-clientes/{id}/{referencia}")
def detalle_solicitud(id: Pos, referencia: Ref, actor: str = Depends(autenticar)):
    if actor.rol == "proveedor":
        raise HTTPException(403, "El proveedor no accede a solicitudes de clientes")
    with closing(repositorio_sqlite.conectar_db()) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        solicitud = db.execute(
            "SELECT * FROM solicitudes_cliente WHERE pedido_id=? AND referencia=?",
            (id, referencia),
        ).fetchone()
        if solicitud is None or (
            actor.rol == "cliente" and solicitud["usuario"] != str(actor)
        ):
            raise HTTPException(404, "Solicitud no encontrada")
        if actor.rol == "cliente":
            resolucion = db.execute(
                "SELECT estado,motivo FROM resoluciones_cliente WHERE pedido_id=? AND referencia=?",
                (id, referencia),
            ).fetchone()
            return {
                "solicitud": dict(solicitud),
                "resolucion": dict(resolucion) if resolucion else None,
            }
        from gestiones_cliente import contexto

        return contexto(db, dict(solicitud), actor.rol)


class Resolucion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado: Literal["atendida", "rechazada"]
    motivo: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


@router.put("/solicitudes-clientes/{id}/{referencia}/resolucion")
def resolver(
    id: Pos, referencia: Ref, datos: Resolucion, actor: str = Depends(autenticar)
):
    if actor.rol not in ("administrador", "empleado"):
        raise HTTPException(403, "Se requiere personal del negocio")
    with closing(repositorio_sqlite.conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        anterior = db.execute(
            "SELECT * FROM solicitudes_cliente WHERE pedido_id=? AND referencia=?",
            (id, referencia),
        ).fetchone()
        if not anterior:
            raise HTTPException(404, "Solicitud no encontrada")
        r = db.execute(
            "SELECT * FROM resoluciones_cliente WHERE pedido_id=? AND referencia=?",
            (id, referencia),
        ).fetchone()
        if r:
            if (r["estado"], r["motivo"]) != (datos.estado, datos.motivo):
                raise HTTPException(409, "La solicitud ya tiene otra resolución")
            return dict(r)
        db.execute(
            "INSERT INTO resoluciones_cliente(pedido_id,referencia,estado,motivo,usuario) VALUES (?,?,?,?,?)",
            (id, referencia, datos.estado, datos.motivo, str(actor)),
        )
        db.execute(
            "UPDATE solicitudes_cliente SET estado=? WHERE pedido_id=? AND referencia=?",
            (datos.estado, id, referencia),
        )
        auditar(
            db,
            "venta",
            id,
            "solicitud_cliente_resuelta",
            {"referencia": referencia, "estado": datos.estado},
        )
        return dict(
            db.execute(
                "SELECT * FROM resoluciones_cliente WHERE pedido_id=? AND referencia=?",
                (id, referencia),
            ).fetchone()
        )


class Aviso(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado: Literal["confirmado", "despachado", "sin_disponibilidad"]
    nota: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


def exigir_proveedor(actor):
    if actor.rol != "proveedor":
        raise HTTPException(403, "Se requiere una cuenta de proveedor")


@router.get("/mi-proveedor/pedidos")
def mis_pedidos_proveedor(
    filtro: Literal["abiertos", "todos"] = "abiertos",
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 10,
    actor: str = Depends(autenticar),
):
    exigir_proveedor(actor)
    from pedidos_proveedor import listar

    with closing(repositorio_sqlite.conectar_db()) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        return listar(db, actor.proveedor, filtro, pagina, limite)


@router.get("/mi-proveedor/pedidos/{id}")
def mi_pedido_proveedor(id: Pos, actor: str = Depends(autenticar)):
    exigir_proveedor(actor)
    from pedidos_proveedor import propio, acciones_aviso, avisos

    with closing(repositorio_sqlite.conectar_db()) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        pedido = propio(db, id, actor.proveedor)
        ultimo = avisos(db, id, actor.proveedor, 1, 1)["avisos"]
        from reposicion_simulada import compra_db

        sim = compra_db(db, id)
        return {
            "pedido": pedido,
            "acciones_aviso": [] if sim else acciones_aviso(pedido),
            "ultimo_aviso": ultimo[0] if ultimo else None,
            "simulacion": sim,
        }


@router.get("/mi-proveedor/pedidos/{id}/avisos")
def mis_avisos_proveedor(
    id: Pos,
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 10,
    actor: str = Depends(autenticar),
):
    exigir_proveedor(actor)
    from pedidos_proveedor import avisos

    with closing(repositorio_sqlite.conectar_db()) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        return avisos(db, id, actor.proveedor, pagina, limite)


@router.put("/mi-proveedor/pedidos/{id}/avisos/{referencia}")
def aviso(id: Pos, referencia: Ref, datos: Aviso, actor: str = Depends(autenticar)):
    if actor.rol != "proveedor":
        raise HTTPException(403, "Solo el proveedor asociado puede emitir este aviso")
    with closing(repositorio_sqlite.conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        from pedidos_proveedor import propio, acciones_aviso

        pedido = propio(db, id, actor.proveedor)
        from reposicion_simulada import compra_db

        if compra_db(db, id):
            raise HTTPException(
                409, "Este pedido usa avisos automáticos del proveedor simulado."
            )
        anterior = db.execute(
            "SELECT * FROM avisos_proveedor WHERE pedido_id=? AND referencia=?",
            (id, referencia),
        ).fetchone()
        if anterior and (anterior["estado"], anterior["nota"]) != (
            datos.estado,
            datos.nota,
        ):
            raise HTTPException(409, "La referencia ya corresponde a otro aviso")
        if anterior is None and datos.estado not in acciones_aviso(pedido):
            raise HTTPException(
                409,
                "El pedido ya está cerrado. Podés consultar sus avisos anteriores, pero no informar uno nuevo.",
            )
        db.execute(
            "INSERT OR IGNORE INTO avisos_proveedor(pedido_id,referencia,proveedor,usuario,estado,nota) VALUES (?,?,?,?,?,?)",
            (id, referencia, actor.proveedor, str(actor), datos.estado, datos.nota),
        )
        if anterior is None:
            auditar(
                db,
                "pedido_proveedor",
                id,
                "aviso_proveedor_recibido",
                {"referencia": referencia, "estado": datos.estado},
            )
        return {
            "aviso": dict(
                db.execute(
                    "SELECT * FROM avisos_proveedor WHERE pedido_id=? AND referencia=?",
                    (id, referencia),
                ).fetchone()
            ),
            "mensaje": "Aviso registrado. El inventario solo aumenta al confirmar la recepción física.",
        }


@router.get("/pedidos/{id}/avisos-proveedor")
def ver_avisos(id: Pos, actor: str = Depends(autenticar)):
    if actor.rol == "cliente":
        raise HTTPException(403, "Esta consulta corresponde a compras del negocio")
    with closing(repositorio_sqlite.conectar_db()) as db:
        db.row_factory = sqlite3.Row
        pedido = db.execute(
            "SELECT proveedor FROM pedidos_reposicion WHERE id=?", (id,)
        ).fetchone()
        if not pedido or (
            actor.rol == "proveedor" and pedido["proveedor"] != actor.proveedor
        ):
            raise HTTPException(404, "Pedido no encontrado")
        return {
            "avisos": [
                dict(x)
                for x in db.execute(
                    "SELECT * FROM avisos_proveedor WHERE pedido_id=? ORDER BY registrado_en",
                    (id,),
                )
            ]
        }


class OfertaPublicada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    nombre: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
    ]
    marca: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
    ]
    categoria: Literal["tecnologia", "alimento", "libreria"]
    precio: Annotated[str, StringConstraints(pattern=r"^\d{1,12}(\.\d{1,2})?$")]
    stock: int = Field(ge=0, le=1000000, strict=True)


class CatalogoPublicado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    productos: list[OfertaPublicada] = Field(max_length=999)


@router.put("/mi-proveedor/catalogo")
def publicar(datos: CatalogoPublicado, actor: str = Depends(autenticar)):
    if actor.rol != "proveedor":
        raise HTTPException(
            403, "Esta publicación corresponde al proveedor autenticado"
        )
    if len({x.id for x in datos.productos}) != len(datos.productos):
        raise HTTPException(422, "No repitas identificadores de oferta en el catálogo")
    from catalogos import guardar_catalogo

    return guardar_catalogo(
        repositorio_sqlite.conectar_db,
        actor.proveedor,
        {"moneda": "ARS", "productos": [x.model_dump() for x in datos.productos]},
        "publicado",
    )


@router.get("/auditoria/comercial")
def historial_comercial(
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 20,
    entidad: (
        Literal[
            "venta", "caja", "pedido_proveedor", "emergencia", "producto", "proveedor"
        ]
        | None
    ) = None,
    actor_filtro: Annotated[str, Query(max_length=64)] | None = None,
    actor: str = Depends(exigir_administrador),
):
    from auditoria_comercial import listar

    return listar(
        repositorio_sqlite.conectar_db, pagina, limite, entidad, None, actor_filtro
    )


@router.get("/auditoria/comercial/{entidad}/{identificador}")
def historial_operacion(
    entidad: Literal[
        "venta", "caja", "pedido_proveedor", "emergencia", "producto", "proveedor"
    ],
    identificador: Annotated[str, Path(min_length=1, max_length=100)],
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 20,
    actor: str = Depends(autenticar),
):
    if actor.rol not in ("administrador", "empleado"):
        raise HTTPException(
            403, "El historial de responsables corresponde al personal del negocio"
        )
    if actor.rol == "empleado" and entidad not in (
        "venta",
        "caja",
        "pedido_proveedor",
        "emergencia",
    ):
        raise HTTPException(403, "Este historial requiere administración")
    if entidad in ("venta", "pedido_proveedor", "producto"):
        if (
            not identificador.isascii()
            or not identificador.isdecimal()
            or not 0 < int(identificador) <= 2**63 - 1
        ):
            raise HTTPException(
                422, "Ingresá un ID numérico válido para esta operación"
            )
        identificador = str(int(identificador))
    from auditoria_comercial import listar

    return listar(
        repositorio_sqlite.conectar_db, pagina, limite, entidad, identificador
    )
