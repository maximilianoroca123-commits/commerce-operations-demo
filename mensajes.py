"""Console-facing labels, date input and HTTP error presentation."""

from datetime import date, datetime, timedelta, timezone

ESTADOS = {
    "retiro": "Retiro en el local",
    "envio": "Envío a domicilio",
    "local": "Entrega en el local",
    "pendiente_pago": "Pendiente de pago",
    "stock_suficiente": "Stock suficiente",
    "stock_en_alerta": "Stock cerca del mínimo",
    "requiere_revision": "Reposición pendiente de resolver",
    "pedido_pendiente": "Hay pedidos por recibir",
    "sin_oferta_elegible": "No hay ofertas que cumplan las condiciones",
    "desactivada": "Regla desactivada",
    "pedido_generado": "Pedido de reposición generado",
    "pedidos_generados": "Pedidos de reposición generados",
    "sin_regla": "Sin regla de reposición",
    "pendiente": "Pendiente",
    "parcial": "Recibido parcialmente",
    "recibido": "Recibido por completo",
    "cancelado": "Cancelado",
    "cerrado_incompleto": "Cerrado con unidades sin recibir",
    "aprobado": "Aprobado",
    "rechazado": "Rechazado",
    "procesando": "En procesamiento",
    "preparando": "En preparación",
    "listo": "Listo para entregar",
    "enviado": "En camino",
    "entregado": "Entregado",
    "no_corresponde": "No corresponde",
    "confirmado": "Confirmado",
    "fallido": "Fallido",
    "vigente": "Vigente",
    "devuelta_parcial": "Devuelta parcialmente",
    "devuelta": "Devuelta por completo",
    "reposicion_sugerida": "Reposición sugerida (modo aviso)",
    "cobertura_insuficiente": "Cantidad disponible en proveedores insuficiente",
    "catalogo_no_confiable": "Catálogos desactualizados o inaccesibles",
    "sin_ofertas": "Sin ofertas disponibles",
    "limite_precio": "Se supera el precio autorizado",
    "limite_unidades": "Se supera la cantidad autorizada",
    "pedido_demorado": "Pedido demorado",
    "pedido_cancelado": "Pedido automático cancelado",
    "exceso_proyectado": "El stock previsto supera el objetivo",
    "cerca_del_minimo": "Stock cerca del mínimo",
    "reposicion_emergencia": "Reposición manual de emergencia",
    "ajuste_manual": "Ajuste manual",
    "venta_qr": "Venta por QR",
    "venta_efectivo": "Venta en efectivo",
    "venta_directa": "Venta directa",
    "correccion_remito": "Corrección de remito",
    "saldo_inicial": "Stock inicial",
}
CAMPOS = {
    "temporal": "Contraseña temporal",
    "usuario": "Nombre de usuario",
    "clave": "Contraseña",
    "actual": "Contraseña actual",
    "nueva": "Nueva contraseña",
    "correo": "Correo",
    "apellido": "Apellido",
    "cliente": "Ficha del cliente",
    "proveedor": "Proveedor asociado",
    "rol": "Rol",
    "direccion_entrega": "Dirección de entrega",
    "fecha_compra": "Fecha de compra",
    "empleado": "Nombre del empleado",
    "origen": "Lugar de compra",
    "motivo": "Motivo",
    "producto_id": "ID del producto",
    "cantidad": "Cantidad",
    "precio": "Precio",
    "stock": "Stock",
    "costo_unitario_centavos": "Costo unitario en centavos",
    "numero_comprobante": "Número de comprobante",
    "tipo_comprobante": "Tipo de comprobante",
    "referencia": "Referencia",
    "nombre": "Nombre",
    "categoria": "Categoría",
    "contenido_base64": "Contenido del archivo",
    "recibido": "Dinero recibido",
    "minimo": "Stock mínimo",
    "objetivo": "Stock objetivo",
    "alertar_desde": "Nivel de alerta",
}


def etiqueta(valor):
    return ESTADOS.get(valor, str(valor).replace("_", " ").capitalize())


