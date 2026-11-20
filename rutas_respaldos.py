"""API route group: respaldos."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Path
from autenticacion import exigir_administrador
import repositorio_sqlite
import respaldos
import sqlite3

router = APIRouter()
Nombre = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]+\.zip$", max_length=120)]


def ejecutar(funcion, *args, **kwargs):
    try:
        return funcion(repositorio_sqlite.RUTA_DB_API, *args, **kwargs)
    except (respaldos.ErrorRespaldo, OSError, sqlite3.Error) as e:
        raise HTTPException(409, str(e)) from e


@router.post("/respaldos", status_code=201)
def crear(actor=Depends(exigir_administrador)):
    return ejecutar(respaldos.crear, actor=actor)


@router.get("/respaldos")
def listar(actor=Depends(exigir_administrador)):
    return {"respaldos": ejecutar(respaldos.listar)}


@router.post("/respaldos/{nombre}/verificacion")
def verificar(nombre: Nombre, actor=Depends(exigir_administrador)):
    return ejecutar(respaldos.verificar, nombre)
