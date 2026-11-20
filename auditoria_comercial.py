"""Transactional audit records with request-scoped actor identity."""

import json
import sqlite3
from contextvars import ContextVar
from contextlib import closing

identidad_actual = ContextVar("identidad_comercial", default=None)
habilitada = ContextVar("auditoria_comercial_habilitada", default=True)


def crear_tablas(db):
    db.execute("""CREATE TABLE IF NOT EXISTS auditoria_comercial (
        id INTEGER PRIMARY KEY, entidad TEXT NOT NULL, entidad_id TEXT NOT NULL,
        accion TEXT NOT NULL, actor TEXT NOT NULL, rol TEXT NOT NULL,
        iniciado_por TEXT, detalle TEXT NOT NULL,
        registrado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS auditoria_por_entidad ON auditoria_comercial(entidad,entidad_id,id)"
    )
    db.execute(
        """CREATE TRIGGER IF NOT EXISTS auditoria_comercial_no_editar BEFORE UPDATE ON auditoria_comercial
        BEGIN SELECT RAISE(ABORT,'El historial comercial no se edita'); END"""
    )
    db.execute(
        """CREATE TRIGGER IF NOT EXISTS auditoria_comercial_no_borrar BEFORE DELETE ON auditoria_comercial
        BEGIN SELECT RAISE(ABORT,'El historial comercial no se borra'); END"""
    )


def registrar(db, entidad, id, accion, detalle=None, responsable=None):
    if not habilitada.get():
        return
    identidad = identidad_actual.get()
    actor = responsable or (str(identidad) if identidad is not None else "sistema")
    rol = "sistema" if responsable or identidad is None else identidad.rol
    db.execute(
        """INSERT INTO auditoria_comercial(entidad,entidad_id,accion,actor,rol,iniciado_por,detalle)
        VALUES (?,?,?,?,?,?,?)""",
        (
            entidad,
            str(id),
            accion,
            actor,
            rol,
            str(identidad) if responsable and identidad is not None else None,
            json.dumps(detalle or {}, ensure_ascii=False, sort_keys=True),
        ),
    )


def listar(conectar_db, pagina, limite, entidad=None, id=None, actor=None):
    filtros = []
    datos = []
    for campo, valor in [
        ("entidad", entidad),
        ("entidad_id", str(id) if id is not None else None),
        ("actor", actor),
    ]:
        if valor is not None:
            filtros.append(campo + "=?")
            datos.append(valor)
    donde = " WHERE " + " AND ".join(filtros) if filtros else ""
    with closing(conectar_db()) as db:
        db.row_factory = sqlite3.Row
        total = db.execute(
            "SELECT COUNT(*) FROM auditoria_comercial" + donde, datos
        ).fetchone()[0]
        filas = []
        for x in db.execute(
            "SELECT * FROM auditoria_comercial"
            + donde
            + " ORDER BY id DESC LIMIT ? OFFSET ?",
            [*datos, limite, (pagina - 1) * limite],
        ):
            fila = dict(x)
            fila["detalle"] = json.loads(fila["detalle"])
            filas.append(fila)
        return {
            "movimientos": filas,
            "total": total,
            "pagina": pagina,
            "limite": limite,
        }