def error_respuesta(respuesta):
    try:
        detalle = respuesta.json().get("detail")
    except (ValueError, AttributeError):
        detalle = None
    codigo = respuesta.status_code
    if codigo == 401:
        return "Usuario o contraseña incorrectos. Volvé a iniciar sesión."
    if codigo == 403:
        if isinstance(detalle, str) and detalle.startswith(
            "Debés cambiar tu contraseña temporal"
        ):
            return detalle
        return (
            "Tu cuenta no tiene permiso para esta operación. Consultá al administrador."
        )
    if codigo >= 500:
        return (
            "El servidor no pudo confirmar el resultado. Consultá el registro antes de volver a cargarlo. "
            "Si reintentás, conservá la misma referencia y los mismos datos para evitar duplicados."
        )
    if isinstance(detalle, list):
        errores = []
        for dato in detalle:
            if not isinstance(dato, dict):
                continue
            ruta = [
                x for x in dato.get("loc", []) if x not in ("body", "query", "path")
            ]
            campo = (
                CAMPOS.get(str(ruta[-1]), etiqueta(str(ruta[-1])))
                if ruta
                else "Datos ingresados"
            )
            fila = next((x + 1 for x in ruta if isinstance(x, int)), None)
            if fila:
                campo = f"Producto en la línea {fila}: {campo}"
            tipo = dato.get("type", "")
            contexto = dato.get("ctx") or {}
            if "date" in tipo:
                explicacion = (
                    "Ingresá una fecha válida como año-mes-día, por ejemplo 2026-11-18."
                )
            elif tipo == "missing":
                explicacion = "Este dato es obligatorio."
            elif tipo.startswith("int"):
                explicacion = "Ingresá un número entero, sin letras ni decimales."
            elif tipo == "greater_than":
                explicacion = f"El valor debe ser mayor que {contexto.get('gt', 0)}."
            elif tipo == "greater_than_equal":
                explicacion = f"El valor mínimo es {contexto.get('ge')}."
            elif tipo == "less_than_equal":
                explicacion = f"El valor máximo es {contexto.get('le')}."
            elif tipo == "string_too_short":
                explicacion = "Completá este dato; no puede quedar vacío."
            elif tipo == "string_too_long":
                explicacion = (
                    f"Usá como máximo {contexto.get('max_length')} caracteres."
                )
            elif tipo in ("literal_error", "enum"):
                explicacion = f"Elegí una de las opciones indicadas: {contexto.get('expected', '')}."
            elif tipo == "string_pattern_mismatch":
                explicacion = "Revisá el formato indicado. Las referencias admiten hasta 64 letras, números, guiones y guiones bajos."
            elif tipo == "value_error":
                explicacion = dato.get("msg", "Revisá este dato.").removeprefix(
                    "Value error, "
                )
            else:
                explicacion = (
                    "Revisá el formato y los límites indicados para este dato."
                )
            errores.append(f"- {campo}: {explicacion}")
        return "No se aceptaron los datos:\n" + "\n".join(errores)
    if isinstance(detalle, str):
        return detalle
    return {
        404: "No se encontró el registro o la dirección solicitada. Revisá el ID o la referencia; si actualizaste el programa, reiniciá el servidor.",
        409: "La operación entra en conflicto con el registro existente. Consultalo antes de modificar los datos.",
        422: "Revisá los datos obligatorios, sus formatos y los límites indicados.",
    }.get(codigo, "No se pudo completar la solicitud. Consultá al administrador.")


def pedir_fecha_compra():
    while True:
        texto = input("Fecha de compra (año-mes-día, ej. 2026-11-18): ").strip()
        try:
            fecha = date.fromisoformat(texto)
            if fecha.isoformat() != texto:
                raise ValueError
        except ValueError:
            print(
                "Fecha inválida. Escribí año-mes-día con guiones; no copies la descripción del campo."
            )
            continue
        if fecha > datetime.now(timezone(timedelta(hours=-3))).date():
            print(
                "La fecha de compra no puede ser posterior a hoy (hora de Argentina)."
            )
            continue
        return texto
