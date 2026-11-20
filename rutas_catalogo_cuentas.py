# API route group: catalogo cuentas.
from fastapi import APIRouter, Depends
from rutas_abastecimiento import exigir_personal, consultar, Pos
from autenticacion import exigir_administrador
import contexto_catalogo_cuentas as contexto

router = APIRouter()


@router.get("/operaciones/productos/{id}")
def producto(id: Pos, actor=Depends(exigir_personal)):
    return consultar(contexto.producto, id, actor.rol)


@router.get("/usuarios/{nombre}")
def cuenta(nombre: str, actor=Depends(exigir_administrador)):
    return consultar(contexto.cuenta, nombre, actor)
