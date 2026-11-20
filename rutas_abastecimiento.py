"""API route group: abastecimiento."""

from contextlib import closing
from typing import Annotated, Literal
import sqlite3
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from autenticacion import autenticar
from errores import ProductoNoEncontradoError
import repositorio_sqlite
import abastecimiento

router = APIRouter()
Pos = Annotated[int, Path(gt=0, le=2**63 - 1)]


def exigir_personal(actor=Depends(autenticar)):
    if actor.rol not in ("administrador", "empleado"):
        raise HTTPException(403, "Esta consulta corresponde al personal del negocio")
    return actor


def consultar(funcion, *args):
    try:
        with closing(repositorio_sqlite.conectar_db()) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            return funcion(db, *args)
    except ProductoNoEncontradoError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/abastecimiento/pedidos")
def listado(
    filtro: Literal["abiertos", "todos"] = "abiertos",
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 10,
    actor=Depends(exigir_personal),
):
    return consultar(abastecimiento.listar, filtro, pagina, limite)


@router.get("/abastecimiento/pedidos/{id}")
def detalle(id: Pos, actor=Depends(exigir_personal)):
    return consultar(abastecimiento.contexto, id, actor.rol)


@router.get("/abastecimiento/pedidos/{id}/remitos")
def remitos(
    id: Pos,
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 10,
    actor=Depends(exigir_personal),
):
    return consultar(abastecimiento.remitos, id, pagina, limite)


@router.get("/abastecimiento/pedidos/{id}/avisos")
def avisos(
    id: Pos,
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 10,
    actor=Depends(exigir_personal),
):
    from pedidos_proveedor import avisos as listar_avisos

    def obtener(db):
        p = abastecimiento.contexto(db, id, actor.rol)["pedido"]
        return listar_avisos(db, id, p["proveedor"], pagina, limite)

    return consultar(obtener)
