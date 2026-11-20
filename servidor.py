# HTTP endpoints, dependency-based access control and application lifecycle tasks.


import asyncio
from contextlib import asynccontextmanager
import logging
import sqlite3
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse

from autenticacion import (
    autenticar,
    exigir_compras,
    exigir_consulta,
    exigir_administrador,
    OPCIONES_EMPLEADO,
)
from catalogos import (
    PROVEEDORES,
    descargar_catalogo,
    guardar_catalogo,
    listar_ofertas,
    vincular_oferta,
)
from config import CATEGORIAS_VALIDAS
from errores import ProductoDuplicadoError, ProductoNoEncontradoError, ErrorPersistencia
from modelos import (
    ProductoCrear,
    ProductoActualizar,
    VinculoOferta,
    RecepcionPedido,
    EntregaPedido,
    CorreccionEntrega,
    VentaCrear,
    CarritoCrear,
    PagoSimulado,
    EventoPagoDemo,
    ConexionPagoDemo,
    EntregaVenta,
)
from paginacion import calcular_cantidad_paginas
from ventas import ConflictoVentaError, registrar_venta
from reposicion import (
    ConflictoReposicionError,
    cancelar_pedido,
    cerrar_incompleto,
    corregir_entrega,
    listar_correcciones,
    consultar_pedido,
    generar_reposicion,
    listar_pedidos,
    recibir_pedido,
    registrar_entrega,
)
from repositorio_sqlite import (
    conectar_db,
    obtener_producto_por_id,
    obtener_producto_por_nombre,
    crear_producto,
    guardar_producto_actualizado,
    eliminar_producto as eliminar_producto_sqlite,
    contar_productos,
    obtener_productos_paginados,
)

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def ciclo_operaciones(app):
    from caja import recuperar_cobros
    import reposicion_simulada

    reposicion_simulada.instalar(conectar_db)

    async def verificar_pendientes():
        while True:
            try:
                await asyncio.to_thread(recuperar_cobros, conectar_db)
            except (sqlite3.Error, ErrorPersistencia):
                logger.exception("No se pudieron recuperar los cobros pendientes")
            await asyncio.sleep(1)

    async def verificar_reposicion():
        from reposicion_automatica import ciclo_programado

        while True:
            try:
                await asyncio.to_thread(ciclo_programado, conectar_db)
            except (sqlite3.Error, ErrorPersistencia):
                logger.exception("No se pudo ejecutar la reposición automática")
            await asyncio.sleep(5)

    async def verificar_simulacion():
        while True:
            try:
                await asyncio.to_thread(reposicion_simulada.ciclo, conectar_db)
            except (sqlite3.Error, ErrorPersistencia):
                logger.exception("No se pudo avanzar la reposición simulada")
            await asyncio.sleep(1)

    tarea_simulacion = asyncio.create_task(verificar_simulacion())
    tarea_reposicion = asyncio.create_task(verificar_reposicion())
    tarea = asyncio.create_task(verificar_pendientes())
    try:
        yield
    finally:
        tarea.cancel()
        tarea_reposicion.cancel()
        tarea_simulacion.cancel()
        for pendiente in (tarea, tarea_reposicion, tarea_simulacion):
            try:
                await pendiente
            except asyncio.CancelledError:
                pass


@asynccontextmanager
async def ciclo_pagos(app):
    import repositorio_sqlite
    from respaldos import bloqueo, automatico_si_corresponde, ErrorRespaldo

    detener = asyncio.Event()

    async def copias_periodicas():
        while not detener.is_set():
            try:
                await asyncio.to_thread(
                    automatico_si_corresponde, repositorio_sqlite.RUTA_DB_API
                )
            except (ErrorRespaldo, OSError, sqlite3.Error):
                logger.exception(
                    "No se pudo completar el respaldo automático; se reintentará"
                )
            try:
                await asyncio.wait_for(detener.wait(), timeout=300)
            except asyncio.TimeoutError:
                pass

    with bloqueo(repositorio_sqlite.RUTA_DB_API):
        async with ciclo_operaciones(app):
            tarea_copias = asyncio.create_task(copias_periodicas())
            try:
                yield
            finally:
                detener.set()

                await tarea_copias


