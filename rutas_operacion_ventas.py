# API route group: operacion ventas.
from fastapi import APIRouter, Depends
from rutas_abastecimiento import exigir_personal, consultar, Pos
import operacion_ventas

router = APIRouter()


@router.get("/operaciones/caja-actual")
def caja_actual(actor=Depends(exigir_personal)):
    return consultar(operacion_ventas.caja_actual, actor.rol)


@router.get("/operaciones/ventas/{id}")
def venta(id: Pos, actor=Depends(exigir_personal)):
    return consultar(operacion_ventas.venta, id, actor.rol)
