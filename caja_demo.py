"""Optional console client for simulated payment and QR workflows."""

import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from uuid import uuid4

import cv2
import numpy as np
import requests

from menu_api import URL_API_LOCAL
from mensajes import error_respuesta, etiqueta


def guardar_qr(referencia, carpeta):
    carpeta.mkdir(exist_ok=True)
    ruta = carpeta / f"{referencia}.png"
    texto = "cobro-demo:" + referencia
    for version in (0, 5, 6):
        parametros = cv2.QRCodeEncoder_Params()
        parametros.version = version
        imagen = cv2.QRCodeEncoder_create(parametros).encode(texto)
        imagen = cv2.copyMakeBorder(imagen, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
        imagen = cv2.resize(imagen, None, fx=9, fy=9, interpolation=cv2.INTER_NEAREST)
        if cv2.QRCodeDetector().detectAndDecode(imagen)[0] == texto:
            ruta.write_bytes(cv2.imencode(".png", imagen)[1].tobytes())
            break
    else:
        raise ValueError("No se pudo generar un QR legible. Volvé a intentarlo.")
    return ruta


def leer_cobro(ruta):
    try:
        imagen = cv2.imdecode(
            np.frombuffer(Path(ruta).read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE
        )
        if imagen is None:
            raise ValueError("No se pudo abrir la imagen.")
        texto, _, _ = cv2.QRCodeDetector().detectAndDecode(imagen)
        datos = {"tipo": "cobro_demo", "referencia": texto.removeprefix("cobro-demo:")}
        if not texto.startswith("cobro-demo:"):
            raise ValueError("Formato de QR inválido")
    except (OSError, cv2.error, ValueError) as error:
        raise ValueError(
            "La imagen debe contener un QR de cobro de esta demo."
        ) from error
    if (
        not isinstance(datos, dict)
        or set(datos) != {"tipo", "referencia"}
        or datos["tipo"] != "cobro_demo"
        or not isinstance(datos["referencia"], str)
        or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", datos["referencia"]) is None
    ):
        raise ValueError("El QR no corresponde a un cobro de esta demo.")
    return datos["referencia"]


class ResultadoIncierto(ValueError):
    pass


class CajaDemo:
    def __init__(self, ventana, sesion):
        self.ventana = ventana
        self.sesion = sesion
        self.lineas = {}
        self.referencia = None
        self.foto = None
        ventana.title("Caja · cobro simulado")
        panel = ttk.Frame(ventana, padding=20)
        panel.pack(fill="both", expand=True)
        ttk.Label(
            panel, text="Caja · cobro simulado", font=("Segoe UI", 16, "bold")
        ).pack(anchor="w")
        self.tabla = ttk.Treeview(
            panel, columns=("nombre", "cantidad", "precio"), show="headings", height=6
        )
        for campo, titulo in (
            ("nombre", "Producto"),
            ("cantidad", "Cantidad"),
            ("precio", "Precio unitario"),
        ):
            self.tabla.heading(campo, text=titulo)
            self.tabla.column(campo, width=160)
        self.tabla.pack(fill="both", expand=True, pady=12)
        self.total = tk.StringVar(value="Total estimado: $0")
        ttk.Label(panel, textvariable=self.total).pack(anchor="w")
        botones = ttk.Frame(panel)
        botones.pack(fill="x", pady=10)
        self.agregar = ttk.Button(
            botones, text="Agregar por ID", command=self.agregar_producto
        )
        self.agregar.pack(side="left")
        self.quitar = ttk.Button(
            botones, text="Quitar seleccionado", command=self.quitar_producto
        )
        self.quitar.pack(side="left", padx=5)
        self.cobrar = ttk.Button(botones, text="Generar QR", command=self.generar_cobro)
        self.cobrar.pack(side="left")
        ttk.Button(
            panel, text="Simular billetera · abrir QR", command=self.abrir_billetera
        ).pack(anchor="w")
        self.qr = ttk.Label(panel)
        self.qr.pack(pady=8)
        self.estado = tk.StringVar(value="Agregá los productos que pasan por caja.")
        ttk.Label(panel, textvariable=self.estado, wraplength=540).pack(anchor="w")
        self.billetera = None

    def pedir_api(self, metodo, ruta, datos=None):
        try:
            respuesta = self.sesion.request(
                metodo, URL_API_LOCAL + ruta, json=datos, timeout=5
            )
        except requests.RequestException:
            raise ResultadoIncierto(
                "No se pudo confirmar el resultado. Reintentá la misma operación."
            ) from None
        if respuesta.status_code != 200:
            if respuesta.status_code >= 500:
                raise ResultadoIncierto(
                    "La API no confirmó el resultado. Reintentá la misma operación."
                )
            raise ValueError(error_respuesta(respuesta))
        return respuesta.json()

    def refrescar(self):
        self.tabla.delete(*self.tabla.get_children())
        total = 0
        for identificador, producto in self.lineas.items():
            self.tabla.insert(
                "",
                "end",
                iid=str(identificador),
                values=(
                    producto["nombre"],
                    producto["cantidad"],
                    f'${producto["precio"]}',
                ),
            )
            total += producto["cantidad"] * producto["precio"]
        self.total.set(f"Total estimado: ${total}")

    def agregar_producto(self):
        identificador = simpledialog.askinteger(
            "Producto", "ID del producto:", minvalue=1, parent=self.ventana
        )
        if identificador is None:
            return
        cantidad = simpledialog.askinteger(
            "Cantidad", "Unidades:", minvalue=1, parent=self.ventana
        )
        if cantidad is None:
            return
        try:
            producto = self.pedir_api("GET", f"/productos/{identificador}")
        except ValueError as error:
            self.estado.set(str(error))
            return
        anterior = self.lineas.get(identificador, {}).get("cantidad", 0)
        self.lineas[identificador] = {**producto, "cantidad": anterior + cantidad}
        self.refrescar()

    def quitar_producto(self):
        for seleccionado in self.tabla.selection():
            del self.lineas[int(seleccionado)]
        self.refrescar()

    def generar_cobro(self):
        if not self.lineas:
            self.estado.set("Agregá al menos un producto.")
            return
        if self.referencia is None:
            self.referencia = uuid4().hex

            self.agregar.state(["disabled"])
            self.quitar.state(["disabled"])
        try:
            cobro = self.pedir_api(
                "PUT",
                f"/cobros-demo/{self.referencia}",
                {
                    "productos": [
                        {"producto_id": id, "cantidad": p["cantidad"]}
                        for id, p in self.lineas.items()
                    ],
                },
            )
            ruta = guardar_qr(
                self.referencia, Path(__file__).resolve().parent / "cobros_qr"
            )
            self.foto = tk.PhotoImage(file=str(ruta))
            self.qr.configure(image=self.foto)
            self.total.set(f'Total del cobro: ${cobro["total"]}')
            self.estado.set(
                f"Cobro {self.referencia} pendiente. QR guardado en cobros_qr."
            )
        except ResultadoIncierto as error:
            self.estado.set(str(error))
        except ValueError as error:
            self.referencia = None
            self.agregar.state(["!disabled"])
            self.quitar.state(["!disabled"])
            self.estado.set(str(error))
        except (OSError, cv2.error) as error:
            self.estado.set(
                f"No se pudo guardar el QR. Volvé a pulsar Generar QR. {error}"
            )

    def abrir_billetera(self):
        ruta = filedialog.askopenfilename(
            parent=self.ventana,
            initialdir=Path(__file__).resolve().parent / "cobros_qr",
            filetypes=[("Imagen PNG", "*.png")],
        )
        if not ruta:
            return
        try:
            referencia = leer_cobro(ruta)
            cobro = self.pedir_api("GET", f"/cobros-demo/{referencia}")
        except ValueError as error:
            self.estado.set(str(error))
            return
        if self.billetera is not None and self.billetera.winfo_exists():
            self.billetera.destroy()
        self.billetera = tk.Toplevel(self.ventana)
        self.billetera.title("Billetera de prueba")
        panel = ttk.Frame(self.billetera, padding=20)
        panel.pack()
        ttk.Label(
            panel,
            text=f'Cobro {referencia}\nTotal: ${cobro["total"]}\nEstado: {etiqueta(cobro["estado"])}',
            wraplength=420,
        ).pack(pady=10)
        ttk.Button(
            panel,
            text="Simular pago aprobado",
            command=lambda: self.resolver_pago(referencia, "aprobado"),
        ).pack(fill="x", pady=4)
        ttk.Button(
            panel,
            text="Simular pago rechazado",
            command=lambda: self.resolver_pago(referencia, "rechazado"),
        ).pack(fill="x", pady=4)

    def resolver_pago(self, referencia, estado):
        try:
            cobro = self.pedir_api(
                "PUT", f"/cobros-demo/{referencia}/pago", {"estado": estado}
            )
        except ValueError as error:
            messagebox.showerror(
                "Resultado del cobro", str(error), parent=self.billetera
            )
            return
        self.estado.set(
            f'Cobro {referencia}: {etiqueta(cobro["estado"])}. Total: ${cobro["total"]}.'
        )
        if referencia == self.referencia:
            self.referencia = None
            self.lineas.clear()
            self.refrescar()
            self.qr.configure(image="")
            self.agregar.state(["!disabled"])
            self.quitar.state(["!disabled"])
        self.billetera.destroy()


def main():
    ventana = tk.Tk()
    ventana.withdraw()
    with requests.Session() as sesion:
        usuario = simpledialog.askstring(
            "Caja de prueba",
            "Usuario del empleado o administrador (consulta solo para compatibilidad):",
            parent=ventana,
        )
        if not usuario:
            ventana.destroy()
            return
        clave = simpledialog.askstring(
            "Caja de prueba", "Contraseña:", show="*", parent=ventana
        )
        if clave is None:
            ventana.destroy()
            return
        sesion.auth = (usuario.strip(), clave)
        try:
            respuesta = sesion.get(f"{URL_API_LOCAL}/sesion", timeout=5)
            respuesta.raise_for_status()
            if respuesta.json().get("debe_cambiar_clave"):
                messagebox.showerror(
                    "Cambiar contraseña",
                    "Antes de usar la caja, ingresá a menu_api.py y cambiá tu contraseña temporal.",
                    parent=ventana,
                )
                ventana.destroy()
                return
            if (
                respuesta.json().get("rol_efectivo")
                not in ("empleado", "administrador")
                and usuario != "consulta"
            ):
                messagebox.showerror(
                    "Acceso a caja",
                    "La caja presencial corresponde al personal del negocio. Para comprar online usá el menú de cliente.",
                    parent=ventana,
                )
                ventana.destroy()
                return
        except requests.RequestException:
            messagebox.showerror(
                "Inicio de sesión",
                "No se pudo iniciar sesión. Revisá la contraseña y que el servidor esté encendido.",
                parent=ventana,
            )
            ventana.destroy()
            return
        ventana.deiconify()
        CajaDemo(ventana, sesion)
        ventana.mainloop()


if __name__ == "__main__":
    main()