app = FastAPI(lifespan=ciclo_pagos)


@app.exception_handler(ErrorPersistencia)
async def manejar_error_persistencia(
    request: Request,
    error: ErrorPersistencia,
):

    logger.error(
        "Fallo de persistencia en %s %s",
        request.method,
        request.url.path,
        exc_info=(type(error), error, error.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "No se pudo completar la operación"},
    )


from fastapi.exceptions import RequestValidationError


@app.exception_handler(RequestValidationError)
async def validar_sin_exponer_datos(request: Request, error: RequestValidationError):

    errores = []
    for e in error.errors():
        contexto = {
            k: v
            for k, v in (e.get("ctx") or {}).items()
            if k in ("gt", "ge", "lt", "le", "min_length", "max_length", "expected")
            and isinstance(v, (str, int, float))
        }
        errores.append(
            {"loc": e["loc"], "type": e["type"], "msg": e["msg"], "ctx": contexto}
        )
    return JSONResponse(status_code=422, content={"detail": errores})


@app.middleware("http")
async def evitar_cache_privada(request: Request, call_next):
    respuesta = await call_next(request)
    if request.headers.get("authorization"):
        respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@app.get("/sesion")
def consultar_sesion(usuario: str = Depends(autenticar)):
    opciones = (
        [str(x) for x in range(1, 44)]
        if usuario.rol == "administrador"
        else (
            sorted(
                OPCIONES_EMPLEADO | {"34", "35", "36", "37", "38", "41", "43"}, key=int
            )
            if usuario.rol == "empleado"
            else []
        )
    )
    if str(usuario) == "consulta":
        opciones = ["3"]
    return {
        "usuario": str(usuario),
        "rol": str(usuario) if usuario.legado else usuario.rol,
        "rol_efectivo": usuario.rol,
        "cliente_id": usuario.cliente_id,
        "proveedor": usuario.proveedor,
        "debe_cambiar_clave": usuario.debe_cambiar_clave,
        "opciones_operativas": [] if usuario.debe_cambiar_clave else opciones,
        "cuenta_compatibilidad": usuario.legado,
    }


@app.get("/productos", dependencies=[Depends(autenticar)])
def listar_productos(
    categoria: str | None = None,
    precio_min: int | None = None,
    precio_max: int | None = None,
    pagina: int = 1,
    limite: int = 10,
    texto: str | None = None,
):

    if pagina < 1:
        raise HTTPException(
            status_code=422,
            detail="pagina debe ser mayor o igual a 1",
        )

    if not 1 <= limite <= 10:
        raise HTTPException(
            status_code=422,
            detail="limite debe estar entre 1 y 10",
        )

    if categoria is not None and categoria not in CATEGORIAS_VALIDAS:
        raise HTTPException(
            status_code=422,
            detail="categoria invalida",
        )

    if precio_min is not None and precio_min < 0:
        raise HTTPException(
            status_code=422,
            detail="precio minimo debe ser igual o mayor a 0",
        )

    if precio_max is not None and precio_max < 0:
        raise HTTPException(
            status_code=422,
            detail="precio maximo debe ser igual o mayor a 0",
        )

    if precio_min is not None and precio_max is not None and precio_min > precio_max:
        raise HTTPException(
            status_code=422,
            detail="precio_min no puede ser mayor que precio_max",
        )

    texto = (texto.strip() or None) if texto is not None else None

    productos_pagina = obtener_productos_paginados(
        pagina, limite, categoria, precio_min, precio_max, texto
    )

    total = contar_productos(categoria, precio_min, precio_max, texto)
    cantidad_de_paginas = calcular_cantidad_paginas(total, limite)
    return {
        "productos": productos_pagina,
        "total": total,
        "cantidad_paginas": cantidad_de_paginas,
        "pagina": pagina,
        "limite": limite,
    }


