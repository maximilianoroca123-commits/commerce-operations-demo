"""Regression tests: mensajes."""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch
from mensajes import error_respuesta, pedir_fecha_compra
from menu_api import mostrar_compra_emergencia, solicitar_compras
import requests


class Mensajes(unittest.TestCase):
    def respuesta(self, codigo, detalle):
        r = Mock(status_code=codigo)
        r.json.return_value = {"detail": detalle}
        return r

    def test_fecha_invalida_repite_solo_ese_campo(self):
        with patch(
            "builtins.input",
            side_effect=["Fecha de compra", "2999-01-01", "2020-01-01"],
        ), redirect_stdout(io.StringIO()) as salida:
            self.assertEqual(pedir_fecha_compra(), "2020-01-01")
        self.assertIn("Fecha inválida", salida.getvalue())
        self.assertIn("posterior a hoy", salida.getvalue())

    def test_error_identifica_linea_y_campo_sin_exponer_valor(self):
        r = self.respuesta(
            422,
            [
                {
                    "loc": ["body", "productos", 1, "cantidad"],
                    "type": "greater_than",
                    "ctx": {"gt": 0},
                    "input": "secreto",
                },
                {"loc": ["body", "fecha_compra"], "type": "date_from_datetime_parsing"},
            ],
        )
        texto = error_respuesta(r)
        self.assertIn("línea 2: Cantidad", texto)
        self.assertIn("Fecha de compra", texto)
        self.assertNotIn("secreto", texto)

    def test_historial_no_se_presenta_como_faltante_actual(self):
        r = {
            "total_centavos": 540000,
            "referencia": "compra-1",
            "fondo": "emergencias_reposicion",
            "empleado": "Ana",
            "registrado_por": "compras",
            "estado_documentacion": "adjunto_pendiente",
            "situacion_al_registrar": [
                {
                    "producto_id": 1,
                    "estado": "requiere_revision",
                    "faltante_objetivo": 3,
                }
            ],
        }
        with redirect_stdout(io.StringIO()) as salida:
            mostrar_compra_emergencia(r)
        texto = salida.getvalue()
        self.assertIn("histórica", texto)
        self.assertIn("no es el stock actual", texto)
        self.assertIn("ya están registrados", texto)
        self.assertNotIn("requiere_revision", texto)

    def test_error_servidor_y_red_no_prometen_que_no_hubo_cambios(self):
        r = self.respuesta(500, "error interno")
        self.assertIn("misma referencia", error_respuesta(r))
        sesion = Mock()
        sesion.request.side_effect = requests.Timeout()
        with redirect_stdout(io.StringIO()) as salida:
            self.assertIsNone(solicitar_compras(sesion, "PUT", "/prueba"))
        self.assertIn("misma referencia", salida.getvalue())

    def test_respuesta_no_json_y_permisos(self):
        r = Mock(status_code=502)
        r.json.side_effect = ValueError()
        self.assertIn("no pudo confirmar", error_respuesta(r))
        self.assertIn(
            "no tiene permiso", error_respuesta(self.respuesta(403, "Forbidden"))
        )
        self.assertIn(
            "contraseña", error_respuesta(self.respuesta(401, "Unauthorized"))
        )


if __name__ == "__main__":
    unittest.main()
