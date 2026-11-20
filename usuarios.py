"""Account persistence, password derivation and customer order ownership."""

import json
import hashlib
import secrets
import sqlite3
from contextlib import closing
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from typing import Annotated, Literal

NombreUsuario = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{2,39}$")]
Texto = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]


class PerfilCliente(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: Texto
    apellido: Texto
    correo: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=254
        ),
    ]
    telefono: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None
    ) = None


class AltaUsuario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    usuario: NombreUsuario
    clave: Annotated[str, StringConstraints(min_length=10, max_length=128)] = Field(
        repr=False
    )
    rol: Literal["administrador", "empleado", "cliente", "proveedor"]
    cliente: PerfilCliente | None = None
    proveedor: Literal["demo", "demo-b"] | None = None

    @model_validator(mode="after")
    def coherencia(self):
        if any(ord(c) < 32 or ord(c) > 126 for c in self.clave):
            raise ValueError(
                "La contraseña debe usar letras sin tildes, números y símbolos ASCII para este acceso local"
            )
        if (self.rol == "cliente") != (self.cliente is not None):
            raise ValueError(
                "El rol cliente requiere su ficha; otros roles no deben incluirla"
            )
        if (self.rol == "proveedor") != (self.proveedor is not None):
            raise ValueError(
                "El rol proveedor requiere su proveedor asociado; otros roles no deben incluirlo"
            )
        if self.usuario in ("compras", "consulta"):
            raise ValueError(
                "Ese nombre está reservado para la compatibilidad de la demo"
            )
        return self


class EstadoUsuario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activo: bool = Field(strict=True)


class CambioClave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actual: Annotated[str, StringConstraints(max_length=128)] = Field(repr=False)
    nueva: Annotated[str, StringConstraints(min_length=10, max_length=128)] = Field(
        repr=False
    )

    @model_validator(mode="after")
    def validar_nueva(self):
        if any(ord(c) < 32 or ord(c) > 126 for c in self.nueva):
            raise ValueError(
                "La contraseña debe usar letras sin tildes, números y símbolos ASCII para este acceso local"
            )
        return self