@app.get("/productos/{id}", dependencies=[Depends(autenticar)])
def consultar_producto(id: int):
    producto_existente = obtener_producto_por_id(id)
    if producto_existente is None:
        raise HTTPException(
            status_code=404,
            detail="Producto no encontrado",
        )
    return producto_existente


@app.post("/productos", status_code=201, dependencies=[Depends(exigir_compras)])
def recibir_producto(producto: ProductoCrear):
    producto_existente = obtener_producto_por_nombre(producto.nombre)
    if producto_existente is not None:
        raise HTTPException(
            status_code=409,
            detail="El producto ya existe",
        )

    try:
        nuevo_producto = crear_producto(
            producto.nombre,
            producto.categoria,
            producto.precio,
            producto.stock,
            producto.marca,
        )
        return nuevo_producto
    except ProductoDuplicadoError:
        raise HTTPException(
            status_code=409,
            detail="El producto ya existe",
        )


@app.patch("/productos/{id}", dependencies=[Depends(exigir_compras)])
def actualizar_producto(id: int, producto: ProductoActualizar):

    cambios = producto.model_dump(exclude_unset=True)

    if not cambios:
        raise HTTPException(
            status_code=422,
            detail="No se enviaron campos a actualizar",
        )

    try:
        return guardar_producto_actualizado(id, cambios)
    except ConflictoVentaError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ProductoNoEncontradoError:
        raise HTTPException(
            status_code=404,
            detail="Producto no encontrado",
        )


@app.delete("/productos/{id}", status_code=204, dependencies=[Depends(exigir_compras)])
def eliminar_producto(id: int):
    producto_existente = obtener_producto_por_id(id)
    if producto_existente is None:
        raise HTTPException(
            status_code=404,
            detail="Producto no encontrado",
        )
    try:
        eliminar_producto_sqlite(id)
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409, detail="El producto tiene historial de pedidos o ventas"
        ) from error
    except ProductoNoEncontradoError:
        raise HTTPException(
            status_code=404,
            detail="Producto no encontrado",
        )


@app.post("/proveedores/{proveedor}/importar", dependencies=[Depends(exigir_compras)])
def importar_catalogo(proveedor: str):
    url = PROVEEDORES.get(proveedor)
    if url is None:
        raise HTTPException(status_code=404, detail="Proveedor desconocido")
    try:
        catalogo = descargar_catalogo(url)
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=502, detail="No se pudo leer el catálogo"
        ) from error
    try:
        return guardar_catalogo(conectar_db, proveedor, catalogo)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudieron guardar las ofertas") from error


@app.get("/proveedores/{proveedor}/ofertas", dependencies=[Depends(exigir_compras)])
def consultar_ofertas(proveedor: str):
    if proveedor not in PROVEEDORES:
        raise HTTPException(status_code=404, detail="Proveedor desconocido")
    try:
        return listar_ofertas(conectar_db, proveedor)
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudieron consultar las ofertas") from error


@app.put(
    "/proveedores/{proveedor}/ofertas/{id_externo}/vinculo",
    dependencies=[Depends(exigir_compras)],
)
def confirmar_vinculo(proveedor: str, id_externo: str, vinculo: VinculoOferta):
    if proveedor not in PROVEEDORES:
        raise HTTPException(status_code=404, detail="Proveedor desconocido")
    try:
        return vincular_oferta(conectar_db, proveedor, id_externo, vinculo.producto_id)
    except ProductoNoEncontradoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudo guardar el vínculo") from error


@app.post("/productos/{id}/reposicion", dependencies=[Depends(exigir_compras)])
def evaluar_reposicion(id: int):
    try:
        return generar_reposicion(conectar_db, id)
    except ProductoNoEncontradoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudo evaluar la reposición") from error


