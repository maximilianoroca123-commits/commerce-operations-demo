"""API route group: reposicion simulada."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from autenticacion import exigir_administrador
from rutas_abastecimiento import exigir_personal
from errores import ProductoNoEncontradoError
from reposicion import ConflictoReposicionError
import reposicion_simulada as servicio
import repositorio_sqlite

router = APIRouter(prefix="/reposicion-simulada")


class Configuracion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    producto_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    activa: bool = Field(strict=True)


class Aporte(BaseModel):
    model_config = ConfigDict(extra="forbid")
    importe_centavos: int = Field(gt=0, le=100000000, strict=True)


def ejecutar(fn, *args):
    try:
        return fn(repositorio_sqlite.conectar_db, *args)
    except ProductoNoEncontradoError as e:
        raise HTTPException(404, str(e)) from e
    except ConflictoReposicionError as e:
        raise HTTPException(409, str(e)) from e


@router.get("")
def consultar(pagina: Annotated[int, Query(ge=1)] = 1, actor=Depends(exigir_personal)):
    return ejecutar(servicio.consultar, pagina)


@router.put("/configuracion")
def configurar(datos: Configuracion, actor=Depends(exigir_administrador)):
    return ejecutar(servicio.configurar, datos.producto_id, datos.activa)


@router.put("/ejemplo")
def preparar(actor=Depends(exigir_administrador)):
    return ejecutar(servicio.preparar_ejemplo)


@router.put("/aportes/{referencia}")
def aportar(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]+$", max_length=64)],
    datos: Aporte,
    actor=Depends(exigir_administrador),
):
    return ejecutar(servicio.aportar, referencia, datos.importe_centavos, actor)


@router.put("/pedidos/{id}/pago-aprobado")
def pagar(
    id: Annotated[int, Path(gt=0, le=2**63 - 1)], actor=Depends(exigir_administrador)
):
    return ejecutar(servicio.pagar, id)
