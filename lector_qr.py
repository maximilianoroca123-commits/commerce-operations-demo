"""Optional decoding and validation of demonstration purchase QR images."""

import json
from pathlib import Path

import cv2
import numpy as np


def leer_compra_qr(ruta):
    try:
        datos = np.frombuffer(Path(ruta).read_bytes(), dtype=np.uint8)
        imagen = cv2.imdecode(datos, cv2.IMREAD_GRAYSCALE) if datos.size else None
        if imagen is None:
            raise ValueError("No se pudo abrir la imagen.")
        texto, _, _ = cv2.QRCodeDetector().detectAndDecode(imagen)
    except (OSError, cv2.error) as error:
        raise ValueError("No se pudo leer la imagen.") from error
    if not texto:
        raise ValueError("No se encontró un QR legible en la imagen.")

    mensaje = "El QR no contiene los datos de una compra de esta demo."
    try:
        compra = json.loads(texto)
    except ValueError as error:
        raise ValueError(mensaje) from error
    if not isinstance(compra, dict) or set(compra) != {
        "tipo",
        "producto_id",
        "cantidad",
    }:
        raise ValueError(mensaje)
    if compra["tipo"] != "compra_demo" or any(
        type(compra[campo]) is not int or not 1 <= compra[campo] <= 2**63 - 1
        for campo in ("producto_id", "cantidad")
    ):
        raise ValueError(mensaje)
    return {"producto_id": compra["producto_id"], "cantidad": compra["cantidad"]}