def crear_tablas(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, apellido TEXT NOT NULL,
        correo TEXT NOT NULL, telefono TEXT, correo_verificado INTEGER NOT NULL DEFAULT 0)"""
    )
    db.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        usuario TEXT PRIMARY KEY, clave_hash TEXT NOT NULL,
        rol TEXT NOT NULL CHECK(rol IN ('administrador','empleado','cliente','proveedor')),
        cliente_id INTEGER UNIQUE REFERENCES clientes(id), proveedor TEXT,
        activo INTEGER NOT NULL DEFAULT 1 CHECK(activo IN (0,1)),
        creado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))""")
    columnas = {c[1] for c in db.execute("PRAGMA table_info(usuarios)")}
    if "debe_cambiar_clave" not in columnas:
        db.execute(
            "ALTER TABLE usuarios ADD COLUMN debe_cambiar_clave INTEGER NOT NULL DEFAULT 0 CHECK(debe_cambiar_clave IN (0,1))"
        )
    if "version_credencial" not in columnas:
        db.execute(
            "ALTER TABLE usuarios ADD COLUMN version_credencial INTEGER NOT NULL DEFAULT 0"
        )
    db.execute("""CREATE TABLE IF NOT EXISTS auditoria_cuentas (
        id INTEGER PRIMARY KEY, actor TEXT NOT NULL, afectado TEXT NOT NULL,
        accion TEXT NOT NULL, detalle TEXT NOT NULL,
        registrado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))""")
    db.execute(
        """CREATE TRIGGER IF NOT EXISTS auditoria_cuentas_no_editar BEFORE UPDATE ON auditoria_cuentas
        BEGIN SELECT RAISE(ABORT,'El historial de cuentas no se edita'); END"""
    )
    db.execute(
        """CREATE TRIGGER IF NOT EXISTS auditoria_cuentas_no_borrar BEFORE DELETE ON auditoria_cuentas
        BEGIN SELECT RAISE(ABORT,'El historial de cuentas no se borra'); END"""
    )
    db.execute("""CREATE TABLE IF NOT EXISTS restablecimientos_clave (
        usuario TEXT NOT NULL REFERENCES usuarios(usuario), referencia TEXT NOT NULL,
        clave_hash TEXT NOT NULL, motivo TEXT NOT NULL, actor TEXT NOT NULL,
        PRIMARY KEY(usuario,referencia))""")
    db.execute("""CREATE TABLE IF NOT EXISTS titulares_pedido (
        pedido_id INTEGER PRIMARY KEY REFERENCES pedidos_venta(id),
        cliente_id INTEGER REFERENCES clientes(id), propietario TEXT,
        registrado_por TEXT NOT NULL, contacto_compra TEXT, direccion_entrega TEXT)""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS titulares_por_propietario ON titulares_pedido(propietario,pedido_id)"
    )
    db.execute("""CREATE TABLE IF NOT EXISTS solicitudes_cliente (
        pedido_id INTEGER NOT NULL REFERENCES pedidos_venta(id), referencia TEXT NOT NULL,
        usuario TEXT NOT NULL, tipo TEXT NOT NULL, motivo TEXT NOT NULL,
        estado TEXT NOT NULL DEFAULT 'pendiente_revision',
        registrado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        PRIMARY KEY(pedido_id,referencia))""")
    db.execute("""CREATE TABLE IF NOT EXISTS avisos_proveedor (
        pedido_id INTEGER NOT NULL REFERENCES pedidos_reposicion(id), referencia TEXT NOT NULL,
        proveedor TEXT NOT NULL, usuario TEXT NOT NULL, estado TEXT NOT NULL, nota TEXT NOT NULL,
        registrado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        PRIMARY KEY(pedido_id,referencia))""")

    db.execute(
        """CREATE TABLE IF NOT EXISTS resoluciones_cliente (
        pedido_id INTEGER NOT NULL, referencia TEXT NOT NULL, estado TEXT NOT NULL, motivo TEXT NOT NULL,
        usuario TEXT NOT NULL, PRIMARY KEY(pedido_id,referencia),
        FOREIGN KEY(pedido_id,referencia) REFERENCES solicitudes_cliente(pedido_id,referencia))"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS fuentes_catalogo (
        proveedor TEXT PRIMARY KEY, modo TEXT NOT NULL CHECK(modo IN ('externo','publicado')))"""
    )


# Derive a salted password hash rather than storing a plaintext password.
def hash_clave(clave):
    sal = secrets.token_hex(16)
    derivado = hashlib.scrypt(
        clave.encode(), salt=bytes.fromhex(sal), n=16384, r=8, p=1
    ).hex()
    return f"scrypt${sal}${derivado}"


def verificar_clave(clave, guardada):
    try:
        _, sal, esperada = guardada.split("$")
        actual = hashlib.scrypt(
            clave.encode(), salt=bytes.fromhex(sal), n=16384, r=8, p=1
        ).hex()
        return secrets.compare_digest(actual, esperada)
    except (ValueError, TypeError):
        return False


def consultar_usuario(conectar_db, nombre):
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        r = db.execute("SELECT * FROM usuarios WHERE usuario=?", (nombre,)).fetchone()
        return dict(r) if r else None


def crear_usuario(conectar_db, datos, actor="compras"):
    clave_hash = hash_clave(datos.clave)
    with closing(conectar_db()) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        if db.execute(
            "SELECT 1 FROM usuarios WHERE usuario=?", (datos.usuario,)
        ).fetchone():
            raise HTTPException(409, "El nombre de usuario ya está registrado")
        cliente_id = None
        if datos.cliente:
            c = datos.cliente
            cliente_id = db.execute(
                "INSERT INTO clientes(nombre,apellido,correo,telefono) VALUES (?,?,?,?)",
                (c.nombre, c.apellido, c.correo.casefold(), c.telefono),
            ).lastrowid
        db.execute(
            "INSERT INTO usuarios(usuario,clave_hash,rol,cliente_id,proveedor) VALUES (?,?,?,?,?)",
            (datos.usuario, clave_hash, datos.rol, cliente_id, datos.proveedor),
        )
        registrar_cuenta(db, actor, datos.usuario, "cuenta_creada", {"rol": datos.rol})
        return dict(
            db.execute(
                "SELECT usuario,rol,cliente_id,proveedor,activo FROM usuarios WHERE usuario=?",
                (datos.usuario,),
            ).fetchone()
        )


# A valid customer identity does not grant access to another customer order.
def comprobar_titular(db, origen, referencia, actor):
    if actor is None or actor.rol != "cliente":
        return
    r = db.execute(
        """SELECT t.propietario FROM pedidos_venta p LEFT JOIN titulares_pedido t ON t.pedido_id=p.id
        WHERE p.origen=? AND p.referencia=?""",
        (origen, referencia),
    ).fetchone()
    tabla = "cobros_demo" if origen == "qr" else "ventas"
    existe = db.execute(
        f"SELECT 1 FROM {tabla} WHERE referencia=?", (referencia,)
    ).fetchone()
    if existe and (r is None or r[0] != str(actor)):
        raise HTTPException(404, "Operación no encontrada")


def vincular_actor(db, pedido_id, actor, direccion=None):
    if actor is None:
        return
    propietario = str(actor) if actor.rol == "cliente" else None
    perfil = (
        db.execute(
            "SELECT nombre,apellido,correo,telefono,correo_verificado FROM clientes WHERE id=?",
            (actor.cliente_id,),
        ).fetchone()
        if actor.cliente_id
        else None
    )
    contacto = json.dumps(dict(perfil), ensure_ascii=False) if perfil else None
    db.execute(
        """INSERT OR IGNORE INTO titulares_pedido(pedido_id,cliente_id,propietario,registrado_por,contacto_compra,direccion_entrega)
        VALUES (?,?,?,?,?,?)""",
        (pedido_id, actor.cliente_id, propietario, str(actor), contacto, direccion),
    )


def exigir_titular(conectar_db, pedido_id, actor):
    if actor.rol in ("administrador", "empleado"):
        return
    if actor.rol != "cliente":
        raise HTTPException(403, "Tu cuenta no puede consultar ventas del negocio")
    with closing(conectar_db()) as db:
        r = db.execute(
            "SELECT propietario FROM titulares_pedido WHERE pedido_id=?", (pedido_id,)
        ).fetchone()
        if r is None or r[0] != str(actor):
            raise HTTPException(404, "Pedido de venta no encontrado")


def registrar_cuenta(db, actor, afectado, accion, detalle):
    """Record application-defined details only, never passwords or raw request bodies."""
    db.execute(
        "INSERT INTO auditoria_cuentas(actor,afectado,accion,detalle) VALUES (?,?,?,?)",
        (
            str(actor),
            afectado,
            accion,
            json.dumps(detalle, ensure_ascii=False, sort_keys=True),
        ),
    )


class RestablecerClave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temporal: Annotated[str, StringConstraints(min_length=10, max_length=128)] = Field(
        repr=False
    )
    motivo: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]

    @model_validator(mode="after")
    def formato(self):
        if any(ord(c) < 32 or ord(c) > 126 for c in self.temporal):
            raise ValueError(
                "La contraseña temporal debe usar letras sin tildes, números y símbolos ASCII"
            )
        return self
