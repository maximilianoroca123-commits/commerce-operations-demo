"""Bilingual demonstration receipts derived from completed sales."""

from mensajes import etiqueta

from html import escape

from pedidos_venta import ConflictoEntregaError, consultar


def importe(valor, idioma="es"):
    if idioma == "en":
        return "ARS " + format(valor, ",") + ".00"
    return "$ " + format(valor, ",").replace(",", ".") + ",00"


def generar_ticket(conectar_db, pedido_id, idioma="es"):
    if idioma not in ("es", "en"):
        raise ValueError("Idioma no admitido")

    def t(es, en):
        return en if idioma == "en" else es

    def money(value):
        return importe(value, idioma)

    states = {
        "aprobado": "Approved",
        "pendiente": "Pending",
        "preparando": "Preparing",
        "listo": "Ready",
        "enviado": "Shipped",
        "entregado": "Delivered",
        "cancelado": "Cancelled",
        "revision": "Under review",
        "pendiente_pago": "Awaiting payment",
        "vigente": "No returns",
        "devuelta": "Fully returned",
        "devuelta_parcial": "Partially returned",
        "directa": "Direct",
        "qr": "QR",
        "online": "Online",
        "presencial": "In person",
        "local": "In store",
        "retiro": "Store pickup",
        "envio": "Shipping",
        "efectivo": "Cash",
        "qr_demo": "Simulated QR",
    }

    def status(value):
        return states.get(value, value) if idioma == "en" else etiqueta(value)

    def raw_status(value):
        return states.get(value, value) if idioma == "en" else value

    pedido = consultar(conectar_db, pedido_id)
    if pedido["estado_pago"] != "aprobado":
        raise ConflictoEntregaError("El ticket requiere una venta con pago aprobado")
    detalle_efectivo = ""
    if pedido["efectivo"]:
        detalle_efectivo = (
            f"<p>{t('Efectivo recibido: ','Cash received: ')}{money(pedido['efectivo']['recibido'])}</p>"
            f"<p>{t('Vuelto: ','Change: ')}{money(pedido['efectivo']['vuelto'])}</p>"
        )
    filas = []
    for producto in pedido["productos"]:
        subtotal = producto["cantidad"] * producto["precio_unitario"]
        filas.append(
            "<tr>"
            f'<td>{escape(producto["nombre"])}</td>'
            f'<td>{producto["cantidad"]}</td>'
            f'<td>{money(producto["precio_unitario"])}</td>'
            f"<td>{money(subtotal)}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="{idioma}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t('Ticket de demostración · Venta ','Demonstration receipt · Sale ')}{pedido["id"]}</title>
<style>
body {{ font-family: Arial, sans-serif; color: #222; margin: 32px auto; padding: 0 20px; max-width: 720px; }}
h1 {{ font-size: 24px; }}
dl {{ display: grid; grid-template-columns: 140px 1fr; gap: 7px; }}
dt {{ font-weight: bold; }} dd {{ margin: 0; overflow-wrap: anywhere; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 24px; }}
th, td {{ border-bottom: 1px solid #ddd; padding: 10px 5px; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
.total {{ text-align: right; font-size: 22px; font-weight: bold; }}
footer {{ font-size: 13px; margin-top: 32px; }}
@media print {{ body {{ margin: 0; max-width: none; }} }}
</style>
</head>
<body>
<h1>{t('Ticket de demostración','Demonstration receipt')}</h1>
<dl>
<dt>{t('Pedido de venta','Sales order')}</dt><dd>{pedido["id"]}</dd>
<dt>{t('Cliente','Customer')}</dt><dd>{t('Cliente registrado · ID ','Registered customer · ID ')+str(pedido['cliente_id']) if pedido.get('cliente_id') else t('Consumidor sin identificar','Unidentified customer')}</dd>
<dt>{t('Referencia','Reference')}</dt><dd>{escape(pedido["referencia"])}</dd>
<dt>{t('Origen','Origin')}</dt><dd>{escape(raw_status(pedido["origen"]))}</dd>
<dt>{t('Canal y modalidad','Channel and delivery method')}</dt><dd>{escape(raw_status(pedido["canal"]))} · {escape(raw_status(pedido["modalidad"]))}</dd>
<dt>{t('Fecha del pedido','Order date')}</dt><dd>{escape(pedido["creado_en"])} (UTC)</dd>
<dt>{t('Pago','Payment')}</dt><dd>{escape(status(pedido["estado_pago"]))}</dd>
<dt>{t('Medio de pago','Payment method')}</dt><dd>{escape(raw_status(pedido["medio_pago"]))}</dd>
<dt>{t('Entrega','Delivery')}</dt><dd>{escape(status(pedido["estado_entrega"]))}</dd>
</dl>
<table>
<thead><tr><th>{t('Producto','Product')}</th><th>{t('Unidades','Units')}</th><th>{t('Precio unitario','Unit price')}</th><th>{t('Subtotal','Subtotal')}</th></tr></thead>
<tbody>{"".join(filas)}</tbody>
</table>
<p class="total">{t('Total ARS ','Total ')}{money(pedido["total"])}</p>
{detalle_efectivo}
<p>{t('Estado comercial: ','Commercial status: ')}{escape(status(pedido["devoluciones"]["estado_comercial"]))}</p>
<p>{t('Devoluciones registradas: ','Recorded returns: ')}{money(pedido["devoluciones"]["importe_devoluciones"])}</p>
<p>{t('Dinero reintegrado: ','Money refunded: ')}{money(pedido["devoluciones"]["importe_reintegrado"])}</p>
<p>{t('Pendiente de reintegrar: ','Outstanding refund: ')}{money(pedido["devoluciones"]["importe_por_reintegrar"])}</p>
<footer>{t('Comprobante de una operación de prueba. Sin validez fiscal.','Receipt for a demonstration transaction. Not a tax invoice.')}</footer>
</body>
</html>"""