@app.get("/pedidos", dependencies=[Depends(exigir_compras)])
def obtener_pedidos(
    usuario: str = Depends(exigir_compras),
    estado: (
        Literal["pendiente", "parcial", "recibido", "cancelado", "cerrado_incompleto"]
        | None
    ) = None,
    producto_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
):
    try:
        pedidos = listar_pedidos(conectar_db, estado=estado, producto_id=producto_id)
        return (
            [p for p in pedidos if p["proveedor"] == usuario.proveedor]
            if usuario.rol == "proveedor"
            else pedidos
        )
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudieron consultar los pedidos") from error


@app.get("/pedidos/{id}", dependencies=[Depends(exigir_compras)])
def obtener_pedido(
    id: Annotated[int, Path(gt=0, le=2**63 - 1)], usuario: str = Depends(exigir_compras)
):
    try:
        pedido = consultar_pedido(conectar_db, id)
        if usuario.rol == "proveedor" and pedido["proveedor"] != usuario.proveedor:
            raise HTTPException(404, "Pedido no encontrado")
        return pedido
    except ProductoNoEncontradoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudo consultar el pedido") from error


@app.put("/pedidos/{id}/recepcion", dependencies=[Depends(exigir_compras)])
def confirmar_recepcion(id: int, recepcion: RecepcionPedido):
    try:
        return recibir_pedido(conectar_db, id, recepcion.costo_pagado_centavos)
    except ProductoNoEncontradoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConflictoReposicionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudo registrar la recepción") from error


@app.put("/pedidos/{id}/cancelacion", dependencies=[Depends(exigir_compras)])
def confirmar_cancelacion(id: Annotated[int, Path(gt=0, le=2**63 - 1)]):
    try:
        return cancelar_pedido(conectar_db, id)
    except ProductoNoEncontradoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConflictoReposicionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudo cancelar el pedido") from error


@app.put(
    "/pedidos/{id}/recepciones/{referencia}", dependencies=[Depends(exigir_compras)]
)
def confirmar_entrega(
    id: Annotated[int, Path(gt=0, le=2**63 - 1)],
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]+$", max_length=64)],
    entrega: EntregaPedido,
):
    try:
        return registrar_entrega(
            conectar_db, id, referencia, entrega.cantidad, entrega.costo_pagado_centavos
        )
    except ProductoNoEncontradoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConflictoReposicionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudo registrar la entrega") from error


@app.put("/pedidos/{id}/cierre-incompleto", dependencies=[Depends(exigir_compras)])
def confirmar_cierre_incompleto(id: Annotated[int, Path(gt=0, le=2**63 - 1)]):
    try:
        return cerrar_incompleto(conectar_db, id)
    except ProductoNoEncontradoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConflictoReposicionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudo cerrar el pedido") from error


@app.put(
    "/pedidos/{id}/recepciones/{referencia}/correcciones/{codigo}",
    dependencies=[Depends(exigir_compras)],
)
def confirmar_correccion(
    id: Annotated[int, Path(gt=0, le=2**63 - 1)],
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]+$", max_length=64)],
    codigo: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]+$", max_length=64)],
    correccion: CorreccionEntrega,
):
    try:
        return corregir_entrega(
            conectar_db,
            id,
            referencia,
            codigo,
            correccion.cantidad,
            correccion.costo_pagado_centavos,
            correccion.motivo,
        )
    except ProductoNoEncontradoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConflictoReposicionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudo corregir el remito") from error


@app.get(
    "/pedidos/{id}/recepciones/{referencia}/correcciones",
    dependencies=[Depends(exigir_compras)],
)
def consultar_correcciones(
    id: Annotated[int, Path(gt=0, le=2**63 - 1)],
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]+$", max_length=64)],
):
    try:
        return listar_correcciones(conectar_db, id, referencia)
    except ProductoNoEncontradoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudieron consultar las correcciones") from error


@app.put("/ventas/{referencia}", dependencies=[Depends(exigir_consulta)])
def confirmar_venta(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]+$", max_length=64)],
    venta: VentaCrear,
    usuario: str = Depends(exigir_consulta),
):
    try:
        return registrar_venta(
            conectar_db, referencia, venta.producto_id, venta.cantidad, usuario
        )
    except ProductoNoEncontradoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConflictoVentaError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudo registrar la venta") from error


