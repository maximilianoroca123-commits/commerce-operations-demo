"""Optional console client for demonstration QR purchases."""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from uuid import uuid4

import requests

from lector_qr import leer_compra_qr
from menu_api import URL_API_LOCAL
from mensajes import error_respuesta, etiqueta


class CompraQR:
    def __init__(self, ventana, sesion):
        self.ventana = ventana
        self.sesion = sesion
        self.compra = None
        self.referencia = None
        ventana.title("Compra simulada por QR")
        ventana.minsize(470, 280)

        panel = ttk.Frame(ventana, padding=24)
        panel.pack(fill="both", expand=True)
        ttk.Label(
            panel, text="Compra simulada por QR", font=("Segoe UI", 16, "bold")
        ).pack(anchor="w")
        acceso = ttk.Frame(panel)
        acceso.pack(fill="x", pady=(14, 12))
        ttk.Label(acceso, text="Contraseña de consulta").pack(side="left")
        self.clave = ttk.Entry(acceso, show="*")
        self.clave.pack(side="left", fill="x", expand=True, padx=8)
        self.clave.bind("<Return>", lambda _: self.iniciar_sesion())
        self.entrar = ttk.Button(
            acceso, text="Iniciar sesión", command=self.iniciar_sesion
        )
        self.entrar.pack(side="left")

        acciones = ttk.Frame(panel)
        acciones.pack(fill="x")
        self.cargar = ttk.Button(
            acciones,
            text="Leer QR desde imagen",
            command=self.cargar_imagen,
            state="disabled",
        )
        self.cargar.pack(side="left")
        self.confirmar = ttk.Button(
            acciones,
            text="Confirmar compra",
            command=self.confirmar_compra,
            state="disabled",
        )
        self.confirmar.pack(side="left", padx=8)
        self.cancelar = ttk.Button(
            acciones,
            text="Cancelar selección",
            command=self.cancelar_compra,
            state="disabled",
        )
        self.cancelar.pack(side="left")
        self.detalle = tk.StringVar(value="")
        ttk.Label(panel, textvariable=self.detalle, wraplength=460).pack(
            anchor="w", pady=14
        )
        self.estado = tk.StringVar(
            value="Iniciá sesión como consulta para elegir una imagen."
        )
        ttk.Label(panel, textvariable=self.estado, wraplength=460).pack(anchor="w")
        self.clave.focus_set()

    def iniciar_sesion(self):
        self.sesion.auth = ("consulta", self.clave.get())
        try:
            respuesta = self.sesion.get(f"{URL_API_LOCAL}/sesion", timeout=5)
        except requests.RequestException:
            self.estado.set("No se pudo conectar con la API local.")
            return
        if respuesta.status_code != 200:
            self.estado.set(error_respuesta(respuesta))
            return
        self.clave.delete(0, tk.END)
        self.clave.state(["disabled"])
        self.entrar.state(["disabled"])
        self.cargar.state(["!disabled"])
        self.estado.set("Elegí una imagen con un QR de compra de la demo.")

    def limpiar_seleccion(self):
        self.compra = None
        self.referencia = None
        self.detalle.set("")
        self.confirmar.configure(text="Confirmar compra", state="disabled")
        self.cancelar.state(["disabled"])
        self.cargar.state(["!disabled"])

    def cargar_imagen(self):
        ruta = filedialog.askopenfilename(
            parent=self.ventana, filetypes=[("Imágenes", "*.png *.jpg *.jpeg")]
        )
        if not ruta:
            return
        self.limpiar_seleccion()
        try:
            compra = leer_compra_qr(ruta)
            respuesta = self.sesion.get(
                f'{URL_API_LOCAL}/productos/{compra["producto_id"]}', timeout=5
            )
        except ValueError as error:
            self.estado.set(str(error))
            return
        except requests.RequestException:
            self.estado.set("No se pudo consultar el producto en la API.")
            return
        if respuesta.status_code != 200:
            self.estado.set(
                "El producto del QR no existe."
                if respuesta.status_code == 404
                else f"No se pudo consultar el producto (HTTP {respuesta.status_code})."
            )
            return
        producto = respuesta.json()
        self.compra = compra
        self.detalle.set(
            f'{producto["nombre"]} (ID {producto["id"]}) · {compra["cantidad"]} unidades\n'
            f'Precio unitario: ${producto["precio"]} · Stock al consultar: {producto["stock"]}'
        )
        self.estado.set("Revisá la cantidad antes de confirmar.")
        self.confirmar.state(["!disabled"])
        self.cancelar.state(["!disabled"])

    def cancelar_compra(self):
        self.limpiar_seleccion()
        self.estado.set("Compra cancelada antes de enviarla.")

    def confirmar_compra(self):
        if self.referencia is None:
            if not messagebox.askyesno(
                "Confirmar compra simulada", self.detalle.get(), parent=self.ventana
            ):
                self.cancelar_compra()
                return
            self.referencia = uuid4().hex
        try:
            respuesta = self.sesion.put(
                f"{URL_API_LOCAL}/ventas/{self.referencia}", json=self.compra, timeout=5
            )
        except requests.RequestException:
            self.pedir_reintento()
            return
        if respuesta.status_code >= 500:
            self.pedir_reintento()
            return
        if respuesta.status_code != 200:
            mensaje = error_respuesta(respuesta)
            self.limpiar_seleccion()
            self.estado.set(mensaje)
            return
        venta = respuesta.json()["venta"]
        self.limpiar_seleccion()
        self.estado.set(
            f'Compra registrada. Stock al registrar esta compra: {venta["stock_restante"]}.\n'
            f'Referencia: {venta["referencia"]}'
        )

    def pedir_reintento(self):
        self.cargar.state(["disabled"])
        self.cancelar.state(["disabled"])
        self.confirmar.configure(text="Reintentar compra")
        self.estado.set(
            f"La API no confirmó el resultado. Reintentá con la misma referencia: {self.referencia}"
        )


def main():
    ventana = tk.Tk()
    with requests.Session() as sesion:
        CompraQR(ventana, sesion)
        ventana.mainloop()


if __name__ == "__main__":
    main()