def ejecutar_operacion_caja(operacion, *argumentos):
    try:
        return operacion(conectar_db, *argumentos)
    except ProductoNoEncontradoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConflictoVentaError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudo procesar el cobro") from error


@app.put("/cobros-demo/{referencia}", dependencies=[Depends(exigir_consulta)])
def preparar_cobro(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    carrito: CarritoCrear,
    usuario: str = Depends(exigir_consulta),
):
    from caja import crear_cobro

    if not usuario.legado and usuario.rol == "cliente" and carrito.canal != "online":
        raise HTTPException(
            422, "El cliente debe seleccionar canal online y retiro o envío"
        )
    if (
        not usuario.legado
        and carrito.modalidad == "envio"
        and not carrito.direccion_entrega
    ):
        raise HTTPException(422, "Ingresá la dirección donde debe entregarse el pedido")
    if carrito.modalidad != "envio" and carrito.direccion_entrega:
        raise HTTPException(
            422, "Solo los pedidos con envío llevan dirección de entrega"
        )
    return ejecutar_operacion_caja(
        crear_cobro,
        referencia,
        [producto.model_dump() for producto in carrito.productos],
        carrito.canal,
        carrito.modalidad,
        usuario,
        carrito.direccion_entrega,
    )


@app.get("/cobros-demo/{referencia}", dependencies=[Depends(exigir_consulta)])
def ver_cobro(referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]):
    from caja import consultar_cobro

    return ejecutar_operacion_caja(consultar_cobro, referencia)


@app.put("/cobros-demo/{referencia}/pago", dependencies=[Depends(exigir_consulta)])
def simular_resultado_pago(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    pago: PagoSimulado,
):
    from caja import confirmar_pago

    return ejecutar_operacion_caja(confirmar_pago, referencia, pago.estado)


@app.put(
    "/cobros-demo/{referencia}/eventos/{evento}",
    dependencies=[Depends(exigir_consulta)],
)
def evento_pago_demo(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    evento: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    pago: EventoPagoDemo,
):
    from caja import emitir_evento

    return ejecutar_operacion_caja(emitir_evento, referencia, evento, pago.estado)


@app.put("/cobros-demo/{referencia}/conexion", dependencies=[Depends(exigir_consulta)])
def conexion_pago_demo(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    conexion: ConexionPagoDemo,
):
    from caja import conectar_proveedor

    return ejecutar_operacion_caja(conectar_proveedor, referencia, conexion.disponible)


@app.put(
    "/cobros-demo/{referencia}/devolucion", dependencies=[Depends(exigir_consulta)]
)
def devolver_pago_demo(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
):
    from caja import reembolsar

    return ejecutar_operacion_caja(reembolsar, referencia)


@app.post("/pagos-demo/conciliar", dependencies=[Depends(exigir_compras)])
def conciliar_pagos_demo():
    from caja import recuperar_cobros

    return ejecutar_operacion_caja(recuperar_cobros)


@app.get("/productos/{id}/disponibilidad", dependencies=[Depends(autenticar)])
def disponibilidad_producto(id: Annotated[int, Path(gt=0, le=2**63 - 1)]):
    from contextlib import closing
    from inventario_reservas import reservado
    from pedidos_venta import pendiente_entrega

    with closing(conectar_db()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        producto = db.execute(
            "SELECT stock FROM productos WHERE id = ?", (id,)
        ).fetchone()
        if producto is None:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        cantidad = reservado(db, id)
        vendidas = pendiente_entrega(db, id)
        return {
            "producto_id": id,
            "stock": producto[0],
            "reservado": cantidad,
            "disponible": producto[0] - cantidad,
            "vendido_pendiente_entrega": vendidas,
        }


def ejecutar_pedido_venta(operacion, *argumentos):
    from pedidos_venta import ConflictoEntregaError

    try:
        return operacion(conectar_db, *argumentos)
    except ProductoNoEncontradoError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConflictoEntregaError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except sqlite3.Error as error:
        raise ErrorPersistencia("No se pudo procesar el pedido de venta") from error


@app.get("/pedidos-venta", dependencies=[Depends(autenticar)])
def listar_pedidos_venta(
    usuario: str = Depends(autenticar),
    pendientes_entrega: bool = False,
    canal: Literal["presencial", "online"] | None = None,
    estado_entrega: (
        Literal[
            "pendiente_pago",
            "pendiente",
            "preparando",
            "listo",
            "enviado",
            "entregado",
            "cancelado",
            "revision",
        ]
        | None
    ) = None,
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 20,
):
    from pedidos_venta import listar

    if usuario.rol == "proveedor":
        raise HTTPException(403, "El proveedor no puede consultar ventas a clientes")
    return ejecutar_pedido_venta(
        listar,
        canal,
        estado_entrega,
        pagina,
        limite,
        None,
        str(usuario) if usuario.rol == "cliente" else None,
        pendientes_entrega,
    )


@app.get("/pedidos-venta/{id}", dependencies=[Depends(autenticar)])
def consultar_pedido_venta(
    id: Annotated[int, Path(gt=0, le=2**63 - 1)], usuario: str = Depends(autenticar)
):
    from usuarios import exigir_titular

    exigir_titular(conectar_db, id, usuario)
    from pedidos_venta import consultar

    return ejecutar_pedido_venta(consultar, id)


@app.put("/pedidos-venta/{id}/entrega", dependencies=[Depends(exigir_compras)])
def actualizar_entrega_venta(
    id: Annotated[int, Path(gt=0, le=2**63 - 1)],
    entrega: EntregaVenta,
):
    from pedidos_venta import cambiar_entrega

    return ejecutar_pedido_venta(cambiar_entrega, id, entrega.estado)


@app.get("/ventas", dependencies=[Depends(exigir_compras)])
def consultar_ventas_cobradas(
    canal: Literal["presencial", "online"] | None = None,
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 20,
):
    from pedidos_venta import listar

    return ejecutar_pedido_venta(listar, canal, None, pagina, limite, "aprobado")


@app.get("/pedidos-venta/{id}/ticket", dependencies=[Depends(autenticar)])
def consultar_ticket_venta(
    id: Annotated[int, Path(gt=0, le=2**63 - 1)],
    usuario: str = Depends(autenticar),
    idioma: Literal["es", "en"] = "es",
):
    from usuarios import exigir_titular

    exigir_titular(conectar_db, id, usuario)
    from fastapi.responses import HTMLResponse
    from tickets import generar_ticket

    contenido = ejecutar_pedido_venta(generar_ticket, id, idioma)
    return HTMLResponse(contenido, headers={"Cache-Control": "no-store"})


from modelos import DevolucionVenta, MotivoCancelacion, ReintegroVenta


@app.put(
    "/pedidos-venta/{id}/devoluciones/{referencia}",
    dependencies=[Depends(exigir_compras)],
)
def registrar_devolucion_venta(
    id: Annotated[int, Path(gt=0, le=2**63 - 1)],
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    datos: DevolucionVenta,
):
    from devoluciones import registrar

    return ejecutar_pedido_venta(registrar, id, referencia, datos.model_dump())


@app.put(
    "/pedidos-venta/{id}/cancelaciones/{referencia}",
    dependencies=[Depends(exigir_compras)],
)
def cancelar_venta_pagada(
    id: Annotated[int, Path(gt=0, le=2**63 - 1)],
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    datos: MotivoCancelacion,
):
    from devoluciones import registrar

    return ejecutar_pedido_venta(
        registrar, id, referencia, datos.model_dump(), "cancelacion"
    )


@app.put(
    "/pedidos-venta/{id}/devoluciones/{referencia}/reintegro",
    dependencies=[Depends(exigir_compras)],
)
def simular_reintegro_venta(
    id: Annotated[int, Path(gt=0, le=2**63 - 1)],
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    datos: ReintegroVenta,
):
    from devoluciones import reintegrar

    return ejecutar_pedido_venta(
        reintegrar, id, referencia, datos.estado, datos.caja_esperada
    )


@app.get("/inventario/movimientos", dependencies=[Depends(exigir_compras)])
def consultar_movimientos_inventario(
    producto_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
    tipo: (
        Literal[
            "saldo_inicial",
            "alta",
            "baja",
            "ajuste_manual",
            "venta_directa",
            "venta_qr",
            "venta_efectivo",
            "recepcion",
            "reposicion_emergencia",
            "correccion_remito",
            "devolucion",
            "cancelacion",
        ]
        | None
    ) = None,
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 10,
):
    from movimientos_inventario import listar

    return ejecutar_pedido_venta(listar, producto_id, tipo, pagina, limite)


from modelos import AperturaCaja, CierreCaja, MovimientoEfectivo, VentaEfectivo


@app.put("/cajas/{referencia}/apertura", dependencies=[Depends(exigir_compras)])
def abrir_caja_efectivo(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    datos: AperturaCaja,
):
    from caja_efectivo import abrir

    return ejecutar_pedido_venta(abrir, referencia, datos.fondo_inicial)


@app.get("/cajas", dependencies=[Depends(exigir_compras)])
def listar_cajas_efectivo(
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 10,
):
    from caja_efectivo import listar

    return ejecutar_pedido_venta(listar, pagina, limite)


@app.get("/cajas/{referencia}", dependencies=[Depends(exigir_compras)])
def consultar_caja_efectivo(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
):
    from caja_efectivo import consultar

    return ejecutar_pedido_venta(consultar, referencia)


@app.put("/cajas/{referencia}/cierre", dependencies=[Depends(exigir_compras)])
def cerrar_caja_efectivo(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    datos: CierreCaja,
):
    from caja_efectivo import cerrar

    return ejecutar_pedido_venta(
        cerrar, referencia, datos.contado, datos.saldo_esperado
    )


@app.put(
    "/cajas/{referencia}/movimientos/{operacion}",
    dependencies=[Depends(exigir_compras)],
)
def registrar_movimiento_efectivo(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    operacion: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    datos: MovimientoEfectivo,
):
    from caja_efectivo import movimiento_manual

    return ejecutar_pedido_venta(
        movimiento_manual,
        referencia,
        operacion,
        datos.tipo,
        datos.importe,
        datos.motivo,
    )


@app.put("/ventas-efectivo/{referencia}", dependencies=[Depends(exigir_compras)])
def cobrar_venta_efectivo(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    datos: VentaEfectivo,
    usuario: str = Depends(exigir_compras),
):
    from caja_efectivo import cobrar

    return ejecutar_pedido_venta(
        cobrar, referencia, datos.model_dump(exclude_none=True), usuario
    )


from modelos import ReglaReposicion


@app.put("/productos/{id}/regla-reposicion", dependencies=[Depends(exigir_compras)])
def configurar_reposicion_automatica(
    id: Annotated[int, Path(gt=0, le=2**63 - 1)],
    datos: ReglaReposicion,
):
    from reposicion_automatica import guardar_regla

    return ejecutar_pedido_venta(guardar_regla, id, datos.model_dump())


@app.get("/productos/{id}/regla-reposicion", dependencies=[Depends(exigir_compras)])
def ver_regla_reposicion(id: Annotated[int, Path(gt=0, le=2**63 - 1)]):
    from reposicion_automatica import consultar_regla

    return ejecutar_pedido_venta(consultar_regla, id)


@app.post("/reposicion-automatica/evaluar", dependencies=[Depends(exigir_compras)])
def ejecutar_reposicion_automatica(actualizar_catalogos: bool = True):
    from reposicion_automatica import ejecutar_ciclo

    return ejecutar_pedido_venta(ejecutar_ciclo, actualizar_catalogos)


@app.get("/reposicion-automatica/alertas", dependencies=[Depends(exigir_compras)])
def ver_alertas_reposicion(
    activas: bool = True,
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 10,
):
    from reposicion_automatica import listar_alertas

    return ejecutar_pedido_venta(listar_alertas, activas, pagina, limite)


from modelos import ReposicionEmergencia


@app.put(
    "/productos/{id}/reposiciones-emergencia/{referencia}",
    dependencies=[Depends(exigir_compras)],
)
def recibir_reposicion_emergencia(
    id: Annotated[int, Path(gt=0, le=2**63 - 1)],
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    datos: ReposicionEmergencia,
    usuario: str = Depends(exigir_compras),
):
    from reposicion_emergencia import recibir

    return ejecutar_pedido_venta(
        recibir, id, referencia, datos.model_dump(mode="json"), usuario
    )


from modelos import CompraEmergencia, AdjuntoComprobante


@app.put(
    "/reposiciones-emergencia/{referencia}", dependencies=[Depends(exigir_compras)]
)
def registrar_compra_emergencia(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    datos: CompraEmergencia,
    usuario: str = Depends(exigir_compras),
):
    from reposicion_emergencia import recibir_compra

    return ejecutar_pedido_venta(
        recibir_compra, referencia, datos.model_dump(mode="json"), usuario
    )


@app.get("/reposiciones-emergencia", dependencies=[Depends(exigir_compras)])
def listar_compras_emergencia(
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 10,
    adjunto_pendiente: bool = False,
):
    from reposicion_emergencia import listar

    return ejecutar_pedido_venta(listar, pagina, limite, adjunto_pendiente)


@app.get(
    "/reposiciones-emergencia/{referencia}", dependencies=[Depends(exigir_compras)]
)
def ver_compra_emergencia(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
):
    from reposicion_emergencia import consultar

    return ejecutar_pedido_venta(consultar, referencia)


@app.put(
    "/reposiciones-emergencia/{referencia}/comprobante",
    dependencies=[Depends(exigir_compras)],
)
def adjuntar_comprobante_emergencia(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    datos: AdjuntoComprobante,
    usuario: str = Depends(exigir_compras),
):
    from reposicion_emergencia import adjuntar

    return ejecutar_pedido_venta(adjuntar, referencia, datos.model_dump(), usuario)


@app.get(
    "/reposiciones-emergencia/{referencia}/comprobante",
    dependencies=[Depends(exigir_compras)],
)
def descargar_comprobante_emergencia(
    referencia: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
):
    from fastapi.responses import Response
    from reposicion_emergencia import descargar

    archivo = ejecutar_pedido_venta(descargar, referencia)
    extension = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}[
        archivo["mime"]
    ]
    return Response(
        archivo["contenido"],
        media_type=archivo["mime"],
        headers={
            "Content-Disposition": f'attachment; filename="comprobante-{referencia}.{extension}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@app.get("/fondo-emergencias", dependencies=[Depends(exigir_compras)])
def ver_fondo_emergencias(
    pagina: Annotated[int, Query(ge=1)] = 1,
    limite: Annotated[int, Query(ge=1, le=50)] = 10,
):
    from reposicion_emergencia import consultar_fondo

    return ejecutar_pedido_venta(consultar_fondo, pagina, limite)


from rutas_usuarios import router as rutas_cuentas

app.include_router(rutas_cuentas)

from rutas_respaldos import router as rutas_copias

app.include_router(rutas_copias)

from rutas_abastecimiento import router as rutas_abastecimiento

app.include_router(rutas_abastecimiento)

from rutas_operacion_ventas import router as rutas_operacion_ventas

app.include_router(rutas_operacion_ventas)

from rutas_catalogo_cuentas import router as rutas_catalogo_cuentas

app.include_router(rutas_catalogo_cuentas)


from interfaz_web import instalar as instalar_interfaz_web

instalar_interfaz_web(app)

from rutas_reposicion_simulada import router as rutas_simulacion

app.include_router(rutas_simulacion)
